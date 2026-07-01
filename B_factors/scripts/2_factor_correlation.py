"""检查 Fama-MacBeth 解释变量之间的相关系数和 VIF。

这个脚本默认读取上游已经清洗好的基金-月份面板：

    B_factors/output/panel_base.parquet

默认输出到：

    B_factors/output/variable_correlation_check/

相关系数采用 Fama-MacBeth 口径：先在每个月的基金横截面里计算 Pearson
相关系数矩阵，再对每一对变量的月度相关系数取时间序列均值。这样做可以避免
直接 pooled corr() 把“跨月份均值差异”和“当月横截面关系”混在一起。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from scipy import stats


# =============================================================================
# 配置区：后续改默认输入、输出目录、日期列或样本门槛时，优先改这里
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_MODEL_KEY = "fm_baseline"


def parse_model_key() -> str:
    """在完整参数解析前，先取出 --model 用来加载对应 registry 配置。

    本脚本的默认输入路径、输出目录和变量清单都依赖 registry。
    所以要先轻量解析一次 model key，再初始化这些全局默认值。
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--model", default=DEFAULT_MODEL_KEY)
    args, _ = parser.parse_known_args()
    return str(args.model)


def load_regression_config(model_key: str) -> dict[str, object]:
    """从统一注册表读取变量和路径配置。"""

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(model_key)


MODEL_KEY = parse_model_key()
REGRESSION_CONFIG = load_regression_config(MODEL_KEY)


def project_path(config_key: str) -> Path:
    """把注册表里的项目相对路径转成绝对路径。"""

    return PROJECT_ROOT / str(REGRESSION_CONFIG[config_key])


INPUT_PATH = project_path("regression_input_path")
OUTPUT_DIR = project_path("correlation_output_dir")
DATE_COL = str(REGRESSION_CONFIG["date_col"])
MIN_CROSS_SECTION_N = int(REGRESSION_CONFIG["min_cross_section_n"])
SAMPLE_FILTERS = dict(REGRESSION_CONFIG["sample_filters"])
FACTOR_SAMPLE_FILTERS = {
    factor: dict(filters)
    for factor, filters in dict(REGRESSION_CONFIG.get("factor_sample_filters", {})).items()
}
INTERACTION_MAIN_EFFECTS = list(
    REGRESSION_CONFIG.get("interaction_main_effects") or []
)
RAW_INTERACTIONS = list(REGRESSION_CONFIG.get("interactions") or [])
RAW_INTERACTION_CENTERING = REGRESSION_CONFIG.get("interaction_centering", "none")
Y_COL = str(REGRESSION_CONFIG["y"])

CURRENT_FACTOR_PLACEHOLDER = "FAC"
MATCHED_RANK_MEAN_PLACEHOLDER = "RANK_MEAN"
STANDARDIZE_NONE = "none"
STANDARDIZE_CROSS_SECTION = "cross_section"
CENTER_NONE = "none"
CENTER_CROSS_SECTION_MEAN = "cross_section_mean"

# 审核结果阈值。
# 相关系数使用绝对值，是因为高正相关和高负相关都可能带来共线性或变量重叠风险。
CORRELATION_RISK_THRESHOLD = 0.50
# VIF 使用 p90 作为主判断列，避免 max_vif 被个别月份的极端情况过度放大。
VIF_RISK_THRESHOLD = 5.0
VIF_RISK_METRIC = "p90_vif"


def parse_comma_list(raw_value: str | None) -> list[str] | None:
    """把命令行里的逗号分隔变量清单转成 list。

    返回 None 表示用户没有传入这个参数；返回空 list 表示用户传了参数但内容为空。
    这两个状态在合并默认变量时含义不同，所以这里刻意保留区别。
    """
    if raw_value is None:
        return None
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def factor_columns_for_spec(factor_spec: object) -> list[str]:
    """把 registry 的 factor 声明转换成实际列名。

    普通模型中 factor 是字符串；dummy 模型中一个 tuple/list 表示一组 dummy
    会同时进入回归。相关性诊断按单列变量检查，所以这里把 tuple/list 拆成
    每个 dummy 列，后面逐列与 controls 计算相关性和 VIF。
    """

    if isinstance(factor_spec, (tuple, list)):
        columns = [str(column) for column in factor_spec]
    else:
        columns = [str(factor_spec)]

    if not columns or any(not column for column in columns):
        raise ValueError(f"factor 配置不能为空：{factor_spec!r}")
    return columns


def flatten_factor_columns(factor_specs: list[object]) -> list[str]:
    """展开所有 factor 配置，去重并保留首次出现顺序。"""

    columns: list[str] = []
    for factor_spec in factor_specs:
        columns.extend(factor_columns_for_spec(factor_spec))
    return list(dict.fromkeys(columns))


def resolve_variable_for_factor(variable: object, factor_col: str) -> str:
    """把 FAC/RANK_MEAN 占位符解析成当前期限的真实列名。"""
    variable_name = str(variable).strip()
    if variable_name == CURRENT_FACTOR_PLACEHOLDER:
        return factor_col
    if variable_name == MATCHED_RANK_MEAN_PLACEHOLDER:
        if not factor_col.startswith("FAC_rank_vol_"):
            raise ValueError(f"无法从当前 factor 推导 rank_mean 列名：{factor_col!r}")
        return factor_col.replace("FAC_rank_vol_", "rank_mean_", 1)
    if not variable_name:
        raise ValueError("交互项或主效应变量名不能为空")
    return variable_name


def normalize_standardize_method(method: object) -> str:
    """统一交互项标准化配置；当前支持不标准化和按月截面标准化。"""
    normalized = str(method if method is not None else STANDARDIZE_NONE).strip().lower()
    aliases = {
        "": STANDARDIZE_NONE,
        "none": STANDARDIZE_NONE,
        "no": STANDARDIZE_NONE,
        "不标准化": STANDARDIZE_NONE,
        "不標準化": STANDARDIZE_NONE,
        "cross_section": STANDARDIZE_CROSS_SECTION,
        "cross-section": STANDARDIZE_CROSS_SECTION,
        "cross_sectional": STANDARDIZE_CROSS_SECTION,
        "by_month": STANDARDIZE_CROSS_SECTION,
        "按回归截面标准化": STANDARDIZE_CROSS_SECTION,
        "按回歸截面標準化": STANDARDIZE_CROSS_SECTION,
    }
    if normalized not in aliases:
        raise ValueError(f"未知交互项标准化方式：{method!r}")
    return aliases[normalized]


