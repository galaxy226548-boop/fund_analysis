"""为“代表参数窗口 × 未来收益期限”回归结果生成可视化图表。

输入（只读，不修改）：

    D_analysis/output/fund_consistency/representative_window_horizon_tests/
    20260630_001020/representative_window_horizon_results.csv
    20260630_001020/term_structure_table.csv
    20260630_001020/representative_window_horizon_report.md

输出（全部写到独立的 plots 子目录，不覆盖已有结果）：

    D_analysis/output/fund_consistency/representative_window_horizon_tests/
    20260630_001020/plots/*.png
    20260630_001020/plots/visualization_summary.md

运行方式：

    .venv/bin/python D_analysis/scripts/plot_representative_window_horizon_results.py
"""

from __future__ import annotations

import os
import tempfile
import argparse
from pathlib import Path

# 部分沙箱环境下用户 home 目录的 matplotlib 缓存不可写，统一重定向到系统临时目录，
# 避免画图时反复打印无关警告。
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "fund_analysis_matplotlib_cache"),
)

import matplotlib

matplotlib.use("Agg")

import matplotlib.cm
import matplotlib.colors
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "representative_window_horizon_tests"
    / "20260630_001020"
)
RESULTS_CSV_PATH = RUN_DIR / "representative_window_horizon_results.csv"
TERM_STRUCTURE_CSV_PATH = RUN_DIR / "term_structure_table.csv"
REPORT_MD_PATH = RUN_DIR / "representative_window_horizon_report.md"
PLOTS_DIR = RUN_DIR / "plots"

SIGNIFICANCE_T_THRESHOLD = 1.96
DPI = 220

# y_horizon 在所有图表中必须固定为 1m -> 3m -> 6m -> 12m 的顺序。
Y_HORIZON_ORDER = (
    "future_return_1m",
    "future_return_3m",
    "future_return_6m",
    "future_return_12m",
)
Y_HORIZON_LABELS = {
    "future_return_1m": "1m",
    "future_return_3m": "3m",
    "future_return_6m": "6m",
    "future_return_12m": "12m",
}

# 系数组合按用户指定顺序排列，所有热力图从上往下保持这个顺序。
PARAM_NAME_ORDER = (
    "m1_n9",
    "m2_n6",
    "m2_n7",
    "m3_n4",
    "m3_n6",
    "m5_n12",
    "m6_n11",
    "m6_n12",
    "m9_n6",
)

SAMPLE_GROUP_ORDER = ("Full sample", "Top50", "Bottom50", "Top33", "Mid33", "Bottom33")

# Top33 重点窗口图使用的两类窗口。
TOP33_SHORT_REVERSAL_WINDOWS = ("m3_n6", "m2_n6", "m2_n7")
TOP33_MEDIUM_CONTINUATION_WINDOWS = ("m6_n12", "m6_n11", "m5_n12")
TOP33_KEY_WINDOWS = TOP33_SHORT_REVERSAL_WINDOWS + TOP33_MEDIUM_CONTINUATION_WINDOWS

SHORT_REVERSAL_COLOR = "#1f77b4"
MEDIUM_CONTINUATION_COLOR = "#d62728"


def parse_args() -> argparse.Namespace:
    """读取命令行参数，允许对不同时间戳结果目录重复生成图表。"""
    parser = argparse.ArgumentParser(
        description="为代表参数窗口 × 未来收益期限结果生成可视化图表。"
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=RUN_DIR,
        help="包含 representative_window_horizon_results.csv 的结果目录。",
    )
    return parser.parse_args()


def set_run_dir(run_dir: Path) -> None:
    """按命令行指定的结果目录更新输入和输出路径。"""
    global RUN_DIR, RESULTS_CSV_PATH, TERM_STRUCTURE_CSV_PATH, REPORT_MD_PATH, PLOTS_DIR
    RUN_DIR = run_dir if run_dir.is_absolute() else PROJECT_ROOT / run_dir
    RESULTS_CSV_PATH = RUN_DIR / "representative_window_horizon_results.csv"
    TERM_STRUCTURE_CSV_PATH = RUN_DIR / "term_structure_table.csv"
    REPORT_MD_PATH = RUN_DIR / "representative_window_horizon_report.md"
    PLOTS_DIR = RUN_DIR / "plots"


