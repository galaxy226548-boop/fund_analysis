"""基金季度五分组 portfolio sorting 检验工具。

这个脚本提供一个通用函数 ``portfolio_sorting_backtest``，用于在基金面板数据中
按照某个调仓日已知变量做分组，并检验未来收益是否在不同组合之间有差异。

典型使用场景：
1. 输入每只基金每个月末的一行观测；
2. 每季度末用当时已经可得的因子值对基金分成五组；
3. 计算未来 6 个月收益等指标在各组中的均值；
4. 检验 High-Low 组合，也就是“经济含义更好的一组 - 经济含义更差的一组”。

注意：本脚本不会回看未来信息。普通 sort_col 需要已经在输入表中存在；如果 registry
配置了 ``portfolio_sorting_factors`` 形式的交互项，本脚本会在运行时只用当期已知变量
构造对应排序列。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/private/tmp")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


WeightMethod = Literal["equal", "value"]
TStatMethod = Literal["simple", "newey_west"]
Frequency = Literal["month", "monthly", "quarter", "quarterly", "year", "yearly"]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"

STANDARDIZE_NONE = "none"
STANDARDIZE_CROSS_SECTION = "cross_section"
CURRENT_FACTOR_PLACEHOLDER = "FAC"
MATCHED_RANK_MEAN_PLACEHOLDER = "RANK_MEAN"
STANDARDIZE_ALIASES = {
    "none": STANDARDIZE_NONE,
    "": STANDARDIZE_NONE,
    "no": STANDARDIZE_NONE,
    "不标准化": STANDARDIZE_NONE,
    "不標準化": STANDARDIZE_NONE,
    "cross_section": STANDARDIZE_CROSS_SECTION,
    "cross-section": STANDARDIZE_CROSS_SECTION,
    "cross_sectional": STANDARDIZE_CROSS_SECTION,
    "by_month": STANDARDIZE_CROSS_SECTION,
    "section": STANDARDIZE_CROSS_SECTION,
    "按回归截面标准化": STANDARDIZE_CROSS_SECTION,
    "按回歸截面標準化": STANDARDIZE_CROSS_SECTION,
}


@dataclass(frozen=True)
class PortfolioSortingResult:
    """portfolio sorting 的标准输出容器。

    Attributes
    ----------
    period_returns:
        每个调仓日、每个未来收益列、每个组合的当期组合收益。
    summary_table:
        每个未来收益列下，各组合以及 High-Low 的均值、t 值和有效期数。
    diagnostics:
        每个调仓日的样本数量、缺失值数量和各组样本数，便于检查分组质量。
    """

    period_returns: pd.DataFrame
    summary_table: pd.DataFrame
    diagnostics: pd.DataFrame


def _check_required_columns(
    df: pd.DataFrame,
    required_cols: list[str],
) -> None:
    """检查输入表是否包含所有必要列。

    Parameters
    ----------
    df:
        用户传入的面板数据。
    required_cols:
        本次回测必须用到的列名清单。

    Raises
    ------
    ValueError
        如果输入表缺少任何必要列，就一次性报出所有缺失列。
    """

    # 把缺失列集中列出来，这样用户不用反复运行脚本才能逐个发现问题。
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"输入数据缺少必要列：{missing_cols}")


def _normalize_ret_cols(ret_cols: str | list[str] | tuple[str, ...]) -> list[str]:
    """把 ret_cols 统一整理成列表。

    Parameters
    ----------
    ret_cols:
        一个未来收益列名，或多个未来收益列名。

    Returns
    -------
    list[str]
        整理后的未来收益列名列表。
    """

    # 单个字符串是最常见的简写形式，这里转成列表方便后面统一循环。
    if isinstance(ret_cols, str):
        return [ret_cols]

    # 如果用户传入 list 或 tuple，则复制成新的 list，避免后续意外修改原对象。
    normalized = list(ret_cols)
    if not normalized:
        raise ValueError("ret_cols 不能为空；至少需要提供一个未来表现列。")
    return normalized


def _filter_rebalance_dates(
    df: pd.DataFrame,
    date_col: str,
    frequency: Frequency,
) -> pd.DataFrame:
    """按调仓频率保留对应日期。

    Parameters
    ----------
    df:
        已经包含 datetime 日期列的面板数据。
    date_col:
        日期列名。
    frequency:
        调仓频率。支持 month/monthly、quarter/quarterly、year/yearly。

    Returns
    -------
    pd.DataFrame
        只保留调仓日期后的数据副本。
    """

    freq = str(frequency).lower()

    # 月度调仓不需要额外筛选，保留所有月份。
    if freq in {"month", "monthly"}:
        return df.copy()

    # 季度调仓只保留 3、6、9、12 月的月末观测。这里不强制检查“是否真的是月末”，
    # 因为有些数据供应商会把月末日期存成该月最后一个交易日。
    if freq in {"quarter", "quarterly"}:
        return df.loc[df[date_col].dt.month.isin([3, 6, 9, 12])].copy()

    # 年度调仓只保留 12 月观测。
    if freq in {"year", "yearly"}:
        return df.loc[df[date_col].dt.month == 12].copy()

    raise ValueError(
        "frequency 只支持 'month'/'monthly'、'quarter'/'quarterly'、"
        f"'year'/'yearly'，当前传入：{frequency!r}"
    )


def _assign_quantile_groups(
    values: pd.Series,
    n_groups: int,
) -> pd.Series:
    """对单个调仓日的基金做分位数组编号。

    Parameters
    ----------
    values:
        单个调仓日内的 sort_col 序列，必须已经去掉缺失值。
    n_groups:
        分组数量，例如五分组就是 5。

    Returns
    -------
    pd.Series
        与 values 索引对齐的原始分组编号，1 表示最低 sort_col 组，n_groups 表示
        最高 sort_col 组。
    """

    if len(values) < n_groups:
        # 样本数比组数还少时，qcut 没有稳定含义，直接全部记为缺失分组。
        return pd.Series(np.nan, index=values.index, dtype=float)

    try:
        # 优先直接按 sort_col 做 qcut，这样分组边界更符合“按因子值切分”的直觉。
        groups = pd.qcut(values, q=n_groups, labels=False) + 1
    except ValueError:
        # 当 sort_col 有大量重复值时，qcut 可能因为分位点重复而失败。
        # 这时用 rank(method="first") 打破并列值，让每只基金仍能被稳定分到一组。
        ranks = values.rank(method="first")
        groups = pd.qcut(ranks, q=n_groups, labels=False) + 1

    return groups.astype(float)


def _format_group_label(economic_group: int, n_groups: int) -> str:
    """把经济含义分组编号转成易读标签。

    economic_group 永远按“经济含义”排序：1 是 Low，n_groups 是 High。
    """

    if economic_group == 1:
        return "Low"
    if economic_group == n_groups:
        return "High"
    return f"Q{economic_group}"


def _weighted_average(
    values: pd.Series,
    weights: pd.Series | None,
    weight_method: WeightMethod,
) -> float:
    """计算单个组合在单个调仓日的收益。

    Parameters
    ----------
    values:
        当前组合内的未来收益序列，已经去掉缺失值。
    weights:
        当前组合内的权重序列；等权组合可以传入 None。
    weight_method:
        "equal" 表示等权平均；"value" 表示按 weight_col 做规模加权。

    Returns
    -------
    float
        组合收益。如果样本为空或权重不可用，返回 NaN。
    """

    if values.empty:
        return np.nan

    if weight_method == "equal":
        return float(values.mean())

    if weights is None or weights.empty:
        return np.nan

    # 规模加权时，理论上前面已经剔除了缺失或非正权重。这里仍做一次保护，
    # 防止未来调用逻辑变化时把异常权重带进来。
    total_weight = float(weights.sum())
    if not np.isfinite(total_weight) or total_weight <= 0:
        return np.nan
    return float(np.average(values.to_numpy(dtype=float), weights=weights.to_numpy(dtype=float)))


def _simple_tstat(values: pd.Series) -> float:
    """计算时间序列均值的普通 t 值。

    这里检验的是组合收益时间序列的均值是否显著不为 0。
    """

    y = values.dropna().to_numpy(dtype=float)
    n_obs = len(y)
    if n_obs <= 1:
        return np.nan

    sample_std = float(np.std(y, ddof=1))
    if sample_std == 0 or not np.isfinite(sample_std):
        return np.nan
    return float(np.mean(y) / (sample_std / np.sqrt(n_obs)))


def _newey_west_tstat(values: pd.Series, nw_lags: int | None = None) -> float:
    """计算时间序列均值的 Newey-West t 值。

    对一条组合收益时间序列 y，本质上是在做常数项回归 ``y ~ 1``。
    常数项就是 y 的均值；常数项 t 值就是“均值 / Newey-West 标准误”。

    Parameters
    ----------
    values:
        待检验的时间序列。
    nw_lags:
        Newey-West 滞后阶数。如果为 None，则使用常见经验规则
        ``floor(4 * (T / 100) ** (2 / 9))``。
    """

    y = values.dropna().to_numpy(dtype=float)
    n_obs = len(y)
    if n_obs <= 1:
        return np.nan

    if nw_lags is None:
        # 这个经验规则常用于 HAC 标准误；样本很短时至少给 0 阶，也就是不加自相关项。
        lag = int(np.floor(4 * (n_obs / 100) ** (2 / 9)))
    else:
        lag = int(nw_lags)

    if lag < 0:
        raise ValueError("nw_lags 不能为负数。")
    lag = min(lag, n_obs - 1)

    centered = y - np.mean(y)

    # gamma_0 是残差序列的 0 阶自协方差；除以 n_obs 是 HAC 估计中的常见写法。
    long_run_var = float(np.dot(centered, centered) / n_obs)

    # 逐阶加入带 Bartlett 权重的自协方差。滞后越远，权重越低。
    for lag_i in range(1, lag + 1):
        weight = 1.0 - lag_i / (lag + 1.0)
        gamma = float(np.dot(centered[lag_i:], centered[:-lag_i]) / n_obs)
        long_run_var += 2.0 * weight * gamma

    # 均值的方差等于长期方差除以样本期数。
    mean_var = max(long_run_var, 0.0) / n_obs
    if mean_var <= 0 or not np.isfinite(mean_var):
        return np.nan

    return float(np.mean(y) / np.sqrt(mean_var))


def _mean_tstat(
    values: pd.Series,
    tstat_method: TStatMethod,
    nw_lags: int | None,
) -> float:
    """根据用户指定方法计算均值 t 值。"""

    if tstat_method == "simple":
        return _simple_tstat(values)
    if tstat_method == "newey_west":
        return _newey_west_tstat(values, nw_lags=nw_lags)
    raise ValueError("tstat_method 只支持 'simple' 或 'newey_west'。")


def _tstat_pvalue(
    values: pd.Series,
    tstat_method: TStatMethod,
    nw_lags: int | None,
) -> tuple[float, float]:
    """同时计算均值 t 值和双侧 p-value。

    Parameters
    ----------
    values:
        需要检验均值是否为 0 的时间序列。
    tstat_method:
        t 值计算方法，和 ``portfolio_sorting_backtest`` 保持一致。
    nw_lags:
        Newey-West 滞后阶数。

    Returns
    -------
    tuple[float, float]
        第一个元素是 t 值，第二个元素是双侧 p-value。p-value 使用 t 分布近似，
        自由度为有效期数减 1。
    """

    clean_values = values.dropna()
    t_stat = _mean_tstat(clean_values, tstat_method=tstat_method, nw_lags=nw_lags)
    dof = int(clean_values.shape[0] - 1)
    if dof <= 0 or not np.isfinite(t_stat):
        return t_stat, np.nan

    # 双侧 p-value：t 值越极端，p-value 越小。这里用 scipy 的 t 分布 CDF。
    p_value = float(2.0 * stats.t.sf(abs(t_stat), df=dof))
    return t_stat, p_value


def _validate_inputs(
    df: pd.DataFrame,
    id_col: str,
    date_col: str,
    sort_col: str,
    ret_cols: list[str],
    n_groups: int,
    weight_method: WeightMethod,
    weight_col: str | None,
    min_group_size: int,
    tstat_method: TStatMethod,
    nw_lags: int | None,
) -> None:
    """集中做输入检查，让主函数逻辑更容易读。"""

    if not isinstance(df, pd.DataFrame):
        raise TypeError("df 必须是 pandas DataFrame。")
    if df.empty:
        raise ValueError("df 为空，无法做 portfolio sorting。")
    if n_groups < 2:
        raise ValueError("n_groups 至少需要为 2。")
    if min_group_size < 1:
        raise ValueError("min_group_size 至少需要为 1。")
    if weight_method not in {"equal", "value"}:
        raise ValueError("weight_method 只支持 'equal' 或 'value'。")
    if tstat_method not in {"simple", "newey_west"}:
        raise ValueError("tstat_method 只支持 'simple' 或 'newey_west'。")
    if nw_lags is not None and int(nw_lags) < 0:
        raise ValueError("nw_lags 不能为负数。")
    if weight_method == "value" and not weight_col:
        raise ValueError("weight_method='value' 时必须提供 weight_col。")

    required_cols = [id_col, date_col, sort_col] + ret_cols
    if weight_method == "value" and weight_col is not None:
        required_cols.append(weight_col)
    _check_required_columns(df, required_cols)


def portfolio_sorting_backtest(
    df: pd.DataFrame,
    id_col: str,
    date_col: str,
    sort_col: str,
    ret_cols: str | list[str] | tuple[str, ...],
    n_groups: int = 5,
    higher_sort_long: bool = True,
    weight_method: WeightMethod = "equal",
    weight_col: str | None = None,
    require_ret_before_sort: bool = True,
    frequency: Frequency = "quarter",
    min_group_size: int = 5,
    tstat_method: TStatMethod = "newey_west",
    nw_lags: int | None = None,
) -> PortfolioSortingResult:
    """执行基金组合分组回测。

    Parameters
    ----------
    df:
        基金面板数据，每一行通常是一只基金在某个月末的一条观测。
    id_col:
        基金 ID 列名，例如 "fund_id"。本函数主要用它检查和统计样本。
    date_col:
        调仓日期列名，例如 "month_date"。函数内部会转换为 pandas datetime。
    sort_col:
        分组依据列名，例如 "FAC_rank_vol_m3_n6_pairwise1"。
        调用者需要保证该变量在调仓日当时已经可得，避免偷看未来数据。
    ret_cols:
        一个或多个未来表现列名，例如 "future_ret_6m"。
    n_groups:
        分组数量，默认 5，即五分组。
    higher_sort_long:
        如果为 True，sort_col 越高的一组是 High；如果为 False，sort_col 越低的一组是
        High。High-Low 始终表示“经济含义更好的一组 - 更差的一组”。
    weight_method:
        "equal" 表示等权；"value" 表示使用 weight_col 做规模加权。
    weight_col:
        规模加权所用权重列。只有 weight_method="value" 时需要。
    require_ret_before_sort:
        如果为 True，每个 ret_col 单独检验时，排序前先剔除 sort_col 或该 ret_col
        缺失的基金；如果为 False，排序前只剔除 sort_col 缺失，组合收益计算时再剔除
        ret_col 缺失。
    frequency:
        调仓频率。默认 "quarter"，会保留 3、6、9、12 月观测。
    min_group_size:
        每个日期、每个分组至少需要的基金数量；低于该门槛时该组当期收益记为 NaN。
    tstat_method:
        "simple" 使用普通时间序列 t 值；"newey_west" 使用 HAC/Newey-West t 值。
    nw_lags:
        Newey-West 滞后阶数；None 时使用经验规则自动设置。

    Returns
    -------
    PortfolioSortingResult
        包含 period_returns、summary_table 和 diagnostics 三张 DataFrame。
    """

    normalized_ret_cols = _normalize_ret_cols(ret_cols)
    _validate_inputs(
        df=df,
        id_col=id_col,
        date_col=date_col,
        sort_col=sort_col,
        ret_cols=normalized_ret_cols,
        n_groups=n_groups,
        weight_method=weight_method,
        weight_col=weight_col,
        min_group_size=min_group_size,
        tstat_method=tstat_method,
        nw_lags=nw_lags,
    )

    # 复制输入数据，避免函数内部转换日期、临时加列时影响调用者原始 DataFrame。
    work_df = df.copy()
    work_df[date_col] = pd.to_datetime(work_df[date_col], errors="coerce")
    if work_df[date_col].isna().any():
        n_bad_dates = int(work_df[date_col].isna().sum())
        raise ValueError(f"date_col={date_col!r} 中有 {n_bad_dates} 行无法转换为日期。")

    # 按调仓频率筛选日期；季度检验默认只保留 3、6、9、12 月观测。
    rebalance_df = _filter_rebalance_dates(work_df, date_col=date_col, frequency=frequency)
    if rebalance_df.empty:
        raise ValueError(f"按 frequency={frequency!r} 筛选后没有任何调仓日样本。")

    period_return_rows: list[dict[str, object]] = []
    diagnostics_rows: list[dict[str, object]] = []

    # 每个未来收益列都独立做一次组合检验，因为缺失值处理可能不同。
    for ret_col in normalized_ret_cols:
        for rebalance_date, date_df in rebalance_df.groupby(date_col, sort=True):
            # 记录这个调仓日的基础样本诊断，后面会继续补充各组样本数。
            diagnostic_row: dict[str, object] = {
                "ret_col": ret_col,
                "date": rebalance_date,
                "n_total": int(len(date_df)),
                "n_sort_missing": int(date_df[sort_col].isna().sum()),
                "n_ret_missing": int(date_df[ret_col].isna().sum()),
                "require_ret_before_sort": bool(require_ret_before_sort),
            }

            # 排序前必须至少剔除 sort_col 缺失，因为没有分组依据就无法排序。
            sort_input = date_df.loc[date_df[sort_col].notna()].copy()

            if require_ret_before_sort:
                # 这个开关为 True 时，分组边界只由“未来收益也可观测”的基金决定。
                # 这样每组收益的样本和排序样本完全一致，但会改变分组断点。
                sort_input = sort_input.loc[sort_input[ret_col].notna()].copy()

            diagnostic_row["n_before_sort"] = int(len(sort_input))

            if weight_method == "value" and weight_col is not None:
                # 规模加权结果只允许使用缺失权重和非正权重之外的样本。
                # 这一步放在排序前，是为了让 value-weighted 的分组边界和实际可投资样本一致。
                valid_weight_mask = sort_input[weight_col].notna() & (sort_input[weight_col] > 0)
                diagnostic_row["n_weight_missing_or_nonpositive"] = int((~valid_weight_mask).sum())
                sort_input = sort_input.loc[valid_weight_mask].copy()
            else:
                diagnostic_row["n_weight_missing_or_nonpositive"] = 0

            diagnostic_row["n_after_weight_filter"] = int(len(sort_input))

            # 先给所有组放默认缺失计数，避免某个日期无法分组时 diagnostics 列不完整。
            for economic_group in range(1, n_groups + 1):
                diagnostic_row[f"group_{economic_group}_n"] = 0

            if sort_input.empty:
                diagnostics_rows.append(diagnostic_row)
                continue

            # raw_group 按 sort_col 从低到高编号：1 是最低 sort_col，n_groups 是最高 sort_col。
            sort_input["_raw_group"] = _assign_quantile_groups(sort_input[sort_col], n_groups)
            sort_input = sort_input.loc[sort_input["_raw_group"].notna()].copy()

            if sort_input.empty:
                diagnostics_rows.append(diagnostic_row)
                continue

            # economic_group 永远按经济含义排序：1=Low，n_groups=High。
            # 如果 sort_col 越高越好，raw_group 和 economic_group 相同；
            # 如果 sort_col 越低越好，则把分组方向反过来。
            if higher_sort_long:
                sort_input["_economic_group"] = sort_input["_raw_group"].astype(int)
            else:
                sort_input["_economic_group"] = n_groups + 1 - sort_input["_raw_group"].astype(int)

            for economic_group in range(1, n_groups + 1):
                group_df = sort_input.loc[sort_input["_economic_group"] == economic_group].copy()
                group_label = _format_group_label(economic_group, n_groups)

                # require_ret_before_sort=False 时，未来收益缺失的基金已经参与分组，
                # 但不能参与组合收益计算，所以这里再剔除 ret_col 缺失。
                return_df = group_df.loc[group_df[ret_col].notna()].copy()

                diagnostic_row[f"group_{economic_group}_n"] = int(len(return_df))

                if len(return_df) < min_group_size:
                    portfolio_ret = np.nan
                elif weight_method == "equal":
                    portfolio_ret = _weighted_average(return_df[ret_col], None, weight_method)
                else:
                    assert weight_col is not None
                    portfolio_ret = _weighted_average(
                        return_df[ret_col],
                        return_df[weight_col],
                        weight_method,
                    )

                period_return_rows.append(
                    {
                        "ret_col": ret_col,
                        "date": rebalance_date,
                        "sort_col": sort_col,
                        "economic_group": economic_group,
                        "group_label": group_label,
                        "sort_mean": (
                            float(return_df[sort_col].mean())
                            if return_df[sort_col].notna().any()
                            else np.nan
                        ),
                        "portfolio_ret": portfolio_ret,
                        "n_funds": int(len(return_df)),
                    }
                )

            diagnostics_rows.append(diagnostic_row)

    period_returns = pd.DataFrame(period_return_rows)
    diagnostics = pd.DataFrame(diagnostics_rows)

    # 如果所有日期都无法形成组合，返回空的 summary_table，但保留 diagnostics 供排错。
    if period_returns.empty:
        empty_summary = pd.DataFrame(
            columns=["ret_col", "portfolio", "mean", "t_stat", "n_periods", "tstat_method"]
        )
        return PortfolioSortingResult(period_returns, empty_summary, diagnostics)

    summary_rows: list[dict[str, object]] = []

    for ret_col in normalized_ret_cols:
        ret_period_returns = period_returns.loc[period_returns["ret_col"] == ret_col].copy()

        for economic_group in range(1, n_groups + 1):
            group_label = _format_group_label(economic_group, n_groups)
            series = ret_period_returns.loc[
                ret_period_returns["economic_group"] == economic_group,
                "portfolio_ret",
            ]

            summary_rows.append(
                {
                    "ret_col": ret_col,
                    "portfolio": group_label,
                    "economic_group": economic_group,
                    "mean": float(series.mean(skipna=True)) if series.notna().any() else np.nan,
                    "t_stat": _mean_tstat(series, tstat_method=tstat_method, nw_lags=nw_lags),
                    "n_periods": int(series.notna().sum()),
                    "tstat_method": tstat_method,
                    "nw_lags": nw_lags,
                }
            )

        # High-Low 需要先按日期把 High 和 Low 对齐，再计算差值时间序列。
        pivot = ret_period_returns.pivot_table(
            index="date",
            columns="economic_group",
            values="portfolio_ret",
            aggfunc="first",
        )
        if 1 in pivot.columns and n_groups in pivot.columns:
            high_low = pivot[n_groups] - pivot[1]
        else:
            high_low = pd.Series(dtype=float)

        summary_rows.append(
            {
                "ret_col": ret_col,
                "portfolio": "High-Low",
                "economic_group": np.nan,
                "mean": float(high_low.mean(skipna=True)) if high_low.notna().any() else np.nan,
                "t_stat": _mean_tstat(high_low, tstat_method=tstat_method, nw_lags=nw_lags),
                "n_periods": int(high_low.notna().sum()),
                "tstat_method": tstat_method,
                "nw_lags": nw_lags,
            }
        )

    summary_table = pd.DataFrame(summary_rows)
    return PortfolioSortingResult(period_returns, summary_table, diagnostics)


def load_regression_config(model_key: str) -> dict[str, object]:
    """从 ``D_analysis/config/regression_registry.py`` 读取实验配置。

    Parameters
    ----------
    model_key:
        registry 中登记的模型名称，例如 "fm_baseline"。

    Returns
    -------
    dict[str, object]
        指定模型的配置副本。
    """

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到 regression registry：{REGISTRY_PATH}")

    # 按文件路径加载 registry，避免要求 D_analysis 必须是 Python 包。
    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry",
        REGISTRY_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 regression registry：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(model_key)


def resolve_project_path(path_text: str) -> Path:
    """把项目相对路径转成绝对路径。"""

    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def apply_registry_sample_filters(
    df: pd.DataFrame,
    sample_filters: dict[str, object],
) -> pd.DataFrame:
    """根据 registry 中的样本筛选条件过滤数据。

    Parameters
    ----------
    df:
        原始面板数据。
    sample_filters:
        registry 中的 ``sample_filters``，例如
        ``{"is_insample_future_ret_6m": 1}``。

    Returns
    -------
    pd.DataFrame
        筛选后的数据副本。
    """

    filtered_df = df.copy()
    for col, expected_value in sample_filters.items():
        if col not in filtered_df.columns:
            raise ValueError(f"样本筛选列不存在：{col}")
        # 数值筛选优先用数值比较，兼容 1、1.0、"1" 这几种常见存储方式。
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            actual_numeric = pd.to_numeric(filtered_df[col], errors="coerce")
            keep_mask = actual_numeric == float(expected_value)
        else:
            keep_mask = filtered_df[col].astype("string") == str(expected_value)
        filtered_df = filtered_df.loc[keep_mask].copy()
    return filtered_df


def get_filters_for_factor(
    base_filters: dict[str, object],
    factor_sample_filters: dict[str, dict[str, object]],
    factor_col: str,
) -> dict[str, object]:
    """合并基础样本筛选和某个 factor 的额外筛选条件。"""
    # sample_filters 是所有 factor 共同适用的基础口径；factor_sample_filters 只在当前 sort_col 上叠加。
    combined_filters = dict(base_filters)
    for column, expected_value in factor_sample_filters.get(factor_col, {}).items():
        # 同一列如果前后要求不同，说明 registry 配置本身冲突，不能静默覆盖。
        if column in combined_filters and combined_filters[column] != expected_value:
            raise ValueError(
                f"{factor_col} 的筛选条件与基础筛选冲突："
                f"{column}={combined_filters[column]!r} vs {expected_value!r}"
            )
        combined_filters[column] = expected_value
    return combined_filters


def normalize_standardize_method(method: object) -> str:
    """把 registry 中的标准化写法统一成脚本内部使用的取值。"""
    normalized = STANDARDIZE_ALIASES.get(
        str(method if method is not None else STANDARDIZE_NONE).strip().lower()
    )
    if normalized is None:
        available = ", ".join(sorted({STANDARDIZE_NONE, STANDARDIZE_CROSS_SECTION}))
        raise ValueError(f"未知交互项标准化方式：{method!r}；可选值：{available}")
    return normalized


def parse_braced_interaction(text: str) -> tuple[str, str]:
    """解析 ``{X1,X2}`` 形式的交互项声明。"""
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError(f"字符串交互项必须写成 {{X1,X2}} 形式：{text!r}")

    variables = [part.strip() for part in stripped[1:-1].split(",") if part.strip()]
    if len(variables) != 2:
        raise ValueError(f"交互项必须恰好包含两个变量：{text!r}")
    return variables[0], variables[1]


def make_interaction_sort_col(var1: str, var2: str, standardize: str) -> str:
    """生成 portfolio sorting 使用的交互项排序列名。"""
    suffix = "" if standardize == STANDARDIZE_NONE else "__zcs"
    return f"{var1}__x__{var2}{suffix}"


def resolve_interaction_variable(variable: str, factor_col: str) -> str:
    """把交互项占位符替换成当前 factor 对应的真实列名。"""
    if variable == CURRENT_FACTOR_PLACEHOLDER:
        return factor_col
    if variable == MATCHED_RANK_MEAN_PLACEHOLDER:
        if not factor_col.startswith("FAC_rank_vol_"):
            raise ValueError(f"无法从当前 factor 推导 rank_mean 列名：{factor_col!r}")
        return factor_col.replace("FAC_rank_vol_", "rank_mean_", 1)
    return variable


def parse_interaction_item(item: object) -> dict[str, str]:
    """把单个交互项配置整理成统一结构。

    这里支持和 Fama-MacBeth 回归脚本一致的几种写法，方便 registry 复用同一套配置。
    """
    standardize = STANDARDIZE_NONE

    if isinstance(item, str):
        var1, var2 = parse_braced_interaction(item)
    elif isinstance(item, dict):
        if "variables" in item:
            variables = item["variables"]
        elif "vars" in item:
            variables = item["vars"]
        elif "columns" in item:
            variables = item["columns"]
        elif {"x1", "x2"}.issubset(item):
            variables = [item["x1"], item["x2"]]
        else:
            raise ValueError(
                "字典交互项必须包含 variables/vars/columns，或同时包含 x1 和 x2："
                f"{item!r}"
            )

        if isinstance(variables, str):
            var1, var2 = parse_braced_interaction(variables)
        else:
            variables = sorted(variables) if isinstance(variables, set) else list(variables)
            if len(variables) != 2:
                raise ValueError(f"交互项必须恰好包含两个变量：{item!r}")
            var1, var2 = str(variables[0]), str(variables[1])

        standardize = normalize_standardize_method(item.get("standardize", STANDARDIZE_NONE))
    elif isinstance(item, (list, tuple, set)):
        variables = sorted(item) if isinstance(item, set) else list(item)
        if len(variables) != 2:
            raise ValueError(f"交互项必须恰好包含两个变量：{item!r}")
        var1, var2 = str(variables[0]), str(variables[1])
    else:
        raise TypeError(f"不支持的交互项配置类型：{type(item).__name__}")

    var1 = str(var1).strip()
    var2 = str(var2).strip()
    if not var1 or not var2:
        raise ValueError(f"交互项变量名不能为空：{item!r}")
    if var1 == var2:
        raise ValueError(f"交互项的两个变量不能相同：{item!r}")

    return {
        "var1": var1,
        "var2": var2,
        "standardize": standardize,
    }


def expand_sort_specs(
    raw_sort_factors: list[object],
    base_factors: list[str],
) -> list[dict[str, object]]:
    """把 registry 的 portfolio_sorting_factors 展开成实际可运行的排序规格。

    普通字符串代表输入表已有列；含 FAC 的交互项会被展开成每个 Consistency factor
    各一列，这样 portfolio sorting 可以分别输出五个交互项分组结果。
    """
    sort_specs: list[dict[str, object]] = []

    for item in raw_sort_factors:
        if isinstance(item, str) and not item.strip().startswith("{"):
            sort_specs.append(
                {
                    "sort_col": str(item),
                    "filter_factor": str(item),
                    "kind": "column",
                    "source_columns": [str(item)],
                }
            )
            continue

        interaction = parse_interaction_item(item)
        variables = [interaction["var1"], interaction["var2"]]
        has_factor_placeholder = (
            CURRENT_FACTOR_PLACEHOLDER in variables
            or MATCHED_RANK_MEAN_PLACEHOLDER in variables
        )
        factors_to_expand = base_factors if has_factor_placeholder else [None]

        for factor_col in factors_to_expand:
            resolved_vars = [
                resolve_interaction_variable(variable, str(factor_col))
                if factor_col is not None
                else variable
                for variable in variables
            ]
            var1 = str(resolved_vars[0])
            var2 = str(resolved_vars[1])
            if var1 == var2:
                raise ValueError(
                    f"交互项 {item!r} 在 factor={factor_col} 下变成同一个变量，请检查配置。"
                )

            sort_col = make_interaction_sort_col(var1, var2, interaction["standardize"])
            sort_specs.append(
                {
                    "sort_col": sort_col,
                    "filter_factor": str(factor_col) if factor_col is not None else sort_col,
                    "kind": "interaction",
                    "source_columns": [var1, var2],
                    "var1": var1,
                    "var2": var2,
                    "standardize": interaction["standardize"],
                    "raw_config": make_json_safe(item),
                }
            )

    sort_cols = [str(spec["sort_col"]) for spec in sort_specs]
    duplicated = sorted({col for col in sort_cols if sort_cols.count(col) > 1})
    if duplicated:
        raise ValueError(f"portfolio sorting 排序列名重复：{duplicated}")

    return sort_specs


def standardize_sort_source_by_date(
    data: pd.DataFrame,
    date_col: str,
    column: str,
    standardization_mask: pd.Series,
) -> pd.Series:
    """按每个调仓可见日期的横截面对排序变量来源列做 z-score 标准化。"""

    def zscore(group: pd.Series) -> pd.Series:
        numeric = pd.to_numeric(group, errors="coerce")
        std = numeric.std(ddof=0)
        if pd.isna(std) or std == 0:
            return pd.Series(np.nan, index=group.index)
        return (numeric - numeric.mean()) / std

    standardized = pd.Series(np.nan, index=data.index, dtype=float)
    standardized.loc[standardization_mask] = (
        data.loc[standardization_mask].groupby(date_col, sort=False)[column].transform(zscore)
    )
    return standardized


def add_interaction_sort_column(
    data: pd.DataFrame,
    date_col: str,
    sort_spec: dict[str, object],
    ret_col: str,
) -> pd.DataFrame:
    """为单个交互项排序规格生成排序列。

    标准化口径使用“当前排序变量和收益列都非缺失”的样本，这与
    ``portfolio_sorting_backtest`` 默认排序前剔除未来收益缺失的口径保持一致。
    """
    if sort_spec.get("kind") != "interaction":
        return data

    result = data.copy()
    var1 = str(sort_spec["var1"])
    var2 = str(sort_spec["var2"])
    sort_col = str(sort_spec["sort_col"])
    standardize = str(sort_spec["standardize"])

    _check_required_columns(result, [date_col, ret_col, var1, var2])
    standardization_mask = result[[ret_col, var1, var2]].notna().all(axis=1)

    if standardize == STANDARDIZE_NONE:
        left = pd.to_numeric(result[var1], errors="coerce")
        right = pd.to_numeric(result[var2], errors="coerce")
    elif standardize == STANDARDIZE_CROSS_SECTION:
        left = standardize_sort_source_by_date(result, date_col, var1, standardization_mask)
        right = standardize_sort_source_by_date(result, date_col, var2, standardization_mask)
    else:
        raise ValueError(f"未知交互项标准化方式：{standardize!r}")

    result[sort_col] = left * right
    return result


def build_research_summary_table(
    result: PortfolioSortingResult,
    sort_col: str,
    ret_col: str,
    n_groups: int,
    tstat_method: TStatMethod,
    nw_lags: int | None,
) -> pd.DataFrame:
    """生成用户指定格式的 portfolio sorting 研究表。

    表格行包括 Q1/Q2/Q3/Q4/Q5/long-short/t-stat/p-value；
    列包括每组分组指标均值和未来六个月收益均值。

    Parameters
    ----------
    result:
        ``portfolio_sorting_backtest`` 的输出。
    sort_col:
        当前用于分组的一致性指标列名。
    ret_col:
        当前未来收益列名。
    n_groups:
        分组数量。
    tstat_method:
        long-short t 值使用的方法。
    nw_lags:
        Newey-West 滞后阶数。

    Returns
    -------
    pd.DataFrame
        一张适合直接写入 CSV/Excel 的汇总表。
    """

    period_df = result.period_returns.loc[result.period_returns["ret_col"] == ret_col].copy()
    rows: list[dict[str, object]] = []

    # 先逐组填 Q1-Q5。这里的 Q1 是经济含义 Low，Q5 是经济含义 High。
    for economic_group in range(1, n_groups + 1):
        group_df = period_df.loc[period_df["economic_group"] == economic_group].copy()
        rows.append(
            {
                "portfolio": f"Q{economic_group}",
                "consistency_mean": (
                    float(group_df["sort_mean"].mean(skipna=True))
                    if group_df["sort_mean"].notna().any()
                    else np.nan
                ),
                ret_col: (
                    float(group_df["portfolio_ret"].mean(skipna=True))
                    if group_df["portfolio_ret"].notna().any()
                    else np.nan
                ),
                "sort_col": sort_col,
            }
        )

    pivot_ret = period_df.pivot_table(
        index="date",
        columns="economic_group",
        values="portfolio_ret",
        aggfunc="first",
    )
    pivot_sort = period_df.pivot_table(
        index="date",
        columns="economic_group",
        values="sort_mean",
        aggfunc="first",
    )

    # long-short 永远用 Q5 - Q1，因为 economic_group 已经按经济含义排好：
    # Q5 是更好的一组，Q1 是更差的一组。
    long_short_ret = pivot_ret[n_groups] - pivot_ret[1]
    long_short_sort = pivot_sort[n_groups] - pivot_sort[1]
    long_short_t, long_short_p = _tstat_pvalue(
        long_short_ret,
        tstat_method=tstat_method,
        nw_lags=nw_lags,
    )

    rows.append(
        {
            "portfolio": "long-short",
            "consistency_mean": (
                float(long_short_sort.mean(skipna=True))
                if long_short_sort.notna().any()
                else np.nan
            ),
            ret_col: (
                float(long_short_ret.mean(skipna=True))
                if long_short_ret.notna().any()
                else np.nan
            ),
            "sort_col": sort_col,
        }
    )
    rows.append(
        {
            "portfolio": "t-stat",
            "consistency_mean": np.nan,
            ret_col: long_short_t,
            "sort_col": sort_col,
        }
    )
    rows.append(
        {
            "portfolio": "p-value",
            "consistency_mean": np.nan,
            ret_col: long_short_p,
            "sort_col": sort_col,
        }
    )

    return pd.DataFrame(rows, columns=["portfolio", "consistency_mean", ret_col, "sort_col"])


def plot_portfolio_return_bars(
    research_table: pd.DataFrame,
    sort_col: str,
    ret_col: str,
    output_path: Path,
) -> None:
    """绘制 Q1-Q5 和 long-short 收益率柱状图。

    Parameters
    ----------
    research_table:
        ``build_research_summary_table`` 生成的结果表。
    sort_col:
        当前用于分组的一致性指标列名，用于图标题。
    ret_col:
        未来收益列名，用于图标题和 y 轴。
    output_path:
        图片输出路径。
    """

    plot_df = research_table.loc[
        research_table["portfolio"].isin(["Q1", "Q2", "Q3", "Q4", "Q5", "long-short"])
    ].copy()

    colors = ["#4C78A8"] * 5 + ["#F58518"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(plot_df["portfolio"], plot_df[ret_col], color=colors[: len(plot_df)])
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title(f"Portfolio sorting returns: {sort_col}")
    ax.set_xlabel("Portfolio")
    ax.set_ylabel(ret_col)

    # 在柱子上标出数值，方便快速判断 Q1-Q5 是否有递变形状。
    for idx, value in enumerate(plot_df[ret_col]):
        if pd.isna(value):
            continue
        vertical_offset = 0.002 if value >= 0 else -0.004
        ax.text(
            idx,
            value + vertical_offset,
            f"{value:.3f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=9,
        )

    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def _plot_portfolio_return_bars_on_axis(
    ax: plt.Axes,
    research_table: pd.DataFrame,
    sort_col: str,
    ret_col: str,
) -> None:
    """在指定子图上绘制单个因子的 Q1-Q5 和 long-short 收益率。"""

    plot_df = research_table.loc[
        research_table["portfolio"].isin(["Q1", "Q2", "Q3", "Q4", "Q5", "long-short"])
    ].copy()

    colors = ["#4C78A8"] * 5 + ["#F58518"]
    ax.bar(plot_df["portfolio"], plot_df[ret_col], color=colors[: len(plot_df)])
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_title(sort_col, fontsize=9)
    ax.set_xlabel("")
    ax.set_ylabel(ret_col, fontsize=8)
    ax.tick_params(axis="x", labelsize=8, rotation=20)
    ax.tick_params(axis="y", labelsize=8)

    # 每个小图空间有限，只保留三位小数，帮助快速看方向和量级。
    for idx, value in enumerate(plot_df[ret_col]):
        if pd.isna(value):
            continue
        vertical_offset = 0.002 if value >= 0 else -0.004
        ax.text(
            idx,
            value + vertical_offset,
            f"{value:.3f}",
            ha="center",
            va="bottom" if value >= 0 else "top",
            fontsize=7,
        )


def plot_portfolio_return_grid(
    research_tables: list[pd.DataFrame],
    sort_cols: list[str],
    ret_col: str,
    output_path: Path,
    *,
    max_cols: int = 3,
) -> None:
    """把一个或多个因子的 portfolio sorting 柱状图放在同一张图里。

    图的布局跟随因子数量自动调整：只有一个因子时就是一张完整子图，
    两个因子时一行两张，三个及以上时最多每行三张。这样既保留统一大标题，
    又避免单因子结果被强行塞进 1×3 的空画布里。
    """

    if len(research_tables) != len(sort_cols):
        raise ValueError("research_tables 和 sort_cols 数量必须一致。")
    if not research_tables:
        return

    # 根据真实因子数量决定列数。max_cols 保留为参数，方便未来需要每行两张或四张时复用。
    n_items = len(research_tables)
    n_cols = min(max_cols, n_items)
    n_rows = int(np.ceil(len(research_tables) / n_cols))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5.2 * n_cols, 4.0 * n_rows))
    flat_axes = np.atleast_1d(axes).ravel()

    for ax, research_table, sort_col in zip(flat_axes, research_tables, sort_cols):
        _plot_portfolio_return_bars_on_axis(ax, research_table, sort_col, ret_col)

    # 因子数不是 3 的倍数时，隐藏末尾空白子图，避免画布上出现无意义坐标轴。
    for ax in flat_axes[len(research_tables):]:
        ax.set_visible(False)

    fig.suptitle(f"Portfolio sorting returns: {ret_col}", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def remove_individual_bar_figures(output_dir: Path, output_id: str, ret_col: str) -> None:
    """清理旧版逐因子柱状图，让目录里只保留汇总画布。

    旧版本会输出 ``ps_xxx_因子名_y_bar.png``。现在图都汇总到一张画布上，
    因此这里删除同一个 output_id、同一个 y 的旧单图，避免用户误以为需要逐张查看。
    """

    for figure_path in output_dir.glob(f"{output_id}_*_{ret_col}_bar.png"):
        figure_path.unlink()


def parse_future_return_horizon(y_col: str) -> int:
    """从未来收益列名中解析持有期长度。

    Parameters
    ----------
    y_col:
        未来收益列名，例如 ``future_ret_3m``、``future_ret_6m``。

    Returns
    -------
    int
        以月为单位的未来收益窗口长度。

    Raises
    ------
    ValueError
        如果列名中无法解析出 ``数字 + m`` 的期限信息，就直接报错。
    """

    match = re.fullmatch(r"future_ret_(\d+)m", y_col)
    if match is None:
        raise ValueError(
            f"无法从 y_col={y_col!r} 解析未来收益期限；"
            "当前只支持类似 future_ret_3m、future_ret_6m、future_ret_12m 的命名。"
        )
    return int(match.group(1))


def load_output_registry(registry_path: Path) -> dict[str, object]:
    """读取 portfolio sorting 输出登记文件。

    如果 registry 还不存在，就返回一个空登记结构。这样第一次运行时不用手工建文件。
    """

    if not registry_path.exists():
        return {"version": 1, "records": []}

    with registry_path.open("r", encoding="utf-8") as f:
        registry = json.load(f)

    if "records" not in registry or not isinstance(registry["records"], list):
        raise ValueError(f"registry 文件结构不合法，缺少 records 列表：{registry_path}")
    return registry


def save_output_registry(registry: dict[str, object], registry_path: Path) -> None:
    """保存 portfolio sorting 输出登记文件。"""

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def make_json_safe(value: object) -> object:
    """把配置值转换成适合 JSON 稳定比较的类型。"""

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): make_json_safe(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [make_json_safe(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def build_output_core_config(
    *,
    model_key: str,
    input_path: Path,
    factors: list[str],
    date_col: str,
    id_col: str,
    sample_filters: dict[str, object],
    factor_sample_filters: dict[str, dict[str, object]],
    newey_west_lag: int | None,
    frequency: Frequency,
    n_groups: int,
    min_group_size: int,
    higher_sort_long: bool,
    require_ret_before_sort: bool,
    weight_method: WeightMethod,
    weight_col: str | None,
    tstat_method: TStatMethod,
) -> dict[str, object]:
    """生成用于匹配 output_id 的核心配置。

    注意这里故意不包含 y_col。按照需求，除 y 以外配置完全一致时，不同 Y 应合并到
    同一个 output_id 下。
    """

    return make_json_safe(
        {
            "model_key": model_key,
            "input_path": input_path,
            "factors": factors,
            "date_col": date_col,
            "id_col": id_col,
            "sample_filters": sample_filters,
            "factor_sample_filters": factor_sample_filters,
            "newey_west_lag": newey_west_lag,
            "frequency": frequency,
            "n_groups": n_groups,
            "min_group_size": min_group_size,
            "higher_sort_long": higher_sort_long,
            "require_ret_before_sort": require_ret_before_sort,
            "weight_method": weight_method,
            "weight_col": weight_col,
            "tstat_method": tstat_method,
        }
    )


def next_output_id(records: list[dict[str, object]]) -> str:
    """根据现有记录生成下一个稳定递增 output_id。"""

    max_number = 0
    for record in records:
        output_id = str(record.get("output_id", ""))
        match = re.fullmatch(r"ps_(\d+)", output_id)
        if match is not None:
            max_number = max(max_number, int(match.group(1)))
    return f"ps_{max_number + 1:03d}"


def find_or_create_output_record(
    registry: dict[str, object],
    core_config: dict[str, object],
    y_col: str,
    output_dir: Path,
) -> dict[str, object]:
    """匹配或新建本次运行对应的 output registry 记录。

    匹配逻辑：
    1. 除 y 外的核心配置完全一致时，沿用已有 output_id；
    2. 没有匹配记录时，新建 output_id；
    3. y_col 不参与 output_id 匹配，只记录在 y_cols 中。
    """

    records = registry["records"]
    assert isinstance(records, list)

    now_text = datetime.now().isoformat(timespec="seconds")
    for record in records:
        if record.get("core_config") == core_config:
            y_cols = list(record.get("y_cols", []))
            if y_col not in y_cols:
                y_cols.append(y_col)
            record["y_cols"] = sort_y_cols_by_horizon(y_cols)
            record["updated_at"] = now_text
            return record

    output_id = next_output_id(records)
    record = {
        "output_id": output_id,
        "created_at": now_text,
        "updated_at": now_text,
        "core_config": core_config,
        "y_cols": [y_col],
        "output_paths": build_output_paths(output_dir, output_id),
    }
    records.append(record)
    return record


def build_output_paths(output_dir: Path, output_id: str) -> dict[str, str]:
    """集中生成 output_id 对应的核心输出文件路径。"""

    return {
        "summary": str(output_dir / f"{output_id}_summary.csv"),
        "period_returns": str(output_dir / f"{output_id}_period_returns.csv"),
        "diagnostics": str(output_dir / f"{output_id}_diagnostics.csv"),
        "sample_periods": str(output_dir / f"{output_id}_sample_periods.csv"),
        "registry": str(output_dir / "portfolio_sorting_registry.json"),
    }


def sort_y_cols_by_horizon(y_cols: list[str]) -> list[str]:
    """按未来收益期限从短到长排序 y 列。"""

    return sorted(y_cols, key=parse_future_return_horizon)


def merge_summary_tables(
    existing_summary: pd.DataFrame | None,
    new_summary: pd.DataFrame,
    y_col: str,
    y_cols: list[str],
) -> pd.DataFrame:
    """把新 Y 的结果合并进同一 output_id 的主 summary 表。

    主表保留简洁的横向结构：
    ``sort_col``、``portfolio``、``consistency_mean``、多个 y_col。
    如果同一个 y_col 重跑，会先移除旧列再写入新列，实现覆盖。
    """

    key_cols = ["sort_col", "portfolio"]
    value_cols = key_cols + ["consistency_mean", y_col]
    new_part = new_summary[value_cols].copy()

    if existing_summary is None or existing_summary.empty:
        merged = new_part
    else:
        existing = existing_summary.copy()
        if y_col in existing.columns:
            # 同一 output_id 下重跑同一个 y 时，删除旧 y 列后再合并新结果。
            existing = existing.drop(columns=[y_col])

        # consistency_mean 只由 X 分组决定，和 Y 没有直接关系；如果旧表已有，
        # 以本次重跑结果为准覆盖，避免样本口径更新后留下旧值。
        if "consistency_mean" in existing.columns:
            existing = existing.drop(columns=["consistency_mean"])

        merged = existing.merge(new_part, on=key_cols, how="outer")

    ordered_y_cols = [col for col in sort_y_cols_by_horizon(y_cols) if col in merged.columns]
    ordered_cols = key_cols + ["consistency_mean"] + ordered_y_cols
    portfolio_order = {
        "Q1": 1,
        "Q2": 2,
        "Q3": 3,
        "Q4": 4,
        "Q5": 5,
        "long-short": 6,
        "t-stat": 7,
        "p-value": 8,
    }
    merged["_portfolio_order"] = merged["portfolio"].map(portfolio_order).fillna(99)
    merged = merged.sort_values(["sort_col", "_portfolio_order", "portfolio"]).drop(
        columns=["_portfolio_order"]
    )
    return merged[ordered_cols].reset_index(drop=True)


def build_sample_periods_table(result: PortfolioSortingResult, sort_col: str) -> pd.DataFrame:
    """整理每个组合用于统计的有效期数，供诊断使用。"""

    rows: list[dict[str, object]] = []
    for _, row in result.summary_table.iterrows():
        rows.append(
            {
                "sort_col": sort_col,
                "ret_col": row["ret_col"],
                "portfolio": row["portfolio"],
                "n_periods": row["n_periods"],
            }
        )
    return pd.DataFrame(rows)


def merge_long_output_by_y(
    existing_df: pd.DataFrame | None,
    new_df: pd.DataFrame,
    y_col: str,
) -> pd.DataFrame:
    """合并 period_returns、diagnostics、sample_periods 等长表输出。

    同一个 y_col 重跑时，会删掉旧 y 的行再写入新行；不同 y_col 会自然追加。
    """

    if existing_df is None or existing_df.empty or "ret_col" not in existing_df.columns:
        return new_df.copy()

    kept_existing = existing_df.loc[existing_df["ret_col"] != y_col].copy()
    return pd.concat([kept_existing, new_df], ignore_index=True)


def has_tuple_factor(factors: list[object]) -> bool:
    """判断 registry factors 中是否包含 tuple/list 形式的 dummy 变量组。"""

    return any(isinstance(factor, (tuple, list)) for factor in factors)


def write_skipped_portfolio_sorting_registry(
    output_registry_path: Path,
    *,
    model_key: str,
    input_path: Path,
    reason: str,
    factors: list[object],
) -> None:
    """为不适合 portfolio sorting 的模型写出跳过记录，避免 engine 误判失败。"""

    registry = load_output_registry(output_registry_path)
    registry["skipped"] = True
    registry["last_skip"] = {
        "model_key": model_key,
        "input_path": str(input_path),
        "reason": reason,
        "factors": [str(factor) for factor in factors],
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_output_registry(registry, output_registry_path)


def run_registry_portfolio_sorting(
    model_key: str = "fm_baseline",
    factors: list[str] | None = None,
    y_col: str | None = None,
    frequency: Frequency = "quarter",
    n_groups: int = 5,
    min_group_size: int = 5,
    higher_sort_long: bool = True,
    require_ret_before_sort: bool = True,
) -> dict[str, pd.DataFrame]:
    """读取 registry 和真实 panel_base.parquet，批量运行 portfolio sorting。

    Parameters
    ----------
    model_key:
        registry 中的模型名称。
    factors:
        需要跑的 X 列名列表。None 表示跑 registry 中所有 factors。
    y_col:
        本次要检验的未来收益列。None 表示使用 registry 中的 y。
    frequency:
        调仓频率。
    n_groups:
        分组数量。
    min_group_size:
        每组每期最低基金数量。
    higher_sort_long:
        是否把 sort_col 高的一组视为 High。
    require_ret_before_sort:
        是否在排序前剔除未来收益缺失样本。

    Returns
    -------
    dict[str, pd.DataFrame]
        key 是输出名称，value 是对应 DataFrame，便于被其他脚本或 notebook 复用。
    """

    config = load_regression_config(model_key)
    input_path = resolve_project_path(str(config["regression_input_path"]))
    output_dir = resolve_project_path(str(config["output_dir"])) / "portfolio_sorting"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_registry_path = output_dir / "portfolio_sorting_registry.json"

    date_col = str(config["date_col"])
    id_col = str(list(config["id_columns"])[0])
    ret_col = str(y_col) if y_col is not None else str(config["y"])
    # 先解析未来收益期限，避免无法排序的 y_col 静默混进结果表。
    parse_future_return_horizon(ret_col)
    raw_factors = list(config["factors"])
    has_explicit_sort_factors = bool(config.get("portfolio_sorting_factors"))
    if factors is None and not has_explicit_sort_factors and has_tuple_factor(raw_factors):
        reason = (
            "registry factors 包含 tuple/list dummy 变量组，默认 portfolio sorting "
            "没有单一排序列口径；如需运行，请在 registry 中显式配置 portfolio_sorting_factors。"
        )
        write_skipped_portfolio_sorting_registry(
            output_registry_path,
            model_key=model_key,
            input_path=input_path,
            reason=reason,
            factors=raw_factors,
        )
        print(f"跳过 portfolio sorting：{reason}")
        print(f"跳过记录已写入：{output_registry_path}")
        return {}

    base_factors = [str(col) for col in raw_factors]
    raw_sort_factors = list(config.get("portfolio_sorting_factors") or base_factors)
    selected_raw_sort_factors = raw_sort_factors if factors is None else factors
    sort_specs = expand_sort_specs(selected_raw_sort_factors, base_factors)
    selected_factors = [str(spec["sort_col"]) for spec in sort_specs]
    sample_filters = dict(config.get("sample_filters", {}))
    factor_sample_filters = {
        str(factor): dict(filters)
        for factor, filters in dict(config.get("factor_sample_filters", {})).items()
    }
    nw_lags = int(config["newey_west_lag"]) if config.get("newey_west_lag") is not None else None

    core_config = build_output_core_config(
        model_key=model_key,
        input_path=input_path,
        factors=selected_factors,
        date_col=date_col,
        id_col=id_col,
        sample_filters=sample_filters,
        factor_sample_filters=factor_sample_filters,
        newey_west_lag=nw_lags,
        frequency=frequency,
        n_groups=n_groups,
        min_group_size=min_group_size,
        higher_sort_long=higher_sort_long,
        require_ret_before_sort=require_ret_before_sort,
        weight_method="equal",
        weight_col=None,
        tstat_method="newey_west",
    )
    output_registry = load_output_registry(output_registry_path)
    output_record = find_or_create_output_record(
        output_registry,
        core_config=core_config,
        y_col=ret_col,
        output_dir=output_dir,
    )
    output_id = str(output_record["output_id"])
    output_paths = build_output_paths(output_dir, output_id)
    output_record["output_paths"] = output_paths

    df = pd.read_parquet(input_path)

    combined_research_tables: list[pd.DataFrame] = []
    combined_period_returns: list[pd.DataFrame] = []
    combined_diagnostics: list[pd.DataFrame] = []
    combined_sample_periods: list[pd.DataFrame] = []
    plotted_sort_cols: list[str] = []

    for sort_spec in sort_specs:
        sort_col = str(sort_spec["sort_col"])
        filter_factor = str(sort_spec["filter_factor"])
        # portfolio sorting 按 sort_col 单独应用额外筛选，和主回归的 factor_sample_filters 口径一致。
        # 对交互项排序列来说，筛选口径来自它展开时对应的原始 FAC。
        sort_filters = get_filters_for_factor(sample_filters, factor_sample_filters, filter_factor)
        sort_df = apply_registry_sample_filters(df, sort_filters)
        sort_df = add_interaction_sort_column(
            data=sort_df,
            date_col=date_col,
            sort_spec=sort_spec,
            ret_col=ret_col,
        )
        result = portfolio_sorting_backtest(
            df=sort_df,
            id_col=id_col,
            date_col=date_col,
            sort_col=sort_col,
            ret_cols=[ret_col],
            n_groups=n_groups,
            higher_sort_long=higher_sort_long,
            weight_method="equal",
            require_ret_before_sort=require_ret_before_sort,
            frequency=frequency,
            min_group_size=min_group_size,
            tstat_method="newey_west",
            nw_lags=nw_lags,
        )
        research_table = build_research_summary_table(
            result=result,
            sort_col=sort_col,
            ret_col=ret_col,
            n_groups=n_groups,
            tstat_method="newey_west",
            nw_lags=nw_lags,
        )

        combined_research_tables.append(research_table)
        plotted_sort_cols.append(sort_col)
        combined_period_returns.append(result.period_returns)
        combined_diagnostics.append(result.diagnostics)
        combined_sample_periods.append(build_sample_periods_table(result, sort_col))

    new_summary = pd.concat(combined_research_tables, ignore_index=True)
    new_period = pd.concat(combined_period_returns, ignore_index=True)
    new_diag = pd.concat(combined_diagnostics, ignore_index=True)
    new_sample_periods = pd.concat(combined_sample_periods, ignore_index=True)

    summary_path = Path(output_paths["summary"])
    period_path = Path(output_paths["period_returns"])
    diagnostics_path = Path(output_paths["diagnostics"])
    sample_periods_path = Path(output_paths["sample_periods"])

    existing_summary = (
        pd.read_csv(summary_path)
        if summary_path.exists()
        else None
    )
    existing_period = (
        pd.read_csv(period_path)
        if period_path.exists()
        else None
    )
    existing_diag = (
        pd.read_csv(diagnostics_path)
        if diagnostics_path.exists()
        else None
    )
    existing_sample_periods = (
        pd.read_csv(sample_periods_path)
        if sample_periods_path.exists()
        else None
    )

    y_cols = list(output_record.get("y_cols", [ret_col]))
    combined_table = merge_summary_tables(
        existing_summary=existing_summary,
        new_summary=new_summary,
        y_col=ret_col,
        y_cols=y_cols,
    )
    combined_period = merge_long_output_by_y(existing_period, new_period, ret_col)
    combined_diag = merge_long_output_by_y(existing_diag, new_diag, ret_col)
    combined_sample_periods = merge_long_output_by_y(
        existing_sample_periods,
        new_sample_periods,
        ret_col,
    )

    combined_table.to_csv(summary_path, index=False, encoding="utf-8-sig")
    combined_period.to_csv(period_path, index=False, encoding="utf-8-sig")
    combined_diag.to_csv(diagnostics_path, index=False, encoding="utf-8-sig")
    combined_sample_periods.to_csv(sample_periods_path, index=False, encoding="utf-8-sig")

    figure_grid_path = output_dir / f"{output_id}_{ret_col}_bar_grid.png"
    # 统一输出一张多面板图片，替代旧版每个因子一张图的查看方式。
    plot_portfolio_return_grid(
        research_tables=combined_research_tables,
        sort_cols=plotted_sort_cols,
        ret_col=ret_col,
        output_path=figure_grid_path,
    )
    remove_individual_bar_figures(output_dir, output_id, ret_col)

    output_record["y_cols"] = sort_y_cols_by_horizon(y_cols)
    output_record["output_paths"] = output_paths
    output_record["newey_west_lag_by_y"] = {
        **dict(output_record.get("newey_west_lag_by_y", {})),
        ret_col: nw_lags,
    }
    output_record["last_run"] = {
        "y_col": ret_col,
        "factors": selected_factors,
        "sort_specs": make_json_safe(sort_specs),
        "sample_filters": sample_filters,
        "factor_sample_filters": factor_sample_filters,
        "filters_by_factor": {
            str(spec["sort_col"]): get_filters_for_factor(
                sample_filters,
                factor_sample_filters,
                str(spec["filter_factor"]),
            )
            for spec in sort_specs
        },
        "figure_grid": str(figure_grid_path),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_output_registry(output_registry, output_registry_path)

    print(f"output_id：{output_id}")
    print(f"结果已输出到：{output_dir}")
    print(combined_table)

    return {
        "summary": combined_table,
        "period_returns": combined_period,
        "diagnostics": combined_diag,
        "sample_periods": combined_sample_periods,
    }


def build_minimal_example_data() -> pd.DataFrame:
    """构造一份最小模拟数据，展示函数调用方式。

    Returns
    -------
    pd.DataFrame
        包含 fund_id、month_date、sort_signal、future_ret_6m 和 fund_size 的模拟面板。
    """

    rng = np.random.default_rng(20260623)
    month_dates = pd.date_range("2020-01-31", periods=36, freq="ME")
    fund_ids = [f"F{i:03d}" for i in range(1, 81)]

    rows: list[dict[str, object]] = []
    for month_date in month_dates:
        for fund_id in fund_ids:
            # sort_signal 模拟调仓日当时已经知道的基金特征。
            sort_signal = rng.normal(loc=0.0, scale=1.0)
            # 让未来收益和 sort_signal 有一点正相关，方便示例中看到 High-Low 方向。
            future_ret_6m = 0.015 + 0.01 * sort_signal + rng.normal(0.0, 0.05)
            fund_size = rng.lognormal(mean=10.0, sigma=0.8)
            rows.append(
                {
                    "fund_id": fund_id,
                    "month_date": month_date,
                    "sort_signal": sort_signal,
                    "future_ret_6m": future_ret_6m,
                    "fund_size": fund_size,
                }
            )

    return pd.DataFrame(rows)


def run_minimal_example() -> None:
    """运行最小模拟示例，并打印 summary_table。"""

    example_df = build_minimal_example_data()
    result = portfolio_sorting_backtest(
        df=example_df,
        id_col="fund_id",
        date_col="month_date",
        sort_col="sort_signal",
        ret_cols=["future_ret_6m"],
        n_groups=5,
        higher_sort_long=True,
        weight_method="equal",
        frequency="quarter",
        min_group_size=5,
        tstat_method="newey_west",
    )

    print(result.summary_table)


def parse_args() -> argparse.Namespace:
    """读取命令行参数。

    默认行为是读取 registry 中的真实数据路径并运行所有 factors。
    如果只想快速验证一个 X，可以使用 ``--factor 某个列名``。
    """

    parser = argparse.ArgumentParser(description="运行基金季度五分组 portfolio sorting 检验。")
    parser.add_argument(
        "--model",
        default="fm_baseline",
        help="regression_registry.py 中的模型名称，默认 fm_baseline。",
    )
    parser.add_argument(
        "--factor",
        action="append",
        default=None,
        help="只运行指定 X 列名；可重复传入。默认运行 registry 中所有 factors。",
    )
    parser.add_argument(
        "--y-col",
        default=None,
        help="本次要检验的未来收益列；默认使用 registry 中的 y。",
    )
    parser.add_argument(
        "--example",
        action="store_true",
        help="运行最小模拟数据示例，而不是读取真实 panel_base.parquet。",
    )
    parser.add_argument(
        "--frequency",
        default="quarter",
        choices=["month", "monthly", "quarter", "quarterly", "year", "yearly"],
        help="调仓频率，默认 quarter。",
    )
    parser.add_argument(
        "--min-group-size",
        type=int,
        default=5,
        help="每个日期、每个分组最低基金数量，默认 5。",
    )
    parser.add_argument(
        "--lower-sort-long",
        action="store_true",
        help="如果该参数打开，则 sort_col 越低的一组代表经济含义更好的 High。",
    )
    parser.add_argument(
        "--keep-ret-missing-before-sort",
        action="store_true",
        help="如果该参数打开，则排序前不剔除未来收益缺失样本，只在计算收益时剔除。",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.example:
        run_minimal_example()
    else:
        run_registry_portfolio_sorting(
            model_key=args.model,
            factors=args.factor,
            y_col=args.y_col,
            frequency=args.frequency,
            higher_sort_long=not args.lower_sort_long,
            require_ret_before_sort=not args.keep_ret_missing_before_sort,
            min_group_size=args.min_group_size,
        )
