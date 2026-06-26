#!/usr/bin/env python3
"""Compute weekly returns for active equity funds from daily returns.

The input fund-code file is expected to contain one fund code per line. Rows in
FUND_MKT_Quotation_clean.parquet are filtered where ``Symbol`` belongs to that
code set. Weekly returns are compounded from ``ReturnDaily`` as:

    weekly_return = product(1 + ReturnDaily) - 1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
A_DATA_ROOT = PROJECT_ROOT / "A_data"
DEFAULT_CODES_PATH = A_DATA_ROOT / "input" / "主动权益型基金代码.txt"
DEFAULT_PARQUET_PATH = A_DATA_ROOT / "prepared_data" / "FUND_MKT_Quotation_clean.parquet"
DEFAULT_OUTPUT_PATH = A_DATA_ROOT / "output" / "主動權益型基金周回報率.xlsx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codes", type=Path, default=DEFAULT_CODES_PATH, help="主动权益型基金代码文件")
    parser.add_argument(
        "--quotation",
        type=Path,
        default=DEFAULT_PARQUET_PATH,
        help="FUND_MKT_Quotation_clean.parquet 路径",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="输出 xlsx 路径")
    parser.add_argument(
        "--week-frequency",
        default="W-FRI",
        help="周频聚合规则，默认 W-FRI（以周五作为周末日期）",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def normalize_code(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def read_fund_codes(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"基金代码文件不存在: {path}")

    codes: list[str] = []
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        codes.append(normalize_code(line))

    unique_codes = list(dict.fromkeys(codes))
    if not unique_codes:
        raise ValueError(f"基金代码文件为空: {path}")
    return unique_codes


def load_daily_returns(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"行情 parquet 文件不存在: {path}")

    frame = pd.read_parquet(path, columns=["Symbol", "ReturnDaily"], engine="pyarrow")
    if frame.index.name is None:
        frame.index.name = "date"
    if frame.index.name != "date":
        frame = frame.rename_axis("date")

    frame = frame.reset_index()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["Symbol"] = frame["Symbol"].map(normalize_code)
    frame["ReturnDaily"] = pd.to_numeric(frame["ReturnDaily"], errors="coerce")
    return frame.dropna(subset=["date"])


def compound_weekly(group: pd.Series) -> float:
    valid = group.dropna()
    if valid.empty:
        return pd.NA
    return (1.0 + valid).prod() - 1.0


def build_weekly_returns(
    daily_returns: pd.DataFrame,
    fund_codes: list[str],
    week_frequency: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    code_set = set(fund_codes)
    filtered = daily_returns.loc[
        daily_returns["Symbol"].isin(code_set),
        ["date", "Symbol", "ReturnDaily"],
    ].copy()
    filtered = filtered.sort_values(["Symbol", "date"])

    matched_codes = set(filtered["Symbol"].dropna().unique())
    unmatched = pd.DataFrame({"Symbol": [code for code in fund_codes if code not in matched_codes]})

    if filtered.empty:
        weekly = pd.DataFrame(
            columns=[
                "Symbol",
                "week_end_date",
                "week_start_date",
                "observations",
                "weekly_return",
            ]
        )
        return filtered, weekly, unmatched

    weekly = (
        filtered.set_index("date")
        .groupby("Symbol", group_keys=True)
        .resample(week_frequency)["ReturnDaily"]
        .agg(observations="count", weekly_return=compound_weekly)
        .reset_index()
        .rename(columns={"date": "week_end_date"})
    )
    weekly["week_start_date"] = weekly["week_end_date"] - pd.Timedelta(days=6)
    weekly = weekly[
        ["Symbol", "week_end_date", "week_start_date", "observations", "weekly_return"]
    ].sort_values(["Symbol", "week_end_date"])
    return filtered, weekly, unmatched


def write_workbook(
    output_path: Path,
    daily_returns: pd.DataFrame,
    weekly_returns: pd.DataFrame,
    unmatched_codes: pd.DataFrame,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl", datetime_format="yyyy-mm-dd") as writer:
        weekly_returns.to_excel(writer, sheet_name="weekly_return", index=False)
        daily_returns.to_excel(writer, sheet_name="daily_return", index=False)
        unmatched_codes.to_excel(writer, sheet_name="unmatched_codes", index=False)

        workbook = writer.book
        for sheet_name in workbook.sheetnames:
            worksheet = workbook[sheet_name]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for column_cells in worksheet.columns:
                header = column_cells[0].value
                if header in {"weekly_return", "ReturnDaily"}:
                    for cell in column_cells[1:]:
                        cell.number_format = "0.000000"
                    worksheet.column_dimensions[column_cells[0].column_letter].width = 14
                elif header in {"date", "week_end_date", "week_start_date"}:
                    for cell in column_cells[1:]:
                        cell.number_format = "yyyy-mm-dd"
                    worksheet.column_dimensions[column_cells[0].column_letter].width = 14
                else:
                    worksheet.column_dimensions[column_cells[0].column_letter].width = 16


def main() -> int:
    args = parse_args()
    codes_path = resolve_path(args.codes)
    parquet_path = resolve_path(args.quotation)
    output_path = resolve_path(args.output)

    fund_codes = read_fund_codes(codes_path)
    daily_returns = load_daily_returns(parquet_path)
    filtered_daily, weekly_returns, unmatched_codes = build_weekly_returns(
        daily_returns=daily_returns,
        fund_codes=fund_codes,
        week_frequency=args.week_frequency,
    )
    write_workbook(output_path, filtered_daily, weekly_returns, unmatched_codes)

    print(f"读取基金代码: {len(fund_codes)}")
    print(f"匹配到基金代码: {filtered_daily['Symbol'].nunique() if not filtered_daily.empty else 0}")
    print(f"筛选日收益行数: {len(filtered_daily)}")
    print(f"生成周收益行数: {len(weekly_returns)}")
    print(f"输出文件: {output_path}")
    if filtered_daily.empty:
        print("警告: 当前行情表 Symbol 列没有匹配到任何主动权益型基金代码。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
