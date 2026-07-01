"""运行通过样本门槛的累积 Dummy Fama–MacBeth，并检验边际与累积效果。

累积编码为 Dk=1(hitcount>=k)。在同时放入 D1～Dn 后，Dk 的系数就是
Hit 从 k-1 增加到 k 的边际效果；Hit=h 相对 Hit=0 的累计预测效果则是
beta1+...+betah。累计效果的标准误直接对逐月系数和做 Newey–West，因而会
自动保留不同 beta 之间的协方差。
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib-winrate-dummy")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGRESSION_SCRIPT = (
    PROJECT_ROOT / "D_analysis" / "scripts" / "consistency_fama_mac_regression.py"
)
DEFAULT_PASSING_MODELS = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_identification_grid"
    / "passing_models.csv"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_cumulative_dummy_effects"
)
MODEL_SPECS = {
    "top50": ("fm_winrates_top50_nonoverlap", "Top 50"),
    "top33": ("fm_winrates_top33_nonoverlap", "Top 33"),
    "bottom33": ("fm_winrates_bottom33_nonoverlap", "Bottom 33"),
}
METRIC_ORDER = ["top50", "top33", "bottom33"]
METRIC_COLORS = {
    "top50": "#3B6FE2",
    "top33": "#2CA25F",
    "bottom33": "#E67E5F",
}
LABEL_PATTERN = re.compile(
    r"^winrate_cumulative_m(?P<m>[1-6])_n(?P<n>[1-6])_pairwise(?P<pairwise>[1-6])$"
)
HIT_PATTERN = re.compile(r"_hit_above(?P<zero_based>\d+)(?:_|$)")


def parse_args() -> argparse.Namespace:
    """读取上一轮通过清单和本轮输出目录。"""
    parser = argparse.ArgumentParser(description="运行累积 winrate Dummy 效果检验。")
    parser.add_argument("--passing-models", type=Path, default=DEFAULT_PASSING_MODELS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def load_regression_module(model_key: str) -> Any:
    """按模型 key 加载正式回归函数，使控制变量和 NW 参数来自 registry。"""
    original_argv = sys.argv[:]
    try:
        sys.argv = [str(REGRESSION_SCRIPT), "--model", model_key]
        spec = importlib.util.spec_from_file_location(
            f"cumulative_dummy_regression_{model_key}", REGRESSION_SCRIPT
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载回归脚本：{REGRESSION_SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = original_argv


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """对一个预先定义的检验 family 做 BH-FDR。"""
    output = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().sort_values()
    if valid.empty:
        return output
    m = len(valid)
    raw = valid.to_numpy(dtype=float) * m / np.arange(1, m + 1, dtype=float)
    adjusted = np.minimum.accumulate(raw[::-1])[::-1]
    output.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    return output


def hit_k(column: str) -> int:
    """把 hit_above0 转成经济解释中的第 1 次 Hit。"""
    match = HIT_PATTERN.search(column)
    if match is None:
        raise ValueError(f"无法从累积 Dummy 列名提取 k：{column}")
    return int(match.group("zero_based")) + 1


def cumulative_specs(module: Any) -> dict[tuple[int, int], tuple[str, ...]]:
    """从 registry 中提取 (m,n) 到累积 Dummy 列组的映射。"""
    suffixes = dict(module.FACTOR_GROUP_SUFFIXES)
    mapping: dict[tuple[int, int], tuple[str, ...]] = {}
    for raw_factor in module.CONSISTENCY_COLS:
        if not isinstance(raw_factor, (tuple, list)):
            continue
        factor = tuple(str(column) for column in raw_factor)
        label = str(suffixes.get(factor, ""))
        match = LABEL_PATTERN.fullmatch(label)
        if match is None:
            continue
        m = int(match.group("m"))
        n = int(match.group("n"))
        pairwise = int(match.group("pairwise"))
        if pairwise == m:
            mapping[(m, n)] = tuple(sorted(factor, key=hit_k))
    return mapping


def nw_mean_covariance(values: pd.DataFrame, lag: int) -> tuple[np.ndarray, int]:
    """计算多变量月度系数均值的 Newey–West 协方差矩阵。"""
    clean = values.dropna().to_numpy(dtype=float)
    t = len(clean)
    if t <= 1:
        return np.full((values.shape[1], values.shape[1]), np.nan), t
    centered = clean - clean.mean(axis=0, keepdims=True)
    long_run = centered.T @ centered / t
    for ell in range(1, min(lag, t - 1) + 1):
        weight = 1.0 - ell / (min(lag, t - 1) + 1.0)
        gamma = centered[ell:].T @ centered[:-ell] / t
        long_run += weight * (gamma + gamma.T)
    covariance = (long_run / t + (long_run / t).T) / 2.0
    return covariance, t


def two_sided_summary(series: pd.Series, lag: int) -> dict[str, float | int]:
    """汇总一个月度系数序列，并生成 t-based 95% NW 信赖区间。"""
    clean = series.dropna().astype(float)
    t = len(clean)
    estimate = float(clean.mean()) if t else np.nan
    if t <= 1:
        return {
            "estimate": estimate,
            "newey_west_se": np.nan,
            "t_stat": np.nan,
            "p_value": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "n_months": t,
        }
    # 复用与主回归完全相同的单变量 NW 公式。
    centered = clean.to_numpy() - estimate
    max_lag = min(lag, t - 1)
    long_run_var = float(centered @ centered / t)
    for ell in range(1, max_lag + 1):
        weight = 1.0 - ell / (max_lag + 1.0)
        gamma = float(centered[ell:] @ centered[:-ell] / t)
        long_run_var += 2.0 * weight * gamma
    se = float(np.sqrt(max(long_run_var, 0.0) / t))
    t_stat = estimate / se if se > 0 else np.nan
    p_value = (
        float(2.0 * stats.t.sf(abs(t_stat), df=t - 1))
        if np.isfinite(t_stat)
        else np.nan
    )
    critical = float(stats.t.ppf(0.975, df=t - 1))
    return {
        "estimate": estimate,
        "newey_west_se": se,
        "t_stat": t_stat,
        "p_value": p_value,
        "ci_low": estimate - critical * se,
        "ci_high": estimate + critical * se,
        "n_months": t,
    }


def joint_and_direction_tests(
    monthly: pd.DataFrame,
    factor_cols: list[str],
    expected_sign: int,
    lag: int,
) -> dict[str, Any]:
    """计算 HAC-Wald 联合检验和预期方向的 intersection–union 检验。"""
    beta_matrix = monthly[factor_cols].dropna()
    covariance, t = nw_mean_covariance(beta_matrix, lag)
    mean_beta = beta_matrix.mean().to_numpy(dtype=float)
    if t <= 1 or not np.isfinite(covariance).all():
        wald, df_rank, joint_p = np.nan, 0, np.nan
    else:
        df_rank = int(np.linalg.matrix_rank(covariance))
        wald = float(mean_beta @ np.linalg.pinv(covariance) @ mean_beta)
        joint_p = float(stats.chi2.sf(wald, df=df_rank)) if df_rank else np.nan

    one_sided_p: list[float] = []
    for column in factor_cols:
        summary = two_sided_summary(beta_matrix[column], lag)
        t_stat = float(summary["t_stat"])
        one_sided_p.append(
            float(stats.t.sf(expected_sign * t_stat, df=t - 1))
            if np.isfinite(t_stat) and t > 1
            else np.nan
        )
    valid_direction_p = [p for p in one_sided_p if np.isfinite(p)]
    # IUT 的 p 值取各单边检验中最大者：只有每个增量都显著朝预期方向才拒绝。
    direction_iut_p = max(valid_direction_p) if valid_direction_p else np.nan
    signed = expected_sign * mean_beta
    return {
        "joint_wald_stat": wald,
        "joint_wald_df": df_rank,
        "joint_p_value": joint_p,
        "expected_direction": "positive" if expected_sign > 0 else "negative",
        "expected_direction_count": int((signed > 0).sum()),
        "direction_share": float((signed > 0).mean()),
        "all_marginals_expected_direction": bool((signed > 0).all()),
        "direction_iut_p_value": direction_iut_p,
        "n_months": t,
    }


def p_short(value: float) -> str:
    """把 p/q 压缩成柱状图可读文本。"""
    if pd.isna(value):
        return "NA"
    if value < 0.001:
        return "<.001"
    return f"{value:.3f}".replace("0.", ".")


def plot_effect_pages(
    effects: pd.DataFrame,
    model_tests: pd.DataFrame,
    effect_type: str,
    output_dir: Path,
) -> None:
    """按 n 生成 2×3 多面板柱状图，柱旁标 raw p 和 FDR q。"""
    if effect_type not in {"adjacent", "cumulative"}:
        raise ValueError(f"未知效果类型：{effect_type}")
    effect_label = "Adjacent increment: Hit k−1 → k" if effect_type == "adjacent" else "Cumulative effect: Hit k vs Hit 0"
    file_label = "adjacent_marginal" if effect_type == "adjacent" else "cumulative_vs_hit0"
    metric_labels = {metric: MODEL_SPECS[metric][1] for metric in METRIC_ORDER}
    offsets = {"top50": -0.24, "top33": 0.0, "bottom33": 0.24}
    width = 0.22

    for n in range(2, 7):
        page = effects.loc[effects["n"].eq(n)].copy()
        if page.empty:
            continue
        # 同一页所有 m 使用共同 y 轴，便于横向比较经济量级。
        ci_bound = float(page[["ci_low_pp", "ci_high_pp"]].abs().max().max())
        y_limit = max(ci_bound * 1.38, 0.25)
        fig, axes = plt.subplots(2, 3, figsize=(19, 11), sharey=True)
        axes_flat = axes.ravel()

        for m, ax in enumerate(axes_flat, start=1):
            panel = page.loc[page["m"].eq(m)]
            x = np.arange(1, n + 1, dtype=float)
            for metric in METRIC_ORDER:
                group = panel.loc[panel["metric"].eq(metric)].sort_values("k")
                if group.empty:
                    continue
                positions = group["k"].to_numpy(dtype=float) + offsets[metric]
                estimate = group["estimate_pp"].to_numpy(dtype=float)
                lower = estimate - group["ci_low_pp"].to_numpy(dtype=float)
                upper = group["ci_high_pp"].to_numpy(dtype=float) - estimate
                significant = group["significant_fdr_5pct"].to_numpy(dtype=bool)
                bars = ax.bar(
                    positions,
                    estimate,
                    width=width,
                    color=METRIC_COLORS[metric],
                    alpha=0.9,
                    label=metric_labels[metric],
                    edgecolor=["#111111" if flag else "white" for flag in significant],
                    linewidth=[2.2 if flag else 0.5 for flag in significant],
                    yerr=np.vstack([lower, upper]),
                    capsize=2.5,
                    error_kw={"ecolor": "#222222", "elinewidth": 1.0},
                )
                for bar, (_, row) in zip(bars, group.iterrows()):
                    anchor = row["ci_high_pp"] if row["estimate_pp"] >= 0 else row["ci_low_pp"]
                    dy = 0.025 * y_limit * (1 if row["estimate_pp"] >= 0 else -1)
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        anchor + dy,
                        f"p/q\n{p_short(row['p_value'])}/{p_short(row['q_value'])}",
                        ha="center",
                        va="bottom" if row["estimate_pp"] >= 0 else "top",
                        fontsize=6.2,
                        rotation=90,
                        fontweight="bold" if row["significant_fdr_5pct"] else "normal",
                    )

            ax.axhline(0, color="#333333", linewidth=0.9)
            ax.set_xlim(0.45, n + 0.55)
            ax.set_ylim(-y_limit, y_limit)
            ax.set_xticks(x)
            ax.set_xticklabels(
                [f"{k-1}→{k}" for k in range(1, n + 1)]
                if effect_type == "adjacent"
                else [f"{k} vs 0" for k in range(1, n + 1)],
                fontsize=8,
            )
            ax.grid(axis="y", color="#dddddd", linewidth=0.7)
            ax.set_axisbelow(True)
            ax.set_title(f"m={m}, n={n}", fontsize=11, fontweight="bold")
            if m in {1, 4}:
                ax.set_ylabel("Future 6m return effect (pp)")

            # 相邻图额外显示模型层面的联合与方向检验 raw p/q。
            if effect_type == "adjacent":
                tests = model_tests.loc[
                    model_tests["m"].eq(m) & model_tests["n"].eq(n)
                ]
                notes = []
                for metric in METRIC_ORDER:
                    one = tests.loc[tests["metric"].eq(metric)]
                    if one.empty:
                        continue
                    row = one.iloc[0]
                    short = {"top50": "T50", "top33": "T33", "bottom33": "B33"}[metric]
                    notes.append(
                        f"{short} J {p_short(row.joint_p_value)}/{p_short(row.joint_q_value)}; "
                        f"D {p_short(row.direction_iut_p_value)}/{p_short(row.direction_iut_q_value)}"
                    )
                if notes:
                    ax.text(
                        0.01,
                        0.99,
                        "\n".join(notes),
                        transform=ax.transAxes,
                        ha="left",
                        va="top",
                        fontsize=6.5,
                        color="#333333",
                        bbox={"facecolor": "white", "alpha": 0.72, "edgecolor": "none", "pad": 2},
                    )

        handles = [
            plt.Rectangle((0, 0), 1, 1, color=METRIC_COLORS[metric], label=metric_labels[metric])
            for metric in METRIC_ORDER
        ]
        # 双行主标题本身较高，因此把图例单独下移，并在二者之间留出明确空白。
        # 同时把子图区域的上边界下移，避免图例压到第一行面板标题。
        fig.legend(
            handles=handles,
            loc="upper center",
            ncol=3,
            frameon=False,
            bbox_to_anchor=(0.5, 0.905),
        )
        fig.suptitle(
            f"Cumulative Dummy effects, n={n}\n{effect_label}; 95% t-based Newey–West CI",
            fontsize=17,
            fontweight="bold",
            y=0.995,
            linespacing=1.25,
        )
        footer = (
            "Bar label = raw p / BH-FDR q; thick border = q<0.05. "
            + (
                "Panel note: J=joint HAC-Wald p/q; D=direction IUT p/q."
                if effect_type == "adjacent"
                else "FDR family contains all cumulative Hit-vs-0 tests."
            )
        )
        fig.text(0.5, 0.012, footer, ha="center", fontsize=9, color="#444444")
        fig.tight_layout(rect=(0.025, 0.045, 0.985, 0.855), h_pad=2.4, w_pad=1.2)
        fig.savefig(
            output_dir / f"{file_label}_n{n}_multipanel.png",
            dpi=220,
            bbox_inches="tight",
        )
        plt.close(fig)


def build_report(
    adjacent: pd.DataFrame,
    cumulative: pd.DataFrame,
    model_tests: pd.DataFrame,
    output_path: Path,
) -> None:
    """把四类检验的经济量级和显著性写成中文报告。"""
    lines = [
        "# 累积 Dummy Fama–MacBeth 效果报告",
        "",
        "## 解释与检验口径",
        "",
        "- `Dk=1(hitcount>=k)`；同时放入 D1～Dn 后，beta_k 是 Hit 从 k−1 增加到 k 的边际效果。",
        "- Hit h 相对 Hit 0 的累计效果为 beta_1+...+beta_h；信赖区间来自逐月系数和的 NW(5) 时间序列。",
        "- 相邻增量、累计效果、模型联合检验、方向 IUT 分属四个预先定义的 family，各自做 BH-FDR。",
        "- 方向 IUT：Top 50/33 要求每个增量均为正；Bottom 33 要求每个增量均为负。"
        "raw p 取模型内各单边检验的最大值，只有全部增量都显著朝预期方向才拒绝。",
        "",
        "## 总览",
        "",
        "| 口径 | 相邻检验数 | 相邻 q<0.05 | 累积检验数 | 累积 q<0.05 | 联合 q<0.05 | 方向 q<0.05 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for metric in METRIC_ORDER:
        a = adjacent.loc[adjacent["metric"].eq(metric)]
        c = cumulative.loc[cumulative["metric"].eq(metric)]
        t = model_tests.loc[model_tests["metric"].eq(metric)]
        lines.append(
            f"| {MODEL_SPECS[metric][1]} | {len(a)} | {int(a.significant_fdr_5pct.sum())} | "
            f"{len(c)} | {int(c.significant_fdr_5pct.sum())} | "
            f"{int(t.joint_significant_fdr_5pct.sum())} | {int(t.direction_significant_fdr_5pct.sum())} |"
        )

    lines.extend(
        [
            "",
            "## 经济量级分布",
            "",
            "| 口径 | 相邻 beta 范围（百分点） | 相邻中位数 | 累积效果范围（百分点） | 累积中位数 | 预期方向相邻增量占比 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for metric in METRIC_ORDER:
        a = adjacent.loc[adjacent["metric"].eq(metric)]
        c = cumulative.loc[cumulative["metric"].eq(metric)]
        expected_sign = -1 if metric == "bottom33" else 1
        expected_share = float((expected_sign * a["estimate"] > 0).mean())
        lines.append(
            f"| {MODEL_SPECS[metric][1]} | {a.estimate_pp.min():.2f}～{a.estimate_pp.max():.2f} | "
            f"{a.estimate_pp.median():.2f} | {c.estimate_pp.min():.2f}～{c.estimate_pp.max():.2f} | "
            f"{c.estimate_pp.median():.2f} | {expected_share:.1%} |"
        )

    lines.extend(["", "## FDR 显著的相邻增量", ""])
    sig_adjacent = adjacent.loc[adjacent["significant_fdr_5pct"]].sort_values(
        ["metric", "q_value", "n", "m", "k"]
    )
    if sig_adjacent.empty:
        lines.append("没有相邻增量在统一 family 内达到 q<0.05。")
    else:
        lines.extend(
            [
                "| 口径 | m | n | k−1→k | beta（百分点） | 95% CI | p | q | 月份 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in sig_adjacent.itertuples():
            lines.append(
                f"| {row.display_name} | {row.m} | {row.n} | {row.k-1}→{row.k} | "
                f"{row.estimate_pp:.3f} | [{row.ci_low_pp:.3f}, {row.ci_high_pp:.3f}] | "
                f"{row.p_value:.4g} | {row.q_value:.4g} | {row.n_months} |"
            )

    lines.extend(["", "## FDR 显著的累计 Hit-vs-0 效果", ""])
    sig_cumulative = cumulative.loc[cumulative["significant_fdr_5pct"]].sort_values(
        ["metric", "q_value", "n", "m", "k"]
    )
    if sig_cumulative.empty:
        lines.append("没有累计效果在统一 family 内达到 q<0.05。")
    else:
        lines.extend(
            [
                "| 口径 | m | n | Hit k vs 0 | 效果（百分点） | 95% CI | p | q | 月份 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in sig_cumulative.itertuples():
            lines.append(
                f"| {row.display_name} | {row.m} | {row.n} | {row.k} | "
                f"{row.estimate_pp:.3f} | [{row.ci_low_pp:.3f}, {row.ci_high_pp:.3f}] | "
                f"{row.p_value:.4g} | {row.q_value:.4g} | {row.n_months} |"
            )

    lines.extend(["", "## 模型层面结论", ""])
    for metric in METRIC_ORDER:
        tests = model_tests.loc[model_tests["metric"].eq(metric)]
        all_direction = int(tests["all_marginals_expected_direction"].sum())
        lines.append(
            f"- {MODEL_SPECS[metric][1]}：{all_direction}/{len(tests)} 个模型的点估计全部朝预期方向；"
            f"联合 Wald q<0.05 有 {int(tests.joint_significant_fdr_5pct.sum())} 个，"
            f"严格方向 IUT q<0.05 有 {int(tests.direction_significant_fdr_5pct.sum())} 个。"
        )
    joint_significant = model_tests.loc[
        model_tests["joint_significant_fdr_5pct"]
    ].sort_values(["metric", "joint_q_value", "n", "m"])
    lines.extend(
        [
            "",
            "### FDR 显著的联合 HAC-Wald 检验",
            "",
            "| 口径 | m | n | Wald | df | p | q | 预期方向增量占比 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in joint_significant.itertuples():
        lines.append(
            f"| {row.display_name} | {row.m} | {row.n} | {row.joint_wald_stat:.2f} | "
            f"{row.joint_wald_df} | {row.joint_p_value:.4g} | {row.joint_q_value:.4g} | "
            f"{row.direction_share:.0%} |"
        )
    lines.extend(
        [
            "",
            "Bottom 33 的负边际或负累计效果应解释为：持续处于后 33% 的次数增加，"
            "预测未来 6 个月收益更低。负号在这个口径下是理论预期方向。",
            "",
            "## 注意事项",
            "",
            "同一 (m,n) 内的边际 beta 高度相关，因此累计效果必须使用逐月系数和计算 NW 标准误，"
            "不能把各 beta 的标准误直接相加。联合检验使用多变量 HAC 均值协方差及 Wald 统计量；"
            "若 HAC 协方差降秩，自由度采用其数值秩。",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """运行 64 个累积 Dummy 模型，并输出四类检验、图表和报告。"""
    args = parse_args()
    passing_path = args.passing_models if args.passing_models.is_absolute() else PROJECT_ROOT / args.passing_models
    output_dir = args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
    if not passing_path.exists():
        raise FileNotFoundError(f"找不到通过模型清单：{passing_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)

    passing = pd.read_csv(passing_path)
    passing = passing.loc[passing["passes_initial_gate"].astype(bool)].copy()
    if len(passing) != 64:
        raise ValueError(f"预期 64 个通过模型，实际读取 {len(passing)} 个。")

    adjacent_rows: list[dict[str, Any]] = []
    cumulative_rows: list[dict[str, Any]] = []
    model_rows: list[dict[str, Any]] = []
    full_result_frames: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []
    sample_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    for metric, (model_key, display_name) in MODEL_SPECS.items():
        module = load_regression_module(model_key)
        spec_mapping = cumulative_specs(module)
        selected = passing.loc[passing["metric"].eq(metric)].sort_values(["n", "m"])
        selected_specs = [spec_mapping[(int(row.m), int(row.n))] for row in selected.itertuples()]
        required_columns = list(
            dict.fromkeys(
                [
                    module.DATE_COL,
                    module.Y_COL,
                    *module.CONTROL_COLS,
                    *module.SAMPLE_FILTERS,
                    *[column for factor in selected_specs for column in factor],
                ]
            )
        )
        panel = pd.read_parquet(module.INPUT_PATH, columns=required_columns)

        for selection, factor_spec in zip(selected.itertuples(), selected_specs):
            m, n = int(selection.m), int(selection.n)
            factor_cols = list(factor_spec)
            factor_df = module.apply_sample_filters(
                panel, module.get_filters_for_factor(factor_spec)
            )
            monthly, sample_summary, skipped_records = module.run_factor_regression(
                factor_df, factor_spec
            )
            factor_label = module.factor_label_for_spec(factor_spec)
            result_table = module.build_result_table(monthly, factor_label)
            result_table.insert(0, "metric", metric)
            result_table.insert(1, "m", m)
            result_table.insert(2, "n", n)
            full_result_frames.append(result_table)

            base = {
                "metric": metric,
                "display_name": display_name,
                "model_key": model_key,
                "factor": factor_label,
                "m": m,
                "n": n,
                "pairwise": m,
            }
            for column in factor_cols:
                k = hit_k(column)
                summary = two_sided_summary(monthly[column], module.NEWEY_WEST_LAG)
                adjacent_rows.append({**base, "k": k, "variable": column, **summary})

                # 每个月先把 beta1..betak 相加，再对这条月度累计序列做 NW。
                cumulative_series = monthly[factor_cols[:k]].sum(axis=1)
                cumulative_summary = two_sided_summary(
                    cumulative_series, module.NEWEY_WEST_LAG
                )
                cumulative_rows.append({**base, "k": k, **cumulative_summary})

            expected_sign = -1 if metric == "bottom33" else 1
            tests = joint_and_direction_tests(
                monthly, factor_cols, expected_sign, module.NEWEY_WEST_LAG
            )
            model_rows.append({**base, **tests})

            monthly.insert(0, "metric", metric)
            monthly.insert(1, "m", m)
            monthly.insert(2, "n", n)
            monthly_frames.append(monthly)
            sample_summary.update({"metric": metric, "m": m, "n": n})
            sample_rows.append(sample_summary)
            for skipped_record in skipped_records:
                skipped_record.update({"metric": metric, "m": m, "n": n})
                skipped_rows.append(skipped_record)
        del panel, module
        gc.collect()

    adjacent = pd.DataFrame(adjacent_rows).sort_values(["metric", "n", "m", "k"])
    cumulative = pd.DataFrame(cumulative_rows).sort_values(["metric", "n", "m", "k"])
    model_tests = pd.DataFrame(model_rows).sort_values(["metric", "n", "m"])

    # 四类研究主张分别校正，不把模型层检验和单个增量混在同一个 family。
    adjacent["q_value"] = benjamini_hochberg(adjacent["p_value"])
    adjacent["significant_fdr_5pct"] = adjacent["q_value"].lt(0.05)
    cumulative["q_value"] = benjamini_hochberg(cumulative["p_value"])
    cumulative["significant_fdr_5pct"] = cumulative["q_value"].lt(0.05)
    model_tests["joint_q_value"] = benjamini_hochberg(model_tests["joint_p_value"])
    model_tests["joint_significant_fdr_5pct"] = model_tests["joint_q_value"].lt(0.05)
    model_tests["direction_iut_q_value"] = benjamini_hochberg(
        model_tests["direction_iut_p_value"]
    )
    model_tests["direction_significant_fdr_5pct"] = model_tests[
        "direction_iut_q_value"
    ].lt(0.05)

    for frame in (adjacent, cumulative):
        frame["estimate_pp"] = frame["estimate"] * 100.0
        frame["ci_low_pp"] = frame["ci_low"] * 100.0
        frame["ci_high_pp"] = frame["ci_high"] * 100.0

    adjacent.to_csv(output_dir / "adjacent_marginal_effects_fdr.csv", index=False)
    cumulative.to_csv(output_dir / "cumulative_hit_vs_hit0_effects_fdr.csv", index=False)
    model_tests.to_csv(output_dir / "model_joint_direction_tests_fdr.csv", index=False)
    pd.concat(full_result_frames, ignore_index=True).to_csv(
        output_dir / "fama_macbeth_full_results.csv", index=False
    )
    pd.concat(monthly_frames, ignore_index=True).to_csv(
        output_dir / "fama_macbeth_monthly_coefficients.csv", index=False
    )
    pd.DataFrame(sample_rows).to_csv(
        output_dir / "fama_macbeth_sample_summary.csv", index=False
    )
    pd.DataFrame(skipped_rows).to_csv(
        output_dir / "fama_macbeth_skipped_months.csv", index=False
    )

    plot_effect_pages(adjacent, model_tests, "adjacent", chart_dir)
    plot_effect_pages(cumulative, model_tests, "cumulative", chart_dir)
    build_report(adjacent, cumulative, model_tests, output_dir / "effect_report.md")

    metadata = {
        "models_run": int(len(model_tests)),
        "dependent_variable": "future_ret_6m",
        "dummy_encoding": "Dk=1(hitcount>=k)",
        "controls": list(load_regression_module("fm_winrates_top50_nonoverlap").CONTROL_COLS),
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "fdr_families": {
            "adjacent_marginal_effects": int(len(adjacent)),
            "cumulative_hit_vs_hit0_effects": int(len(cumulative)),
            "joint_hac_wald_models": int(model_tests["joint_p_value"].notna().sum()),
            "direction_iut_models": int(model_tests["direction_iut_p_value"].notna().sum()),
        },
        "significant_fdr_5pct": {
            "adjacent": int(adjacent["significant_fdr_5pct"].sum()),
            "cumulative": int(cumulative["significant_fdr_5pct"].sum()),
            "joint": int(model_tests["joint_significant_fdr_5pct"].sum()),
            "direction": int(model_tests["direction_significant_fdr_5pct"].sum()),
        },
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        "完成："
        f"{len(model_tests)} 个模型，{len(adjacent)} 个相邻增量，"
        f"{len(cumulative)} 个累计效果。"
    )
    print(
        "FDR q<0.05："
        f"相邻 {int(adjacent.significant_fdr_5pct.sum())}，"
        f"累计 {int(cumulative.significant_fdr_5pct.sum())}，"
        f"联合 {int(model_tests.joint_significant_fdr_5pct.sum())}，"
        f"方向 {int(model_tests.direction_significant_fdr_5pct.sum())}。"
    )
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    main()
