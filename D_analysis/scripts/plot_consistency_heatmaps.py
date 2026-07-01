"""汇总热力图回归结果并绘制 FAC 系数 / t 值热力图。

输入是五个热力图模型的 ``fama_macbeth_results.csv``。脚本会从 ``factor`` 或
``variable`` 列中解析 ``FAC_rank_vol_m{m}_n{n}_pairwise1`` 的 m、n 参数，
并为每个样本组输出：

1. FAC coefficient 热力图 PNG 和矩阵 CSV
2. FAC t-stat 热力图 PNG 和矩阵 CSV，其中不显著格子用灰色显示
3. 所有样本组合并的显著性 summary CSV（|t| >= 1.96）
4. 用于判断“哪些 m,n 组合有效”的结论汇总 CSV 和 Markdown 草稿
5. 跨五个样本组的综合显著性热力图

运行方式：

    .venv/bin/python D_analysis/scripts/plot_consistency_heatmaps.py
"""

from __future__ import annotations

import argparse
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

# Codex 沙箱里用户 home 下的 matplotlib 缓存目录可能不可写。先把缓存目录放到
# 系统临时目录，避免 --help 或画图时反复打印无关警告、拖慢启动。
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "fund_analysis_matplotlib_cache"),
)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "D_analysis" / "output" / "fund_consistency" / "heatmap_summary"
)
SIGNIFICANCE_T_THRESHOLD = 1.96
FAC_PATTERN = re.compile(r"FAC_rank_vol_m(?P<m>\d+)_n(?P<n>\d+)_pairwise1")


@dataclass(frozen=True)
class HeatmapModel:
    """记录一个热力图回归模型的输入文件和展示名称。"""

    key: str
    label: str
    result_path: Path


HEATMAP_MODELS = (
    HeatmapModel(
        key="fm_heatmap_up",
        label="Up Top50",
        result_path=PROJECT_ROOT
        / "D_analysis"
        / "output"
        / "fund_consistency"
        / "fm_heatmap_up"
        / "fama_macbeth_results.csv",
    ),
    HeatmapModel(
        key="fm_heatmap_down",
        label="Down Bottom50",
        result_path=PROJECT_ROOT
        / "D_analysis"
        / "output"
        / "fund_consistency"
        / "fm_heatmap_down"
        / "fama_macbeth_results.csv",
    ),
    HeatmapModel(
        key="fm_heatmap_top33",
        label="Top33",
        result_path=PROJECT_ROOT
        / "D_analysis"
        / "output"
        / "fund_consistency"
        / "fm_heatmap_top33"
        / "fama_macbeth_results.csv",
    ),
    HeatmapModel(
        key="fm_heatmap_mid33",
        label="Mid33",
        result_path=PROJECT_ROOT
        / "D_analysis"
        / "output"
        / "fund_consistency"
        / "fm_heatmap_mid33"
        / "fama_macbeth_results.csv",
    ),
    HeatmapModel(
        key="fm_heatmap_bm33",
        label="Bottom33",
        result_path=PROJECT_ROOT
        / "D_analysis"
        / "output"
        / "fund_consistency"
        / "fm_heatmap_bm33"
        / "fama_macbeth_results.csv",
    ),
)


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="从热力图回归结果生成 FAC 系数和 t 值热力图。"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="热力图 PNG、矩阵 CSV 和 summary CSV 的输出目录。",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="允许跳过缺失的结果文件；默认遇到缺失文件即报错停止。",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="在热力图格子中标出数值；默认不标注，适合 12x12 图保持清爽。",
    )
    return parser.parse_args()


def resolve_output_dir(path: Path) -> Path:
    """把输出目录解析为绝对路径。"""
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def check_input_files(models: tuple[HeatmapModel, ...], allow_missing: bool) -> None:
    """检查输入结果文件是否存在；缺失时给出清楚提示。"""
    missing = [model for model in models if not model.result_path.exists()]
    if missing and not allow_missing:
        details = "\n".join(f"- {model.key}: {model.result_path}" for model in missing)
        raise FileNotFoundError(
            "以下热力图回归结果文件不存在，请先运行热力图回归：\n"
            f"{details}"
        )
    if missing:
        print("以下结果文件缺失，将跳过：")
        for model in missing:
            print(f"- {model.key}: {model.result_path}")


