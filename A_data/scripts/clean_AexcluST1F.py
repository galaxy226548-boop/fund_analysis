#!/usr/bin/env python3
"""Clean AexcluST1F financial statement files and IndexStatement.xlsx.

This script processes:
- IS_AexcluST1F.xlsx -> Astock_IS.parquet
- directCF_AexcluST1F.xlsx -> Astock_directCF.parquet
- indirectCF_AexcluST1F.xlsx -> Astock_indirectCF.parquet
- DeltaE_AexcluST1F_1.xlsx + DeltaE_AexcluST1F_2.xlsx -> Astock_DeltaE.parquet
- BS_AexcluST1F.xlsx -> BS_AexcluST1F.parquet
- Ashare_profit.xlsx -> Ashare_profit.parquet
- IndexStatement.xlsx -> IndexStatement.xlsx (cleaned)

All outputs are saved to A_data/prepared_data/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Constants
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
A_DATA_ROOT = PROJECT_ROOT / "A_data"
DATA_DIR = PROJECT_ROOT / "A_data/data"
UPDATE_DIR = PROJECT_ROOT / "A_data/data/update"
OUTPUT_DIR = PROJECT_ROOT / "A_data/prepared_data"
REFERENCE_DIR = PROJECT_ROOT / "A_data/reference"
INVENTORY_PATH = PROJECT_ROOT / "A_data/reference/data_inventory_A.json"

# File mappings for AexcluST1F files (3-row header: English, Chinese, Unit)
AEXCLU_FILES = {
    "IS": ("IS_AexcluST1F.xlsx", "Astock_IS.parquet"),
    "directCF": ("directCF_AexcluST1F.xlsx", "Astock_directCF.parquet"),
    "indirectCF": ("indirectCF_AexcluST1F.xlsx", "Astock_indirectCF.parquet"),
}

DELTA_E_FILES = ["DeltaE_AexcluST1F_1.xlsx", "DeltaE_AexcluST1F_2.xlsx"]
DELTA_E_OUTPUT = "Astock_DeltaE.parquet"

INDEX_STATEMENT = ("IndexStatement.xlsx", "IndexStatement.xlsx")
FIELD_DICTIONARY_OUTPUT = "AexcluST1F_field_dictionary.md"
FIELD_TXT_PATTERN = "*AexcluST1F.txt"
FIELD_LINE_RE = re.compile(r"^(?P<field>\S+)\s+\[(?P<name>.*?)\]\s*-\s*(?P<description>.*)$")
FIELD_DOC_DATA_SOURCE = "CSMAR_FS"
SPLIT_FILE_SUFFIX_RE = re.compile(r"_\d+$")

# Dedupe keys
CF_IS_DEDUPE_COLS = ["Stkcd", "Accper", "Typrep", "IfCorrect", "DeclareDate"]
DELTA_E_DEDUPE_COLS = ["Stkcd", "Accper", "Typrep", "DataSources", "SubjectCode"]

BASE_AEXCLU_FILES = {
    "BS": ("BS_AexcluST1F.xlsx", "BS_AexcluST1F.parquet", CF_IS_DEDUPE_COLS, []),
    "Ashare_profit": (
        "Ashare_profit.xlsx",
        "Ashare_profit.parquet",
        ["Stkcd", "Accper", "Typrep"],
        ["Indcd", "Indnme", "Indcd1", "Indnme1"],
    ),
}

# Key columns that need special handling
STRING_ZFILL_COLS = ["Stkcd", "Indexcd"]
DATE_COLS = ["Accper", "DeclareDate", "Date", "date"]
KEEP_AS_STRING_COLS = ["ShortName", "Typrep", "DataSources", "SubjectCode", "SubjectName"]
TYPREP_KEEP_VALUE = "A"
PUBDATE_SOURCE_DATE_COLS = ["Accper", "Date", "date"]
PUBDATE_ALLOWED_MONTH_DAYS = {"01-01", "03-31", "06-30", "09-30", "12-31"}


def read_aexclu_file(path: Path) -> tuple[pd.DataFrame, dict[str, tuple[str, str]]]:
    """Read AexcluST1F file with 3-row header structure.

    Row 0: English field names (used as column names)
    Row 1: Chinese field names
    Row 2: Units
    Row 3+: Data

    Returns:
        tuple of (data_df, field_metadata) where field_metadata maps
        field_name -> (chinese_name, unit)
    """
    raw = pd.read_excel(path, header=None, engine="openpyxl")
    raw = raw.dropna(how="all")

    if raw.shape[0] < 4:
        print(f"Warning: {path.name} has less than 4 rows, skipping")
        return pd.DataFrame(), {}

    # Extract header info
    field_names = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(raw.iloc[0])]
    chinese_names = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[1]]
    units = [str(v).strip() if pd.notna(v) else "" for v in raw.iloc[2]]

    # Build field metadata
    field_meta = {}
    for i, fname in enumerate(field_names):
        field_meta[fname] = (chinese_names[i], units[i])

    # Extract data (from row 3 onwards)
    data = raw.iloc[3:].copy()
    data.columns = field_names
    data = data.reset_index(drop=True)

    return data, field_meta


def clean_string_series(series: pd.Series) -> pd.Series:
    """Strip strings while preserving missing values as missing values."""
    return series.where(series.notna(), pd.NA).astype("string").str.strip()


def clean_aexclu_df(df: pd.DataFrame, extra_string_cols: list[str] | None = None) -> pd.DataFrame:
    """Clean AexcluST1F dataframe.

    - Stkcd: string, zfill(6)
    - Accper, DeclareDate: convert to date
    - ShortName, Typrep, DataSources, SubjectCode, SubjectName: keep as string
    - extra_string_cols: additional fields to keep as string, e.g. industry fields
    - IfCorrect: numeric
    - Other columns: numeric coercion
    - No NaN filling
    """
    df = df.copy()
    string_cols = set(KEEP_AS_STRING_COLS)
    if extra_string_cols:
        string_cols.update(extra_string_cols)

    for col in df.columns:
        if col in STRING_ZFILL_COLS:
            df[col] = clean_string_series(df[col]).str.zfill(6)
        elif col in DATE_COLS:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif col in string_cols:
            df[col] = clean_string_series(df[col])
        elif col == "IfCorrect":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            # Try numeric conversion for all other columns
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = add_pubdate_if_period_dates(df)

    return df


def filter_typrep_a(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only consolidated A-report rows when Typrep is available."""
    if "Typrep" not in df.columns:
        return df
    return df.loc[df["Typrep"].eq(TYPREP_KEEP_VALUE)].copy()


