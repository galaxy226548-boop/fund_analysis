"""代表参数窗口 × 未来收益期限检验脚本。

这个脚本用于在任务 1 的热力图扫描之后，集中检查少数“有代表性”的
``m_n`` 参数窗口在不同未来收益期限下是否仍然成立。它刻意不修改
``consistency_fama_mac_regression.py`` 这样的核心回归脚本，而是在这里复用
任务 1 的输入面板、控制变量和 Fama-MacBeth 估计口径。

默认不会覆盖任何已有结果：每次正式运行都会在输出目录下新建一个时间戳子目录。

运行示例：

    .venv/bin/python D_analysis/scripts/run_representative_window_horizon_tests.py --help
    .venv/bin/python D_analysis/scripts/run_representative_window_horizon_tests.py --dry-run
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_PANEL_PATH = (
    PROJECT_ROOT / "A_data" / "output" / "panel_base_heatmap_m1_12_n1_12.parquet"
)
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "representative_window_horizon_tests"
)

# 用户报告中希望使用 future_return_* 作为展示口径；项目面板实际长期使用
# future_ret_*。脚本会优先寻找用户给定列名，找不到时再尝试项目别名。
REQUESTED_Y_COLUMNS = (
    "future_return_1m",
    "future_return_3m",
    "future_return_6m",
    "future_return_12m",
)
Y_COLUMN_ALIASES = {
    "future_return_1m": "future_ret_1m",
    "future_return_3m": "future_ret_3m",
    "future_return_6m": "future_ret_6m",
    "future_return_12m": "future_ret_12m",
}

PARAM_GROUPS = {
    "short_reversal_candidates": (
        (3, 6),
        (2, 6),
        (2, 7),
    ),
    "medium_continuation_candidates": (
        (6, 12),
        (6, 11),
        (5, 12),
        (1, 9),
    ),
    "neutral_controls": (
        (9, 6),
        (3, 4),
    ),
}

SAMPLE_GROUPS = {
    "Top33": {"flag_kind": "tercile", "filter_value": 3},
    "Mid33": {"flag_kind": "tercile", "filter_value": 2},
    "Bottom33": {"flag_kind": "tercile", "filter_value": 1},
    "Top50": {"flag_kind": "median", "filter_value": 2},
    "Bottom50": {"flag_kind": "median", "filter_value": -2},
}


@dataclass(frozen=True)
class ParamSpec:
    """记录一个代表性参数窗口。"""

    category: str
    m: int
    n: int

    @property
    def param_name(self) -> str:
        """返回报告里使用的短名称，例如 m3_n6。"""
        return f"m{self.m}_n{self.n}"

    @property
    def fac_col(self) -> str:
        """返回当前窗口的一致性指标列名。"""
        return f"FAC_rank_vol_m{self.m}_n{self.n}_pairwise1"

    @property
    def rank_mean_col(self) -> str:
        """返回当前窗口对应的 rank_mean 列名。"""
        return f"rank_mean_m{self.m}_n{self.n}_pairwise1"

    @property
    def tercile_flag_col(self) -> str:
        """返回当前窗口对应的三分组样本标记列名。"""
        return f"is_tercile_rank_mean_m{self.m}_n{self.n}_pairwise1"

    @property
    def median_flag_col(self) -> str:
        """返回当前窗口对应的中位数二分组样本标记列名。"""
        return f"is_median_rank_mean_m{self.m}_n{self.n}_pairwise1"


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="运行代表参数窗口 × 未来收益期限的 Fama-MacBeth 检验。"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_PANEL_PATH,
        help="包含 heatmap FAC、rank_mean、分组列和未来收益的 panel parquet。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="输出根目录；正式运行会在其下创建时间戳子目录。",
    )
    parser.add_argument(
        "--include-full-sample",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="是否加入 Full sample；默认加入。",
    )
    parser.add_argument(
        "--include-rank-mean",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "是否把当前窗口对应的 rank_mean 作为额外解释变量。默认关闭，"
            "以贴近任务 1 heatmap 回归的 FAC + controls 口径。"
        ),
    )
    parser.add_argument(
        "--params",
        nargs="+",
        default=None,
        help=(
            "只运行指定参数窗口，例如 --params m3_n6 m2_n7。"
            "默认运行全部代表窗口。"
        ),
    )
    parser.add_argument(
        "--sample-groups",
        nargs="+",
        choices=["Top33", "Mid33", "Bottom33", "Top50", "Bottom50", "Full sample"],
        default=None,
        help="只运行指定样本组；默认运行 Top33/Mid33/Bottom33，并按设置加入 Full sample。",
    )
    parser.add_argument(
        "--y-horizons",
        nargs="+",
        choices=list(REQUESTED_Y_COLUMNS),
        default=None,
        help=(
            "只运行指定未来收益期限，使用报告口径名称，例如 future_return_1m。"
            "默认运行 1m/3m/6m/12m。"
        ),
    )
    parser.add_argument(
        "--min-cross-section-n",
        type=int,
        default=None,
        help="覆盖 registry 中的最小月度横截面样本数；默认沿用 fm_baseline。",
    )
    parser.add_argument(
        "--newey-west-lag",
        type=int,
        default=None,
        help="覆盖 registry 中的 Newey-West 滞后阶数；默认沿用 fm_baseline。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查输入列并打印将运行的组合，不执行回归、不写结果。",
    )
    return parser.parse_args()


def resolve_project_path(path: Path) -> Path:
    """把相对路径解析到项目根目录下。"""
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_registry_config(key: str = "fm_baseline") -> dict[str, object]:
    """读取 registry 中的模型配置，复用 baseline 的控制变量和估计参数。"""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "representative_window_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(key)


def representative_specs() -> list[ParamSpec]:
    """展开三类代表参数窗口，保持报告中的固定顺序。"""
    specs: list[ParamSpec] = []
    for category, pairs in PARAM_GROUPS.items():
        for m, n in pairs:
            specs.append(ParamSpec(category=category, m=m, n=n))
    return specs


def filter_specs(specs: list[ParamSpec], requested_params: list[str] | None) -> list[ParamSpec]:
    """按命令行参数筛选代表窗口，用于小规模验证或局部重跑。"""
    if not requested_params:
        return specs

    by_name = {spec.param_name: spec for spec in specs}
    unknown = [name for name in requested_params if name not in by_name]
    if unknown:
        raise ValueError(
            f"未知参数窗口：{unknown}；可选值：{sorted(by_name)}"
        )
    return [by_name[name] for name in requested_params]


def select_sample_groups(
    requested_groups: list[str] | None,
    *,
    include_full_sample: bool,
) -> list[str]:
    """确定本次运行的样本组列表。"""
    default_groups = ["Top33", "Mid33", "Bottom33"]
    if include_full_sample:
        default_groups.append("Full sample")

    if not requested_groups:
        return default_groups

    groups = list(dict.fromkeys(requested_groups))
    if "Full sample" in groups and not include_full_sample:
        raise ValueError(
            "命令行指定了 Full sample，但 --no-include-full-sample 已关闭该样本组。"
        )
    return groups


def sample_group_flag_column(spec: ParamSpec, sample_group: str) -> str | None:
    """返回某个样本组需要使用的分组列；Full sample 不需要分组列。"""
    if sample_group == "Full sample":
        return None
    group_config = SAMPLE_GROUPS[sample_group]
    if group_config["flag_kind"] == "tercile":
        return spec.tercile_flag_col
    if group_config["flag_kind"] == "median":
        return spec.median_flag_col
    raise ValueError(f"未知样本组 flag_kind：{group_config}")


def read_parquet_columns(path: Path) -> list[str]:
    """只读取 parquet schema，不加载完整 800MB+ 数据。"""
    try:
        import pyarrow.parquet as pq

        return list(pq.ParquetFile(path).schema_arrow.names)
    except Exception:
        # 如果 pyarrow schema 读取失败，再退回 pandas 读取 0 行；这仍然不会加载全表。
        return list(pd.read_parquet(path, columns=[]).columns)


def resolve_y_columns(
    columns: Iterable[str],
    requested_y_columns: list[str] | None = None,
) -> dict[str, str]:
    """把报告口径的 Y 名称解析成面板中的实际列名。

    返回字典 key 是报告中展示的 ``future_return_*``，value 是实际读取的列名。
    如果某个期限两种命名都不存在，就一次性列出所有缺失列，避免静默跳过。
    """
    available = set(columns)
    resolved: dict[str, str] = {}
    missing: list[str] = []
    y_columns = tuple(requested_y_columns) if requested_y_columns else REQUESTED_Y_COLUMNS
    for requested in y_columns:
        alias = Y_COLUMN_ALIASES[requested]
        if requested in available:
            resolved[requested] = requested
        elif alias in available:
            resolved[requested] = alias
        else:
            missing.append(f"{requested}（也未找到别名 {alias}）")

    if missing:
        raise ValueError(
            "输入 panel 缺少以下未来收益列，脚本不会静默跳过：\n"
            + "\n".join(f"- {item}" for item in missing)
        )
    return resolved


def required_columns(
    specs: list[ParamSpec],
    y_map: dict[str, str],
    controls: list[str],
    *,
    include_rank_mean: bool,
    sample_groups: list[str],
) -> list[str]:
    """列出脚本运行必须用到的全部字段。"""
    columns = {
        "ifind_code",
        "month_date",
        "investment_type",
        *y_map.values(),
        *controls,
    }
    for requested_y, actual_y in y_map.items():
        # 样本内标记跟随实际项目列名：future_ret_6m -> is_insample_future_ret_6m。
        columns.add(f"is_insample_{actual_y}")
    for spec in specs:
        columns.add(spec.fac_col)
        for sample_group in sample_groups:
            flag_column = sample_group_flag_column(spec, sample_group)
            if flag_column is not None:
                columns.add(flag_column)
        if include_rank_mean:
            columns.add(spec.rank_mean_col)
    return sorted(columns)


def check_missing_columns(columns: Iterable[str], required: Iterable[str]) -> None:
    """检查输入列是否齐全，缺失时一次性报出完整清单。"""
    available = set(columns)
    missing = [column for column in required if column not in available]
    if missing:
        raise ValueError(
            "输入 panel 缺少必要列：\n"
            + "\n".join(f"- {column}" for column in missing)
        )


def apply_filters(data: pd.DataFrame, filters: dict[str, object]) -> pd.DataFrame:
    """按给定筛选条件过滤样本。"""
    mask = pd.Series(True, index=data.index)
    for column, expected in filters.items():
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            mask &= pd.to_numeric(data[column], errors="coerce") == float(expected)
        else:
            mask &= data[column].astype("string") == str(expected)
    return data.loc[mask].copy()


def get_future_return_sample_filters(y_col: str) -> dict[str, int]:
    """返回普通未来收益对应的截止日与持有期连续样本筛选。

    本脚本直接读取 A_data 大面板，没有经过 registry 驱动的 B_factors 清洗，
    因此要在这里显式采用与正式模型相同的 horizon-specific 筛选口径。
    """

    match = re.fullmatch(r"future_ret_(\d+)m", y_col)
    if match is None:
        raise ValueError(
            "代表窗口检验只支持 future_ret_{horizon}m 格式的普通未来收益："
            f"{y_col!r}"
        )
    horizon = int(match.group(1))
    return {
        f"is_insample_future_ret_{horizon}m": 1,
        f"match_is_sample_future_ret_{horizon}m": 1,
    }


def winsorize_by_month(
    data: pd.DataFrame,
    columns: list[str],
    *,
    date_col: str,
    lower_quantile: float,
    upper_quantile: float,
) -> pd.DataFrame:
    """按月份对连续变量做缩尾，口径沿用 B_factors 预处理层。

    这里不修改原始 panel，只在本脚本的内存副本上处理。这样可以保证输出结果
    与任务 1 的回归更可比，同时满足“不修改原始数据”的约束。
    """
    result = data.copy()
    for column in columns:
        if column not in result.columns:
            continue
        # 连续变量缩尾后的分位数边界通常是浮点数；即使原列是 Int64
        # （例如基金年龄），回归中也应按 float 使用，避免写回整数列时报类型错误。
        numeric = pd.to_numeric(result[column], errors="coerce").astype("float64")
        lower = numeric.groupby(result[date_col], sort=False).transform(
            lambda s: s.quantile(lower_quantile)
        )
        upper = numeric.groupby(result[date_col], sort=False).transform(
            lambda s: s.quantile(upper_quantile)
        )
        result[column] = numeric.clip(lower=lower, upper=upper)
    return result


def ols_cross_section(
    data: pd.DataFrame,
    y_col: str,
    x_cols: list[str],
) -> pd.Series:
    """对单个月份做横截面 OLS，公式与核心回归脚本保持一致。"""
    y = data[y_col].to_numpy(dtype=float)
    x = data[x_cols].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    coef_names = ["const"] + x_cols

    beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < x.shape[1]:
        raise np.linalg.LinAlgError("设计矩阵秩不足，可能存在变量共线")

    fitted = x @ beta
    residual = y - fitted
    ss_res = float(np.dot(residual, residual))
    ss_total = float(np.dot(y - y.mean(), y - y.mean()))
    r_squared = 1.0 - ss_res / ss_total if ss_total > 0 else np.nan
    n_obs = len(y)
    n_params = x.shape[1]
    adj_r_squared = (
        1.0 - (1.0 - r_squared) * (n_obs - 1) / (n_obs - n_params)
        if ss_total > 0 and n_obs > n_params
        else np.nan
    )

    result = pd.Series(beta, index=coef_names)
    result["r_squared"] = r_squared
    result["adj_r_squared"] = adj_r_squared
    result["n_obs"] = n_obs
    return result


def newey_west_mean_se(values: pd.Series, lag: int) -> float:
    """计算月度系数均值的 Newey-West 标准误。"""
    x = values.dropna().to_numpy(dtype=float)
    t_count = len(x)
    if t_count <= 1:
        return np.nan

    centered = x - x.mean()
    max_lag = min(lag, t_count - 1)
    long_run_var = np.dot(centered, centered) / t_count
    for ell in range(1, max_lag + 1):
        weight = 1.0 - ell / (max_lag + 1.0)
        gamma = np.dot(centered[ell:], centered[:-ell]) / t_count
        long_run_var += 2.0 * weight * gamma
    return float(np.sqrt(max(long_run_var, 0.0) / t_count))


def summarize_variable(
    monthly_coef: pd.DataFrame,
    variable: str,
    *,
    newey_west_lag: int,
) -> dict[str, float | int]:
    """把某个变量的月度系数序列汇总成 Fama-MacBeth 统计量。"""
    if variable not in monthly_coef.columns:
        return {"coef": np.nan, "t_stat": np.nan, "p_value": np.nan, "n_months": 0}

    series = monthly_coef[variable].dropna()
    n_months = int(len(series))
    coef = float(series.mean()) if n_months else np.nan
    se = newey_west_mean_se(series, newey_west_lag) if n_months else np.nan
    t_stat = coef / se if se and not np.isnan(se) and se > 0 else np.nan
    p_value = (
        float(2.0 * stats.t.sf(abs(t_stat), df=max(n_months - 1, 1)))
        if not np.isnan(t_stat)
        else np.nan
    )
    return {
        "coef": coef,
        "t_stat": t_stat,
        "p_value": p_value,
        "n_months": n_months,
    }


def run_one_regression(
    data: pd.DataFrame,
    *,
    spec: ParamSpec,
    sample_group: str,
    y_label: str,
    y_col: str,
    controls: list[str],
    min_cross_section_n: int,
    newey_west_lag: int,
    include_rank_mean: bool,
) -> tuple[dict[str, object], pd.DataFrame]:
    """运行一个参数窗口、一个样本组、一个 Y 期限的 Fama-MacBeth 回归。"""
    filters = get_future_return_sample_filters(y_col)
    if sample_group != "Full sample":
        flag_column = sample_group_flag_column(spec, sample_group)
        if flag_column is None:
            raise ValueError(f"{sample_group} 缺少分组列配置。")
        filters[flag_column] = SAMPLE_GROUPS[sample_group]["filter_value"]

    filtered = apply_filters(data, filters)
    x_cols = [spec.fac_col]
    if include_rank_mean:
        x_cols.append(spec.rank_mean_col)
    x_cols.extend(controls)
    required = [y_col, *x_cols]

    valid_mask = filtered[required].notna().all(axis=1)
    valid = filtered.loc[valid_mask, ["month_date", *required]].copy()
    monthly_n = valid.groupby("month_date").size().rename("n_valid")
    eligible_months = monthly_n[monthly_n >= min_cross_section_n].index
    regression_df = valid.loc[valid["month_date"].isin(eligible_months)].copy()

    monthly_rows: list[pd.Series] = []
    for month, month_df in regression_df.groupby("month_date", sort=True):
        try:
            coef = ols_cross_section(month_df, y_col, x_cols)
        except Exception:
            # 单个月份共线或异常时跳过，保持与核心回归脚本“跳过坏月份”的口径一致。
            continue
        coef["month_date"] = month
        monthly_rows.append(coef)

    monthly_coef = pd.DataFrame(monthly_rows)
    if monthly_coef.empty:
        monthly_coef = pd.DataFrame(
            columns=["month_date", "n_obs", "r_squared", "adj_r_squared", "const", *x_cols]
        )

    fac_stats = summarize_variable(
        monthly_coef, spec.fac_col, newey_west_lag=newey_west_lag
    )
    rank_stats = summarize_variable(
        monthly_coef, spec.rank_mean_col, newey_west_lag=newey_west_lag
    )

    row = {
        "sample_group": sample_group,
        "m": spec.m,
        "n": spec.n,
        "param_name": spec.param_name,
        "param_category": spec.category,
        "y_horizon": y_label,
        "y_column": y_col,
        "model_spec": (
            "FAC + rank_mean + baseline controls"
            if include_rank_mean
            else "FAC + baseline controls"
        ),
        "coef_FAC": fac_stats["coef"],
        "t_FAC": fac_stats["t_stat"],
        "p_FAC": fac_stats["p_value"],
        "coef_rank_mean": rank_stats["coef"] if include_rank_mean else np.nan,
        "t_rank_mean": rank_stats["t_stat"] if include_rank_mean else np.nan,
        "p_rank_mean": rank_stats["p_value"] if include_rank_mean else np.nan,
        "n_months": fac_stats["n_months"],
        "avg_obs_per_month": (
            float(monthly_coef["n_obs"].mean()) if len(monthly_coef) else np.nan
        ),
        "total_regression_obs": (
            int(monthly_coef["n_obs"].sum()) if len(monthly_coef) else 0
        ),
        "r2": (
            float(monthly_coef["r_squared"].mean()) if len(monthly_coef) else np.nan
        ),
        "adj_r2": (
            float(monthly_coef["adj_r_squared"].mean())
            if len(monthly_coef)
            else np.nan
        ),
        "filtered_rows_before_dropna": int(len(filtered)),
        "valid_rows_after_dropna": int(valid_mask.sum()),
        "eligible_months": int(len(eligible_months)),
        "min_cross_section_n": min_cross_section_n,
        "newey_west_lag": newey_west_lag,
    }
    return row, monthly_coef


def build_term_structure(results: pd.DataFrame) -> pd.DataFrame:
    """生成期限结构宽表：行是 param_name + sample_group，列是不同 Y 期限。"""
    table = results.copy()
    table["coef_t_cell"] = table.apply(
        lambda row: (
            "" if pd.isna(row["coef_FAC"]) else f"{row['coef_FAC']:.4f} ({row['t_FAC']:.2f})"
        ),
        axis=1,
    )
    wide = table.pivot_table(
        index=["param_category", "param_name", "sample_group"],
        columns="y_horizon",
        values="coef_t_cell",
        aggfunc="first",
    ).reset_index()
    return wide


def write_markdown_report(
    output_path: Path,
    results: pd.DataFrame,
    term_structure: pd.DataFrame,
    *,
    include_rank_mean: bool,
) -> None:
    """根据结果表自动写出一份简洁 Markdown 报告。"""
    significant = results.loc[results["t_FAC"].abs() >= 1.96].copy()
    short = results.loc[results["param_category"] == "short_reversal_candidates"]
    medium = results.loc[results["param_category"] == "medium_continuation_candidates"]
    m3 = short.loc[short["param_name"].str.startswith("m3_")]
    m6_top33 = medium.loc[
        medium["param_name"].str.startswith("m6_") & medium["sample_group"].eq("Top33")
    ]

    def direction_text(data: pd.DataFrame) -> str:
        if data.empty:
            return "无可用结果"
        avg_by_y = data.groupby("y_horizon")["coef_FAC"].mean().sort_index()
        return "；".join(f"{idx}: {value:.4f}" for idx, value in avg_by_y.items())

    m3_short_negative = (
        not m3.empty
        and m3.loc[m3["y_horizon"].isin(["future_return_1m", "future_return_3m"]), "coef_FAC"].mean()
        < m3.loc[m3["y_horizon"].isin(["future_return_6m", "future_return_12m"]), "coef_FAC"].mean()
    )
    m6_top_positive = not m6_top33.empty and (m6_top33["coef_FAC"] > 0).any()

    candidates = significant.loc[
        significant["sample_group"].isin(["Top33", "Full sample"])
    ].sort_values(["p_FAC", "param_category", "param_name"])

    lines = [
        "# 代表参数窗口 × 未来收益期限检验报告",
        "",
        "## 口径说明",
        "",
        "- 回归方法：逐月横截面 OLS + Fama-MacBeth 时间序列均值。",
        "- 控制变量、最小横截面样本数和 Newey-West 滞后阶数默认沿用 `fm_baseline`。",
        "- 样本分组：Top33 / Mid33 / Bottom33 使用每个窗口自己的 `is_tercile_rank_mean_*`。",
        "- Full sample 不使用 rank_mean 分组筛选。",
        f"- rank_mean 是否入模：{include_rank_mean}。",
        "",
        "## 自动回答",
        "",
        "### 1. m3 类窗口是否在短期限 Y 下更负？",
        "",
        f"- m3 类 FAC 平均系数按期限：{direction_text(m3)}。",
        f"- 初步判断：{'是，短期限更负。' if m3_short_negative else '当前结果不支持短期限更负。'}",
        "",
        "### 2. m3 类窗口是否支持短期均值回归解释？",
        "",
        "- 若 m3 类窗口在 1m/3m 下为负且显著，而 6m/12m 弱化，则支持短期均值回归解释。",
        f"- 当前 m3 显著记录数：{len(significant.loc[significant['param_name'].str.startswith('m3_')])}。",
        "",
        "### 3. m6 类窗口是否在 Top33 中保持正向？",
        "",
        f"- m6 Top33 FAC 平均系数按期限：{direction_text(m6_top33)}。",
        f"- 初步判断：{'存在正向证据。' if m6_top_positive else '当前未看到稳定正向证据。'}",
        "",
        "### 4. m6 类窗口适合预测未来几个月收益？",
        "",
        "- 建议优先查看 m6_n11 / m6_n12 在 Top33 中 t 值最高的 Y 期限。",
        "",
        "### 5. 哪些窗口适合进入下一步组合回测？",
        "",
    ]

    if candidates.empty:
        lines.append("- 当前没有 `|t_FAC| >= 1.96` 且位于 Top33/Full sample 的候选。")
    else:
        preview = candidates.head(20)
        for row in preview.itertuples(index=False):
            lines.append(
                f"- {row.param_name} / {row.sample_group} / {row.y_horizon}: "
                f"coef={row.coef_FAC:.4f}, t={row.t_FAC:.2f}"
            )

    lines.extend(
        [
            "",
            "## 期限结构表预览",
            "",
            dataframe_to_markdown(term_structure.head(30)),
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def dataframe_to_markdown(data: pd.DataFrame) -> str:
    """把小型 DataFrame 转成 Markdown 表，避免依赖 pandas 的可选 tabulate 包。"""
    if data.empty:
        return "无可展示记录。"

    display = data.fillna("").astype(str)
    columns = list(display.columns)
    rows = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in display.iterrows():
        rows.append("| " + " | ".join(row[column] for column in columns) + " |")
    return "\n".join(rows)


def make_output_dir(output_root: Path) -> Path:
    """创建带时间戳的输出目录，避免覆盖已有结果。"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)
    return output_dir


