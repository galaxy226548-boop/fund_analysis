"""检查 panel_base parquet 的基准结构和关键分布。

这个脚本只读取已经生成的 parquet 文件，不会修改业务数据。它的用途是把
拆分重构前的输出口径固定下来：之后如果重构了清洗流程，可以再次运行本脚本，
用文本报告快速比对行列、缺失值、数值统计量和 q5/q10 标签分布是否一致。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "B_factors" / "output" / "panel_base.parquet"
DEFAULT_REPORT_PATH = (
    PROJECT_ROOT / "B_factors" / "output" / "baseline_current" / "panel_base_check.txt"
)


def parse_args() -> argparse.Namespace:
    """读取命令行参数，方便检查默认输出或任意备份文件。"""

    parser = argparse.ArgumentParser(description="检查 panel_base parquet 基准输出。")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="要检查的 parquet 文件路径。",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="文本报告输出路径；报告内容也会打印到终端。",
    )
    return parser.parse_args()


def build_report(data: pd.DataFrame, input_path: Path) -> str:
    """生成固定格式的文本报告，减少之后人工比对时的口径差异。"""

    lines: list[str] = []
    lines.append(f"检查文件：{input_path}")
    lines.append(f"行数：{len(data)}")
    lines.append(f"列数：{data.shape[1]}")

    lines.append("\n列名列表：")
    for column in data.columns:
        lines.append(f"- {column}")

    lines.append("\n每列缺失值数量：")
    missing_counts = data.isna().sum()
    for column, missing_count in missing_counts.items():
        lines.append(f"{column}: {int(missing_count)}")

    # 这里只选择 pandas 识别出的数值列，避免把日期和字符串列误放进统计表。
    numeric_data = data.select_dtypes(include="number")
    lines.append("\n数值列 count/mean/std/min/max：")
    if numeric_data.empty:
        lines.append("(无数值列)")
    else:
        numeric_summary = numeric_data.describe().loc[["count", "mean", "std", "min", "max"]]
        lines.append(numeric_summary.to_string())

    # q5/q10 标签列是后续分组收益和回归检查的关键输出，所以单独列出取值分布。
    label_columns = [
        column
        for column in data.columns
        if column.startswith("q5_") or column.startswith("q10_")
    ]
    lines.append("\nq5/q10 标签列取值分布：")
    if not label_columns:
        lines.append("(未找到 q5_/q10_ 标签列)")
    for column in label_columns:
        lines.append(f"\n[{column}]")
        distribution = data[column].value_counts(dropna=False).sort_index()
        for value, count in distribution.items():
            lines.append(f"{value}: {int(count)}")

    return "\n".join(lines) + "\n"


def main() -> None:
    """读取 parquet，打印并保存检查报告。"""

    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"找不到输入文件：{args.input}")

    data = pd.read_parquet(args.input)
    report = build_report(data, args.input)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"检查报告已写入：{args.report}")


if __name__ == "__main__":
    main()