def parse_m_n_from_text(text: object) -> tuple[int, int] | None:
    """从一段文本中解析 FAC_rank_vol 的 m 和 n。"""
    match = FAC_PATTERN.search(str(text))
    if match is None:
        return None
    return int(match.group("m")), int(match.group("n"))


def find_factor_effect_rows(data: pd.DataFrame) -> pd.DataFrame:
    """筛出每个 FAC 因子自身的回归结果行。

    Fama-MacBeth 输出中每个 factor 会对应多行：截距、FAC 自身、控制变量等。
    热力图只需要 FAC 自身的系数和 t 值，所以优先保留 ``variable == factor`` 的行。
    若未来某些输出只在 variable 中写 FAC 名称，也会用正则兜底识别。
    """
    required_columns = {"factor", "variable", "coef", "t_stat"}
    missing_columns = sorted(required_columns - set(data.columns))
    if missing_columns:
        raise ValueError(f"结果文件缺少字段：{missing_columns}")

    factor_text = data["factor"].astype(str)
    variable_text = data["variable"].astype(str)
    same_factor_row = factor_text == variable_text
    variable_is_fac = variable_text.map(lambda value: FAC_PATTERN.search(value) is not None)
    result = data.loc[same_factor_row & variable_is_fac].copy()

    if result.empty:
        result = data.loc[variable_is_fac].copy()
    if result.empty:
        factor_is_fac = factor_text.map(lambda value: FAC_PATTERN.search(value) is not None)
        result = data.loc[factor_is_fac].copy()

    return result


