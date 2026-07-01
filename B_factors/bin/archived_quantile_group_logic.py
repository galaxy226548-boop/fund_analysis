"""历史归档：旧版 q5/q10 分组标签生成逻辑。

当前 B_factors pipeline 不再生成 q5/q10 标签。本文件只是把旧逻辑集中保存，
方便以后需要恢复或参考时查阅；不要在生产流程中直接 import。
"""

from __future__ import annotations

import pandas as pd


def make_quantile_group(series: pd.Series, group_count: int) -> pd.Series:
    """把单个月内的某个 Consistency 因子切成 q 组。"""

    result = pd.Series(pd.NA, index=series.index, dtype="Int64")
    valid = series.dropna()
    if len(valid) < group_count:
        return result

    # rank(method="first") 会在相同数值之间按原始顺序打破并列。
    # 这样 qcut 能稳定得到近似等数量分组，同时仍保持“因子值越大，组号越大”。
    ranks = valid.rank(method="first", ascending=True)
    labels = range(1, group_count + 1)
    grouped = pd.qcut(ranks, q=group_count, labels=labels)
    result.loc[valid.index] = grouped.astype("Int64")
    return result


def add_quantile_groups(
    data: pd.DataFrame,
    group_column: str,
    factor_group_suffixes: dict[str, str],
) -> pd.DataFrame:
    """按月为每个 Consistency 因子生成 5 组和 10 组标签。"""

    data = data.copy()
    month_groups = data.groupby(group_column, observed=True, sort=False)

    for factor_column, suffix in factor_group_suffixes.items():
        for group_count in (5, 10):
            output_column = f"q{group_count}_{suffix}"
            data[output_column] = month_groups[factor_column].transform(
                lambda series, q=group_count: make_quantile_group(series, q)
            )
            data[output_column] = data[output_column].astype("Int64")

    return data


def archived_runner_step_quantile_group(
    data: pd.DataFrame,
    group_column: str,
    factor_group_suffixes: dict[str, str],
) -> pd.DataFrame:
    """旧 run_factor_pipeline.py 中 step_quantile_group 的等价逻辑。"""

    return add_quantile_groups(
        data=data,
        group_column=group_column,
        factor_group_suffixes=factor_group_suffixes,
    )
