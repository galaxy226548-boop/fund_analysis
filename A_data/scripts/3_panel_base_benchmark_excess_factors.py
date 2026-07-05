"""为 ``panel_base`` 和热力图面板追加基准超额收益版一致性因子。

默认读取并覆盖：

    A_data/output/panel_base.parquet
    A_data/output/panel_base_heatmap_m1_12_n1_12.parquet

以及对应的 *_preview.xlsx 预览文件。

课题背景（方案乙，2026-07 与使用者确认）：普通 ``FAC_rank_vol_m{m}_n{n}``
用原始 m 月累计收益在「月份 x 投资类型」截面内排名；本脚本把排名输入换成
「基金 m 月收益 - 该基金自身基准指数同期收益」（基准超额收益），截面分组
保持「月份 x 投资类型」不变。目的：剥离基准风格暴露对排名一致性的污染，
衡量更接近经理技能的一致性。

基准收益口径：
- 基准指数净值来自 A_data/data/iFind_API/ 下 4 个宽表（偏股混合/普通股票
  x 存续/已到期），每行一只基金，列为月末日期；
- 净值为 0 表示未成立/缺失，一律按缺失处理；
- 基准 m 月收益 = NAV(e)/NAV(e-m) - 1（简单收益，与 PANEL_RETURN_TYPE 一致），
  任一端点缺失（含中途断档）时记缺失，不填补；
- 窗口 i 的基准收益终点月为 e = t - (i-1)，与 past_ret_{m}m_{i} 的窗口对齐。

排名口径：与 3_generate_panel_base.py 完全一致——窗口 i 的超额收益在当前
月份 t 的「month_date x investment_type」截面内排名（method="average"、
pct=True），资格 = is_sample & match_is_sample_past_ret_{m}m_{i} & 超额非缺失。
与普通版的唯一差别：排名输入是超额收益，且基准收益缺失的基金-月退出该
截面分母（覆盖率约 97%）。

按 5 套 baseline 窗口规格 (m,n) = (3,6)/(6,3)/(6,6)/(6,12)/(12,6) 生成列族：

- ``FAC_rank_vol_bmk_m{m}_n{n}_pairwise1``：1 - n 个超额排名的标准差（ddof=1）；
- ``rank_mean_bmk_m{m}_n{n}_pairwise1``：n 个超额排名的均值；
- ``is_median_rank_mean_bmk_...`` / ``is_tercile_rank_mean_bmk_...``：
  按 month_date x investment_type 截面对超额排名均值做二分/三分组，边界与
  ``3_panel_base_grouping_factors.py`` 完全一致（<=0.5 记 -2、>0.5 记 2；
  <=1/3 记 1、中间记 2、>2/3 记 3）；
- ``hitcount_top50_bmk_...`` / ``hitrate_top50_bmk_...`` 与累计
  ``dummy_top50_bmk_m{m}_n{n}_hit_above{0..n-1}_pairwise1``：命中口径与
  ``3_panel_base_winrates_factors.py`` 一致（rank > 0.5 记命中，累计编码）。

同时追加两列分类标注（均为每只基金一个常量，不影响排名截面）：

- ``objective_class``：投资目标分类代码 1/2/3，来自 iFind 投资目标表，
  供后续异质性分析使用；
- ``as_绝对收益类``：0/1 dummy（objective_class==1 记 1），供 fm_bmk_objctrl
  等模型作控制变量；命名对齐现有 ``as_偏股混合型基金`` 风格。

注：与使用者确认的结论——分类代码 2（相对市场类）并入代码 3 处理，且本
脚本对全部基金统一用各自基准指数（.BI）计算超额。

同时输出校验表：

    A_data/output/benchmark_excess_factors_check.xlsx

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_benchmark_excess_factors.py
"""

from __future__ import annotations

import argparse
import datetime
import os
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.stats import rankdata

import Config


DEFAULT_SOURCE_PANEL_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_TARGET_PATHS = (
    Config.PANEL_OUTPUT_PATH,
    Config.PANEL_HEATMAP_OUTPUT_PATH,
)
DEFAULT_CHECK_OUTPUT_PATH = (
    Config.A_DATA_ROOT / "output" / "benchmark_excess_factors_check.xlsx"
)
DEFAULT_PREVIEW_ROWS = 1000

# 基准指数净值宽表（0 视为缺失）。
BENCHMARK_NAV_PATHS = (
    Config.A_DATA_ROOT / "data" / "iFind_API" / "iFind偏股混合型基金基准指数净值变化.xlsx",
    Config.A_DATA_ROOT / "data" / "iFind_API" / "iFind偏股混合型已到期基金基准指数净值变化.xlsx",
    Config.A_DATA_ROOT / "data" / "iFind_API" / "iFind普通股票型基金基准指数净值变化.xlsx",
    Config.A_DATA_ROOT / "data" / "iFind_API" / "iFind普通股票型已到期基金基准指数净值变化.xlsx",
)
BENCHMARK_CODE_COLUMN = "证券代码"