def normalize_centering_method(method: object) -> str:
    """统一交互变量中心化配置；目前支持不处理和按月截面去均值。"""
    normalized = str(method if method is not None else CENTER_NONE).strip().lower()
    aliases = {
        "": CENTER_NONE,
        "none": CENTER_NONE,
        "no": CENTER_NONE,
        "不中心化": CENTER_NONE,
        "cross_section_mean": CENTER_CROSS_SECTION_MEAN,
        "cross-section-mean": CENTER_CROSS_SECTION_MEAN,
        "by_month_mean": CENTER_CROSS_SECTION_MEAN,
        "monthly_demean": CENTER_CROSS_SECTION_MEAN,
        "月度去均值": CENTER_CROSS_SECTION_MEAN,
    }
    if normalized not in aliases:
        raise ValueError(f"未知交互变量中心化方式：{method!r}")
    return aliases[normalized]


INTERACTION_CENTERING = normalize_centering_method(RAW_INTERACTION_CENTERING)


def parse_braced_interaction(text: str) -> tuple[str, str]:
    """解析 registry 中的 ``{X1,X2}`` 交互项简写。"""
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError(f"字符串交互项必须写成 {{X1,X2}} 形式：{text!r}")
    variables = [part.strip() for part in stripped[1:-1].split(",")]
    if len(variables) != 2 or any(not variable for variable in variables):
        raise ValueError(f"交互项必须恰好包含两个非空变量：{text!r}")
    return variables[0], variables[1]


def parse_interaction_config(
    raw_interactions: list[object],
) -> list[dict[str, str]]:
    """把 registry 的多种交互项写法整理成统一结构。"""
    parsed: list[dict[str, str]] = []
    for index, item in enumerate(raw_interactions, start=1):
        standardize = STANDARDIZE_NONE
        custom_name: str | None = None

        if isinstance(item, str):
            var1, var2 = parse_braced_interaction(item)
        elif isinstance(item, dict):
            if "variables" in item:
                variables = item["variables"]
            elif "vars" in item:
                variables = item["vars"]
            elif "columns" in item:
                variables = item["columns"]
            elif {"x1", "x2"}.issubset(item):
                variables = [item["x1"], item["x2"]]
            else:
                raise ValueError(f"交互项字典缺少变量定义：第 {index} 项 {item!r}")
            if isinstance(variables, str):
                var1, var2 = parse_braced_interaction(variables)
            else:
                values = sorted(variables) if isinstance(variables, set) else list(variables)
                if len(values) != 2:
                    raise ValueError(f"交互项必须恰好包含两个变量：第 {index} 项")
                var1, var2 = str(values[0]), str(values[1])
            standardize = normalize_standardize_method(item.get("standardize"))
            custom_name = str(item["name"]).strip() if item.get("name") else None
        elif isinstance(item, (list, tuple, set)):
            values = sorted(item) if isinstance(item, set) else list(item)
            if len(values) != 2:
                raise ValueError(f"交互项必须恰好包含两个变量：第 {index} 项")
            var1, var2 = str(values[0]), str(values[1])
        else:
            raise TypeError(f"不支持的交互项配置类型：{type(item).__name__}")

        var1, var2 = str(var1).strip(), str(var2).strip()
        if not var1 or not var2 or var1 == var2:
            raise ValueError(f"交互项变量无效：第 {index} 项 {item!r}")
        suffix = "" if standardize == STANDARDIZE_NONE else "__zcs"
        if INTERACTION_CENTERING == CENTER_CROSS_SECTION_MEAN:
            suffix += "__dmcs"
        parsed.append(
            {
                "var1": var1,
                "var2": var2,
                "standardize": standardize,
                "name": custom_name or f"{var1}__x__{var2}{suffix}",
            }
        )
    return parsed


INTERACTIONS = parse_interaction_config(RAW_INTERACTIONS)

if INTERACTION_CENTERING != CENTER_NONE and any(
    interaction["standardize"] != STANDARDIZE_NONE for interaction in INTERACTIONS
):
    raise ValueError("interaction_centering 不能与交互项 standardize 同时启用")


def interaction_source_columns_for_factor(factor_col: str) -> list[str]:
    """列出当前期限生成主效应和交互项所需的原始输入列。"""
    columns = [
        resolve_variable_for_factor(variable, factor_col)
        for variable in INTERACTION_MAIN_EFFECTS
    ]
    for interaction in INTERACTIONS:
        columns.extend(
            [
                resolve_variable_for_factor(interaction["var1"], factor_col),
                resolve_variable_for_factor(interaction["var2"], factor_col),
            ]
        )
    return list(dict.fromkeys(columns))


def make_centered_column_name(column: str) -> str:
    """生成与回归脚本一致的月度截面去均值列名。"""
    return f"{column}__dmcs"


def demean_by_cross_section(
    data: pd.DataFrame,
    column: str,
    centering_mask: pd.Series | None = None,
) -> pd.Series:
    """在当前模型完整候选样本内，按月对单个解释变量仅做去均值。"""
    if centering_mask is None:
        centering_mask = pd.Series(True, index=data.index)

    centered = pd.Series(np.nan, index=data.index, dtype=float)
    numeric = pd.to_numeric(data.loc[centering_mask, column], errors="coerce")
    month_means = numeric.groupby(
        data.loc[centering_mask, DATE_COL], sort=False
    ).transform("mean")
    centered.loc[centering_mask] = numeric - month_means
    return centered


