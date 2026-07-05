"""为 ``panel_base`` 和热力图面板追加四个月度市场状态列。

默认读取并覆盖：

    A_data/output/panel_base.parquet
    A_data/output/panel_base_heatmap_m1_12_n1_12.parquet

以及对应的 *_preview.xlsx 预览文件。

四个市场状态列均为月度值（同一月份所有基金取值相同），编码统一为
1 / -1 / NaN（float64）：

1. ``mkt_state_hs300``：沪深300当月收益 >0 记 1，<0 记 -1，=0 或缺失记 NaN；
2. ``mkt_state_style``：国证成长(399370) 当月收益高于国证价值(399371) 记 1，
   低于记 -1，相等或任一缺失记 NaN；
3. ``mkt_state_size``：中证800当月收益高于中证1000（大盘占优）记 1，
   低于（小盘占优）记 -1，相等或任一缺失记 NaN；
4. ``mkt_state_indvol``：31个申万一级行业当月收益的横截面标准差，对照含当月
   在内的最近36个月该指标的中位数，大于等于记 1（高波动），小于记 -1
   （低波动）；窗口内有效月份不足36个或当月任一行业缺失记 NaN。

同时输出市场状态校验表：

    A_data/output/mkt_condition_check.xlsx

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_mkt_condition.py
    .venv/bin/python A_data/scripts/3_panel_base_mkt_condition.py --no-preview
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


EDB_DIR = Config.A_DATA_ROOT / "prepared_data" / "ifind_edb"
DEFAULT_INDEX_INPUT_PATH = EDB_DIR / "HS300_CSI800_CSI1000_mrt.xlsx"
DEFAULT_STYLE_INPUT_PATH = EDB_DIR / "399370_399371_mrt.xlsx"
DEFAULT_INDUSTRY_INPUT_PATH = EDB_DIR / "SW_level1_industry_mrt.xlsx"
DEFAULT_TARGET_PATHS = (
    Config.PANEL_OUTPUT_PATH,
    Config.PANEL_HEATMAP_OUTPUT_PATH,
)
DEFAULT_CHECK_OUTPUT_PATH = (
    Config.A_DATA_ROOT / "output" / "mkt_condition_check.xlsx"
)
DEFAULT_PREVIEW_ROWS = 1000

MARKET_DATE_COLUMN = "日期"
HS300_RETURN_COLUMN = "HS300_monthly_return"
CSI800_RETURN_COLUMN = "CSI800_monthly_return"
CSI1000_RETURN_COLUMN = "CSI1000_monthly_return"
GROWTH_RETURN_COLUMN = "GZ_Growth_monthly_return"
VALUE_RETURN_COLUMN = "GZ_Value_monthly_return"

STATE_HS300_COLUMN = "mkt_state_hs300"
STATE_STYLE_COLUMN = "mkt_state_style"
STATE_SIZE_COLUMN = "mkt_state_size"
STATE_INDVOL_COLUMN = "mkt_state_indvol"
STATE_COLUMNS = (
    STATE_HS300_COLUMN,
    STATE_STYLE_COLUMN,
    STATE_SIZE_COLUMN,
    STATE_INDVOL_COLUMN,
)

INDUSTRY_VOL_COLUMN = "industry_return_xsec_vol"
INDUSTRY_VOL_MEDIAN_COLUMN = "industry_vol_rolling_median_36m"
INDVOL_ROLLING_WINDOW = 36

INSAMPLE_FLAG_COLUMN = "is_insample_future_ret_6m"


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="为 panel_base 和热力图面板追加四个月度市场状态列。"
    )
    parser.add_argument(
        "--index-input",
        type=Path,
        default=DEFAULT_INDEX_INPUT_PATH,
        help="沪深300/中证800/中证1000月收益 Excel 路径。",
    )
    parser.add_argument(
        "--style-input",
        type=Path,
        default=DEFAULT_STYLE_INPUT_PATH,
        help="国证成长/国证价值月收益 Excel 路径。",
    )
    parser.add_argument(
        "--industry-input",
        type=Path,
        default=DEFAULT_INDUSTRY_INPUT_PATH,
        help="申万一级行业月收益 Excel 路径。",
    )
    parser.add_argument(
        "--targets",
        type=Path,
        nargs="+",
        default=list(DEFAULT_TARGET_PATHS),
        help="需要追加市场状态列的 parquet 面板路径，默认两个正式面板。",
    )
    parser.add_argument(
        "--check-output",
        type=Path,
        default=DEFAULT_CHECK_OUTPUT_PATH,
        help="市场状态校验表输出路径。",
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


def read_monthly_returns(
    input_path: Path, value_columns: list[str] | None = None
) -> pd.DataFrame:
    """读取月度收益 Excel，返回以自然月份为索引的数值表。

    面板日期可能是交易日月末，而 Excel 日期可能是自然月末或最后交易日，
    统一转成月份 Period 后再对齐，避免 2026-06-27 与 2026-06-30 这类错配。
    """
    if not input_path.exists():
        raise FileNotFoundError(f"月度收益文件不存在：{input_path}")

    data = pd.read_excel(input_path)
    require_columns(data, [MARKET_DATE_COLUMN], input_path)
    dates = pd.to_datetime(data[MARKET_DATE_COLUMN], errors="coerce")
    if dates.isna().any():
        raise ValueError(f"{input_path} 中存在无法识别的日期。")

    periods = dates.dt.to_period("M")
    if periods.duplicated().any():
        duplicate_months = periods[periods.duplicated(keep=False)].astype(str)
        raise ValueError(
            f"{input_path} 存在重复月份：" + "、".join(duplicate_months.head(10))
        )

    if value_columns is None:
        value_columns = [
            column for column in data.columns if column != MARKET_DATE_COLUMN
        ]
    require_columns(data, value_columns, input_path)

    result = data[value_columns].apply(pd.to_numeric, errors="coerce")
    result.index = pd.PeriodIndex(periods, freq="M")
    return result.sort_index()


def make_sign_state(values: pd.Series) -> pd.Series:
    """把数值序列转成 1/-1/NaN 状态：正为 1，负为 -1，零或缺失为 NaN。"""
    state = pd.Series(np.nan, index=values.index, dtype="float64")
    state[values > 0] = 1.0
    state[values < 0] = -1.0
    return state


def build_industry_vol_state(
    industry_returns: pd.DataFrame,
) -> pd.DataFrame:
    """计算行业横截面波动率及其滚动中位数状态。

    当月指标为全部行业收益的横截面标准差；任一行业缺失则当月指标记缺失。
    对照窗口为含当月在内的最近36个月，窗口内有效指标不足36个则不打标。
    """
    complete_months = industry_returns.notna().all(axis=1)
    volatility = pd.Series(np.nan, index=industry_returns.index, dtype="float64")
    volatility.loc[complete_months] = industry_returns.loc[complete_months].std(
        axis=1, ddof=Config.RANK_VOL_DDOF
    )

    rolling_median = volatility.rolling(
        window=INDVOL_ROLLING_WINDOW, min_periods=INDVOL_ROLLING_WINDOW
    ).median()

    state = pd.Series(np.nan, index=volatility.index, dtype="float64")
    comparable = volatility.notna() & rolling_median.notna()
    state[comparable & (volatility >= rolling_median)] = 1.0
    state[comparable & (volatility < rolling_median)] = -1.0

    return pd.DataFrame(
        {
            INDUSTRY_VOL_COLUMN: volatility,
            INDUSTRY_VOL_MEDIAN_COLUMN: rolling_median,
            STATE_INDVOL_COLUMN: state,
        }
    )


def build_state_table(
    index_input_path: Path,
    style_input_path: Path,
    industry_input_path: Path,
) -> pd.DataFrame:
    """汇总四个市场状态列和相关诊断字段，索引为自然月份。"""
    index_returns = read_monthly_returns(
        index_input_path,
        [HS300_RETURN_COLUMN, CSI800_RETURN_COLUMN, CSI1000_RETURN_COLUMN],
    )
    style_returns = read_monthly_returns(
        style_input_path,
        [GROWTH_RETURN_COLUMN, VALUE_RETURN_COLUMN],
    )
    industry_returns = read_monthly_returns(industry_input_path)
    industry_state = build_industry_vol_state(industry_returns)

    state_table = pd.concat(
        [
            index_returns,
            style_returns,
            industry_state,
        ],
        axis=1,
    ).sort_index()

    state_table[STATE_HS300_COLUMN] = make_sign_state(
        state_table[HS300_RETURN_COLUMN]
    )
    state_table[STATE_STYLE_COLUMN] = make_sign_state(
        state_table[GROWTH_RETURN_COLUMN] - state_table[VALUE_RETURN_COLUMN]
    )
    state_table[STATE_SIZE_COLUMN] = make_sign_state(
        state_table[CSI800_RETURN_COLUMN] - state_table[CSI1000_RETURN_COLUMN]
    )
    return state_table


def validate_state_table(state_table: pd.DataFrame) -> None:
    """校验状态列取值范围与行业波动率状态的构造恒等式。"""
    for column in STATE_COLUMNS:
        values = state_table[column].dropna()
        if not values.isin([1.0, -1.0]).all():
            raise AssertionError(f"{column} 出现 1/-1 之外的取值。")
        if values.empty:
            raise AssertionError(f"{column} 没有任何有效状态月份。")

    comparable = (
        state_table[INDUSTRY_VOL_COLUMN].notna()
        & state_table[INDUSTRY_VOL_MEDIAN_COLUMN].notna()
    )
    if not state_table.loc[~comparable, STATE_INDVOL_COLUMN].isna().all():
        raise AssertionError("行业波动率或滚动中位数缺失时，状态标记必须缺失。")
    expected_high = comparable & (
        state_table[INDUSTRY_VOL_COLUMN]
        >= state_table[INDUSTRY_VOL_MEDIAN_COLUMN]
    )
    if not (
        state_table.loc[expected_high, STATE_INDVOL_COLUMN] == 1.0
    ).all():
        raise AssertionError("高波动状态与滚动中位数比较结果不一致。")


def read_panel_month_periods(panel_path: Path) -> pd.Series:
    """只读取面板的 month_date 列并转成自然月份。"""
    if not panel_path.exists():
        raise FileNotFoundError(f"面板文件不存在：{panel_path}")
    months = pd.read_parquet(
        panel_path, columns=[Config.COLUMN_MONTH_DATE]
    )[Config.COLUMN_MONTH_DATE]
    months = pd.to_datetime(months, errors="coerce")
    if months.isna().any():
        raise ValueError(f"{panel_path} 中存在无法识别的 month_date。")
    return months.dt.to_period("M")


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


def append_states_to_panel(
    panel_path: Path,
    state_table: pd.DataFrame,
    preview_rows: int,
    write_preview: bool,
) -> dict[str, object]:
    """把四个状态列追加到单个 parquet 面板并原子写回。

    使用 pyarrow 直接追加列，避免把热力图大面板整表转入 pandas。
    原有列不做任何修改，重复运行时先移除本脚本拥有的旧状态列。
    """
    month_periods = read_panel_month_periods(panel_path)

    state_values: dict[str, np.ndarray] = {}
    for column in STATE_COLUMNS:
        mapped = month_periods.map(state_table[column])
        state_values[column] = mapped.to_numpy(dtype="float64")
        if not np.isfinite(state_values[column]).any():
            raise AssertionError(
                f"{panel_path} 的 {column} 全部缺失，请检查月份对齐。"
            )

    table = pq.read_table(panel_path)
    if table.num_rows != len(month_periods):
        raise AssertionError(f"{panel_path} 行数与 month_date 列读取结果不一致。")

    base_names = [
        name for name in table.column_names if name not in STATE_COLUMNS
    ]
    original_names = list(table.column_names)
    table = table.select(base_names)
    for column in STATE_COLUMNS:
        table = table.append_column(
            column, pa.array(state_values[column], type=pa.float64())
        )

    expected_names = base_names + list(STATE_COLUMNS)
    if list(table.column_names) != expected_names:
        raise AssertionError("状态列没有正确追加到面板右侧。")

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

    non_null_counts = {
        column: int(np.isfinite(values).sum())
        for column, values in state_values.items()
    }
    return {
        "panel_path": panel_path,
        "preview_path": preview_path,
        "row_count": int(table.num_rows),
        "column_count": int(table.num_columns),
        "replaced_existing_state_columns": sorted(
            set(original_names) & set(STATE_COLUMNS)
        ),
        "non_null_counts": non_null_counts,
    }


def count_state_switches(states_by_month: pd.Series) -> int:
    """统计相邻自然月之间状态发生翻转的次数，缺失月份不参与比较。"""
    ordered = states_by_month.sort_index()
    previous = ordered.shift(1)
    # PeriodIndex 相邻差值是月份偏移对象，必须先取 ordinal 才能和 1 比较。
    month_ordinals = pd.Series(ordered.index.asi8, index=ordered.index)
    consecutive = month_ordinals.diff() == 1
    comparable = ordered.notna() & previous.notna() & consecutive
    return int((ordered[comparable] != previous[comparable]).sum())


def build_check_tables(
    state_table: pd.DataFrame, panel_path: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成月度明细和汇总两张校验表。

    汇总口径基于 panel_base 的月份范围：分别统计全部面板月份和
    is_insample_future_ret_6m=1 月份内各状态的分布与切换次数。
    """
    panel_flags = pd.read_parquet(
        panel_path, columns=[Config.COLUMN_MONTH_DATE, INSAMPLE_FLAG_COLUMN]
    )
    panel_flags[Config.COLUMN_MONTH_DATE] = pd.to_datetime(
        panel_flags[Config.COLUMN_MONTH_DATE], errors="coerce"
    )
    month_periods = panel_flags[Config.COLUMN_MONTH_DATE].dt.to_period("M")
    panel_months = pd.PeriodIndex(sorted(month_periods.unique()), freq="M")
    insample_months = pd.PeriodIndex(
        sorted(
            month_periods[panel_flags[INSAMPLE_FLAG_COLUMN] == 1].unique()
        ),
        freq="M",
    )

    monthly_detail = state_table.copy()
    monthly_detail.insert(0, "month", monthly_detail.index.astype(str))
    monthly_detail["in_panel_months"] = monthly_detail.index.isin(panel_months)
    monthly_detail["in_insample_6m_months"] = monthly_detail.index.isin(
        insample_months
    )
    monthly_detail = monthly_detail.reset_index(drop=True)

    summary_rows = []
    for column in STATE_COLUMNS:
        full_series = state_table[column]
        panel_series = full_series.reindex(panel_months)
        insample_series = full_series.reindex(insample_months)
        non_missing = full_series.dropna()
        summary_rows.append(
            {
                "state_column": column,
                "first_valid_month": str(non_missing.index.min()),
                "last_valid_month": str(non_missing.index.max()),
                "panel_months_total": len(panel_months),
                "panel_months_state_1": int((panel_series == 1.0).sum()),
                "panel_months_state_-1": int((panel_series == -1.0).sum()),
                "panel_months_state_nan": int(panel_series.isna().sum()),
                "panel_state_switches": count_state_switches(panel_series),
                "insample_months_total": len(insample_months),
                "insample_months_state_1": int((insample_series == 1.0).sum()),
                "insample_months_state_-1": int(
                    (insample_series == -1.0).sum()
                ),
                "insample_months_state_nan": int(insample_series.isna().sum()),
                "insample_state_switches": count_state_switches(
                    insample_series
                ),
            }
        )
    summary = pd.DataFrame(summary_rows)
    return monthly_detail, summary