# 投资目标分类表（objective_class 数据源）。表尾有"数据来源"注脚行，
# 以分类代码为 NaN 识别并剔除。
OBJECTIVE_TABLE_PATHS = (
    Config.A_DATA_ROOT
    / "prepared_data" / "iFind_terminal_fund_center" / "iFind偏股混合型基金投资目标.xlsx",
    Config.A_DATA_ROOT
    / "prepared_data" / "iFind_terminal_fund_center" / "iFind普通股票型基金投资目标.xlsx",
)
OBJECTIVE_CODE_COLUMN = "证券代码"
OBJECTIVE_CLASS_COLUMN_SOURCE = "投资目标分类代码"
OBJECTIVE_CLASS_COLUMN = "objective_class"
OBJECTIVE_ABS_DUMMY_COLUMN = "as_绝对收益类"

# 与 fm_baseline 相同的 5 套 (m, n) 窗口，pairwise 固定为 1。
FACTOR_SPECS = tuple(
    (return_horizon, rank_count)
    for return_horizon, rank_count in Config.PANEL_PAST_RETURN_COMBOS
)
PAIRWISE = 1
RETURN_HORIZONS = tuple(
    sorted({return_horizon for return_horizon, _ in FACTOR_SPECS})
)
# 每个收益期限需要的最大窗口期数（决定要读多少列、算多少个超额排名）。
MAX_RANK_COUNT_BY_HORIZON = {
    return_horizon: max(
        rank_count
        for horizon, rank_count in FACTOR_SPECS
        if horizon == return_horizon
    )
    for return_horizon in RETURN_HORIZONS
}

# 命中口径与 3_panel_base_winrates_factors.py 的 top50 完全一致：rank > 0.5。
TOP50_THRESHOLD = 0.5
WINRATE_METRIC = "top50"
FACTOR_TAG = "bmk"

BOTTOM_TERCILE_CUTOFF = 1 / 3
TOP_TERCILE_CUTOFF = 2 / 3

BRUTE_FORCE_SAMPLE_SIZE = 60
BRUTE_FORCE_RANDOM_SEED = 20260702

INSAMPLE_FLAG_COLUMN = "is_insample_future_ret_6m"
MIN_CROSS_SECTION_N = 50


def get_past_return_column(return_horizon: int, window_index: int) -> str:
    """返回 pairwise=1 的过去收益列名。"""
    return f"past_ret_{return_horizon}m_{window_index}"


def get_past_match_column(return_horizon: int, window_index: int) -> str:
    """返回过去收益窗口的样本匹配标签列名。"""
    return f"match_is_sample_past_ret_{return_horizon}m_{window_index}"


def get_plain_fac_column(return_horizon: int, rank_count: int) -> str:
    """返回普通（非超额）FAC 列名，供校验表对比相关性。"""
    return f"FAC_rank_vol_m{return_horizon}_n{rank_count}_pairwise{PAIRWISE}"


def get_bmk_fac_column(return_horizon: int, rank_count: int) -> str:
    """返回基准超额排名波动率因子列名。"""
    return (
        f"FAC_rank_vol_{FACTOR_TAG}_m{return_horizon}_n{rank_count}_"
        f"pairwise{PAIRWISE}"
    )


def get_bmk_rank_mean_column(return_horizon: int, rank_count: int) -> str:
    """返回基准超额排名均值列名。"""
    return (
        f"rank_mean_{FACTOR_TAG}_m{return_horizon}_n{rank_count}_"
        f"pairwise{PAIRWISE}"
    )


def get_bmk_median_column(return_horizon: int, rank_count: int) -> str:
    """返回超额排名均值中位数二分列名，取值 -2/2。"""
    return "is_median_" + get_bmk_rank_mean_column(return_horizon, rank_count)


def get_bmk_tercile_column(return_horizon: int, rank_count: int) -> str:
    """返回超额排名均值三分组列名，取值 1/2/3。"""
    return "is_tercile_" + get_bmk_rank_mean_column(return_horizon, rank_count)


def get_bmk_hitcount_column(return_horizon: int, rank_count: int) -> str:
    """返回超额排名 top50 命中次数列名。"""
    return (
        f"hitcount_{WINRATE_METRIC}_{FACTOR_TAG}_m{return_horizon}_"
        f"n{rank_count}_pairwise{PAIRWISE}"
    )


def get_bmk_hitrate_column(return_horizon: int, rank_count: int) -> str:
    """返回超额排名 top50 命中比例列名。"""
    return (
        f"hitrate_{WINRATE_METRIC}_{FACTOR_TAG}_m{return_horizon}_"
        f"n{rank_count}_pairwise{PAIRWISE}"
    )


