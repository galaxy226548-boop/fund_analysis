"""检查 winrate dummy 的月度可识别性，并检验任意两档 beta 的差异。

这个脚本不重新运行 Fama-MacBeth 主回归，而是读取 registry 指定的回归面板和
``fama_macbeth_monthly_coefficients.csv``。它回答两个容易被汇总结果掩盖的问题：

1. 哪些月份因为某个 hit 组没有基金，或完整设计矩阵不满秩而无法回归；
2. 任意两档 hit 系数之差是否显著，而不只是分别检验它们相对 hit0 的系数。

默认检查 ``fm_winrates_top50_nonoverlap`` 的 ``m3_n6``：

    .venv/bin/python D_analysis/scripts/winrates_check.py

也可以切换到 registry 中其他 tuple/list dummy 组：

    .venv/bin/python D_analysis/scripts/winrates_check.py \
        --model fm_winrates_top50_nonoverlap \
        --factor winrate_m6_n6_pairwise6
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_MODEL_KEY = "fm_winrates_top50_nonoverlap"
DEFAULT_FACTOR_LABEL = "winrate_m3_n6_pairwise3"


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="检查 winrate dummy 的逐月可识别性和 beta 两两差异。"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_KEY,
        help="regression_registry.py 中的模型 key。",
    )
    parser.add_argument(
        "--factor",
        default=DEFAULT_FACTOR_LABEL,
        help="factor_group_suffixes 中的窗口短名，例如 winrate_m3_n6_pairwise3。",
    )
    parser.add_argument(
        "--panel",
        type=Path,
        default=None,
        help="可选：覆盖 registry 的 regression_input_path。",
    )
    parser.add_argument(
        "--monthly-coefficients",
        type=Path,
        default=None,
        help="可选：覆盖默认的 fama_macbeth_monthly_coefficients.csv。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="可选：覆盖默认输出目录。",
    )
    return parser.parse_args()


def load_regression_config(model_key: str) -> dict[str, Any]:
    """按文件路径加载 registry，避免依赖运行时的 Python import 路径。"""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location("winrates_check_registry", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.get_regression_config(model_key))


def project_path(path_value: str | Path) -> Path:
    """把项目相对路径转换为绝对路径，绝对路径则保持不变。"""
    path = Path(path_value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def factor_label_from_config(
    factor_spec: tuple[str, ...],
    suffixes: dict[Any, Any],
) -> str:
    """取得回归输出中使用的稳定 factor 标签。"""
    configured = suffixes.get(factor_spec)
    if configured is not None:
        return str(configured)
    return "__".join(factor_spec)


def select_factor_spec(
    config: dict[str, Any], requested_label: str
) -> tuple[tuple[str, ...], str]:
    """按窗口短名找到对应的一组 dummy 列。"""
    suffixes = dict(config.get("factor_group_suffixes", {}))
    candidates: list[tuple[tuple[str, ...], str]] = []

    for raw_factor in config.get("factors", []):
        if not isinstance(raw_factor, (tuple, list)):
            continue
        factor_spec = tuple(str(column) for column in raw_factor)
        label = factor_label_from_config(factor_spec, suffixes)
        candidates.append((factor_spec, label))
        if label == requested_label:
            return factor_spec, label

    available = ", ".join(label for _, label in candidates) or "无 tuple/list dummy 组"
    raise ValueError(
        f"模型中找不到 factor={requested_label!r}；可选窗口：{available}"
    )


def build_filter_mask(series: pd.Series, expected_value: Any) -> pd.Series:
    """兼容数值和字符串筛选值，口径与主回归脚本保持一致。"""
    expected_numeric = pd.to_numeric(pd.Series([expected_value]), errors="coerce").iloc[0]
    if pd.notna(expected_numeric):
        return pd.to_numeric(series, errors="coerce") == expected_numeric
    return series.astype("string") == str(expected_value)


def factor_filters(
    config: dict[str, Any], factor_spec: tuple[str, ...], factor_label: str
) -> dict[str, Any]:
    """合并模型基础筛选和当前 dummy 组自己的筛选条件。"""
    filters = dict(config.get("sample_filters", {}))
    factor_specific = dict(config.get("factor_sample_filters", {}))

    # registry 可能按 tuple 或输出标签登记额外筛选，两种方式都兼容。
    extra = factor_specific.get(factor_spec)
    if extra is None:
        extra = factor_specific.get(factor_label, {})
    filters.update(dict(extra or {}))
    return filters


def apply_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    """依次应用样本筛选，并在字段缺失时尽早报错。"""
    result = df.copy()
    for column, expected_value in filters.items():
        if column not in result.columns:
            raise ValueError(f"输入面板缺少样本筛选列：{column}")
        result = result.loc[build_filter_mask(result[column], expected_value)].copy()
    return result


def hit_order(column: str) -> int:
    """从 dummy 列名提取 hit 次数或累积门槛，用于稳定排序。"""
    cumulative = re.search(r"_hit_above(\d+)(?:_|$)", column)
    if cumulative:
        return int(cumulative.group(1))
    ordinary = re.search(r"_hit(\d+)(?:_|$)", column)
    if ordinary:
        return int(ordinary.group(1))
    raise ValueError(f"无法从 dummy 列名识别 hit 次数：{column}")


def hit_label(column: str) -> str:
    """把完整变量名缩短成适合结果表阅读的标签。"""
    cumulative = re.search(r"_hit_above(\d+)(?:_|$)", column)
    if cumulative:
        return f"hit_above{cumulative.group(1)}"
    return f"hit{hit_order(column)}"


def is_cumulative_group(factor_cols: list[str]) -> bool:
    """判断当前 dummy 是否采用嵌套累计门槛编码。"""
    return any("_hit_above" in column for column in factor_cols)


def prepare_regression_sample(
    panel: pd.DataFrame,
    config: dict[str, Any],
    factor_spec: tuple[str, ...],
    factor_label: str,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """按主回归口径构造完整样本，并把相关列转换为数值。"""
    if config.get("interactions"):
        raise ValueError("winrates_check 暂不支持带交互项的 dummy 模型。")

    date_col = str(config["date_col"])
    y_col = str(config["y"])
    factor_cols = sorted(list(factor_spec), key=hit_order)
    control_cols = [str(column) for column in config.get("controls", [])]
    filter_columns = list(factor_filters(config, factor_spec, factor_label))
    required = list(
        dict.fromkeys([date_col, y_col, *factor_cols, *control_cols, *filter_columns])
    )
    missing = [column for column in required if column not in panel.columns]
    if missing:
        raise ValueError(f"输入面板缺少必要列：{missing}")

    filtered = apply_filters(
        panel,
        factor_filters(config, factor_spec, factor_label),
    )
    numeric_cols = [y_col, *factor_cols, *control_cols]
    for column in numeric_cols:
        filtered[column] = pd.to_numeric(filtered[column], errors="coerce")

    # 与主回归一样，只有 Y、当前 dummy 组和全部控制变量都完整的行才进入月度检查。
    complete = filtered.dropna(subset=numeric_cols).copy()
    complete[date_col] = pd.to_datetime(complete[date_col], errors="coerce")
    complete = complete.dropna(subset=[date_col])
    return complete, factor_cols, control_cols


def add_ordinary_group_labels(
    sample: pd.DataFrame, factor_cols: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    """把省略的 hit0 基准组补回，供逐月频次和满秩诊断使用。"""
    factor_values = sample[factor_cols]
    valid_values = factor_values.isin([0, 1]).all(axis=None)
    if not valid_values:
        raise ValueError("普通 one-hot dummy 出现 0/1 之外的取值。")

    row_sum = factor_values.sum(axis=1)
    if not row_sum.isin([0, 1]).all():
        raise ValueError("普通 one-hot dummy 的行和不在 0/1 内，无法重建 hit0。")

    result = sample.copy()
    result["__hit_group"] = "hit0"
    ordered_labels = ["hit0"]
    for column in factor_cols:
        label = hit_label(column)
        result.loc[result[column].eq(1), "__hit_group"] = label
        ordered_labels.append(label)
    return result, ordered_labels


def matrix_rank_with_const(values: pd.DataFrame) -> tuple[int, int]:
    """返回加截距后设计矩阵的实际秩和列数。"""
    matrix = values.to_numpy(dtype=float)
    matrix = np.column_stack([np.ones(len(matrix)), matrix])
    return int(np.linalg.matrix_rank(matrix)), int(matrix.shape[1])


def build_monthly_identification(
    sample: pd.DataFrame,
    factor_cols: list[str],
    control_cols: list[str],
    date_col: str,
    min_cross_section_n: int,
) -> pd.DataFrame:
    """逐月统计组别频次，并检查 dummy 和完整回归矩阵是否满秩。"""
    cumulative = is_cumulative_group(factor_cols)
    if cumulative:
        prepared = sample.copy()
        factor_values = prepared[factor_cols]
        if not factor_values.isin([0, 1]).all(axis=None):
            raise ValueError("累积 dummy 出现 0/1 之外的取值。")

        # Dk=1(hitcount>=k) 必须从 D1 到 Dn 单调不增。只有先验证这一点，
        # 才能安全地用各列之和还原每只基金的精确 hitcount。
        if len(factor_cols) > 1:
            left = factor_values.iloc[:, :-1].to_numpy(dtype=int)
            right = factor_values.iloc[:, 1:].to_numpy(dtype=int)
            if np.any(left < right):
                raise ValueError("累积 dummy 不满足 D1>=D2>=...>=Dn，无法还原 hitcount。")
        prepared["__hit_count"] = factor_values.sum(axis=1).astype(int)
        group_labels = [f"hit{k}" for k in range(len(factor_cols) + 1)]
    else:
        prepared, group_labels = add_ordinary_group_labels(sample, factor_cols)

    rows: list[dict[str, Any]] = []
    for month, month_df in prepared.groupby(date_col, sort=True):
        n_obs = int(len(month_df))
        dummy_rank, dummy_columns = matrix_rank_with_const(month_df[factor_cols])
        full_rank, full_columns = matrix_rank_with_const(
            month_df[[*factor_cols, *control_cols]]
        )

        row: dict[str, Any] = {
            "month_date": pd.Timestamp(month).strftime("%Y-%m-%d"),
            "complete_case_n": n_obs,
            "min_cross_section_n": min_cross_section_n,
            "eligible_n": n_obs >= min_cross_section_n,
            "dummy_matrix_rank": dummy_rank,
            "dummy_matrix_columns": dummy_columns,
            "dummy_full_rank": dummy_rank == dummy_columns,
            "full_matrix_rank": full_rank,
            "full_matrix_columns": full_columns,
            "full_model_rank": full_rank == full_columns,
        }

        if cumulative:
            # 累积 dummy 不是互斥列，但可以还原成互斥的精确 hit 组。
            # 同时保留每个 Dk 的 1/0 数量，方便追查是哪一道门槛失去变化。
            for column in factor_cols:
                label = hit_label(column)
                row[f"{label}_count_1"] = int(month_df[column].eq(1).sum())
                row[f"{label}_count_0"] = int(month_df[column].eq(0).sum())
            counts = month_df["__hit_count"].value_counts()
            group_counts = {
                label: int(counts.get(k, 0))
                for k, label in enumerate(group_labels)
            }
            for label, count in group_counts.items():
                row[f"{label}_n"] = count
            missing_groups = [
                label for label, count in group_counts.items() if count == 0
            ]
            row["missing_groups"] = ",".join(missing_groups)
            row["min_group_n"] = min(group_counts.values())
            row["all_groups_ge_1"] = all(
                count >= 1 for count in group_counts.values()
            )
            row["all_groups_ge_5"] = all(
                count >= 5 for count in group_counts.values()
            )
            row["all_groups_ge_10"] = all(
                count >= 10 for count in group_counts.values()
            )
        else:
            counts = month_df["__hit_group"].value_counts()
            group_counts = {label: int(counts.get(label, 0)) for label in group_labels}
            for label, count in group_counts.items():
                row[f"{label}_n"] = count
            missing_groups = [label for label, count in group_counts.items() if count == 0]
            row["missing_groups"] = ",".join(missing_groups)
            row["min_group_n"] = min(group_counts.values())
            row["all_groups_ge_1"] = all(count >= 1 for count in group_counts.values())
            row["all_groups_ge_5"] = all(count >= 5 for count in group_counts.values())
            row["all_groups_ge_10"] = all(count >= 10 for count in group_counts.values())

        row["regression_ready"] = bool(row["eligible_n"] and row["full_model_rank"])
        reasons: list[str] = []
        if not row["eligible_n"]:
            reasons.append("完整样本少于月度门槛")
        if row["eligible_n"] and not row["dummy_full_rank"]:
            if row["missing_groups"]:
                reasons.append(f"dummy组缺失:{row['missing_groups']}")
            else:
                reasons.append("dummy矩阵不满秩")
        if row["eligible_n"] and row["dummy_full_rank"] and not row["full_model_rank"]:
            reasons.append("加入控制变量后不满秩")
        row["failure_reason"] = ";".join(reasons)
        rows.append(row)

    return pd.DataFrame(rows)


def newey_west_mean_se(values: pd.Series, lag: int) -> float:
    """按主回归脚本的同一公式计算时间序列均值的 Newey-West 标准误。"""
    x = values.dropna().to_numpy(dtype=float)
    t = len(x)
    if t <= 1:
        return np.nan

    centered = x - x.mean()
    max_lag = min(lag, t - 1)
    long_run_var = float(np.dot(centered, centered) / t)
    for ell in range(1, max_lag + 1):
        weight = 1.0 - ell / (max_lag + 1.0)
        gamma = float(np.dot(centered[ell:], centered[:-ell]) / t)
        long_run_var += 2.0 * weight * gamma
    return float(np.sqrt(max(long_run_var, 0.0) / t))


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """对一组 p 值做 Benjamini-Hochberg FDR 校正。"""
    result = pd.Series(np.nan, index=p_values.index, dtype="float64")
    valid = p_values.dropna().sort_values()
    if valid.empty:
        return result

    m = len(valid)
    raw = valid.to_numpy(dtype=float) * m / np.arange(1, m + 1)
    adjusted = np.minimum.accumulate(raw[::-1])[::-1]
    result.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def build_beta_pair_tests(
    monthly_coefficients: pd.DataFrame,
    factor_cols: list[str],
    factor_label: str,
    date_col: str,
    nw_lag: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算每一对 beta 的月度差值及其 Newey-West 均值检验。"""
    if "factor" not in monthly_coefficients.columns:
        raise ValueError("月度系数文件缺少 factor 列。")
    if date_col not in monthly_coefficients.columns:
        raise ValueError(f"月度系数文件缺少日期列：{date_col}")

    factor_monthly = monthly_coefficients.loc[
        monthly_coefficients["factor"].astype(str).eq(factor_label)
    ].copy()
    if factor_monthly.empty:
        raise ValueError(f"月度系数文件中找不到 factor={factor_label!r}。")

    missing = [column for column in factor_cols if column not in factor_monthly.columns]
    if missing:
        raise ValueError(f"月度系数文件缺少当前 dummy 系数列：{missing}")

    factor_monthly[date_col] = pd.to_datetime(factor_monthly[date_col], errors="coerce")
    factor_monthly = factor_monthly.dropna(subset=[date_col]).sort_values(date_col)

    coefficient_specs: list[dict[str, Any]] = []
    if not is_cumulative_group(factor_cols):
        # 普通 one-hot 回归以 hit0 为基准，虽然回归文件没有 beta_hit0，
        # 但它在每个月都严格等于 0，可以纳入所有两两差异检验。
        coefficient_specs.append(
            {"label": "hit0", "order": 0, "column": None}
        )
    coefficient_specs.extend(
        {
            "label": hit_label(column),
            "order": hit_order(column),
            "column": column,
        }
        for column in factor_cols
    )
    coefficient_specs = sorted(coefficient_specs, key=lambda item: int(item["order"]))

    summary_rows: list[dict[str, Any]] = []
    detail_frames: list[pd.DataFrame] = []
    for lower, upper in combinations(coefficient_specs, 2):
        lower_values = (
            pd.Series(0.0, index=factor_monthly.index)
            if lower["column"] is None
            else pd.to_numeric(factor_monthly[str(lower["column"])], errors="coerce")
        )
        upper_values = (
            pd.Series(0.0, index=factor_monthly.index)
            if upper["column"] is None
            else pd.to_numeric(factor_monthly[str(upper["column"])], errors="coerce")
        )
        difference = upper_values - lower_values
        valid = difference.notna()
        difference = difference.loc[valid]
        n_months = int(len(difference))
        mean_difference = float(difference.mean()) if n_months else np.nan
        nw_se = newey_west_mean_se(difference, nw_lag) if n_months else np.nan
        t_stat = (
            mean_difference / nw_se
            if pd.notna(nw_se) and nw_se > 0
            else np.nan
        )
        p_value = (
            float(2.0 * stats.t.sf(abs(t_stat), df=max(n_months - 1, 1)))
            if pd.notna(t_stat)
            else np.nan
        )
        pair_name = f"beta_{upper['label']}-beta_{lower['label']}"
        order_gap = int(upper["order"]) - int(lower["order"])
        if int(lower["order"]) == 0:
            # 所有 hitK 相对 hit0 的比较共同回答“高命中组是否区别于零命中组”。
            # hit1-hit0 也放在这里，因为它更接近首次参与/level 效应。
            hypothesis_family = "level_vs_hit0"
        elif order_gap == 1:
            # 从已经命中过至少一次开始，相邻档差异才回答“再多命中一次”的边际价值。
            hypothesis_family = "adjacent_marginal_increment"
        else:
            # 非相邻、且不以 hit0 为基准的差异不对应当前两项核心主张，单列为探索性检验。
            hypothesis_family = "exploratory_nonadjacent"
        summary_rows.append(
            {
                "factor": factor_label,
                "pair": pair_name,
                "hypothesis_family": hypothesis_family,
                "lower_beta": lower["label"],
                "upper_beta": upper["label"],
                "lower_order": lower["order"],
                "upper_order": upper["order"],
                "is_adjacent": order_gap == 1,
                "mean_lower_beta": float(lower_values.loc[valid].mean()),
                "mean_upper_beta": float(upper_values.loc[valid].mean()),
                "mean_difference": mean_difference,
                "newey_west_se": nw_se,
                "t_stat": t_stat,
                "p_value": p_value,
                "n_months": n_months,
                "newey_west_lag": nw_lag,
            }
        )

        detail_frames.append(
            pd.DataFrame(
                {
                    "factor": factor_label,
                    "pair": pair_name,
                    "month_date": factor_monthly.loc[valid, date_col].dt.strftime(
                        "%Y-%m-%d"
                    ),
                    "lower_beta_value": lower_values.loc[valid],
                    "upper_beta_value": upper_values.loc[valid],
                    "beta_difference": difference,
                }
            )
        )

    summary = pd.DataFrame(summary_rows)
    summary["significant_5pct"] = summary["p_value"] < 0.05
    # FDR 的“假设族”必须由研究主张决定，不能因为脚本顺手计算了 21 对差异，
    # 就把它们全部塞进同一次校正。这里按上面三种经济问题分别做 BH 校正。
    summary["family_size"] = summary.groupby("hypothesis_family")[
        "p_value"
    ].transform("count")
    summary["family_fdr_q_value"] = np.nan
    for _, family_index in summary.groupby("hypothesis_family").groups.items():
        summary.loc[family_index, "family_fdr_q_value"] = benjamini_hochberg(
            summary.loc[family_index, "p_value"]
        )
    summary["significant_family_fdr_5pct"] = (
        summary["family_fdr_q_value"] < 0.05
    )

    # 全部 21 对一起校正只保留为探索性敏感度信息，列名明确标示其范围；
    # 它不能替代按研究主张划分的 family_fdr_q_value。
    summary["exploratory_all_pairs_fdr_q_value"] = benjamini_hochberg(
        summary["p_value"]
    )
    details = pd.concat(detail_frames, ignore_index=True)
    return summary, details