def add_interaction_columns(
    data: pd.DataFrame,
    factor_col: str,
    centering_mask: pd.Series | None = None,
) -> pd.DataFrame:
    """按当前期限生成与回归脚本同定义的乘积交互项。"""
    if not INTERACTIONS:
        return data

    result = data.copy()
    for interaction in INTERACTIONS:
        var1 = resolve_variable_for_factor(interaction["var1"], factor_col)
        var2 = resolve_variable_for_factor(interaction["var2"], factor_col)
        method = interaction["standardize"]

        if method == STANDARDIZE_NONE:
            if INTERACTION_CENTERING == CENTER_CROSS_SECTION_MEAN:
                # 与回归脚本完全一致：两侧变量先在当月完整候选样本内减均值，
                # 诊断矩阵同时使用这两个中心化主效应及其乘积。
                left = demean_by_cross_section(result, var1, centering_mask)
                right = demean_by_cross_section(result, var2, centering_mask)
                result[make_centered_column_name(var1)] = left
                result[make_centered_column_name(var2)] = right
            else:
                left = pd.to_numeric(result[var1], errors="coerce")
                right = pd.to_numeric(result[var2], errors="coerce")
        else:
            # 标准化只使用当前期限通过样本筛选后的月度截面，与回归口径一致。
            def zscore(series: pd.Series) -> pd.Series:
                numeric = pd.to_numeric(series, errors="coerce")
                std = numeric.std(ddof=0)
                if pd.isna(std) or std == 0:
                    return pd.Series(np.nan, index=series.index)
                return (numeric - numeric.mean()) / std

            left = result.groupby(DATE_COL, sort=False)[var1].transform(zscore)
            right = result.groupby(DATE_COL, sort=False)[var2].transform(zscore)

        result[interaction["name"]] = left * right
    return result


def diagnostic_variables_for_factor(
    factor_col: str, control_columns: list[str]
) -> list[str]:
    """构造当前期限完整回归设计矩阵的变量顺序。"""
    main_effects = [
        resolve_variable_for_factor(variable, factor_col)
        for variable in INTERACTION_MAIN_EFFECTS
    ]
    factor_and_main_effects = [factor_col, *main_effects]
    if INTERACTION_CENTERING == CENTER_CROSS_SECTION_MEAN and INTERACTIONS:
        interaction_sources = {
            resolve_variable_for_factor(variable, factor_col)
            for interaction in INTERACTIONS
            for variable in (interaction["var1"], interaction["var2"])
        }
        factor_and_main_effects = [
            make_centered_column_name(column)
            if column in interaction_sources
            else column
            for column in factor_and_main_effects
        ]
    interaction_names = [interaction["name"] for interaction in INTERACTIONS]
    return list(
        dict.fromkeys([*factor_and_main_effects, *interaction_names, *control_columns])
    )


def parse_args() -> argparse.Namespace:
    """读取命令行参数，让默认检查和临时变量组合检查共用同一套逻辑。"""
    parser = argparse.ArgumentParser(
        description="按 Fama-MacBeth 月度横截面口径检查变量相关系数和 VIF。"
    )
    parser.add_argument(
        "--model",
        default=MODEL_KEY,
        help="regression_registry.py 中的模型名称，默认 fm_baseline。",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_PATH,
        help="输入 parquet 文件路径；默认读取 B_factors/output/panel_base.parquet。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="输出目录；默认写入 B_factors/output/variable_correlation_check/。",
    )
    parser.add_argument(
        "--min-cross-section-n",
        type=int,
        default=MIN_CROSS_SECTION_N,
        help="每个月进入相关系数和 VIF 计算的最小横截面样本数。",
    )
    parser.add_argument(
        "--consistency-columns",
        type=str,
        default=None,
        help="手动覆盖 Consistency 变量，多个变量用英文逗号分隔。",
    )
    parser.add_argument(
        "--control-columns",
        type=str,
        default=None,
        help="手动覆盖控制变量，多个变量用英文逗号分隔。",
    )
    parser.add_argument(
        "--variables",
        type=str,
        default=None,
        help="直接指定完整变量列表；指定后忽略 Consistency/Control 分组。",
    )
    return parser.parse_args()


def choose_variables(
    args: argparse.Namespace,
    default_consistency_columns: list[str],
    default_control_columns: list[str],
) -> tuple[list[str], dict[str, object]]:
    """根据命令行参数决定最终进入相关性和 VIF 的变量清单。"""
    manual_variables = parse_comma_list(args.variables)
    manual_consistency = parse_comma_list(args.consistency_columns)
    manual_controls = parse_comma_list(args.control_columns)

    if manual_variables is not None:
        # --variables 是最直接的覆盖方式。用户指定后，脚本不再区分变量组来源。
        variables = manual_variables
        source_info = {
            "mode": "manual_variables",
            "variables_source": "--variables",
            "consistency_columns_source": "ignored_by_variables",
            "control_columns_source": "ignored_by_variables",
            "consistency_columns": [],
            "control_columns": [],
        }
    else:
        consistency_columns = (
            manual_consistency
            if manual_consistency is not None
            else default_consistency_columns
        )
        control_columns = (
            manual_controls if manual_controls is not None else default_control_columns
        )
        variables = consistency_columns + control_columns
        source_info = {
            "mode": "grouped_consistency_control",
            "variables_source": "consistency_columns + control_columns",
            "consistency_columns_source": (
                "--consistency-columns"
                if manual_consistency is not None
                else str(REGISTRY_PATH)
            ),
            "control_columns_source": (
                "--control-columns"
                if manual_controls is not None
                else str(REGISTRY_PATH)
            ),
            "consistency_columns": consistency_columns,
            "control_columns": control_columns,
        }

    # 去重但保留用户给定顺序。重复变量会让相关矩阵和 VIF 设计矩阵天然共线。
    unique_variables = list(dict.fromkeys(variables))
    if not unique_variables:
        raise ValueError("最终变量列表为空；请检查命令行参数或来源脚本变量配置。")

    source_info["variables"] = unique_variables
    source_info["removed_duplicate_variables"] = [
        variable for variable in variables if variables.count(variable) > 1
    ]
    return unique_variables, source_info


def require_columns(data: pd.DataFrame, required_columns: Iterable[str], source: Path) -> None:
    """检查输入表是否包含本脚本需要的字段。"""
    missing_columns = [column for column in required_columns if column not in data.columns]
    if missing_columns:
        raise ValueError(f"{source} 缺少字段：{missing_columns}")


def get_filter_columns() -> list[str]:
    """列出基础筛选和 per-factor 筛选会用到的全部字段。"""
    # 相关性诊断也要复用回归样本口径，因此需要检查并读取所有筛选列。
    columns = list(SAMPLE_FILTERS)
    for filters in FACTOR_SAMPLE_FILTERS.values():
        columns.extend(filters)
    return list(dict.fromkeys(columns))