def write_check_workbook(
    monthly_detail: pd.DataFrame,
    summary: pd.DataFrame,
    check_output_path: Path,
) -> None:
    """把校验表写成两个 sheet 的 Excel 工作簿。"""
    temporary_check = make_temporary_path(check_output_path)
    try:
        with pd.ExcelWriter(temporary_check) as writer:
            summary.to_excel(writer, sheet_name="summary", index=False)
            monthly_detail.to_excel(
                writer, sheet_name="monthly_detail", index=False
            )
        check_read_back = pd.read_excel(temporary_check, sheet_name="summary")
        if len(check_read_back) != len(summary):
            raise AssertionError("校验表回读后的行数不一致。")
        os.replace(temporary_check, check_output_path)
    finally:
        temporary_check.unlink(missing_ok=True)


def print_summary(
    panel_summaries: list[dict[str, object]],
    summary: pd.DataFrame,
    check_output_path: Path,
) -> None:
    """打印每个面板的写入结果和状态分布摘要。"""
    for panel_summary in panel_summaries:
        print(f"面板：{panel_summary['panel_path']}")
        if panel_summary["preview_path"] is not None:
            print(f"  预览：{panel_summary['preview_path']}")
        replaced = panel_summary["replaced_existing_state_columns"]
        if replaced:
            print(f"  重复运行，已替换旧状态列：{replaced}")
        print(
            f"  行数：{panel_summary['row_count']:,}；"
            f"列数：{panel_summary['column_count']:,}"
        )
        non_null_counts = panel_summary["non_null_counts"]
        for column in STATE_COLUMNS:
            print(f"  {column} 非缺失行数：{non_null_counts[column]:,}")
    print(f"校验表：{check_output_path}")
    print(summary.to_string(index=False))


