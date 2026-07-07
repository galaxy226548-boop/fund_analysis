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


def _sign(x: float) -> int:
    """符号函数：正 1、负 -1、零 0。"""
    return (x > 0) - (x < 0)


def neighbor_robustness_score(m: int, n: int, coef: float, family_fm: pd.DataFrame, cfg: dict) -> tuple[float, dict]:
    """邻格稳健性：邻格中"与本格同号且 |t|>=阈值"的比例 × 满分。

    family_fm 为同一模型+变量的 FM 子表（含 m, n, coef, t_stat）；
    邻格按族内出现过的 m/n 取值构造轴，缺数据的邻格不进分母。
    """
    # 从配置中取出满分与显著性阈值
    full, t_min = cfg["neighbor_full"], cfg["neighbor_t_min"]
    formula = f"邻格中(同号且|t|>={t_min})的比例 × {full:g}分；邻格=沿一条轴走一步"
    # 轴由族内全部 (m, n) 组合决定，新参数进来后自动扩展
    m_axis, n_axis = build_axes(zip(family_fm["m"], family_fm["n"]))
    wanted = set(neighbor_cells(m, n, m_axis, n_axis))
    # 只统计族里真实存在数据的邻格
    available = family_fm[[(mm, nn) in wanted for mm, nn in zip(family_fm["m"], family_fm["n"])]]
    if available.empty:
        # 无邻格数据时无法计算比例，直接给 0 分并在明细里说明原因
        return 0.0, {"名称": "邻格稳健性", "公式": formula, "代入": "无邻格数据", "得分": 0.0}
    # 命中条件：邻格系数与本格同号，且 |t| 达到显著阈值
    hits = available[
        (available["coef"].map(_sign) == _sign(float(coef)))
        & (available["t_stat"].abs() >= t_min)
    ]
    # 比例 × 满分得到最终得分
    score = full * len(hits) / len(available)
    # 拼接每个邻格的 t 值，便于明细复算
    cells = ", ".join(f"m{r.m}_n{r.n}(t={r.t_stat:.2f})" for r in available.itertuples())
    detail = {
        "名称": "邻格稳健性", "公式": formula,
        "代入": f"{len(hits)}/{len(available)} 命中；邻格: {cells}",
        "得分": score,
    }
    return score, detail


def ps_score(p_value: float | None, long_short: float | None, fm_coef: float | None, cfg: dict) -> tuple[float, dict]:
    """多空显著性：p 分档基础分 × 方向冲突折扣 × 经济显著性折扣（可叠乘）。"""
    # 从配置中取出满分与分档规则
    full, bands = cfg["ps_full"], cfg["ps_p_bands"]
    formula = (
        "; ".join(f"p<{thr}→{frac * full:g}分" for thr, frac in bands)
        + f"; 方向冲突×{cfg['ps_direction_conflict_mult']}"
        + f"; |月均多空|<{cfg['ps_econ_threshold']:.1%}×{cfg['ps_econ_mult']}"
    )
    if _is_missing(p_value):
        # 无 PS 记录时直接得 0 分
        return 0.0, {"名称": "多空显著性", "公式": formula, "代入": "无PS记录", "得分": 0.0}
    # p 值越小越好，按分档取基础分
    base = _band_score(float(p_value), bands, full, higher_is_better=False)
    mult, notes = 1.0, [f"p={float(p_value):.4f}→基础{base:g}分"]
    # 方向冲突：FM 系数与多空收益符号相反（都非零才判断）
    if not _is_missing(long_short) and not _is_missing(fm_coef) and float(long_short) * float(fm_coef) < 0:
        mult *= cfg["ps_direction_conflict_mult"]
        notes.append(f"方向冲突×{cfg['ps_direction_conflict_mult']}")
    # 经济显著性：月均多空收益太小，即使显著也缺乏选基价值
    if not _is_missing(long_short) and abs(float(long_short)) < cfg["ps_econ_threshold"]:
        mult *= cfg["ps_econ_mult"]
        notes.append(f"|多空|={abs(float(long_short)):.2%}<{cfg['ps_econ_threshold']:.1%}×{cfg['ps_econ_mult']}")
    # 两个折扣可叠乘，最终得分 = 基础分 × 累计折扣
    score = base * mult
    return score, {"名称": "多空显著性", "公式": formula, "代入": "; ".join(notes), "得分": score}


