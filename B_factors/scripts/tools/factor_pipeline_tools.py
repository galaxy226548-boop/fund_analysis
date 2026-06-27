"""基金因子清洗流水线的通用工具函数。

这里放的是“怎么处理数据”的通用步骤；具体使用哪些列、筛选哪些样本、
winsorize 用什么分位点，仍然由调用脚本传入。这样拆分以后，主脚本可以继续
负责实验口径，工具函数只负责稳定执行这些口径。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


def require_columns(data: pd.DataFrame, required_columns: Iterable[str], source: Path) -> None:
    """检查输入数据是否包含本脚本需要的字段。"""

    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source} 缺少字段：{missing}；请先检查上游 panel_base 是否已生成完整变量。"
        )


def normalize_month_date(data: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """统一 month_date 类型，保证后面的按月分组稳定。"""

    data = data.copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    if data[date_col].isna().any():
        bad_rows = int(data[date_col].isna().sum())
        raise ValueError(f"{date_col} 存在 {bad_rows} 行无法解析的日期。")
    return data


def apply_sample_filters(
    data: pd.DataFrame,
    sample_filters: dict[str, object],
) -> pd.DataFrame:
    """按照 sample_filters 保留进入本次回归样本的行。"""

    mask = pd.Series(True, index=data.index)
    for column, expected_value in sample_filters.items():
        # 有些上游文件会把 1/0 保存成 1.0 或字符串；数值条件优先用数值比较，减少类型误差。
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            actual_numeric = pd.to_numeric(data[column], errors="coerce")
            mask &= actual_numeric == float(expected_value)
        else:
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


def winsorize_by_month(
    data: pd.DataFrame,
    columns: Iterable[str],
    group_column: str,
    lower_quantile: float,
    upper_quantile: float,
) -> pd.DataFrame:
    """按 month_date 分组，对指定连续变量做 1%/99% winsorize。"""

    data = data.copy()
    grouped = data.groupby(group_column, observed=True, sort=False)

    for column in columns:
        # 每个月分别计算上下分位点，避免不同时期市场环境差异把阈值混在一起。
        lower = grouped[column].transform(lambda series: series.quantile(lower_quantile))
        upper = grouped[column].transform(lambda series: series.quantile(upper_quantile))
        data[column] = data[column].clip(lower=lower, upper=upper)

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
    sample_filters: dict[str, object],
    factor_sample_filters: dict[str, dict[str, object]] | None = None,
    winsor_group_column: str,
    winsor_lower_quantile: float,
    winsor_upper_quantile: float,
    winsorize_columns: Iterable[str],
    keep_columns: Iterable[str],
    factor_specs: Iterable[str] | None = None,
    factor_columns: Iterable[str] | None = None,
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
        "sample_filters": sample_filters,
        "factor_sample_filters": factor_sample_filters or {},
        "factor_specs": list(factor_specs or []),
        "factor_columns": list(factor_columns or []),
        "winsorize": {
            "group_column": winsor_group_column,
            "lower_quantile": winsor_lower_quantile,
            "upper_quantile": winsor_upper_quantile,
            "columns": list(winsorize_columns),
        },
        # 保留旧字段名，避免已有 summary 对比脚本或外部 notebook 因字段改名失效。
        "kept_columns_before_group_labels": list(keep_columns),
        "output_columns": output_columns,
    }