def generate_market_condition_columns(
    index_input_path: Path = DEFAULT_INDEX_INPUT_PATH,
    style_input_path: Path = DEFAULT_STYLE_INPUT_PATH,
    industry_input_path: Path = DEFAULT_INDUSTRY_INPUT_PATH,
    target_paths: Iterable[Path] = DEFAULT_TARGET_PATHS,
    check_output_path: Path = DEFAULT_CHECK_OUTPUT_PATH,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
    write_preview: bool = True,
) -> dict[str, object]:
    """构建市场状态表、追加到全部目标面板并输出校验表。"""
    if preview_rows <= 0:
        raise ValueError("preview_rows 必须是正整数。")

    state_table = build_state_table(
        index_input_path, style_input_path, industry_input_path
    )
    validate_state_table(state_table)

    panel_summaries = [
        append_states_to_panel(
            Path(panel_path),
            state_table,
            preview_rows=preview_rows,
            write_preview=write_preview,
        )
        for panel_path in target_paths
    ]

    # 校验表的样本口径以正式 panel_base 为准。
    monthly_detail, summary = build_check_tables(
        state_table, Config.PANEL_OUTPUT_PATH
    )
    write_check_workbook(monthly_detail, summary, check_output_path)
    return {
        "panel_summaries": panel_summaries,
        "summary": summary,
        "check_output_path": check_output_path,
    }


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    result = generate_market_condition_columns(
        index_input_path=args.index_input,
        style_input_path=args.style_input,
        industry_input_path=args.industry_input,
        target_paths=args.targets,
        check_output_path=args.check_output,
        preview_rows=args.preview_rows,
        write_preview=not args.no_preview,
    )
    print_summary(
        result["panel_summaries"],
        result["summary"],
        result["check_output_path"],
    )


if __name__ == "__main__":
    main()