def get_bmk_dummy_column(
    return_horizon: int, rank_count: int, minimum_hits: int
) -> str:
    """返回超额排名 top50 累计 dummy 列名，minimum_hits 从 1 到 n。

    列名沿用现有 ``hit_above{k-1}`` 累计编码约定。
    """
    if minimum_hits < 1:
        raise ValueError("minimum_hits 必须至少为 1。")
    return (
        f"dummy_{WINRATE_METRIC}_{FACTOR_TAG}_m{return_horizon}_"
        f"n{rank_count}_hit_above{minimum_hits - 1}_pairwise{PAIRWISE}"
    )


def get_spec_output_columns(return_horizon: int, rank_count: int) -> list[str]:
    """列出一个 (m,n) 组合的全部输出列，顺序固定。"""
    return [
        get_bmk_fac_column(return_horizon, rank_count),
        get_bmk_rank_mean_column(return_horizon, rank_count),
        get_bmk_median_column(return_horizon, rank_count),
        get_bmk_tercile_column(return_horizon, rank_count),
        get_bmk_hitcount_column(return_horizon, rank_count),
        get_bmk_hitrate_column(return_horizon, rank_count),
        *[
            get_bmk_dummy_column(return_horizon, rank_count, minimum_hits)
            for minimum_hits in range(1, rank_count + 1)
        ],
    ]


def get_owned_output_columns() -> list[str]:
    """列出由本脚本管理的全部字段，便于重复运行时先删除旧结果。"""
    columns: list[str] = [OBJECTIVE_CLASS_COLUMN, OBJECTIVE_ABS_DUMMY_COLUMN]
    for return_horizon, rank_count in FACTOR_SPECS:
        columns.extend(get_spec_output_columns(return_horizon, rank_count))
    return columns


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="为 panel_base 和热力图面板追加基准超额收益版一致性因子。"
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


def read_benchmark_nav_matrix() -> pd.DataFrame:
    """读取 4 个基准净值宽表并合成 基金 x 月份 的净值矩阵。

    - 行索引为基金证券代码（与面板 ifind_code 同格式）；
    - 列为月份 Period，要求连续且各文件间无重复基金；
    - 0 值一律替换为 NaN（未成立/缺失）。
    """
    matrices = []
    for path in BENCHMARK_NAV_PATHS:
        if not path.exists():
            raise FileNotFoundError(f"基准净值文件不存在：{path}")
        frame = pd.read_excel(path)
        date_columns = [
            column
            for column in frame.columns
            if isinstance(column, datetime.datetime)
        ]
        if not date_columns:
            raise ValueError(f"{path} 中没有识别到日期列。")
        matrix = (
            frame.set_index(BENCHMARK_CODE_COLUMN)[date_columns]
            .apply(pd.to_numeric, errors="coerce")
        )
        matrix.columns = pd.PeriodIndex(
            [pd.Period(column, freq="M") for column in date_columns], freq="M"
        )
        matrices.append(matrix)

    combined = pd.concat(matrices)
    duplicated = combined.index.duplicated(keep=False)
    if duplicated.any():
        raise AssertionError(
            "基准净值文件间存在重复基金代码，例如："
            f"{sorted(set(combined.index[duplicated]))[:5]}"
        )
    combined = combined.replace(0, np.nan).sort_index(axis=1)

    month_ordinals = combined.columns.asi8
    if not ((month_ordinals[1:] - month_ordinals[:-1]) == 1).all():
        raise AssertionError("基准净值月份网格不连续。")
    return combined


def build_benchmark_return_lookup(
    benchmark_nav: pd.DataFrame, return_horizon: int
) -> pd.Series:
    """构建 (基金, 月份 ordinal) 到基准 m 月收益的查找序列。

    收益 = NAV(e)/NAV(e-m) - 1；任一端点缺失时为 NaN（断档不填补）。
    """
    returns = benchmark_nav / benchmark_nav.shift(return_horizon, axis=1) - 1.0
    stacked = returns.stack()
    return pd.Series(
        stacked.to_numpy(),
        index=pd.MultiIndex.from_arrays(
            [
                stacked.index.get_level_values(0).to_numpy(),
                stacked.index.get_level_values(1).asi8,
            ],
            names=[Config.COLUMN_IFIND_CODE, "month_ordinal"],
        ),
    )


