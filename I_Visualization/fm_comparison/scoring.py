"""打分引擎：四维打分 + 扣分项 + 擂台徽章。

全部为纯函数：输入 tidy DataFrame / 标量与 cfg 字典，输出 (得分, 明细字典)。
明细字典统一结构 {"名称", "公式", "代入", "得分"}，页面的"分数计算明细"直接渲染，
让每个分数都能被人工复算。
"""

from __future__ import annotations

import math
from typing import Iterable

import pandas as pd


def _is_missing(value) -> bool:
    """判断标量缺失（None 或 NaN）。"""
    # 检查是否为 None
    if value is None:
        return True
    # 检查是否为 NaN（仅对 float 类型）
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def sample_layer(model: str) -> str:
    """按模型目录名的下划线分词识别样本层：up / bottom33 / other。"""
    # 将模型字符串按下划线分词
    tokens = str(model).split("_")
    # 首先检查是否包含 "bottom33"
    if "bottom33" in tokens:
        return "bottom33"
    # 其次检查是否包含 "up"
    if "up" in tokens:
        return "up"
    # 都不含则返回 "other"
    return "other"


def build_axes(pairs: Iterable[tuple[int, int]]) -> tuple[list[int], list[int]]:
    """从 (m, n) 集合构造排序去重的 m 轴与 n 轴。"""
    # 将输入转换为列表以支持多次遍历
    pairs = list(pairs)
    # 提取所有不同的 m 值并排序
    m_axis = sorted({p[0] for p in pairs})
    # 提取所有不同的 n 值并排序
    n_axis = sorted({p[1] for p in pairs})
    return m_axis, n_axis


def neighbor_cells(m: int, n: int, m_axis: list[int], n_axis: list[int]) -> list[tuple[int, int]]:
    """邻格 = 参数网格上恰好沿一条轴走一步的组合（曼哈顿距离 1，对角不算）。"""
    neighbors: list[tuple[int, int]] = []
    # 找到当前 (m, n) 在两个轴上的索引位置
    mi, ni = m_axis.index(m), n_axis.index(n)
    # 沿 m 轴走一步（n 不动）：检查左右邻近的 m 值
    for step in (-1, 1):
        if 0 <= mi + step < len(m_axis):
            neighbors.append((m_axis[mi + step], n))
    # 沿 n 轴走一步（m 不动）：检查上下邻近的 n 值
    for step in (-1, 1):
        if 0 <= ni + step < len(n_axis):
            neighbors.append((m, n_axis[ni + step]))
    return neighbors


def _band_score(value: float, bands: list[tuple[float, float]], full: float, higher_is_better: bool) -> float:
    """分档打分：bands 为 (阈值, 满分占比) 列表；FM 用 |t| 越大越好，PS 用 p 越小越好。"""
    # 遍历分档列表，从高到低匹配第一个满足条件的档位
    for threshold, fraction in bands:
        # 根据方向判断是否命中此档：higher_is_better 为真时使用 >=，否则使用 <
        hit = value >= threshold if higher_is_better else value < threshold
        if hit:
            return fraction * full
    # 都不符合则得 0 分
    return 0.0


def fm_significance_score(t_stat: float | None, cfg: dict) -> tuple[float, dict]:
    """FM 显著性：按 |t| 分档乘满分；t 缺失得 0。"""
    # 从配置中获取满分与分档规则
    full, bands = cfg["fm_full"], cfg["fm_t_bands"]
    # 构造公式说明文本
    formula = "; ".join(f"|t|>={thr}→{frac * full:g}分" for thr, frac in bands) + "; 其他→0"
    # 如果 t 值缺失，返回 0 分
    if _is_missing(t_stat):
        return 0.0, {"名称": "FM显著性", "公式": formula, "代入": "t 值缺失", "得分": 0.0}
    # 计算 t 值的绝对值对应的分数
    score = _band_score(abs(float(t_stat)), bands, full, higher_is_better=True)
    # 构造明细字典
    detail = {"名称": "FM显著性", "公式": formula, "代入": f"|t|={abs(float(t_stat)):.2f}", "得分": score}
    return score, detail


def _tier_penalty(value: float, tiers: list[tuple[float, float]]) -> float:
    """阶梯扣分：tiers 按阈值升序，命中第一个 value < 阈值 的档（最严档），否则 0。"""
    # 遍历阶梯列表，找到第一个命中的档位（最严档）
    for threshold, penalty in tiers:
        if value < threshold:
            return penalty
    # 都不符合则无扣分
    return 0.0


def sample_penalty(n_months: float, n_obs: float, cfg: dict) -> tuple[float, dict]:
    """样本量扣分：月份数与（月份数×月均基金数）分别按阶梯取最严档后相加。"""
    # 月份数的阶梯扣分：未缺失则计算，缺失则为 0
    months_pen = 0.0 if _is_missing(n_months) else _tier_penalty(float(n_months), cfg["months_penalties"])
    # 样本数的阶梯扣分：未缺失则计算，缺失则为 0
    obs_pen = 0.0 if _is_missing(n_obs) else _tier_penalty(float(n_obs), cfg["obs_penalties"])
    # 两类扣分相加
    total = months_pen + obs_pen
    # 构造公式说明文本
    formula = (
        "月份数: " + "; ".join(f"<{t}→{p:g}" for t, p in cfg["months_penalties"])
        + " | 样本数: " + "; ".join(f"<{t}→{p:g}" for t, p in cfg["obs_penalties"])
    )
    # 构造明细字典
    detail = {
        "名称": "样本量扣分", "公式": formula,
        "代入": f"月份数={n_months}, 样本数={n_obs} → {months_pen:g} + {obs_pen:g}",
        "得分": total,
    }
    return total, detail