def main() -> None:
    """程序入口。"""
    args = parse_args()
    input_path = resolve_project_path(args.input)
    output_root = resolve_project_path(args.output_root)

    if not input_path.exists():
        raise FileNotFoundError(f"输入 panel 不存在：{input_path}")

    baseline_config = load_registry_config("fm_baseline")
    controls = list(baseline_config["controls"])
    min_cross_section_n = (
        int(args.min_cross_section_n)
        if args.min_cross_section_n is not None
        else int(baseline_config["min_cross_section_n"])
    )
    newey_west_lag = (
        int(args.newey_west_lag)
        if args.newey_west_lag is not None
        else int(baseline_config["newey_west_lag"])
    )
    winsorize_config = dict(baseline_config["winsorize"])

    specs = filter_specs(representative_specs(), args.params)
    sample_groups = select_sample_groups(
        args.sample_groups,
        include_full_sample=bool(args.include_full_sample),
    )
    schema_columns = read_parquet_columns(input_path)
    y_map = resolve_y_columns(schema_columns, args.y_horizons)
    required = required_columns(
        specs,
        y_map,
        controls,
        include_rank_mean=bool(args.include_rank_mean),
        sample_groups=sample_groups,
    )
    check_missing_columns(schema_columns, required)

    print(f"输入 panel：{input_path}")
    print("Y 列映射：")
    for label, actual in y_map.items():
        print(f"  {label} -> {actual}")
    print(f"参数窗口数：{len(specs)}")
    print(f"样本组：{', '.join(sample_groups)}")
    print(f"控制变量：{', '.join(controls)}")
    print(f"是否加入 rank_mean 主效应：{bool(args.include_rank_mean)}")
    print(f"min_cross_section_n：{min_cross_section_n}")
    print(f"newey_west_lag：{newey_west_lag}")

    if args.dry_run:
        print("--dry-run：列检查通过，未读取完整 parquet，未运行回归。")
        return

    # 只读取本脚本需要的列，避免把完整 700+ 列全部加载进内存。
    data = pd.read_parquet(input_path, columns=required)
    data["month_date"] = pd.to_datetime(data["month_date"], errors="coerce")

    # winsorize 只在内存副本上做。控制变量只缩尾 baseline 原本声明的连续列，
    # 不处理 as_偏股混合型基金 这类 0/1 哑变量，避免改变变量含义或触发类型转换错误。
    factor_cols = [spec.fac_col for spec in specs]
    rank_mean_cols = [spec.rank_mean_col for spec in specs] if args.include_rank_mean else []
    baseline_winsor_columns = set(winsorize_config["columns"])
    winsor_control_cols = [column for column in controls if column in baseline_winsor_columns]
    winsor_columns = list(
        dict.fromkeys([*y_map.values(), *factor_cols, *rank_mean_cols, *winsor_control_cols])
    )
    data = winsorize_by_month(
        data,
        winsor_columns,
        date_col="month_date",
        lower_quantile=float(winsorize_config["lower_quantile"]),
        upper_quantile=float(winsorize_config["upper_quantile"]),
    )

    output_dir = make_output_dir(output_root)
    rows: list[dict[str, object]] = []
    monthly_parts: list[pd.DataFrame] = []
    for spec in specs:
        for sample_group in sample_groups:
            for y_label, y_col in y_map.items():
                row, monthly = run_one_regression(
                    data,
                    spec=spec,
                    sample_group=sample_group,
                    y_label=y_label,
                    y_col=y_col,
                    controls=controls,
                    min_cross_section_n=min_cross_section_n,
                    newey_west_lag=newey_west_lag,
                    include_rank_mean=bool(args.include_rank_mean),
                )
                rows.append(row)
                monthly = monthly.copy()
                monthly.insert(0, "sample_group", sample_group)
                monthly.insert(1, "param_name", spec.param_name)
                monthly.insert(2, "y_horizon", y_label)
                monthly_parts.append(monthly)

    results = pd.DataFrame(rows)
    term_structure = build_term_structure(results)
    monthly_coef = pd.concat(monthly_parts, ignore_index=True) if monthly_parts else pd.DataFrame()

    results_csv = output_dir / "representative_window_horizon_results.csv"
    results_xlsx = output_dir / "representative_window_horizon_results.xlsx"
    term_csv = output_dir / "term_structure_table.csv"
    term_xlsx = output_dir / "term_structure_table.xlsx"
    monthly_csv = output_dir / "representative_window_horizon_monthly_coefficients.csv"
    report_md = output_dir / "representative_window_horizon_report.md"
    metadata_json = output_dir / "run_metadata.json"

    results.to_csv(results_csv, index=False, encoding="utf-8-sig")
    results.to_excel(results_xlsx, index=False)
    term_structure.to_csv(term_csv, index=False, encoding="utf-8-sig")
    term_structure.to_excel(term_xlsx, index=False)
    monthly_coef.to_csv(monthly_csv, index=False, encoding="utf-8-sig")
    write_markdown_report(
        report_md,
        results,
        term_structure,
        include_rank_mean=bool(args.include_rank_mean),
    )
    metadata_json.write_text(
        json.dumps(
            {
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "y_column_map": y_map,
                "param_groups": {
                    key: [f"m{m}_n{n}" for m, n in pairs]
                    for key, pairs in PARAM_GROUPS.items()
                },
                "selected_params": [spec.param_name for spec in specs],
                "sample_groups": sample_groups,
                "controls": controls,
                "include_rank_mean": bool(args.include_rank_mean),
                "min_cross_section_n": min_cross_section_n,
                "newey_west_lag": newey_west_lag,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("代表参数窗口 × 未来收益期限检验完成。")
    print(f"输出目录：{output_dir}")
    print(f"结果表：{results_csv}")
    print(f"期限结构表：{term_csv}")
    print(f"Markdown 报告：{report_md}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"代表参数窗口 × 未来收益期限检验失败：{exc}")
        raise SystemExit(1) from None