def require_input_files() -> None:
    """检查三个必需输入文件是否存在，缺失则清楚报错并终止。"""
    missing_paths = [
        path
        for path in (RESULTS_CSV_PATH, TERM_STRUCTURE_CSV_PATH, REPORT_MD_PATH)
        if not path.exists()
    ]
    if missing_paths:
        missing_list = "\n".join(f"- {path}" for path in missing_paths)
        raise FileNotFoundError(
            "缺少以下必需输入文件，无法生成可视化：\n"
            f"{missing_list}\n"
            "请确认已经运行过 run_representative_window_horizon_tests.py，"
            "且本脚本中的 RUN_DIR 与实际输出目录一致。"
        )


def load_results() -> pd.DataFrame:
    """读取回归结果表，并固定 y_horizon、param_name、sample_group 的展示顺序。"""
    results = pd.read_csv(RESULTS_CSV_PATH)

    results["y_horizon"] = pd.Categorical(
        results["y_horizon"], categories=Y_HORIZON_ORDER, ordered=True
    )
    results["param_name"] = pd.Categorical(
        results["param_name"], categories=PARAM_NAME_ORDER, ordered=True
    )
    results["sample_group"] = pd.Categorical(
        results["sample_group"], categories=SAMPLE_GROUP_ORDER, ordered=True
    )
    results["is_significant"] = results["t_FAC"].abs() >= SIGNIFICANCE_T_THRESHOLD
    return results


def build_param_palette() -> dict[str, tuple]:
    """给每个 param_name 分配固定颜色，保证多张图里同一个窗口颜色一致。"""
    color_map = plt.get_cmap("tab10")
    return {
        param_name: color_map(index % 10)
        for index, param_name in enumerate(PARAM_NAME_ORDER)
    }


PARAM_PALETTE = build_param_palette()


def plot_term_structure_lines(
    results: pd.DataFrame, value_column: str, y_label: str, output_name: str
) -> Path:
    """画期限结构折线图：x 轴是 y_horizon，每条线是一个 param_name，按 sample_group 分面。

    用空心圆圈标记 |t_FAC| < 1.96（不显著），实心圆圈标记显著点；
    coef 图和 t-stat 图共用这个函数。
    """
    sample_groups = [
        group for group in SAMPLE_GROUP_ORDER if group in results["sample_group"].unique()
    ]
    fig, axes = plt.subplots(
        1, len(sample_groups), figsize=(5.2 * len(sample_groups), 4.6), sharey=True
    )
    if len(sample_groups) == 1:
        axes = [axes]

    x_positions = range(len(Y_HORIZON_ORDER))

    for axis, sample_group in zip(axes, sample_groups):
        group_data = results[results["sample_group"] == sample_group]
        for param_name in PARAM_NAME_ORDER:
            param_data = group_data[group_data["param_name"] == param_name].sort_values(
                "y_horizon"
            )
            if param_data.empty:
                continue
            color = PARAM_PALETTE[param_name]
            axis.plot(
                x_positions,
                param_data[value_column].to_numpy(),
                color=color,
                linewidth=1.6,
                label=param_name,
                zorder=2,
            )
            # 显著点用实心圆，不显著点用空心圆。
            significant_mask = param_data["is_significant"].to_numpy()
            y_values = param_data[value_column].to_numpy()
            axis.scatter(
                [x for x, flag in zip(x_positions, significant_mask) if flag],
                [y for y, flag in zip(y_values, significant_mask) if flag],
                color=color,
                marker="o",
                s=46,
                edgecolors="black",
                linewidths=0.8,
                zorder=3,
            )
            axis.scatter(
                [x for x, flag in zip(x_positions, significant_mask) if not flag],
                [y for y, flag in zip(y_values, significant_mask) if not flag],
                facecolors="white",
                edgecolors=color,
                marker="o",
                s=40,
                linewidths=1.2,
                zorder=3,
            )

        if value_column == "t_FAC":
            axis.axhline(
                SIGNIFICANCE_T_THRESHOLD, color="gray", linestyle="--", linewidth=1.0
            )
            axis.axhline(
                -SIGNIFICANCE_T_THRESHOLD, color="gray", linestyle="--", linewidth=1.0
            )
        else:
            axis.axhline(0, color="gray", linestyle="-", linewidth=0.8)

        axis.set_xticks(list(x_positions))
        axis.set_xticklabels([Y_HORIZON_LABELS[h] for h in Y_HORIZON_ORDER])
        axis.set_title(sample_group, fontsize=12)
        axis.set_xlabel("未来收益期限")
        axis.grid(True, alpha=0.3)

    axes[0].set_ylabel(y_label)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="lower center",
        ncol=min(len(PARAM_NAME_ORDER), 9),
        bbox_to_anchor=(0.5, -0.05),
        fontsize=9,
        title="系数组合（实心=显著 |t|>=1.96，空心=不显著）",
    )
    fig.suptitle(y_label + " 期限结构（按样本组分面）", fontsize=14)
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))

    output_path = PLOTS_DIR / output_name
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return output_path


