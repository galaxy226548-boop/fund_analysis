"""
基金一致性因子的 Fama-MacBeth 横截面回归。

这个脚本假设输入表已经完成了样本筛选、Consistency 构造和 winsorize。
脚本本身只负责：
1. 针对每个 Consistency 指标生成有效样本标记；
2. 按月做横截面 OLS；
3. 对月度系数序列计算 Fama-MacBeth 均值和 Newey-West 标准误；
4. 输出回归结果、月度系数和样本摘要。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


# =============================================================================
# 配置区：后续修改变量、样本门槛或 Newey-West 滞后阶数时，优先改这里
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = PROJECT_ROOT / "B_factors" / "output" / "panel_base.parquet"
OUTPUT_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "fama_macbeth_regression"
)

DATE_COL = "month_date"
INSAMPLE_COL = "is_insample_future_ret_6m"
Y_COL = "future_ret_6m"

CONSISTENCY_COLS = [
    "FAC_rank_vol_m3_n6_pairwise1",
    "FAC_rank_vol_m6_n3_pairwise1",
    "FAC_rank_vol_m6_n6_pairwise1",
    "FAC_rank_vol_m6_n12_pairwise1",
    "FAC_rank_vol_m12_n6_pairwise1",
]

CONTROL_COLS = [
    "CtrlRetSTR",
    "CtrlRetLTM",
    "CtrlVol",
    "as_偏股混合型基金",
    "Ctrl_log_fund_size",
    "Ctrl_fund_age",
]

MIN_CROSS_SECTION_N = 50
NEWEY_WEST_LAG = 5


def check_required_columns(df: pd.DataFrame) -> None:
    """检查输入表是否包含回归所需列，避免后面报错位置太晚、太难读。"""
    required_cols = [DATE_COL, INSAMPLE_COL, Y_COL] + CONSISTENCY_COLS + CONTROL_COLS
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"输入表缺少必要列：{missing_cols}")


def ols_cross_section(data: pd.DataFrame, x_cols: list[str]) -> pd.Series:
    """
    对单个月份做一次横截面 OLS。

    这里不用 statsmodels，是为了让脚本只依赖项目当前环境里已有的 numpy/scipy。
    np.linalg.lstsq 可以处理普通最小二乘；如果某个月变量共线导致秩不足，
    主程序会跳过该月并记录失败原因。
    """
    y = data[Y_COL].to_numpy(dtype=float)
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

    # R 方衡量当月横截面里模型解释了多少收益差异。
    # 如果当月 y 没有波动，ss_total 会等于 0，这时 R 方没有经济含义，记为缺失。
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
    return result


def newey_west_mean_se(values: pd.Series, lag: int) -> float:
    """
    计算“时间序列均值”的 Newey-West 标准误。

    Fama-MacBeth 的最终系数是每月系数的均值。由于未来 6 个月收益存在重叠，
    月度系数序列可能自相关，所以这里对均值的标准误做 Newey-West 调整。
    """
    x = values.dropna().to_numpy(dtype=float)
    t = len(x)
    if t <= 1:
        return np.nan

    centered = x - x.mean()
    max_lag = min(lag, t - 1)

    # gamma_0 是方差项，后面叠加 Bartlett 权重下的自协方差项。
    long_run_var = np.dot(centered, centered) / t
    for ell in range(1, max_lag + 1):
        weight = 1.0 - ell / (max_lag + 1.0)
        gamma = np.dot(centered[ell:], centered[:-ell]) / t
        long_run_var += 2.0 * weight * gamma

    # long_run_var 是月度系数序列的长期方差；均值的方差还要除以 t。
    return float(np.sqrt(max(long_run_var, 0.0) / t))


def summarize_factor_sample(
    df: pd.DataFrame,
    factor_col: str,
    required_cols: list[str],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """
    为单个 Consistency 指标生成有效样本，并统计每月可用样本数。

    不在全表统一 dropna，是因为 5 个 Consistency 指标的缺失情况不同。
    每个模型只按自己需要的列判断是否有效。
    """
    valid_mask = df[required_cols].notna().all(axis=1)
    valid_df = df.loc[valid_mask, [DATE_COL] + required_cols].copy()
    monthly_n = valid_df.groupby(DATE_COL).size().rename("n_valid")

    eligible_months = monthly_n[monthly_n >= MIN_CROSS_SECTION_N].index
    regression_df = valid_df[valid_df[DATE_COL].isin(eligible_months)].copy()

    sample_summary = {
        "factor": factor_col,
        "valid_rows": int(valid_mask.sum()),
        "valid_months": int(monthly_n.shape[0]),
        "eligible_months": int(len(eligible_months)),
        "min_cross_section_n": int(MIN_CROSS_SECTION_N),
        "monthly_n_min": int(monthly_n.min()) if len(monthly_n) else 0,
        "monthly_n_mean": float(monthly_n.mean()) if len(monthly_n) else np.nan,
        "monthly_n_median": float(monthly_n.median()) if len(monthly_n) else np.nan,
        "monthly_n_max": int(monthly_n.max()) if len(monthly_n) else 0,
    }
    return regression_df, sample_summary


def run_factor_regression(df: pd.DataFrame, factor_col: str) -> tuple[pd.DataFrame, dict[str, object], list[dict[str, object]]]:
    """完成单个 Consistency 指标的月度横截面回归和样本统计。"""
    x_cols = [factor_col] + CONTROL_COLS
    required_cols = [Y_COL] + x_cols
    regression_df, sample_summary = summarize_factor_sample(df, factor_col, required_cols)

    monthly_rows: list[pd.Series] = []
    skipped_months: list[dict[str, object]] = []

    for month, month_df in regression_df.groupby(DATE_COL, sort=True):
        try:
            coef = ols_cross_section(month_df, x_cols)
        except Exception as exc:
            skipped_months.append(
                {
                    "factor": factor_col,
                    "month_date": str(pd.Timestamp(month).date()),
                    "n_obs": int(len(month_df)),
                    "reason": str(exc),
                }
            )
            continue

        coef[DATE_COL] = month
        coef["factor"] = factor_col
        coef["n_obs"] = int(len(month_df))
        monthly_rows.append(coef)

    if monthly_rows:
        monthly_coef = pd.DataFrame(monthly_rows)
        ordered_cols = ["factor", DATE_COL, "n_obs", "r_squared", "adj_r_squared", "const"] + x_cols
        monthly_coef = monthly_coef[ordered_cols]
    else:
        monthly_coef = pd.DataFrame(
            columns=["factor", DATE_COL, "n_obs", "r_squared", "adj_r_squared", "const"] + x_cols
        )

    sample_summary["regression_months"] = int(len(monthly_coef))
    sample_summary["regression_rows"] = int(monthly_coef["n_obs"].sum()) if len(monthly_coef) else 0
    sample_summary["skipped_months_after_eligibility"] = int(len(skipped_months))
    sample_summary["avg_r_squared"] = (
        float(monthly_coef["r_squared"].mean()) if len(monthly_coef) else np.nan
    )
    sample_summary["avg_adj_r_squared"] = (
        float(monthly_coef["adj_r_squared"].mean()) if len(monthly_coef) else np.nan
    )

    return monthly_coef, sample_summary, skipped_months


def build_result_table(monthly_coef: pd.DataFrame, factor_col: str) -> pd.DataFrame:
    """把单个指标的月度系数序列汇总成 Fama-MacBeth 结果表。"""
    coef_cols = [
        col
        for col in monthly_coef.columns
        if col not in {"factor", DATE_COL, "n_obs", "r_squared", "adj_r_squared"}
    ]
    rows = []

    for variable in coef_cols:
        series = monthly_coef[variable].dropna()
        n_months = int(len(series))
        coef = float(series.mean()) if n_months else np.nan
        se = newey_west_mean_se(series, NEWEY_WEST_LAG) if n_months else np.nan
        t_stat = coef / se if se and not np.isnan(se) and se > 0 else np.nan
        p_value = (
            float(2.0 * stats.t.sf(abs(t_stat), df=max(n_months - 1, 1)))
            if not np.isnan(t_stat)
            else np.nan
        )

        rows.append(
            {
                "factor": factor_col,
                "variable": variable,
                "coef": coef,
                "newey_west_se": se,
                "t_stat": t_stat,
                "p_value": p_value,
                "n_months": n_months,
                "avg_monthly_n": float(monthly_coef["n_obs"].mean()) if len(monthly_coef) else np.nan,
                "total_regression_obs": int(monthly_coef["n_obs"].sum()) if len(monthly_coef) else 0,
                "avg_r_squared": float(monthly_coef["r_squared"].mean()) if len(monthly_coef) else np.nan,
                "avg_adj_r_squared": (
                    float(monthly_coef["adj_r_squared"].mean()) if len(monthly_coef) else np.nan
                ),
                "newey_west_lag": int(NEWEY_WEST_LAG),
                "min_cross_section_n": int(MIN_CROSS_SECTION_N),
            }
        )

    return pd.DataFrame(rows)


def significance_stars(p_value: float) -> str:
    """把 p 值转换成论文表格里常见的显著性星号。"""
    if pd.isna(p_value):
        return ""
    if p_value < 0.01:
        return "***"
    if p_value < 0.05:
        return "**"
    if p_value < 0.1:
        return "*"
    return ""


def build_cross_section_correlation_table(
    df: pd.DataFrame,
    factor_col: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    构建单个 Consistency 指标对应的截面相关系数表。

    注意这里不是直接对整个面板调用 corr()。正确做法是：
    1. 每个月先用当月横截面样本计算一次相关系数矩阵；
    2. 对每一对变量的月度相关系数序列取时间均值；
    3. 再对这条月度相关系数序列做均值是否为 0 的 t 检验。
    """
    variable_order = [factor_col] + CONTROL_COLS

    # 相关系数表只需要解释变量之间的关系，不把 future_ret_6m 放进去。
    # 这里仍沿用 n>=50 的门槛，避免某些月份横截面太小导致相关系数不稳。
    valid_df = df[[DATE_COL] + variable_order].dropna().copy()
    monthly_n = valid_df.groupby(DATE_COL).size()
    eligible_months = monthly_n[monthly_n >= MIN_CROSS_SECTION_N].index
    valid_df = valid_df[valid_df[DATE_COL].isin(eligible_months)].copy()

    monthly_corrs: list[pd.DataFrame] = []
    for month, month_df in valid_df.groupby(DATE_COL, sort=True):
        # 如果某个变量当月没有波动，pandas 会把相关系数记为 NaN；
        # 后面做均值和 t 检验时会自动跳过这些无效月份。
        corr = month_df[variable_order].corr()
        corr["month_date"] = month
        monthly_corrs.append(corr.reset_index(names="row_variable"))

    if not monthly_corrs:
        empty_table = pd.DataFrame(index=variable_order, columns=variable_order)
        empty_long = pd.DataFrame()
        empty_control = pd.DataFrame()
        return empty_table, empty_long, empty_control

    monthly_corr_df = pd.concat(monthly_corrs, ignore_index=True)
    long_corr = monthly_corr_df.melt(
        id_vars=["month_date", "row_variable"],
        value_vars=variable_order,
        var_name="col_variable",
        value_name="corr",
    )

    summary_rows = []
    for row_var in variable_order:
        for col_var in variable_order:
            corr_series = long_corr.loc[
                (long_corr["row_variable"] == row_var)
                & (long_corr["col_variable"] == col_var),
                "corr",
            ].dropna()
            n_months = int(len(corr_series))
            mean_corr = float(corr_series.mean()) if n_months else np.nan

            # 对角线固定为 1，不需要做显著性检验。
            if row_var == col_var or n_months <= 1:
                p_value = np.nan
            else:
                _, p_value = stats.ttest_1samp(corr_series, popmean=0.0)
                p_value = float(p_value)

            summary_rows.append(
                {
                    "factor": factor_col,
                    "row_variable": row_var,
                    "col_variable": col_var,
                    "mean_corr": mean_corr,
                    "p_value": p_value,
                    "stars": significance_stars(p_value),
                    "n_months": n_months,
                }
            )

    corr_summary = pd.DataFrame(summary_rows)

    # 输出展示表：上三角放均值相关系数，下三角放显著性星号，对角线为 1.000。
    display_names = {factor_col: "Consistency"}
    display_names.update({col: col for col in CONTROL_COLS})
    display_order = [display_names[col] for col in variable_order]
    display_table = pd.DataFrame(index=display_order, columns=display_order, dtype=object)
    for i, row_var in enumerate(variable_order):
        for j, col_var in enumerate(variable_order):
            row_name = display_names[row_var]
            col_name = display_names[col_var]
            if i == j:
                display_table.loc[row_name, col_name] = "1.000"
            elif i < j:
                value = corr_summary.loc[
                    (corr_summary["row_variable"] == row_var)
                    & (corr_summary["col_variable"] == col_var),
                    "mean_corr",
                ].iloc[0]
                display_table.loc[row_name, col_name] = f"{value:.3f}" if pd.notna(value) else ""
            else:
                stars = corr_summary.loc[
                    (corr_summary["row_variable"] == row_var)
                    & (corr_summary["col_variable"] == col_var),
                    "stars",
                ].iloc[0]
                display_table.loc[row_name, col_name] = stars

    # 为了不同 Consistency 指标的表可以合并保存，额外补一列 factor。
    display_table = display_table.reset_index(names="variable")
    display_table.insert(0, "factor", factor_col)

    control_corr = corr_summary[
        (corr_summary["row_variable"] == factor_col)
        & (corr_summary["col_variable"].isin(CONTROL_COLS))
    ].copy()
    control_corr = control_corr[
        ["factor", "col_variable", "mean_corr", "p_value", "stars", "n_months"]
    ].rename(columns={"col_variable": "control_variable"})

    return display_table, corr_summary, control_corr