def clean_index_statement_df(df: pd.DataFrame) -> pd.DataFrame:
    """Clean IndexStatement dataframe.

    - Indexcd: string, zfill(6)
    - Date: convert to date
    - Other columns: numeric coercion
    """
    df = df.copy()

    for col in df.columns:
        if col == "Indexcd":
            df[col] = df[col].astype(str).str.strip().str.zfill(6)
        elif col == "Date":
            df[col] = pd.to_datetime(df[col], errors="coerce")
        else:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = add_pubdate_if_period_dates(df)

    return df


def add_pubdate_if_period_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Add PubDate when the period date column uses standard report dates.

    Trigger only when the source date column's non-null month-day values are
    at most five and all belong to the known report-date set.
    """
    date_col = next((col for col in PUBDATE_SOURCE_DATE_COLS if col in df.columns), None)
    if date_col is None:
        return df

    dates = pd.to_datetime(df[date_col], errors="coerce")
    month_days = set(dates.dropna().dt.strftime("%m-%d").unique())
    if not month_days or len(month_days) > 5 or not month_days.issubset(PUBDATE_ALLOWED_MONTH_DAYS):
        return df

    pub_dates = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    mappings = {
        "01-01": (0, 4, 30),
        "03-31": (0, 4, 30),
        "06-30": (0, 8, 31),
        "09-30": (0, 10, 31),
        "12-31": (1, 4, 30),
    }
    source_month_days = dates.dt.strftime("%m-%d")
    source_years = dates.dt.year
    for month_day, (year_offset, month, day) in mappings.items():
        mask = source_month_days.eq(month_day) & source_years.notna()
        if not mask.any():
            continue
        pub_dates.loc[mask] = pd.to_datetime(
            {
                "year": source_years.loc[mask].astype("int64") + year_offset,
                "month": month,
                "day": day,
            }
        )

    df["PubDate"] = pub_dates
    return df


def dedupe_df(df: pd.DataFrame, key_cols: list[str]) -> pd.DataFrame:
    """Deduplicate dataframe by key columns, keeping last occurrence.

    Handles NaN in key columns by sorting NaN last.
    """
    existing_keys = [c for c in key_cols if c in df.columns]
    if not existing_keys:
        return df

    # Sort by key columns (NaN goes last)
    df_sorted = df.sort_values(by=existing_keys, na_position="last")

    # Drop duplicates, keep last
    df_deduped = df_sorted.drop_duplicates(subset=existing_keys, keep="last")

    return df_deduped.reset_index(drop=True)


def save_field_md(field_meta: dict[str, tuple[str, str]], output_path: Path, source_file: str) -> None:
    """Save field documentation in markdown format."""
    lines = [
        f"# {output_path.stem} fields",
        "",
        f"Source file: {source_file}",
        "",
        "| field | chinese_name | unit |",
        "| --- | --- | --- |",
    ]
    for fname, (cname, unit) in field_meta.items():
        lines.append(f"| {fname} | {cname} | {unit} |")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Wrote {output_path}")


def markdown_escape(value: Any) -> str:
    """Escape a value for markdown table cells."""
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def display_path(path: Path) -> str:
    """Return a project-relative path when possible, otherwise an absolute path."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def walk_inventory_records(value: Any) -> list[dict[str, Any]]:
    """Collect row-like dictionaries from the data inventory json."""
    records = []
    if isinstance(value, dict):
        if "file_name" in value and "relative_path" in value:
            records.append(value)
        for child in value.values():
            records.extend(walk_inventory_records(child))
    elif isinstance(value, list):
        for child in value:
            records.extend(walk_inventory_records(child))
    return records