def choose_key_window_sample_group(results: pd.DataFrame) -> str:
    """选择重点窗口图使用的样本组；优先 Top33，其次 Top50。"""
    available_groups = set(results["sample_group"].astype(str).dropna())
    for sample_group in ("Top33", "Top50", "Full sample"):
        if sample_group in available_groups:
            return sample_group
    return sorted(available_groups)[0]


def plot_key_windows(results: pd.DataFrame) -> Path:
    """重点窗口图：短期反转 vs 中期持续候选窗口的 coef_FAC 期限结构对比。"""
    selected_sample_group = choose_key_window_sample_group(results)
    key_data = results[
        (results["sample_group"] == selected_sample_group)
        & (results["param_name"].isin(TOP33_KEY_WINDOWS))
    ]

    fig, axis = plt.subplots(figsize=(8, 5.5))
    x_positions = range(len(Y_HORIZON_ORDER))

    for param_name in TOP33_KEY_WINDOWS:
        param_data = key_data[key_data["param_name"] == param_name].sort_values(
            "y_horizon"
        )
        if param_data.empty:
            continue
        is_short_reversal = param_name in TOP33_SHORT_REVERSAL_WINDOWS
        color = SHORT_REVERSAL_COLOR if is_short_reversal else MEDIUM_CONTINUATION_COLOR
        linestyle = "-" if is_short_reversal else "--"
        axis.plot(
            x_positions,
            param_data["coef_FAC"].to_numpy(),
            color=color,
            linestyle=linestyle,
            linewidth=1.8,
            marker="o",
            markersize=5,
            label=param_name,
            zorder=2,
        )
        # 显著点额外描边标星，突出强调。
        significant_data = param_data[param_data["is_significant"]]
        if not significant_data.empty:
            sig_x = [
                x_positions[Y_HORIZON_ORDER.index(h)]
                for h in significant_data["y_horizon"]
            ]
            axis.scatter(
                sig_x,
                significant_data["coef_FAC"].to_numpy(),
                marker="*",
                s=170,
                color=color,
                edgecolors="black",
                linewidths=0.8,
                zorder=3,
            )

    axis.axhline(0, color="gray", linestyle="-", linewidth=0.8)
    axis.set_xticks(list(x_positions))
    axis.set_xticklabels([Y_HORIZON_LABELS[h] for h in Y_HORIZON_ORDER])
    axis.set_xlabel("未来收益期限")
    axis.set_ylabel("FAC 系数")
    axis.set_title(
        f"{selected_sample_group} 重点窗口：短期反转 vs 中期持续候选（★ = |t| >= 1.96）",
        fontsize=13,
    )
    axis.grid(True, alpha=0.3)

    # 自定义图例，额外标出两个类别的颜色含义。
    from matplotlib.lines import Line2D

    category_handles = [
        Line2D([0], [0], color=SHORT_REVERSAL_COLOR, linestyle="-", label="短期反转候选"),
        Line2D(
            [0], [0], color=MEDIUM_CONTINUATION_COLOR, linestyle="--", label="中期持续候选"
        ),
    ]
    window_handles, window_labels = axis.get_legend_handles_labels()
    first_legend = axis.legend(
        category_handles, ["短期反转候选", "中期持续候选"], loc="upper left", fontsize=9
    )
    axis.add_artist(first_legend)
    axis.legend(
        window_handles, window_labels, loc="lower left", fontsize=8, title="系数组合"
    )

    safe_group_name = selected_sample_group.replace(" ", "_").lower()
    output_path = PLOTS_DIR / f"{safe_group_name}_key_windows_coef.png"
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return output_path


