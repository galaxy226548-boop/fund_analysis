"""Step 02：按照 fm_baseline 的样本条件筛选行。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from _step_common import load_regression_config
from tools.factor_pipeline_tools import apply_sample_filters, require_columns


CONFIG = load_regression_config()
SAMPLE_FILTERS = dict(CONFIG["sample_filters"])


def parse_args() -> argparse.Namespace:
    """读取输入和输出路径。"""

    parser = argparse.ArgumentParser(description="Step 02：筛选样本。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """执行样本筛选。"""

    args = parse_args()
    data = pd.read_parquet(args.input)
    require_columns(data, SAMPLE_FILTERS, args.input)
    data = apply_sample_filters(data, SAMPLE_FILTERS)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(args.output, index=False)
    print(f"输出：{args.output}，shape={data.shape}")


if __name__ == "__main__":
    main()
