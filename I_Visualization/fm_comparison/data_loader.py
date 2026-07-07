"""解析 回归系数显著性_总表.xlsx 的五个 sheet 为整洁 DataFrame。

总表的共同格式：同一 sheet 内多个批次块首尾相接，表头行（首列为"来源批次"）
重复出现。本模块先按表头行切块，再逐 sheet 解析成 tidy 结构。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

import config

# 表头行的识别标记：首列单元格文本
HEADER_MARKER = "来源批次"

# FM 系数单元格格式，如 "-0.07*\n(t=-1.73)"；\s 可匹配中间的换行
_COEF_CELL_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(\*{0,3})\s*\(t=(-?\d+(?:\.\d+)?)\)\s*$"
)
# 模型参数格式：可带市态状态前缀，如 "m3_n6_pairwise1" / "growth_m3_n3_pairwise1"
# 状态前缀（growth/value、highvol/lowvol、hs300up/hs300down、large/small）是
# 市态条件维度，必须保留，否则不同市态的结果会被压成同一格造成重复合并
_PARAM_RE = re.compile(r"^(?:([a-z0-9]+)_)?m(\d+)_n(\d+)", re.IGNORECASE)


def split_header_blocks(raw: pd.DataFrame, marker: str = HEADER_MARKER) -> list[pd.DataFrame]:
    """按重复出现的表头行把 sheet 切成多个块，并把表头提升为列名。"""
    # 找到所有表头行的位置（首列文本等于标记）
    header_idx = [i for i in range(len(raw)) if str(raw.iloc[i, 0]).strip() == marker]
    blocks: list[pd.DataFrame] = []
    for k, start in enumerate(header_idx):
        # 每个块的范围：当前表头行之后，到下一个表头行（或表尾）为止
        end = header_idx[k + 1] if k + 1 < len(header_idx) else len(raw)
        header = raw.iloc[start]
        body = raw.iloc[start + 1 : end].copy()
        # 表头单元格可能是 NaN（如 FM 系数表的空列），统一转成字符串列名
        body.columns = ["" if pd.isna(c) else str(c).strip() for c in header]
        # 丢掉首列为空的行（块间空行）
        body = body[body.iloc[:, 0].notna()].reset_index(drop=True)
        blocks.append(body)
    return blocks


def parse_coef_cell(cell) -> tuple[float, float, int] | None:
    """把 "-0.07*\\n(t=-1.73)" 解析成 (coef, t, 星数)；解析失败返回 None。"""
    # 非字符串（NaN/None/数值）一律视为缺失
    if not isinstance(cell, str):
        if cell is None or (isinstance(cell, float) and math.isnan(cell)):
            return None
        cell = str(cell)
    match = _COEF_CELL_RE.match(cell)
    if match is None:
        return None
    coef, stars, t_stat = match.groups()
    return float(coef), float(t_stat), len(stars)


def parse_param(text: str) -> tuple[str, int, int, str] | None:
    """解析模型参数为 (市态状态, m, n, param_key)；解析失败返回 None。

    例："m3_n6_pairwise1" -> ("", 3, 6, "m3_n6")；
        "growth_m3_n3_pairwise1" -> ("growth", 3, 3, "growth_m3_n3")。
    """
    if not isinstance(text, str):
        return None
    match = _PARAM_RE.match(text)
    if match is None:
        return None
    state = match.group(1) or ""
    m_val, n_val = int(match.group(2)), int(match.group(3))
    key = f"{state}_m{m_val}_n{n_val}" if state else f"m{m_val}_n{n_val}"
    return state, m_val, n_val, key


def batch_run_no(batch: str) -> int:
    """取批次名的尾号（如 ..._004 -> 4），无法解析返回 -1。"""
    if not isinstance(batch, str):
        return -1
    tail = batch.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def keep_latest_batch(df: pd.DataFrame) -> pd.DataFrame:
    """同一模型目录跨批次重复出现时，只保留批次尾号最大（最新）的那一批。"""
    if df.empty:
        return df
    # 按 (尾号, 批次名) 排序后取每个模型的最后一个批次名作为"最新批次"
    tmp = df.assign(_run=df["batch"].map(batch_run_no))
    latest = (
        tmp.sort_values(["_run", "batch"])
        .groupby("model")["batch"]
        .last()
    )
    # 只保留每个模型属于其最新批次的行
    mask = df.apply(lambda row: row["batch"] == latest[row["model"]], axis=1)
    return df[mask].drop(columns=[c for c in ["_run"] if c in df.columns]).reset_index(drop=True)
