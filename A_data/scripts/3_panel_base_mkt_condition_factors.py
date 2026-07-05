"""为 ``panel_base`` 和热力图面板追加市态条件一致性因子。

默认读取并覆盖：

    A_data/output/panel_base.parquet
    A_data/output/panel_base_heatmap_m1_12_n1_12.parquet

以及对应的 *_preview.xlsx 预览文件。运行前提：两个面板都已经由
``3_panel_base_mkt_condition.py`` 写入四个 ``mkt_state_*`` 市场状态列。

市态月份选择口径（所有指标共用）：对每个 t 月和每个市态 regime，从 t 往回
（含 t）选取最近 n 个属于该 regime 的月份，跳过不属于的月份；最早被选中的
月份不得早于 t 往前 ``--max-lookback``（默认 36）个月，凑不齐 n 个则该月所有
基金的对应指标记缺失。基金在任一被选中月份缺少排名时结果记缺失，不会悄悄
用更早月份补足。

排名口径说明（与普通 FAC 的已知差异）：普通 ``FAC_rank_vol_m{m}_n{n}`` 的
n 个排名全部在 t 月截面内对 n 个滞后收益窗口排名（同一批基金作分母）；
市态版本需要回看最多 36 个月，超出了 t 月截面排名列的覆盖范围，因此沿用
``3_panel_base_volatility_alternative.py`` 的先例：在每个被选中的市态月 tau，
读取该月自己截面的 ``past_ret_{m}m_rank_1``。两种口径的分母基金池不同，
即使最近 n 个月连续同市态，市态因子与普通因子也只是高度相关而非严格相等。

按 5 套 baseline 窗口规格 (m,n) = (3,6)/(6,3)/(6,6)/(6,12)/(12,6) 与 8 个
regime（4 个市态维度各 2 个方向）生成以下列族：

- ``FAC_rank_vol_{regime}_m{m}_n{n}_pairwise1``：1 - n 个市态月排名的标准差
  （ddof=1），与普通 FAC 同向，越大排名越稳定；
- ``rank_mean_{regime}_m{m}_n{n}_pairwise1``：n 个市态月排名的均值；
- ``is_median_rank_mean_{regime}_...`` / ``is_tercile_rank_mean_{regime}_...``：
  按 month_date x investment_type 截面对市态排名均值做二分/三分组，边界与
  ``3_panel_base_grouping_factors.py`` 完全一致（<=0.5 记 -2、>0.5 记 2；
  <=1/3 记 1、中间记 2、>2/3 记 3）；
- ``hitcount_top50_{regime}_...`` / ``hitrate_top50_{regime}_...`` 与累计
  ``dummy_top50_{regime}_m{m}_n{n}_hit_above{0..n-1}_pairwise1``：命中口径与
  ``3_panel_base_winrates_factors.py`` 一致（rank > 0.5 记命中）。

regime 命名：hs300up/hs300down（沪深300涨跌）、growth/value（国证成长/价值
占优）、large/small（中证800/中证1000占优）、highvol/lowvol（行业横截面
波动率高低）。

同时输出校验表：

    A_data/output/mkt_condition_factors_check.xlsx

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_mkt_condition_factors.py
    .venv/bin/python A_data/scripts/3_panel_base_mkt_condition_factors.py --max-lookback 48
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import Config


DEFAULT_SOURCE_PANEL_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_TARGET_PATHS = (
    Config.PANEL_OUTPUT_PATH,
    Config.PANEL_HEATMAP_OUTPUT_PATH,
)
DEFAULT_CHECK_OUTPUT_PATH = (
    Config.A_DATA_ROOT / "output" / "mkt_condition_factors_check.xlsx"
)
DEFAULT_PREVIEW_ROWS = 1000
DEFAULT_MAX_LOOKBACK_MONTHS = 36

# 市态维度与 regime 命名。state 取值 1/-1 对应 P1 脚本写入的编码。
STATE_REGIME_DEFINITIONS = (
    ("mkt_state_hs300", (("hs300up", 1.0), ("hs300down", -1.0))),
    ("mkt_state_style", (("growth", 1.0), ("value", -1.0))),
    ("mkt_state_size", (("large", 1.0), ("small", -1.0))),
    ("mkt_state_indvol", (("highvol", 1.0), ("lowvol", -1.0))),
)
STATE_COLUMNS = tuple(state for state, _ in STATE_REGIME_DEFINITIONS)

# 与 fm_baseline 相同的 5 套 (m, n) 窗口；市态版滚动选月，pairwise 固定为 1。
FACTOR_SPECS = tuple(
    (return_horizon, rank_count)
    for return_horizon, rank_count in Config.PANEL_PAST_RETURN_COMBOS
)
PAIRWISE = 1
MAX_RANK_COUNT = max(rank_count for _, rank_count in FACTOR_SPECS)
RETURN_HORIZONS = tuple(
    sorted({return_horizon for return_horizon, _ in FACTOR_SPECS})
)

# 命中口径与 3_panel_base_winrates_factors.py 的 top50 完全一致：rank > 0.5。
TOP50_THRESHOLD = 0.5
WINRATE_METRIC = "top50"

BOTTOM_TERCILE_CUTOFF = 1 / 3
TOP_TERCILE_CUTOFF = 2 / 3

# 月份 ordinal 的缺失哨兵值，保证 MultiIndex 查找永远落空返回 NaN。
MISSING_ORDINAL = -1

BRUTE_FORCE_SAMPLE_SIZE = 60
BRUTE_FORCE_RANDOM_SEED = 20260702

INSAMPLE_FLAG_COLUMN = "is_insample_future_ret_6m"
MIN_CROSS_SECTION_N = 50


def get_rank_source_column(return_horizon: int) -> str:
    """返回市态月排名查找使用的当月截面排名列。"""
    return f"past_ret_{return_horizon}m_rank_1"


def get_state_fac_column(regime: str, return_horizon: int, rank_count: int) -> str:
    """返回市态排名波动率因子列名。"""
    return (
        f"FAC_rank_vol_{regime}_m{return_horizon}_n{rank_count}_"
        f"pairwise{PAIRWISE}"
    )


def get_state_rank_mean_column(
    regime: str, return_horizon: int, rank_count: int
) -> str:
    """返回市态排名均值列名。"""
    return (
        f"rank_mean_{regime}_m{return_horizon}_n{rank_count}_"
        f"pairwise{PAIRWISE}"
    )


def get_state_median_column(
    regime: str, return_horizon: int, rank_count: int
) -> str:
    """返回市态排名均值中位数二分列名，取值 -2/2。"""
    return "is_median_" + get_state_rank_mean_column(
        regime, return_horizon, rank_count
    )


def get_state_tercile_column(
    regime: str, return_horizon: int, rank_count: int
) -> str:
    """返回市态排名均值三分组列名，取值 1/2/3。"""
    return "is_tercile_" + get_state_rank_mean_column(
        regime, return_horizon, rank_count
    )


def get_state_hitcount_column(
    regime: str, return_horizon: int, rank_count: int
) -> str:
    """返回市态 top50 命中次数列名。"""
    return (
        f"hitcount_{WINRATE_METRIC}_{regime}_m{return_horizon}_n{rank_count}_"
        f"pairwise{PAIRWISE}"
    )


def get_state_hitrate_column(
    regime: str, return_horizon: int, rank_count: int
) -> str:
    """返回市态 top50 命中比例列名。"""
    return (
        f"hitrate_{WINRATE_METRIC}_{regime}_m{return_horizon}_n{rank_count}_"
        f"pairwise{PAIRWISE}"
    )


def get_state_dummy_column(
    regime: str, return_horizon: int, rank_count: int, minimum_hits: int
) -> str:
    """返回市态 top50 累计 dummy 列名，minimum_hits 从 1 到 n。"""
    if minimum_hits < 1:
        raise ValueError("minimum_hits 必须至少为 1。")
    return (
        f"dummy_{WINRATE_METRIC}_{regime}_m{return_horizon}_n{rank_count}_"
        f"hit_above{minimum_hits - 1}_pairwise{PAIRWISE}"
    )


def iter_regimes() -> Iterable[tuple[str, str, float]]:
    """依次给出 (市态列, regime 名, 状态取值)。"""
    for state_column, regimes in STATE_REGIME_DEFINITIONS:
        for regime, state_value in regimes:
            yield state_column, regime, state_value


def get_spec_output_columns(
    regime: str, return_horizon: int, rank_count: int
) -> list[str]:
    """列出一个 regime x (m,n) 组合的全部输出列，顺序固定。"""
    return [
        get_state_fac_column(regime, return_horizon, rank_count),
        get_state_rank_mean_column(regime, return_horizon, rank_count),
        get_state_median_column(regime, return_horizon, rank_count),
        get_state_tercile_column(regime, return_horizon, rank_count),
        get_state_hitcount_column(regime, return_horizon, rank_count),
        get_state_hitrate_column(regime, return_horizon, rank_count),
        *[
            get_state_dummy_column(regime, return_horizon, rank_count, minimum_hits)
            for minimum_hits in range(1, rank_count + 1)
        ],
    ]


def get_owned_output_columns() -> list[str]:
    """列出由本脚本管理的全部字段，便于重复运行时先删除旧结果。"""
    columns: list[str] = []
    for _, regime, _ in iter_regimes():
        for return_horizon, rank_count in FACTOR_SPECS:
            columns.extend(
                get_spec_output_columns(regime, return_horizon, rank_count)
            )
    return columns


def get_legacy_mutually_exclusive_columns() -> list[str]:
    """列出市态旧版 hit0..hitn 互斥 dummy，供写盘时定向清理。"""
    return [
        f"dummy_{WINRATE_METRIC}_{regime}_m{return_horizon}_n{rank_count}_"
        f"hit{hit_k}_pairwise{PAIRWISE}"
        for _, regime, _ in iter_regimes()
        for return_horizon, rank_count in FACTOR_SPECS
        for hit_k in range(rank_count + 1)
    ]


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="为 panel_base 和热力图面板追加市态条件一致性因子。"
    )
    parser.add_argument(
        "--source-panel",
        type=Path,
        default=DEFAULT_SOURCE_PANEL_PATH,
        help="计算因子使用的 panel_base parquet 路径。",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        nargs="+",
        default=list(DEFAULT_TARGET_PATHS),
        help="需要追加因子列的 parquet 面板路径，默认两个正式面板。",
    )
    parser.add_argument(
        "--max-lookback",
        type=int,
        default=DEFAULT_MAX_LOOKBACK_MONTHS,
        help="选取市态月份的最大回看深度（月），默认 36。",
    )
    parser.add_argument(
        "--check-output",
        type=Path,
        default=DEFAULT_CHECK_OUTPUT_PATH,
        help="校验表输出路径。",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=DEFAULT_PREVIEW_ROWS,
        help="预览文件保留的前部行数。",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="只写 parquet，不刷新 Excel 预览。",
    )
    return parser.parse_args()


def read_source_panel(source_panel_path: Path) -> pd.DataFrame:
    """读取计算所需的最小列集合并校验。"""
    if not source_panel_path.exists():
        raise FileNotFoundError(f"面板文件不存在：{source_panel_path}")

    required_columns = [
        Config.COLUMN_IFIND_CODE,
        Config.COLUMN_INVESTMENT_TYPE,
        Config.COLUMN_MONTH_DATE,
        INSAMPLE_FLAG_COLUMN,
        *STATE_COLUMNS,
        *[
            get_rank_source_column(return_horizon)
            for return_horizon in RETURN_HORIZONS
        ],
        *[
            f"FAC_rank_vol_m{return_horizon}_n{rank_count}_pairwise{PAIRWISE}"
            for return_horizon, rank_count in FACTOR_SPECS
        ],
    ]
    schema_names = set(pq.read_schema(source_panel_path).names)
    missing = [
        column for column in required_columns if column not in schema_names
    ]
    if missing:
        raise ValueError(
            f"{source_panel_path} 缺少字段：{missing}；"
            "请先运行 3_panel_base_mkt_condition.py 并确认排名列完整。"
        )

    data = pd.read_parquet(source_panel_path, columns=required_columns)
    data[Config.COLUMN_MONTH_DATE] = pd.to_datetime(
        data[Config.COLUMN_MONTH_DATE], errors="coerce"
    )
    if data[Config.COLUMN_MONTH_DATE].isna().any():
        raise ValueError(f"{source_panel_path} 中存在无法识别的 month_date。")

    key_columns = [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    if data.duplicated(key_columns).any():
        raise ValueError(f"{source_panel_path} 存在重复基金-月份键。")
    return data


def extract_month_state_table(data: pd.DataFrame) -> pd.DataFrame:
    """从面板提取月份到市态的映射，并校验同月取值唯一。"""
    per_month = data.groupby(Config.COLUMN_MONTH_DATE)[list(STATE_COLUMNS)]
    if (per_month.nunique(dropna=True) > 1).any().any():
        raise AssertionError("同一月份的市态取值不唯一，请检查 P1 输出。")

    state_table = per_month.first()
    state_table.index = pd.DatetimeIndex(state_table.index).to_period("M")
    return state_table.sort_index()


def build_regime_month_targets(
    state_series: pd.Series,
    state_value: float,
    max_lookback: int,
) -> pd.DataFrame:
    """为每个月列出截至当月最近 MAX_RANK_COUNT 个指定 regime 月份的 ordinal。

    月份选择只由市场状态决定，与基金数据无关。返回表以月份 ordinal 为索引，
    列 target_1 是最近的 regime 月，target_k 依次向更早排；不足的填哨兵值。
    被选中的月份必须满足 ordinal >= 当月 ordinal - (max_lookback - 1)。
    """
    ordered = state_series.sort_index()
    month_ordinals = ordered.index.asi8

    history: list[int] = []
    rows = np.full(
        (len(ordered), MAX_RANK_COUNT), MISSING_ORDINAL, dtype="int64"
    )
    for row_index, (month_ordinal, value) in enumerate(
        zip(month_ordinals, ordered.to_numpy())
    ):
        if value == state_value:
            history.append(int(month_ordinal))
        earliest_allowed = month_ordinal - (max_lookback - 1)
        eligible = [
            ordinal for ordinal in history[-max_lookback:]
            if ordinal >= earliest_allowed
        ]
        recent = eligible[-MAX_RANK_COUNT:]
        # target_1 放最近的月份：recent 按时间升序，因此反转后从近到远排。
        for position, ordinal in enumerate(reversed(recent)):
            rows[row_index, position] = ordinal

    return pd.DataFrame(
        rows,
        index=pd.Index(month_ordinals, name="month_ordinal"),
        columns=[f"target_{k}" for k in range(1, MAX_RANK_COUNT + 1)],
    )


def build_rank_lookup(
    data: pd.DataFrame, return_horizon: int
) -> pd.Series:
    """构建 (基金, 月份 ordinal) 到当月截面排名的查找序列。"""
    month_ordinals = (
        data[Config.COLUMN_MONTH_DATE].dt.to_period("M").array.asi8
    )
    return pd.Series(
        pd.to_numeric(
            data[get_rank_source_column(return_horizon)], errors="coerce"
        ).to_numpy(),
        index=pd.MultiIndex.from_arrays(
            [data[Config.COLUMN_IFIND_CODE].to_numpy(), month_ordinals],
            names=[Config.COLUMN_IFIND_CODE, "month_ordinal"],
        ),
    )


def collect_state_rank_matrix(
    data: pd.DataFrame,
    rank_lookup: pd.Series,
    month_targets: pd.DataFrame,
) -> np.ndarray:
    """收集每行最近 MAX_RANK_COUNT 个 regime 月份的排名矩阵。

    第 j 列对应 target_{j+1}，即从最近到更早排列。选中月份缺排名时保持 NaN。
    """
    row_month_ordinals = (
        data[Config.COLUMN_MONTH_DATE].dt.to_period("M").array.asi8
    )
    aligned_targets = month_targets.reindex(row_month_ordinals)
    # 面板月份理应全部在市态表覆盖范围内；reindex 落空说明上游月份对不上。
    if aligned_targets.isna().any().any():
        raise AssertionError("存在市态表未覆盖的面板月份。")

    codes = data[Config.COLUMN_IFIND_CODE].to_numpy()
    matrix = np.full((len(data), MAX_RANK_COUNT), np.nan, dtype="float64")
    for column_index in range(MAX_RANK_COUNT):
        target_ordinals = (
            aligned_targets.iloc[:, column_index].to_numpy(dtype="int64")
        )
        lookup_keys = pd.MultiIndex.from_arrays(
            [codes, target_ordinals], names=rank_lookup.index.names
        )
        matrix[:, column_index] = rank_lookup.reindex(lookup_keys).to_numpy()
    return matrix


def compute_group_split_columns(
    data: pd.DataFrame, rank_mean_values: pd.Series
) -> tuple[pd.Series, pd.Series]:
    """按截面百分位生成中位数二分和三分组标记。

    分组边界与 3_panel_base_grouping_factors.py 完全一致。
    """
    group_keys = [
        data[Config.COLUMN_MONTH_DATE],
        data[Config.COLUMN_INVESTMENT_TYPE],
    ]
    cross_section_rank_pct = rank_mean_values.groupby(
        group_keys, sort=False
    ).rank(method="average", pct=True)
    non_missing = rank_mean_values.notna()

    median_values = pd.Series(np.nan, index=data.index, dtype="float64")
    median_values.loc[non_missing & (cross_section_rank_pct <= 0.5)] = -2.0
    median_values.loc[non_missing & (cross_section_rank_pct > 0.5)] = 2.0

    tercile_values = pd.Series(np.nan, index=data.index, dtype="float64")
    tercile_values.loc[non_missing] = 2.0
    tercile_values.loc[
        non_missing & (cross_section_rank_pct <= BOTTOM_TERCILE_CUTOFF)
    ] = 1.0
    tercile_values.loc[
        non_missing & (cross_section_rank_pct > TOP_TERCILE_CUTOFF)
    ] = 3.0
    return median_values, tercile_values


def build_state_factor_columns(
    data: pd.DataFrame, max_lookback: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """计算全部市态条件因子列，并返回月度选月诊断表。

    返回值第一项是与 data 行对齐的新列表；第二项是每个 regime x n 的
    月度目标可用性诊断（供校验表使用）。
    """
    state_table = extract_month_state_table(data)
    rank_lookups = {
        return_horizon: build_rank_lookup(data, return_horizon)
        for return_horizon in RETURN_HORIZONS
    }

    new_columns: dict[str, pd.Series] = {}
    diagnostics_rows: list[dict[str, object]] = []

    for state_column, regime, state_value in iter_regimes():
        month_targets = build_regime_month_targets(
            state_table[state_column], state_value, max_lookback
        )
        matrices = {
            return_horizon: collect_state_rank_matrix(
                data, rank_lookups[return_horizon], month_targets
            )
            for return_horizon in RETURN_HORIZONS
        }

        target_matrix = month_targets.to_numpy()
        month_index = month_targets.index.to_numpy()
        for return_horizon, rank_count in FACTOR_SPECS:
            selected = matrices[return_horizon][:, :rank_count]
            full_window = np.isfinite(selected).all(axis=1)

            fac_values = pd.Series(np.nan, index=data.index, dtype="float64")
            fac_values.loc[full_window] = 1.0 - np.std(
                selected[full_window], axis=1, ddof=Config.RANK_VOL_DDOF
            )
            rank_mean_values = pd.Series(
                np.nan, index=data.index, dtype="float64"
            )
            rank_mean_values.loc[full_window] = selected[full_window].mean(
                axis=1
            )
            median_values, tercile_values = compute_group_split_columns(
                data, rank_mean_values
            )

            hit_flags = selected > TOP50_THRESHOLD
            hitcount_values = pd.Series(
                np.nan, index=data.index, dtype="float64"
            )
            hitcount_values.loc[full_window] = hit_flags[full_window].sum(
                axis=1
            )
            hitrate_values = hitcount_values / rank_count

            new_columns[
                get_state_fac_column(regime, return_horizon, rank_count)
            ] = fac_values
            new_columns[
                get_state_rank_mean_column(regime, return_horizon, rank_count)
            ] = rank_mean_values
            new_columns[
                get_state_median_column(regime, return_horizon, rank_count)
            ] = median_values
            new_columns[
                get_state_tercile_column(regime, return_horizon, rank_count)
            ] = tercile_values
            new_columns[
                get_state_hitcount_column(regime, return_horizon, rank_count)
            ] = hitcount_values
            new_columns[
                get_state_hitrate_column(regime, return_horizon, rank_count)
            ] = hitrate_values
            for minimum_hits in range(1, rank_count + 1):
                dummy_values = pd.Series(
                    np.nan, index=data.index, dtype="float64"
                )
                dummy_values.loc[full_window] = (
                    hitcount_values.loc[full_window] >= minimum_hits
                ).astype("float64")
                new_columns[
                    get_state_dummy_column(
                        regime, return_horizon, rank_count, minimum_hits
                    )
                ] = dummy_values

            # 月度诊断：第 n 个目标月是否存在，以及实际回看跨度。
            nth_target = target_matrix[:, rank_count - 1]
            has_targets = nth_target != MISSING_ORDINAL
            spans = np.where(
                has_targets, month_index - nth_target + 1, np.nan
            )
            diagnostics_rows.append(
                {
                    "regime": regime,
                    "return_horizon_m": return_horizon,
                    "rank_count_n": rank_count,
                    "months_total": len(month_targets),
                    "months_with_full_targets": int(has_targets.sum()),
                    "months_missing_targets": int((~has_targets).sum()),
                    "mean_lookback_span": float(np.nanmean(spans)),
                    "max_lookback_span": (
                        float(np.nanmax(spans)) if has_targets.any() else np.nan
                    ),
                }
            )

    return (
        pd.DataFrame(new_columns, index=data.index),
        pd.DataFrame(diagnostics_rows),
    )


def brute_force_check(
    data: pd.DataFrame,
    factor_columns: pd.DataFrame,
    max_lookback: int,
) -> int:
    """对随机抽样的行用纯 Python 逻辑复算因子，校验向量化实现。

    返回实际复算并通过的行数。抽样只覆盖 FAC 非缺失的行；对每行独立地
    重新选月、查排名、算波动率/均值/命中数，与向量化结果逐一比对。
    """
    state_table = extract_month_state_table(data)
    rank_lookups = {
        return_horizon: build_rank_lookup(data, return_horizon)
        for return_horizon in RETURN_HORIZONS
    }
    state_months: dict[tuple[str, float], list[int]] = {}
    for state_column, regime, state_value in iter_regimes():
        series = state_table[state_column]
        state_months[(regime, state_value)] = [
            int(ordinal)
            for ordinal, value in zip(series.index.asi8, series.to_numpy())
            if value == state_value
        ]

    rng = np.random.default_rng(BRUTE_FORCE_RANDOM_SEED)
    checked = 0
    for state_column, regime, state_value in iter_regimes():
        for return_horizon, rank_count in FACTOR_SPECS:
            fac_column = get_state_fac_column(
                regime, return_horizon, rank_count
            )
            candidates = np.flatnonzero(
                factor_columns[fac_column].notna().to_numpy()
            )
            if len(candidates) == 0:
                raise AssertionError(f"{fac_column} 没有任何非缺失值。")
            sample_size = min(
                BRUTE_FORCE_SAMPLE_SIZE // len(FACTOR_SPECS) + 1,
                len(candidates),
            )
            sampled = rng.choice(candidates, size=sample_size, replace=False)
            for row_position in sampled:
                row = data.iloc[row_position]
                month_ordinal = int(
                    pd.Period(row[Config.COLUMN_MONTH_DATE], freq="M").ordinal
                )
                earliest_allowed = month_ordinal - (max_lookback - 1)
                eligible = [
                    ordinal
                    for ordinal in state_months[(regime, state_value)]
                    if earliest_allowed <= ordinal <= month_ordinal
                ]
                selected_months = eligible[-rank_count:]
                if len(selected_months) < rank_count:
                    raise AssertionError(
                        f"{fac_column} 行 {row_position} 市态月不足却有非缺失值。"
                    )
                ranks = [
                    rank_lookups[return_horizon].get(
                        (row[Config.COLUMN_IFIND_CODE], ordinal), np.nan
                    )
                    for ordinal in selected_months
                ]
                if not np.isfinite(ranks).all():
                    raise AssertionError(
                        f"{fac_column} 行 {row_position} 排名缺失却有非缺失值。"
                    )
                expected_fac = 1.0 - float(
                    np.std(ranks, ddof=Config.RANK_VOL_DDOF)
                )
                expected_mean = float(np.mean(ranks))
                expected_hitcount = float(
                    sum(rank > TOP50_THRESHOLD for rank in ranks)
                )
                actual_fac = factor_columns.iloc[row_position][fac_column]
                actual_mean = factor_columns.iloc[row_position][
                    get_state_rank_mean_column(
                        regime, return_horizon, rank_count
                    )
                ]
                actual_hitcount = factor_columns.iloc[row_position][
                    get_state_hitcount_column(
                        regime, return_horizon, rank_count
                    )
                ]
                if not (
                    np.isclose(actual_fac, expected_fac)
                    and np.isclose(actual_mean, expected_mean)
                    and np.isclose(actual_hitcount, expected_hitcount)
                ):
                    raise AssertionError(
                        f"{fac_column} 行 {row_position} 暴力复算不一致："
                        f"FAC {actual_fac} vs {expected_fac}，"
                        f"mean {actual_mean} vs {expected_mean}，"
                        f"hitcount {actual_hitcount} vs {expected_hitcount}。"
                    )
                checked += 1
    return checked


def validate_factor_columns(
    data: pd.DataFrame, factor_columns: pd.DataFrame
) -> None:
    """校验取值范围、缺失一致性和累计 dummy 的嵌套关系。"""
    for state_column, regime, _ in iter_regimes():
        for return_horizon, rank_count in FACTOR_SPECS:
            fac = factor_columns[
                get_state_fac_column(regime, return_horizon, rank_count)
            ]
            rank_mean = factor_columns[
                get_state_rank_mean_column(regime, return_horizon, rank_count)
            ]
            median_flag = factor_columns[
                get_state_median_column(regime, return_horizon, rank_count)
            ]
            tercile_flag = factor_columns[
                get_state_tercile_column(regime, return_horizon, rank_count)
            ]
            hitcount = factor_columns[
                get_state_hitcount_column(regime, return_horizon, rank_count)
            ]
            hitrate = factor_columns[
                get_state_hitrate_column(regime, return_horizon, rank_count)
            ]

            if (fac.notna() != rank_mean.notna()).any():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的 FAC 与"
                    " rank_mean 缺失模式不一致。"
                )
            if not rank_mean.dropna().between(0, 1).all():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的 rank_mean"
                    " 超出 [0,1]。"
                )
            if (fac.dropna() > 1).any():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的 FAC 大于 1。"
                )
            if not median_flag.dropna().isin([-2.0, 2.0]).all():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的中位数标记"
                    " 出现 -2/2 之外的值。"
                )
            if not tercile_flag.dropna().isin([1.0, 2.0, 3.0]).all():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的三分组标记"
                    " 出现 1/2/3 之外的值。"
                )
            if (rank_mean.isna() & median_flag.notna()).any() or (
                rank_mean.isna() & tercile_flag.notna()
            ).any():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 在 rank_mean"
                    " 缺失时分组标记非缺失。"
                )
            if not hitcount.dropna().between(0, rank_count).all():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的 hitcount"
                    " 超出 [0,n]。"
                )
            expected_hitrate = hitcount / rank_count
            if not np.allclose(
                hitrate.to_numpy(),
                expected_hitrate.to_numpy(),
                equal_nan=True,
            ):
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的 hitrate"
                    " 与 hitcount/n 不一致。"
                )

            dummy_frame = factor_columns[
                [
                    get_state_dummy_column(
                        regime, return_horizon, rank_count, minimum_hits
                    )
                    for minimum_hits in range(1, rank_count + 1)
                ]
            ]
            valid_rows = hitcount.notna()
            for minimum_hits, column in enumerate(dummy_frame.columns, start=1):
                expected = (hitcount.loc[valid_rows] >= minimum_hits).astype("float64")
                if not np.array_equal(dummy_frame.loc[valid_rows, column], expected):
                    raise AssertionError(
                        f"{column} 与 hitcount >= {minimum_hits} 不一致。"
                    )
            if (dummy_frame.loc[valid_rows].diff(axis=1).iloc[:, 1:] > 0).any().any():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 的累计 dummy"
                    " 不满足嵌套单调性。"
                )
            if dummy_frame.loc[~valid_rows].notna().any().any():
                raise AssertionError(
                    f"{regime} m{return_horizon} n{rank_count} 在 hitcount"
                    " 缺失时 dummy 非缺失。"
                )


def make_temporary_path(target_path: Path) -> Path:
    """在目标目录创建同后缀临时路径，便于验证后原子替换。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target_path.stem}_",
        suffix=target_path.suffix,
        dir=target_path.parent,
    )
    os.close(descriptor)
    return Path(temporary_name)


