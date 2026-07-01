"""对 Fama-MacBeth 嵌套模型中的新增变量进行联合显著性检验。

脚本读取统一回归 registry 和现有 panel 数据，不改变主回归脚本及其输出。
对每套 Consistency 口径使用同一完整案例样本估计三个嵌套模型，再基于
月度横截面系数序列构造多变量 Newey-West/HAC Wald 检验。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_MODEL_KEY = "fm_baseline_interaction"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "D_analysis" / "output" / "mutual_significance_check"
MIN_RECOMMENDED_TIME_PERIODS = 12

RESULT_COLUMNS = [
    "run_id",
    "y_var",
    "consistency_var",
    "meanrank_var",
    "interaction_var",
    "test_name",
    "variables_tested",
    "n_time_periods",
    "df",
    "wald_stat",
    "p_value",
    "significance",
    "hac_lags",
    "r2_base",
    "adj_r2_base",
    "r2_full",
    "adj_r2_full",
    "delta_r2",
    "delta_adj_r2",
    "status",
    "note",
]


def parse_args() -> argparse.Namespace:
    """解析模型、输出目录和可选 HAC 滞后阶数。"""
    parser = argparse.ArgumentParser(
        description="基于月度 Fama-MacBeth 系数序列执行嵌套模型 Wald 检验。"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_KEY,
        help=f"regression registry 中的模型 key（默认：{DEFAULT_MODEL_KEY}）。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录；相对路径按项目根目录解析。",
    )
    parser.add_argument(
        "--hac-lags",
        type=int,
        default=None,
        help="覆盖 registry 中的 Newey-West 滞后阶数。",
    )
    return parser.parse_args()


def load_registry_config(model_key: str) -> dict[str, Any]:
    """按文件路径读取统一 registry，避免依赖运行时的 Python 包路径。"""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location("nested_test_registry", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(model_key)


def resolve_project_path(path_value: str | Path) -> Path:
    """把 registry 或命令行中的相对路径统一转换成项目绝对路径。"""
    path = Path(path_value).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_panel_data(input_path: Path) -> pd.DataFrame:
    """读取 Fama-MacBeth 主回归使用的同一份 panel 数据。"""
    if not input_path.exists():
        raise FileNotFoundError(f"找不到回归输入数据：{input_path}")

    suffix = input_path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(input_path)
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)
    raise ValueError(f"暂不支持的输入格式：{input_path.suffix}")


def apply_sample_filters(
    data: pd.DataFrame, sample_filters: dict[str, Any]
) -> pd.DataFrame:
    """应用 registry 中的基础样本条件，并兼容数值型 0/1 标记。"""
    missing = [column for column in sample_filters if column not in data.columns]
    if missing:
        raise ValueError(f"输入表缺少样本筛选列：{missing}")

    mask = pd.Series(True, index=data.index)
    for column, expected in sample_filters.items():
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            mask &= pd.to_numeric(data[column], errors="coerce").eq(float(expected))
        else:
            mask &= data[column].astype("string").eq(str(expected))
    return data.loc[mask].copy()


def infer_meanrank_var(consistency_var: str) -> str:
    """按现有命名规则把 FAC_rank_vol 口径映射到同期限 rank_mean。"""
    prefix = "FAC_rank_vol_"
    if not consistency_var.startswith(prefix):
        raise ValueError(
            "当前 registry 使用 RANK_MEAN 占位符，但无法从 Consistency 变量推导期限："
            f"{consistency_var}"
        )
    return consistency_var.replace(prefix, "rank_mean_", 1)


def build_model_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """为每套 Consistency 口径构造模型 0、模型 1 和模型 2。"""
    factors = list(config.get("factors") or [])
    controls = [str(column) for column in config.get("controls") or []]
    interactions = list(config.get("interactions") or [])
    main_effects = list(config.get("interaction_main_effects") or [])

    # 本脚本针对单一连续 Consistency 与对应 rank_mean 的模型。
    # 遇到 dummy 变量组时不静默猜测，应明确提示配置不适用。
    grouped_factors = [factor for factor in factors if not isinstance(factor, str)]
    if grouped_factors:
        raise ValueError(f"嵌套模型检验暂不支持 factor 变量组：{grouped_factors}")
    if "RANK_MEAN" not in main_effects:
        raise ValueError("registry 未配置 interaction_main_effects=['RANK_MEAN']。")
    if "{FAC,RANK_MEAN}" not in interactions:
        raise ValueError("registry 未配置 interactions=['{FAC,RANK_MEAN}']。")

    specs: list[dict[str, Any]] = []
    for factor in factors:
        consistency_var = str(factor)
        meanrank_var = infer_meanrank_var(consistency_var)
        # 使用真实变量名生成每套口径唯一的交互项名，便于 CSV 自解释。
        interaction_var = f"{consistency_var}__x__{meanrank_var}"
        specs.append(
            {
                "consistency_var": consistency_var,
                "meanrank_var": meanrank_var,
                "interaction_var": interaction_var,
                "model_0": controls,
                "model_1": controls + [consistency_var],
                "model_2": controls
                + [consistency_var, meanrank_var, interaction_var],
            }
        )
    return specs


def ols_cross_section(
    month_data: pd.DataFrame, y_var: str, x_vars: list[str]
) -> pd.Series:
    """估计单月横截面 OLS，并返回系数、R²和调整 R²。"""
    y = month_data[y_var].to_numpy(dtype=float)
    x = month_data[x_vars].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(month_data)), x])
    coefficient_names = ["const"] + x_vars

    beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    if rank < x.shape[1]:
        raise np.linalg.LinAlgError("设计矩阵秩不足，可能存在完全共线")

    residual = y - x @ beta
    ss_res = float(residual @ residual)
    centered_y = y - y.mean()
    ss_total = float(centered_y @ centered_y)
    n_obs = len(y)
    n_params = x.shape[1]
    r_squared = 1.0 - ss_res / ss_total if ss_total > 0 else np.nan
    adj_r_squared = (
        1.0 - (1.0 - r_squared) * (n_obs - 1) / (n_obs - n_params)
        if ss_total > 0 and n_obs > n_params
        else np.nan
    )

    result = pd.Series(beta, index=coefficient_names)
    result["n_obs"] = n_obs
    result["r_squared"] = r_squared
    result["adj_r_squared"] = adj_r_squared
    return result


def run_monthly_cross_sectional_regressions(
    data: pd.DataFrame,
    date_var: str,
    y_var: str,
    x_vars: list[str],
    min_cross_section_n: int,
    model_label: str,
) -> tuple[pd.DataFrame, list[str]]:
    """逐月执行横截面回归，跳过样本不足或矩阵奇异的月份。"""
    rows: list[pd.Series] = []
    warnings: list[str] = []

    for month, month_data in data.groupby(date_var, sort=True):
        month_text = str(pd.Timestamp(month).date())
        if len(month_data) < min_cross_section_n:
            warnings.append(
                f"{model_label}：{month_text} 样本量 {len(month_data)} "
                f"低于门槛 {min_cross_section_n}，已跳过。"
            )
            continue
        # 除项目统一门槛外，还要求观测数严格大于参数数，避免调整 R²无定义。
        if len(month_data) <= len(x_vars) + 1:
            warnings.append(
                f"{model_label}：{month_text} 样本量不多于参数数，已跳过。"
            )
            continue

        try:
            result = ols_cross_section(month_data, y_var, x_vars)
        except (np.linalg.LinAlgError, ValueError) as exc:
            warnings.append(f"{model_label}：{month_text} 回归失败，已跳过：{exc}")
            continue

        result[date_var] = month
        rows.append(result)

    ordered_columns = (
        [date_var, "n_obs", "r_squared", "adj_r_squared", "const"] + x_vars
    )
    if not rows:
        return pd.DataFrame(columns=ordered_columns), warnings
    return pd.DataFrame(rows)[ordered_columns], warnings


def compute_fmb_mean_and_hac_cov(
    coefficient_series: pd.DataFrame, hac_lags: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """计算系数向量均值及该均值的多变量 Newey-West/HAC 协方差。"""
    clean = coefficient_series.replace([np.inf, -np.inf], np.nan).dropna()
    values = clean.to_numpy(dtype=float)
    n_periods = len(values)
    if n_periods < 2:
        raise ValueError("有效月份少于 2，无法估计 HAC 协方差。")

    mean_vector = values.mean(axis=0)
    centered = values - mean_vector
    effective_lags = min(int(hac_lags), n_periods - 1)

    # 先估计系数序列的长期协方差，再除以 T 得到样本均值的协方差。
    long_run_cov = centered.T @ centered / n_periods
    for lag in range(1, effective_lags + 1):
        weight = 1.0 - lag / (effective_lags + 1.0)
        lag_cov = centered[lag:].T @ centered[:-lag] / n_periods
        long_run_cov += weight * (lag_cov + lag_cov.T)

    mean_cov = long_run_cov / n_periods
    # 浮点误差可能带来极小的非对称项，显式对称化便于后续求逆和诊断。
    mean_cov = (mean_cov + mean_cov.T) / 2.0
    return mean_vector, mean_cov, effective_lags


def wald_test(
    mean_vector: np.ndarray, mean_cov: np.ndarray
) -> tuple[float, int, float, bool, str]:
    """对平均系数向量等于零执行卡方 Wald 检验。"""
    df = int(len(mean_vector))
    if mean_cov.shape != (df, df):
        raise ValueError("HAC 协方差矩阵维度与待检验系数不一致。")
    if not np.isfinite(mean_cov).all():
        raise ValueError("HAC 协方差矩阵包含非有限值。")

    rank = int(np.linalg.matrix_rank(mean_cov))
    condition_number = float(np.linalg.cond(mean_cov))
    used_pseudo_inverse = rank < df or not np.isfinite(condition_number) or condition_number > 1e12
    if used_pseudo_inverse:
        inverse_cov = np.linalg.pinv(mean_cov)
        inverse_note = "HAC 协方差矩阵不可逆或接近奇异，使用 pseudo-inverse。"
    else:
        inverse_cov = np.linalg.inv(mean_cov)
        inverse_note = ""

    statistic = float(mean_vector.T @ inverse_cov @ mean_vector)
    # 理论上 Wald 统计量非负；仅容忍浮点运算造成的极小负数。
    if statistic < 0 and abs(statistic) < 1e-10:
        statistic = 0.0
    if statistic < 0:
        raise ValueError("Wald 统计量为负，HAC 协方差矩阵可能非半正定。")
    p_value = float(stats.chi2.sf(statistic, df=df))
    return statistic, df, p_value, used_pseudo_inverse, inverse_note


def significance_label(p_value: float) -> str:
    """把 p 值转换成最严格的常用显著性水平标签。"""
    if p_value < 0.01:
        return "1%"
    if p_value < 0.05:
        return "5%"
    if p_value < 0.10:
        return "10%"
    return "not_significant"


def summarize_model_fit(
    base_results: pd.DataFrame,
    full_results: pd.DataFrame,
    date_var: str,
) -> dict[str, float]:
    """在两个模型都成功的共同月份上汇总平均 R²及其增量。"""
    fit_columns = [date_var, "r_squared", "adj_r_squared"]
    paired = base_results[fit_columns].merge(
        full_results[fit_columns], on=date_var, suffixes=("_base", "_full")
    )
    if paired.empty:
        return {
            "r2_base": np.nan,
            "adj_r2_base": np.nan,
            "r2_full": np.nan,
            "adj_r2_full": np.nan,
            "delta_r2": np.nan,
            "delta_adj_r2": np.nan,
        }

    r2_base = float(paired["r_squared_base"].mean())
    adj_r2_base = float(paired["adj_r_squared_base"].mean())
    r2_full = float(paired["r_squared_full"].mean())
    adj_r2_full = float(paired["adj_r_squared_full"].mean())
    return {
        "r2_base": r2_base,
        "adj_r2_base": adj_r2_base,
        "r2_full": r2_full,
        "adj_r2_full": adj_r2_full,
        "delta_r2": r2_full - r2_base,
        "delta_adj_r2": adj_r2_full - adj_r2_base,
    }


def failed_rows_for_spec(
    run_id: str,
    y_var: str,
    spec: dict[str, Any],
    hac_lags: int,
    note: str,
) -> list[dict[str, Any]]:
    """变量缺失或整组失败时，为三项预定检验各输出一行 failed。"""
    tests = [
        ("add_consistency", [spec["consistency_var"]]),
        (
            "add_consistency_meanrank_interaction",
            [spec["consistency_var"], spec["meanrank_var"], spec["interaction_var"]],
        ),
        ("interaction_only", [spec["interaction_var"]]),
    ]
    rows = []
    for test_name, variables in tests:
        row = {column: np.nan for column in RESULT_COLUMNS}
        row.update(
            {
                "run_id": run_id,
                "y_var": y_var,
                "consistency_var": spec["consistency_var"],
                "meanrank_var": spec["meanrank_var"],
                "interaction_var": spec["interaction_var"],
                "test_name": test_name,
                "variables_tested": json.dumps(variables, ensure_ascii=False),
                "df": len(variables),
                "hac_lags": hac_lags,
                "status": "failed",
                "note": note,
            }
        )
        rows.append(row)
    return rows


def make_test_row(
    run_id: str,
    y_var: str,
    spec: dict[str, Any],
    test_name: str,
    variables_tested: list[str],
    coefficient_results: pd.DataFrame,
    base_results: pd.DataFrame,
    full_results: pd.DataFrame,
    date_var: str,
    hac_lags: int,
) -> tuple[dict[str, Any], list[str]]:
    """完成单项 Wald 检验，并组装一行标准输出。"""
    notes: list[str] = []
    warnings: list[str] = []
    fit_summary = summarize_model_fit(base_results, full_results, date_var)

    row: dict[str, Any] = {
        "run_id": run_id,
        "y_var": y_var,
        "consistency_var": spec["consistency_var"],
        "meanrank_var": spec["meanrank_var"],
        "interaction_var": spec["interaction_var"],
        "test_name": test_name,
        "variables_tested": json.dumps(variables_tested, ensure_ascii=False),
        "n_time_periods": 0,
        "df": len(variables_tested),
        "wald_stat": np.nan,
        "p_value": np.nan,
        "significance": np.nan,
        "hac_lags": hac_lags,
        **fit_summary,
        "status": "failed",
        "note": "",
    }

    try:
        mean_vector, mean_cov, effective_lags = compute_fmb_mean_and_hac_cov(
            coefficient_results[variables_tested], hac_lags
        )
        n_periods = int(coefficient_results[variables_tested].dropna().shape[0])
        statistic, df, p_value, _, inverse_note = wald_test(mean_vector, mean_cov)
        if effective_lags != hac_lags:
            notes.append(
                f"可用月份有限，HAC 实际滞后阶数由 {hac_lags} 调整为 {effective_lags}。"
            )
        if inverse_note:
            notes.append(inverse_note)
        if n_periods < MIN_RECOMMENDED_TIME_PERIODS:
            warning = (
                f"{spec['consistency_var']} / {test_name}：有效月份仅 {n_periods}，"
                f"少于建议门槛 {MIN_RECOMMENDED_TIME_PERIODS}。"
            )
            warnings.append(warning)
            notes.append(warning)

        row.update(
            {
                "n_time_periods": n_periods,
                "df": df,
                "wald_stat": statistic,
                "p_value": p_value,
                "significance": significance_label(p_value),
                "status": "success",
            }
        )
    except Exception as exc:
        row["note"] = f"Wald 检验失败：{exc}"
        warnings.append(f"{spec['consistency_var']} / {test_name}：{row['note']}")
        return row, warnings

    row["note"] = " ".join(notes)
    return row, warnings


def get_git_commit() -> str | None:
    """读取当前 Git commit；项目不是 Git 仓库时返回 None。"""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def save_outputs(
    results: pd.DataFrame,
    metadata: dict[str, Any],
    output_dir: Path,
    run_id: str,
) -> tuple[Path, Path]:
    """以唯一 run_id 保存 CSV 和 JSON，绝不覆盖已有结果。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"fmb_nested_wald_tests_{run_id}.csv"
    json_path = output_dir / f"fmb_nested_wald_tests_{run_id}.json"
    if csv_path.exists() or json_path.exists():
        raise FileExistsError(f"输出文件已存在，为避免覆盖已停止：{run_id}")

    results.to_csv(csv_path, index=False, encoding="utf-8-sig")
    metadata["output_csv_path"] = str(csv_path)
    metadata["output_json_path"] = str(json_path)
    with json_path.open("x", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2, default=str)
    return csv_path, json_path