def get_filters_for_factor(factor_col: str) -> dict[str, object]:
    """返回某个 Consistency 指标实际使用的筛选条件。"""
    # 先放共同基础筛选，再叠加当前 factor 自己的 top-half 等额外筛选。
    combined_filters = dict(SAMPLE_FILTERS)
    factor_filters = FACTOR_SAMPLE_FILTERS.get(factor_col, {})
    for column, expected_value in factor_filters.items():
        # 同一列如果基础筛选和 factor 筛选要求不同，说明 registry 配置冲突，应尽早报错。
        if column in combined_filters and combined_filters[column] != expected_value:
            raise ValueError(
                f"{factor_col} 的筛选条件与基础筛选冲突："
                f"{column}={combined_filters[column]!r} vs {expected_value!r}"
            )
        combined_filters[column] = expected_value
    return combined_filters


def apply_sample_filters(
    data: pd.DataFrame,
    sample_filters: dict[str, object],
) -> pd.DataFrame:
    """按照给定筛选条件保留样本行。"""
    # 从全 True 掩码开始，每个筛选条件都会进一步缩小样本范围。
    mask = pd.Series(True, index=data.index)
    for column, expected_value in sample_filters.items():
        # 上游有时会把 1/0 存成 1.0 或字符串；数值条件优先用数值比较，减少类型误差。
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            actual_numeric = pd.to_numeric(data[column], errors="coerce")
            mask &= actual_numeric == float(expected_value)
        else:
            mask &= data[column].astype("string") == str(expected_value)
    return data.loc[mask].copy()


def normalize_analysis_data(
    data: pd.DataFrame,
    variables: list[str],
    date_col: str,
) -> pd.DataFrame:
    """统一日期和变量类型，减少上游存储格式差异对计算的影响。"""
    analysis_data = data[[date_col] + variables].copy()
    analysis_data[date_col] = pd.to_datetime(analysis_data[date_col], errors="coerce")
    if analysis_data[date_col].isna().any():
        bad_rows = int(analysis_data[date_col].isna().sum())
        raise ValueError(f"{date_col} 存在 {bad_rows} 行无法解析的日期。")

    for variable in variables:
        # 相关系数和 VIF 都需要数值变量；无法转换的内容设为缺失，后面按完整样本删除。
        analysis_data[variable] = pd.to_numeric(
            analysis_data[variable], errors="coerce"
        ).astype("float64")

    return analysis_data


def significance_stars(p_value: float) -> str:
    """把 p 值转换成常见的显著性星号。"""
    if pd.isna(p_value):
        return ""
    if p_value < 0.01:
        return "***"
    if p_value < 0.05:
        return "**"
    if p_value < 0.1:
        return "*"
    return ""


