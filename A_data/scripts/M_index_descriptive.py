"""
批量计算 A_data/prepared_data/iFind_EDB 目录下每个 M_ 开头文件里每一列指数的月度收益率，
并对结果运行描述性统计分析。

步骤：
1. 扫描 A_data/prepared_data/iFind_EDB 下所有 M_*.xlsx 文件。
2. 通过 return_calculation_set.json 把每个文件里的原始列名映射为统一的变量短名。
3. 对同一个源文件里的所有列计算月度收益率（简单或对数），按日期合并成一张表，
   统一输出到 {源文件名}_mrt.xlsx（一个源文件对应一个输出文件）。
4. 调用 4_descriptive_analysis_tool.py，对同一个源文件的所有收益率列一次性做描述性统计。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_DIR = PROJECT_ROOT / "A_data/prepared_data/iFind_EDB"
VARIABLE_MAP_FILE = PROJECT_ROOT / "A_data/scripts/return_calculation_set.json"
TOOL_SCRIPT = PROJECT_ROOT / "A_data/scripts/4_descriptive_analysis_tool.py"
DESC_OUTPUT_ROOT = PROJECT_ROOT / "A_data/output/descriptive_analysis"

DATE_COL = "日期"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量计算 iFind_EDB 目录下每个 M_ 文件各指数的月度收益率并运行描述性统计。"
    )
    parser.add_argument(
        "--method",
        choices=["simple", "log"],
        default="simple",
        help="收益率计算方式：simple（简单收益率）或 log（对数收益率）。默认 simple。",
    )
    return parser.parse_args()


def load_variable_map() -> dict[str, dict[str, str]]:
    return json.loads(VARIABLE_MAP_FILE.read_text(encoding="utf-8"))


def compute_monthly_return_series(input_file: Path, index_col: str, method: str, ret_col: str) -> pd.DataFrame:
    df = pd.read_excel(input_file, usecols=[DATE_COL, index_col])
    df = df.dropna(subset=[index_col]).sort_values(DATE_COL).reset_index(drop=True)

    if method == "log":
        df[ret_col] = np.log(df[index_col] / df[index_col].shift(1))
    else:
        df[ret_col] = df[index_col].pct_change()

    df = df.dropna(subset=[ret_col])
    return df[[DATE_COL, ret_col]]


def merge_return_series(series_list: list[pd.DataFrame]) -> pd.DataFrame:
    merged = series_list[0]
    for series in series_list[1:]:
        merged = merged.merge(series, on=DATE_COL, how="outer")
    return merged.sort_values(DATE_COL).reset_index(drop=True)


def run_descriptive_analysis(input_path: Path, ret_cols: list[str], label: str, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(TOOL_SCRIPT),
        "--input", str(input_path),
        "--columns", *ret_cols,
        "--prefix", f"{label}月度收益率",
        "--output-dir", str(output_dir),
    ]
    print(f"运行描述性统计分析，输出到 {output_dir}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def process_file(input_file: Path, file_map: dict[str, str], method: str) -> None:
    columns = pd.read_excel(input_file, nrows=0).columns.tolist()
    index_cols = [col for col in columns if col != DATE_COL]

    ret_cols: list[str] = []
    series_list: list[pd.DataFrame] = []
    for index_col in index_cols:
        short_name = file_map.get(index_col)
        if short_name is None:
            raise KeyError(f"{VARIABLE_MAP_FILE} 缺少 {input_file.name} 中列 {index_col} 的变量命名映射")
        ret_col = f"{short_name}_monthly_return"
        series_list.append(compute_monthly_return_series(input_file, index_col, method, ret_col))
        ret_cols.append(ret_col)

    merged = merge_return_series(series_list)
    label = input_file.stem.removeprefix("M_")
    output_file = INPUT_DIR / f"{label}_mrt.xlsx"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(output_file, index=False)
    print(f"[{input_file.name}] 已保存 {len(merged)} 行、{len(ret_cols)} 列月度收益率到 {output_file}")

    desc_output_dir = DESC_OUTPUT_ROOT / label
    run_descriptive_analysis(output_file, ret_cols, label, desc_output_dir)


def main() -> None:
    args = parse_args()
    print(f"收益率计算方式：{args.method}")

    variable_map = load_variable_map()
    input_files = sorted(INPUT_DIR.glob("M_*.xlsx"))
    if not input_files:
        raise FileNotFoundError(f"{INPUT_DIR} 下没有找到 M_ 开头的文件")

    for input_file in input_files:
        file_map = variable_map.get(input_file.name)
        if file_map is None:
            raise KeyError(f"{VARIABLE_MAP_FILE} 缺少 {input_file.name} 的变量命名映射")
        process_file(input_file, file_map, method=args.method)


if __name__ == "__main__":
    main()
