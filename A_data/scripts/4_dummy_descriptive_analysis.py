"""
为 dummy variable 回归模型生成描述性统计。

本脚本优先从 regression_registry.py 的已有字段自动推断，不需要新增配置字段。
需要的字段包括：factors、y、date_col、sample_filters、preprocess_output_path、
output_dir 和 factor_group_suffixes。回归配置为了避免 dummy variable trap 会省略
hit0 基准组；描述性统计会为普通 one-hot 组自动补回 hit0，累积门槛组则保持
原有的四个嵌套变量。
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis/config/regression_registry.py"
MATPLOTLIB_CACHE_DIR = PROJECT_ROOT / "A_data/output/.matplotlib_cache"
DEFAULT_MODEL_KEY = "fm_winrates_top50"
EXCEL_SHEET_NAME_LIMIT = 31

# Matplotlib 默认可能把字体缓存写到用户目录；这里固定到项目 output 下，和现有脚本保持一致。
MATPLOTLIB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MATPLOTLIB_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(MATPLOTLIB_CACHE_DIR))

import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(description="为 dummy variable 模型生成描述性统计。")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_KEY,
        help="regression_registry.py 中的模型名称。",
    )
    return parser.parse_args()


def load_regression_config(model_key: str) -> dict[str, Any]:
    """从 regression_registry.py 读取指定模型配置。"""
    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry",
        REGISTRY_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(model_key)


def resolve_project_path(path_text: str | Path) -> Path:
    """把 registry 里的项目相对路径转成绝对路径。"""
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def configure_matplotlib() -> None:
    """设置 matplotlib，让中文标题和负号尽量正常显示。"""
    plt.rcParams["font.sans-serif"] = [
        "Arial Unicode MS",
        "PingFang SC",
        "Heiti SC",
        "SimHei",
        "Microsoft YaHei",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def read_input_file(input_path: Path) -> pd.DataFrame:
    """根据文件后缀读取输入数据。"""
    if not input_path.exists():
        raise FileNotFoundError(f"未找到输入文件：{input_path}")

    suffix = input_path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(input_path)
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)

    raise ValueError(f"暂不支持该文件类型：{suffix}。请使用 .parquet / .csv / .xlsx / .xls。")


def build_filter_mask(series: pd.Series, expected_value: Any) -> pd.Series:
    """按 registry 中的筛选值生成 True/False mask。"""
    # 先尝试把期望值转成数值；能转成功就走数值比较，避免 "1" != 1.0 的问题。
    expected_numeric = pd.to_numeric(pd.Series([expected_value]), errors="coerce").iloc[0]
    if pd.notna(expected_numeric):
        # 期望值是数值，把原始列也转成数值再逐行比较。
        numeric_series = pd.to_numeric(series, errors="coerce")
        return numeric_series == expected_numeric
    # 期望值不是数值（比如字符串类别），改用字符串精确匹配。
    return series.astype("string") == str(expected_value)


def apply_sample_filters(df: pd.DataFrame, sample_filters: dict[str, Any]) -> pd.DataFrame:
    """按照 sample_filters 保留基础样本。"""
    # 复制一份，避免修改调用方的原始 DataFrame。
    filtered = df.copy()

    # 逐个筛选条件依次叠加（AND 逻辑）。
    for column, expected_value in sample_filters.items():
        if column not in filtered.columns:
            raise ValueError(f"输入数据中找不到样本筛选列：{column}")

        before_count = len(filtered)
        # 生成当前条件的布尔 mask，保留满足条件的行。
        mask = build_filter_mask(filtered[column], expected_value)
        filtered = filtered.loc[mask].copy()
        print(
            f"已按 {column} == {expected_value} 筛选："
            f"原始 {before_count} 行，保留 {len(filtered)} 行。"
        )

        # 如果某个条件筛完后没有剩余样本，直接报错，避免后续空表分析。
        if filtered.empty:
            raise ValueError(f"按 {column} == {expected_value} 筛选后没有剩余样本。")

    return filtered


def get_dummy_factor_groups(factors: list[Any]) -> list[tuple[str, ...]]:
    """从 factors 中取出 tuple/list 形式的 dummy 变量组。"""
    groups: list[tuple[str, ...]] = []

    for factor in factors:
        # 只取 tuple/list 形式的项（一组 dummy 变量）；单个字符串的 factor 跳过。
        if isinstance(factor, (tuple, list)):
            group = tuple(str(column) for column in factor)
            if group:
                groups.append(group)

    # 如果整个 factors 列表里都没有 tuple/list，说明这个模型不适用本脚本。
    if not groups:
        raise ValueError("config['factors'] 中没有找到 tuple/list 形式的 dummy 变量组。")

    return groups


def clean_filename_text(raw_text: str) -> str:
    """把短名整理成适合文件名的形式。"""
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", raw_text.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "dummy_group"


def extract_hit_label(dummy_name: str) -> str:
    """从 dummy 列名中提取简短且保留经济含义的 hit 标签。"""
    # 累积门槛必须先匹配，避免将 hit_above0 错当成普通 hit0。
    cumulative_match = re.search(r"_hit_above(\d+)(?:_|$)", dummy_name)
    if cumulative_match:
        return f"hit>{cumulative_match.group(1)}"

    # 用正则匹配 "_hitN_" 或 "_hitN" 结尾的模式，取出数字 N。
    match = re.search(r"_hit(\d+)(?:_|$)", dummy_name)
    if match:
        return f"hit{match.group(1)}"
    # 没有匹配到 hit 模式时，退回原始列名作为标签。
    return dummy_name


def include_hit0_for_descriptive(
    df: pd.DataFrame,
    dummy_cols: tuple[str, ...],
) -> tuple[str, ...]:
    """为普通 one-hot 描述性统计补回回归配置中省略的 hit0 基准组。

    带截距项回归只能放入 hit1 到 hitm，否则全部 dummy 的行和为 1，会产生完全
    共线性；描述性统计没有这个限制，因此应该展示 hit0 到 hitm 的完整分布。
    ``hit_aboveN`` 累积 dummy 不是互斥分组，不能也不需要补造 hit0。
    """
    # 如果配置以后已经显式包含 hit0，就直接沿用，避免重复添加同一列。
    if any(extract_hit_label(column) == "hit0" for column in dummy_cols):
        return dummy_cols

    # 同一组 dummy 只有命中次数不同，因此可由第一列（通常是 hit1）稳定推导 hit0。
    first_col = dummy_cols[0]
    hit0_col = re.sub(r"_hit\d+(?=_|$)", "_hit0", first_col, count=1)

    # 对不采用 hitN 命名的通用 dummy 组保持原行为，不擅自猜测基准组列名。
    if hit0_col == first_col:
        return dummy_cols

    if hit0_col not in df.columns:
        # 清洗流水线只保留回归需要的 hit1 到 hitm，因此输出面板可能没有 hit0。
        # 利用 one-hot 互斥关系重建基准组，同时保留无有效历史窗口行的缺失状态。
        numeric_df = build_dummy_numeric_df(df, dummy_cols)
        all_missing = numeric_df.isna().all(axis=1)
        all_present = numeric_df.notna().all(axis=1)
        partial_missing = ~(all_missing | all_present)
        if partial_missing.any():
            raise ValueError(
                f"{dummy_cols[0]} 所在 dummy 组出现部分列缺失，无法可靠重建 hit0；"
                f"异常行数：{int(partial_missing.sum())}"
            )

        row_sum = numeric_df.loc[all_present].sum(axis=1)
        invalid_sum = ~row_sum.isin([0, 1])
        if invalid_sum.any():
            raise ValueError(
                f"{dummy_cols[0]} 所在 dummy 组不满足 one-hot 规则，无法可靠重建 hit0；"
                f"异常行数：{int(invalid_sum.sum())}"
            )

        hit0 = pd.Series(np.nan, index=df.index, dtype="float64")
        hit0.loc[all_present] = (row_sum == 0).astype("int64")
        df[hit0_col] = hit0

    return (hit0_col, *dummy_cols)


def infer_group_suffix(dummy_cols: tuple[str, ...]) -> str:
    """当 registry 没有 suffix 时，从第一个 dummy 变量名中推断窗口短名。"""
    # 用第一个列名来推断整组的窗口配置（同一组 dummy 共享相同的 m/n 窗口）。
    first_col = dummy_cols[0]
    # 优先匹配完整的 "m3_n6...pairwise1" 模式。
    match = re.search(r"(m\d+_n\d+).*?(pairwise\d+)", first_col)
    if match:
        return clean_filename_text(f"{match.group(1)}_{match.group(2)}")

    # 退而求其次，只匹配 "m3_n6" 部分。
    match = re.search(r"m\d+_n\d+", first_col)
    if match:
        return clean_filename_text(match.group(0))

    # 都匹配不到时，用整个列名作为后缀。
    return clean_filename_text(first_col)


def get_group_suffix(
    dummy_cols: tuple[str, ...],
    factor_group_suffixes: dict[Any, Any],
) -> str:
    """优先用 registry 中的 suffix，否则从变量名自动推断。"""
    # 先查 registry 的 factor_group_suffixes 映射（key 是 tuple）。
    suffix = factor_group_suffixes.get(dummy_cols)
    if suffix is None:
        # registry 没有配置时，从列名自动提取窗口信息。
        suffix = infer_group_suffix(dummy_cols)
    return clean_filename_text(str(suffix))


def make_sheet_name(base_name: str, used_sheet_names: set[str]) -> str:
    """生成符合 Excel 31 字符限制、且不重复的 sheet 名。"""
    # 去掉 Excel sheet 名不允许的特殊字符。
    cleaned = re.sub(r"[\[\]:*?/\\]", "_", base_name).strip()
    # Excel sheet 名最长 31 个字符，超出直接截断。
    if len(cleaned) > EXCEL_SHEET_NAME_LIMIT:
        cleaned = cleaned[:EXCEL_SHEET_NAME_LIMIT]

    candidate = cleaned or "sheet"
    # 如果已经有同名 sheet，在末尾加 _1, _2, ... 直到不重复。
    counter = 1
    while candidate in used_sheet_names:
        suffix = f"_{counter}"
        candidate = f"{cleaned[:EXCEL_SHEET_NAME_LIMIT - len(suffix)]}{suffix}"
        counter += 1

    used_sheet_names.add(candidate)
    return candidate


def validate_required_columns(df: pd.DataFrame, columns: list[str]) -> None:
    """提前检查列是否齐全，让报错信息更直接。"""
    missing_columns = [column for column in columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"输入数据中找不到这些列：{missing_columns}")


def build_dummy_numeric_df(df: pd.DataFrame, dummy_cols: tuple[str, ...]) -> pd.DataFrame:
    """把 dummy 列转成数值，后续统一用 1 和非 1 做统计。"""
    numeric_df = pd.DataFrame(index=df.index)
    for column in dummy_cols:
        numeric_df[column] = pd.to_numeric(df[column], errors="coerce")
    return numeric_df


def calculate_frequency_table(dummy_df: pd.DataFrame) -> pd.DataFrame:
    """计算每个 dummy 的 1/0 样本量和 1 的占比。"""
    rows = []

    # 逐列统计：每列是一个 dummy 变量，值只有 0 和 1。
    for column in dummy_df.columns:
        series = dummy_df[column]
        # 去掉 NaN 后再统计，避免缺失值干扰频次。
        valid = series.dropna()
        count_1 = int((valid == 1).sum())
        count_0 = int((valid != 1).sum())
        pct_1 = count_1 / len(valid) if len(valid) > 0 else np.nan
        rows.append(
            {
                "dummy_name": column,
                "count_1": count_1,
                "count_0": count_0,
                "pct_1": pct_1,
            }
        )

    return pd.DataFrame(rows)


def calculate_overlap_table(dummy_df: pd.DataFrame, hit_labels: list[str]) -> pd.DataFrame:
    """计算 P(hit_j=1 | hit_i=1) 条件概率矩阵。"""
    # 构建 N x N 矩阵，行是"条件样本 hit_i=1"，列是"条件结果 hit_j=1"。
    result = pd.DataFrame(index=hit_labels, columns=hit_labels, dtype="float64")

    for row_label, row_col in zip(hit_labels, dummy_df.columns):
        # row_mask：当前行对应的 dummy=1 的样本集合（作为条件的分母）。
        row_mask = dummy_df[row_col] == 1
        denominator = int(row_mask.sum())

        for col_label, col_col in zip(hit_labels, dummy_df.columns):
            if denominator == 0:
                result.loc[row_label, col_label] = np.nan
            else:
                # 在 hit_i=1 的样本中，有多少同时 hit_j=1。
                numerator = int(((dummy_df[col_col] == 1) & row_mask).sum())
                result.loc[row_label, col_label] = numerator / denominator

    return result


def calculate_y_distribution_table(
    df: pd.DataFrame,
    dummy_df: pd.DataFrame,
    y_column: str,
    hit_labels: list[str],
) -> pd.DataFrame:
    """计算全样本和各 dummy=1 子样本的因变量分布。"""
    y_series = pd.to_numeric(df[y_column], errors="coerce")
    # 第一组是"全样本"作为基准，后面依次是每个 dummy=1 的子样本。
    groups: list[tuple[str, pd.Series]] = [("全样本", y_series)]

    for hit_label, dummy_col in zip(hit_labels, dummy_df.columns):
        # 取出 dummy=1 对应位置的因变量值。
        groups.append((hit_label, y_series.loc[dummy_df[dummy_col] == 1]))

    rows = []
    for group_name, group_series in groups:
        clean = group_series.dropna()
        rows.append(
            {
                "group": group_name,
                "mean": clean.mean(),
                "median": clean.median(),
                "std": clean.std(ddof=1),
                "count": int(clean.count()),
            }
        )

    return pd.DataFrame(rows)


def calculate_time_stability_table(
    df: pd.DataFrame,
    dummy_df: pd.DataFrame,
    date_col: str,
    hit_labels: list[str],
) -> pd.DataFrame:
    """按月份统计每个 dummy=1 的样本量。"""
    # 组装临时工作表：日期列 + 每个 dummy 是否为 1（转成 0/1 整数方便 sum）。
    work = pd.DataFrame(index=df.index)
    work[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    for hit_label, dummy_col in zip(hit_labels, dummy_df.columns):
        work[hit_label] = (dummy_df[dummy_col] == 1).astype("int64")

    # 丢掉无法识别日期的行，避免图表出现 NaT 分组。
    work = work.dropna(subset=[date_col])
    if work.empty:
        raise ValueError(f"日期列 {date_col} 无法解析出有效日期。")

    # 按月分组求和，得到每月每个 dummy=1 的样本量。
    grouped = work.groupby(date_col, sort=True)[hit_labels].sum()
    # 把日期索引格式化成 "YYYY-MM"，方便图表显示。
    grouped.index = grouped.index.strftime("%Y-%m")
    grouped.index.name = date_col
    return grouped


def make_subplot_grid(
    item_count: int,
    *,
    cols: int = 3,
    subplot_width: float = 6.2,
    subplot_height: float = 4.8,
) -> tuple[plt.Figure, np.ndarray]:
    """创建“每行 cols 张图”的大画布，并把 axes 拉平成一维数组。

    matplotlib 在只有一行或一列时会返回不同形状的 axes。这里统一整理成一维，
    后面循环绘图时就不用反复判断 axes 到底是一张、一个列表还是二维矩阵。
    """
    rows = math.ceil(item_count / cols)
    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(cols * subplot_width, rows * subplot_height),
        squeeze=False,
    )
    return fig, axes.ravel()


def hide_unused_axes(axes: np.ndarray, used_count: int) -> None:
    """隐藏大画布最后一行没有用上的空白子图。"""
    for ax in axes[used_count:]:
        ax.axis("off")


def draw_frequency_on_ax(
    ax: plt.Axes,
    table: pd.DataFrame,
    hit_labels: list[str],
    title_suffix: str,
) -> None:
    """把 dummy 频次柱状图画到指定子图上，供单图和汇总图复用。"""
    bars = ax.bar(hit_labels, table["count_1"], color="#4C78A8", edgecolor="white")

    # 在每个柱顶标注该 dummy=1 的占比百分数。
    for bar, pct_1 in zip(bars, table["pct_1"]):
        label = "NA" if pd.isna(pct_1) else f"{pct_1:.1%}"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            label,
            ha="center",
            va="bottom",
            fontsize=8,
        )

    ax.set_title(f"{title_suffix} dummy=1 样本量与占比", fontsize=10)
    ax.set_xlabel("dummy")
    ax.set_ylabel("样本量")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.tick_params(axis="x", rotation=30)


def plot_frequency(
    table: pd.DataFrame,
    hit_labels: list[str],
    title_suffix: str,
    output_path: Path,
) -> None:
    """输出 dummy 频次柱状图。"""
    # 图宽根据 dummy 数量动态调整，避免标签拥挤。
    fig_width = max(8, len(hit_labels) * 0.9)
    fig, ax = plt.subplots(figsize=(fig_width, 5.2))
    draw_frequency_on_ax(ax, table, hit_labels, title_suffix)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def draw_overlap_heatmap_on_ax(
    ax: plt.Axes,
    table: pd.DataFrame,
    title_suffix: str,
) -> Any:
    """把跨 dummy 条件概率热力图画到指定子图上。"""
    values = table.to_numpy(dtype="float64")
    # 条件概率范围固定 [0, 1]，颜色越深概率越高。
    image = ax.imshow(values, cmap="YlGnBu", vmin=0, vmax=1)

    ax.set_xticks(np.arange(len(table.columns)), labels=table.columns)
    ax.set_yticks(np.arange(len(table.index)), labels=table.index)
    ax.set_title(f"{title_suffix} 跨 dummy 重叠度", fontsize=10)
    ax.set_xlabel("条件结果：hit_j=1")
    ax.set_ylabel("条件样本：hit_i=1")
    ax.tick_params(axis="x", rotation=45, labelsize=8)
    ax.tick_params(axis="y", labelsize=8)

    # 在每个格子里标注百分比数字，方便直接读数。
    for row_idx in range(values.shape[0]):
        for col_idx in range(values.shape[1]):
            value = values[row_idx, col_idx]
            text = "NA" if pd.isna(value) else f"{value:.0%}"
            ax.text(col_idx, row_idx, text, ha="center", va="center", fontsize=7)

    return image


def plot_overlap_heatmap(
    table: pd.DataFrame,
    title_suffix: str,
    output_path: Path,
) -> None:
    """输出跨 dummy 条件概率热力图。"""
    # 热力图用正方形，大小随 dummy 数量伸缩。
    fig_size = max(6, len(table.columns) * 0.75)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size))
    image = draw_overlap_heatmap_on_ax(ax, table, title_suffix)
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04, label="条件概率")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def draw_y_distribution_on_ax(
    ax: plt.Axes,
    table: pd.DataFrame,
    y_column: str,
    title_suffix: str,
) -> None:
    """把因变量均值和标准差柱状图画到指定子图上。"""
    yerr = table["std"].fillna(0)
    ax.bar(
        table["group"],
        table["mean"],
        yerr=yerr,
        color="#54A24B",
        edgecolor="white",
        capsize=4,
        alpha=0.9,
    )
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title(f"{title_suffix} {y_column} 均值与标准差", fontsize=10)
    ax.set_xlabel("样本组")
    ax.set_ylabel("均值")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.tick_params(axis="x", rotation=30, labelsize=8)


def plot_y_distribution(
    table: pd.DataFrame,
    y_column: str,
    title_suffix: str,
    output_path: Path,
) -> None:
    """输出因变量均值和标准差柱状图。"""
    fig_width = max(8, len(table) * 0.9)
    fig, ax = plt.subplots(figsize=(fig_width, 5.2))
    draw_y_distribution_on_ax(ax, table, y_column, title_suffix)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def draw_time_stability_on_ax(
    ax: plt.Axes,
    table: pd.DataFrame,
    title_suffix: str,
) -> None:
    """把每月 dummy=1 样本量折线图画到指定子图上。"""
    # 用整数序列作为 x 轴位置，避免日期间距不均匀。
    x_values = np.arange(len(table.index))
    # 每条折线代表一个 dummy，方便观察哪个 dummy 在特定月份样本量骤降。
    for column in table.columns:
        ax.plot(x_values, table[column], marker="o", linewidth=1.3, markersize=2.5, label=column)

    # x 轴标签太密时按固定间隔显示，保持可读性。
    tick_step = max(1, len(table.index) // 12)
    ax.set_xticks(x_values[::tick_step], table.index[::tick_step], rotation=45, ha="right")
    ax.set_title(f"{title_suffix} dummy=1 样本量时序稳定性", fontsize=10)
    ax.set_xlabel("月份")
    ax.set_ylabel("样本量")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    ax.legend(ncol=min(4, len(table.columns)), fontsize=7)


def plot_time_stability(
    table: pd.DataFrame,
    title_suffix: str,
    output_path: Path,
) -> None:
    """输出每月 dummy=1 样本量折线图。"""
    # 图宽根据月份数量伸缩，但限制在 [10, 18] 范围内避免过宽。
    fig_width = max(10, min(18, len(table.index) * 0.22))
    fig, ax = plt.subplots(figsize=(fig_width, 5.8))
    draw_time_stability_on_ax(ax, table, title_suffix)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def plot_all_dummy_grids(
    plot_items: list[dict[str, Any]],
    y_column: str,
    model_key: str,
    output_dir: Path,
    *,
    cols: int = 3,
) -> list[Path]:
    """把所有 dummy 组合按每行三张小图汇总到四张大画布里。"""
    output_paths: list[Path] = []

    # 频次汇总图：每个子图对应一个 dummy 变量组合。
    fig, axes = make_subplot_grid(len(plot_items), cols=cols)
    for ax, item in zip(axes, plot_items):
        draw_frequency_on_ax(
            ax,
            item["frequency_table"],
            item["hit_labels"],
            item["group_suffix"],
        )
    hide_unused_axes(axes, len(plot_items))
    fig.suptitle(f"{model_key} dummy=1 样本量与占比汇总", fontsize=14)
    fig.tight_layout()
    output_path = output_dir / f"{model_key}_频次_汇总.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    output_paths.append(output_path)

    # 重叠度汇总图：共用一个 colorbar，避免每个子图旁边都挤一条色带。
    fig, axes = make_subplot_grid(len(plot_items), cols=cols, subplot_width=5.6, subplot_height=5.2)
    image = None
    used_axes = []
    for ax, item in zip(axes, plot_items):
        image = draw_overlap_heatmap_on_ax(
            ax,
            item["overlap_table"],
            item["group_suffix"],
        )
        used_axes.append(ax)
    hide_unused_axes(axes, len(plot_items))
    if image is not None:
        fig.colorbar(image, ax=used_axes, fraction=0.02, pad=0.02, label="条件概率")
    fig.suptitle(f"{model_key} 跨 dummy 重叠度汇总", fontsize=14)
    # 共享 colorbar 和 tight_layout 容易冲突；手动留出标题和色带空间更稳定。
    fig.subplots_adjust(top=0.9, right=0.88, hspace=0.55, wspace=0.35)
    output_path = output_dir / f"{model_key}_重叠度_汇总.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    output_paths.append(output_path)

    # 因变量分布汇总图：保留每组“全样本 + 各 hit 子样本”的均值和标准差。
    fig, axes = make_subplot_grid(len(plot_items), cols=cols)
    for ax, item in zip(axes, plot_items):
        draw_y_distribution_on_ax(
            ax,
            item["y_distribution_table"],
            y_column,
            item["group_suffix"],
        )
    hide_unused_axes(axes, len(plot_items))
    fig.suptitle(f"{model_key} 因变量均值与标准差汇总", fontsize=14)
    fig.tight_layout()
    output_path = output_dir / f"{model_key}_因变量分布_汇总.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    output_paths.append(output_path)

    # 时序稳定性汇总图：每张小图显示一组 dummy 在各月份的样本量变化。
    fig, axes = make_subplot_grid(len(plot_items), cols=cols, subplot_width=6.8, subplot_height=5.0)
    for ax, item in zip(axes, plot_items):
        draw_time_stability_on_ax(
            ax,
            item["time_stability_table"],
            item["group_suffix"],
        )
    hide_unused_axes(axes, len(plot_items))
    fig.suptitle(f"{model_key} dummy=1 样本量时序稳定性汇总", fontsize=14)
    fig.tight_layout()
    output_path = output_dir / f"{model_key}_时序稳定性_汇总.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    output_paths.append(output_path)

    return output_paths


def save_excel(tables: dict[str, tuple[pd.DataFrame, bool]], output_path: Path) -> None:
    """把所有表格写入一个 Excel 文件，并做简单列宽处理。"""
    used_sheet_names: set[str] = set()
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # 每张表写入单独的 sheet；write_index 控制是否输出 DataFrame 的 index 列。
        for raw_sheet_name, (table, write_index) in tables.items():
            sheet_name = make_sheet_name(raw_sheet_name, used_sheet_names)
            table.to_excel(writer, sheet_name=sheet_name, index=write_index)

        # 写完后统一调整格式：冻结首行、按内容自适应列宽。
        for sheet_name in writer.book.sheetnames:
            ws = writer.book[sheet_name]
            # 冻结首行，方便滚动时始终看到表头。
            ws.freeze_panes = "A2"
            for column_cells in ws.columns:
                column_letter = column_cells[0].column_letter
                max_length = max(
                    len(str(cell.value)) if cell.value is not None else 0
                    for cell in column_cells
                )
                # 列宽下限 10、上限 45，避免太窄或太宽。
                ws.column_dimensions[column_letter].width = min(max(max_length + 2, 10), 45)


def analyze_one_dummy_group(
    df: pd.DataFrame,
    dummy_cols: tuple[str, ...],
    group_suffix: str,
    y_column: str,
    date_col: str,
    output_dir: Path,
) -> dict[str, Any]:
    """对单个窗口配置的 dummy 变量组完成四项分析。"""
    # 提前检查所需列是否都在 DataFrame 里，避免跑到一半才报错。
    validate_required_columns(df, [*dummy_cols, y_column, date_col])

    # 把 dummy 列统一转成数值型，后续用 == 1 判断。
    dummy_df = build_dummy_numeric_df(df, dummy_cols)
    # 从列名中提取短标签（hit1, hit2, ...），用于图表轴标签和表格行名。
    hit_labels = [extract_hit_label(column) for column in dummy_cols]

    # 四项分析：频次、重叠度、因变量分布、时序稳定性。
    frequency_table = calculate_frequency_table(dummy_df)
    overlap_table = calculate_overlap_table(dummy_df, hit_labels)
    y_distribution_table = calculate_y_distribution_table(df, dummy_df, y_column, hit_labels)
    time_stability_table = calculate_time_stability_table(df, dummy_df, date_col, hit_labels)

    tables = {
        f"{group_suffix}_频次": (frequency_table, False),
        f"{group_suffix}_重叠度": (overlap_table, True),
        f"{group_suffix}_因变量分布": (y_distribution_table, False),
        f"{group_suffix}_时序稳定性": (time_stability_table, True),
    }
    plot_item = {
        "group_suffix": group_suffix,
        "hit_labels": hit_labels,
        "frequency_table": frequency_table,
        "overlap_table": overlap_table,
        "y_distribution_table": y_distribution_table,
        "time_stability_table": time_stability_table,
    }

    # tables 用于写 Excel；plot_item 用于后续把所有组合拼到汇总大图里。
    # 这里不再保存单个 dummy 组合的图片，避免输出目录里图片过多。
    return {"tables": tables, "plot_item": plot_item}


def main() -> None:
    """读取模型配置并生成 dummy 描述性统计结果。"""
    args = parse_args()
    configure_matplotlib()

    # 从 registry 读取模型配置，提取所需字段。
    config = load_regression_config(args.model)
    input_path = resolve_project_path(str(config["preprocess_output_path"]))
    output_dir = resolve_project_path(str(config["output_dir"])) / "descriptive_dummy"
    output_dir.mkdir(parents=True, exist_ok=True)

    y_column = str(config["y"])
    date_col = str(config["date_col"])
    sample_filters = dict(config.get("sample_filters", {}))
    factor_group_suffixes = dict(config.get("factor_group_suffixes", {}))
    # 从 factors 中筛出 tuple 形式的 dummy 变量组（跳过单字符串 factor）。
    dummy_groups = get_dummy_factor_groups(list(config["factors"]))

    print(f"模型版本：{args.model}")
    print(f"输入文件：{input_path}")
    print(f"输出目录：{output_dir}")
    print(f"dummy 变量组数：{len(dummy_groups)}")

    # 读取数据并应用基础样本筛选（如 is_insample_future_ret_6m == 1）。
    raw_df = read_input_file(input_path)
    filtered_df = apply_sample_filters(raw_df, sample_filters)

    # 对每组 dummy 变量分别跑四项分析，收集表格写 Excel，同时收集绘图数据做汇总大图。
    all_tables: dict[str, tuple[pd.DataFrame, bool]] = {}
    plot_items: list[dict[str, Any]] = []
    for dummy_cols in dummy_groups:
        # suffix 映射的 key 使用原始回归变量组，因此要在补 hit0 之前取得短名称。
        group_suffix = get_group_suffix(dummy_cols, factor_group_suffixes)
        # 普通 one-hot 回归省略 hit0，描述性统计会补回；累积门槛组保持不变。
        descriptive_dummy_cols = include_hit0_for_descriptive(
            filtered_df,
            dummy_cols,
        )
        print(f"\n开始分析：{group_suffix}")
        analysis_result = analyze_one_dummy_group(
            filtered_df,
            descriptive_dummy_cols,
            group_suffix,
            y_column,
            date_col,
            output_dir,
        )
        all_tables.update(analysis_result["tables"])
        plot_items.append(analysis_result["plot_item"])

    # 输出四张汇总大图；每行固定放三张小图。
    grid_paths = plot_all_dummy_grids(
        plot_items,
        y_column,
        args.model,
        output_dir,
        cols=3,
    )

    # 所有组的四项分析表格合并到一个 Excel 文件，按 sheet 区分。
    excel_path = output_dir / f"{args.model}_dummy_descriptive.xlsx"
    save_excel(all_tables, excel_path)

    print(f"\nExcel 表格：{excel_path}")
    print("汇总图片：")
    for grid_path in grid_paths:
        print(f"- {grid_path}")
    print(f"图片输出目录：{output_dir}")


if __name__ == "__main__":
    main()