def build_correlation_outputs(
    data: pd.DataFrame,
    variables: list[str],
    date_col: str,
    min_cross_section_n: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    """按月计算横截面相关系数，再汇总成矩阵和长表。"""
    valid_data = data[[date_col] + variables].dropna().copy()
    monthly_n = valid_data.groupby(date_col).size()
    eligible_months = monthly_n[monthly_n >= min_cross_section_n].index
    valid_data = valid_data[valid_data[date_col].isin(eligible_months)].copy()

    monthly_corrs: list[pd.DataFrame] = []
    skipped_months: list[dict[str, object]] = []

    for month, month_data in valid_data.groupby(date_col, sort=True):
        # 相关系数允许变量当月无波动，此时 pandas 会给出 NaN。
        # 这些 NaN 不会中断流程，后续按变量对做时间序列均值时自然跳过。
        corr = month_data[variables].corr(method="pearson")
        corr[date_col] = month
        monthly_corrs.append(corr.reset_index(names="row_variable"))

    below_threshold_months = monthly_n[monthly_n < min_cross_section_n]
    for month, n_obs in below_threshold_months.items():
        skipped_months.append(
            {
                "month_date": str(pd.Timestamp(month).date()),
                "n_obs": int(n_obs),
                "reason": "完整变量样本数小于 min_cross_section_n",
            }
        )

    if not monthly_corrs:
        empty_summary = pd.DataFrame(
            columns=[
                "row_variable",
                "col_variable",
                "mean_corr",
                "p_value",
                "stars",
                "n_months",
            ]
        )
        empty_table = pd.DataFrame(index=variables, columns=variables).reset_index(
            names="variable"
        )
        metadata = {
            "eligible_months": 0,
            "skipped_months": skipped_months,
        }
        return empty_summary, empty_table, empty_table.copy(), metadata

    monthly_corr_data = pd.concat(monthly_corrs, ignore_index=True)
    long_monthly_corr = monthly_corr_data.melt(
        id_vars=[date_col, "row_variable"],
        value_vars=variables,
        var_name="col_variable",
        value_name="corr",
    )

    summary_rows: list[dict[str, object]] = []
    for row_variable in variables:
        for col_variable in variables:
            pair_series = long_monthly_corr.loc[
                (long_monthly_corr["row_variable"] == row_variable)
                & (long_monthly_corr["col_variable"] == col_variable),
                "corr",
            ].dropna()
            n_months = int(len(pair_series))
            mean_corr = float(pair_series.mean()) if n_months else np.nan

            if row_variable == col_variable or n_months <= 1:
                p_value = np.nan
            else:
                _, raw_p_value = stats.ttest_1samp(pair_series, popmean=0.0)
                p_value = float(raw_p_value) if pd.notna(raw_p_value) else np.nan

            summary_rows.append(
                {
                    "row_variable": row_variable,
                    "col_variable": col_variable,
                    "mean_corr": mean_corr,
                    "p_value": p_value,
                    "stars": significance_stars(p_value),
                    "n_months": n_months,
                }
            )

    summary = pd.DataFrame(summary_rows)
    numeric_table = pd.DataFrame(index=variables, columns=variables, dtype=float)
    table_with_stars = pd.DataFrame(index=variables, columns=variables, dtype=object)

    for row_variable in variables:
        for col_variable in variables:
            match = summary[
                (summary["row_variable"] == row_variable)
                & (summary["col_variable"] == col_variable)
            ].iloc[0]
            mean_corr = match["mean_corr"]
            stars = match["stars"]
            numeric_table.loc[row_variable, col_variable] = mean_corr
            if pd.isna(mean_corr):
                table_with_stars.loc[row_variable, col_variable] = ""
            elif row_variable == col_variable:
                table_with_stars.loc[row_variable, col_variable] = "1.000"
            else:
                table_with_stars.loc[row_variable, col_variable] = f"{mean_corr:.3f}{stars}"

    numeric_table = numeric_table.reset_index(names="variable")
    table_with_stars = table_with_stars.reset_index(names="variable")
    metadata = {
        "eligible_months": int(len(eligible_months)),
        "skipped_months": skipped_months,
        "complete_case_rows": int(len(valid_data)),
    }
    return summary, numeric_table, table_with_stars, metadata


def calculate_vif_for_matrix(
    matrix: pd.DataFrame,
    variables: list[str],
) -> tuple[dict[str, float] | None, str | None]:
    """对一个横截面样本矩阵计算 VIF。

    VIF 可以理解为“某个变量能被其他变量解释到什么程度”。这里使用标准化后
    相关矩阵的逆矩阵对角线计算，结果与逐个变量回归得到的 VIF 等价。这样写
    更短，也更容易统一检查共线和秩不足。
    """
    if len(matrix) <= len(variables):
        return None, "样本数不大于变量数，无法稳定计算 VIF"

    std_values = matrix[variables].std(ddof=0)
    zero_variance_columns = std_values[std_values <= 0].index.tolist()
    if zero_variance_columns:
        return None, f"变量无横截面波动：{zero_variance_columns}"

    corr = matrix[variables].corr(method="pearson").to_numpy(dtype=float)
    if np.isnan(corr).any() or np.isinf(corr).any():
        return None, "相关矩阵包含 NaN 或 Inf"

    rank = np.linalg.matrix_rank(corr)
    if rank < len(variables):
        return None, f"相关矩阵秩不足：rank={rank}, variables={len(variables)}"

    try:
        inv_corr = np.linalg.inv(corr)
    except np.linalg.LinAlgError as exc:
        return None, f"相关矩阵无法求逆：{exc}"

    vif_values = np.diag(inv_corr)
    if np.isnan(vif_values).any() or np.isinf(vif_values).any():
        return None, "VIF 结果包含 NaN 或 Inf"

    return {
        variable: float(vif)
        for variable, vif in zip(variables, vif_values, strict=True)
    }, None


def build_monthly_vif_long(
    data: pd.DataFrame,
    variables: list[str],
    date_col: str,
    min_cross_section_n: int,
) -> pd.DataFrame:
    """逐月计算横截面 VIF，并把失败月份原因写入长表。"""
    output_columns = [
        "month_date",
        "variable",
        "vif",
        "n_obs",
        "status",
        "reason",
    ]
    rows: list[dict[str, object]] = []

    # 先按月循环，再在月内 dropna，是为了把每个月的失败原因记录得更清楚。
    for month, month_data in data.groupby(date_col, sort=True):
        month_complete = month_data[[date_col] + variables].dropna().copy()
        n_obs = int(len(month_complete))

        if n_obs < min_cross_section_n:
            reason = "完整变量样本数小于 min_cross_section_n"
            for variable in variables:
                rows.append(
                    {
                        "month_date": str(pd.Timestamp(month).date()),
                        "variable": variable,
                        "vif": np.nan,
                        "n_obs": n_obs,
                        "status": "skipped",
                        "reason": reason,
                    }
                )
            continue

        vif_values, reason = calculate_vif_for_matrix(month_complete, variables)
        if vif_values is None:
            for variable in variables:
                rows.append(
                    {
                        "month_date": str(pd.Timestamp(month).date()),
                        "variable": variable,
                        "vif": np.nan,
                        "n_obs": n_obs,
                        "status": "failed",
                        "reason": reason,
                    }
                )
            continue

        for variable in variables:
            rows.append(
                {
                    "month_date": str(pd.Timestamp(month).date()),
                    "variable": variable,
                    "vif": vif_values[variable],
                    "n_obs": n_obs,
                    "status": "ok",
                    "reason": "",
                }
            )

    # 如果筛选后没有任何月份，仍返回带固定列名的空表，避免下游按 status 列汇总时报错。
    return pd.DataFrame(rows, columns=output_columns)


def summarize_monthly_vif(monthly_vif: pd.DataFrame) -> pd.DataFrame:
    """把月度 VIF 长表汇总成变量层面的时间序列诊断表。"""
    ok_vif = monthly_vif[monthly_vif["status"] == "ok"].copy()
    if ok_vif.empty:
        return pd.DataFrame(
            columns=[
                "variable",
                "mean_vif",
                "median_vif",
                "p90_vif",
                "max_vif",
                "ok_months",
                "failed_or_skipped_months",
            ]
        )

    summary = (
        ok_vif.groupby("variable")["vif"]
        .agg(
            mean_vif="mean",
            median_vif="median",
            p90_vif=lambda series: series.quantile(0.9),
            max_vif="max",
            ok_months="count",
        )
        .reset_index()
    )

    failed_counts = (
        monthly_vif[monthly_vif["status"] != "ok"]
        .groupby("variable")
        .size()
        .rename("failed_or_skipped_months")
        .reset_index()
    )
    summary = summary.merge(failed_counts, on="variable", how="left")
    summary["failed_or_skipped_months"] = (
        summary["failed_or_skipped_months"].fillna(0).astype(int)
    )
    return summary


def build_overall_vif(
    data: pd.DataFrame,
    variables: list[str],
    date_col: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """把所有月份 pooled 到一起，计算一次补充性 VIF。"""
    pooled_data = data[[date_col] + variables].dropna().copy()
    vif_values, reason = calculate_vif_for_matrix(pooled_data, variables)

    rows: list[dict[str, object]] = []
    if vif_values is None:
        for variable in variables:
            rows.append(
                {
                    "variable": variable,
                    "vif": np.nan,
                    "n_obs": int(len(pooled_data)),
                    "status": "failed",
                    "reason": reason,
                }
            )
    else:
        for variable in variables:
            rows.append(
                {
                    "variable": variable,
                    "vif": vif_values[variable],
                    "n_obs": int(len(pooled_data)),
                    "status": "ok",
                    "reason": "",
                }
            )

    metadata = {
        "pooled_complete_case_rows": int(len(pooled_data)),
        "pooled_status": "ok" if vif_values is not None else "failed",
        "pooled_reason": "" if vif_values is not None else reason,
    }
    return pd.DataFrame(rows), metadata


def build_correlation_risk_pairs(
    corr_summary: pd.DataFrame,
    threshold: float,
) -> pd.DataFrame:
    """从相关系数长表中筛出需要审核的唯一变量对。"""
    output_columns = [
        "variable_1",
        "variable_2",
        "mean_corr",
        "abs_mean_corr",
        "p_value",
        "stars",
        "n_months",
        "risk_level",
        "review_note",
    ]
    if corr_summary.empty:
        return pd.DataFrame(columns=output_columns)

    risk_data = corr_summary[corr_summary["row_variable"] != corr_summary["col_variable"]].copy()
    risk_data["abs_mean_corr"] = risk_data["mean_corr"].abs()
    risk_data = risk_data[risk_data["abs_mean_corr"] >= threshold].copy()
    if risk_data.empty:
        return pd.DataFrame(columns=output_columns)

    # 相关矩阵天然对称；把 A-B 和 B-A 视为同一组，避免审核表重复出现同一风险。
    risk_data["pair_key"] = risk_data.apply(
        lambda row: tuple(sorted([row["row_variable"], row["col_variable"]])),
        axis=1,
    )
    risk_data = (
        risk_data.sort_values(["abs_mean_corr", "n_months"], ascending=[False, False])
        .drop_duplicates("pair_key", keep="first")
        .copy()
    )

    risk_data["variable_1"] = risk_data["pair_key"].map(lambda pair: pair[0])
    risk_data["variable_2"] = risk_data["pair_key"].map(lambda pair: pair[1])
    risk_data["risk_level"] = np.where(
        risk_data["stars"].fillna("").astype(str).str.len() > 0,
        "重点关注相关性风险",
        "相关性风险",
    )
    risk_data["review_note"] = np.where(
        risk_data["risk_level"] == "重点关注相关性风险",
        (
            f"abs(mean_corr) >= {threshold:.2f}，且显著性星号不为空；"
            "建议重点检查变量含义是否重叠。"
        ),
        (
            f"abs(mean_corr) >= {threshold:.2f}；"
            "建议结合变量含义和 VIF 判断是否需要调整。"
        ),
    )

    return risk_data[output_columns].sort_values(
        "abs_mean_corr", ascending=False
    ).reset_index(drop=True)


def build_vif_risk_variables(
    vif_summary: pd.DataFrame,
    metric: str,
    threshold: float,
) -> pd.DataFrame:
    """从 VIF 时间序列汇总中筛出需要审核的变量。"""
    output_columns = [
        "variable",
        "mean_vif",
        "median_vif",
        "p90_vif",
        "max_vif",
        "ok_months",
        "failed_or_skipped_months",
        "risk_metric",
        "risk_threshold",
        "risk_level",
        "review_note",
    ]
    if vif_summary.empty:
        return pd.DataFrame(columns=output_columns)
    if metric not in vif_summary.columns:
        raise ValueError(f"VIF 风险判断列不存在：{metric}")

    risk_data = vif_summary[vif_summary[metric] > threshold].copy()
    if risk_data.empty:
        return pd.DataFrame(columns=output_columns)

    risk_data["risk_metric"] = metric
    risk_data["risk_threshold"] = float(threshold)
    risk_data["risk_level"] = "VIF 风险"
    risk_data["review_note"] = (
        f"{metric} > {threshold:.1f}；建议检查该变量是否能被其他解释变量稳定线性解释。"
    )
    return risk_data[output_columns].sort_values(
        metric, ascending=False
    ).reset_index(drop=True)


def format_markdown_table(
    data: pd.DataFrame,
    columns: list[str],
    float_columns: Iterable[str],
) -> str:
    """把小型审核表转成 Markdown，方便直接放进人工审核报告。"""
    if data.empty:
        return ""

    display_data = data[columns].copy()
    for column in float_columns:
        if column in display_data.columns:
            display_data[column] = display_data[column].map(
                lambda value: "" if pd.isna(value) else f"{value:.3f}"
            )

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in display_data.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in columns) + " |")
    return "\n".join(lines)


