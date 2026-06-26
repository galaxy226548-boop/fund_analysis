"""
descriptive_analysis.py

用途：
对一列或多列数值数据做描述性统计，并输出 Excel 表格和常用分布图。

默认输出位置：
A_data/output/descriptive_analysis/

示例：
1. 分析 Excel 中所有可转成数字的列：
   .venv/bin/python A_data/scripts/descriptive_analysis.py --input A_data/output/panel_base.parquet

2. 只分析指定列：
   .venv/bin/python A_data/scripts/descriptive_analysis.py --input data.xlsx --columns rank_vol_3_6 rank_vol_6_6

3. 指定 Excel sheet 和输出目录：
   .venv/bin/python A_data/scripts/descriptive_analysis.py --input data.xlsx --sheet Sheet1 --output-dir A_data/output/my_desc

4. 不想每次手动输入文件名前缀，也可以直接传 --prefix：
   .venv/bin/python A_data/scripts/descriptive_analysis.py --input data.xlsx --prefix rank_vol_test

5. 只保留某一列等于指定值的行，再做描述性统计：
   .venv/bin/python A_data/scripts/descriptive_analysis.py \
     --input A_data/output/panel_base.parquet \
     --filter-column is_insample_future_ret_6m \
     --filter-value 1 \
     --columns rank_vol_m3_n6_pairwise1 rank_vol_m6_n3_pairwise1
"""

from __future__ import annotations

import argparse
import math
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "A_data/output/descriptive_analysis"
MATPLOTLIB_CACHE_DIR = PROJECT_ROOT / "A_data/output/.matplotlib_cache"
PERCENTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
CDF_THRESHOLDS = (0.05, 0.10, 0.15, 0.20)

# Matplotlib 默认可能想把缓存写到用户目录；在受限环境里会报 warning。
# 这里改到项目 output 下面，保证脚本在当前项目里可以稳定运行。
MATPLOTLIB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MATPLOTLIB_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(MATPLOTLIB_CACHE_DIR))

import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="对一列或多列数值数据做描述性统计、直方图、箱线图和累计分布函数图。"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="输入文件路径，支持 .csv / .xlsx / .xls / .parquet。",
    )
    parser.add_argument(
        "--columns",
        nargs="*",
        default=None,
        help="需要分析的列名。若不填写，则自动分析所有可转成数字的列。",
    )
    parser.add_argument(
        "--sheet",
        default=0,
        help="Excel 的 sheet 名或序号。默认读取第一个 sheet。",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录。默认是 A_data/output/descriptive_analysis。",
    )
    parser.add_argument(
        "--hist-bins",
        type=int,
        default=30,
        help="直方图分箱数量。默认 30。",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="输出文件名前缀。若不填写，脚本会在运行时询问。",
    )
    parser.add_argument(
        "--filter-column",
        default=None,
        help="筛选用的列名。例如 is_insample_future_ret_6m。需要和 --filter-value 一起使用。",
    )
    parser.add_argument(
        "--filter-value",
        default=None,
        help="筛选用的目标值。例如 1。脚本会先尝试按数字比较，失败时再按文本比较。",
    )
    return parser.parse_args()


def clean_filename_prefix(raw_prefix: str) -> str:
    """
    把用户输入的文件名前缀整理成适合保存文件的形式。

    例子：
    - "rank vol 3/6" 会变成 "rank_vol_3_6"
    - 如果用户直接回车，就使用 "descriptive"
    """
    prefix = raw_prefix.strip()

    if not prefix:
        return "descriptive"

    # 文件名里不适合出现 / \ : * ? " < > | 等字符，这里统一替换成下划线。
    prefix = re.sub(r'[\\/:*?"<>|\s]+', "_", prefix)
    prefix = prefix.strip("._-")

    if not prefix:
        return "descriptive"

    return prefix


def ask_output_prefix(prefix_from_args: str | None) -> str:
    """
    决定本次输出文件名前缀。

    如果命令行传了 --prefix，就直接用；
    如果没传，就在 cmd / terminal 中询问用户。
    """
    if prefix_from_args is not None:
        return clean_filename_prefix(prefix_from_args)

    raw_prefix = input("请为本次生成的系列文件命名（将作为文件名前缀，直接回车默认 descriptive）：")
    return clean_filename_prefix(raw_prefix)


