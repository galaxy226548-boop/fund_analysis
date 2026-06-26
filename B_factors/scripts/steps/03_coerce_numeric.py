"""Step 03：把连续变量转换成数值类型。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from _step_common import load_regression_config, winsorize_settings
from tools.factor_pipeline_tools import coerce_numeric_columns, require_columns


CONFIG = load_regression_config()
WINSORIZE_COLUMNS = winsorize_settings(CONFIG)["columns"]


def parse_args() -> argparse.Namespace:
    """读取输入和输出路径。"""

    parser = argparse.ArgumentParser(description="Step 03：连续变量转数值。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """执行数值类型转换。"""

    args = parse_args()
    data = pd.read_parquet(args.input)
    require_columns(data, WINSORIZE_COLUMNS, args.input)
    data = coerce_numeric_columns(data, WINSORIZE_COLUMNS)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(args.output, index=False)
    print(f"输出：{args.output}，shape={data.shape}")


if __name__ == "__main__":
    main()