def plot_significance_heatmaps(results: pd.DataFrame) -> list[Path]:
    """每个 sample_group 输出一张热力图：行是 param_name，列是 y_horizon，颜色是 t_FAC。

    绘图配色方案参考 plot_consistency_heatmaps.py 的 plot_t_stat_heatmap：
    - 不显著格子（abs(t_FAC) < 1.96）用灰阶表示，abs(t) 越接近 0 颜色越深；
    - 显著格子用 RdBu_r 发散色系，颜色方向表示系数方向；
    - 显著格子额外用黑框圈出，避免和灰色格子混淆。
    格子文字显示 coef_FAC 和 t_FAC，例如 "-0.08\\n(-2.84)"。
    """
    output_paths: list[Path] = []

    for sample_group in SAMPLE_GROUP_ORDER:
        group_data = results[results["sample_group"] == sample_group]
        if group_data.empty:
            continue

        t_matrix = group_data.pivot(
            index="param_name", columns="y_horizon", values="t_FAC"
        ).reindex(index=PARAM_NAME_ORDER, columns=Y_HORIZON_ORDER)
        coef_matrix = group_data.pivot(
            index="param_name", columns="y_horizon", values="coef_FAC"
        ).reindex(index=PARAM_NAME_ORDER, columns=Y_HORIZON_ORDER)

        values = t_matrix.to_numpy(dtype="float64")
        finite = np.isfinite(values)
        significant = finite & (np.abs(values) >= SIGNIFICANCE_T_THRESHOLD)
        nonsignificant = finite & ~significant

        # 先手工构造底图颜色。NaN 用浅灰；不显著格子用灰阶，abs(t) 越接近 0 越深。
        image_values = np.ones((*values.shape, 4), dtype="float64")
        image_values[:, :, :3] = 0.93
        image_values[:, :, 3] = 1.0

        # 灰阶区间比原脚本更浅（0.45~0.88），避免格子整体看起来太暗、文字不好读。
        gray_strength = np.zeros_like(values, dtype="float64")
        gray_strength[nonsignificant] = np.clip(
            np.abs(values[nonsignificant]) / SIGNIFICANCE_T_THRESHOLD, 0.0, 1.0
        )
        gray_rgb = 0.45 + 0.43 * gray_strength
        for channel in range(3):
            image_values[:, :, channel] = np.where(
                nonsignificant, gray_rgb, image_values[:, :, channel]
            )

        # 显著格子仍用发散色系，便于一眼区分负向/正向；和白色按 8:2 混合，
        # 让颜色淡一些，避免深红/深蓝盖住黑色文字导致不容易阅读。
        max_abs = (
            np.nanmax(np.abs(values[significant])) if significant.any() else 1.0
        )
        max_abs = max(float(max_abs), SIGNIFICANCE_T_THRESHOLD)
        norm = matplotlib.colors.Normalize(vmin=-max_abs, vmax=max_abs)
        cmap = plt.get_cmap("RdBu_r")
        significant_colors = cmap(norm(values[significant]))
        white = np.ones_like(significant_colors)
        white[:, 3] = 1.0
        image_values[significant] = 0.8 * significant_colors + 0.2 * white

        fig, axis = plt.subplots(figsize=(7.5, 6.5))
        axis.imshow(image_values)

        axis.set_xticks(range(len(Y_HORIZON_ORDER)))
        axis.set_xticklabels([Y_HORIZON_LABELS[h] for h in Y_HORIZON_ORDER])
        axis.set_yticks(range(len(PARAM_NAME_ORDER)))
        axis.set_yticklabels(PARAM_NAME_ORDER)
        axis.set_xticks(np.arange(-0.5, len(Y_HORIZON_ORDER), 1), minor=True)
        axis.set_yticks(np.arange(-0.5, len(PARAM_NAME_ORDER), 1), minor=True)
        # 全局样式表（seaborn-v0_8-whitegrid）会在主刻度（也就是每个格子中心）
        # 画网格线，导致格子里出现一条淡灰十字线；这里先关掉主网格，
        # 只保留格子边界处的白色分隔线（次刻度）。
        axis.grid(False, which="major")
        axis.grid(which="minor", color="white", linestyle="-", linewidth=0.8)
        axis.tick_params(which="minor", bottom=False, left=False)

        # 用黑框圈出显著格子，避免浅色显著值和灰色不显著值混在一起。
        for row_index, column_index in np.argwhere(significant):
            axis.add_patch(
                plt.Rectangle(
                    (column_index - 0.5, row_index - 0.5),
                    1,
                    1,
                    fill=False,
                    edgecolor="black",
                    linewidth=1.0,
                )
            )

        # 格子文字显示 coef_FAC 和 t_FAC。
        for row_index, row_name in enumerate(t_matrix.index):
            for column_index, column_name in enumerate(t_matrix.columns):
                coef_value = coef_matrix.loc[row_name, column_name]
                t_value = t_matrix.loc[row_name, column_name]
                if pd.isna(coef_value) or pd.isna(t_value):
                    continue
                axis.text(
                    column_index,
                    row_index,
                    f"{coef_value:.2f}\n({t_value:.2f})",
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color="black",
                )

        axis.set_title(
            f"不同收益窗口下显著性热力图 - {sample_group}",
            fontsize=11,
        )
        axis.set_xlabel("未来收益期限")
        axis.set_ylabel("系数组合")

        colorbar = fig.colorbar(
            matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), ax=axis, shrink=0.88
        )
        colorbar.set_label(
            f"显著 t 值颜色；灰色表示 |t| < {SIGNIFICANCE_T_THRESHOLD}"
        )

        safe_group_name = sample_group.replace(" ", "_")
        output_path = PLOTS_DIR / f"heatmap_tstat_{safe_group_name}.png"
        fig.tight_layout()
        fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
        plt.close(fig)
        output_paths.append(output_path)

    return output_paths