def main() -> None:
    """运行全部嵌套模型、Wald 检验和结果登记。"""
    args = parse_args()
    config = load_registry_config(args.model)
    input_path = resolve_project_path(str(config["regression_input_path"]))
    output_dir = resolve_project_path(args.output_dir)
    date_var = str(config["date_col"])
    y_var = str(config["y"])
    min_cross_section_n = int(config["min_cross_section_n"])
    hac_lags = (
        int(args.hac_lags)
        if args.hac_lags is not None
        else int(config["newey_west_lag"])
    )
    if hac_lags < 0:
        raise ValueError("HAC 滞后阶数不能为负数。")

    created_at = datetime.now().astimezone()
    # 微秒精度使连续运行也能得到不同文件名，同时保留清晰的时间含义。
    run_id = created_at.strftime("%Y%m%d_%H%M%S_%f")
    panel = load_panel_data(input_path)
    if date_var not in panel.columns or y_var not in panel.columns:
        raise ValueError(f"输入表缺少日期列或因变量：{[date_var, y_var]}")
    panel[date_var] = pd.to_datetime(panel[date_var], errors="coerce")
    panel = panel.loc[panel[date_var].notna()].copy()
    panel = apply_sample_filters(panel, dict(config.get("sample_filters") or {}))

    model_specs = build_model_specs(config)
    all_rows: list[dict[str, Any]] = []
    all_warnings: list[str] = []

    for spec in model_specs:
        source_columns = (
            [date_var, y_var]
            + list(spec["model_0"])
            + [spec["consistency_var"], spec["meanrank_var"]]
        )
        source_columns = list(dict.fromkeys(source_columns))
        missing_columns = [column for column in source_columns if column not in panel.columns]
        if missing_columns:
            note = f"输入表缺少变量，整组检验跳过：{missing_columns}"
            all_warnings.append(f"{spec['consistency_var']}：{note}")
            all_rows.extend(failed_rows_for_spec(run_id, y_var, spec, hac_lags, note))
            continue

        # 三个嵌套模型统一使用模型 2 所需变量的完整案例样本，保证 R²增量可比。
        group_data = panel[source_columns].copy()
        numeric_columns = [y_var] + list(spec["model_0"]) + [
            spec["consistency_var"],
            spec["meanrank_var"],
        ]
        for column in numeric_columns:
            group_data[column] = pd.to_numeric(group_data[column], errors="coerce")
        group_data[spec["interaction_var"]] = (
            group_data[spec["consistency_var"]] * group_data[spec["meanrank_var"]]
        )
        complete_columns = [y_var] + list(spec["model_2"])
        group_data = group_data.dropna(subset=complete_columns).copy()

        if group_data.empty:
            note = "模型 2 所需变量取完整案例后没有可用观测。"
            all_warnings.append(f"{spec['consistency_var']}：{note}")
            all_rows.extend(failed_rows_for_spec(run_id, y_var, spec, hac_lags, note))
            continue

        # 三个模型已经使用同一完整案例样本，因此月份资格也只需判断一次。
        # 这样既确保嵌套模型比较基于完全相同的月份，也避免同一条样本不足警告
        # 分别被模型 0、1、2 重复记录三遍。
        monthly_counts = group_data.groupby(date_var).size()
        insufficient_months = monthly_counts[monthly_counts < min_cross_section_n]
        for month, n_obs in insufficient_months.items():
            all_warnings.append(
                f"{spec['consistency_var']} / common_sample："
                f"{pd.Timestamp(month).date()} 样本量 {int(n_obs)} "
                f"低于门槛 {min_cross_section_n}，三个模型均跳过该月。"
            )
        eligible_months = monthly_counts[monthly_counts >= min_cross_section_n].index
        group_data = group_data[group_data[date_var].isin(eligible_months)].copy()
        if group_data.empty:
            note = "没有月份达到最小横截面样本量门槛。"
            all_warnings.append(f"{spec['consistency_var']}：{note}")
            all_rows.extend(failed_rows_for_spec(run_id, y_var, spec, hac_lags, note))
            continue

        monthly_results: dict[str, pd.DataFrame] = {}
        for model_name in ["model_0", "model_1", "model_2"]:
            label = f"{spec['consistency_var']} / {model_name}"
            results, warnings = run_monthly_cross_sectional_regressions(
                group_data,
                date_var,
                y_var,
                list(spec[model_name]),
                min_cross_section_n,
                label,
            )
            monthly_results[model_name] = results
            all_warnings.extend(warnings)

        test_definitions = [
            (
                "add_consistency",
                [spec["consistency_var"]],
                "model_1",
            ),
            (
                "add_consistency_meanrank_interaction",
                [spec["consistency_var"], spec["meanrank_var"], spec["interaction_var"]],
                "model_2",
            ),
            (
                "interaction_only",
                [spec["interaction_var"]],
                "model_2",
            ),
        ]
        for test_name, variables, full_model_name in test_definitions:
            row, warnings = make_test_row(
                run_id,
                y_var,
                spec,
                test_name,
                variables,
                monthly_results[full_model_name],
                monthly_results["model_0"],
                monthly_results[full_model_name],
                date_var,
                hac_lags,
            )
            # interaction_only 的检验来自模型 2；R²字段也展示模型 2 相对模型 0，
            # 避免引入用户未定义的第四个受限模型。
            if test_name == "interaction_only":
                extra_note = "interaction_only 的拟合优度字段为模型 2 相对模型 0。"
                row["note"] = " ".join(part for part in [row["note"], extra_note] if part)
            all_rows.append(row)
            all_warnings.extend(warnings)

    results = pd.DataFrame(all_rows, columns=RESULT_COLUMNS)
    fixed_effects = [
        column for column in config.get("controls") or [] if str(column).startswith("as_")
    ]
    metadata: dict[str, Any] = {
        "run_id": run_id,
        "model_key": args.model,
        "input_data_path": str(input_path),
        "y_var": y_var,
        "control_vars": list(config.get("controls") or []),
        "fixed_effects": fixed_effects,
        "fixed_effects_note": (
            "固定效应变量同时保留在 control_vars 中；当前二分类样本里，"
            "as_偏股混合型基金加截距等价于投资类型固定效应。"
        ),
        "tested_consistency_vars": [spec["consistency_var"] for spec in model_specs],
        "meanrank_vars": [spec["meanrank_var"] for spec in model_specs],
        "interaction_vars": [spec["interaction_var"] for spec in model_specs],
        "hac_lags": hac_lags,
        "min_cross_section_n": min_cross_section_n,
        "created_at": created_at.isoformat(),
        "code_version_or_git_commit": get_git_commit(),
        "any_warnings": all_warnings,
    }
    csv_path, json_path = save_outputs(results, metadata, output_dir, run_id)

    failed_count = int(results["status"].ne("success").sum()) if len(results) else 0
    significant_5pct = int(
        (
            results["status"].eq("success")
            & pd.to_numeric(results["p_value"], errors="coerce").lt(0.05)
        ).sum()
    )
    print("Nested FMB Wald tests completed.")
    print(f"Output CSV: {csv_path}")
    print(f"Output JSON: {json_path}")
    print(f"Number of tests: {len(results)}")
    print(f"Number of failed tests: {failed_count}")
    print(f"Significant at 5%: {significant_5pct}")


if __name__ == "__main__":
    main()
