#!/usr/bin/env python3
"""清洗同花顺 iFind EDB 导出的股票市场数据文件。

脚本接收一个或多个输入文件路径，识别“指标名称 / 频率 / 单位”表头，
清理尾部来源说明与空行，并把清洗结果写入 ``A_data/prepared_data/iFind_EDB``。
每次运行还会更新 ``A_data/prepared_data/iFind_EDB_stkmktdata.json``，记录
清洗文件路径及每个指标的名称、频率和单位。
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "A_data" / "prepared_data" / "iFind_EDB"
DEFAULT_METADATA_PATH = PROJECT_ROOT / "A_data" / "prepared_data" / "iFind_EDB_stkmktdata.json"

HEADER_LABELS = {"指标名称", "频率", "单位"}
MISSING_TEXT = {"", "-", "--", "—", "na", "n/a", "nan", "none", "null"}
SOURCE_ROW_RE = re.compile(r"数据来源\s*[：:]?\s*同花顺\s*i\s*find", re.IGNORECASE)
NUMERIC_TEXT_RE = re.compile(r"^[+-]?(?:\d+(?:[.,]\d+)*|[.,]\d+)(?:[eE][+-]?\d+)?$")


def parse_args() -> argparse.Namespace:
    """读取 macOS 终端传入的文件路径和可选输出位置。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="需要清洗的 Excel、CSV 或 TSV 文件路径")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"清洗文件目录（默认：{DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--metadata-path",
        type=Path,
        default=DEFAULT_METADATA_PATH,
        help=f"JSON 元数据路径（默认：{DEFAULT_METADATA_PATH}）",
    )
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    """将相对路径统一解释为相对于项目根目录。"""
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = PROJECT_ROOT / expanded
    return expanded.resolve()


def display_path(path: Path) -> str:
    """项目内路径写成相对路径，便于 JSON 在不同电脑上使用。"""
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def normalize_text(value: Any) -> str:
    """把表头等单元格转换成去除首尾空白的文本。"""
    if pd.isna(value):
        return ""
    return str(value).strip()


def read_raw_table(path: Path) -> pd.DataFrame:
    """不指定表头读取文件，以免 pandas 提前吞掉 iFind 的多行表头。"""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(path, header=None, dtype=object)
    if suffix == ".csv":
        return pd.read_csv(path, header=None, dtype=object)
    if suffix in {".tsv", ".txt"}:
        return pd.read_csv(path, sep="\t", header=None, dtype=object)
    raise ValueError(f"不支持的文件格式：{path.suffix or '无扩展名'}")


def is_empty_row(row: pd.Series) -> bool:
    """判断一整行是否为空；只包含空白字符串也视为空。"""
    return all(normalize_text(value) == "" for value in row)


def is_source_row(row: pd.Series) -> bool:
    """识别“数据来源：同花顺 iFind”，兼容大小写和中英文冒号。"""
    text = " ".join(normalize_text(value) for value in row if normalize_text(value))
    return bool(SOURCE_ROW_RE.search(text))