def compute_significant_counts(results: pd.DataFrame) -> pd.DataFrame:
    """统计每个 param_name 在所有 sample_group x y_horizon 组合中的正/负显著次数。"""
    significant_rows = results[results["is_significant"]]
    positive_counts = (
        significant_rows[significant_rows["coef_FAC"] > 0]
        .groupby("param_name", observed=True)
        .size()
        .reindex(PARAM_NAME_ORDER, fill_value=0)
    )
    negative_counts = (
        significant_rows[significant_rows["coef_FAC"] < 0]
        .groupby("param_name", observed=True)
        .size()
        .reindex(PARAM_NAME_ORDER, fill_value=0)
    )
    return pd.DataFrame(
        {"正向显著次数": positive_counts, "负向显著次数": negative_counts}
    )


def plot_significant_count_bar(counts: pd.DataFrame) -> Path:
    """画稳健候选 summary 堆叠柱状图：正向显著和负向显著分开统计、堆叠展示。"""
    fig, axis = plt.subplots(figsize=(8, 5))
    x_positions = np.arange(len(counts.index))

    axis.bar(
        x_positions,
        counts["正向显著次数"],
        color="#2ca02c",
        label="正向显著（|t|>=1.96 且系数>0）",
    )
    axis.bar(
        x_positions,
        counts["负向显著次数"],
        bottom=counts["正向显著次数"],
        color="#d62728",
        label="负向显著（|t|>=1.96 且系数<0）",
    )

    for x_position, param_name in zip(x_positions, counts.index):
        total_count = (
            counts.loc[param_name, "正向显著次数"]
            + counts.loc[param_name, "负向显著次数"]
        )
        if total_count > 0:
            axis.text(
                x_position,
                total_count + 0.1,
                str(int(total_count)),
                ha="center",
                va="bottom",
                fontsize=9,
            )

    axis.set_xticks(x_positions)
    axis.set_xticklabels(list(counts.index), rotation=30, ha="right")
    axis.set_ylabel("显著次数")
    axis.set_title("稳健候选汇总：各系数组合显著次数统计", fontsize=13)
    axis.legend(fontsize=9)
    axis.grid(True, axis="y", alpha=0.3)

    output_path = PLOTS_DIR / "significant_count_by_param.png"
    fig.tight_layout()
    fig.savefig(output_path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return output_path


def identify_supportive_windows(
    results: pd.DataFrame,
) -> tuple[list[str], list[str], list[str]]:
    """根据显著结果，归纳支持短期均值回归 / 中期持续性 / 建议进入回测的窗口列表。"""
    significant_rows = results[results["is_significant"]]

    # 短期均值回归：短窗口（1m/3m）上出现显著负系数。
    short_horizon_negative = significant_rows[
        (significant_rows["y_horizon"].isin(["future_return_1m", "future_return_3m"]))
        & (significant_rows["coef_FAC"] < 0)
    ]
    mean_reversion_windows = sorted(
        short_horizon_negative["param_name"].astype(str).unique().tolist(),
        key=lambda name: PARAM_NAME_ORDER.index(name),
    )

    # 中期持续性：中长窗口（6m/12m）上出现显著正系数。
    medium_horizon_positive = significant_rows[
        (significant_rows["y_horizon"].isin(["future_return_6m", "future_return_12m"]))
        & (significant_rows["coef_FAC"] > 0)
    ]
    continuation_windows = sorted(
        medium_horizon_positive["param_name"].astype(str).unique().tolist(),
        key=lambda name: PARAM_NAME_ORDER.index(name),
    )

    # 建议进入组合回测：在至少 2 个不同 y_horizon 上都显著的窗口，方向不要求一致，
    # 但需要在多个期限上都站得住，说明结果不是单一期限的偶然。
    counts_per_param = significant_rows.groupby("param_name", observed=True)[
        "y_horizon"
    ].nunique()
    backtest_candidates = sorted(
        counts_per_param[counts_per_param >= 2].index.astype(str).tolist(),
        key=lambda name: PARAM_NAME_ORDER.index(name),
    )

    return mean_reversion_windows, continuation_windows, backtest_candidates


def write_visualization_summary(
    results: pd.DataFrame,
    counts: pd.DataFrame,
    heatmap_paths: list[Path],
) -> Path:
    """生成可视化说明 Markdown，汇总每张图的看法和主要结论。"""
    mean_reversion_windows, continuation_windows, backtest_candidates = (
        identify_supportive_windows(results)
    )

    heatmap_lines = "\n".join(f"- `{path.name}`" for path in heatmap_paths)
    counts_lines = "\n".join(
        f"- {param_name}：正向显著 {row['正向显著次数']} 次，负向显著 {row['负向显著次数']} 次"
        for param_name, row in counts.iterrows()
    )

    n_sample_groups = results["sample_group"].nunique()
    n_y_horizons = results["y_horizon"].nunique()
    sample_group_names = " / ".join(results["sample_group"].astype(str).dropna().unique())
    key_sample_group = choose_key_window_sample_group(results)

    content = f"""# 代表参数窗口 x 未来收益期限 可视化说明

来源数据：`representative_window_horizon_results.csv`、`term_structure_table.csv`
显著性阈值：|t_FAC| >= {SIGNIFICANCE_T_THRESHOLD}

## 1. coef_term_structure_by_sample_group.png

期限结构折线图，x 轴是未来收益期限（1m/3m/6m/12m），y 轴是 FAC 系数，每条线代表一个
系数组合，按本次可用样本组（{sample_group_names}）分面展示。
实心圆点表示该点 |t_FAC| >= 1.96（显著），空心圆点表示不显著。

怎么看：在某个样本组的分面里，如果一条线在短期限（1m/3m）为负且显著，
说明该窗口在该样本组里支持短期均值回归；如果在长期限（6m/12m）为正且显著，
说明该窗口支持中期收益持续性。

## 2. tstat_term_structure_by_sample_group.png

与图 1 结构相同，但 y 轴换成 FAC 的 t 值，并加了 y=1.96 和 y=-1.96 两条参考虚线，
方便直接判断每个期限上的统计显著性，而不需要换算 p 值。

## 3. *_key_windows_coef.png

本次重点窗口图使用 `{key_sample_group}`。脚本优先使用 Top33；如果本次结果没有 Top33，则使用 Top50 或其他可用样本组。图中对比两类重点窗口：短期反转候选（m3_n6、m2_n6、m2_n7，蓝色实线）
和中期持续候选（m6_n12、m6_n11、m5_n12，红色虚线）的 coef_FAC 期限结构，
显著点额外用黑边五角星标出。

怎么看：蓝色线如果在短期限走低（负的 coef）且有星标，说明 `{key_sample_group}` 基金近期排名靠前
反而预示短期跑输，存在短期均值回归；红色线如果在长期限走高（正的 coef）且有星标，
说明 `{key_sample_group}` 基金中期排名具有持续性。

## 4. heatmap_tstat_<sample_group>.png（共 {len(heatmap_paths)} 张）

每个样本组一张热力图，行是系数组合，列是未来收益期限。配色方案与 plot_consistency_heatmaps.py 一致：
不显著格子（|t| < 1.96）用灰阶表示，abs(t) 越接近 0 颜色越深；显著格子用
红蓝发散色（红色正、蓝色负）并额外用黑框圈出，避免和灰色格子混淆。格子文字第一行是
FAC 系数，括号内是 t 值，例如 “-0.08\\n(-2.84)”。

生成的热力图文件：
{heatmap_lines}

怎么看：黑框圈住、颜色鲜艳的格子代表该窗口在该期限上统计上站得住；灰色格子说明
不显著，灰色越深代表 |t| 越接近 0。扫一行可以看出某个窗口在不同期限上的表现
走向，扫一列可以比较同一期限下不同窗口的差异。

## 5. significant_count_by_param.png

稳健候选汇总堆叠柱状图：统计每个系数组合在本次结果的全部 {n_sample_groups} 个样本组 x {n_y_horizons} 个
未来收益期限 = {n_sample_groups * n_y_horizons} 种组合中，|t| >= 1.96 的次数，绿色是正向显著次数，红色是负向显著
次数，柱子顶部数字是合计显著次数。

各窗口显著次数：
{counts_lines}

怎么看：柱子越高、且某一种颜色占主导，说明该窗口的显著结果方向越一致、越稳健；
如果一个窗口正负显著次数都不少，说明它在不同样本组或期限上方向不稳定，需要谨慎对待。

## 主要视觉结论

### 支持短期均值回归的窗口（短期限上系数显著为负）

{"".join(f"- {name}" + chr(10) for name in mean_reversion_windows) if mean_reversion_windows else "- 暂未发现满足条件的窗口"}

### 支持中期持续性的窗口（中长期限上系数显著为正）

{"".join(f"- {name}" + chr(10) for name in continuation_windows) if continuation_windows else "- 暂未发现满足条件的窗口"}

### 建议进入组合回测的窗口（至少在 2 个不同期限上显著）

{"".join(f"- {name}" + chr(10) for name in backtest_candidates) if backtest_candidates else "- 暂未发现满足条件的窗口"}

> 以上结论仅基于显著性次数的简单归纳，实际是否纳入回测仍需结合经济含义、
> 样本组间一致性和 r2 / adj_r2 等指标综合判断。
"""

    output_path = PLOTS_DIR / "visualization_summary.md"
    output_path.write_text(content, encoding="utf-8")
    return output_path


def main() -> None:
    """脚本入口：检查输入、画图、生成说明文档。"""
    args = parse_args()
    set_run_dir(args.run_dir)
    require_input_files()
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)

    results = load_results()

    plt.style.use("seaborn-v0_8-whitegrid" if "seaborn-v0_8-whitegrid" in plt.style.available else "default")
    plt.rcParams["axes.unicode_minus"] = False
    # 优先使用常见的中文兼容字体，找不到时退回 matplotlib 默认字体。
    plt.rcParams["font.sans-serif"] = [
        "PingFang SC",
        "Heiti SC",
        "Microsoft YaHei",
        "SimHei",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]

    coef_plot_path = plot_term_structure_lines(
        results, "coef_FAC", "FAC 系数", "coef_term_structure_by_sample_group.png"
    )
    tstat_plot_path = plot_term_structure_lines(
        results, "t_FAC", "FAC t 值", "tstat_term_structure_by_sample_group.png"
    )
    top33_plot_path = plot_key_windows(results)
    heatmap_paths = plot_significance_heatmaps(results)
    counts = compute_significant_counts(results)
    bar_plot_path = plot_significant_count_bar(counts)
    summary_path = write_visualization_summary(results, counts, heatmap_paths)

    print("已生成以下图表：")
    for path in [coef_plot_path, tstat_plot_path, top33_plot_path, *heatmap_paths, bar_plot_path]:
        print(f"- {path}")
    print(f"已生成可视化说明：{summary_path}")


if __name__ == "__main__":
    main()