def get_default_preview_path(output_path: Path) -> Path:
    """根据 parquet 输出路径推导 Excel 预览路径。"""
    return output_path.with_name(output_path.stem + "_preview.xlsx")


def append_factors_to_panel(
    panel_path: Path,
    source_keys: pd.MultiIndex,
    factor_columns: pd.DataFrame,
    preview_rows: int,
    write_preview: bool,
) -> dict[str, object]:
    """把因子列按基金-月份主键对齐后追加到单个 parquet 面板。"""
    keys = pd.read_parquet(
        panel_path,
        columns=[Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE],
    )
    target_index = pd.MultiIndex.from_arrays(
        [
            keys[Config.COLUMN_IFIND_CODE].to_numpy(),
            pd.to_datetime(keys[Config.COLUMN_MONTH_DATE])
            .dt.to_period("M")
            .array.asi8,
        ],
        names=source_keys.names,
    )
    if target_index.duplicated().any():
        raise AssertionError(f"{panel_path} 存在重复基金-月份键。")
    if len(target_index) != len(source_keys):
        raise AssertionError(
            f"{panel_path} 行数与来源面板不一致，无法对齐因子列。"
        )

    aligned = factor_columns.set_axis(source_keys, axis=0).reindex(
        target_index
    )
    # 键集合必须完全一致：reindex 落空会产生整行 NaN，用 FAC 全缺失来兜底
    # 检查会误伤真实缺失，这里直接比较集合差。
    missing_keys = target_index.difference(source_keys)
    if len(missing_keys) > 0:
        raise AssertionError(
            f"{panel_path} 存在来源面板没有的基金-月份键，例如："
            f"{list(missing_keys[:5])}"
        )

    table = pq.read_table(panel_path)
    columns_to_replace = {
        *factor_columns.columns,
        *get_legacy_mutually_exclusive_columns(),
    }
    base_names = [
        name
        for name in table.column_names
        if name not in columns_to_replace
    ]
    replaced = sorted(set(table.column_names) - set(base_names))
    table = table.select(base_names)
    for column in factor_columns.columns:
        table = table.append_column(
            column, pa.array(aligned[column].to_numpy(), type=pa.float64())
        )

    temporary_output = make_temporary_path(panel_path)
    preview_path = get_default_preview_path(panel_path) if write_preview else None
    temporary_preview = (
        make_temporary_path(preview_path) if preview_path is not None else None
    )
    try:
        pq.write_table(table, temporary_output)
        written_metadata = pq.ParquetFile(temporary_output).metadata
        if written_metadata.num_rows != table.num_rows:
            raise AssertionError("临时 parquet 回读后的行数不一致。")
        if written_metadata.num_columns != table.num_columns:
            raise AssertionError("临时 parquet 回读后的列数不一致。")

        if temporary_preview is not None:
            preview = table.slice(0, preview_rows).to_pandas()
            preview.to_excel(temporary_preview, index=False)
            preview_check = pd.read_excel(temporary_preview, nrows=5)
            if list(preview_check.columns) != list(preview.columns):
                raise AssertionError("临时 Excel 预览的字段顺序不一致。")

        os.replace(temporary_output, panel_path)
        if temporary_preview is not None and preview_path is not None:
            os.replace(temporary_preview, preview_path)
    finally:
        temporary_output.unlink(missing_ok=True)
        if temporary_preview is not None:
            temporary_preview.unlink(missing_ok=True)

    return {
        "panel_path": panel_path,
        "preview_path": preview_path,
        "row_count": int(table.num_rows),
        "column_count": int(table.num_columns),
        "replaced_existing_columns": len(replaced),
    }


