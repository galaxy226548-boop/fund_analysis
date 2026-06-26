"""Step 04：按月对连续变量做 winsorize。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from _step_common import load_regression_config, winsorize_settings
from tools.factor_pipeline_tools import require_columns, winsorize_by_month


CONFIG = load_regression_config()
WINSORIZE = winsorize_settings(CONFIG)


def parse_args() -> argparse.Namespace:
    """读取输入和输出路径。"""

    parser = argparse.ArgumentParser(description="Step 04：按月 winsorize。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """执行 winsorize。"""

    args = parse_args()
    data = pd.read_parquet(args.input)
    require_columns(data, WINSORIZE["columns"] + [WINSORIZE["group_column"]], args.input)
    data = winsorize_by_month(
        data=data,
        columns=WINSORIZE["columns"],
        group_column=WINSORIZE["group_column"],
        lower_quantile=WINSORIZE["lower_quantile"],
        upper_quantile=WINSORIZE["upper_quantile"],
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(args.output, index=False)
    print(f"输出：{args.output}，shape={data.shape}")


if __name__ == "__main__":
    main()