def read_objective_class_mapping() -> pd.Series:
    """读取投资目标分类映射：基金代码 -> 分类代码 1/2/3。"""
    frames = []
    for path in OBJECTIVE_TABLE_PATHS:
        if not path.exists():
            raise FileNotFoundError(f"投资目标表不存在：{path}")
        frames.append(
            pd.read_excel(
                path,
                usecols=[OBJECTIVE_CODE_COLUMN, OBJECTIVE_CLASS_COLUMN_SOURCE],
            )
        )
    combined = pd.concat(frames, ignore_index=True)
    # 表尾注脚行的分类代码为 NaN，剔除后不应再有缺失。
    combined = combined.dropna(subset=[OBJECTIVE_CLASS_COLUMN_SOURCE])
    if combined[OBJECTIVE_CODE_COLUMN].duplicated().any():
        raise AssertionError("投资目标表存在重复基金代码。")
    mapping = combined.set_index(OBJECTIVE_CODE_COLUMN)[
        OBJECTIVE_CLASS_COLUMN_SOURCE
    ].astype("float64")
    if not mapping.isin([1.0, 2.0, 3.0]).all():
        raise AssertionError("投资目标分类代码出现 1/2/3 之外的值。")
    return mapping


def read_source_panel(source_panel_path: Path) -> pd.DataFrame:
    """读取计算所需的最小列集合并校验。"""
    if not source_panel_path.exists():
        raise FileNotFoundError(f"面板文件不存在：{source_panel_path}")

    required_columns = [
        Config.COLUMN_IFIND_CODE,
        Config.COLUMN_INVESTMENT_TYPE,
        Config.COLUMN_MONTH_DATE,
        Config.COLUMN_IS_SAMPLE,
        INSAMPLE_FLAG_COLUMN,
        *[
            get_plain_fac_column(return_horizon, rank_count)
            for return_horizon, rank_count in FACTOR_SPECS
        ],
    ]
    for return_horizon in RETURN_HORIZONS:
        for window_index in range(
            1, MAX_RANK_COUNT_BY_HORIZON[return_horizon] + 1
        ):
            required_columns.append(
                get_past_return_column(return_horizon, window_index)
            )
            required_columns.append(
                get_past_match_column(return_horizon, window_index)
            )

    schema_names = set(pq.read_schema(source_panel_path).names)
    missing = [
        column for column in required_columns if column not in schema_names
    ]
    if missing:
        raise ValueError(f"{source_panel_path} 缺少字段：{missing}")

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


def compute_excess_rank_columns(
    data: pd.DataFrame, benchmark_nav: pd.DataFrame
) -> tuple[dict[tuple[int, int], pd.Series], pd.DataFrame]:
    """计算每个 (m, 窗口 i) 的基准超额收益截面排名。

    返回值第一项：{(return_horizon, window_index): 排名 Series}；
    第二项：基准收益覆盖率诊断表（供校验表使用）。
    """
    month_ordinals = (
        data[Config.COLUMN_MONTH_DATE].dt.to_period("M").array.asi8
    )
    codes = data[Config.COLUMN_IFIND_CODE].to_numpy()
    is_sample = data[Config.COLUMN_IS_SAMPLE].astype(bool).to_numpy()

    excess_ranks: dict[tuple[int, int], pd.Series] = {}
    coverage_rows: list[dict[str, object]] = []
    for return_horizon in RETURN_HORIZONS:
        benchmark_lookup = build_benchmark_return_lookup(
            benchmark_nav, return_horizon
        )
        for window_index in range(
            1, MAX_RANK_COUNT_BY_HORIZON[return_horizon] + 1
        ):
            fund_return = pd.to_numeric(
                data[get_past_return_column(return_horizon, window_index)],
                errors="coerce",
            )
            window_match = (
                data[get_past_match_column(return_horizon, window_index)]
                .astype(bool)
                .to_numpy()
            )
            # 窗口 i 的收益终点月：e = t - (i - 1)。
            end_ordinals = month_ordinals - (window_index - 1)
            lookup_keys = pd.MultiIndex.from_arrays(
                [codes, end_ordinals], names=benchmark_lookup.index.names
            )
            benchmark_return = pd.Series(
                benchmark_lookup.reindex(lookup_keys).to_numpy(),
                index=data.index,
            )
            excess_return = fund_return - benchmark_return

            # 资格与 3_generate_panel_base.py 一致，另要求超额收益非缺失
            # （即基准收益可得）。
            baseline_eligible = (
                is_sample & window_match & fund_return.notna().to_numpy()
            )
            eligible = baseline_eligible & excess_return.notna().to_numpy()

            rank_values = pd.Series(np.nan, index=data.index, dtype="float64")
            rank_values.loc[eligible] = (
                excess_return[eligible]
                .groupby(
                    [
                        data.loc[eligible, Config.COLUMN_MONTH_DATE],
                        data.loc[eligible, Config.COLUMN_INVESTMENT_TYPE],
                    ],
                    sort=False,
                )
                .rank(method=Config.PANEL_RANK_METHOD, pct=True)
            )
            excess_ranks[(return_horizon, window_index)] = rank_values

            baseline_count = int(baseline_eligible.sum())
            coverage_rows.append(
                {
                    "return_horizon_m": return_horizon,
                    "window_index": window_index,
                    "baseline_eligible_rows": baseline_count,
                    "excess_eligible_rows": int(eligible.sum()),
                    "benchmark_coverage": (
                        float(eligible.sum() / baseline_count)
                        if baseline_count
                        else np.nan
                    ),
                }
            )
    return excess_ranks, pd.DataFrame(coverage_rows)


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


