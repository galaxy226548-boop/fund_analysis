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
    # 非字符串入参返回 None
    if not isinstance(text, str):
        return None
    # 按正则表达式匹配参数格式
    match = _PARAM_RE.match(text)
    if match is None:
        return None
    # 提取市态状态、m 值和 n 值
    state = match.group(1) or ""
    m_val, n_val = int(match.group(2)), int(match.group(3))
    # 构建参数标识 key
    key = f"{state}_m{m_val}_n{n_val}" if state else f"m{m_val}_n{n_val}"
    return state, m_val, n_val, key


def batch_run_no(batch: str) -> int:
    """取批次名的尾号（如 ..._004 -> 4），无法解析返回 -1。"""
    # 非字符串入参返回 -1
    if not isinstance(batch, str):
        return -1
    # 按最后一个下划线分割，取尾部
    tail = batch.rsplit("_", 1)[-1]
    # 如果尾部是数字则返回整数，否则返回 -1
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


# 覆盖表列名 -> 英文标准名（列名与总表完全一致，注意"平均 R²"中间有空格）
_COVERAGE_RENAME = {
    "来源批次": "batch",
    "模型目录": "model",
    "模型参数": "param",
    "月份数": "n_months",
    "月均基金数": "avg_funds",
    "月份数×月均基金数": "n_obs",
    "平均 R²": "avg_r2",
    "平均调整 R²": "avg_adj_r2",
}

_PS_RENAME = {
    "来源批次": "batch",
    "模型目录": "model",
    "解释变量": "variable",
    "模型参数": "param",
    "long-short": "long_short",
    "t-stat": "t_stat",
    "p-value": "p_value",
}


def _add_param_cols(df: pd.DataFrame) -> pd.DataFrame:
    """按 param 列补 state、m、n、param_key 四列，无法解析的行丢弃。"""
    # 对 param 列逐行解析出 (state, m, n, param_key) 四元组，解析失败的返回 None
    parsed = df["param"].map(parse_param)
    # 丢弃解析失败的行，保持 df 与 parsed 索引对齐
    df = df[parsed.notna()].copy()
    parsed = parsed[parsed.notna()]
    # 分别取出四元组的四个分量，写回四个新列；state 是市态条件列，供 score_all
    # 按 (state, m, n) 分组而非仅 (m, n)，避免不同市态被误合并
    df["state"] = [p[0] for p in parsed]
    df["m"] = [p[1] for p in parsed]
    df["n"] = [p[2] for p in parsed]
    df["param_key"] = [p[3] for p in parsed]
    return df