def build_diagnostic_review_markdown(
    correlation_risks: pd.DataFrame,
    vif_risks: pd.DataFrame,
    variables: list[str],
    corr_threshold: float,
    vif_metric: str,
    vif_threshold: float,
    corr_metadata: dict[str, object],
) -> str:
    """生成面向人工复核的 Markdown 审核报告。"""
    lines = [
        "# Fama-MacBeth 变量相关性与 VIF 审核报告",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
        "## 一、审核口径",
        "",
        f"- 分析变量数：{len(variables)}。",
        f"- 相关性风险：非对角线变量对的 `abs(mean_corr) >= {corr_threshold:.2f}`。",
        "- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。",
        f"- VIF 风险：`{vif_metric} > {vif_threshold:.1f}`。",
        f"- 相关系数有效月份数：{corr_metadata.get('eligible_months', 0)}。",
        "",
        "阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；"
        "`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，"
        "同时避免 `max_vif` 被个别月份异常放大。",
        "",
        "## 二、相关性风险变量对",
        "",
    ]

    if correlation_risks.empty:
        lines.append(f"按 `abs(mean_corr) >= {corr_threshold:.2f}` 口径，本次未发现相关性风险变量对。")
    else:
        lines.append(
            f"按 `abs(mean_corr) >= {corr_threshold:.2f}` 口径，本次发现 "
            f"{len(correlation_risks)} 组相关性风险变量对："
        )
        lines.append("")
        lines.append(
            format_markdown_table(
                correlation_risks,
                [
                    "variable_1",
                    "variable_2",
                    "mean_corr",
                    "abs_mean_corr",
                    "stars",
                    "n_months",
                    "risk_level",
                ],
                ["mean_corr", "abs_mean_corr"],
            )
        )

    lines.extend(["", "## 三、VIF 风险变量", ""])
    if vif_risks.empty:
        lines.append(
            f"按 `{vif_metric} > {vif_threshold:.1f}` 口径，本次未发现稳定偏高的 VIF 风险变量。"
        )
    else:
        lines.append(
            f"按 `{vif_metric} > {vif_threshold:.1f}` 口径，本次发现 "
            f"{len(vif_risks)} 个 VIF 风险变量："
        )
        lines.append("")
        lines.append(
            format_markdown_table(
                vif_risks,
                [
                    "variable",
                    "mean_vif",
                    "median_vif",
                    "p90_vif",
                    "max_vif",
                    "ok_months",
                    "failed_or_skipped_months",
                    "risk_level",
                ],
                ["mean_vif", "median_vif", "p90_vif", "max_vif"],
            )
        )

    lines.extend(
        [
            "",
            "## 四、建议解读",
            "",
            "- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。",
            "- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。",
            "- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。",
            "- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。",
        ]
    )
    return "\n".join(lines) + "\n"


