"""
按分组对比 panel_base.parquet 中 rank volatility 指标的分布。

这个脚本是固定配置型入口，默认做下面这件事：
- 读取 A_data/output/panel_base.parquet；
- 对 5 个 rank_vol_*_pairwise1 列逐个分析；
- 每个分析列都按“全样本 + investment_type 各取值”生成对比图；
- 同时输出 Excel 统计表，方便和图片互相核对。

输出位置：
A_data/output/descriptive_comparison/
"""

from __future__ import annotations

import importlib.util
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOL_SCRIPT = PROJECT_ROOT / "A_data/scripts/4_descriptive_analysis_tool.py"

INPUT_FILE = PROJECT_ROOT / "A_data/output/panel_base.parquet"
OUTPUT_DIR = PROJECT_ROOT / "A_data/output/descriptive_comparison"
PREFIX = "原型默认系列X_by_investment_type"

GROUP_COLUMN = "investment_type"
COLUMNS = (
    "rank_vol_m3_n6_pairwise1",
    "rank_vol_m6_n3_pairwise1",
    "rank_vol_m6_n6_pairwise1",
    "rank_vol_m6_n12_pairwise1",
    "rank_vol_m12_n6_pairwise1",
)

HIST_BINS = 30
PLOTS_PER_ROW = 3