def load_coverage(xlsx: Path) -> pd.DataFrame:
    """加载"模型比较样本覆盖"sheet：每行一个 (模型目录, m,n) 的覆盖与 R² 指标。"""
    # 按行读原始 sheet（不设表头，交给 split_header_blocks 处理重复表头行）
    raw = pd.read_excel(xlsx, sheet_name="模型比较样本覆盖", header=None)
    # 按表头行切块，多个批次块首尾相接
    blocks = split_header_blocks(raw)
    # 把所有块拼接成一张长表
    df = pd.concat(blocks, ignore_index=True)
    # 只保留识别的列并改英文名，便于下游统一引用
    df = df[[c for c in _COVERAGE_RENAME if c in df.columns]].rename(columns=_COVERAGE_RENAME)
    # 从 param 列解析出 state/m/n/param_key
    df = _add_param_cols(df)
    # 数值列统一转型，脏值转 NaN
    for col in ["n_months", "avg_funds", "n_obs", "avg_r2", "avg_adj_r2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # 0 个月覆盖不是有效覆盖记录，且这类行在 FM 系数表里本就没有对应结果，过滤后不影响下游打分
    df = df[df["n_months"].notna() & (df["n_months"] > 0)]
    return df.reset_index(drop=True)


def load_fm_coef(xlsx: Path) -> pd.DataFrame:
    """加载"FM系数整理"sheet：宽表（每列一个模型）转长表，并解析系数单元格。"""
    # 按行读原始 sheet，不设表头
    raw = pd.read_excel(xlsx, sheet_name="FM系数整理", header=None)
    records: list[dict] = []
    # 按表头行切块后逐块处理（宽表转长表）
    for block in split_header_blocks(raw):
        # 模型列的表头格式为 "fm_baseline_top33\n变量：FAC_rank_vol"
        model_cols = [c for c in block.columns if "\n变量：" in str(c)]
        # 逐行逐模型列展开：每个 (行, 模型列) 组合是一条长表记录
        for _, row in block.iterrows():
            for col in model_cols:
                # 解析单元格里的系数、t 值、星号，空单元格返回 None 跳过
                parsed = parse_coef_cell(row[col])
                if parsed is None:
                    continue  # 空格/NaN：该模型在此参数组合下无结果
                # 列名拆出模型名与变量名
                model, variable = str(col).split("\n变量：", 1)
                coef, t_stat, stars = parsed
                records.append({
                    "batch": row["来源批次"],
                    "model": model.strip(),
                    "variable": variable.strip(),
                    "param": row["模型参数"],
                    "coef": coef,
                    "t_stat": t_stat,
                    "stars": stars,
                })
    # 记录列表转成 DataFrame
    df = pd.DataFrame(records)
    # 补 state/m/n/param_key 四列后返回
    return _add_param_cols(df).reset_index(drop=True)


def load_ps(xlsx: Path) -> pd.DataFrame:
    """加载"PS_long_short_pvalue"sheet：多空收益、t 与 p 值。"""
    # 按行读原始 sheet，不设表头
    raw = pd.read_excel(xlsx, sheet_name="PS_long_short_pvalue", header=None)
    # 按表头行切块，多个批次块首尾相接
    blocks = split_header_blocks(raw)
    # 拼接所有块成长表
    df = pd.concat(blocks, ignore_index=True)
    # 只保留识别的列并改英文名
    df = df[[c for c in _PS_RENAME if c in df.columns]].rename(columns=_PS_RENAME)
    # 从 param 列解析出 state/m/n/param_key
    df = _add_param_cols(df)
    # 数值列统一转型，脏值转 NaN
    for col in ["long_short", "t_stat", "p_value"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _md_table_rows(text) -> list[list[str]]:
    """从单元格内嵌的 markdown 表格提取数据行（跳过表头与分隔行）。"""
    # 非字符串或含"未发现"字样：视为没有风险记录
    if not isinstance(text, str) or "未发现" in text:
        return []
    rows: list[list[str]] = []
    # 按行扫描单元格文本，找出 markdown 表格的数据行
    for line in text.splitlines():
        line = line.strip()
        # 只处理以竖线开头的表格行
        if not line.startswith("|"):
            continue
        # 去掉首尾竖线后按竖线切分单元格，并去除两侧空白
        cells = [c.strip() for c in line.strip("|").split("|")]
        # 跳过表头行（含 variable 字样）与分隔行（全为 --- ）
        if not cells or cells[0].startswith("variable") or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def parse_corr_cell(text) -> list[tuple[str, str]]:
    """解析相关性风险单元格，返回原始 (var_1, var_2) 行列表（含重复标记）。"""
    # 取 markdown 表格前两列组成 (var_1, var_2) 元组，逐行保留（不去重）
    return [(r[0], r[1]) for r in _md_table_rows(text) if len(r) >= 2]


def parse_vif_cell(text) -> list[str]:
    """解析 VIF 风险单元格，返回风险变量名列表（含重复标记）。"""
    # 取 markdown 表格首列作为风险变量名，逐行保留（不去重）
    return [r[0] for r in _md_table_rows(text)]


def _corr_diag_from_blocks(blocks: list[pd.DataFrame]) -> pd.DataFrame:
    """把诊断 sheet 的块聚合成整洁表：按变量对去重，统计标记次数与核心变量涉险。"""
    records: list[dict] = []
    # 核心变量前缀（如 "FAC"），用于标记风险对/变量是否涉及核心变量
    core = config.CORE_VARIABLE_PREFIX
    # 逐块逐行处理，每行对应一个 (批次, 模型目录) 的诊断记录
    for block in blocks:
        for _, row in block.iterrows():
            batch, model = row["来源批次"], row["模型目录"]
            # 相关性风险：按 (var_1, var_2) 排序后去重，重复次数即持续性的分子
            pair_counts: dict[tuple[str, str], int] = {}
            for pair in parse_corr_cell(row.get("相关性风险变量对")):
                # 变量对排序后作为字典 key，保证 (a,b) 与 (b,a) 视为同一对
                key = tuple(sorted(pair))
                pair_counts[key] = pair_counts.get(key, 0) + 1
            for (v1, v2), cnt in pair_counts.items():
                records.append({
                    "batch": batch, "model": model, "kind": "corr",
                    "var_1": v1, "var_2": v2, "n_flagged": cnt,
                    "involves_core": v1.startswith(core) or v2.startswith(core),
                })
            # VIF 风险：按变量名去重
            vif_counts: dict[str, int] = {}
            for var in parse_vif_cell(row.get("VIF风险变量")):
                vif_counts[var] = vif_counts.get(var, 0) + 1
            for var, cnt in vif_counts.items():
                records.append({
                    "batch": batch, "model": model, "kind": "vif",
                    "var_1": var, "var_2": None, "n_flagged": cnt,
                    "involves_core": var.startswith(core),
                })
    # 固定列顺序，即便 records 为空也返回带正确列名的空表
    columns = ["batch", "model", "kind", "var_1", "var_2", "n_flagged", "involves_core"]
    return pd.DataFrame(records, columns=columns)


def load_corr_diag(xlsx: Path) -> pd.DataFrame:
    """加载"变量相关性诊断"sheet 为整洁风险表。"""
    # 按行读原始 sheet，不设表头
    raw = pd.read_excel(xlsx, sheet_name="变量相关性诊断", header=None)
    # 按表头行切块后聚合成整洁风险表
    return _corr_diag_from_blocks(split_header_blocks(raw))


def load_all(xlsx: Path) -> dict[str, pd.DataFrame]:
    """一次加载四张表并做最新批次去重，返回 {"coverage","fm","ps","diag"}。"""
    # 依次加载四张表，每张表都按模型目录做最新批次去重后返回
    return {
        "coverage": keep_latest_batch(load_coverage(xlsx)),
        "fm": keep_latest_batch(load_fm_coef(xlsx)),
        "ps": keep_latest_batch(load_ps(xlsx)),
        "diag": keep_latest_batch(load_corr_diag(xlsx)),
    }
