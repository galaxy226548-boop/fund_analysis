"""清洗进入回归的基金 Consistency 因子数据。

默认读取：

    B_factors/input/panel_base.parquet

默认输出：

    B_factors/output/panel_base.parquet
    B_factors/output/panel_base_preview.xlsx
    B_factors/output/panel_base_summary.json

这个脚本的定位是“回归前处理层”：先按照样本标记筛选行，再只保留本次
回归需要的变量，最后对连续变量按月 winsorize。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pandas as pd

from tools.factor_pipeline_tools import (
    apply_sample_filters,
    build_summary,
    coerce_numeric_columns,
    normalize_month_date,
    require_columns,
    winsorize_by_month,
)


# 项目根目录。
# __file__ 是当前脚本路径；parents[2] 表示往上两级，回到 Fund_Analysis 目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"


def load_regression_config() -> dict[str, object]:
    """从统一注册表读取本次清洗和回归共用的变量口径。

    这个脚本位于 B_factors/scripts，注册表位于 D_analysis/config。为了不依赖
    当前工作目录是否已经加入 Python import 路径，这里按文件路径加载模块。
    只读取配置函数，不会执行任何回归逻辑。
    """

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config("fm_baseline")


REGRESSION_CONFIG = load_regression_config()


def project_path(config_key: str) -> Path:
    """把注册表里的项目相对路径转成绝对路径，方便命令行默认值使用。"""

    return PROJECT_ROOT / str(REGRESSION_CONFIG[config_key])

DEFAULT_INPUT_PATH = project_path("preprocess_input_path")
DEFAULT_OUTPUT_PATH = project_path("preprocess_output_path")
DEFAULT_PREVIEW_PATH = project_path("preprocess_preview_path")
DEFAULT_SUMMARY_PATH = project_path("preprocess_summary_path")

# 预览 Excel 不适合写入几十万行；这里默认只输出前若干行，方便人工快速检查。
DEFAULT_PREVIEW_ROWS = 5000

# ---------------------------------------------------------------------------
# 1. 样本筛选条件
# ---------------------------------------------------------------------------
# 这里从统一注册表读取“本次进入回归”的筛选条件。
# 如果以后要换成未来 3 个月或 12 个月收益，只需要改 registry 中的实验口径。
SAMPLE_FILTERS = dict(REGRESSION_CONFIG["sample_filters"])
# 每个 Consistency 指标可以有自己的额外样本筛选条件。
# preprocess 阶段只应用上面的基础 SAMPLE_FILTERS；这里读取后主要用于保留列和写入 summary。
FACTOR_SAMPLE_FILTERS = {
    factor: dict(filters)
    for factor, filters in dict(REGRESSION_CONFIG.get("factor_sample_filters", {})).items()
}

# ---------------------------------------------------------------------------
# 2. 变量设置
# ---------------------------------------------------------------------------
BASIC_ID_COLUMNS = list(REGRESSION_CONFIG["id_columns"])

SAMPLE_FLAG_COLUMNS = list(REGRESSION_CONFIG["sample_flag_columns"])

DATE_COL = str(REGRESSION_CONFIG["date_col"])
Y_COL = str(REGRESSION_CONFIG["y"])

DEPENDENT_COLUMNS = [Y_COL]

# 输入文件里的原始 Consistency 因子列名仍然是 FAC_rank_vol_...。
CONSISTENCY_COLUMNS = list(REGRESSION_CONFIG["factors"])

CONTROL_COLUMNS = list(REGRESSION_CONFIG["controls"])
EXTRA_COLUMNS = list(REGRESSION_CONFIG.get("extra_columns", []))


def get_factor_filter_columns() -> list[str]:
    """列出所有 factor_sample_filters 会用到的筛选列。

    这些列即使不直接进入回归，也必须保留到 preprocess 输出表中，因为回归脚本
    后面会按单个 factor 再做额外筛选。
    """
    # 用 dict.fromkeys 去重并保留首次出现顺序，方便输出列顺序稳定。
    columns = [
        column
        for filters in FACTOR_SAMPLE_FILTERS.values()
        for column in filters
    ]
    return list(dict.fromkeys(columns))


FACTOR_FILTER_COLUMNS = get_factor_filter_columns()

KEEP_COLUMNS = (
    BASIC_ID_COLUMNS
    + SAMPLE_FLAG_COLUMNS
    + DEPENDENT_COLUMNS
    + CONSISTENCY_COLUMNS
    + CONTROL_COLUMNS
    + EXTRA_COLUMNS
    + [
        column
        for column in FACTOR_FILTER_COLUMNS
        if column not in BASIC_ID_COLUMNS
        + SAMPLE_FLAG_COLUMNS
        + DEPENDENT_COLUMNS
        + CONSISTENCY_COLUMNS
        + CONTROL_COLUMNS
        + EXTRA_COLUMNS
    ]
)

# ---------------------------------------------------------------------------
# 3. 数据清洗设置
# ---------------------------------------------------------------------------
winsorize_config = REGRESSION_CONFIG["winsorize"]
WINSOR_GROUP_COLUMN = str(winsorize_config["group_column"])
WINSOR_LOWER_QUANTILE = float(winsorize_config["lower_quantile"])
WINSOR_UPPER_QUANTILE = float(winsorize_config["upper_quantile"])
WINSORIZE_COLUMNS = list(winsorize_config["columns"])

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
    parser.add_argument(
        "--debug-intermediate-dir",
        type=Path,
        default=None,
        help="可选：保存清洗过程中的中间 parquet 到指定目录，默认不输出。",
    )
    return parser.parse_args()


def write_debug_intermediate(
    data: pd.DataFrame,
    debug_dir: Path | None,
    filename: str,
) -> None:
    """在调试模式下保存中间结果；默认流程不会调用任何写盘动作。"""

    if debug_dir is None:
        return

    debug_dir.mkdir(parents=True, exist_ok=True)
    data.to_parquet(debug_dir / filename, index=False)


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

    # 除了最终保留列，也要检查基础筛选列和所有 per-factor 筛选列都存在。
    # 这样可以在清洗一开始就发现上游 panel_base 是否缺少新分组标记。
    required_columns = set(KEEP_COLUMNS) | set(SAMPLE_FILTERS) | set(FACTOR_FILTER_COLUMNS)
    require_columns(raw_data, required_columns, args.input)

    data = normalize_month_date(raw_data, DATE_COL)

    # 先裁剪到本次回归需要的字段，能降低后面处理和输出的体量。
    data = data.loc[:, KEEP_COLUMNS].copy()
    write_debug_intermediate(
        data=data,
        debug_dir=args.debug_intermediate_dir,
        filename="01_selected_columns.parquet",
    )

    data = apply_sample_filters(data, SAMPLE_FILTERS)
    write_debug_intermediate(
        data=data,
        debug_dir=args.debug_intermediate_dir,
        filename="02_sample_filtered.parquet",
    )
    insample_rows = len(data)

    data = coerce_numeric_columns(data, WINSORIZE_COLUMNS)
    write_debug_intermediate(
        data=data,
        debug_dir=args.debug_intermediate_dir,
        filename="03_numeric_coerced.parquet",
    )

    data = winsorize_by_month(
        data=data,
        columns=WINSORIZE_COLUMNS,
        group_column=WINSOR_GROUP_COLUMN,
        lower_quantile=WINSOR_LOWER_QUANTILE,
        upper_quantile=WINSOR_UPPER_QUANTILE,
    )
    write_debug_intermediate(
        data=data,
        debug_dir=args.debug_intermediate_dir,
        filename="04_winsorized.parquet",
    )

    preview_path = None if args.no_preview else args.preview
    summary = build_summary(
        input_path=args.input,
        output_path=args.output,
        preview_path=preview_path,
        original_rows=original_rows,
        insample_rows=insample_rows,
        output_rows=len(data),
        output_columns=list(data.columns),
        sample_filters=SAMPLE_FILTERS,
        factor_sample_filters=FACTOR_SAMPLE_FILTERS,
        winsor_group_column=WINSOR_GROUP_COLUMN,
        winsor_lower_quantile=WINSOR_LOWER_QUANTILE,
        winsor_upper_quantile=WINSOR_UPPER_QUANTILE,
        winsorize_columns=WINSORIZE_COLUMNS,
        keep_columns=KEEP_COLUMNS,
        factor_specs=[str(factor) for factor in CONSISTENCY_COLUMNS],
        factor_columns=CONSISTENCY_COLUMNS,
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