def remove_trailing_junk(raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """只检查原文件最后两行，并删除其中的全空行或来源说明行。"""
    cleaned = raw.copy()
    tail_indexes = list(cleaned.index[-2:])

    # 两行分别判断，而不是只从末行连续向上删；这样即使文件结构稍有变化，
    # 只要垃圾内容位于原始文件最后两行内，就仍会被准确移除。
    junk_indexes = [
        index
        for index in tail_indexes
        if is_empty_row(cleaned.loc[index]) or is_source_row(cleaned.loc[index])
    ]
    return cleaned.drop(index=junk_indexes), len(junk_indexes)


def find_header_rows(raw: pd.DataFrame) -> dict[str, int]:
    """在文件前 20 行寻找已知表头标签，并返回它们的行号。"""
    found: dict[str, int] = {}
    for row_number in range(min(20, len(raw))):
        first_cell = normalize_text(raw.iloc[row_number, 0])
        if first_cell in HEADER_LABELS and first_cell not in found:
            found[first_cell] = row_number

    if "指标名称" not in found:
        raise ValueError("前 20 行内没有找到必需的“指标名称”表头")
    return found


def metadata_row(raw: pd.DataFrame, row_number: int | None, width: int) -> list[str | None]:
    """读取频率或单位行；文件缺少该行时为每个指标填入 null。"""
    if row_number is None:
        return [None] * (width - 1)
    values = [normalize_text(value) or None for value in raw.iloc[row_number, 1:width]]
    return values


def unique_names(names: list[str]) -> list[str]:
    """保证列名唯一，避免同名指标在 pandas 中互相覆盖。"""
    seen: dict[str, int] = {}
    result: list[str] = []
    for position, name in enumerate(names, start=1):
        base = name or f"未命名指标_{position}"
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return result


def infer_column_separators(series: pd.Series) -> tuple[str | None, str | None]:
    """从同时含点和逗号的数值推断该列的小数点与千位分隔符。

    例如 ``1.896,84`` 的最后一个符号是逗号，所以推断逗号是小数点、
    点是千位分隔符；``1,896.84`` 则得到相反结论。
    """
    votes: list[str] = []
    for value in series:
        if not isinstance(value, str):
            continue
        text = value.strip().replace("，", ",").replace("。", ".")
        if "," in text and "." in text:
            votes.append("," if text.rfind(",") > text.rfind(".") else ".")

    if not votes:
        return None, None
    decimal = max(set(votes), key=votes.count)
    thousands = "." if decimal == "," else ","
    return decimal, thousands


def parse_numeric_text(
    value: Any,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> tuple[Any, bool]:
    """尝试把带本地化分隔符的单元格转换成数值。

    返回 ``(转换后的值, 是否为无法确认的文本)``。无法安全识别的文本会原样
    保留，避免静默变成缺失值；调用方会把数量和示例写入 JSON 供人工检查。
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return pd.NA, False
    if isinstance(value, bool):
        return value, True
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return pd.NA, False
        return value, False
    if not isinstance(value, str):
        return value, True

    text = value.strip()
    if text.casefold() in MISSING_TEXT:
        return pd.NA, False

    # 常见财务表会用括号表示负数，也可能混入空格或不换行空格。
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()
    text = re.sub(r"[\s\u00a0\u202f']", "", text).replace("，", ",").replace("。", ".")
    if not NUMERIC_TEXT_RE.fullmatch(text):
        return value.strip(), True

    if decimal_separator and thousands_separator:
        normalized = text.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in text and "." in text:
        # 没有足够的列级信息时，以最后出现的符号作为小数点。
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        normalized = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        groups = text.lstrip("+-").split(",")
        if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
            normalized = text.replace(",", "")
        else:
            normalized = text.replace(",", ".")
    elif text.count(".") > 1:
        groups = text.lstrip("+-").split(".")
        if all(len(group) == 3 for group in groups[1:]):
            normalized = text.replace(".", "")
        else:
            normalized = text.replace(".", "", text.count(".") - 1)
    else:
        normalized = text

    try:
        number = float(normalized)
    except ValueError:
        return value.strip(), True
    if negative:
        number = -number
    if number.is_integer():
        return int(number), False
    return number, False


def is_monthly(frequencies: list[str | None]) -> bool:
    """仅当所有已填写的指标频率都是“月”时启用月末日期规则。"""
    available = [value.strip() for value in frequencies if value and value.strip()]
    return bool(available) and all(value == "月" for value in available)


def clean_file(path: Path, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    """清洗单个文件，写出 xlsx，并返回该文件的 JSON 元数据。"""
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"输入文件不存在：{path}")

    raw = read_raw_table(path)
    raw, removed_tail_rows = remove_trailing_junk(raw)
    headers = find_header_rows(raw)

    indicator_row = headers["指标名称"]
    width = raw.shape[1]
    raw_indicator_names = [normalize_text(value) for value in raw.iloc[indicator_row, 1:width]]
    indicator_names = unique_names(raw_indicator_names)
    frequencies = metadata_row(raw, headers.get("频率"), width)
    units = metadata_row(raw, headers.get("单位"), width)

    # 数据从所有已识别表头的最后一行之后开始；其中的全空行不具有业务含义。
    data_start = max(headers.values()) + 1
    data = raw.iloc[data_start:, :width].copy().dropna(how="all")
    if data.empty:
        raise ValueError("移除表头和尾部说明后没有数据行")
    data.columns = ["日期", *indicator_names]

    dates = pd.to_datetime(data.pop("日期"), errors="coerce")
    invalid_date_count = int(dates.isna().sum())
    if invalid_date_count:
        raise ValueError(f"日期列有 {invalid_date_count} 个值无法解析")

    file_updated_at = datetime.fromtimestamp(path.stat().st_mtime)
    file_updated_date = pd.Timestamp(file_updated_at.date())
    monthly = is_monthly(frequencies)
    if monthly:
        # 月频当月数据不能晚于文件实际更新日；历史月份仍保持自然月末。
        month_ends = dates + pd.offsets.MonthEnd(0)
        dates = pd.Series(
            [min(month_end, file_updated_date) for month_end in month_ends],
            index=dates.index,
            dtype="datetime64[ns]",
        )

    unparsed_examples: dict[str, list[str]] = {}
    unparsed_count = 0
    for column in data.columns:
        decimal, thousands = infer_column_separators(data[column])
        converted: list[Any] = []
        examples: list[str] = []
        for value in data[column]:
            parsed, unparsed = parse_numeric_text(value, decimal, thousands)
            converted.append(parsed)
            if unparsed:
                unparsed_count += 1
                if len(examples) < 5:
                    examples.append(str(value))
        data[column] = converted
        if examples:
            unparsed_examples[column] = examples

    data.index = pd.DatetimeIndex(dates, name="日期")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{path.stem}.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl", datetime_format="yyyy-mm-dd") as writer:
        data.to_excel(writer, sheet_name="Sheet1", index=True)
        worksheet = writer.sheets["Sheet1"]
        worksheet.freeze_panes = "B2"
        worksheet.auto_filter.ref = worksheet.dimensions
        worksheet.sheet_view.showGridLines = False

        # 日期列若沿用默认宽度，Excel 会显示成“###”；指标名称较长，则通过
        # 适度加宽并换行，兼顾可读性和横向滚动距离。
        worksheet.column_dimensions["A"].width = 12
        for cell in worksheet["A"][1:]:
            cell.number_format = "yyyy-mm-dd"
        for column_number in range(2, len(data.columns) + 2):
            worksheet.column_dimensions[get_column_letter(column_number)].width = 18
        for cell in worksheet[1]:
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        worksheet.row_dimensions[1].height = 42

    indicators = [
        {"指标名称": name, "频率": frequency, "单位": unit}
        for name, frequency, unit in zip(indicator_names, frequencies, units, strict=True)
    ]
    metadata = {
        "源文件": display_path(path),
        "清洗文件": display_path(output_path),
        "文件最后更新日期": file_updated_at.isoformat(timespec="seconds"),
        "月频日期已按文件更新日校正": monthly,
        "删除的尾部垃圾行数": removed_tail_rows,
        "数据行数": len(data),
        "指标数量": len(indicators),
        "指标": indicators,
        "未解析文本数量": unparsed_count,
        "未解析文本示例": unparsed_examples,
    }
    return output_path, metadata


def update_metadata(path: Path, records: dict[str, dict[str, Any]]) -> None:
    """合并更新 JSON，保留本次未处理文件的既有记录。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {"版本": 1, "文件": {}}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                document.update(loaded)
        except json.JSONDecodeError as exc:
            raise ValueError(f"现有 JSON 无法解析，未覆盖：{path}（{exc}）") from exc

    existing_files = document.get("文件")
    if not isinstance(existing_files, dict):
        existing_files = {}
    existing_files.update(records)
    document["版本"] = 1
    document["文件"] = existing_files
    document["最近更新于"] = datetime.now().astimezone().isoformat(timespec="seconds")

    # 先写临时文件再替换，避免程序中途退出留下半截 JSON。
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def main() -> int:
    """命令行入口：依次处理文件，全部成功后统一更新元数据。"""
    args = parse_args()
    output_dir = resolve_path(args.output_dir)
    metadata_path = resolve_path(args.metadata_path)
    records: dict[str, dict[str, Any]] = {}

    try:
        for input_value in args.files:
            input_path = resolve_path(input_value)
            output_path, metadata = clean_file(input_path, output_dir)
            records[input_path.name] = metadata
            print(f"已清洗：{display_path(input_path)} -> {display_path(output_path)}")
        update_metadata(metadata_path, records)
        print(f"已更新元数据：{display_path(metadata_path)}")
    except (OSError, ValueError) as exc:
        print(f"清洗失败：{exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
