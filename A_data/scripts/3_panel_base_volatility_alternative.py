"""为 ``panel_base`` 追加替代排名波动率和沪深300市场状态指标。

默认读取并覆盖：

    A_data/output/panel_base.parquet
    A_data/output/panel_base_preview.xlsx

本脚本新增四类变量：

1. 基金过去 1 个月累计收益在同月、同投资类型基金中的百分位排名；
2. 过去 1/3/6/12 个月累计收益排名之间的标准差；
3. 过去 1/3/6/12 个月累计收益排名之间的均值；
4. 分别回溯最近 3/6/12 个沪深300上涨月和下跌月，计算基金当月
   1 个月收益排名的标准差。

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_volatility_alternative.py
    .venv/bin/python A_data/scripts/3_panel_base_volatility_alternative.py --no-preview
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import Config


DEFAULT_INPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_OUTPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_MARKET_INPUT_PATH = (
    Config.A_DATA_ROOT / "prepared_data" / "iFind_EDB" / "HS300_mrt.xlsx"
)
DEFAULT_PREVIEW_ROWS = 1000

MARKET_DATE_COLUMN = "日期"
MARKET_RETURN_COLUMN = "HS300_monthly_return"
MARKET_DIRECTION_COLUMN = "hs300_market_direction"

ONE_MONTH_RANK_COLUMN = "past_ret_1m_rank_1"
CROSS_HORIZON_VOLATILITY_COLUMN = (
    "rank_vol_across_horizons_1m_3m_6m_12m"
)
CROSS_HORIZON_RANK_MEAN_COLUMN = (
    "rank_mean_across_horizons_1m_3m_6m_12m"
)
CROSS_HORIZON_RANK_COLUMNS = (
    ONE_MONTH_RANK_COLUMN,
    "past_ret_3m_rank_1",
    "past_ret_6m_rank_1",
    "past_ret_12m_rank_1",
)

MARKET_STATE_WINDOWS = (3, 6, 12)
MARKET_STATES = {"up": 1, "down": -1}


def get_market_state_volatility_column(state_name: str, rank_count: int) -> str:
    """返回上涨或下跌市场状态排名波动率的列名。"""
    return f"rank_vol_{state_name}_n{rank_count}_pairwise1"


def get_owned_output_columns() -> list[str]:
    """列出由本脚本管理的字段，便于重复运行时先删除旧结果。"""
    columns = [
        ONE_MONTH_RANK_COLUMN,
        CROSS_HORIZON_VOLATILITY_COLUMN,
        CROSS_HORIZON_RANK_MEAN_COLUMN,
        MARKET_DIRECTION_COLUMN,
    ]
    for state_name in MARKET_STATES:
        columns.extend(
            get_market_state_volatility_column(state_name, rank_count)
            for rank_count in MARKET_STATE_WINDOWS
        )
    return columns


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="为 panel_base 追加替代排名波动率和沪深300状态指标。"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="输入 panel_base parquet 路径。",
    )
    parser.add_argument(
        "--market-input",
        type=Path,
        default=DEFAULT_MARKET_INPUT_PATH,
        help="沪深300月收益 Excel 路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="输出 parquet 路径；默认覆盖正式 panel_base。",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Excel 预览路径；默认跟随 output 生成 *_preview.xlsx。",
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


def require_columns(
    data: pd.DataFrame, columns: Iterable[str], source_path: Path | str
) -> None:
    """检查输入是否包含全部必需字段，并给出容易定位的报错。"""
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source_path} 缺少字段：{missing}；实际字段数为 {len(data.columns)}。"
        )


def read_panel(input_path: Path) -> pd.DataFrame:
    """读取面板并校验主键、日期、净值和排名原料。"""
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")

    data = pd.read_parquet(input_path)
    required_columns = [
        Config.COLUMN_IFIND_CODE,
        Config.COLUMN_INVESTMENT_TYPE,
        Config.COLUMN_MONTH_DATE,
        Config.COLUMN_NAV,
        Config.COLUMN_IS_SAMPLE,
        Config.COLUMN_IS_SIZE_ELIGIBLE,
        *CROSS_HORIZON_RANK_COLUMNS[1:],
    ]
    require_columns(data, required_columns, input_path)

    # 日期和净值若无法识别，后续 shift 仍可能运行但会产生大量静默缺失，
    # 因此在进入计算前就统一转换并明确报错。
    data = data.copy()
    data[Config.COLUMN_MONTH_DATE] = pd.to_datetime(
        data[Config.COLUMN_MONTH_DATE], errors="coerce"
    )
    data[Config.COLUMN_NAV] = pd.to_numeric(
        data[Config.COLUMN_NAV], errors="coerce"
    )
    if data[Config.COLUMN_MONTH_DATE].isna().any():
        raise ValueError(f"{input_path} 中存在无法识别的 month_date。")
    if data[Config.COLUMN_NAV].isna().any() or (
        data[Config.COLUMN_NAV] <= 0
    ).any():
        raise ValueError(f"{input_path} 中存在缺失或非正数净值。")

    key_columns = [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    duplicate_keys = data.duplicated(key_columns, keep=False)
    if duplicate_keys.any():
        examples = data.loc[duplicate_keys, key_columns].head(10)
        raise ValueError("面板中存在重复基金-月份键：\n" + examples.to_string(index=False))
    return data


def read_market_directions(market_input_path: Path) -> pd.Series:
    """读取沪深300月收益，并返回以月份为索引的 1/-1 状态序列。"""
    if not market_input_path.exists():
        raise FileNotFoundError(f"沪深300月收益文件不存在：{market_input_path}")

    market = pd.read_excel(market_input_path)
    require_columns(
        market,
        [MARKET_DATE_COLUMN, MARKET_RETURN_COLUMN],
        market_input_path,
    )
    market = market[[MARKET_DATE_COLUMN, MARKET_RETURN_COLUMN]].copy()
    market[MARKET_DATE_COLUMN] = pd.to_datetime(
        market[MARKET_DATE_COLUMN], errors="coerce"
    )
    market[MARKET_RETURN_COLUMN] = pd.to_numeric(
        market[MARKET_RETURN_COLUMN], errors="coerce"
    )
    if market.isna().any().any():
        raise ValueError("沪深300月收益文件中存在无法识别的日期或收益率。")

    # 面板日期可能是交易日月末，而 Excel 日期可能是自然月末；统一成月份后
    # 再对齐，可以避免 2026-05-29 与 2026-05-31 这类日期错配。
    market["month_period"] = market[MARKET_DATE_COLUMN].dt.to_period("M")
    if market["month_period"].duplicated().any():
        duplicate_months = market.loc[
            market["month_period"].duplicated(keep=False), "month_period"
        ].astype(str)
        raise ValueError(
            "沪深300月收益文件存在重复月份："
            + "、".join(duplicate_months.head(10))
        )

    zero_return = market[MARKET_RETURN_COLUMN] == 0
    if zero_return.any():
        zero_months = market.loc[zero_return, "month_period"].astype(str)
        raise ValueError(
            "沪深300出现月收益率等于 0 的月份，无法归入上涨或下跌："
            + "、".join(zero_months.head(10))
        )

    directions = pd.Series(
        np.where(market[MARKET_RETURN_COLUMN] > 0, 1, -1),
        index=pd.PeriodIndex(market["month_period"], freq="M"),
        name=MARKET_DIRECTION_COLUMN,
        dtype="int8",
    )
    return directions.sort_index()


def calculate_past_1m_rank(data: pd.DataFrame) -> pd.Series:
    """计算过去1个月收益在同月同类基金中的百分位排名。

    这里完全沿用 ``3_generate_panel_base.py`` 的排名资格：当前月和上月
    必须连续，两个端点都必须在样本内且满足规模资格。排名采用 average 方法，
    因而并列收益会得到相同的平均百分位排名。
    """
    key_columns = [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    working = data.assign(_original_position=np.arange(len(data))).sort_values(
        key_columns
    )
    grouped = working.groupby(Config.COLUMN_IFIND_CODE, sort=False)

    previous_nav = grouped[Config.COLUMN_NAV].shift(1)
    previous_date = grouped[Config.COLUMN_MONTH_DATE].shift(1)
    previous_sample = grouped[Config.COLUMN_IS_SAMPLE].shift(1).fillna(False)
    previous_size = (
        grouped[Config.COLUMN_IS_SIZE_ELIGIBLE].shift(1).fillna(False)
    )

    current_period = working[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    previous_period = previous_date.dt.to_period("M")
    has_consecutive_months = previous_period + 1 == current_period

    current_sample = working[Config.COLUMN_IS_SAMPLE].fillna(False).astype(bool)
    current_size = (
        working[Config.COLUMN_IS_SIZE_ELIGIBLE].fillna(False).astype(bool)
    )
    valid_window = (
        has_consecutive_months
        & current_sample
        & current_size
        & previous_sample.astype(bool)
        & previous_size.astype(bool)
        & previous_nav.notna()
    )

    one_month_return = working[Config.COLUMN_NAV] / previous_nav - 1
    rank_values = pd.Series(np.nan, index=working.index, dtype="float64")
    group_columns = [Config.COLUMN_MONTH_DATE, Config.COLUMN_INVESTMENT_TYPE]
    rank_values.loc[valid_window] = (
        working.loc[valid_window]
        .assign(_past_ret_1m=one_month_return.loc[valid_window])
        .groupby(group_columns, sort=False)["_past_ret_1m"]
        .rank(method=Config.PANEL_RANK_METHOD, pct=True)
    )

    # 计算时为了 shift 排过序，返回前按原位置恢复输入行顺序。
    result = pd.Series(
        rank_values.to_numpy(),
        index=working["_original_position"].to_numpy(),
        dtype="float64",
    )
    return result.sort_index().reset_index(drop=True)


def calculate_cross_horizon_volatility(data: pd.DataFrame) -> pd.Series:
    """计算1/3/6/12个月排名的样本标准差，缺一项就保持缺失。"""
    ranks = data[list(CROSS_HORIZON_RANK_COLUMNS)].apply(
        pd.to_numeric, errors="coerce"
    )
    full_window = ranks.notna().all(axis=1)
    volatility = pd.Series(np.nan, index=data.index, dtype="float64")
    volatility.loc[full_window] = ranks.loc[full_window].std(
        axis=1, ddof=Config.RANK_VOL_DDOF
    )
    return volatility


def calculate_cross_horizon_rank_mean(data: pd.DataFrame) -> pd.Series:
    """计算1/3/6/12个月排名的行内均值，缺一项就保持缺失。"""
    ranks = data[list(CROSS_HORIZON_RANK_COLUMNS)].apply(
        pd.to_numeric, errors="coerce"
    )
    full_window = ranks.notna().all(axis=1)
    rank_mean = pd.Series(np.nan, index=data.index, dtype="float64")
    rank_mean.loc[full_window] = ranks.loc[full_window].mean(axis=1)
    return rank_mean


def attach_market_direction(
    data: pd.DataFrame, market_directions: pd.Series
) -> pd.Series:
    """按自然月份把沪深300 1/-1 状态映射到面板每一行。"""
    panel_period = data[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    missing_periods = sorted(set(panel_period.unique()) - set(market_directions.index))
    if missing_periods:
        raise ValueError(
            "沪深300月收益未覆盖面板月份："
            + "、".join(str(period) for period in missing_periods[:20])
        )
    return panel_period.map(market_directions).astype("int8")


def build_recent_state_months(
    market_directions: pd.Series,
    state_value: int,
    max_rank_count: int,
) -> dict[pd.Period, tuple[object, ...]]:
    """为每个月列出截至当月最近若干个指定市场状态月份。

    月份选择只由沪深300决定，与某只基金是否有数据无关。这样当基金在某个
    被选中的上涨月或下跌月缺少排名时，结果会正确地变成 NaN，而不会悄悄
    跳到更早月份补足。
    """
    history: list[pd.Period] = []
    targets: dict[pd.Period, tuple[object, ...]] = {}
    for month_period, direction in market_directions.items():
        if int(direction) == state_value:
            history.append(month_period)
        recent_history = history[-max_rank_count:]
        # 固定矩阵宽度为12列，但把已有月份靠右保存。这样历史只有5个上涨月时，
        # n=3 可以读取最右3列正常计算，n=6/12 则因左侧仍有 NaT 保持缺失。
        padding = [pd.NaT] * (max_rank_count - len(recent_history))
        targets[month_period] = tuple([*padding, *recent_history])
    return targets


def collect_recent_state_rank_matrix(
    data: pd.DataFrame,
    market_directions: pd.Series,
    state_value: int,
    max_rank_count: int = max(MARKET_STATE_WINDOWS),
) -> np.ndarray:
    """收集每行截至当月最近 ``max_rank_count`` 个指定状态月的1个月排名。"""
    panel_period = data[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    targets_by_month = build_recent_state_months(
        market_directions, state_value, max_rank_count
    )

    # 基金-月份主键在 read_panel 中已经验证唯一，因此可以安全地用 MultiIndex
    # 做精确查找。缺少某个选中月份时 reindex 会返回 NaN，符合完整窗口要求。
    rank_lookup = pd.Series(
        pd.to_numeric(data[ONE_MONTH_RANK_COLUMN], errors="coerce").to_numpy(),
        index=pd.MultiIndex.from_arrays(
            [data[Config.COLUMN_IFIND_CODE].to_numpy(), panel_period.to_numpy()],
            names=[Config.COLUMN_IFIND_CODE, "month_period"],
        ),
    )
    matrix = np.full((len(data), max_rank_count), np.nan, dtype="float64")

    for column_index in range(max_rank_count):
        target_periods = panel_period.map(
            lambda period: targets_by_month.get(
                period, tuple([pd.NaT] * max_rank_count)
            )[column_index]
        )
        lookup_keys = pd.MultiIndex.from_arrays(
            [data[Config.COLUMN_IFIND_CODE].to_numpy(), target_periods.to_numpy()],
            names=rank_lookup.index.names,
        )
        matrix[:, column_index] = rank_lookup.reindex(lookup_keys).to_numpy()
    return matrix


def add_market_state_volatilities(
    data: pd.DataFrame, market_directions: pd.Series
) -> pd.DataFrame:
    """新增最近3/6/12个上涨月和下跌月的1个月排名标准差。"""
    result = data.copy()
    max_rank_count = max(MARKET_STATE_WINDOWS)
    for state_name, state_value in MARKET_STATES.items():
        rank_matrix = collect_recent_state_rank_matrix(
            result,
            market_directions,
            state_value,
            max_rank_count=max_rank_count,
        )
        for rank_count in MARKET_STATE_WINDOWS:
            # rank_matrix 按时间从早到晚保存最近12个状态月，因此 n=3/6
            # 应从矩阵最右边取最近的 n 个，而不是取最左边的较早月份。
            selected_ranks = rank_matrix[:, -rank_count:]
            full_window = np.isfinite(selected_ranks).all(axis=1)
            values = np.full(len(result), np.nan, dtype="float64")
            values[full_window] = np.std(
                selected_ranks[full_window],
                axis=1,
                ddof=Config.RANK_VOL_DDOF,
            )
            result[
                get_market_state_volatility_column(state_name, rank_count)
            ] = values
    return result


def build_alternative_volatility_features(
    original: pd.DataFrame, market_directions: pd.Series
) -> pd.DataFrame:
    """按固定顺序生成本脚本全部10个输出字段。"""
    # 重复运行时只移除本脚本拥有的旧字段，其他上游或下游变量原样保留。
    owned_columns = get_owned_output_columns()
    base_columns = [column for column in original.columns if column not in owned_columns]
    result = original[base_columns].copy()

    result[ONE_MONTH_RANK_COLUMN] = calculate_past_1m_rank(result).to_numpy()
    result[CROSS_HORIZON_VOLATILITY_COLUMN] = (
        calculate_cross_horizon_volatility(result)
    )
    result[CROSS_HORIZON_RANK_MEAN_COLUMN] = (
        calculate_cross_horizon_rank_mean(result)
    )
    result[MARKET_DIRECTION_COLUMN] = attach_market_direction(
        result, market_directions
    ).to_numpy()
    result = add_market_state_volatilities(result, market_directions)
    return result


def validate_result(original: pd.DataFrame, result: pd.DataFrame) -> None:
    """写盘前校验行数、主键、原字段和新增指标的基本恒等式。"""
    if len(result) != len(original):
        raise AssertionError("新增指标后面板行数发生变化。")

    key_columns = [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    if not result[key_columns].equals(original[key_columns]):
        raise AssertionError("新增指标后基金-月份主键或行顺序发生变化。")

    original_base_columns = [
        column for column in original.columns if column not in get_owned_output_columns()
    ]
    if list(result.columns[: len(original_base_columns)]) != original_base_columns:
        raise AssertionError("原有字段顺序发生变化，新增字段没有正确追加到右侧。")
    for column in original_base_columns:
        if not result[column].equals(original[column]):
            raise AssertionError(f"原字段 {column} 的值被意外修改。")

    rank_values = result[ONE_MONTH_RANK_COLUMN].dropna()
    if not rank_values.between(0, 1).all():
        raise AssertionError(f"{ONE_MONTH_RANK_COLUMN} 出现0到1之外的值。")
    rank_mean_values = result[CROSS_HORIZON_RANK_MEAN_COLUMN].dropna()
    if not rank_mean_values.between(0, 1).all():
        raise AssertionError(
            f"{CROSS_HORIZON_RANK_MEAN_COLUMN} 出现0到1之外的值。"
        )
    if not result[MARKET_DIRECTION_COLUMN].isin([-1, 1]).all():
        raise AssertionError(f"{MARKET_DIRECTION_COLUMN} 出现1/-1之外的值。")

    expected_cross = calculate_cross_horizon_volatility(result)
    if not result[CROSS_HORIZON_VOLATILITY_COLUMN].equals(expected_cross):
        raise AssertionError("四期限排名波动率与四个排名列的标准差不一致。")

    expected_rank_mean = calculate_cross_horizon_rank_mean(result)
    if not result[CROSS_HORIZON_RANK_MEAN_COLUMN].equals(expected_rank_mean):
        raise AssertionError("四期限排名均值与四个排名列的行内均值不一致。")

    volatility_columns = [
        CROSS_HORIZON_VOLATILITY_COLUMN,
        *[
            get_market_state_volatility_column(state_name, rank_count)
            for state_name in MARKET_STATES
            for rank_count in MARKET_STATE_WINDOWS
        ],
    ]
    for column in volatility_columns:
        values = result[column].dropna()
        if not np.isfinite(values).all() or (values < 0).any():
            raise AssertionError(f"{column} 出现负数或非有限值。")


def get_default_preview_path(output_path: Path) -> Path:
    """根据 parquet 输出路径推导 Excel 预览路径。"""
    return output_path.with_name(output_path.stem + "_preview.xlsx")


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


def write_outputs_atomically(
    result: pd.DataFrame,
    output_path: Path,
    preview_path: Path | None,
    preview_rows: int,
) -> None:
    """先写临时文件并回读校验，通过后再覆盖正式输出。"""
    if preview_rows <= 0:
        raise ValueError("preview_rows 必须是正整数。")

    temporary_output = make_temporary_path(output_path)
    temporary_preview = (
        make_temporary_path(preview_path) if preview_path is not None else None
    )
    try:
        result.to_parquet(temporary_output, index=False)
        parquet_check = pd.read_parquet(
            temporary_output,
            columns=[Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE],
        )
        if len(parquet_check) != len(result):
            raise AssertionError("临时 parquet 回读后的行数不一致。")

        if temporary_preview is not None:
            preview = result.head(preview_rows)
            preview.to_excel(temporary_preview, index=False)
            preview_check = pd.read_excel(temporary_preview)
            if preview_check.shape != preview.shape:
                raise AssertionError(
                    "临时 Excel 预览回读后的行列数与预期不一致。"
                )
            if list(preview_check.columns) != list(preview.columns):
                raise AssertionError("临时 Excel 预览的字段顺序不一致。")

        # 只有 parquet 和可选 preview 都完成回读校验后，才替换正式文件。
        os.replace(temporary_output, output_path)
        if temporary_preview is not None and preview_path is not None:
            os.replace(temporary_preview, preview_path)
    finally:
        temporary_output.unlink(missing_ok=True)
        if temporary_preview is not None:
            temporary_preview.unlink(missing_ok=True)


def generate_alternative_volatility_features(
    input_path: Path = DEFAULT_INPUT_PATH,
    market_input_path: Path = DEFAULT_MARKET_INPUT_PATH,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    preview_path: Path | None = None,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
    write_preview: bool = True,
) -> dict[str, object]:
    """读取、计算、校验并写出替代排名波动率指标。"""
    original = read_panel(input_path)
    market_directions = read_market_directions(market_input_path)
    result = build_alternative_volatility_features(original, market_directions)
    validate_result(original, result)

    actual_preview_path = None
    if write_preview:
        actual_preview_path = preview_path or get_default_preview_path(output_path)
    write_outputs_atomically(
        result,
        output_path=output_path,
        preview_path=actual_preview_path,
        preview_rows=preview_rows,
    )

    added_columns = get_owned_output_columns()
    return {
        "input_path": input_path,
        "market_input_path": market_input_path,
        "output_path": output_path,
        "preview_path": actual_preview_path,
        "row_count": len(result),
        "column_count": len(result.columns),
        "added_columns": added_columns,
        "non_null_counts": {
            column: int(result[column].notna().sum()) for column in added_columns
        },
    }


def print_summary(summary: dict[str, object]) -> None:
    """打印输出路径和每个新增变量的有效行数。"""
    print(f"输入路径：{summary['input_path']}")
    print(f"沪深300路径：{summary['market_input_path']}")
    print(f"输出路径：{summary['output_path']}")
    if summary["preview_path"] is not None:
        print(f"预览路径：{summary['preview_path']}")
    print(f"输出行数：{summary['row_count']:,}")
    print(f"输出列数：{summary['column_count']:,}")
    print("本脚本字段及非缺失行数：")
    non_null_counts = summary["non_null_counts"]
    for column in summary["added_columns"]:
        print(f"  {column}：{non_null_counts[column]:,}")


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    summary = generate_alternative_volatility_features(
        input_path=args.input,
        market_input_path=args.market_input,
        output_path=args.output,
        preview_path=args.preview,
        preview_rows=args.preview_rows,
        write_preview=not args.no_preview,
    )
    print_summary(summary)


if __name__ == "__main__":
    main()