def normalize_source_stem(path: Path) -> str:
    """Normalize split file stems like DeltaE_AexcluST1F_1 to DeltaE_AexcluST1F."""
    return SPLIT_FILE_SUFFIX_RE.sub("", path.stem)


def resolve_inventory_path(relative_path: str, data_root: Path = A_DATA_ROOT) -> Path | None:
    """Resolve inventory relative paths across the two layouts used in A_data."""
    rel_path = Path(relative_path)
    candidates = [
        data_root / rel_path,
        data_root / "data" / rel_path,
    ]
    return next((path for path in candidates if path.exists()), None)


def parse_field_txt_line(line: str) -> dict[str, str]:
    """Parse a field description line from an AexcluST1F txt file."""
    clean_line = line.strip()
    match = FIELD_LINE_RE.match(clean_line)
    if not match:
        return {
            "field": clean_line,
            "chinese_name": "",
            "description": "",
        }
    return {
        "field": match.group("field").strip(),
        "chinese_name": match.group("name").strip(),
        "description": match.group("description").strip(),
    }


def find_field_txt_files_from_inventory(
    data_source: str,
    inventory_path: Path,
    data_root: Path = A_DATA_ROOT,
) -> list[Path]:
    """Find txt dictionaries whose matching data files share the requested source."""
    if not inventory_path.exists():
        return []

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = walk_inventory_records(inventory)

    data_stems = {
        normalize_source_stem(Path(record["file_name"]))
        for record in records
        if record.get("data_source") == data_source and record.get("suffix") != ".txt"
    }

    candidates = []
    for record in records:
        if record.get("suffix") != ".txt" or not record.get("relative_path"):
            continue

        txt_stem = Path(record["file_name"]).stem
        if txt_stem not in data_stems:
            continue

        txt_path = resolve_inventory_path(record["relative_path"], data_root=data_root)
        if txt_path is not None:
            candidates.append(txt_path)

    return sorted(set(candidates), key=lambda path: display_path(path))