def normalize_sheet_arg(sheet_arg: str):
    """
    argparse 读进来的 sheet 一律是字符串。
    如果用户输入的是 0、1、2 这种数字，就转成 int；否则保留 sheet 名。
    """
    if isinstance(sheet_arg, str) and sheet_arg.isdigit():
        return int(sheet_arg)
    return sheet_arg


def read_input_file(input_path: Path, sheet=0) -> pd.DataFrame:
    """根据文件后缀读取数据。"""
    if not input_path.exists():
        raise FileNotFoundError(f"未找到输入文件：{input_path}")

    suffix = input_path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path, sheet_name=sheet)
    if suffix == ".parquet":
        return pd.read_parquet(input_path)

    raise ValueError(f"暂不支持该文件类型：{suffix}。请使用 .csv / .xlsx / .xls / .parquet。")


def validate_filter_args(filter_column: str | None, filter_value: str | None) -> None:
    """
    检查筛选参数是否成对出现。

    用户如果只写了 --filter-column，却忘了写 --filter-value，脚本不知道要筛选成什么值。
    反过来，只写 --filter-value 也不行，因为脚本不知道要看哪一列。
    """
    has_filter_column = filter_column is not None
    has_filter_value = filter_value is not None

    if has_filter_column != has_filter_value:
        raise ValueError("--filter-column 和 --filter-value 需要同时填写，或同时不填写。")


def build_filter_mask(series: pd.Series, filter_value: str) -> pd.Series:
    """
    根据一列数据和用户输入的目标值，生成 True/False 筛选条件。

    返回的 mask 可以理解成一串“保留/不保留”的标记：
    - True：这一行要保留；
    - False：这一行要丢掉。

    这里优先尝试数字比较，是为了让命令行里的 "1" 可以匹配数据里的整数 1 或浮点数 1.0。
    如果目标值不是数字，例如 "A类"，就退回到文本比较。
    """
    numeric_filter_value = pd.to_numeric(pd.Series([filter_value]), errors="coerce").iloc[0]

    # 如果用户输入的筛选值可以转成数字，就尽量按数字比较。
    if pd.notna(numeric_filter_value):
        numeric_series = pd.to_numeric(series, errors="coerce")
        return numeric_series == numeric_filter_value

    # 如果不是数字，就按文本比较。astype("string") 可以比较好地处理缺失值。
    return series.astype("string") == filter_value


def apply_row_filter(
    df: pd.DataFrame,
    filter_column: str | None,
    filter_value: str | None,
) -> pd.DataFrame:
    """
    如果用户传入筛选参数，就先筛选行；如果没传，就原样返回数据。

    例如：
    --filter-column is_insample_future_ret_6m --filter-value 1
    表示只保留 is_insample_future_ret_6m 等于 1 的行。
    """
    validate_filter_args(filter_column, filter_value)

    if filter_column is None:
        return df

    if filter_column not in df.columns:
        raise ValueError(f"输入数据中找不到筛选列：{filter_column}")

    mask = build_filter_mask(df[filter_column], filter_value)
    filtered_df = df.loc[mask].copy()

    print(
        f"已按 {filter_column} == {filter_value} 筛选："
        f"原始 {len(df)} 行，保留 {len(filtered_df)} 行。"
    )

    if filtered_df.empty:
        raise ValueError("筛选后没有剩余样本。请检查 --filter-column 和 --filter-value 是否正确。")

    return filtered_df


def choose_numeric_columns(df: pd.DataFrame, requested_columns: list[str] | None) -> pd.DataFrame:
    """
    选择需要分析的列，并尽量把内容转成数字。

    注意：
    - 原始数据里如果有字符串形式的数字，例如 "0.123"，这里会转成 0.123。
    - 无法转成数字的内容会变成缺失值 NaN。
    """
    if requested_columns:
        missing_columns = [column for column in requested_columns if column not in df.columns]
        if missing_columns:
            raise ValueError(f"输入数据中找不到这些列：{missing_columns}")
        candidate = df[requested_columns].copy()
    else:
        candidate = df.copy()

    numeric_df = pd.DataFrame(index=df.index)

    for column in candidate.columns:
        converted = pd.to_numeric(candidate[column], errors="coerce")

        # 如果整列都无法转成数字，就跳过。比如基金名称、日期等列。
        if converted.notna().sum() == 0:
            continue

        numeric_df[column] = converted

    if numeric_df.empty:
        raise ValueError("没有找到可分析的数值列。请检查输入文件，或用 --columns 指定列。")

    return numeric_df