def build_identification_summary(
    monthly: pd.DataFrame,
    factor_label: str,
) -> pd.DataFrame:
    """把逐月诊断压缩成一行窗口级摘要。"""
    eligible = monthly["eligible_n"].astype(bool)
    ready = monthly["regression_ready"].astype(bool)
    eligible_n = int(eligible.sum())
    ready_n = int((eligible & ready).sum())
    return pd.DataFrame(
        [
            {
                "factor": factor_label,
                "months_with_complete_cases": int(len(monthly)),
                "eligible_months": eligible_n,
                "dummy_full_rank_months": int(
                    (eligible & monthly["dummy_full_rank"].astype(bool)).sum()
                ),
                "full_model_rank_months": ready_n,
                "failed_months_after_eligibility": eligible_n - ready_n,
                "regression_ready_rate": ready_n / eligible_n if eligible_n else np.nan,
                "months_all_groups_ge_5": int(
                    (eligible & monthly["all_groups_ge_5"].fillna(False).astype(bool)).sum()
                ),
                "months_all_groups_ge_10": int(
                    (eligible & monthly["all_groups_ge_10"].fillna(False).astype(bool)).sum()
                ),
            }
        ]
    )


def main() -> None:
    """运行月度可识别性检查和 beta 两两差异检验，并写出审计文件。"""
    args = parse_args()
    config = load_regression_config(args.model)
    factor_spec, factor_label = select_factor_spec(config, args.factor)

    panel_path = (
        project_path(args.panel)
        if args.panel is not None
        else project_path(str(config["regression_input_path"]))
    )
    model_output_dir = project_path(str(config["output_dir"]))
    monthly_path = (
        project_path(args.monthly_coefficients)
        if args.monthly_coefficients is not None
        else model_output_dir / "fama_macbeth_monthly_coefficients.csv"
    )
    output_dir = (
        project_path(args.output_dir)
        if args.output_dir is not None
        else model_output_dir / "winrates_check" / factor_label
    )

    if not panel_path.exists():
        raise FileNotFoundError(f"找不到回归输入面板：{panel_path}")
    if not monthly_path.exists():
        raise FileNotFoundError(f"找不到月度系数文件：{monthly_path}")

    print(f"模型：{args.model}")
    print(f"窗口：{factor_label}")
    print(f"回归面板：{panel_path}")
    print(f"月度系数：{monthly_path}")

    panel = pd.read_parquet(panel_path)
    sample, factor_cols, control_cols = prepare_regression_sample(
        panel,
        config,
        factor_spec,
        factor_label,
    )
    date_col = str(config["date_col"])
    min_cross_section_n = int(config["min_cross_section_n"])
    nw_lag = int(config["newey_west_lag"])

    monthly_identification = build_monthly_identification(
        sample,
        factor_cols,
        control_cols,
        date_col,
        min_cross_section_n,
    )
    identification_summary = build_identification_summary(
        monthly_identification,
        factor_label,
    )

    monthly_coefficients = pd.read_csv(monthly_path)
    pair_tests, pair_details = build_beta_pair_tests(
        monthly_coefficients,
        factor_cols,
        factor_label,
        date_col,
        nw_lag,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    monthly_identification.to_csv(
        output_dir / "monthly_dummy_identification.csv",
        index=False,
        encoding="utf-8-sig",
    )
    identification_summary.to_csv(
        output_dir / "dummy_identification_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pair_tests.to_csv(
        output_dir / "beta_pairwise_newey_west_tests.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pair_details.to_csv(
        output_dir / "beta_pairwise_monthly_differences.csv",
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "model": args.model,
        "factor": factor_label,
        "panel_path": str(panel_path),
        "monthly_coefficients_path": str(monthly_path),
        "output_dir": str(output_dir),
        "factor_columns": factor_cols,
        "control_columns": control_cols,
        "sample_filters": factor_filters(config, factor_spec, factor_label),
        "min_cross_section_n": min_cross_section_n,
        "newey_west_lag": nw_lag,
        "beta_pair_count": int(len(pair_tests)),
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_row = identification_summary.iloc[0]
    print(
        "月度可识别性："
        f"{int(summary_row['full_model_rank_months'])}/"
        f"{int(summary_row['eligible_months'])} 个合格月份可回归"
    )
    print(f"beta 两两检验：{len(pair_tests)} 对")
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    main()
