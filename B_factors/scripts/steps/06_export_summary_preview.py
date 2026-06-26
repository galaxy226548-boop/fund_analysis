"""Step 06：导出最终 parquet、summary JSON 和 preview Excel。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from _step_common import (
    keep_columns,
    load_regression_config,
    project_path,
    winsorize_settings,
)
from tools.factor_pipeline_tools import apply_sample_filters, build_summary, require_columns


CONFIG = load_regression_config()
DEFAULT_PREVIEW_ROWS = 5000
DEFAULT_OUTPUT_PATH = project_path(str(CONFIG["preprocess_output_path"]))
DEFAULT_PREVIEW_PATH = project_path(str(CONFIG["preprocess_preview_path"]))
DEFAULT_SUMMARY_PATH = project_path(str(CONFIG["preprocess_summary_path"]))
ORIGINAL_INPUT_PATH = project_path(str(CONFIG["preprocess_input_path"]))
SAMPLE_FILTERS = dict(CONFIG["sample_filters"])
FACTOR_SAMPLE_FILTERS = {
    str(factor): dict(filters)
    for factor, filters in dict(CONFIG.get("factor_sample_filters", {})).items()
}
KEEP_COLUMNS = keep_columns(CONFIG)
WINSORIZE = winsorize_settings(CONFIG)


def parse_args() -> argparse.Namespace:
    """读取输入、输出和预览路径。"""

    parser = argparse.ArgumentParser(description="Step 06：导出最终文件和摘要。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--preview", type=Path, default=DEFAULT_PREVIEW_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--preview-rows", type=int, default=DEFAULT_PREVIEW_ROWS)
    parser.add_argument("--no-preview", action="store_true")
    return parser.parse_args()


def write_outputs(
    data: pd.DataFrame,
    output_path: Path,
    preview_path: Path,
    summary_path: Path,
    summary: dict[str, object],
    preview_rows: int,
    no_preview: bool,
) -> None:
    """写出最终 parquet、preview Excel 和 summary JSON。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(output_path, index=False)

    if not no_preview:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        data.head(preview_rows).to_excel(preview_path, index=False)

    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    """复制最终 parquet，并生成和旧大脚本同口径的摘要及预览。"""

    args = parse_args()
    data = pd.read_parquet(args.input)
    original_data = pd.read_parquet(ORIGINAL_INPUT_PATH)
    require_columns(original_data, SAMPLE_FILTERS, ORIGINAL_INPUT_PATH)

    # summary 里的 original_rows / insample_rows 沿用旧大脚本口径。
    original_rows = len(original_data)
    insample_rows = len(apply_sample_filters(original_data, SAMPLE_FILTERS))

    preview_path = None if args.no_preview else args.preview
    summary = build_summary(
        input_path=ORIGINAL_INPUT_PATH,
        output_path=args.output,
        preview_path=preview_path,
        original_rows=original_rows,
        insample_rows=insample_rows,
        output_rows=len(data),
        output_columns=list(data.columns),
        sample_filters=SAMPLE_FILTERS,
        factor_sample_filters=FACTOR_SAMPLE_FILTERS,
        winsor_group_column=WINSORIZE["group_column"],
        winsor_lower_quantile=WINSORIZE["lower_quantile"],
        winsor_upper_quantile=WINSORIZE["upper_quantile"],
        winsorize_columns=WINSORIZE["columns"],
        keep_columns=KEEP_COLUMNS,
    )
    write_outputs(
        data=data,
        output_path=args.output,
        preview_path=args.preview,
        summary_path=args.summary,
        summary=summary,
        preview_rows=args.preview_rows,
        no_preview=args.no_preview,
    )
    print(f"输出 parquet：{args.output}，shape={data.shape}")
    if not args.no_preview:
        print(f"输出 preview Excel：{args.preview}")
    print(f"输出 summary：{args.summary}")


if __name__ == "__main__":
    main()