def safe_ratio(numerator: float, denominator: float) -> float:
    """安全计算比例，避免除以 0。"""
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return np.nan
    return numerator / denominator


def judge_right_skew(mean_value: float, median_value: float) -> str:
    """
    根据 mean 和 median 判断是否右偏。

    常见经验：均值 > 中位数，说明右侧较大的值把平均数拉高，可能右偏。
    """
    if pd.isna(mean_value) or pd.isna(median_value):
        return "无法判断"
    if mean_value > median_value:
        return "是"
    return "否"


def judge_high_tail(p90: float, p95: float, p99: float, p25: float, p75: float) -> tuple[str, str]:
    """
    根据 p90 / p95 / p99 判断右侧尾部是否明显变厚。

    这里使用一个容易理解、也方便修改的启发式规则：
    - 先看 p90 到 p99 的跨度；
    - 再用 IQR = p75 - p25 作为“正常中间波动”的参照；
    - 如果高分位跨度大于 1 个 IQR，或者 p99 到 p95 的增量明显大于 p95 到 p90，
      就认为高分位尾部比较厚。
    """
    iqr = p75 - p25
    high_range = p99 - p90
    upper_gap_95_90 = p95 - p90
    upper_gap_99_95 = p99 - p95

    if any(pd.isna(x) for x in [p90, p95, p99, p25, p75]) or iqr <= 0:
        return "无法判断", "IQR 不足或分位数缺失"

    range_vs_iqr = safe_ratio(high_range, iqr)
    gap_ratio = safe_ratio(upper_gap_99_95, upper_gap_95_90)

    has_high_tail = range_vs_iqr > 1 or gap_ratio > 2
    reason = f"p99-p90={high_range:.6g}, IQR={iqr:.6g}, (p99-p95)/(p95-p90)={gap_ratio:.3g}"

    return ("是" if has_high_tail else "否"), reason


def judge_extreme_values(
    min_value: float,
    max_value: float,
    p1: float,
    p99: float,
    p25: float,
    p75: float,
) -> tuple[str, str]:
    """
    根据 min / max 判断是否存在异常极值。

    规则：
    - IQR = p75 - p25；
    - 如果 min 比 p1 还低很多，或 max 比 p99 还高很多，就标记为“是”；
    - “很多”这里定义为超过 1.5 个 IQR。
    """
    iqr = p75 - p25

    if any(pd.isna(x) for x in [min_value, max_value, p1, p99, p25, p75]) or iqr <= 0:
        return "无法判断", "IQR 不足或分位数缺失"

    lower_distance = p1 - min_value
    upper_distance = max_value - p99
    has_extreme = lower_distance > 1.5 * iqr or upper_distance > 1.5 * iqr
    reason = f"p1-min={lower_distance:.6g}, max-p99={upper_distance:.6g}, 1.5*IQR={1.5 * iqr:.6g}"

    return ("是" if has_extreme else "否"), reason


