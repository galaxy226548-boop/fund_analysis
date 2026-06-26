"""Step 05：为 Consistency 因子生成 q5/q10 分组标签。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from _step_common import load_regression_config, winsorize_settings
from tools.factor_pipeline_tools import add_quantile_groups, require_columns


CONFIG = load_regression_config()
WINSOR_GROUP_COLUMN = winsorize_settings(CONFIG)["group_column"]
FACTOR_GROUP_SUFFIXES = dict(CONFIG["factor_group_suffixes"])


def parse_args() -> argparse.Namespace:
    """读取输入和输出路径。"""

    parser = argparse.ArgumentParser(description="Step 05：生成 q5/q10 标签。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """执行 q5/q10 分组。"""

    args = parse_args()
    data = pd.read_parquet(args.input)
    require_columns(data, list(FACTOR_GROUP_SUFFIXES) + [WINSOR_GROUP_COLUMN], args.input)
    data = add_quantile_groups(
        data=data,
        group_column=WINSOR_GROUP_COLUMN,
        factor_group_suffixes=FACTOR_GROUP_SUFFIXES,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(args.output, index=False)
    print(f"输出：{args.output}，shape={data.shape}")


if __name__ == "__main__":
    main()