def analyze_variable_set(
    data: pd.DataFrame,
    variables: list[str],
    date_col: str,
    min_cross_section_n: int,
) -> dict[str, object]:
    """对一组变量完成相关系数、VIF 和风险表计算。"""
    # 先统一日期和变量数值类型，后面的相关系数和 VIF 都依赖这些列是数值。
    analysis_data = normalize_analysis_data(data, variables, date_col)
    # 按 Fama-MacBeth 口径计算月度横截面相关系数，再做时间序列汇总。
    corr_summary, corr_table, corr_table_with_stars, corr_metadata = (
        build_correlation_outputs(
            analysis_data,
            variables,
            date_col,
            min_cross_section_n,
        )
    )
    # VIF 同样按月计算，方便识别某些月份的横截面共线性问题。
    monthly_vif = build_monthly_vif_long(
        analysis_data,
        variables,
        date_col,
        min_cross_section_n,
    )
    # 将月度 VIF 汇总成变量层面的均值、中位数、p90 和最大值。
    vif_summary = summarize_monthly_vif(monthly_vif)
    # pooled VIF 只是补充诊断，帮助观察整体样本里的变量线性关系。
    overall_vif, overall_vif_metadata = build_overall_vif(
        analysis_data,
        variables,
        date_col,
    )
    # 从长表中抽取超过阈值的相关性风险对，便于人工优先查看。
    correlation_risks = build_correlation_risk_pairs(
        corr_summary,
        CORRELATION_RISK_THRESHOLD,
    )
    # 从 VIF 汇总里抽取超过阈值的变量。
    vif_risks = build_vif_risk_variables(
        vif_summary,
        VIF_RISK_METRIC,
        VIF_RISK_THRESHOLD,
    )

    return {
        "corr_summary": corr_summary,
        "corr_table": corr_table,
        "corr_table_with_stars": corr_table_with_stars,
        "corr_metadata": corr_metadata,
        "monthly_vif": monthly_vif,
        "vif_summary": vif_summary,
        "overall_vif": overall_vif,
        "overall_vif_metadata": overall_vif_metadata,
        "correlation_risks": correlation_risks,
        "vif_risks": vif_risks,
    }


def add_factor_label(data: pd.DataFrame, factor_col: str) -> pd.DataFrame:
    """给单个 factor 的诊断输出加上 factor 标记列。"""
    # 空表也要带上 factor 列，后面 concat 后的输出 schema 才稳定。
    result = data.copy()
    result.insert(0, "factor", factor_col)
    return result