def calculate_one_column_stats(series: pd.Series) -> dict:
    """计算单列数据的描述性统计。"""
    total_count = len(series)
    clean = series.dropna()
    missing_count = int(series.isna().sum())
    missing_rate = missing_count / total_count if total_count > 0 else np.nan

    if clean.empty:
        return {
            "N": 0,
            "mean": np.nan,
            "std": np.nan,
            "min": np.nan,
            "p1": np.nan,
            "p5": np.nan,
            "p10": np.nan,
            "p25": np.nan,
            "median": np.nan,
            "p75": np.nan,
            "p90": np.nan,
            "p95": np.nan,
            "p99": np.nan,
            "max": np.nan,
            "skewness": np.nan,
            "kurtosis": np.nan,
            "missing count": missing_count,
            "missing rate": missing_rate,
            "是否右偏": "无法判断",
            "是否有高波动尾部": "无法判断",
            "高波动尾部判断理由": "无有效样本",
            "是否有异常极值": "无法判断",
            "异常极值判断理由": "无有效样本",
        }

    quantiles = clean.quantile(PERCENTILES)
    mean_value = clean.mean()
    median_value = quantiles.loc[0.50]
    high_tail, high_tail_reason = judge_high_tail(
        quantiles.loc[0.90],
        quantiles.loc[0.95],
        quantiles.loc[0.99],
        quantiles.loc[0.25],
        quantiles.loc[0.75],
    )
    extreme_values, extreme_reason = judge_extreme_values(
        clean.min(),
        clean.max(),
        quantiles.loc[0.01],
        quantiles.loc[0.99],
        quantiles.loc[0.25],
        quantiles.loc[0.75],
    )

    return {
        "N": int(clean.count()),
        "mean": mean_value,
        "std": clean.std(ddof=1),
        "min": clean.min(),
        "p1": quantiles.loc[0.01],
        "p5": quantiles.loc[0.05],
        "p10": quantiles.loc[0.10],
        "p25": quantiles.loc[0.25],
        "median": median_value,
        "p75": quantiles.loc[0.75],
        "p90": quantiles.loc[0.90],
        "p95": quantiles.loc[0.95],
        "p99": quantiles.loc[0.99],
        "max": clean.max(),
        "skewness": clean.skew(),
        "kurtosis": clean.kurt(),
        "missing count": missing_count,
        "missing rate": missing_rate,
        "是否右偏": judge_right_skew(mean_value, median_value),
        "是否有高波动尾部": high_tail,
        "高波动尾部判断理由": high_tail_reason,
        "是否有异常极值": extreme_values,
        "异常极值判断理由": extreme_reason,
    }


def calculate_descriptive_table(numeric_df: pd.DataFrame) -> pd.DataFrame:
    """汇总所有列的描述性统计表。"""
    rows = []

    for column in numeric_df.columns:
        row = {"column": column}
        row.update(calculate_one_column_stats(numeric_df[column]))
        rows.append(row)

    return pd.DataFrame(rows)


def calculate_cdf_threshold_table(numeric_df: pd.DataFrame) -> pd.DataFrame:
    """
    计算每列有多少样本小于几个常用阈值。

    这个表对应需求中的：
    rank volatility 小于 0.05 / 0.10 / 0.15 / 0.20 的样本占比。
    """
    rows = []

    for column in numeric_df.columns:
        clean = numeric_df[column].dropna()
        row = {"column": column, "N": int(clean.count())}

        for threshold in CDF_THRESHOLDS:
            count = int((clean <= threshold).sum())
            rate = count / len(clean) if len(clean) > 0 else np.nan
            row[f"count <= {threshold:.2f}"] = count
            row[f"rate <= {threshold:.2f}"] = rate

        rows.append(row)

    return pd.DataFrame(rows)


def get_subplot_grid(column_count: int, plots_per_row: int = 3) -> tuple[int, int]:
    """根据列数量计算大画布需要几行几列。"""
    row_count = math.ceil(column_count / plots_per_row)
    return row_count, plots_per_row


def hide_extra_axes(axes, used_count: int) -> None:
    """隐藏没有用到的小图区域。"""
    for ax in axes.flat[used_count:]:
        ax.set_visible(False)


