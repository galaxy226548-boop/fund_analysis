"""
计算沪深300指数月度收益率，并对结果运行描述性统计分析。

步骤：
1. 读取 M_HS300_CSI800_CSI1000.xlsx 中的沪深300月度指数。
2. 计算月度收益率（简单或对数），输出到 HS300_mrt.xlsx。
3. 调用 4_descriptive_analysis_tool.py 对收益率做描述性统计。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]

INPUT_FILE = PROJECT_ROOT / "A_data/prepared_data/iFind_EDB/M_HS300_CSI800_CSI1000.xlsx"
OUTPUT_FILE = PROJECT_ROOT / "A_data/prepared_data/iFind_EDB/HS300_mrt.xlsx"
TOOL_SCRIPT = PROJECT_ROOT / "A_data/scripts/4_descriptive_analysis_tool.py"
DESC_OUTPUT_DIR = PROJECT_ROOT / "A_data/output/descriptive_analysis/HS300"

INDEX_COL = "沪深300指数:月:最后一条"
DATE_COL = "日期"
RET_COL = "HS300_monthly_return"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="计算沪深300月度收益率并运行描述性统计。")
    parser.add_argument(
        "--method",
        choices=["simple", "log"],
        default="simple",
        help="收益率计算方式：simple（简单收益率）或 log（对数收益率）。默认 simple。",
    )
    return parser.parse_args()


def compute_monthly_returns(method: str) -> pd.DataFrame:
    df = pd.read_excel(INPUT_FILE, usecols=[DATE_COL, INDEX_COL])
    df = df.dropna(subset=[INDEX_COL]).sort_values(DATE_COL).reset_index(drop=True)

    if method == "log":
        df[RET_COL] = np.log(df[INDEX_COL] / df[INDEX_COL].shift(1))
    else:
        df[RET_COL] = df[INDEX_COL].pct_change()

    df = df.dropna(subset=[RET_COL])
    return df[[DATE_COL, RET_COL]]


def run_descriptive_analysis(input_path: Path) -> None:
    DESC_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(TOOL_SCRIPT),
        "--input", str(input_path),
        "--columns", RET_COL,
        "--prefix", "HS300月度收益率",
        "--output-dir", str(DESC_OUTPUT_DIR),
    ]
    print(f"\n运行描述性统计分析，输出到 {DESC_OUTPUT_DIR}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    args = parse_args()

    print(f"收益率计算方式：{args.method}")
    result = compute_monthly_returns(args.method)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    result.to_excel(OUTPUT_FILE, index=False)
    print(f"已保存 {len(result)} 条月度收益率到 {OUTPUT_FILE}")

    run_descriptive_analysis(OUTPUT_FILE)


if __name__ == "__main__":
    main()