def load_descriptive_tool():
    """
    动态加载已有的描述性统计工具脚本。

    这个文件名以数字开头，不能直接写成普通的 import。
    所以这里用 importlib 按文件路径加载，这样可以继续复用里面已经写好的
    读文件、计算统计量、CDF 阈值等函数。
    """
    spec = importlib.util.spec_from_file_location("descriptive_analysis_tool", TOOL_SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载工具脚本：{TOOL_SCRIPT}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


desc_tool = load_descriptive_tool()

# 工具脚本会在导入 matplotlib 前设置缓存目录。这里在它加载完成后再导入 pyplot，
# 可以沿用同一套受限环境下更稳定的 matplotlib 配置。
import matplotlib.pyplot as plt
from matplotlib import font_manager


def configure_chinese_font() -> None:
    """
    为图片标题配置中文字体。

    如果不主动设置，matplotlib 常常会使用默认的 DejaVu Sans，
    这个字体不包含中文字符，保存图片时标题可能显示成方框。
    这里按 macOS 和常见中文环境的字体名称依次尝试，找到一个可用字体就使用它。
    """
    candidate_fonts = (
        "Arial Unicode MS",
        "Heiti TC",
        "Songti SC",
        "STHeiti",
        "PingFang SC",
        "Noto Sans CJK SC",
        "SimHei",
    )

    for font_name in candidate_fonts:
        try:
            font_manager.findfont(font_name, fallback_to_default=False)
        except ValueError:
            continue

        plt.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        return


configure_chinese_font()


@dataclass(frozen=True)
class SampleGroup:
    """
    保存一个样本组的信息。

    - raw_name：写入 Excel 的完整组名，保留数据里的原始取值。
    - display_name：画图标题里展示的短名称。
    - data：这个组对应的 DataFrame。
    """

    raw_name: str
    display_name: str
    data: pd.DataFrame


def validate_input_columns(df: pd.DataFrame) -> None:
    """检查输入数据中是否包含分组列和所有待分析列。"""
    required_columns = [GROUP_COLUMN, *COLUMNS]
    missing_columns = [column for column in required_columns if column not in df.columns]

    if missing_columns:
        raise ValueError(f"输入数据缺少这些列：{missing_columns}")


def shorten_group_name(value: object) -> str:
    """
    把分组取值整理成适合放在图片标题里的短名称。

    Excel 里仍保留原始值；这里只影响图标题。
    比如数据里是“偏股混合型基金”，标题显示为“偏股混合型”。
    """
    name = str(value)
    if name.endswith("基金"):
        return name[: -len("基金")]
    return name


def build_sample_groups(df: pd.DataFrame) -> list[SampleGroup]:
    """构造“全样本 + 各分组取值”的样本组列表。"""
    groups = [
        SampleGroup(raw_name="全样本", display_name="全样本", data=df),
    ]

    # drop_duplicates 会保留数据中第一次出现的顺序，比简单排序更贴近原数据。
    unique_values = df[GROUP_COLUMN].dropna().drop_duplicates()

    for value in unique_values:
        group_df = df.loc[df[GROUP_COLUMN] == value]
        groups.append(
            SampleGroup(
                raw_name=str(value),
                display_name=shorten_group_name(value),
                data=group_df,
            )
        )

    if len(groups) == 1:
        raise ValueError(f"{GROUP_COLUMN} 没有任何非空分组取值。")

    return groups


def clean_series(group: SampleGroup, column: str) -> pd.Series:
    """取出某个样本组中的某个分析列，并转成数值后去掉缺失值。"""
    numeric = pd.to_numeric(group.data[column], errors="coerce")
    return numeric.dropna()


def get_subplot_grid(plot_count: int) -> tuple[int, int]:
    """根据小图数量计算大画布的行数和列数。"""
    row_count = math.ceil(plot_count / PLOTS_PER_ROW)
    return row_count, PLOTS_PER_ROW


def hide_extra_axes(axes, used_count: int) -> None:
    """隐藏没有用到的小图格子。"""
    for ax in axes.flat[used_count:]:
        ax.set_visible(False)


def calculate_shared_limits(values: pd.Series) -> tuple[float, float]:
    """
    根据全样本有效值计算共享横轴或纵轴范围。

    共享坐标轴能让不同分组的小图更容易横向比较。
    """
    if values.empty:
        return 0.0, 1.0

    min_value = float(values.min())
    max_value = float(values.max())

    if min_value == max_value:
        padding = abs(min_value) * 0.05 if min_value != 0 else 0.05
        return min_value - padding, max_value + padding

    padding = (max_value - min_value) * 0.05
    return min_value - padding, max_value + padding


def make_axes(plot_count: int):
    """创建每行 3 个小图的大画布。"""
    row_count, col_count = get_subplot_grid(plot_count)
    fig, axes = plt.subplots(row_count, col_count, figsize=(5.5 * col_count, 3.8 * row_count))
    return fig, np.atleast_2d(axes)


def plot_boxplot_comparison(column: str, groups: list[SampleGroup], output_path: Path) -> None:
    """为单个分析列生成按样本组对比的箱线图。"""
    full_clean = clean_series(groups[0], column)
    y_min, y_max = calculate_shared_limits(full_clean)

    fig, axes = make_axes(len(groups))

    for idx, group in enumerate(groups):
        ax = axes.flat[idx]
        clean = clean_series(group, column)
        title = f"{group.display_name}\nN={len(clean):,}"

        if clean.empty:
            ax.text(0.5, 0.5, "无有效样本", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title, fontsize=11)
            ax.set_ylim(y_min, y_max)
            continue

        ax.boxplot([clean], tick_labels=[""], showfliers=True)
        ax.set_title(title, fontsize=11)
        ax.set_ylabel("value")
        ax.set_ylim(y_min, y_max)
        ax.grid(axis="y", linestyle="--", alpha=0.35)

    hide_extra_axes(axes, len(groups))
    fig.suptitle(f"{column} - Boxplot Comparison", fontsize=15)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_histogram_comparison(column: str, groups: list[SampleGroup], output_path: Path) -> None:
    """为单个分析列生成按样本组对比的直方图。"""
    full_clean = clean_series(groups[0], column)
    x_min, x_max = calculate_shared_limits(full_clean)
    bins = np.histogram_bin_edges(full_clean, bins=HIST_BINS) if not full_clean.empty else HIST_BINS

    fig, axes = make_axes(len(groups))

    for idx, group in enumerate(groups):
        ax = axes.flat[idx]
        clean = clean_series(group, column)
        title = f"{group.display_name}\nN={len(clean):,}"

        if clean.empty:
            ax.text(0.5, 0.5, "无有效样本", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title, fontsize=11)
            ax.set_xlim(x_min, x_max)
            continue

        ax.hist(clean, bins=bins, color="#4C78A8", edgecolor="white", alpha=0.85)
        ax.axvline(0, color="#D62728", linestyle="--", linewidth=1, label="0")
        ax.axvline(clean.mean(), color="#F58518", linestyle="-", linewidth=1, label="mean")
        ax.axvline(clean.median(), color="#54A24B", linestyle="-", linewidth=1, label="median")
        ax.set_title(title, fontsize=11)
        ax.set_xlabel("value")
        ax.set_ylabel("frequency")
        ax.set_xlim(x_min, x_max)
        ax.legend(fontsize=8)

    hide_extra_axes(axes, len(groups))
    fig.suptitle(f"{column} - Histogram Comparison", fontsize=15)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_cdf_comparison(column: str, groups: list[SampleGroup], output_path: Path) -> None:
    """为单个分析列生成按样本组对比的累计分布函数图。"""
    full_clean = clean_series(groups[0], column)
    x_min, x_max = calculate_shared_limits(full_clean)

    fig, axes = make_axes(len(groups))

    for idx, group in enumerate(groups):
        ax = axes.flat[idx]
        clean = clean_series(group, column).sort_values()
        title = f"{group.display_name}\nN={len(clean):,}"

        if clean.empty:
            ax.text(0.5, 0.5, "无有效样本", ha="center", va="center", transform=ax.transAxes)
            ax.set_title(title, fontsize=11)
            ax.set_xlim(x_min, x_max)
            ax.set_ylim(0, 1.02)
            continue

        y_values = np.arange(1, len(clean) + 1) / len(clean)
        ax.plot(clean, y_values, color="#4C78A8", linewidth=1.8)

        for threshold in desc_tool.CDF_THRESHOLDS:
            rate = (clean <= threshold).mean()
            ax.axvline(threshold, color="#D62728", linestyle="--", linewidth=0.8, alpha=0.7)
            ax.text(
                threshold,
                min(rate + 0.03, 0.98),
                f"{threshold:.2f}: {rate:.1%}",
                fontsize=8,
                rotation=90,
                va="bottom",
                ha="right",
            )

        ax.set_title(title, fontsize=11)
        ax.set_xlabel("value")
        ax.set_ylabel("cumulative probability")
        ax.set_xlim(x_min, x_max)
        ax.set_ylim(0, 1.02)
        ax.grid(linestyle="--", alpha=0.3)

    hide_extra_axes(axes, len(groups))
    fig.suptitle(f"{column} - CDF Comparison", fontsize=15)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def calculate_comparison_tables(
    df: pd.DataFrame,
    groups: list[SampleGroup],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """计算 Excel 里的三张对比表。"""
    descriptive_rows = []
    cdf_rows = []
    summary_rows = []

    for group in groups:
        summary_row = {
            "group": group.raw_name,
            "display group": group.display_name,
            "row count": len(group.data),
        }

        for column in COLUMNS:
            numeric_series = pd.to_numeric(group.data[column], errors="coerce")
            clean = numeric_series.dropna()

            descriptive_row = {
                "column": column,
                "group": group.raw_name,
                "display group": group.display_name,
            }
            descriptive_row.update(desc_tool.calculate_one_column_stats(numeric_series))
            descriptive_rows.append(descriptive_row)

            cdf_row = {
                "column": column,
                "group": group.raw_name,
                "display group": group.display_name,
                "N": int(clean.count()),
            }
            for threshold in desc_tool.CDF_THRESHOLDS:
                count = int((clean <= threshold).sum())
                rate = count / len(clean) if len(clean) > 0 else np.nan
                cdf_row[f"count <= {threshold:.2f}"] = count
                cdf_row[f"rate <= {threshold:.2f}"] = rate
            cdf_rows.append(cdf_row)

            summary_row[f"{column} N"] = int(clean.count())

        summary_rows.append(summary_row)

    return (
        pd.DataFrame(descriptive_rows),
        pd.DataFrame(cdf_rows),
        pd.DataFrame(summary_rows),
    )


def save_comparison_excel(
    descriptive_table: pd.DataFrame,
    cdf_threshold_table: pd.DataFrame,
    group_summary_table: pd.DataFrame,
    output_path: Path,
) -> None:
    """保存分组对比 Excel，并设置基础列宽。"""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        descriptive_table.to_excel(writer, sheet_name="descriptive", index=False)
        cdf_threshold_table.to_excel(writer, sheet_name="cdf_thresholds", index=False)
        group_summary_table.to_excel(writer, sheet_name="group_summary", index=False)

        for sheet_name in writer.book.sheetnames:
            ws = writer.book[sheet_name]
            ws.freeze_panes = "A2"

            for column_cells in ws.columns:
                column_letter = column_cells[0].column_letter
                max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
                ws.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 45)


def main() -> None:
    """运行全部固定配置的分组对比描述性分析。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_df = desc_tool.read_input_file(INPUT_FILE)
    validate_input_columns(raw_df)
    groups = build_sample_groups(raw_df)

    descriptive_table, cdf_threshold_table, group_summary_table = calculate_comparison_tables(raw_df, groups)
    excel_path = OUTPUT_DIR / f"{PREFIX}_comparison.xlsx"
    save_comparison_excel(descriptive_table, cdf_threshold_table, group_summary_table, excel_path)

    for column in COLUMNS:
        boxplot_path = OUTPUT_DIR / f"{PREFIX}_{column}_boxplot_comparison.png"
        histogram_path = OUTPUT_DIR / f"{PREFIX}_{column}_histogram_comparison.png"
        cdf_path = OUTPUT_DIR / f"{PREFIX}_{column}_cdf_comparison.png"

        plot_boxplot_comparison(column, groups, boxplot_path)
        plot_histogram_comparison(column, groups, histogram_path)
        plot_cdf_comparison(column, groups, cdf_path)

    print(f"已读取：{INPUT_FILE}")
    print(f"分组列：{GROUP_COLUMN}")
    print(f"样本组：{', '.join(group.raw_name for group in groups)}")
    print(f"已分析列数：{len(COLUMNS)}")
    print(f"Excel 对比统计表：{excel_path}")
    print(f"图片输出目录：{OUTPUT_DIR}")


if __name__ == "__main__":
    main()