def main() -> None:
    """脚本入口：读取输入、逐个指标回归、写出结果文件。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(INPUT_PATH)
    check_required_columns(df)

    # 输入表按设计应已经是样本内数据；这里仍做一次检查，避免误读其他表。
    insample_values = sorted(df[INSAMPLE_COL].dropna().unique().tolist())
    if insample_values != [1]:
        raise ValueError(
            f"输入表应只包含 {INSAMPLE_COL}=1 的样本，当前取值为：{insample_values}"
        )

    all_monthly_coef = []
    all_results = []
    sample_summaries = []
    skipped_months = []
    correlation_tables = []
    correlation_summaries = []
    consistency_control_corrs = []

    for factor_col in CONSISTENCY_COLS:
        monthly_coef, sample_summary, skipped = run_factor_regression(df, factor_col)
        result_table = build_result_table(monthly_coef, factor_col)
        corr_table, corr_summary, control_corr = build_cross_section_correlation_table(df, factor_col)

        all_monthly_coef.append(monthly_coef)
        all_results.append(result_table)
        sample_summaries.append(sample_summary)
        skipped_months.extend(skipped)
        correlation_tables.append(corr_table)
        correlation_summaries.append(corr_summary)
        consistency_control_corrs.append(control_corr)

    monthly_coef_df = pd.concat(all_monthly_coef, ignore_index=True)
    results_df = pd.concat(all_results, ignore_index=True)
    sample_summary_df = pd.DataFrame(sample_summaries)
    skipped_months_df = pd.DataFrame(skipped_months)
    correlation_table_df = pd.concat(correlation_tables, ignore_index=True)
    correlation_summary_df = pd.concat(correlation_summaries, ignore_index=True)
    consistency_control_corr_df = pd.concat(consistency_control_corrs, ignore_index=True)

    results_df.to_csv(OUTPUT_DIR / "fama_macbeth_results.csv", index=False, encoding="utf-8-sig")
    monthly_coef_df.to_csv(
        OUTPUT_DIR / "fama_macbeth_monthly_coefficients.csv",
        index=False,
        encoding="utf-8-sig",
    )
    sample_summary_df.to_csv(
        OUTPUT_DIR / "fama_macbeth_sample_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    skipped_months_df.to_csv(
        OUTPUT_DIR / "fama_macbeth_skipped_months.csv",
        index=False,
        encoding="utf-8-sig",
    )
    correlation_table_df.to_csv(
        OUTPUT_DIR / "correlation_table.csv",
        index=False,
        encoding="utf-8-sig",
    )
    correlation_summary_df.to_csv(
        OUTPUT_DIR / "correlation_summary_long.csv",
        index=False,
        encoding="utf-8-sig",
    )
    consistency_control_corr_df.to_csv(
        OUTPUT_DIR / "consistency_control_correlations.csv",
        index=False,
        encoding="utf-8-sig",
    )

    metadata = {
        "run_time": datetime.now().isoformat(timespec="seconds"),
        "input_path": str(INPUT_PATH),
        "output_dir": str(OUTPUT_DIR),
        "date_col": DATE_COL,
        "y_col": Y_COL,
        "consistency_cols": CONSISTENCY_COLS,
        "control_cols": CONTROL_COLS,
        "newey_west_lag": NEWEY_WEST_LAG,
        "min_cross_section_n": MIN_CROSS_SECTION_N,
        "input_rows": int(len(df)),
        "input_months": int(df[DATE_COL].nunique()),
        "note": "输入表已由上游程序完成样本内筛选、1-rank_vol 构造和月度横截面 1%/99% winsorize。",
    }
    with open(OUTPUT_DIR / "run_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Fama-MacBeth 回归完成，结果已输出到：{OUTPUT_DIR}")
    print(sample_summary_df.to_string(index=False))
    print("\nConsistency 与控制变量的截面相关系数均值：")
    print(consistency_control_corr_df.to_string(index=False))


if __name__ == "__main__":
    main()