def find_aexclu_field_txt_files(
    update_dir: Path,
    data_source: str = FIELD_DOC_DATA_SOURCE,
    inventory_path: Path = INVENTORY_PATH,
) -> list[Path]:
    """Find txt dictionaries related to this financial-statement data source."""
    candidates = find_field_txt_files_from_inventory(
        data_source=data_source,
        inventory_path=inventory_path,
    )
    if candidates:
        return candidates

    candidates = list(update_dir.glob(FIELD_TXT_PATTERN))

    # Fallback for environments without an inventory file.
    data_dir = update_dir.parent
    for name in ["Ashare_profit.txt", "BS_AexcluST1F.txt"]:
        txt_path = data_dir / name
        if txt_path.exists():
            candidates.append(txt_path)

    return sorted(set(candidates), key=lambda path: display_path(path))


def build_aexclu_field_dictionary(
    update_dir: Path,
    output_path: Path,
    data_source: str = FIELD_DOC_DATA_SOURCE,
    inventory_path: Path = INVENTORY_PATH,
) -> Path | None:
    """Merge same-data-source txt field dictionaries into one markdown file."""
    txt_files = find_aexclu_field_txt_files(
        update_dir=update_dir,
        data_source=data_source,
        inventory_path=inventory_path,
    )
    if not txt_files:
        print(f"Warning: no field txt files found for data_source={data_source}")
        return None

    rows_by_source: list[tuple[Path, list[dict[str, str]]]] = []
    for txt_path in txt_files:
        lines = txt_path.read_text(encoding="utf-8-sig").splitlines()
        rows = [parse_field_txt_line(line) for line in lines if line.strip()]
        rows_by_source.append((txt_path, rows))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AexcluST1F Field Dictionary",
        "",
        f"Merged from the source txt files associated with data_source `{data_source}`.",
        "",
        "## Source Files",
        "",
    ]
    for txt_path, rows in rows_by_source:
        rel_path = display_path(txt_path)
        lines.append(f"- `{rel_path}` ({len(rows)} fields)")

    lines.extend(["", "## Fields", ""])

    for txt_path, rows in rows_by_source:
        title = txt_path.stem
        rel_path = display_path(txt_path)
        lines.extend(
            [
                f"### {title}",
                "",
                f"Source: `{rel_path}`",
                "",
                "| field | chinese_name | description |",
                "| --- | --- | --- |",
            ]
        )
        for row in rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_escape(row["field"]),
                        markdown_escape(row["chinese_name"]),
                        markdown_escape(row["description"]),
                    ]
                )
                + " |"
            )
        lines.append("")

    output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"  Wrote {output_path}")
    return output_path


def print_df_summary(df: pd.DataFrame, name: str) -> None:
    """Print summary statistics for dataframe."""
    print(f"\n{name}:")
    print(f"  Rows: {len(df)}")

    # Date range for Accper or Date
    date_col = "Accper" if "Accper" in df.columns else "Date" if "Date" in df.columns else None
    if date_col and df[date_col].notna().any():
        print(f"  {date_col} range: {df[date_col].min()} ~ {df[date_col].max()}")

    # Non-null counts for key columns
    key_cols = [c for c in ["Stkcd", "Indexcd", "Typrep", "SubjectCode"] if c in df.columns]
    for col in key_cols:
        non_null = df[col].notna().sum()
        print(f"  {col} non-null: {non_null}")