def build_factor_summary(
    data: pd.DataFrame, factor_columns: pd.DataFrame
) -> pd.DataFrame:
    """汇总每个 regime x (m,n) 的覆盖率、有效月份数和与普通因子的相关性。"""
    month_periods = data[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    insample = data[INSAMPLE_FLAG_COLUMN] == 1

    summary_rows = []
    for state_column, regime, _ in iter_regimes():
        for return_horizon, rank_count in FACTOR_SPECS:
            fac_column = get_state_fac_column(
                regime, return_horizon, rank_count
            )
            plain_fac_column = (
                f"FAC_rank_vol_m{return_horizon}_n{rank_count}_"
                f"pairwise{PAIRWISE}"
            )
            fac = factor_columns[fac_column]
            plain_fac = pd.to_numeric(data[plain_fac_column], errors="coerce")

            insample_counts = (
                fac[insample]
                .notna()
                .groupby(month_periods[insample])
                .sum()
            )
            effective_months = int(
                (insample_counts >= MIN_CROSS_SECTION_N).sum()
            )
            both_valid = fac.notna() & plain_fac.notna()
            correlation = (
                float(fac[both_valid].corr(plain_fac[both_valid]))
                if both_valid.sum() > 2
                else np.nan
            )
            summary_rows.append(
                {
                    "regime": regime,
                    "return_horizon_m": return_horizon,
                    "rank_count_n": rank_count,
                    "fac_column": fac_column,
                    "non_null_rows": int(fac.notna().sum()),
                    "non_null_rows_insample": int(fac[insample].notna().sum()),
                    "effective_fm_months_ge50": effective_months,
                    "corr_with_plain_fac": correlation,
                    "hitrate_non_null_rows": int(
                        factor_columns[
                            get_state_hitrate_column(
                                regime, return_horizon, rank_count
                            )
                        ]
                        .notna()
                        .sum()
                    ),
                }
            )
    return pd.DataFrame(summary_rows)


def write_check_workbook(
    factor_summary: pd.DataFrame,
    month_diagnostics: pd.DataFrame,
    check_output_path: Path,
) -> None:
    """把因子汇总和月度选月诊断写成 Excel 工作簿。"""
    temporary_check = make_temporary_path(check_output_path)
    try:
        with pd.ExcelWriter(temporary_check) as writer:
            factor_summary.to_excel(
                writer, sheet_name="factor_summary", index=False
            )
            month_diagnostics.to_excel(
                writer, sheet_name="month_target_diagnostics", index=False
            )
        read_back = pd.read_excel(temporary_check, sheet_name="factor_summary")
        if len(read_back) != len(factor_summary):
            raise AssertionError("校验表回读后的行数不一致。")
        os.replace(temporary_check, check_output_path)
    finally:
        temporary_check.unlink(missing_ok=True)


def generate_market_condition_factors(
    source_panel_path: Path = DEFAULT_SOURCE_PANEL_PATH,
    target_paths: Iterable[Path] = DEFAULT_TARGET_PATHS,
    max_lookback: int = DEFAULT_MAX_LOOKBACK_MONTHS,
    check_output_path: Path = DEFAULT_CHECK_OUTPUT_PATH,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
    write_preview: bool = True,
) -> dict[str, object]:
    """计算市态条件因子、校验并写入全部目标面板。"""
    if preview_rows <= 0:
        raise ValueError("preview_rows 必须是正整数。")
    if max_lookback < MAX_RANK_COUNT:
        raise ValueError(
            f"max_lookback 不得小于最大排名期数 {MAX_RANK_COUNT}。"
        )

    data = read_source_panel(source_panel_path)
    factor_columns, month_diagnostics = build_state_factor_columns(
        data, max_lookback
    )
    if list(factor_columns.columns) != get_owned_output_columns():
        raise AssertionError("因子列集合与登记的输出列清单不一致。")

    validate_factor_columns(data, factor_columns)
    checked_rows = brute_force_check(data, factor_columns, max_lookback)

    source_keys = pd.MultiIndex.from_arrays(
        [
            data[Config.COLUMN_IFIND_CODE].to_numpy(),
            data[Config.COLUMN_MONTH_DATE].dt.to_period("M").array.asi8,
        ],
        names=[Config.COLUMN_IFIND_CODE, "month_ordinal"],
    )
    panel_summaries = [
        append_factors_to_panel(
            Path(panel_path),
            source_keys,
            factor_columns,
            preview_rows=preview_rows,
            write_preview=write_preview,
        )
        for panel_path in target_paths
    ]

    factor_summary = build_factor_summary(data, factor_columns)
    write_check_workbook(
        factor_summary, month_diagnostics, check_output_path
    )
    return {
        "panel_summaries": panel_summaries,
        "factor_summary": factor_summary,
        "month_diagnostics": month_diagnostics,
        "check_output_path": check_output_path,
        "max_lookback": max_lookback,
        "brute_force_checked_rows": checked_rows,
        "added_column_count": len(factor_columns.columns),
    }


def print_summary(result: dict[str, object]) -> None:
    """打印面板写入结果和因子覆盖摘要。"""
    print(f"最大回看深度：{result['max_lookback']} 个月")
    print(f"新增列数：{result['added_column_count']}")
    print(f"暴力复算通过行数：{result['brute_force_checked_rows']}")
    for panel_summary in result["panel_summaries"]:
        print(f"面板：{panel_summary['panel_path']}")
        if panel_summary["preview_path"] is not None:
            print(f"  预览：{panel_summary['preview_path']}")
        if panel_summary["replaced_existing_columns"]:
            print(
                "  重复运行，已替换旧因子列数："
                f"{panel_summary['replaced_existing_columns']}"
            )
        print(
            f"  行数：{panel_summary['row_count']:,}；"
            f"列数：{panel_summary['column_count']:,}"
        )
    print(f"校验表：{result['check_output_path']}")

    factor_summary = result["factor_summary"]
    aggregated = (
        factor_summary.groupby("regime")
        .agg(
            fac_non_null_rows=("non_null_rows", "sum"),
            min_effective_fm_months=("effective_fm_months_ge50", "min"),
            max_effective_fm_months=("effective_fm_months_ge50", "max"),
            mean_corr_with_plain_fac=("corr_with_plain_fac", "mean"),
        )
        .reset_index()
    )
    print(aggregated.to_string(index=False))


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    result = generate_market_condition_factors(
        source_panel_path=args.source_panel,
        target_paths=args.targets,
        max_lookback=args.max_lookback,
        check_output_path=args.check_output,
        preview_rows=args.preview_rows,
        write_preview=not args.no_preview,
    )
    print_summary(result)


if __name__ == "__main__":
    main()