def build_metric_matrices(
    result_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """读取一个模型结果文件，返回 coef/t 矩阵和长表。

    矩阵行是 m=1..12，列是 n=1..12。长表用于生成显著性 summary。
    """
    data = pd.read_csv(result_path)
    factor_rows = find_factor_effect_rows(data)

    records: list[dict[str, object]] = []
    for _, row in factor_rows.iterrows():
        parsed = parse_m_n_from_text(row.get("factor"))
        if parsed is None:
            parsed = parse_m_n_from_text(row.get("variable"))
        if parsed is None:
            continue

        m, n = parsed
        if not (1 <= m <= 12 and 1 <= n <= 12):
            # 本脚本只负责 m,n=1..12 的热力图；其他口径留给别的汇总脚本。
            continue

        records.append(
            {
                "m": m,
                "n": n,
                "factor": row.get("factor"),
                "variable": row.get("variable"),
                "coef": pd.to_numeric(row.get("coef"), errors="coerce"),
                "t_stat": pd.to_numeric(row.get("t_stat"), errors="coerce"),
                "p_value": pd.to_numeric(row.get("p_value"), errors="coerce")
                if "p_value" in row
                else np.nan,
                "n_months": pd.to_numeric(row.get("n_months"), errors="coerce")
                if "n_months" in row
                else np.nan,
                "avg_monthly_n": pd.to_numeric(
                    row.get("avg_monthly_n"), errors="coerce"
                )
                if "avg_monthly_n" in row
                else np.nan,
            }
        )

    long_table = pd.DataFrame(records)
    if long_table.empty:
        raise ValueError(f"{result_path} 中没有找到 FAC_rank_vol_m*_n*_pairwise1 结果行。")

    duplicated = long_table.duplicated(["m", "n"], keep=False)
    if duplicated.any():
        examples = long_table.loc[duplicated, ["m", "n", "factor", "variable"]].head(10)
        raise ValueError(
            f"{result_path} 中同一个 (m,n) 出现多条 FAC 结果，请检查：\n"
            + examples.to_string(index=False)
        )

    coef_matrix = make_matrix(long_table, "coef")
    t_matrix = make_matrix(long_table, "t_stat")
    return coef_matrix, t_matrix, long_table


def make_matrix(long_table: pd.DataFrame, value_column: str) -> pd.DataFrame:
    """把长表转换成 m x n 矩阵，保证坐标轴完整覆盖 1..12。"""
    matrix = pd.DataFrame(index=range(1, 13), columns=range(1, 13), dtype="float64")
    for _, row in long_table.iterrows():
        matrix.loc[int(row["m"]), int(row["n"])] = row[value_column]
    matrix.index.name = "m"
    matrix.columns.name = "n"
    return matrix


def save_matrix(matrix: pd.DataFrame, output_path: Path) -> None:
    """保存矩阵 CSV。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(output_path, encoding="utf-8-sig")


def plot_heatmap(
    matrix: pd.DataFrame,
    output_path: Path,
    title: str,
    colorbar_label: str,
    *,
    cmap: str,
    center_zero: bool,
    annotate: bool,
) -> None:
    """绘制并保存一张 12x12 热力图。"""
    values = matrix.to_numpy(dtype="float64")

    if center_zero:
        max_abs = np.nanmax(np.abs(values)) if np.isfinite(values).any() else 1.0
        vmin, vmax = -max_abs, max_abs
    else:
        vmin = float(np.nanmin(values)) if np.isfinite(values).any() else 0.0
        vmax = float(np.nanmax(values)) if np.isfinite(values).any() else 1.0

    fig, ax = plt.subplots(figsize=(9.5, 7.5))
    image = ax.imshow(values, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)

    ax.set_title(title, fontsize=14, pad=12)
    ax.set_xlabel("n: ranking periods", fontsize=11)
    ax.set_ylabel("m: return horizon (months)", fontsize=11)
    ax.set_xticks(range(12), labels=[str(i) for i in range(1, 13)])
    ax.set_yticks(range(12), labels=[str(i) for i in range(1, 13)])
    ax.set_xticks(np.arange(-0.5, 12, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 12, 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=0.8)
    ax.tick_params(which="minor", bottom=False, left=False)

    if annotate:
        for row_index in range(values.shape[0]):
            for col_index in range(values.shape[1]):
                value = values[row_index, col_index]
                if np.isfinite(value):
                    ax.text(
                        col_index,
                        row_index,
                        f"{value:.2f}",
                        ha="center",
                        va="center",
                        fontsize=6,
                        color="black",
                    )

    colorbar = fig.colorbar(image, ax=ax, shrink=0.88)
    colorbar.set_label(colorbar_label)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_t_stat_heatmap(
    matrix: pd.DataFrame,
    output_path: Path,
    title: str,
    *,
    annotate: bool,
) -> None:
    """绘制更适合解读显著性的 t-stat 热力图。

    t-stat 的符号一定和系数符号一致，因为 t-stat = coef / standard_error，
    而标准误为正。读图时更关键的是 ``abs(t_stat)`` 是否超过阈值：
    - 不显著格子（abs(t)<1.96）用灰色，越接近 0 越深灰；
    - 显著格子用红蓝色，颜色方向表示系数方向。
    """
    values = matrix.to_numpy(dtype="float64")
    finite = np.isfinite(values)
    significant = finite & (np.abs(values) >= SIGNIFICANCE_T_THRESHOLD)
    nonsignificant = finite & ~significant

    # 先手工构造底图颜色。NaN 用浅灰；不显著格子用灰阶，abs(t) 越接近 0 越深。
    image_values = np.ones((*values.shape, 4), dtype="float64")
    image_values[:, :, :3] = 0.93
    image_values[:, :, 3] = 1.0

    gray_strength = np.zeros_like(values, dtype="float64")
    gray_strength[nonsignificant] = np.clip(
        np.abs(values[nonsignificant]) / SIGNIFICANCE_T_THRESHOLD,
        0.0,
        1.0,
    )
    gray_rgb = 0.25 + 0.55 * gray_strength
    for channel in range(3):
        image_values[:, :, channel] = np.where(
            nonsignificant, gray_rgb, image_values[:, :, channel]
        )

    # 显著格子仍用发散色系，便于一眼区分负向/正向。
    max_abs = np.nanmax(np.abs(values[significant])) if significant.any() else 1.0
    max_abs = max(float(max_abs), SIGNIFICANCE_T_THRESHOLD)
    norm = matplotlib.colors.Normalize(vmin=-max_abs, vmax=max_abs)
    cmap = plt.get_cmap("RdBu_r")
    image_values[significant] = cmap(norm(values[significant]))

    fig, ax = plt.subplots(figsize=(9.5, 7.5))
    ax.imshow(image_values, origin="lower")
    ax.set_title(title, fontsize=14, pad=12)
    ax.set_xlabel("n: ranking periods", fontsize=11)
    ax.set_ylabel("m: return horizon (months)", fontsize=11)
    ax.set_xticks(range(12), labels=[str(i) for i in range(1, 13)])
    ax.set_yticks(range(12), labels=[str(i) for i in range(1, 13)])
    ax.set_xticks(np.arange(-0.5, 12, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 12, 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=0.8)
    ax.tick_params(which="minor", bottom=False, left=False)

    # 用黑框圈出显著格子，避免浅色显著值和灰色不显著值混在一起。
    for row_index, col_index in np.argwhere(significant):
        ax.add_patch(
            plt.Rectangle(
                (col_index - 0.5, row_index - 0.5),
                1,
                1,
                fill=False,
                edgecolor="black",
                linewidth=1.0,
            )
        )

    if annotate:
        for row_index in range(values.shape[0]):
            for col_index in range(values.shape[1]):
                value = values[row_index, col_index]
                if np.isfinite(value):
                    ax.text(
                        col_index,
                        row_index,
                        f"{value:.2f}",
                        ha="center",
                        va="center",
                        fontsize=6,
                        color="black",
                    )

    colorbar = fig.colorbar(
        matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap),
        ax=ax,
        shrink=0.88,
    )
    colorbar.set_label("significant t-stat color; gray means |t| < 1.96")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def make_significance_summary(
    model: HeatmapModel, long_table: pd.DataFrame
) -> pd.DataFrame:
    """筛出 |t| >= 1.96 的 m,n 组合，供跨样本组汇总。"""
    significant = long_table.loc[long_table["t_stat"].abs() >= SIGNIFICANCE_T_THRESHOLD].copy()
    significant.insert(0, "sample_group", model.key)
    significant.insert(1, "sample_label", model.label)
    return significant.sort_values(["m", "n"]).reset_index(drop=True)


def make_all_groups_summary(
    model_tables: list[tuple[HeatmapModel, pd.DataFrame]],
) -> pd.DataFrame:
    """把五个样本组的 FAC 结果合成长表。

    这张表是最细粒度的结论底稿：每一行对应一个样本组下的一个 (m,n)
    组合，并补充显著性、方向、m=3/m=6 标记。后面的有效组合筛选都基于它，
    这样如果需要改规则，只用从这张表重新聚合即可。
    """
    parts: list[pd.DataFrame] = []
    for model, long_table in model_tables:
        group_table = long_table.copy()
        group_table.insert(0, "sample_group", model.key)
        group_table.insert(1, "sample_label", model.label)
        parts.append(group_table)

    all_groups = pd.concat(parts, ignore_index=True)
    all_groups["is_significant"] = (
        all_groups["t_stat"].abs() >= SIGNIFICANCE_T_THRESHOLD
    )
    all_groups["significance_rule"] = f"abs(t_stat)>={SIGNIFICANCE_T_THRESHOLD}"
    all_groups["coef_direction"] = np.select(
        [
            all_groups["coef"] > 0,
            all_groups["coef"] < 0,
            all_groups["coef"] == 0,
        ],
        ["positive", "negative", "zero"],
        default="missing",
    )
    all_groups["significant_direction"] = np.where(
        all_groups["is_significant"], all_groups["coef_direction"], "not_significant"
    )
    all_groups["is_m3"] = all_groups["m"].eq(3)
    all_groups["is_m6"] = all_groups["m"].eq(6)
    all_groups["m3_negative_or_m6_positive_marker"] = np.select(
        [
            all_groups["m"].eq(3) & all_groups["coef"].lt(0),
            all_groups["m"].eq(6) & all_groups["coef"].gt(0),
        ],
        ["m3_negative", "m6_positive"],
        default="",
    )

    columns = [
        "m",
        "n",
        "sample_group",
        "sample_label",
        "factor",
        "variable",
        "coef",
        "t_stat",
        "p_value",
        "n_months",
        "avg_monthly_n",
        "is_significant",
        "significance_rule",
        "coef_direction",
        "significant_direction",
        "is_m3",
        "is_m6",
        "m3_negative_or_m6_positive_marker",
    ]
    return all_groups[columns].sort_values(["m", "n", "sample_group"]).reset_index(
        drop=True
    )


def _direction_mode(values: pd.Series) -> str:
    """返回最常见的方向；若没有有效方向，则返回 missing。"""
    usable = values[values.isin(["positive", "negative", "zero"])]
    if usable.empty:
        return "missing"
    return str(usable.value_counts().sort_values(ascending=False).index[0])


def _join_unique(values: pd.Series) -> str:
    """把去重后的样本组名称拼成字符串，便于 CSV 中直接阅读。"""
    unique_values = [str(value) for value in values.dropna().unique()]
    return ";".join(unique_values)


def build_effective_mn_summary(all_groups: pd.DataFrame) -> pd.DataFrame:
    """按显著性和方向稳定性规则筛选有效的 (m,n) 组合。

    当前规则偏向“研究结论候选”而不是最终因果结论：
    - 单个样本组中 abs(t_stat) >= 1.96 记为显著；
    - 显著样本组中的系数方向必须稳定，即都为正或都为负；
    - 至少 2 个样本组显著，记为 candidate；
    - 至少 3 个样本组显著，进一步标记为 robust_candidate。
    """
    rows: list[dict[str, object]] = []
    for (m, n), group in all_groups.groupby(["m", "n"], sort=True):
        non_missing = group.loc[group["coef_direction"] != "missing"].copy()
        significant = group.loc[group["is_significant"]].copy()

        all_direction = _direction_mode(non_missing["coef_direction"])
        significant_direction = _direction_mode(significant["coef_direction"])
        all_direction_count = int(
            (non_missing["coef_direction"] == all_direction).sum()
        )
        significant_direction_count = int(
            (significant["coef_direction"] == significant_direction).sum()
        )

        significant_direction_stable = (
            not significant.empty
            and significant["coef_direction"].nunique(dropna=True) == 1
            and significant_direction in {"positive", "negative"}
        )
        all_direction_stable = (
            not non_missing.empty
            and non_missing["coef_direction"].nunique(dropna=True) == 1
            and all_direction in {"positive", "negative"}
        )
        significant_count = int(significant.shape[0])
        candidate_2plus = significant_count >= 2 and significant_direction_stable
        candidate_3plus = significant_count >= 3 and significant_direction_stable

        rows.append(
            {
                "m": int(m),
                "n": int(n),
                "sample_group_count": int(group.shape[0]),
                "available_coef_count": int(non_missing.shape[0]),
                "significant_group_count": significant_count,
                "significant_groups": _join_unique(significant["sample_group"]),
                "all_direction_mode": all_direction,
                "all_direction_mode_count": all_direction_count,
                "all_direction_stable": bool(all_direction_stable),
                "significant_direction": significant_direction,
                "significant_direction_count": significant_direction_count,
                "significant_direction_stable": bool(significant_direction_stable),
                "mean_coef": group["coef"].mean(skipna=True),
                "median_coef": group["coef"].median(skipna=True),
                "max_abs_t_stat": group["t_stat"].abs().max(skipna=True),
                "mean_t_stat": group["t_stat"].mean(skipna=True),
                "candidate_2plus": bool(candidate_2plus),
                "candidate_3plus": bool(candidate_3plus),
                "effectiveness_tier": "robust_3plus"
                if candidate_3plus
                else "candidate_2plus"
                if candidate_2plus
                else "not_effective",
                "is_m3": int(m) == 3,
                "is_m6": int(m) == 6,
                "m3_negative_significant": bool(
                    int(m) == 3
                    and significant_count >= 1
                    and significant_direction == "negative"
                    and significant_direction_stable
                ),
                "m6_positive_significant": bool(
                    int(m) == 6
                    and significant_count >= 1
                    and significant_direction == "positive"
                    and significant_direction_stable
                ),
            }
        )

    effective = pd.DataFrame(rows)
    effective = effective.loc[effective["candidate_2plus"]].copy()
    sort_columns = [
        "candidate_3plus",
        "significant_group_count",
        "max_abs_t_stat",
        "m",
        "n",
    ]
    return effective.sort_values(sort_columns, ascending=[False, False, False, True, True])


def build_combined_heatmap_matrices(
    all_groups: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """生成跨五个样本组的综合热力图矩阵。

    单个模型的热力图适合看某个样本组内部的形状；综合图则回答“这个
    (m,n) 在五个样本组里到底有多少支持”：
    - significant_group_count：五个样本组中有几个达到 abs(t)>=1.96；
    - signed_significant_count：显著正向记 +1，显著负向记 -1，再求和。
      例如 -3 表示有 3 个样本组显著负向，+2 表示有 2 个样本组显著正向。
    """
    count_matrix = pd.DataFrame(index=range(1, 13), columns=range(1, 13), dtype="float64")
    signed_matrix = pd.DataFrame(index=range(1, 13), columns=range(1, 13), dtype="float64")

    for (m, n), group in all_groups.groupby(["m", "n"], sort=True):
        significant = group.loc[group["is_significant"]].copy()
        signed_values = np.select(
            [significant["coef"].gt(0), significant["coef"].lt(0)],
            [1, -1],
            default=0,
        )
        count_matrix.loc[int(m), int(n)] = float(significant.shape[0])
        signed_matrix.loc[int(m), int(n)] = float(np.sum(signed_values))

    for matrix in (count_matrix, signed_matrix):
        matrix.index.name = "m"
        matrix.columns.name = "n"

    return {
        "combined_significant_group_count": count_matrix,
        "combined_signed_significant_count": signed_matrix,
    }


def save_combined_heatmaps(
    all_groups: pd.DataFrame,
    output_dir: Path,
    *,
    annotate: bool,
) -> dict[str, Path]:
    """保存跨五个样本组的综合热力图和矩阵 CSV。"""
    combined_dir = output_dir / "combined"
    matrices = build_combined_heatmap_matrices(all_groups)
    outputs: dict[str, Path] = {}

    count_matrix = matrices["combined_significant_group_count"]
    count_csv = combined_dir / "combined_significant_group_count_matrix.csv"
    count_png = combined_dir / "combined_significant_group_count_heatmap.png"
    save_matrix(count_matrix, count_csv)
    plot_heatmap(
        count_matrix,
        count_png,
        title="Combined: number of significant sample groups",
        colorbar_label="count of |t| >= 1.96 groups",
        cmap="YlGnBu",
        center_zero=False,
        annotate=annotate,
    )
    outputs["significant_group_count_csv"] = count_csv
    outputs["significant_group_count_png"] = count_png

    signed_matrix = matrices["combined_signed_significant_count"]
    signed_csv = combined_dir / "combined_signed_significant_count_matrix.csv"
    signed_png = combined_dir / "combined_signed_significant_count_heatmap.png"
    save_matrix(signed_matrix, signed_csv)
    plot_heatmap(
        signed_matrix,
        signed_png,
        title="Combined: signed significant count",
        colorbar_label="negative groups (-) / positive groups (+)",
        cmap="RdBu_r",
        center_zero=True,
        annotate=annotate,
    )
    outputs["signed_significant_count_csv"] = signed_csv
    outputs["signed_significant_count_png"] = signed_png

    return outputs


def _format_mn_list(data: pd.DataFrame, limit: int | None = None) -> str:
    """把 (m,n) 列表格式化为 Markdown 中的一行短文本。"""
    if data.empty:
        return "无"
    display_data = data if limit is None else data.head(limit)
    pairs = [
        f"m={int(row.m)}, n={int(row.n)}" for row in display_data.itertuples()
    ]
    suffix = (
        f"；另有 {len(data) - limit} 个未列出"
        if limit is not None and len(data) > limit
        else ""
    )
    return "；".join(pairs) + suffix


def write_conclusion_markdown(
    output_path: Path,
    all_groups: pd.DataFrame,
    effective: pd.DataFrame,
) -> None:
    """写出一份可直接放进报告初稿的 Markdown 结论。

    这份文字故意保留“草稿”语气：它把规则、有效组合、m=3/m=6 的结构性迹象
    摆出来，但不替代后续经济含义解释和稳健性检验。
    """
    robust = effective.loc[effective["candidate_3plus"]].copy()
    candidate = effective.loc[effective["candidate_2plus"]].copy()
    m3 = effective.loc[effective["is_m3"]].copy()
    m6 = effective.loc[effective["is_m6"]].copy()
    m3_negative = effective.loc[effective["m3_negative_significant"]].copy()
    m6_positive = effective.loc[effective["m6_positive_significant"]].copy()

    lines = [
        "# 一致性热力图结论草稿",
        "",
        "## 读图说明",
        "",
        "- t-stat 的符号和系数符号一致，因为 `t_stat = coef / standard_error`，标准误为正。",
        "- 单个样本组的 t-stat 热力图中，灰色表示不显著；越接近 0 越深灰。",
        "- 单个样本组的 t-stat 热力图中，带黑框的红蓝格子表示 `abs(t_stat) >= 1.96`，红蓝方向表示系数方向。",
        "- 综合热力图 `combined_significant_group_count_heatmap.png` 显示五个样本组中有几个显著。",
        "- 综合热力图 `combined_signed_significant_count_heatmap.png` 把显著正向记为 +1、显著负向记为 -1，用于同时看方向和稳健性。",
        "",
        "## 判定规则",
        "",
        f"- 单个样本组中 `abs(t_stat) >= {SIGNIFICANCE_T_THRESHOLD}` 记为显著。",
        "- 只把显著样本组内系数方向一致的 `(m,n)` 视为方向稳定。",
        "- 至少 2 个样本组显著且方向稳定，记为候选有效组合。",
        "- 至少 3 个样本组显著且方向稳定，记为更稳健候选组合。",
        "- 额外标记 `m=3` 与 `m=6`，用于观察“m3 负向、m6 正向”是否呈结构性。",
        "",
        "## 汇总结果",
        "",
        f"- 全量样本组记录数：{len(all_groups)}。",
        f"- 候选有效组合数（至少 2 个样本组显著）：{len(candidate)}。",
        f"- 更稳健候选组合数（至少 3 个样本组显著）：{len(robust)}。",
        "",
        "## 更稳健候选组合",
        "",
        _format_mn_list(robust),
        "",
        "## 候选有效组合",
        "",
        _format_mn_list(candidate),
        "",
        "## m=3 与 m=6 结构性检查",
        "",
        f"- m=3 候选组合数：{len(m3)}；其中显著方向为负且稳定的组合数：{len(m3_negative)}。",
        f"- m=6 候选组合数：{len(m6)}；其中显著方向为正且稳定的组合数：{len(m6_positive)}。",
        f"- m=3 负向候选：{_format_mn_list(m3_negative)}。",
        f"- m=6 正向候选：{_format_mn_list(m6_positive)}。",
        "",
        "## 解读草稿",
        "",
    ]

    if not robust.empty:
        lines.append(
            "按当前阈值，部分 `(m,n)` 组合在多个样本组中同时显著，并且显著系数方向一致，"
            "可以作为一致性指标较有效的初步候选。优先关注 `effective_mn_summary.csv` 中"
            " `effectiveness_tier = robust_3plus` 的组合。"
        )
    elif not candidate.empty:
        lines.append(
            "按当前阈值，存在至少 2 个样本组显著且方向一致的组合，但尚未出现至少 3 个样本组"
            "同时支持的更稳健组合。当前结论应表述为探索性候选。"
        )
    else:
        lines.append(
            "按当前阈值，暂未筛出至少 2 个样本组显著且方向一致的 `(m,n)` 组合。"
            "这意味着热力图结果暂不支持强结论，后续可检查样本划分、控制变量或阈值口径。"
        )

    if len(m3_negative) > 0 and len(m6_positive) > 0:
        lines.append(
            "\n关于 `m=3` 与 `m=6`，当前结果同时出现了 m3 负向候选和 m6 正向候选，"
            "说明“m3 负向、m6 正向”具有一定结构性迹象；但仍建议结合具体样本组、"
            "经济含义和稳健性检验再写入正式结论。"
        )
    elif len(m3_negative) > 0:
        lines.append(
            "\n当前更明显的是 m=3 负向候选；m=6 正向证据不足，"
            "因此不宜直接概括为完整的“m3 负向、m6 正向”结构。"
        )
    elif len(m6_positive) > 0:
        lines.append(
            "\n当前更明显的是 m=6 正向候选；m=3 负向证据不足，"
            "因此不宜直接概括为完整的“m3 负向、m6 正向”结构。"
        )
    else:
        lines.append(
            "\n当前 m=3 负向与 m=6 正向均未形成候选组合层面的稳定证据。"
        )

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_model(
    model: HeatmapModel,
    output_dir: Path,
    *,
    annotate: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """处理一个样本组，输出两张图和两个矩阵。"""
    coef_matrix, t_matrix, long_table = build_metric_matrices(model.result_path)

    group_dir = output_dir / model.key
    coef_csv = group_dir / f"{model.key}_fac_coef_matrix.csv"
    t_csv = group_dir / f"{model.key}_fac_t_stat_matrix.csv"
    coef_png = group_dir / f"{model.key}_fac_coef_heatmap.png"
    t_png = group_dir / f"{model.key}_fac_t_stat_heatmap.png"

    save_matrix(coef_matrix, coef_csv)
    save_matrix(t_matrix, t_csv)
    plot_heatmap(
        coef_matrix,
        coef_png,
        title=f"{model.label}: FAC coefficient",
        colorbar_label="FAC coefficient",
        cmap="RdBu_r",
        center_zero=True,
        annotate=annotate,
    )
    plot_t_stat_heatmap(
        t_matrix,
        t_png,
        title=f"{model.label}: FAC t-stat",
        annotate=annotate,
    )

    print(f"完成样本组：{model.key}")
    print(f"  系数矩阵：{coef_csv}")
    print(f"  t 值矩阵：{t_csv}")
    print(f"  系数热力图：{coef_png}")
    print(f"  t 值热力图：{t_png}")

    return make_significance_summary(model, long_table), long_table


def main() -> None:
    """程序入口。"""
    args = parse_args()
    output_dir = resolve_output_dir(args.output_dir)

    check_input_files(HEATMAP_MODELS, allow_missing=args.allow_missing)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary_parts: list[pd.DataFrame] = []
    model_tables: list[tuple[HeatmapModel, pd.DataFrame]] = []
    processed_count = 0
    for model in HEATMAP_MODELS:
        if not model.result_path.exists():
            continue
        significant_summary, long_table = process_model(
            model, output_dir, annotate=bool(args.annotate)
        )
        summary_parts.append(significant_summary)
        model_tables.append((model, long_table))
        processed_count += 1

    if processed_count == 0:
        raise FileNotFoundError("没有可处理的热力图回归结果文件。")

    if summary_parts:
        summary = pd.concat(summary_parts, ignore_index=True)
    else:
        summary = pd.DataFrame(
            columns=[
                "sample_group",
                "sample_label",
                "m",
                "n",
                "factor",
                "variable",
                "coef",
                "t_stat",
                "p_value",
                "n_months",
                "avg_monthly_n",
            ]
        )

    summary_path = output_dir / "heatmap_significant_fac_summary_abs_t_ge_1_96.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    all_groups = make_all_groups_summary(model_tables)
    all_groups_path = output_dir / "all_groups_summary.csv"
    all_groups.to_csv(all_groups_path, index=False, encoding="utf-8-sig")
    combined_outputs = save_combined_heatmaps(
        all_groups, output_dir, annotate=bool(args.annotate)
    )

    effective = build_effective_mn_summary(all_groups)
    effective_path = output_dir / "effective_mn_summary.csv"
    effective.to_csv(effective_path, index=False, encoding="utf-8-sig")

    conclusion_path = output_dir / "heatmap_conclusion.md"
    write_conclusion_markdown(conclusion_path, all_groups, effective)

    print("\n热力图汇总完成。")
    print(f"处理样本组数量：{processed_count}")
    print(f"显著性 summary：{summary_path}")
    print(f"全样本组 summary：{all_groups_path}")
    print(f"有效组合 summary：{effective_path}")
    print(f"Markdown 结论草稿：{conclusion_path}")
    print("综合热力图：")
    for output_path in combined_outputs.values():
        print(f"  {output_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n热力图汇总失败：{exc}")
        raise SystemExit(1) from None