def process_single_aexclu(
    filename: str,
    output_name: str,
    dedupe_cols: list[str],
    output_dir: Path,
    source_dir: Path,
    extra_string_cols: list[str] | None = None,
) -> pd.DataFrame | None:
    """Process a single AexcluST1F file."""
    source_path = source_dir / filename
    if not source_path.exists():
        print(f"Warning: {source_path} not found, skipping")
        return None

    print(f"\nProcessing {filename}...")

    # Read
    df, field_meta = read_aexclu_file(source_path)
    if df.empty:
        return None

    rows_before = len(df)

    # Clean
    df = clean_aexclu_df(df, extra_string_cols=extra_string_cols)

    # Keep Typrep == A only
    rows_before_filter = len(df)
    df = filter_typrep_a(df)
    if len(df) < rows_before_filter:
        print(f"  Typrep filter: {rows_before_filter} -> {len(df)} rows ({rows_before_filter - len(df)} removed)")

    # Dedupe
    df = dedupe_df(df, dedupe_cols)
    rows_after = len(df)

    if rows_after < rows_before:
        print(f"  Deduped: {rows_before} -> {rows_after} rows ({rows_before - rows_after} removed)")

    # Print summary
    print_df_summary(df, output_name)

    # Save parquet
    output_path = output_dir / output_name
    df.to_parquet(output_path, index=False)
    print(f"  Wrote {output_path}")

    # Save field documentation
    field_md_path = output_dir / f"{Path(output_name).stem}_fields.md"
    save_field_md(field_meta, field_md_path, filename)

    # Save preview
    preview_path = output_dir / f"{Path(output_name).stem}_preview.xlsx"
    df.head(5).to_excel(preview_path, index=False)
    print(f"  Wrote {preview_path}")

    return df


def process_deltaE_files(
    file_list: list[str],
    output_name: str,
    dedupe_cols: list[str],
    output_dir: Path,
    update_dir: Path,
) -> pd.DataFrame | None:
    """Process and merge DeltaE files."""
    print("\nProcessing DeltaE files...")

    frames = []
    field_meta = {}

    for filename in file_list:
        source_path = update_dir / filename
        if not source_path.exists():
            print(f"Warning: {source_path} not found, skipping")
            continue

        print(f"  Reading {filename}...")
        df, meta = read_aexclu_file(source_path)
        if not df.empty:
            frames.append(df)
            field_meta.update(meta)

    if not frames:
        print("No DeltaE files found")
        return None

    # Concat
    df = pd.concat(frames, ignore_index=True)
    rows_before = len(df)
    print(f"  Combined: {rows_before} rows")

    # Clean
    df = clean_aexclu_df(df)

    # Keep Typrep == A only
    rows_before_filter = len(df)
    df = filter_typrep_a(df)
    if len(df) < rows_before_filter:
        print(f"  Typrep filter: {rows_before_filter} -> {len(df)} rows ({rows_before_filter - len(df)} removed)")

    # Dedupe
    df = dedupe_df(df, dedupe_cols)
    rows_after = len(df)

    if rows_after < rows_before:
        print(f"  Deduped: {rows_before} -> {rows_after} rows ({rows_before - rows_after} removed)")

    # Print summary
    print_df_summary(df, output_name)

    # Save parquet
    output_path = output_dir / output_name
    df.to_parquet(output_path, index=False)
    print(f"  Wrote {output_path}")

    # Save field documentation
    field_md_path = output_dir / f"{Path(output_name).stem}_fields.md"
    save_field_md(field_meta, field_md_path, ", ".join(file_list))

    # Save preview
    preview_path = output_dir / f"{Path(output_name).stem}_preview.xlsx"
    df.head(5).to_excel(preview_path, index=False)
    print(f"  Wrote {preview_path}")

    return df


