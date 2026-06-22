"""清洗进入回归的基金 Consistency 因子数据。

默认读取：

    B_factors/input/panel_base.parquet

默认输出：

    B_factors/output/panel_base.parquet
    B_factors/output/panel_base_preview.xlsx
    B_factors/output/panel_base_summary.json

这个脚本的定位是“回归前处理层”：先按照样本标记筛选行，再只保留本次
回归需要的变量，最后对连续变量按月 winsorize，并生成 5 组/10 组分组标签。
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


# 项目根目录。
# __file__ 是当前脚本路径；parents[2] 表示往上两级，回到 Fund_Analysis 目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_INPUT_PATH = PROJECT_ROOT / "B_factors/input/panel_base.parquet"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "B_factors/output/panel_base.parquet"
DEFAULT_PREVIEW_PATH = PROJECT_ROOT / "B_factors/output/panel_base_preview.xlsx"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "B_factors/output/panel_base_summary.json"

# 预览 Excel 不适合写入几十万行；这里默认只输出前若干行，方便人工快速检查。
DEFAULT_PREVIEW_ROWS = 5000

# ---------------------------------------------------------------------------
# 1. 样本筛选条件
# ---------------------------------------------------------------------------
# 这里集中设置“本次进入回归”的筛选条件。
# 如果以后要换成未来 3 个月或 12 个月收益，只需要改这里和下面变量清单。
SAMPLE_FILTERS = {
    "is_insample_future_ret_6m": 1,
}

# ---------------------------------------------------------------------------
# 2. 变量设置
# ---------------------------------------------------------------------------
BASIC_ID_COLUMNS = [
    "ifind_code",
    "month_date",
    "investment_type",
]

SAMPLE_FLAG_COLUMNS = [
    "is_insample_future_ret_6m",
]

DEPENDENT_COLUMNS = [
    "future_ret_6m",
]

# 输入文件里的原始 Consistency 因子列名仍然是 FAC_rank_vol_...。
# 后续 q5/q10 分组标签会按 consistency_... 的短名称输出，便于画图和回归复用。
CONSISTENCY_COLUMNS = [
    "FAC_rank_vol_m3_n6_pairwise1",
    "FAC_rank_vol_m6_n3_pairwise1",
    "FAC_rank_vol_m6_n6_pairwise1",
    "FAC_rank_vol_m6_n12_pairwise1",
    "FAC_rank_vol_m12_n6_pairwise1",
]

CONTROL_COLUMNS = [
    "CtrlRetSTR",
    "CtrlRetLTM",
    "CtrlVol",
    "as_偏股混合型基金",
    "Ctrl_log_fund_size",
    "Ctrl_fund_age",
]

KEEP_COLUMNS = (
    BASIC_ID_COLUMNS
    + SAMPLE_FLAG_COLUMNS
    + DEPENDENT_COLUMNS
    + CONSISTENCY_COLUMNS
    + CONTROL_COLUMNS
)

# ---------------------------------------------------------------------------
# 3. 数据清洗设置
# ---------------------------------------------------------------------------
WINSOR_GROUP_COLUMN = "month_date"
WINSOR_LOWER_QUANTILE = 0.01
WINSOR_UPPER_QUANTILE = 0.99

WINSORIZE_COLUMNS = (
    DEPENDENT_COLUMNS
    + CONSISTENCY_COLUMNS
    + [
        "CtrlRetSTR",
        "CtrlRetLTM",
        "CtrlVol",
        "Ctrl_log_fund_size",
        "Ctrl_fund_age",
    ]
)

# q5/q10 分组标签的输出后缀。key 是输入因子列，value 是输出标签里的短名称。
CONSISTENCY_GROUP_SUFFIXES = {
    "FAC_rank_vol_m3_n6_pairwise1": "consistency_m3_n6_pairwise1",
    "FAC_rank_vol_m6_n3_pairwise1": "consistency_m6_n3_pairwise1",
    "FAC_rank_vol_m6_n6_pairwise1": "consistency_m6_n6_pairwise1",
    "FAC_rank_vol_m6_n12_pairwise1": "consistency_m6_n12_pairwise1",
    "FAC_rank_vol_m12_n6_pairwise1": "consistency_m12_n6_pairwise1",
}


def parse_args() -> argparse.Namespace:
    """读取命令行参数，让默认流程和调试流程都能复用同一份代码。"""

    parser = argparse.ArgumentParser(description="清洗基金 Consistency 回归因子数据。")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="输入 panel_base parquet 文件路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="清洗后 parquet 输出路径。",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=DEFAULT_PREVIEW_PATH,
        help="预览 Excel 输出路径。",
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_SUMMARY_PATH,
        help="处理元信息 JSON 输出路径。",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=DEFAULT_PREVIEW_ROWS,
        help="预览 Excel 最多输出多少行。",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="只输出 parquet 和 summary，不生成预览 Excel。",
    )
    return parser.parse_args()


def require_columns(data: pd.DataFrame, required_columns: Iterable[str], source: Path) -> None:
    """检查输入数据是否包含本脚本需要的字段。"""

    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source} 缺少字段：{missing}；请先检查上游 panel_base 是否已生成完整变量。"
        )


def normalize_month_date(data: pd.DataFrame) -> pd.DataFrame:
    """统一 month_date 类型，保证后面的按月分组稳定。"""

    data = data.copy()
    data["month_date"] = pd.to_datetime(data["month_date"], errors="coerce")
    if data["month_date"].isna().any():
        bad_rows = int(data["month_date"].isna().sum())
        raise ValueError(f"month_date 存在 {bad_rows} 行无法解析的日期。")
    return data


def apply_sample_filters(data: pd.DataFrame) -> pd.DataFrame:
    """按照 SAMPLE_FILTERS 保留进入本次回归样本的行。"""

    mask = pd.Series(True, index=data.index)
    for column, expected_value in SAMPLE_FILTERS.items():
        # 有些上游文件会把 1/0 保存成字符串；这里转成字符串比较，可以减少类型差异造成的误筛选。
        mask &= data[column].astype("string") == str(expected_value)
    return data.loc[mask].copy()


def coerce_numeric_columns(data: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """把连续变量转成数值类型，无法转换的内容设为缺失值。"""

    data = data.copy()
    for column in columns:
        # winsorize 的 1%/99% 分位点通常是小数。
        # 即使原始列是 0/1 或整数，也先转成 float，避免 clip 时因为小数阈值无法写回整数列。
        data[column] = pd.to_numeric(data[column], errors="coerce").astype("float64")
    return data


def winsorize_by_month(data: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """按 month_date 分组，对指定连续变量做 1%/99% winsorize。"""

    data = data.copy()
    grouped = data.groupby(WINSOR_GROUP_COLUMN, observed=True, sort=False)

    for column in columns:
        # 每个月分别计算上下分位点，避免不同时期市场环境差异把阈值混在一起。
        lower = grouped[column].transform(
            lambda series: series.quantile(WINSOR_LOWER_QUANTILE)
        )
        upper = grouped[column].transform(
            lambda series: series.quantile(WINSOR_UPPER_QUANTILE)
        )
        data[column] = data[column].clip(lower=lower, upper=upper)

    return data


def make_quantile_group(series: pd.Series, group_count: int) -> pd.Series:
    """把单个月内的某个 Consistency 因子切成 q 组。

    数值越大，分组标签越大。因此 q5=5 / q10=10 对应 Consistency 较高的多头组。
    如果某个月非缺失样本少于组数，就无法可靠切分，返回缺失标签。
    """

    result = pd.Series(pd.NA, index=series.index, dtype="Int64")
    valid = series.dropna()
    if len(valid) < group_count:
        return result

    # rank(method="first") 会在相同数值之间按原始顺序打破并列。
    # 这样 qcut 能稳定得到近似等数量分组，同时仍保持“因子值越大，组号越大”。
    ranks = valid.rank(method="first", ascending=True)
    labels = range(1, group_count + 1)
    grouped = pd.qcut(ranks, q=group_count, labels=labels)
    result.loc[valid.index] = grouped.astype("Int64")
    return result


def add_consistency_groups(data: pd.DataFrame) -> pd.DataFrame:
    """按月为每个 Consistency 因子生成 5 组和 10 组标签。"""

    data = data.copy()
    month_groups = data.groupby(WINSOR_GROUP_COLUMN, observed=True, sort=False)

    for factor_column, suffix in CONSISTENCY_GROUP_SUFFIXES.items():
        for group_count in (5, 10):
            output_column = f"q{group_count}_{suffix}"
            data[output_column] = month_groups[factor_column].transform(
                lambda series, q=group_count: make_quantile_group(series, q)
            )
            data[output_column] = data[output_column].astype("Int64")

    return data


def build_summary(
    *,
    input_path: Path,
    output_path: Path,
    preview_path: Path | None,
    original_rows: int,
    insample_rows: int,
    output_rows: int,
    output_columns: list[str],
) -> dict[str, object]:
    """整理处理元信息，方便之后复现实验口径。"""

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "input_path": str(input_path),
        "output_path": str(output_path),
        "preview_path": str(preview_path) if preview_path is not None else None,
        "original_rows": original_rows,
        "insample_rows": insample_rows,
        "output_rows": output_rows,
        "sample_filters": SAMPLE_FILTERS,
        "winsorize": {
            "group_column": WINSOR_GROUP_COLUMN,
            "lower_quantile": WINSOR_LOWER_QUANTILE,
            "upper_quantile": WINSOR_UPPER_QUANTILE,
            "columns": list(WINSORIZE_COLUMNS),
        },
        "consistency_group_rule": {
            "group_counts": [5, 10],
            "larger_label_means_higher_consistency": True,
            "long_groups": {"q5": 5, "q10": 10},
            "short_groups": {"q5": 1, "q10": 1},
        },
        "kept_columns_before_group_labels": KEEP_COLUMNS,
        "output_columns": output_columns,
    }


def write_outputs(
    data: pd.DataFrame,
    output_path: Path,
    preview_path: Path,
    summary_path: Path,
    summary: dict[str, object],
    preview_rows: int,
    no_preview: bool,
) -> None:
    """写出 parquet、preview Excel 和 summary JSON。"""

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
    """执行完整清洗流程。"""

    args = parse_args()
    if not args.input.exists():
        raise FileNotFoundError(f"输入文件不存在：{args.input}")

    raw_data = pd.read_parquet(args.input)
    original_rows = len(raw_data)

    required_columns = set(KEEP_COLUMNS) | set(SAMPLE_FILTERS)
    require_columns(raw_data, required_columns, args.input)

    data = normalize_month_date(raw_data)
    data = apply_sample_filters(data)
    insample_rows = len(data)

    # 先裁剪到本次回归需要的字段，能降低后面处理和输出的体量。
    data = data.loc[:, KEEP_COLUMNS].copy()
    data = coerce_numeric_columns(data, WINSORIZE_COLUMNS)
    data = winsorize_by_month(data, WINSORIZE_COLUMNS)
    data = add_consistency_groups(data)

    preview_path = None if args.no_preview else args.preview
    summary = build_summary(
        input_path=args.input,
        output_path=args.output,
        preview_path=preview_path,
        original_rows=original_rows,
        insample_rows=insample_rows,
        output_rows=len(data),
        output_columns=list(data.columns),
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

    print(f"原始样本行数：{original_rows}")
    print(f"样本内行数：{insample_rows}")
    print(f"输出行数：{len(data)}")
    print(f"输出 parquet：{args.output}")
    if not args.no_preview:
        print(f"输出 preview Excel：{args.preview}")
    print(f"输出 summary：{args.summary}")


if __name__ == "__main__":
    main()
