"""Step 01：从原始 panel_base 中选择本次回归需要的列。"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from _step_common import (
    factor_filter_columns,
    keep_columns,
    load_regression_config,
    project_path,
)
from tools.factor_pipeline_tools import normalize_month_date, require_columns


CONFIG = load_regression_config()
KEEP_COLUMNS = keep_columns(CONFIG)
DATE_COL = str(CONFIG["date_col"])
DEFAULT_INPUT_PATH = project_path(str(CONFIG["preprocess_input_path"]))


def parse_args() -> argparse.Namespace:
    """读取输入和输出路径。"""

    parser = argparse.ArgumentParser(description="Step 01：选择回归需要的列。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """执行列选择。"""

    args = parse_args()
    data = pd.read_parquet(args.input)
    # Step runner 只在下一步应用基础 sample_filters；这里需要提前确认 per-factor 筛选列也存在并会被保留。
    required_columns = set(KEEP_COLUMNS) | set(factor_filter_columns(CONFIG))
    require_columns(data, required_columns, args.input)

    # 旧大脚本在样本筛选前先统一 month_date 类型；这里保持同样的日期口径。
    data = normalize_month_date(data, DATE_COL)
    data = data.loc[:, KEEP_COLUMNS].copy()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(args.output, index=False)
    print(f"输出：{args.output}，shape={data.shape}")


if __name__ == "__main__":
    main()