def process_index_statement(
    filename: str,
    output_name: str,
    output_dir: Path,
    update_dir: Path,
) -> pd.DataFrame | None:
    """Process IndexStatement file (single-row header, xlsx output)."""
    source_path = update_dir / filename
    if not source_path.exists():
        print(f"Warning: {source_path} not found, skipping")
        return None

    print(f"\nProcessing {filename}...")

    # Read with single-row header
    df = pd.read_excel(source_path, header=0, engine="openpyxl")
    df = df.dropna(how="all")

    if df.empty:
        return None

    rows_before = len(df)

    # Clean
    df = clean_index_statement_df(df)

    # Print summary
    print_df_summary(df, output_name)

    # Save as xlsx with string format for Indexcd column
    output_path = output_dir / output_name
    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
        workbook = writer.book
        worksheet = writer.sheets["Sheet1"]
        # Format Indexcd column as text (column 0)
        text_format = workbook.add_format({"num_format": "@"})
        worksheet.set_column(0, 0, None, text_format)
    print(f"  Wrote {output_path}")

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--update-dir", type=Path, default=UPDATE_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--field-doc-output",
        type=Path,
        default=None,
        help=f"Markdown path for the merged AexcluST1F txt field dictionary. Defaults to A_data/reference/{FIELD_DICTIONARY_OUTPUT}.",
    )
    parser.add_argument(
        "--field-doc-data-source",
        default=FIELD_DOC_DATA_SOURCE,
        help=f"Inventory data_source used to collect matching txt dictionaries. Defaults to {FIELD_DOC_DATA_SOURCE}.",
    )
    parser.add_argument(
        "--inventory-path",
        type=Path,
        default=INVENTORY_PATH,
        help="Path to data_inventory_A.json used to map txt dictionaries to data sources.",
    )
    parser.add_argument(
        "--field-docs-only",
        action="store_true",
        help="Only merge AexcluST1F txt field dictionaries; do not clean data files.",
    )
    parser.add_argument(
        "--skip-field-docs",
        action="store_true",
        help="Skip writing the merged AexcluST1F txt field dictionary.",
    )
    parser.add_argument(
        "--base-files-only",
        action="store_true",
        help="Only clean BS_AexcluST1F.xlsx and Ashare_profit.xlsx from A_data/data.",
    )
    parser.add_argument(
        "--skip-base-files",
        action="store_true",
        help="Skip cleaning BS_AexcluST1F.xlsx and Ashare_profit.xlsx.",
    )
    args = parser.parse_args()

    base_data_dir = args.base_data_dir
    update_dir = args.update_dir
    output_dir = args.output_dir
    field_doc_output = args.field_doc_output or REFERENCE_DIR / FIELD_DICTIONARY_OUTPUT

    # Create output directory if needed
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source directory: {update_dir}")
    print(f"Base data directory: {base_data_dir}")
    print(f"Output directory: {output_dir}")

    if not args.skip_field_docs:
        print("\nBuilding merged AexcluST1F field dictionary...")
        build_aexclu_field_dictionary(
            update_dir=update_dir,
            output_path=field_doc_output,
            data_source=args.field_doc_data_source,
            inventory_path=args.inventory_path,
        )

    if args.field_docs_only:
        print("\nDone!")
        return

    if not args.skip_base_files:
        for name, (filename, output_name, dedupe_cols, extra_string_cols) in BASE_AEXCLU_FILES.items():
            process_single_aexclu(
                filename=filename,
                output_name=output_name,
                dedupe_cols=dedupe_cols,
                output_dir=output_dir,
                source_dir=base_data_dir,
                extra_string_cols=extra_string_cols,
            )

    if args.base_files_only:
        print("\nDone!")
        return

    # Process AexcluST1F files (IS, directCF, indirectCF)
    for name, (filename, output_name) in AEXCLU_FILES.items():
        process_single_aexclu(
            filename=filename,
            output_name=output_name,
            dedupe_cols=CF_IS_DEDUPE_COLS,
            output_dir=output_dir,
            source_dir=update_dir,
        )

    # Process DeltaE files (merge _1 and _2)
    process_deltaE_files(
        file_list=DELTA_E_FILES,
        output_name=DELTA_E_OUTPUT,
        dedupe_cols=DELTA_E_DEDUPE_COLS,
        output_dir=output_dir,
        update_dir=update_dir,
    )

    # Process IndexStatement (xlsx output)
    process_index_statement(
        filename=INDEX_STATEMENT[0],
        output_name=INDEX_STATEMENT[1],
        output_dir=output_dir,
        update_dir=update_dir,
    )

    print("\nDone!")


if __name__ == "__main__":
    main()