def percentile_of(value: float, pool: pd.Series) -> float:
    """value 在 pool 中的分位（0~1）：小于者计 1、并列计 0.5，除以总数。"""
    # 先剔除缺失值，避免污染分母
    pool = pool.dropna()
    if pool.empty or _is_missing(value):
        # 池为空或目标值缺失时无法计算分位，返回 0
        return 0.0
    # 小于 value 的计 1、等于 value 的计 0.5（并列取中点），再除以样本总数
    return float(((pool < value).sum() + 0.5 * (pool == value).sum()) / len(pool))


def r2_quality_score(r2: float | None, pool: pd.Series, family_r2: float | None, family_pool: pd.Series, cfg: dict) -> tuple[float, dict]:
    """回归质量：个体 R² 全体分位 × 12 + 族平均 R² 跨族分位 × 8（梯度化，无跳分）。"""
    # 从配置中取出个体与族两部分的满分
    ind_full, fam_full = cfg["r2_individual_full"], cfg["r2_family_full"]
    # 分别计算个体 R² 在全体池中的分位、族均 R² 在跨族池中的分位
    ind_pct = percentile_of(r2, pool)
    fam_pct = percentile_of(family_r2, family_pool)
    # 两部分按各自满分加权求和
    score = ind_pct * ind_full + fam_pct * fam_full
    detail = {
        "名称": "回归质量",
        "公式": f"个体R²分位×{ind_full:g} + 族均R²分位×{fam_full:g}",
        "代入": f"个体R²={r2}(分位{ind_pct:.2f}), 族均R²={family_r2}(分位{fam_pct:.2f})",
        "得分": score,
    }
    return score, detail


def collinearity_penalty(diag_family: pd.DataFrame, n_params: int, cfg: dict) -> tuple[float, dict]:
    """共线性扣分（族层面）：唯一风险对/变量的基础扣分 × 持续性系数，分类封顶。

    持续性系数 = 被标记次数 / 该族参数组合数，上限 1（同一对在多个 m,n 里反复
    出现说明风险稳定，扣满；只出现一两次则按比例减轻）。
    """
    notes: list[str] = []
    # corr 类与 vif 类分别累加，最后各自独立封顶
    corr_sum, vif_sum = 0.0, 0.0
    for row in diag_family.itertuples():
        # 防御除零；持续性封顶 1
        persistence = min(1.0, row.n_flagged / n_params) if n_params > 0 else 1.0
        if row.kind == "corr":
            # 含核心变量的风险对用加重档，否则用普通档
            base = cfg["corr_pair_core_penalty"] if row.involves_core else cfg["corr_pair_penalty"]
            corr_sum += base * persistence
            notes.append(f"corr {row.var_1}×{row.var_2}: {base:g}×{persistence:.2f}")
        elif row.kind == "vif":
            # 核心变量自身 VIF 超标用加重档，否则用普通档
            base = cfg["vif_core_penalty"] if row.involves_core else cfg["vif_penalty"]
            vif_sum += base * persistence
            notes.append(f"vif {row.var_1}: {base:g}×{persistence:.2f}")
    # 分类封顶：扣分为负数，用 max 取"不低于上限"
    corr_total = max(corr_sum, cfg["corr_cap"])
    vif_total = max(vif_sum, cfg["vif_cap"])
    # 两类扣分相加得到族层面总扣分
    total = corr_total + vif_total
    formula = (
        f"corr: 每唯一对{cfg['corr_pair_penalty']:g}(含核心{cfg['corr_pair_core_penalty']:g})×持续性, "
        f"上限{cfg['corr_cap']:g} | vif: 每变量{cfg['vif_penalty']:g}(核心{cfg['vif_core_penalty']:g})×持续性, "
        f"上限{cfg['vif_cap']:g}"
    )
    detail = {
        "名称": "共线性扣分", "公式": formula,
        "代入": "; ".join(notes) if notes else "无风险记录",
        "得分": total,
    }
    return total, detail