def plot_histograms(numeric_df: pd.DataFrame, output_path: Path, bins: int = 30) -> None:
    """把各列直方图画到一个大画布中，每行 3 张小图。"""
    row_count, col_count = get_subplot_grid(len(numeric_df.columns), plots_per_row=3)
    fig, axes = plt.subplots(row_count, col_count, figsize=(5.5 * col_count, 3.8 * row_count))

    # 当只有一行或一列时，axes 可能不是二维数组；这里统一转成二维，后面更好处理。
    axes = np.atleast_2d(axes)

    for idx, column in enumerate(numeric_df.columns):
        ax = axes.flat[idx]
        clean = numeric_df[column].dropna()
        ax.hist(clean, bins=bins, color="#4C78A8", edgecolor="white", alpha=0.85)
        ax.axvline(0, color="#D62728", linestyle="--", linewidth=1, label="0")
        ax.axvline(clean.mean(), color="#F58518", linestyle="-", linewidth=1, label="mean")
        ax.axvline(clean.median(), color="#54A24B", linestyle="-", linewidth=1, label="median")
        ax.set_title(str(column), fontsize=11)
        ax.set_xlabel("value")
        ax.set_ylabel("frequency")
        ax.legend(fontsize=8)

    hide_extra_axes(axes, len(numeric_df.columns))
    fig.suptitle("Histograms by Column", fontsize=15)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_boxplot(numeric_df: pd.DataFrame, output_path: Path) -> None:
    """把各列箱线图画在同一个图上，方便横向比较分散程度。"""
    clean_columns = [numeric_df[column].dropna() for column in numeric_df.columns]

    fig_width = max(8, len(numeric_df.columns) * 1.2)
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    ax.boxplot(clean_columns, tick_labels=numeric_df.columns, showfliers=True)
    ax.set_title("Boxplot by Column")
    ax.set_ylabel("value")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_cdf(numeric_df: pd.DataFrame, output_path: Path) -> None:
    """把各列累计分布函数画到一个大画布中，每行 3 张小图。"""
    row_count, col_count = get_subplot_grid(len(numeric_df.columns), plots_per_row=3)
    fig, axes = plt.subplots(row_count, col_count, figsize=(5.5 * col_count, 3.8 * row_count))
    axes = np.atleast_2d(axes)

    for idx, column in enumerate(numeric_df.columns):
        ax = axes.flat[idx]
        clean = numeric_df[column].dropna().sort_values()

        if clean.empty:
            ax.set_title(str(column), fontsize=11)
            ax.text(0.5, 0.5, "无有效样本", ha="center", va="center", transform=ax.transAxes)
            continue

        y_values = np.arange(1, len(clean) + 1) / len(clean)
        ax.plot(clean, y_values, color="#4C78A8", linewidth=1.8)

        # 画出 0.05 / 0.10 / 0.15 / 0.20 的参考线，并在图中标注累计占比。
        for threshold in CDF_THRESHOLDS:
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

        ax.set_title(str(column), fontsize=11)
        ax.set_xlabel("value")
        ax.set_ylabel("cumulative probability")
        ax.set_ylim(0, 1.02)
        ax.grid(linestyle="--", alpha=0.3)

    hide_extra_axes(axes, len(numeric_df.columns))
    fig.suptitle("Cumulative Distribution Functions by Column", fontsize=15)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def save_excel(
    descriptive_table: pd.DataFrame,
    cdf_threshold_table: pd.DataFrame,
    output_path: Path,
) -> None:
    """保存 Excel，并设置简单格式，让表格更容易阅读。"""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        descriptive_table.to_excel(writer, sheet_name="descriptive", index=False)
        cdf_threshold_table.to_excel(writer, sheet_name="cdf_thresholds", index=False)

        for sheet_name in writer.book.sheetnames:
            ws = writer.book[sheet_name]
            ws.freeze_panes = "A2"

            for column_cells in ws.columns:
                column_letter = column_cells[0].column_letter
                max_length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in column_cells)
                ws.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 45)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_prefix = ask_output_prefix(args.prefix)

    raw_df = read_input_file(input_path, sheet=normalize_sheet_arg(args.sheet))
    filtered_df = apply_row_filter(raw_df, args.filter_column, args.filter_value)
    numeric_df = choose_numeric_columns(filtered_df, args.columns)

    descriptive_table = calculate_descriptive_table(numeric_df)
    cdf_threshold_table = calculate_cdf_threshold_table(numeric_df)

    excel_path = output_dir / f"{output_prefix}_descriptive.xlsx"
    histogram_path = output_dir / f"{output_prefix}_histograms.png"
    boxplot_path = output_dir / f"{output_prefix}_boxplot.png"
    cdf_path = output_dir / f"{output_prefix}_cdf.png"

    save_excel(descriptive_table, cdf_threshold_table, excel_path)
    plot_histograms(numeric_df, histogram_path, bins=args.hist_bins)
    plot_boxplot(numeric_df, boxplot_path)
    plot_cdf(numeric_df, cdf_path)

    print(f"已分析列数：{len(numeric_df.columns)}")
    print(f"描述性统计表：{excel_path}")
    print(f"直方图：{histogram_path}")
    print(f"箱线图：{boxplot_path}")
    print(f"累计分布函数图：{cdf_path}")


if __name__ == "__main__":
    main()