def build_factor_columns(
    data: pd.DataFrame,
    excess_ranks: dict[tuple[int, int], pd.Series],
    objective_mapping: pd.Series,
) -> pd.DataFrame:
    """由超额排名计算全部因子列（含 objective_class 标注列）。"""
    new_columns: dict[str, pd.Series] = {}

    objective_values = data[Config.COLUMN_IFIND_CODE].map(objective_mapping)
    if objective_values.isna().any():
        unmatched = (
            data.loc[objective_values.isna(), Config.COLUMN_IFIND_CODE]
            .drop_duplicates()
            .tolist()
        )
        raise AssertionError(
            f"以下基金匹配不到投资目标分类：{unmatched[:10]}"
            f"（共 {len(unmatched)} 只）。"
        )
    new_columns[OBJECTIVE_CLASS_COLUMN] = objective_values.astype("float64")
    new_columns[OBJECTIVE_ABS_DUMMY_COLUMN] = (
        (objective_values == 1.0).astype("float64")
    )

    for return_horizon, rank_count in FACTOR_SPECS:
        rank_matrix = pd.concat(
            [
                excess_ranks[(return_horizon, window_index)]
                for window_index in range(1, rank_count + 1)
            ],
            axis=1,
        ).to_numpy()
        full_window = np.isfinite(rank_matrix).all(axis=1)

        fac_values = pd.Series(np.nan, index=data.index, dtype="float64")
        fac_values.loc[full_window] = 1.0 - np.std(
            rank_matrix[full_window], axis=1, ddof=Config.RANK_VOL_DDOF
        )
        rank_mean_values = pd.Series(np.nan, index=data.index, dtype="float64")
        rank_mean_values.loc[full_window] = rank_matrix[full_window].mean(
            axis=1
        )
        median_values, tercile_values = compute_group_split_columns(
            data, rank_mean_values
        )

        hit_flags = rank_matrix > TOP50_THRESHOLD
        hitcount_values = pd.Series(np.nan, index=data.index, dtype="float64")
        hitcount_values.loc[full_window] = hit_flags[full_window].sum(axis=1)
        hitrate_values = hitcount_values / rank_count

        new_columns[get_bmk_fac_column(return_horizon, rank_count)] = (
            fac_values
        )
        new_columns[get_bmk_rank_mean_column(return_horizon, rank_count)] = (
            rank_mean_values
        )
        new_columns[get_bmk_median_column(return_horizon, rank_count)] = (
            median_values
        )
        new_columns[get_bmk_tercile_column(return_horizon, rank_count)] = (
            tercile_values
        )
        new_columns[get_bmk_hitcount_column(return_horizon, rank_count)] = (
            hitcount_values
        )
        new_columns[get_bmk_hitrate_column(return_horizon, rank_count)] = (
            hitrate_values
        )
        for minimum_hits in range(1, rank_count + 1):
            dummy_values = pd.Series(np.nan, index=data.index, dtype="float64")
            dummy_values.loc[full_window] = (
                hitcount_values.loc[full_window] >= minimum_hits
            ).astype("float64")
            new_columns[
                get_bmk_dummy_column(return_horizon, rank_count, minimum_hits)
            ] = dummy_values

    factor_columns = pd.DataFrame(new_columns, index=data.index)
    ordered = [OBJECTIVE_CLASS_COLUMN, OBJECTIVE_ABS_DUMMY_COLUMN] + [
        column
        for return_horizon, rank_count in FACTOR_SPECS
        for column in get_spec_output_columns(return_horizon, rank_count)
    ]
    return factor_columns[ordered]