def score_all(tables: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame:
    """给全部候选 (模型目录 × m,n) 打分，返回带六项明细的汇总表。"""
    coverage, fm, ps, diag = tables["coverage"], tables["fm"], tables["ps"], tables["diag"]
    # 候选 = FM 系数表与覆盖表能对上的 (model, param)；用完整参数串做键，
    # 避免不同市态状态（growth/value 等前缀）被压成同一格造成笛卡尔积
    base = fm.merge(
        coverage[["model", "param", "n_months", "avg_funds", "n_obs", "avg_r2"]],
        on=["model", "param"], how="inner",
    ).merge(
        ps[["model", "param", "long_short", "p_value"]],
        on=["model", "param"], how="left",
    )
    # R² 分位的两个池：全体候选池 + 各族平均池
    pool_r2 = base["avg_r2"]
    family_avg = base.groupby("model")["avg_r2"].mean()
    family_pool = pd.Series(family_avg.values)

    records: list[dict] = []
    for row in base.itertuples():
        # 族内 FM 子表（邻格用）：同模型+同变量+同市态状态，跨市态不算邻格
        family_fm = fm[
            (fm["model"] == row.model)
            & (fm["variable"] == row.variable)
            & (fm["state"] == row.state)
        ]
        # 族参数组合数（持续性分母）：用完整参数串计数，含全部市态状态
        n_params = coverage[coverage["model"] == row.model]["param"].nunique()
        diag_family = diag[diag["model"] == row.model]
        # 六个组成部分逐项计算，明细全部保留
        fm_s, d1 = fm_significance_score(row.t_stat, cfg)
        nb_s, d2 = neighbor_robustness_score(row.m, row.n, row.coef, family_fm, cfg)
        ps_s, d3 = ps_score(row.p_value, row.long_short, row.coef, cfg)
        r2_s, d4 = r2_quality_score(row.avg_r2, pool_r2, family_avg[row.model], family_pool, cfg)
        sp, d5 = sample_penalty(row.n_months, row.n_obs, cfg)
        cp, d6 = collinearity_penalty(diag_family, n_params, cfg)
        records.append({
            "batch": row.batch, "model": row.model, "layer": sample_layer(row.model),
            "variable": row.variable, "state": row.state,
            "param_key": row.param_key, "m": row.m, "n": row.n,
            "coef": row.coef, "t_stat": row.t_stat, "stars": row.stars,
            "long_short": row.long_short, "p_value": row.p_value,
            "n_months": row.n_months, "avg_funds": row.avg_funds,
            "n_obs": row.n_obs, "avg_r2": row.avg_r2,
            "fm_score": fm_s, "neighbor_score": nb_s, "ps_sig_score": ps_s,
            "r2_score": r2_s, "sample_pen": sp, "collin_pen": cp,
            "total": fm_s + nb_s + ps_s + r2_s + sp + cp,
            "明细": [d1, d2, d3, d4, d5, d6],
        })
    return pd.DataFrame(records)


def attach_badges(scores: pd.DataFrame, baselines: dict, cfg: dict) -> pd.DataFrame:
    """按样本层配对基准，给胜过基准的候选打徽章。

    规则（spec 第 4 节）：总分 > 基准 -> "可能可替代基准"；
    领先 >= replace_margin -> "优先关注"；other 层无基准，不打徽章。
    """
    scores = scores.copy()
    # 每层基准的总分：基准候选缺失时该层不打徽章
    layer_base_total: dict[str, float] = {}
    is_baseline = pd.Series(False, index=scores.index)
    for layer, spec in baselines.items():
        mask = (scores["model"] == spec["model"]) & (scores["param_key"] == spec["param_key"])
        is_baseline |= mask
        if mask.any():
            layer_base_total[layer] = float(scores.loc[mask, "total"].iloc[0])
    scores["is_baseline"] = is_baseline
    scores["baseline_total"] = scores["layer"].map(layer_base_total)
    scores["vs_baseline"] = scores["total"] - scores["baseline_total"]

    def _badge(row) -> str:
        # 基准自己、无基准层、分数未超过基准 -> 无徽章
        if row["is_baseline"] or pd.isna(row["baseline_total"]) or row["total"] <= row["baseline_total"]:
            return ""
        if row["vs_baseline"] >= cfg["replace_margin"]:
            return "优先关注"
        return "可能可替代基准"

    scores["badge"] = scores.apply(_badge, axis=1)
    return scores