def main() -> None:
    """脚本入口：读取数据、计算相关系数和 VIF、写出所有结果。"""
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    default_consistency_columns = flatten_factor_columns(list(REGRESSION_CONFIG["factors"]))
    default_control_columns = list(REGRESSION_CONFIG["controls"])
    variables, variable_source_info = choose_variables(
        args, default_consistency_columns, default_control_columns
    )

    data = pd.read_parquet(args.input)
    required_variables = list(variables)
    if variable_source_info["mode"] == "grouped_consistency_control":
        # 交互项列稍后在脚本内生成；这里检查生成它们所需的 rank_mean 等源列。
        for factor_col in variable_source_info["consistency_columns"]:
            required_variables.extend(interaction_source_columns_for_factor(factor_col))
    require_columns(
        data,
        [DATE_COL] + list(dict.fromkeys(required_variables)) + get_filter_columns(),
        args.input,
    )

    factor_filter_metadata: dict[str, dict[str, object]] = {}
    if variable_source_info["mode"] == "grouped_consistency_control":
        # 默认 registry 模式：每个 Consistency 指标单独应用自己的 factor_sample_filters。
        per_factor_outputs: list[dict[str, object]] = []
        for factor_col in variable_source_info["consistency_columns"]:
            factor_variables = diagnostic_variables_for_factor(
                factor_col,
                variable_source_info["control_columns"],
            )
            factor_filters = get_filters_for_factor(factor_col)
            factor_filter_metadata[factor_col] = factor_filters
            factor_data = apply_sample_filters(data, factor_filters)
            # 中心化均值使用和回归相同的完整候选样本：因变量、当前 FAC、
            # 对应 rank_mean 及所有控制变量都非缺失，其他期限不会影响本期限。
            raw_required = list(
                dict.fromkeys(
                    [Y_COL, factor_col]
                    + interaction_source_columns_for_factor(factor_col)
                    + list(variable_source_info["control_columns"])
                )
            )
            centering_mask = factor_data[raw_required].notna().all(axis=1)
            factor_data = add_interaction_columns(
                factor_data, factor_col, centering_mask
            )
            output = analyze_variable_set(
                data=factor_data,
                variables=factor_variables,
                date_col=DATE_COL,
                min_cross_section_n=args.min_cross_section_n,
            )
            output["factor_col"] = factor_col
            output["variables"] = factor_variables
            output["filtered_rows"] = int(len(factor_data))
            per_factor_outputs.append(output)

        corr_summary = pd.concat(
            [
                add_factor_label(output["corr_summary"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        corr_table = pd.concat(
            [
                add_factor_label(output["corr_table"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        corr_table_with_stars = pd.concat(
            [
                add_factor_label(output["corr_table_with_stars"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        monthly_vif = pd.concat(
            [
                add_factor_label(output["monthly_vif"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        vif_summary = pd.concat(
            [
                add_factor_label(output["vif_summary"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        overall_vif = pd.concat(
            [
                add_factor_label(output["overall_vif"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        correlation_risks = pd.concat(
            [
                add_factor_label(output["correlation_risks"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        vif_risks = pd.concat(
            [
                add_factor_label(output["vif_risks"], str(output["factor_col"]))
                for output in per_factor_outputs
            ],
            ignore_index=True,
        )
        corr_metadata = {
            "mode": "factor_specific_filters",
            "factor_outputs": {
                str(output["factor_col"]): {
                    "variables": output["variables"],
                    "filters": factor_filter_metadata[str(output["factor_col"])],
                    "filtered_rows": output["filtered_rows"],
                    "corr_metadata": output["corr_metadata"],
                    "overall_vif_metadata": output["overall_vif_metadata"],
                }
                for output in per_factor_outputs
            },
        }
        # 报告和 metadata 使用真正进入各期限诊断的完整变量合集。
        variables = list(
            dict.fromkeys(
                variable
                for output in per_factor_outputs
                for variable in output["variables"]
            )
        )
        variable_source_info["variables"] = variables
        variable_source_info["expanded_variables_by_factor"] = {
            str(output["factor_col"]): output["variables"]
            for output in per_factor_outputs
        }
    else:
        # 手动变量模式没有明确的“当前 factor”，只应用共同基础筛选，维持旧的整体诊断语义。
        factor_filter_metadata["manual_variables"] = dict(SAMPLE_FILTERS)
        filtered_data = apply_sample_filters(data, SAMPLE_FILTERS)
        output = analyze_variable_set(
            data=filtered_data,
            variables=variables,
            date_col=DATE_COL,
            min_cross_section_n=args.min_cross_section_n,
        )
        corr_summary = output["corr_summary"]
        corr_table = output["corr_table"]
        corr_table_with_stars = output["corr_table_with_stars"]
        corr_metadata = output["corr_metadata"]
        monthly_vif = output["monthly_vif"]
        vif_summary = output["vif_summary"]
        overall_vif = output["overall_vif"]
        correlation_risks = output["correlation_risks"]
        vif_risks = output["vif_risks"]

    diagnostic_review = build_diagnostic_review_markdown(
        correlation_risks,
        vif_risks,
        variables,
        CORRELATION_RISK_THRESHOLD,
        VIF_RISK_METRIC,
        VIF_RISK_THRESHOLD,
        corr_metadata,
    )

    corr_summary.to_csv(
        output_dir / "fama_macbeth_correlation_summary_long.csv",
        index=False,
        encoding="utf-8-sig",
    )
    corr_table.to_csv(
        output_dir / "fama_macbeth_correlation_table.csv",
        index=False,
        encoding="utf-8-sig",
    )
    corr_table_with_stars.to_csv(
        output_dir / "fama_macbeth_correlation_table_with_stars.csv",
        index=False,
        encoding="utf-8-sig",
    )
    monthly_vif.to_csv(
        output_dir / "fama_macbeth_monthly_vif_long.csv",
        index=False,
        encoding="utf-8-sig",
    )
    vif_summary.to_csv(
        output_dir / "fama_macbeth_time_series_vif_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    overall_vif.to_csv(
        output_dir / "fama_macbeth_overall_vif.csv",
        index=False,
        encoding="utf-8-sig",
    )
    correlation_risks.to_csv(
        output_dir / "result_fama_macbeth_correlation_risk_pairs.csv",
        index=False,
        encoding="utf-8-sig",
    )
    vif_risks.to_csv(
        output_dir / "result_fama_macbeth_vif_risk_variables.csv",
        index=False,
        encoding="utf-8-sig",
    )
    with open(
        output_dir / "fama_macbeth_variable_diagnostic_review.md",
        "w",
        encoding="utf-8",
    ) as file:
        file.write(diagnostic_review)

    metadata = {
        "run_time": datetime.now().isoformat(timespec="seconds"),
        "model_key": args.model,
        "input_path": str(args.input),
        "output_dir": str(output_dir),
        "date_col": DATE_COL,
        "min_cross_section_n": int(args.min_cross_section_n),
        "source_config": str(REGISTRY_PATH),
        "interaction_centering": INTERACTION_CENTERING,
        "variable_source_info": variable_source_info,
        "sample_filters": SAMPLE_FILTERS,
        "factor_sample_filters": {
            str(factor): dict(filters)
            for factor, filters in FACTOR_SAMPLE_FILTERS.items()
        },
        "filters_by_factor": factor_filter_metadata,
        "input_rows": int(len(data)),
        "input_months": int(pd.to_datetime(data[DATE_COL], errors="coerce").nunique()),
        "correlation": corr_metadata,
        "vif": {
            "monthly_ok_rows": int((monthly_vif["status"] == "ok").sum()),
            "monthly_failed_or_skipped_rows": int(
                (monthly_vif["status"] != "ok").sum()
            ),
        },
        "diagnostic_review": {
            "correlation_risk_threshold": float(CORRELATION_RISK_THRESHOLD),
            "correlation_risk_pair_count": int(len(correlation_risks)),
            "vif_risk_metric": VIF_RISK_METRIC,
            "vif_risk_threshold": float(VIF_RISK_THRESHOLD),
            "vif_risk_variable_count": int(len(vif_risks)),
            "correlation_risk_output": str(
                output_dir / "result_fama_macbeth_correlation_risk_pairs.csv"
            ),
            "vif_risk_output": str(
                output_dir / "result_fama_macbeth_vif_risk_variables.csv"
            ),
            "markdown_review_output": str(
                output_dir / "fama_macbeth_variable_diagnostic_review.md"
            ),
        },
        "note": "相关系数和月度 VIF 均按 Fama-MacBeth 的月度横截面口径计算；overall VIF 是 pooled 补充诊断。",
    }
    with open(
        output_dir / "fama_macbeth_variable_correlation_metadata.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    print(f"变量相关系数和 VIF 检查完成，结果已输出到：{output_dir}")
    print(f"最终变量数：{len(variables)}")
    if "eligible_months" in corr_metadata:
        print(f"相关系数有效月份数：{corr_metadata['eligible_months']}")
    else:
        print("相关系数有效月份数按 factor 分别记录在 metadata 中。")
    print(f"相关性风险变量对数量：{len(correlation_risks)}")
    print(f"VIF 风险变量数量：{len(vif_risks)}")
    print("VIF 时间序列摘要：")
    print(vif_summary.to_string(index=False))


if __name__ == "__main__":
    main()