def brute_force_check(
    data: pd.DataFrame,
    factor_columns: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
) -> int:
    """对随机抽样的行用独立代码路径复算因子，校验向量化实现。

    独立性：直接从基准净值矩阵取端点净值算超额收益；用 scipy.rankdata
    在手工筛选的截面上重算百分位排名；不复用向量化路径的任何中间结果。
    """
    month_periods = data[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    month_ordinals = month_periods.array.asi8
    codes = data[Config.COLUMN_IFIND_CODE].to_numpy()
    types = data[Config.COLUMN_INVESTMENT_TYPE].to_numpy()
    is_sample = data[Config.COLUMN_IS_SAMPLE].astype(bool).to_numpy()

    def manual_benchmark_return(
        fund_code: str, end_ordinal: int, return_horizon: int
    ) -> float:
        if fund_code not in benchmark_nav.index:
            return np.nan
        row = benchmark_nav.loc[fund_code]
        end_period = pd.Period(ordinal=end_ordinal, freq="M")
        start_period = end_period - return_horizon
        if end_period not in row.index or start_period not in row.index:
            return np.nan
        end_nav, start_nav = row[end_period], row[start_period]
        if pd.isna(end_nav) or pd.isna(start_nav):
            return np.nan
        return float(end_nav / start_nav - 1.0)

    rng = np.random.default_rng(BRUTE_FORCE_RANDOM_SEED)
    checked = 0
    for return_horizon, rank_count in FACTOR_SPECS:
        fac_column = get_bmk_fac_column(return_horizon, rank_count)
        candidates = np.flatnonzero(
            factor_columns[fac_column].notna().to_numpy()
        )
        if len(candidates) == 0:
            raise AssertionError(f"{fac_column} 没有任何非缺失值。")
        sample_size = min(
            BRUTE_FORCE_SAMPLE_SIZE // len(FACTOR_SPECS) + 1, len(candidates)
        )
        sampled = rng.choice(candidates, size=sample_size, replace=False)
        for row_position in sampled:
            row_ordinal = int(month_ordinals[row_position])
            row_code = codes[row_position]
            # 同月同投资类型的截面行集合。
            cross_section = np.flatnonzero(
                (month_ordinals == row_ordinal)
                & (types == types[row_position])
            )
            manual_ranks = []
            for window_index in range(1, rank_count + 1):
                end_ordinal = row_ordinal - (window_index - 1)
                fund_returns = pd.to_numeric(
                    data[
                        get_past_return_column(return_horizon, window_index)
                    ].iloc[cross_section],
                    errors="coerce",
                ).to_numpy()
                window_match = (
                    data[get_past_match_column(return_horizon, window_index)]
                    .iloc[cross_section]
                    .astype(bool)
                    .to_numpy()
                )
                excess_values = np.array(
                    [
                        fund_return
                        - manual_benchmark_return(
                            fund_code, end_ordinal, return_horizon
                        )
                        for fund_code, fund_return in zip(
                            codes[cross_section], fund_returns
                        )
                    ]
                )
                eligible = (
                    is_sample[cross_section]
                    & window_match
                    & np.isfinite(excess_values)
                )
                self_positions = np.flatnonzero(
                    codes[cross_section] == row_code
                )
                if len(self_positions) != 1 or not eligible[self_positions[0]]:
                    raise AssertionError(
                        f"{fac_column} 行 {row_position} 窗口 {window_index}"
                        " 不满足排名资格却有非缺失值。"
                    )
                pct_ranks = rankdata(
                    excess_values[eligible], method="average"
                ) / eligible.sum()
                self_index_in_eligible = int(
                    np.flatnonzero(
                        np.flatnonzero(eligible) == self_positions[0]
                    )[0]
                )
                manual_ranks.append(float(pct_ranks[self_index_in_eligible]))

            expected_fac = 1.0 - float(
                np.std(manual_ranks, ddof=Config.RANK_VOL_DDOF)
            )
            expected_mean = float(np.mean(manual_ranks))
            expected_hitcount = float(
                sum(rank > TOP50_THRESHOLD for rank in manual_ranks)
            )
            actual_fac = factor_columns[fac_column].iloc[row_position]
            actual_mean = factor_columns[
                get_bmk_rank_mean_column(return_horizon, rank_count)
            ].iloc[row_position]
            actual_hitcount = factor_columns[
                get_bmk_hitcount_column(return_horizon, rank_count)
            ].iloc[row_position]
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
    objective_values = factor_columns[OBJECTIVE_CLASS_COLUMN]
    if objective_values.isna().any():
        raise AssertionError("objective_class 存在缺失。")
    if not objective_values.isin([1.0, 2.0, 3.0]).all():
        raise AssertionError("objective_class 出现 1/2/3 之外的值。")
    abs_dummy = factor_columns[OBJECTIVE_ABS_DUMMY_COLUMN]
    if not abs_dummy.isin([0.0, 1.0]).all():
        raise AssertionError("as_绝对收益类 出现 0/1 之外的值。")
    if not (abs_dummy == (objective_values == 1.0).astype("float64")).all():
        raise AssertionError("as_绝对收益类 与 objective_class 不一致。")

    for return_horizon, rank_count in FACTOR_SPECS:
        fac = factor_columns[get_bmk_fac_column(return_horizon, rank_count)]
        rank_mean = factor_columns[
            get_bmk_rank_mean_column(return_horizon, rank_count)
        ]
        median_flag = factor_columns[
            get_bmk_median_column(return_horizon, rank_count)
        ]
        tercile_flag = factor_columns[
            get_bmk_tercile_column(return_horizon, rank_count)
        ]
        hitcount = factor_columns[
            get_bmk_hitcount_column(return_horizon, rank_count)
        ]
        hitrate = factor_columns[
            get_bmk_hitrate_column(return_horizon, rank_count)
        ]
        label = f"m{return_horizon} n{rank_count}"

        if (fac.notna() != rank_mean.notna()).any():
            raise AssertionError(
                f"{label} 的 FAC 与 rank_mean 缺失模式不一致。"
            )
        if not rank_mean.dropna().between(0, 1).all():
            raise AssertionError(f"{label} 的 rank_mean 超出 [0,1]。")
        if (fac.dropna() > 1).any():
            raise AssertionError(f"{label} 的 FAC 大于 1。")
        if not median_flag.dropna().isin([-2.0, 2.0]).all():
            raise AssertionError(
                f"{label} 的中位数标记出现 -2/2 之外的值。"
            )
        if not tercile_flag.dropna().isin([1.0, 2.0, 3.0]).all():
            raise AssertionError(
                f"{label} 的三分组标记出现 1/2/3 之外的值。"
            )
        if (rank_mean.isna() & median_flag.notna()).any() or (
            rank_mean.isna() & tercile_flag.notna()
        ).any():
            raise AssertionError(
                f"{label} 在 rank_mean 缺失时分组标记非缺失。"
            )
        if not hitcount.dropna().between(0, rank_count).all():
            raise AssertionError(f"{label} 的 hitcount 超出 [0,n]。")
        expected_hitrate = hitcount / rank_count
        if not np.allclose(
            hitrate.to_numpy(), expected_hitrate.to_numpy(), equal_nan=True
        ):
            raise AssertionError(
                f"{label} 的 hitrate 与 hitcount/n 不一致。"
            )

        dummy_frame = factor_columns[
            [
                get_bmk_dummy_column(return_horizon, rank_count, minimum_hits)
                for minimum_hits in range(1, rank_count + 1)
            ]
        ]
        valid_rows = hitcount.notna()
        for minimum_hits, column in enumerate(dummy_frame.columns, start=1):
            expected = (hitcount.loc[valid_rows] >= minimum_hits).astype(
                "float64"
            )
            if not np.array_equal(dummy_frame.loc[valid_rows, column], expected):
                raise AssertionError(
                    f"{column} 与 hitcount >= {minimum_hits} 不一致。"
                )
        if (dummy_frame.loc[valid_rows].diff(axis=1).iloc[:, 1:] > 0).any().any():
            raise AssertionError(f"{label} 的累计 dummy 不满足嵌套单调性。")
        if dummy_frame.loc[~valid_rows].notna().any().any():
            raise AssertionError(
                f"{label} 在 hitcount 缺失时 dummy 非缺失。"
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
    missing_keys = target_index.difference(source_keys)
    if len(missing_keys) > 0:
        raise AssertionError(
            f"{panel_path} 存在来源面板没有的基金-月份键，例如："
            f"{list(missing_keys[:5])}"
        )

    table = pq.read_table(panel_path)
    columns_to_replace = set(factor_columns.columns)
    base_names = [
        name for name in table.column_names if name not in columns_to_replace
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
    """汇总每个 (m,n) 的覆盖率、有效月份数、分类覆盖和与普通因子的相关性。"""
    month_periods = data[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    insample = data[INSAMPLE_FLAG_COLUMN] == 1
    objective_values = factor_columns[OBJECTIVE_CLASS_COLUMN]

    summary_rows = []
    for return_horizon, rank_count in FACTOR_SPECS:
        fac_column = get_bmk_fac_column(return_horizon, rank_count)
        fac = factor_columns[fac_column]
        plain_fac = pd.to_numeric(
            data[get_plain_fac_column(return_horizon, rank_count)],
            errors="coerce",
        )

        insample_counts = (
            fac[insample].notna().groupby(month_periods[insample]).sum()
        )
        effective_months = int((insample_counts >= MIN_CROSS_SECTION_N).sum())
        both_valid = fac.notna() & plain_fac.notna()
        correlation = (
            float(fac[both_valid].corr(plain_fac[both_valid]))
            if both_valid.sum() > 2
            else np.nan
        )
        row: dict[str, object] = {
            "return_horizon_m": return_horizon,
            "rank_count_n": rank_count,
            "fac_column": fac_column,
            "non_null_rows": int(fac.notna().sum()),
            "non_null_rows_insample": int(fac[insample].notna().sum()),
            "plain_fac_non_null_rows": int(plain_fac.notna().sum()),
            "effective_fm_months_ge50": effective_months,
            "corr_with_plain_fac": correlation,
        }
        for objective_class in (1.0, 2.0, 3.0):
            class_rows = objective_values == objective_class
            row[f"non_null_rows_class{int(objective_class)}"] = int(
                fac[class_rows].notna().sum()
            )
        summary_rows.append(row)
    return pd.DataFrame(summary_rows)


def build_objective_summary(
    data: pd.DataFrame, factor_columns: pd.DataFrame
) -> pd.DataFrame:
    """汇总投资目标分类在面板与样本内的基金数量。"""
    frame = pd.DataFrame(
        {
            Config.COLUMN_IFIND_CODE: data[Config.COLUMN_IFIND_CODE],
            OBJECTIVE_CLASS_COLUMN: factor_columns[OBJECTIVE_CLASS_COLUMN],
            Config.COLUMN_IS_SAMPLE: data[Config.COLUMN_IS_SAMPLE].astype(
                bool
            ),
        }
    )
    per_fund = frame.groupby(Config.COLUMN_IFIND_CODE).agg(
        objective_class=(OBJECTIVE_CLASS_COLUMN, "first"),
        ever_in_sample=(Config.COLUMN_IS_SAMPLE, "any"),
    )
    summary = per_fund.groupby("objective_class").agg(
        fund_count=("ever_in_sample", "size"),
        fund_count_in_sample=("ever_in_sample", "sum"),
    )
    return summary.reset_index()


def write_check_workbook(
    factor_summary: pd.DataFrame,
    coverage_diagnostics: pd.DataFrame,
    objective_summary: pd.DataFrame,
    check_output_path: Path,
) -> None:
    """把因子汇总、基准覆盖率和分类汇总写成 Excel 工作簿。"""
    temporary_check = make_temporary_path(check_output_path)
    try:
        with pd.ExcelWriter(temporary_check) as writer:
            factor_summary.to_excel(
                writer, sheet_name="factor_summary", index=False
            )
            coverage_diagnostics.to_excel(
                writer, sheet_name="benchmark_coverage", index=False
            )
            objective_summary.to_excel(
                writer, sheet_name="objective_class_summary", index=False
            )
        read_back = pd.read_excel(temporary_check, sheet_name="factor_summary")
        if len(read_back) != len(factor_summary):
            raise AssertionError("校验表回读后的行数不一致。")
        os.replace(temporary_check, check_output_path)
    finally:
        temporary_check.unlink(missing_ok=True)


def generate_benchmark_excess_factors(
    source_panel_path: Path = DEFAULT_SOURCE_PANEL_PATH,
    target_paths: Iterable[Path] = DEFAULT_TARGET_PATHS,
    check_output_path: Path = DEFAULT_CHECK_OUTPUT_PATH,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
    write_preview: bool = True,
) -> dict[str, object]:
    """计算基准超额一致性因子、校验并写入全部目标面板。"""
    if preview_rows <= 0:
        raise ValueError("preview_rows 必须是正整数。")

    data = read_source_panel(source_panel_path)
    benchmark_nav = read_benchmark_nav_matrix()
    objective_mapping = read_objective_class_mapping()

    panel_funds = set(data[Config.COLUMN_IFIND_CODE].unique())
    missing_nav_funds = panel_funds - set(benchmark_nav.index)
    if missing_nav_funds:
        # 基准净值缺整只基金时不视为致命：该基金的超额收益全缺失即可，
        # 但要在运行输出中明确暴露数量。
        print(
            f"警告：{len(missing_nav_funds)} 只面板基金在基准净值文件中"
            f"没有记录，例如 {sorted(missing_nav_funds)[:5]}。"
        )

    excess_ranks, coverage_diagnostics = compute_excess_rank_columns(
        data, benchmark_nav
    )
    factor_columns = build_factor_columns(data, excess_ranks, objective_mapping)
    if list(factor_columns.columns) != get_owned_output_columns():
        raise AssertionError("因子列集合与登记的输出列清单不一致。")

    validate_factor_columns(data, factor_columns)
    checked_rows = brute_force_check(data, factor_columns, benchmark_nav)

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
    objective_summary = build_objective_summary(data, factor_columns)
    write_check_workbook(
        factor_summary,
        coverage_diagnostics,
        objective_summary,
        check_output_path,
    )
    return {
        "panel_summaries": panel_summaries,
        "factor_summary": factor_summary,
        "coverage_diagnostics": coverage_diagnostics,
        "objective_summary": objective_summary,
        "check_output_path": check_output_path,
        "brute_force_checked_rows": checked_rows,
        "added_column_count": len(factor_columns.columns),
    }


def print_summary(result: dict[str, object]) -> None:
    """打印面板写入结果和因子覆盖摘要。"""
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
    print("因子汇总：")
    print(result["factor_summary"].to_string(index=False))
    print("投资目标分类汇总：")
    print(result["objective_summary"].to_string(index=False))


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    result = generate_benchmark_excess_factors(
        source_panel_path=args.source_panel,
        target_paths=args.targets,
        check_output_path=args.check_output,
        preview_rows=args.preview_rows,
        write_preview=not args.no_preview,
    )
    print_summary(result)


if __name__ == "__main__":
    main()
