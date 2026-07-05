"""按集中登记的经济假设 family 统一执行 BH-FDR。

示例：

    # 查看所有 family 及审核状态
    .venv/bin/python D_analysis/scripts/apply_fdr.py --list

    # 只检查输入、筛选行和 p 值合法性，不写文件
    .venv/bin/python D_analysis/scripts/apply_fdr.py \
        --family fac_heatmap__fm_heatmap_full --dry-run

    # 执行一个已启用 family
    .venv/bin/python D_analysis/scripts/apply_fdr.py \
        --family hitrate_nonoverlap_primary

    # 执行全部 active family
    .venv/bin/python D_analysis/scripts/apply_fdr.py --all-active

本脚本不会覆盖原始回归结果。每个 family 的统一结果写到
``D_analysis/output/fund_consistency/fdr/<family_id>/``。
每个成功写出的 family 都会同时生成两张热力图：一张按 BH-FDR q<0.05 判定显著性
（正式结论用），一张按未经多重检验调整的 raw p<0.05 判定显著性（仅供对照，
不能替代 q 值作为正式结论）。完整 FAC 参数搜索使用 12×11 的 ``(m,n)`` 网格；
标准 FAC 20 项 family 使用“5个窗口×4个Y期限”网格；其余 family 按结果行顺序
排成紧凑网格。使用 ``--annotate-heatmap`` 可以在每个格子中显示统计量和 q/p 值。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

# matplotlib 默认会尝试在用户目录写字体缓存。把缓存放到临时目录，既适合
# 无图形界面的批处理环境，也不会在项目目录留下与分析结果无关的文件。
os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "fund_analysis_matplotlib_cache"),
)

import matplotlib

matplotlib.use("Agg")
# 部分控制变量名（如基金类型哑变量）含中文；默认 DejaVu Sans 没有对应字形，
# 会在图上显示成方框。换成系统自带的中文黑体，并关掉 unicode 负号（黑体一般
# 没有那个字形，否则负数刻度也会变成方框）。
matplotlib.rcParams["font.sans-serif"] = [
    "Heiti TC",
    "PingFang HK",
    "Arial Unicode MS",
    "STHeiti",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fdr_registry import FDR_FAMILIES, get_family, list_families


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "D_analysis" / "output" / "fund_consistency" / "fdr"
)
RUNNABLE_STATUSES = {"active"}
FAC_HEATMAP_FAMILY_PREFIX = "fac_heatmap__"
FAC_HEATMAP_PATTERN = re.compile(
    r"^FAC_rank_vol_m(?P<m>\d+)_n(?P<n>\d+)_pairwise1$"
)
FAC_HEATMAP_M_VALUES = range(1, 13)
FAC_HEATMAP_N_VALUES = range(2, 13)
FAC_HEATMAP_FILENAME = "fac_t_stat_fdr_heatmap.png"
FAC_HEATMAP_NOMINAL_FILENAME = "fac_t_stat_nominal_p_heatmap.png"
FDR_HEATMAP_FILENAME = "fdr_heatmap.png"
NOMINAL_HEATMAP_FILENAME = "nominal_p_heatmap.png"
NOMINAL_P_THRESHOLD = 0.05
STANDARD_FAC_FAMILY_PREFIX = "standard_fac_20__"
STANDARD_FAC_WINDOWS = ("m3_n6", "m6_n3", "m6_n6", "m6_n12", "m12_n6")
STANDARD_FAC_Y_HORIZONS = ("y1m", "y3m", "y6m", "y12m")
STANDARD_FAC_SOURCE_PATTERN = re.compile(r"__(?P<y>y1m|y3m|y6m|y12m)$")

# 跨探索分组的综合显著性汇总：只统计五个探索性 fm_heatmap_* 分组，Full sample
# 是主检验，不参与"有几个分组显著"的计数（与 plot_consistency_heatmaps.py 一致）。
FAC_HEATMAP_EXPLORATORY_MODEL_KEYS = (
    "fm_heatmap_up",
    "fm_heatmap_down",
    "fm_heatmap_top33",
    "fm_heatmap_mid33",
    "fm_heatmap_bottom33",
)
FAC_HEATMAP_COMBINED_DIRNAME = "fac_heatmap__combined"
CONTROL_VARIABLE_PANEL_FILENAME = "control_variable_coef_panel.png"


class InvalidPValueError(ValueError):
    """输入中出现非缺失但不合法的 p 值。"""


def parse_args() -> argparse.Namespace:
    """读取统一 FDR 命令行参数。"""
    parser = argparse.ArgumentParser(description="按登记的 family 统一执行 BH-FDR。")
    parser.add_argument("--list", action="store_true", help="列出全部 family 后退出。")
    parser.add_argument(
        "--family",
        action="append",
        default=[],
        help="要执行的 family id；可重复传入。",
    )
    parser.add_argument(
        "--all-active",
        action="store_true",
        help="执行所有 status=active 的 family。",
    )
    parser.add_argument(
        "--include-pending",
        action="store_true",
        help="允许显式执行 pending_user_review family；默认禁止。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="完成读取、筛选和 p 值校验，但不写输出。",
    )
    parser.add_argument(
        "--annotate-heatmap",
        action="store_true",
        help="在 FDR 热力图格子内标注统计量和 q 值；默认不标注。",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="统一 FDR 输出根目录。",
    )
    return parser.parse_args()


def resolve_project_path(raw_path: str | Path) -> Path:
    """把 registry 中的相对路径解释为项目根目录下路径。"""
    path = Path(raw_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def parse_truthy(series: pd.Series, *, column: str) -> pd.Series:
    """严格解析布尔列，避免字符串 ``False`` 被 Python 当成真。"""
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False).astype(bool)
    normalized = series.astype("string").str.strip().str.lower()
    mapping = {
        "true": True,
        "1": True,
        "yes": True,
        "false": False,
        "0": False,
        "no": False,
    }
    unknown = normalized.notna() & ~normalized.isin(mapping)
    if unknown.any():
        examples = normalized.loc[unknown].drop_duplicates().head(5).tolist()
        raise ValueError(f"布尔筛选列 {column} 含无法识别的值：{examples}")
    return normalized.map(mapping).fillna(False).astype(bool)


def apply_selector(frame: pd.DataFrame, selector: dict[str, Any]) -> pd.Series:
    """把一个声明式 selector 转成布尔掩码。"""
    operation = str(selector.get("op", ""))
    if operation == "equals":
        column = str(selector["column"])
        require_columns(frame, [column])
        return frame[column].eq(selector.get("value"))
    if operation == "regex":
        column = str(selector["column"])
        require_columns(frame, [column])
        return frame[column].astype("string").str.match(
            str(selector["pattern"]), na=False
        )
    if operation == "truthy":
        column = str(selector["column"])
        require_columns(frame, [column])
        return parse_truthy(frame[column], column=column)
    if operation == "column_equals_column":
        left = str(selector["left"])
        right = str(selector["right"])
        require_columns(frame, [left, right])
        return frame[left].astype("string").eq(frame[right].astype("string"))
    raise ValueError(f"不支持的 selector op：{operation!r}")


def require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    """一次性报告缺失列，避免后续产生难理解的 KeyError。"""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"结果文件缺少必要列：{missing}")


def read_source(source: dict[str, Any]) -> pd.DataFrame:
    """读取一个来源表，并按登记条件提取属于当前 family 的假设行。"""
    path = resolve_project_path(str(source["path"]))
    if not path.exists():
        raise FileNotFoundError(f"FDR 输入文件不存在：{path}")

    frame = pd.read_csv(path, encoding="utf-8-sig")
    p_column = str(source.get("p_column", "p_value"))
    require_columns(frame, [p_column])

    mask = pd.Series(True, index=frame.index, dtype=bool)
    for selector in source.get("selectors", []):
        mask &= apply_selector(frame, dict(selector))

    selected = frame.loc[mask].copy()
    if selected.empty:
        raise ValueError(
            f"FDR 来源筛选后没有任何行：{path}；selectors={source.get('selectors', [])}"
        )

    # 保留来源行号，方便 q 值异常时准确回查原始 CSV。
    selected.insert(0, "source_row", selected.index.astype(int) + 2)
    selected.insert(0, "source_label", str(source.get("label", path.name)))
    selected.insert(0, "source_path", str(path.relative_to(PROJECT_ROOT)))
    selected["fdr_input_p_value_raw"] = selected[p_column]
    selected["fdr_input_p_column"] = p_column
    return selected.reset_index(drop=True)


def validate_p_values(raw: pd.Series, *, family_id: str) -> tuple[pd.Series, pd.Series, dict[str, int]]:
    """严格校验 p 值，并返回数值列、有效掩码与审计计数。

    估计失败产生的真正缺失值允许排除；任何非缺失的非数字、无穷值或越界值
    都直接报错。这样可以避免负 p 值被 ``clip`` 成 q=0 后伪装成高度显著。
    """
    missing = raw.isna() | raw.astype("string").str.strip().eq("")
    numeric = pd.to_numeric(raw.where(~missing), errors="coerce")
    non_numeric = ~missing & numeric.isna()
    finite = pd.Series(np.isfinite(numeric.to_numpy(dtype=float)), index=raw.index)
    non_finite = ~missing & numeric.notna() & ~finite
    out_of_range = ~missing & numeric.notna() & finite & ~numeric.between(0.0, 1.0)

    invalid = non_numeric | non_finite | out_of_range
    if invalid.any():
        examples = pd.DataFrame(
            {
                "raw": raw.loc[invalid].astype("string"),
                "non_numeric": non_numeric.loc[invalid],
                "non_finite": non_finite.loc[invalid],
                "out_of_range": out_of_range.loc[invalid],
            }
        ).head(10)
        raise InvalidPValueError(
            f"family={family_id} 发现 {int(invalid.sum())} 个非法 p 值；"
            "非缺失 p 值必须是 [0,1] 内有限数字。示例：\n"
            + examples.to_string(index=False)
        )

    valid = ~missing
    counts = {
        "input_rows": int(len(raw)),
        "valid_p_values": int(valid.sum()),
        "excluded_missing_p_values": int(missing.sum()),
        "invalid_non_numeric": int(non_numeric.sum()),
        "invalid_non_finite": int(non_finite.sum()),
        "invalid_out_of_range": int(out_of_range.sum()),
    }
    return numeric.astype(float), valid, counts


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """对已经通过严格校验的一组有效 p 值计算 BH q-value。"""
    if p_values.empty:
        return pd.Series(dtype=float, index=p_values.index)
    if p_values.isna().any() or not np.isfinite(p_values.to_numpy(dtype=float)).all():
        raise ValueError("benjamini_hochberg 只接受无缺失、有限的 p 值。")
    if not p_values.between(0.0, 1.0).all():
        raise ValueError("benjamini_hochberg 只接受 [0,1] 内的 p 值。")

    ordered = p_values.sort_values(kind="mergesort")
    family_size = len(ordered)
    ranks = np.arange(1, family_size + 1, dtype=float)
    raw_q = ordered.to_numpy(dtype=float) * family_size / ranks
    adjusted = np.minimum.accumulate(raw_q[::-1])[::-1]
    result = pd.Series(np.nan, index=p_values.index, dtype=float)
    result.loc[ordered.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def parse_fac_heatmap_coordinates(value: object) -> tuple[int, int] | None:
    """从 FAC 变量名严格解析热力图坐标 ``(m, n)``。

    这里只接受 ``pairwise1`` 的完整变量名，避免把其他窗口口径误放进同一张
    正式网格。范围检查放在构建矩阵时完成，以便给出更清楚的错误信息。
    """
    match = FAC_HEATMAP_PATTERN.fullmatch(str(value))
    if match is None:
        return None
    return int(match.group("m")), int(match.group("n"))


def build_fac_heatmap_matrices(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """把 FDR 长表转换成 12×11 的 t 值、q 值与 raw p 值矩阵。

    行表示单期过去收益期限 m，列表示排名期数 n。缺失或无法估计的 t/q/p 值
    保持为 NaN；但变量名不合法、坐标越界或同一坐标重复会直接报错，因为这些
    情况意味着图和底表已经不能一一对应。
    """
    require_columns(frame, ["variable", "t_stat", "p_value", "q_value"])

    coordinates = [parse_fac_heatmap_coordinates(value) for value in frame["variable"]]
    invalid_names = [
        str(frame.iloc[index]["variable"])
        for index, coordinate in enumerate(coordinates)
        if coordinate is None
    ]
    if invalid_names:
        raise ValueError(
            "FAC 热力图 family 中出现无法解析的 variable；示例："
            f"{invalid_names[:5]}"
        )

    grid_rows = frame[["variable", "t_stat", "p_value", "q_value"]].copy()
    grid_rows["m"] = [coordinate[0] for coordinate in coordinates if coordinate]
    grid_rows["n"] = [coordinate[1] for coordinate in coordinates if coordinate]

    outside_grid = ~grid_rows["m"].between(1, 12) | ~grid_rows["n"].between(2, 12)
    if outside_grid.any():
        examples = grid_rows.loc[outside_grid, ["variable", "m", "n"]].head(5)
        raise ValueError(
            "FAC 热力图坐标必须位于 m=1..12、n=2..12；示例：\n"
            + examples.to_string(index=False)
        )

    duplicated = grid_rows.duplicated(["m", "n"], keep=False)
    if duplicated.any():
        examples = grid_rows.loc[duplicated, ["variable", "m", "n"]].head(10)
        raise ValueError(
            "FAC 热力图同一个 (m,n) 出现多行，无法确定应绘制哪一个值：\n"
            + examples.to_string(index=False)
        )

    # 先建立完整网格，再逐行填值。这样即使某个规格没有结果，坐标轴仍然固定，
    # 不会因为缺行导致后续格子错位。
    t_matrix = pd.DataFrame(
        np.nan,
        index=FAC_HEATMAP_M_VALUES,
        columns=FAC_HEATMAP_N_VALUES,
        dtype=float,
    )
    q_matrix = t_matrix.copy()
    p_matrix = t_matrix.copy()
    for row in grid_rows.itertuples(index=False):
        t_matrix.loc[int(row.m), int(row.n)] = pd.to_numeric(
            row.t_stat, errors="coerce"
        )
        q_matrix.loc[int(row.m), int(row.n)] = pd.to_numeric(
            row.q_value, errors="coerce"
        )
        p_matrix.loc[int(row.m), int(row.n)] = pd.to_numeric(
            row.p_value, errors="coerce"
        )

    for matrix in (t_matrix, q_matrix, p_matrix):
        matrix.index.name = "m"
        matrix.columns.name = "n"
    return t_matrix, q_matrix, p_matrix


def discover_control_variables(raw_frame: pd.DataFrame) -> list[str]:
    """从 132 窗口热力图 family 的原始（未做 selector 筛选）结果中，
    找出除截距和 FAC 本身以外的全部控制变量，按其在表中首次出现的顺序返回。
    """
    seen: dict[str, None] = {}
    for value in raw_frame["variable"].astype(str):
        if value == "const" or FAC_HEATMAP_PATTERN.fullmatch(value) is not None:
            continue
        seen.setdefault(value, None)
    return list(seen.keys())


def build_variable_grid(
    raw_frame: pd.DataFrame,
    variable: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """为单个非 FAC 变量（如控制变量）整理跨 132 个窗口的 coef/t/raw p 矩阵。

    每个窗口是一次独立的 Fama-MacBeth 回归，(m,n) 坐标要从 ``factor`` 列解析
    （``factor`` 标记当前这次回归用的是哪个 FAC 窗口，``variable`` 才是本函数
    要抽取的那个具体变量名，两者在控制变量行上并不相等）。
    """
    subset = raw_frame.loc[raw_frame["variable"].astype(str) == variable].copy()
    require_columns(subset, ["factor", "coef", "t_stat", "p_value"])

    coordinates = [parse_fac_heatmap_coordinates(value) for value in subset["factor"]]
    invalid_names = [
        str(subset.iloc[index]["factor"])
        for index, coordinate in enumerate(coordinates)
        if coordinate is None
    ]
    if invalid_names:
        raise ValueError(
            f"变量 {variable!r} 存在无法解析窗口坐标的 factor；示例：{invalid_names[:5]}"
        )

    grid_rows = subset[["factor", "coef", "t_stat", "p_value"]].copy()
    grid_rows["m"] = [coordinate[0] for coordinate in coordinates]
    grid_rows["n"] = [coordinate[1] for coordinate in coordinates]

    outside_grid = ~grid_rows["m"].between(1, 12) | ~grid_rows["n"].between(2, 12)
    if outside_grid.any():
        raise ValueError(f"变量 {variable!r} 出现越界窗口坐标（应为 m=1..12、n=2..12）。")
    duplicated = grid_rows.duplicated(["m", "n"], keep=False)
    if duplicated.any():
        raise ValueError(f"变量 {variable!r} 同一个 (m,n) 出现多行，无法确定取哪一行。")

    coef_matrix = pd.DataFrame(
        np.nan, index=FAC_HEATMAP_M_VALUES, columns=FAC_HEATMAP_N_VALUES, dtype=float
    )
    t_matrix = coef_matrix.copy()
    p_matrix = coef_matrix.copy()
    for row in grid_rows.itertuples(index=False):
        coef_matrix.loc[int(row.m), int(row.n)] = pd.to_numeric(
            row.coef, errors="coerce"
        )
        t_matrix.loc[int(row.m), int(row.n)] = pd.to_numeric(
            row.t_stat, errors="coerce"
        )
        p_matrix.loc[int(row.m), int(row.n)] = pd.to_numeric(
            row.p_value, errors="coerce"
        )
    for matrix in (coef_matrix, t_matrix, p_matrix):
        matrix.index.name = "m"
        matrix.columns.name = "n"
    return coef_matrix, t_matrix, p_matrix


def plot_control_variable_panel(
    variable_grids: dict[str, tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]],
    output_path: Path,
    *,
    family_id: str,
    significance_threshold: float,
    annotate: bool,
) -> None:
    """把多个控制变量的系数矩阵拼成一页小倍图（small multiples）。

    颜色表示系数大小，每个子图按自己的取值范围单独归一化（不同变量单位不同，
    不能共用一个色标）；黑框表示 raw p < 阈值——这是未经多重检验校正的参考
    信息，用来快速判断"这个控制变量在整个窗口搜索里是不是一直显著、方向稳不
    稳定"，不是正式的 FDR 结论。
    """
    variable_names = list(variable_grids.keys())
    column_count = min(3, len(variable_names)) or 1
    row_count = int(np.ceil(len(variable_names) / column_count))
    fig, axes = plt.subplots(
        row_count,
        column_count,
        figsize=(4.6 * column_count, 3.8 * row_count),
        squeeze=False,
    )

    for index, variable_name in enumerate(variable_names):
        axis = axes[index // column_count][index % column_count]
        coef_matrix, _, p_matrix = variable_grids[variable_name]
        values = coef_matrix.to_numpy(dtype=float)
        p_values = p_matrix.to_numpy(dtype=float)
        finite = np.isfinite(values)
        max_abs = np.nanmax(np.abs(values[finite])) if finite.any() else 1.0
        max_abs = max(float(max_abs), 1e-12)
        norm = matplotlib.colors.Normalize(vmin=-max_abs, vmax=max_abs)
        cmap = plt.get_cmap("RdBu_r")

        image = axis.imshow(values, origin="lower", cmap=cmap, norm=norm)
        axis.set_title(variable_name, fontsize=9)
        axis.set_xticks(
            range(len(coef_matrix.columns)),
            labels=[str(value) for value in coef_matrix.columns],
            fontsize=6,
        )
        axis.set_yticks(
            range(len(coef_matrix.index)),
            labels=[str(value) for value in coef_matrix.index],
            fontsize=6,
        )
        axis.set_xticks(np.arange(-0.5, len(coef_matrix.columns), 1), minor=True)
        axis.set_yticks(np.arange(-0.5, len(coef_matrix.index), 1), minor=True)
        axis.grid(which="minor", color="white", linewidth=0.5)
        axis.tick_params(which="minor", bottom=False, left=False, length=0)

        significant = finite & np.isfinite(p_values) & (p_values < significance_threshold)
        for row_index, column_index in np.argwhere(significant):
            axis.add_patch(
                plt.Rectangle(
                    (column_index - 0.5, row_index - 0.5),
                    1,
                    1,
                    fill=False,
                    edgecolor="black",
                    linewidth=1.1,
                )
            )

        if annotate:
            for row_index in range(values.shape[0]):
                for column_index in range(values.shape[1]):
                    value = values[row_index, column_index]
                    if np.isfinite(value):
                        axis.text(
                            column_index,
                            row_index,
                            f"{value:.2f}",
                            ha="center",
                            va="center",
                            fontsize=4.2,
                            color="black",
                        )

        fig.colorbar(image, ax=axis, shrink=0.75, pad=0.02)

    for index in range(len(variable_names), row_count * column_count):
        axes[index // column_count][index % column_count].axis("off")

    fig.suptitle(
        f"Control-variable coefficients across the (m,n) window search\n{family_id}",
        fontsize=13,
    )
    fig.text(
        0.5,
        0.005,
        f"Color = coefficient value (each panel normalized to its own range); "
        f"black border: raw p < {significance_threshold:g} "
        "(NOT BH-FDR adjusted, reference only).",
        ha="center",
        fontsize=8.5,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.95))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def write_control_variable_panel(
    config: dict[str, Any],
    output_dir: Path,
    *,
    annotate: bool,
) -> Path | None:
    """为单个 132 窗口 family 生成控制变量的小倍图；没有可用来源或控制变量则跳过。"""
    sources = config.get("sources") or []
    if len(sources) != 1:
        return None
    source_path = resolve_project_path(str(sources[0]["path"]))
    if not source_path.exists():
        return None

    raw_frame = pd.read_csv(source_path, encoding="utf-8-sig")
    control_variables = discover_control_variables(raw_frame)
    if not control_variables:
        return None

    variable_grids = {
        variable: build_variable_grid(raw_frame, variable)
        for variable in control_variables
    }
    output_path = output_dir / CONTROL_VARIABLE_PANEL_FILENAME
    plot_control_variable_panel(
        variable_grids,
        output_path,
        family_id=output_dir.name,
        significance_threshold=NOMINAL_P_THRESHOLD,
        annotate=annotate,
    )
    return output_path


def build_combined_fac_significance_matrices(
    family_frames: dict[str, pd.DataFrame],
    *,
    significance_column: str,
    default_threshold: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """跨若干 FAC heatmap 探索性 family，按 (m,n) 汇总显著次数与带符号显著次数。

    ``significance_column`` 为 ``"q_value"`` 时统计 BH-FDR 口径，为 ``"p_value"``
    时统计未经多重检验校正的 raw p 口径；符号取自 t_stat（与系数符号一致，
    因为 ``t_stat = coef / standard_error``，标准误恒为正）。
    """
    count_matrix = pd.DataFrame(
        0.0, index=FAC_HEATMAP_M_VALUES, columns=FAC_HEATMAP_N_VALUES, dtype=float
    )
    signed_matrix = count_matrix.copy()
    for frame in family_frames.values():
        t_matrix, q_matrix, p_matrix = build_fac_heatmap_matrices(frame)
        significance_matrix = q_matrix if significance_column == "q_value" else p_matrix

        threshold = default_threshold
        if significance_column == "q_value" and "fdr_q_threshold" in frame.columns:
            observed = pd.to_numeric(
                frame["fdr_q_threshold"], errors="coerce"
            ).dropna()
            if not observed.empty:
                threshold = float(observed.iloc[0])

        significant = significance_matrix.notna() & significance_matrix.lt(threshold)
        signed = np.sign(t_matrix.where(significant)).fillna(0.0)
        count_matrix += significant.astype(float)
        signed_matrix += signed

    for matrix in (count_matrix, signed_matrix):
        matrix.index.name = "m"
        matrix.columns.name = "n"
    return count_matrix, signed_matrix


def plot_full_color_heatmap(
    matrix: pd.DataFrame,
    output_path: Path,
    *,
    title: str,
    colorbar_label: str,
    cmap: str,
    center_zero: bool,
    annotate: bool,
) -> None:
    """绘制不做显著性门槛过滤的普通 12x11 热力图（直接看数值）。"""
    values = matrix.to_numpy(dtype=float)
    if center_zero:
        max_abs = np.nanmax(np.abs(values)) if np.isfinite(values).any() else 1.0
        vmin, vmax = -max_abs, max_abs
    else:
        vmin = float(np.nanmin(values)) if np.isfinite(values).any() else 0.0
        vmax = float(np.nanmax(values)) if np.isfinite(values).any() else 1.0

    fig, axis = plt.subplots(figsize=(9.5, 7.5))
    image = axis.imshow(values, origin="lower", cmap=cmap, vmin=vmin, vmax=vmax)
    axis.set_title(title, fontsize=13, pad=12)
    axis.set_xlabel("n: number of ranking periods", fontsize=11)
    axis.set_ylabel("m: return horizon per ranking period (months)", fontsize=11)
    axis.set_xticks(range(len(matrix.columns)), labels=[str(v) for v in matrix.columns])
    axis.set_yticks(range(len(matrix.index)), labels=[str(v) for v in matrix.index])
    axis.set_xticks(np.arange(-0.5, len(matrix.columns), 1), minor=True)
    axis.set_yticks(np.arange(-0.5, len(matrix.index), 1), minor=True)
    axis.grid(which="minor", color="white", linestyle="-", linewidth=0.8)
    axis.tick_params(which="minor", bottom=False, left=False)

    if annotate:
        for row_index in range(values.shape[0]):
            for column_index in range(values.shape[1]):
                value = values[row_index, column_index]
                if np.isfinite(value):
                    axis.text(
                        column_index,
                        row_index,
                        f"{value:.0f}",
                        ha="center",
                        va="center",
                        fontsize=6,
                        color="black",
                    )

    colorbar = fig.colorbar(image, ax=axis, shrink=0.88)
    colorbar.set_label(colorbar_label)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def write_combined_fac_summary(
    output_root: Path,
    *,
    annotate: bool,
) -> dict[str, Path] | None:
    """汇总五个探索性 fm_heatmap_* 分组在每个 (m,n) 上的显著次数与方向。

    对应 plot_consistency_heatmaps.py 原有的 combined significant heatmap，
    分别按 BH-FDR q<0.05 和 raw p<0.05（未校正）各出一版 count + signed 图。
    需要五个探索分组的 fdr_results.csv 都已经由 run_family 生成；缺任何一个
    都直接跳过并返回 None，由调用方决定如何提示。
    """
    family_frames: dict[str, pd.DataFrame] = {}
    for model_key in FAC_HEATMAP_EXPLORATORY_MODEL_KEYS:
        family_id = f"{FAC_HEATMAP_FAMILY_PREFIX}{model_key}"
        result_path = output_root / family_id / "fdr_results.csv"
        if not result_path.exists():
            return None
        family_frames[model_key] = pd.read_csv(result_path, encoding="utf-8-sig")

    combined_dir = output_root / FAC_HEATMAP_COMBINED_DIRNAME
    combined_dir.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}

    for mode, significance_column, threshold, mode_label in (
        ("fdr", "q_value", 0.05, "BH-FDR q<0.05"),
        ("nominal", "p_value", NOMINAL_P_THRESHOLD, "raw p<0.05 (unadjusted)"),
    ):
        count_matrix, signed_matrix = build_combined_fac_significance_matrices(
            family_frames,
            significance_column=significance_column,
            default_threshold=threshold,
        )

        count_csv = combined_dir / f"combined_significant_group_count_{mode}.csv"
        count_png = combined_dir / f"combined_significant_group_count_{mode}.png"
        count_matrix.to_csv(count_csv, encoding="utf-8-sig")
        plot_full_color_heatmap(
            count_matrix,
            count_png,
            title=f"Exploratory groups: number with {mode_label}",
            colorbar_label=f"count of subgroups with {mode_label}",
            cmap="YlGnBu",
            center_zero=False,
            annotate=annotate,
        )
        outputs[f"{mode}_count_csv"] = count_csv
        outputs[f"{mode}_count_png"] = count_png

        signed_csv = combined_dir / f"combined_signed_significant_count_{mode}.csv"
        signed_png = combined_dir / f"combined_signed_significant_count_{mode}.png"
        signed_matrix.to_csv(signed_csv, encoding="utf-8-sig")
        plot_full_color_heatmap(
            signed_matrix,
            signed_png,
            title=f"Exploratory groups: signed {mode_label} count",
            colorbar_label="negative groups (-) / positive groups (+)",
            cmap="RdBu_r",
            center_zero=True,
            annotate=annotate,
        )
        outputs[f"{mode}_signed_csv"] = signed_csv
        outputs[f"{mode}_signed_png"] = signed_png

    metadata = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "exploratory_models": list(FAC_HEATMAP_EXPLORATORY_MODEL_KEYS),
        "primary_model_excluded": "fm_heatmap_full",
        "modes": {
            "fdr": "BH-FDR q<0.05 per family（正式结论使用）",
            "nominal": f"raw p<{NOMINAL_P_THRESHOLD:g}，未做多重检验校正（仅供对照）",
        },
    }
    metadata_path = combined_dir / "combined_fac_summary_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    outputs["metadata"] = metadata_path
    return outputs


def plot_fac_significance_heatmap(
    t_matrix: pd.DataFrame,
    significance_matrix: pd.DataFrame,
    *,
    family_id: str,
    significance_threshold: float,
    significance_tag: str,
    significance_label: str,
    title_note: str,
    footer_note: str,
    output_path: Path,
    annotate: bool,
) -> None:
    """绘制 FAC t-stat 热力图，显著格子按传入的显著性矩阵（q 值或 raw p 值）标记。"""
    values = t_matrix.to_numpy(dtype=float)
    q_values = significance_matrix.to_numpy(dtype=float)
    finite = np.isfinite(values)
    significant = finite & np.isfinite(q_values) & (q_values < significance_threshold)
    nonsignificant = finite & ~significant

    # 缺失 t 值使用浅灰；可估但 FDR 不显著的格子使用灰阶。显著格子才使用
    # 红蓝发散色，因此颜色方向和统计显著性可以同时看清楚。
    image_values = np.ones((*values.shape, 4), dtype=float)
    image_values[:, :, :3] = 0.93
    image_values[:, :, 3] = 1.0

    gray_strength = np.zeros_like(values, dtype=float)
    gray_strength[nonsignificant] = np.clip(
        np.minimum(np.abs(values[nonsignificant]), 1.96) / 1.96,
        0.0,
        1.0,
    )
    gray_rgb = 0.35 + 0.50 * gray_strength
    for channel in range(3):
        image_values[:, :, channel] = np.where(
            nonsignificant, gray_rgb, image_values[:, :, channel]
        )

    max_abs = np.nanmax(np.abs(values[significant])) if significant.any() else 1.0
    max_abs = max(float(max_abs), 1.96)
    norm = matplotlib.colors.Normalize(vmin=-max_abs, vmax=max_abs)
    cmap = plt.get_cmap("RdBu_r")
    image_values[significant] = cmap(norm(values[significant]))

    fig, axis = plt.subplots(figsize=(10.0, 8.0))
    axis.imshow(image_values, origin="lower", aspect="equal")
    axis.set_title(f"FAC t-stat and {title_note}\n{family_id}", fontsize=13)
    axis.set_xlabel("n: number of ranking periods")
    axis.set_ylabel("m: return horizon per ranking period (months)")
    axis.set_xticks(
        range(len(FAC_HEATMAP_N_VALUES)),
        labels=[str(value) for value in FAC_HEATMAP_N_VALUES],
    )
    axis.set_yticks(
        range(len(FAC_HEATMAP_M_VALUES)),
        labels=[str(value) for value in FAC_HEATMAP_M_VALUES],
    )
    axis.set_xticks(np.arange(-0.5, len(FAC_HEATMAP_N_VALUES), 1), minor=True)
    axis.set_yticks(np.arange(-0.5, len(FAC_HEATMAP_M_VALUES), 1), minor=True)
    axis.grid(False, which="major")
    axis.grid(which="minor", color="white", linewidth=0.9)
    axis.tick_params(which="minor", bottom=False, left=False)

    # 黑框只表达一件事：该格子的显著性统计量低于当前阈值。
    for row_index, column_index in np.argwhere(significant):
        axis.add_patch(
            plt.Rectangle(
                (column_index - 0.5, row_index - 0.5),
                1,
                1,
                fill=False,
                edgecolor="black",
                linewidth=1.8,
            )
        )

    if annotate:
        for row_index in range(values.shape[0]):
            for column_index in range(values.shape[1]):
                t_value = values[row_index, column_index]
                q_value = q_values[row_index, column_index]
                if not np.isfinite(t_value):
                    label = "NA"
                else:
                    label = f"t={t_value:.2f}"
                    if np.isfinite(q_value):
                        label += f"\n{significance_tag}={q_value:.2f}"
                # 深色格子使用白字，浅色格子使用黑字，避免标注被底色吞掉。
                rgb_mean = float(image_values[row_index, column_index, :3].mean())
                axis.text(
                    column_index,
                    row_index,
                    label,
                    ha="center",
                    va="center",
                    fontsize=5.7,
                    color="white" if rgb_mean < 0.5 else "black",
                )

    colorbar = fig.colorbar(
        matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap),
        ax=axis,
        shrink=0.86,
    )
    colorbar.set_label(f"t-stat for cells with {significance_label}")
    fig.text(
        0.5,
        0.012,
        footer_note,
        ha="center",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def build_standard_fac_20_matrices(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """把标准 FAC 20 项长表整理成“固定窗口×Y期限”的三个矩阵（t/q/raw p）。"""
    require_columns(
        frame, ["source_label", "variable", "t_stat", "p_value", "q_value"]
    )

    rows: list[dict[str, object]] = []
    for record in frame.itertuples(index=False):
        coordinate = parse_fac_heatmap_coordinates(record.variable)
        source_match = STANDARD_FAC_SOURCE_PATTERN.search(str(record.source_label))
        if coordinate is None or source_match is None:
            raise ValueError(
                "standard_fac_20 热力图无法解析窗口或 Y 期限："
                f"variable={record.variable!r}, source_label={record.source_label!r}"
            )
        window = f"m{coordinate[0]}_n{coordinate[1]}"
        rows.append(
            {
                "window": window,
                "y_horizon": source_match.group("y"),
                "t_stat": pd.to_numeric(record.t_stat, errors="coerce"),
                "p_value": pd.to_numeric(record.p_value, errors="coerce"),
                "q_value": pd.to_numeric(record.q_value, errors="coerce"),
            }
        )

    grid_rows = pd.DataFrame(rows)
    duplicated = grid_rows.duplicated(["window", "y_horizon"], keep=False)
    if duplicated.any():
        raise ValueError("standard_fac_20 热力图出现重复的窗口×Y期限组合。")

    expected = {
        (window, y_horizon)
        for window in STANDARD_FAC_WINDOWS
        for y_horizon in STANDARD_FAC_Y_HORIZONS
    }
    actual = set(zip(grid_rows["window"], grid_rows["y_horizon"], strict=True))
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(
            "standard_fac_20 热力图必须正好包含20项；"
            f"缺少={missing}，多出={extra}"
        )

    t_matrix = grid_rows.pivot(index="window", columns="y_horizon", values="t_stat")
    q_matrix = grid_rows.pivot(index="window", columns="y_horizon", values="q_value")
    p_matrix = grid_rows.pivot(index="window", columns="y_horizon", values="p_value")
    return (
        t_matrix.reindex(index=STANDARD_FAC_WINDOWS, columns=STANDARD_FAC_Y_HORIZONS),
        q_matrix.reindex(index=STANDARD_FAC_WINDOWS, columns=STANDARD_FAC_Y_HORIZONS),
        p_matrix.reindex(index=STANDARD_FAC_WINDOWS, columns=STANDARD_FAC_Y_HORIZONS),
    )


def select_generic_heatmap_metric(
    frame: pd.DataFrame,
) -> tuple[pd.Series, str, bool]:
    """选择通用热力图的颜色指标，并说明是否使用正负发散色阶。"""
    for column, label in (
        ("t_stat", "t-stat"),
        ("estimate", "estimate"),
        ("coef", "coefficient"),
    ):
        if column not in frame.columns:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().any():
            return numeric, label, True

    # Wald/IUT 等结果没有带方向的统计量时，用 -log10(p) 表示证据强度。
    p_values = pd.to_numeric(frame["p_value"], errors="coerce")
    safe = p_values.clip(lower=np.finfo(float).tiny, upper=1.0)
    return -np.log10(safe), "-log10(p)", False


def build_generic_fdr_matrices(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str, bool]:
    """把任意 family 的结果行按原顺序折叠成可阅读的紧凑网格。"""
    require_columns(frame, ["p_value", "q_value"])
    values, metric_label, diverging = select_generic_heatmap_metric(frame)
    item_count = len(frame)
    if item_count == 0:
        raise ValueError("FDR 热力图没有可绘制的结果行。")

    # 最多放12列，避免大型 family 被压成一条过长的横带。
    column_count = min(12, max(1, int(np.ceil(np.sqrt(item_count * 1.5)))))
    row_count = int(np.ceil(item_count / column_count))
    value_array = np.full((row_count, column_count), np.nan, dtype=float)
    q_array = np.full((row_count, column_count), np.nan, dtype=float)
    p_array = np.full((row_count, column_count), np.nan, dtype=float)
    value_array.flat[:item_count] = values.to_numpy(dtype=float)
    q_array.flat[:item_count] = pd.to_numeric(
        frame["q_value"], errors="coerce"
    ).to_numpy(dtype=float)
    p_array.flat[:item_count] = pd.to_numeric(
        frame["p_value"], errors="coerce"
    ).to_numpy(dtype=float)

    row_labels = [str(index + 1) for index in range(row_count)]
    column_labels = [str(index + 1) for index in range(column_count)]
    return (
        pd.DataFrame(value_array, index=row_labels, columns=column_labels),
        pd.DataFrame(q_array, index=row_labels, columns=column_labels),
        pd.DataFrame(p_array, index=row_labels, columns=column_labels),
        metric_label,
        diverging,
    )


def plot_fdr_matrix(
    value_matrix: pd.DataFrame,
    significance_matrix: pd.DataFrame,
    *,
    family_id: str,
    metric_label: str,
    significance_threshold: float,
    significance_label: str,
    title_note: str,
    footer_note: str,
    output_path: Path,
    annotate: bool,
    diverging: bool,
    x_label: str,
    y_label: str,
) -> None:
    """绘制通用矩阵：彩色黑框表示通过传入的显著性判定，灰色表示未通过。"""
    values = value_matrix.to_numpy(dtype=float)
    q_values = significance_matrix.to_numpy(dtype=float)
    finite = np.isfinite(values)
    significant = finite & np.isfinite(q_values) & (q_values < significance_threshold)
    nonsignificant = finite & ~significant

    image_values = np.ones((*values.shape, 4), dtype=float)
    image_values[:, :, :3] = 0.93
    gray_strength = np.zeros_like(values, dtype=float)
    finite_abs = np.abs(values[finite])
    gray_scale = max(float(np.nanpercentile(finite_abs, 90)), 1e-12) if finite.any() else 1.0
    gray_strength[nonsignificant] = np.clip(
        np.abs(values[nonsignificant]) / gray_scale, 0.0, 1.0
    )
    gray_rgb = 0.35 + 0.50 * gray_strength
    for channel in range(3):
        image_values[:, :, channel] = np.where(
            nonsignificant, gray_rgb, image_values[:, :, channel]
        )

    significant_values = values[significant]
    if diverging:
        scale = max(float(np.nanmax(np.abs(significant_values))) if significant.any() else 1.0, 1e-12)
        norm = matplotlib.colors.Normalize(vmin=-scale, vmax=scale)
        cmap = plt.get_cmap("RdBu_r")
    else:
        scale = max(float(np.nanmax(significant_values)) if significant.any() else 1.0, 1e-12)
        norm = matplotlib.colors.Normalize(vmin=0.0, vmax=scale)
        cmap = plt.get_cmap("Reds")
    image_values[significant] = cmap(norm(significant_values))

    width = max(7.0, value_matrix.shape[1] * 0.72)
    height = max(4.5, value_matrix.shape[0] * 0.58)
    fig, axis = plt.subplots(figsize=(width, height))
    axis.imshow(image_values, origin="upper", aspect="auto")
    axis.set_title(f"{metric_label} and {title_note}\n{family_id}", fontsize=12)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.set_xticks(range(value_matrix.shape[1]), labels=value_matrix.columns)
    axis.set_yticks(range(value_matrix.shape[0]), labels=value_matrix.index)
    axis.set_xticks(np.arange(-0.5, value_matrix.shape[1], 1), minor=True)
    axis.set_yticks(np.arange(-0.5, value_matrix.shape[0], 1), minor=True)
    axis.grid(False, which="major")
    axis.grid(which="minor", color="white", linewidth=0.8)
    axis.tick_params(which="minor", bottom=False, left=False)

    for row_index, column_index in np.argwhere(significant):
        axis.add_patch(
            plt.Rectangle(
                (column_index - 0.5, row_index - 0.5),
                1,
                1,
                fill=False,
                edgecolor="black",
                linewidth=1.8,
            )
        )

    if annotate:
        for row_index, column_index in np.argwhere(finite):
            q_value = q_values[row_index, column_index]
            label = f"{values[row_index, column_index]:.2f}"
            if np.isfinite(q_value):
                label += f"\nq={q_value:.2f}"
            rgb_mean = float(image_values[row_index, column_index, :3].mean())
            axis.text(
                column_index,
                row_index,
                label,
                ha="center",
                va="center",
                fontsize=5.6,
                color="white" if rgb_mean < 0.5 else "black",
            )

    colorbar = fig.colorbar(
        matplotlib.cm.ScalarMappable(norm=norm, cmap=cmap), ax=axis, shrink=0.86
    )
    colorbar.set_label(f"{metric_label} for cells with {significance_label}")
    fig.text(
        0.5,
        0.012,
        footer_note,
        ha="center",
        fontsize=8.5,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def write_fdr_heatmap(
    frame: pd.DataFrame,
    *,
    family_id: str,
    q_threshold: float,
    output_dir: Path,
    dry_run: bool,
    annotate: bool,
) -> dict[str, Path] | None:
    """为所有 family 写热力图；dry-run 是唯一不写图片的情况。

    每个 family 会写出两张图：一张按 BH-FDR q 值判定显著性（正式结论用），
    一张按未经多重检验调整的 raw p 值判定显著性（q<0.05 一样标灰，仅供对照
    "如果不做 FDR 校正会看起来怎样"，不能替代 q 值作为正式结论）。
    """
    if dry_run:
        return None

    if family_id.startswith(FAC_HEATMAP_FAMILY_PREFIX):
        t_matrix, q_matrix, p_matrix = build_fac_heatmap_matrices(frame)

        fdr_path = output_dir / FAC_HEATMAP_FILENAME
        plot_fac_significance_heatmap(
            t_matrix,
            q_matrix,
            family_id=family_id,
            significance_threshold=q_threshold,
            significance_tag="q",
            significance_label="BH-FDR significance",
            title_note="BH-FDR significance",
            footer_note=(
                f"Colored cells with black borders: q < {q_threshold:g}; "
                "gray: not FDR-significant; light gray: missing t-stat."
            ),
            output_path=fdr_path,
            annotate=annotate,
        )

        nominal_path = output_dir / FAC_HEATMAP_NOMINAL_FILENAME
        plot_fac_significance_heatmap(
            t_matrix,
            p_matrix,
            family_id=family_id,
            significance_threshold=NOMINAL_P_THRESHOLD,
            significance_tag="p",
            significance_label="raw p-value significance (no multiple-testing adjustment)",
            title_note="raw p-value significance (unadjusted)",
            footer_note=(
                f"Colored cells with black borders: raw p < {NOMINAL_P_THRESHOLD:g} "
                "(NOT BH-FDR adjusted); gray: not nominally significant; "
                "light gray: missing t-stat."
            ),
            output_path=nominal_path,
            annotate=annotate,
        )
        return {"fdr": fdr_path, "nominal": nominal_path}

    fdr_path = output_dir / FDR_HEATMAP_FILENAME
    nominal_path = output_dir / NOMINAL_HEATMAP_FILENAME
    if family_id.startswith(STANDARD_FAC_FAMILY_PREFIX):
        value_matrix, q_matrix, p_matrix = build_standard_fac_20_matrices(frame)
        metric_label = "t-stat"
        diverging = True
        x_label = "Future return horizon"
        y_label = "FAC window"
    else:
        (
            value_matrix,
            q_matrix,
            p_matrix,
            metric_label,
            diverging,
        ) = build_generic_fdr_matrices(frame)
        x_label = "Test position within row"
        y_label = "Sequential row"

    plot_fdr_matrix(
        value_matrix,
        q_matrix,
        family_id=family_id,
        metric_label=metric_label,
        significance_threshold=q_threshold,
        significance_label="BH-FDR significance",
        title_note="BH-FDR significance",
        footer_note=(
            f"Colored cells with black borders: q < {q_threshold:g}; "
            "gray: not FDR-significant."
        ),
        output_path=fdr_path,
        annotate=annotate,
        diverging=diverging,
        x_label=x_label,
        y_label=y_label,
    )
    plot_fdr_matrix(
        value_matrix,
        p_matrix,
        family_id=family_id,
        metric_label=metric_label,
        significance_threshold=NOMINAL_P_THRESHOLD,
        significance_label="raw p-value significance (no multiple-testing adjustment)",
        title_note="raw p-value significance (unadjusted)",
        footer_note=(
            f"Colored cells with black borders: raw p < {NOMINAL_P_THRESHOLD:g} "
            "(NOT BH-FDR adjusted); gray: not nominally significant."
        ),
        output_path=nominal_path,
        annotate=annotate,
        diverging=diverging,
        x_label=x_label,
        y_label=y_label,
    )
    return {"fdr": fdr_path, "nominal": nominal_path}


def run_family(
    family_id: str,
    *,
    output_root: Path,
    dry_run: bool,
    include_pending: bool,
    annotate_heatmap: bool = False,
) -> dict[str, Any]:
    """读取并执行一个 family，返回可写入汇总的 metadata。"""
    config = get_family(family_id)
    status = str(config["status"])
    allowed = status in RUNNABLE_STATUSES or (
        include_pending and status == "pending_user_review"
    )
    if not allowed:
        raise ValueError(
            f"family={family_id} 当前 status={status!r}，默认不可运行。"
            "待审核 family 必须显式加入 --include-pending；blocked/not_required 不能执行。"
        )
    if not config.get("sources"):
        raise ValueError(f"family={family_id} 没有登记可读取的 p-value 来源。")

    frames = [read_source(dict(source)) for source in config["sources"]]
    combined = pd.concat(frames, ignore_index=True, sort=False)
    raw = combined["fdr_input_p_value_raw"]
    numeric, valid, counts = validate_p_values(raw, family_id=family_id)

    combined["p_value"] = numeric
    combined["q_value"] = np.nan
    combined.loc[valid, "q_value"] = benjamini_hochberg(numeric.loc[valid])
    threshold = float(config.get("q_threshold", 0.05))
    combined["is_fdr_significant"] = combined["q_value"].lt(threshold)
    combined["is_nominal_significant"] = combined["p_value"].lt(0.05)
    combined["fdr_family_id"] = family_id
    combined["fdr_family_role"] = str(config["role"])
    combined["fdr_method"] = str(config["method"])
    combined["fdr_q_threshold"] = threshold
    combined["fdr_family_size"] = counts["valid_p_values"]

    metadata: dict[str, Any] = {
        "family_id": family_id,
        "description": config["description"],
        "role": config["role"],
        "status": status,
        "method": config["method"],
        "q_threshold": threshold,
        "family_size": counts["valid_p_values"],
        "significant_q": int(combined["is_fdr_significant"].sum()),
        "nominal_significant_p": int(combined["is_nominal_significant"].sum()),
        "input_audit": counts,
        "sources": config["sources"],
        "notes": config.get("notes", ""),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dry_run": bool(dry_run),
    }

    print(
        f"{family_id}: family_size={counts['valid_p_values']}，"
        f"missing={counts['excluded_missing_p_values']}，"
        f"q<{threshold:g}={metadata['significant_q']}"
    )
    if dry_run:
        return metadata

    output_dir = output_root / family_id
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "fdr_results.csv"
    metadata_path = output_dir / "fdr_metadata.json"
    combined.to_csv(result_path, index=False, encoding="utf-8-sig")
    heatmap_paths = write_fdr_heatmap(
        combined,
        family_id=family_id,
        q_threshold=threshold,
        output_dir=output_dir,
        dry_run=False,
        annotate=annotate_heatmap,
    )
    if heatmap_paths is not None:
        heatmap_metric = (
            "t_stat"
            if "t_stat" in combined.columns
            else "estimate/coef/-log10(p) automatic fallback"
        )
        metadata["heatmap"] = {
            "file": heatmap_paths["fdr"].name,
            "metric": heatmap_metric,
            "significance_column": "q_value",
            "q_threshold": threshold,
            "annotated": bool(annotate_heatmap),
        }
        metadata["heatmap_nominal_p"] = {
            "file": heatmap_paths["nominal"].name,
            "metric": heatmap_metric,
            "significance_column": "p_value",
            "p_threshold": NOMINAL_P_THRESHOLD,
            "note": "未做 BH-FDR 校正，仅供对照，不能替代 q 值作为正式结论。",
            "annotated": bool(annotate_heatmap),
        }

    control_panel_path = None
    if family_id.startswith(FAC_HEATMAP_FAMILY_PREFIX):
        control_panel_path = write_control_variable_panel(
            config, output_dir, annotate=annotate_heatmap
        )
        if control_panel_path is not None:
            metadata["control_variable_panel"] = {
                "file": control_panel_path.name,
                "significance_column": "p_value",
                "p_threshold": NOMINAL_P_THRESHOLD,
                "note": "展示除 FAC 外全部控制变量跨 132 个窗口的系数与 raw p<0.05 参考显著性。",
                "annotated": bool(annotate_heatmap),
            }

    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"  结果：{result_path}")
    if heatmap_paths is not None:
        print(f"  FDR 热力图：{heatmap_paths['fdr']}")
        print(f"  raw p 热力图：{heatmap_paths['nominal']}")
    if control_panel_path is not None:
        print(f"  控制变量小倍图：{control_panel_path}")
    print(f"  元数据：{metadata_path}")
    return metadata


def selected_family_ids(args: argparse.Namespace) -> list[str]:
    """合并显式 family 与 --all-active，并保持稳定顺序、去重。"""
    selected = list(args.family)
    if args.all_active:
        selected.extend(
            family_id
            for family_id, config in sorted(FDR_FAMILIES.items())
            if config.get("status") == "active"
        )
    return list(dict.fromkeys(selected))


def main() -> int:
    """CLI 入口。"""
    args = parse_args()
    if args.list:
        for family_id, status, description in list_families():
            print(f"{family_id}\t{status}\t{description}")
        return 0

    family_ids = selected_family_ids(args)
    if not family_ids:
        raise ValueError("请使用 --family FAMILY_ID、--all-active 或 --list。")

    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root

    run_summaries = []
    for family_id in family_ids:
        run_summaries.append(
            run_family(
                family_id,
                output_root=output_root,
                dry_run=bool(args.dry_run),
                include_pending=bool(args.include_pending),
                annotate_heatmap=bool(args.annotate_heatmap),
            )
        )

    print(f"完成 family 数量：{len(run_summaries)}")

    if bool(args.dry_run):
        return 0

    missing_for_combined = [
        model_key
        for model_key in FAC_HEATMAP_EXPLORATORY_MODEL_KEYS
        if not (
            output_root
            / f"{FAC_HEATMAP_FAMILY_PREFIX}{model_key}"
            / "fdr_results.csv"
        ).exists()
    ]
    if missing_for_combined:
        print(
            "跳过跨探索分组综合显著性汇总：以下 family 尚未生成 fdr_results.csv："
            + ", ".join(missing_for_combined)
        )
    else:
        combined_outputs = write_combined_fac_summary(
            output_root, annotate=bool(args.annotate_heatmap)
        )
        if combined_outputs is not None:
            print("跨探索分组综合显著性汇总（fac_heatmap__combined/）：")
            for key, path in combined_outputs.items():
                print(f"  {key}: {path}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, InvalidPValueError, KeyError, ValueError) as exc:
        print(f"FDR 执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
