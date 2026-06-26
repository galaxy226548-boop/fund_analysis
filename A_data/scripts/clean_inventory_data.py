#!/usr/bin/env python3
"""Clean inventory-listed source files into parquet datasets."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_PACKAGES = ("pandas", "openpyxl", "pyarrow")
SUPPORTED_SOURCES = {"iFind", "wind_EDB", "FRED"}
DIRECT_TABLE_SOURCES = {"wind_asset", "wind_debt_index_trend", "wind_index_valuation"}
EXPLICIT_SKIPS: set[str] = set()
METADATA_LABELS = ("频率", "单位", "指标ID", "来源", "更新时间", "指标名称")
SOURCE_TEXT_RE = re.compile(r"(Wind|同花顺|iFinD|iFind)", re.IGNORECASE)


@dataclass
class Candidate:
    output_name: str
    field_name: str
    series: Any
    source_file: str
    data_source: str
    unit: str | None
    conversion: str
    update_time: Any
    first_valid_time: Any
    inventory_order: int
    frequency: str

    @property
    def decision_time(self) -> Any:
        return self.update_time if self.update_time is not None else self.first_valid_time


def check_dependencies() -> None:
    missing = []
    for package in REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
        except ImportError:
            missing.append(package)
    if missing:
        raise SystemExit(
            "Missing required Python packages: "
            + ", ".join(missing)
            + "\nInstall them in the active environment, for example:\n"
            + "  python -m pip install pandas openpyxl pyarrow"
        )


def import_pandas():
    import pandas as pd

    return pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", default="A_data/reference/data_inventory_A.json")
    parser.add_argument("--data-root", default="A_data")
    parser.add_argument("--output-dir", default="A_data/output")
    parser.add_argument(
        "--file-name",
        action="append",
        default=[],
        help="Only process inventory records whose file_name matches this value. May be repeated.",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def output_name(clean_data: str) -> str:
    path = Path(clean_data)
    if path.suffix:
        return path.name
    return f"{path.name}.parquet"


def output_stem(name: str) -> str:
    return Path(name).stem


def load_inventory(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        inventory = json.load(f)
    try:
        rows = inventory["sheets"]["Sheet1"]["records"]
    except KeyError as exc:
        raise SystemExit(f"Unexpected inventory structure in {path}: missing {exc}") from exc
    return rows


def candidate_records(
    rows: list[dict[str, Any]], file_names: set[str] | None = None
) -> tuple[list[tuple[int, dict[str, Any]]], list[tuple[int, dict[str, Any], str]]]:
    processable = []
    unsupported = []
    for idx, row in enumerate(rows):
        clean = row.get("clean_data")
        file_name = row.get("file_name")
        if file_names and file_name not in file_names:
            continue
        if not clean or clean == "none":
            continue
        source = row.get("data_source")
        out = output_name(str(clean))
        if source in SUPPORTED_SOURCES or source in DIRECT_TABLE_SOURCES:
            processable.append((idx, row))
        elif source == "CSMAR_wind" and out == "index_eod.parquet":
            processable.append((idx, row))
        elif source == "wind_macro_event" and out == "macro.parquet":
            processable.append((idx, row))
        else:
            reason = "explicit skip" if source in EXPLICIT_SKIPS else "unsupported source"
            unsupported.append((idx, row, reason))
    return processable, unsupported


def resolve_source_path(row: dict[str, Any], data_root: Path) -> Path:
    rel = str(row.get("relative_path") or "")
    path = data_root / rel
    if path.exists():
        return path
    if rel.startswith("data/"):
        alt = data_root / rel.removeprefix("data/")
        if alt.exists():
            return alt
    return path


def normalize_dates(values: Any, frequency: str):
    pd = import_pandas()
    dates = pd.to_datetime(values, errors="coerce")
    if str(frequency).lower() == "monthly":
        dates = dates.dt.to_period("M").dt.to_timestamp("M")
    return dates


def conversion_for_unit(unit: Any) -> tuple[float, str]:
    if unit is None:
        return 1.0, "none"
    text = str(unit)
    factor = 1.0
    notes = []
    if "%" in text:
        factor /= 100
        notes.append("% / 100")
    if "亿" in text:
        factor *= 100000000
        notes.append("亿 * 100000000")
    elif "万" in text:
        factor *= 10000
        notes.append("万 * 10000")
    return factor, "; ".join(notes) if notes else "none"


def clean_numeric_text(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value in {"", "--", "-", "NA", "N/A", "nan", "None"}:
            return None
    return value


def row_label(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def is_metadata_or_source_row(label: str, values: list[Any]) -> bool:
    if any(token in label for token in METADATA_LABELS):
        return True
    non_empty = [v for v in values if row_label(v)]
    if not non_empty:
        return True
    text = " ".join(row_label(v) for v in non_empty[:4])
    return bool(SOURCE_TEXT_RE.search(text)) and len(non_empty) <= 2


def first_valid_time(series: Any) -> Any:
    valid = series.dropna()
    if valid.empty:
        return None
    return valid.index[0]


def finalized_series(series: Any) -> Any:
    series = series.sort_index()
    if series.index.has_duplicates:
        series = series.groupby(level=0).last()
    return series


def parse_wide_metadata_table(path: Path, sheet_name: str | None, row: dict[str, Any], inventory_order: int) -> list[Candidate]:
    pd = import_pandas()
    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
            try:
                raw = pd.read_csv(path, header=None, encoding=encoding)
                break
            except UnicodeDecodeError as exc:
                last_error = exc
        else:
            raise last_error or UnicodeDecodeError("unknown", b"", 0, 1, "cannot decode csv")
    else:
        raw = pd.read_excel(path, sheet_name=sheet_name or 0, header=None, engine="openpyxl")
    raw = raw.dropna(how="all")
    if raw.empty or raw.shape[1] < 2:
        return []

    field_names = raw.iloc[0, 1:].tolist()
    metadata: dict[str, list[Any]] = {}
    data_row_indexes = []
    for pos in range(1, len(raw)):
        label = row_label(raw.iloc[pos, 0])
        values = raw.iloc[pos, :].tolist()
        matched = next((token for token in METADATA_LABELS if token in label), None)
        if matched:
            metadata[matched] = raw.iloc[pos, 1:].tolist()
            continue
        if is_metadata_or_source_row(label, values):
            continue
        data_row_indexes.append(pos)

    if not data_row_indexes:
        return []

    data = raw.iloc[data_row_indexes, :].copy()
    dates = normalize_dates(data.iloc[:, 0], str(row.get("frequency") or ""))
    data = data.loc[dates.notna()].copy()
    dates = dates[dates.notna()]
    data.index = dates
    units = metadata.get("单位", [None] * len(field_names))
    updates = metadata.get("更新时间", [None] * len(field_names))

    candidates = []
    for offset, field in enumerate(field_names, start=1):
        name = row_label(field)
        if not name or name.lower().startswith("unnamed"):
            continue
        unit = units[offset - 1] if offset - 1 < len(units) else None
        update_value = updates[offset - 1] if offset - 1 < len(updates) else None
        update_time = pd.to_datetime(update_value, errors="coerce")
        if pd.isna(update_time):
            update_time = None
        factor, conversion = conversion_for_unit(unit)
        values = data.iloc[:, offset].map(clean_numeric_text)
        series = finalized_series(pd.to_numeric(values, errors="coerce") * factor)
        candidates.append(
            Candidate(
                output_name=output_name(str(row["clean_data"])),
                field_name=name,
                series=series,
                source_file=str(path),
                data_source=str(row.get("data_source") or ""),
                unit=row_label(unit) or None,
                conversion=conversion,
                update_time=update_time,
                first_valid_time=first_valid_time(series),
                inventory_order=inventory_order,
                frequency=str(row.get("frequency") or ""),
            )
        )
    return candidates


def parse_fred_update(path: Path) -> Any:
    pd = import_pandas()
    try:
        readme = pd.read_excel(path, sheet_name="README", header=None, engine="openpyxl")
    except Exception:
        return None
    pattern = re.compile(r"Data Updated\\s*[: ]\\s*(.+)", re.IGNORECASE)
    for value in readme.to_numpy().ravel():
        text = row_label(value)
        match = pattern.search(text)
        if match:
            parsed = pd.to_datetime(match.group(1), errors="coerce")
            return None if pd.isna(parsed) else parsed
    return None


def parse_fred(path: Path, sheet_name: str | None, row: dict[str, Any], inventory_order: int) -> list[Candidate]:
    pd = import_pandas()
    if sheet_name and sheet_name.upper() == "README":
        return []
    df = pd.read_excel(path, sheet_name=sheet_name or 0, engine="openpyxl")
    if df.empty or df.shape[1] < 2:
        return []
    date_col = df.columns[0]
    dates = normalize_dates(df[date_col], str(row.get("frequency") or ""))
    df = df.loc[dates.notna()].copy()
    df.index = dates[dates.notna()]
    update_time = parse_fred_update(path)
    candidates = []
    for col in df.columns[1:]:
        field = row_label(col)
        if not field:
            continue
        series = finalized_series(pd.to_numeric(df[col].map(clean_numeric_text), errors="coerce"))
        candidates.append(
            Candidate(
                output_name=output_name(str(row["clean_data"])),
                field_name=field,
                series=series,
                source_file=str(path),
                data_source="FRED",
                unit=None,
                conversion="none",
                update_time=update_time,
                first_valid_time=first_valid_time(series),
                inventory_order=inventory_order,
                frequency=str(row.get("frequency") or ""),
            )
        )
    return candidates


def parse_direct_wind_table(path: Path, sheet_name: str | None, row: dict[str, Any], inventory_order: int) -> list[Candidate]:
    pd = import_pandas()
    df = pd.read_excel(path, sheet_name=sheet_name or 0, engine="openpyxl")
    df = df.dropna(how="all")
    if df.empty or df.shape[1] < 2:
        return []
    date_col = "交易日期" if "交易日期" in df.columns else df.columns[0]
    dates = normalize_dates(df[date_col], str(row.get("frequency") or ""))
    df = df.loc[dates.notna()].copy()
    dates = dates[dates.notna()]
    df.index = dates

    candidates = []
    for col in df.columns:
        field = row_label(col)
        if not field or col == date_col:
            continue
        series = finalized_series(pd.to_numeric(df[col].map(clean_numeric_text), errors="coerce"))
        candidates.append(
            Candidate(
                output_name=output_name(str(row["clean_data"])),
                field_name=field,
                series=series,
                source_file=str(path),
                data_source=str(row.get("data_source") or ""),
                unit=None,
                conversion="comma-safe numeric text",
                update_time=None,
                first_valid_time=first_valid_time(series),
                inventory_order=inventory_order,
                frequency=str(row.get("frequency") or ""),
            )
        )
    return candidates


def parse_index_eod(paths_and_rows: list[tuple[Path, dict[str, Any], int]]) -> tuple[Any, dict[str, Candidate]]:
    pd = import_pandas()
    frames = []
    units_by_field: dict[str, str | None] = {}
    source_files = "; ".join(str(path) for path, _, _ in paths_and_rows)
    for path, row, _order in sorted(paths_and_rows, key=lambda item: item[0].name):
        if not re.fullmatch(r"IndexEOD[1-5]\.xlsx", path.name):
            continue
        raw = pd.read_excel(path, sheet_name=row.get("sheet_name") or 0, header=None, engine="openpyxl")
        raw = raw.dropna(how="all")
        if raw.shape[0] < 4:
            continue
        final_cols = [row_label(v) for v in raw.iloc[1, :].tolist()]
        units = [row_label(v) or None for v in raw.iloc[2, :].tolist()]
        data = raw.iloc[3:, :].copy()
        data.columns = final_cols
        date_col = "交易日期" if "交易日期" in data.columns else data.columns[1]
        dates = normalize_dates(data[date_col], "daily")
        data = data.loc[dates.notna()].copy()
        data.index = dates[dates.notna()]
        data = data.drop(columns=[date_col])
        for col in data.columns:
            unit = units[final_cols.index(col)] if col in final_cols else None
            units_by_field[col] = unit
            factor, _ = conversion_for_unit(unit)
            data[col] = pd.to_numeric(data[col].map(clean_numeric_text), errors="coerce") * factor
        frames.append(data)
    if not frames:
        return pd.DataFrame(), {}

    combined = pd.concat(frames, axis=0).sort_index()
    kept = {}
    for order, col in enumerate(combined.columns):
        unit = units_by_field.get(col)
        _, conversion = conversion_for_unit(unit)
        series = combined[col]
        kept[str(col)] = (
            Candidate(
                output_name="index_eod.parquet",
                field_name=str(col),
                series=series,
                source_file=source_files,
                data_source="CSMAR_wind",
                unit=unit,
                conversion=conversion,
                update_time=None,
                first_valid_time=first_valid_time(series),
                inventory_order=order,
                frequency="daily",
            )
        )
    return combined, kept


def parse_macro_event(path: Path, sheet_name: str | None) -> Any:
    pd = import_pandas()
    sheet = sheet_name or "经济数据"
    frame = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    frame = frame.dropna(how="all").copy()
    if "记录类型" in frame.columns:
        frame = frame.loc[frame["记录类型"].astype(str).str.strip() == "经济数据"].copy()
    for column in ("日期时间", "日期"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    for column in ("前值", "预测值", "今值"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "日期时间" in frame.columns:
        frame = frame.sort_values("日期时间")
    return frame.reset_index(drop=True)


def write_macro_fields_md(path: Path, source_path: Path, sheet_name: str, frame: Any) -> None:
    lines = [
        "# macro.parquet fields",
        "",
        f"Source file: {source_path}",
        f"Source sheet: {sheet_name}",
        "Transform: kept only the economic-data sheet/records from the macro event workbook.",
        "",
        "| field | dtype |",
        "| --- | --- |",
    ]
    for column, dtype in frame.dtypes.items():
        lines.append(f"| {column} | {dtype} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def candidate_sort_key(candidate: Candidate) -> tuple[int, Any, int]:
    if candidate.update_time is not None:
        return (2, candidate.update_time, candidate.inventory_order)
    if candidate.first_valid_time is not None:
        return (1, candidate.first_valid_time, candidate.inventory_order)
    return (0, 0, candidate.inventory_order)


def choose_fields(candidates: list[Candidate]) -> tuple[dict[str, Candidate], list[tuple[Candidate, Candidate, str]]]:
    kept: dict[str, Candidate] = {}
    removed = []
    for candidate in candidates:
        previous = kept.get(candidate.field_name)
        if previous is None:
            kept[candidate.field_name] = candidate
            continue
        if candidate_sort_key(candidate) >= candidate_sort_key(previous):
            kept[candidate.field_name] = candidate
            removed.append((previous, candidate, "replaced by newer duplicate or later inventory record"))
        else:
            removed.append((candidate, previous, "older duplicate removed"))
    return kept, removed


def format_time(value: Any) -> str:
    pd = import_pandas()
    if value is None or pd.isna(value):
        return ""
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return str(value)


def write_fields_md(path: Path, output: str, kept: dict[str, Candidate], removed: list[tuple[Candidate, Candidate, str]]) -> None:
    lines = [
        f"# {output} fields",
        "",
        "## Kept fields",
        "",
        "| field | source_file | data_source | unit | conversion | decision_time | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for field, candidate in sorted(kept.items()):
        lines.append(
            f"| {field} | {candidate.source_file} | {candidate.data_source} | {candidate.unit or ''} | "
            f"{candidate.conversion} | {format_time(candidate.decision_time)} | kept latest field |"
        )
    lines.extend(["", "## Removed duplicates", ""])
    if removed:
        lines.extend(
            [
                "| removed_field | removed_source | removed_time | kept_field | kept_source | kept_time | reason |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for deleted, kept_candidate, reason in removed:
            lines.append(
                f"| {deleted.field_name} | {deleted.source_file} | {format_time(deleted.decision_time)} | "
                f"{kept_candidate.field_name} | {kept_candidate.source_file} | "
                f"{format_time(kept_candidate.decision_time)} | {reason} |"
            )
    else:
        lines.append("No duplicate fields removed.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_unsupported(path: Path, unsupported: list[tuple[int, dict[str, Any], str]]) -> None:
    lines = [
        "# Unsupported files",
        "",
        "| order | clean_data | data_source | frequency | relative_path | sheet_name | reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for order, row, reason in unsupported:
        lines.append(
            f"| {order} | {row.get('clean_data') or ''} | {row.get('data_source') or ''} | "
            f"{row.get('frequency') or ''} | {row.get('relative_path') or ''} | "
            f"{row.get('sheet_name') or ''} | {reason} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_clean_frame(frame: Any, out_path: Path) -> None:
    suffix = out_path.suffix.lower()
    if suffix == ".parquet":
        frame.to_parquet(out_path)
        return
    if suffix in {".xlsx", ".xls"}:
        excel_frame = frame.reset_index()
        index_col = frame.index.name or excel_frame.columns[0]
        if index_col in excel_frame.columns:
            excel_frame = excel_frame.rename(columns={index_col: "交易日期"})
        excel_frame.to_excel(out_path, index=False)
        return
    frame.to_parquet(out_path.with_suffix(".parquet"))


def run_dry_run(rows: list[dict[str, Any]], processable: list[tuple[int, dict[str, Any]]], unsupported: list[tuple[int, dict[str, Any], str]]) -> None:
    print(f"Inventory rows: {len(rows)}")
    print(f"Will process: {len(processable)} records")
    for order, row in processable:
        print(
            f"  PROCESS {order}: {row.get('data_source')} -> {output_name(str(row.get('clean_data')))} "
            f"| {row.get('relative_path')} | {row.get('sheet_name')}"
        )
    print(f"Unsupported/skipped: {len(unsupported)} records")
    for order, row, reason in unsupported:
        print(
            f"  UNSUPPORTED {order}: {row.get('data_source')} -> {row.get('clean_data')} "
            f"| {row.get('relative_path')} | {reason}"
        )


def main() -> None:
    args = parse_args()
    rows = load_inventory(Path(args.inventory))
    selected_file_names = set(args.file_name) if args.file_name else None
    processable, unsupported = candidate_records(rows, selected_file_names)
    if args.dry_run:
        run_dry_run(rows, processable, unsupported)
        return

    check_dependencies()
    pd = import_pandas()
    data_root = Path(args.data_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    by_output: dict[str, list[Candidate]] = {}
    index_eod_rows: list[tuple[Path, dict[str, Any], int]] = []
    macro_event_rows: list[tuple[Path, dict[str, Any], int]] = []
    failures: list[tuple[int, dict[str, Any], str]] = []

    for order, row in processable:
        path = resolve_source_path(row, data_root)
        if not path.exists():
            failures.append((order, row, f"missing source file: {path}"))
            continue
        out = output_name(str(row["clean_data"]))
        source = row.get("data_source")
        try:
            if source == "CSMAR_wind" and out == "index_eod.parquet":
                index_eod_rows.append((path, row, order))
                continue
            if source == "wind_macro_event" and out == "macro.parquet":
                macro_event_rows.append((path, row, order))
                continue
            if source == "FRED":
                candidates = parse_fred(path, row.get("sheet_name"), row, order)
            elif source in {"iFind", "wind_EDB"}:
                candidates = parse_wide_metadata_table(path, row.get("sheet_name"), row, order)
            elif source in DIRECT_TABLE_SOURCES:
                candidates = parse_direct_wind_table(path, row.get("sheet_name"), row, order)
            else:
                failures.append((order, row, f"unsupported source during parse: {source}"))
                continue
        except Exception as exc:
            failures.append((order, row, f"parse failed: {exc}"))
            continue
        by_output.setdefault(out, []).extend(candidates)

    if index_eod_rows:
        try:
            index_frame, index_fields = parse_index_eod(index_eod_rows)
            if not index_frame.empty:
                index_path = output_dir / "index_eod.parquet"
                index_frame.index.name = "date"
                index_frame.to_parquet(index_path)
                index_frame.head(5).to_excel(output_dir / "index_eod_preview.xlsx")
                write_fields_md(output_dir / "index_eod_fields.md", "index_eod.parquet", index_fields, [])
                print(f"Wrote {index_path} ({index_frame.shape[0]} rows x {index_frame.shape[1]} columns)")
        except Exception as exc:
            first_order, first_row = index_eod_rows[0][2], index_eod_rows[0][1]
            failures.append((first_order, first_row, f"index_eod parse failed: {exc}"))

    if macro_event_rows:
        path, row, order = macro_event_rows[-1]
        sheet_name = row.get("sheet_name") or "经济数据"
        try:
            macro_frame = parse_macro_event(path, sheet_name)
            macro_path = output_dir / "macro.parquet"
            macro_frame.to_parquet(macro_path)
            macro_frame.head(5).to_excel(output_dir / "macro_preview.xlsx", index=False)
            write_macro_fields_md(output_dir / "macro_fields.md", path, sheet_name, macro_frame)
            print(f"Wrote {macro_path} ({macro_frame.shape[0]} rows x {macro_frame.shape[1]} columns)")
        except Exception as exc:
            failures.append((order, row, f"macro parse failed: {exc}"))

    unsupported.extend(failures)

    for out, candidates in sorted(by_output.items()):
        if not candidates:
            continue
        kept, removed = choose_fields(candidates)
        frame = pd.concat({field: candidate.series for field, candidate in kept.items()}, axis=1, sort=True)
        frame = frame.sort_index()
        frame.index.name = "date"
        out_path = output_dir / out
        write_clean_frame(frame, out_path)
        stem = output_stem(out)
        frame.head(5).to_excel(output_dir / f"{stem}_preview.xlsx")
        write_fields_md(output_dir / f"{stem}_fields.md", out, kept, removed)
        print(f"Wrote {out_path} ({frame.shape[0]} rows x {frame.shape[1]} columns)")

    write_unsupported(output_dir / "unsupported_files.md", unsupported)
    print(f"Wrote {output_dir / 'unsupported_files.md'} ({len(unsupported)} records)")


if __name__ == "__main__":
    main()
