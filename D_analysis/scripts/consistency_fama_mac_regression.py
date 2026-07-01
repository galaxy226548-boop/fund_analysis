"""
基金一致性因子的 Fama-MacBeth 横截面回归。

这个脚本假设输入表已经完成了样本筛选、Consistency 构造和 winsorize。
脚本本身只负责：
1. 针对每个 Consistency 指标生成有效样本标记；
2. 按月做横截面 OLS；
3. 对月度系数序列计算 Fama-MacBeth 均值和 Newey-West 标准误；
4. 输出回归结果、月度系数和样本摘要。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


# =============================================================================
# 配置区：后续修改变量、样本门槛或 Newey-West 滞后阶数时，优先改这里
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_MODEL_KEY = "fm_baseline"


def parse_model_key() -> str:
    """在完整参数解析前，先读取 --model 以加载对应 registry 配置。

    回归脚本的输入路径、输出目录、变量清单和筛选条件都来自 registry。
    因此需要先知道模型 key，再初始化这些全局配置。
    """
    # 创建一个不显示帮助信息的临时解析器，只为提前读取 --model 参数。
    parser = argparse.ArgumentParser(add_help=False)
    # 注册 --model 参数，默认值指向 fm_baseline 模型配置。
    parser.add_argument("--model", default=DEFAULT_MODEL_KEY)
    # parse_known_args 允许存在其他未注册参数，不会因未知参数报错。
    args, _ = parser.parse_known_args()
    # 返回解析得到的模型 key 字符串。
    return str(args.model)


def load_regression_config(model_key: str) -> dict[str, object]:
    """从统一注册表读取回归配置。

    这里按文件路径加载，是为了让脚本既能直接运行，也能被测试或其他脚本
    用 importlib 按路径加载，不依赖当前 sys.path 的具体状态。
    """

    # 先检查注册表文件是否存在，不存在则尽早报错。
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    # 按文件路径构造模块加载规格，不依赖 sys.path。
    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    # 如果规格或加载器为空，说明文件无法被 Python 识别为模块。
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    # 根据规格创建模块对象并执行模块代码，使其中的函数可供调用。
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 调用注册表模块的 get_regression_config 函数，获取指定模型 key 的完整配置字典。
    return module.get_regression_config(model_key)


# 在模块加载时解析命令行中的模型 key，并据此加载对应的 registry 配置。
MODEL_KEY = parse_model_key()
REGRESSION_CONFIG = load_regression_config(MODEL_KEY)


def project_path(config_key: str) -> Path:
    """把注册表里的项目相对路径转成绝对路径，减少脚本内硬编码。"""
    # 从配置字典中取出相对路径，拼接项目根目录得到绝对路径。
    return PROJECT_ROOT / str(REGRESSION_CONFIG[config_key])


# 从 registry 配置中提取输入文件路径和输出目录路径。
INPUT_PATH = project_path("regression_input_path")
OUTPUT_DIR = project_path("output_dir")

# 提取日期列名、样本筛选条件、因变量列名等核心配置。
DATE_COL = str(REGRESSION_CONFIG["date_col"])
SAMPLE_FILTERS = dict(REGRESSION_CONFIG["sample_filters"])
# 取基础筛选条件中的第一个列名和对应期望值，用于快速引用主筛选字段。
INSAMPLE_COL = str(next(iter(SAMPLE_FILTERS)))
INSAMPLE_EXPECTED_VALUE = SAMPLE_FILTERS[INSAMPLE_COL]
Y_COL = str(REGRESSION_CONFIG["y"])

# 提取 Consistency 因子配置和控制变量列名列表。
# factors 中的元素可以是字符串，也可以是 tuple/list。字符串表示旧模型里的单个
# factor；tuple/list 表示一组 dummy 变量要同时进入同一个回归。
CONSISTENCY_COLS = list(REGRESSION_CONFIG["factors"])
FACTOR_GROUP_SUFFIXES = dict(REGRESSION_CONFIG.get("factor_group_suffixes", {}))
CONTROL_COLS = list(REGRESSION_CONFIG["controls"])
# 提取每个 factor 各自的额外筛选条件；没有额外条件时默认为空字典。
FACTOR_SAMPLE_FILTERS = {
    factor: dict(filters)
    for factor, filters in dict(REGRESSION_CONFIG.get("factor_sample_filters", {})).items()
}
# 提取样本对齐列：null 模型用这些列做 dropna 来对齐样本，但不把它们放进回归。
# 这样 controls-only 回归的样本与 fm_baseline 中对应 factor 的样本完全一致。
SAMPLE_ALIGNMENT_COLUMNS = list(
    REGRESSION_CONFIG.get("sample_alignment_columns") or []
)
# 提取交互项的原始配置列表；没有交互项时默认为空列表。
RAW_INTERACTIONS = list(REGRESSION_CONFIG.get("interactions") or [])
# 交互模型可以显式登记需要同时入模的主效应。占位符会在每套期限回归时
# 解析成真实列名，避免把五套 rank_mean 一次性全部放入同一个截面回归。
RAW_INTERACTION_MAIN_EFFECTS = list(
    REGRESSION_CONFIG.get("interaction_main_effects") or []
)
# 交互模型可以要求先对交互项两侧变量做月度截面去均值。该配置独立于
# standardize：前者只减均值，后者是减均值后再除以标准差。
RAW_INTERACTION_CENTERING = REGRESSION_CONFIG.get("interaction_centering", "none")

MIN_CROSS_SECTION_N = int(REGRESSION_CONFIG["min_cross_section_n"])
NEWEY_WEST_LAG = int(REGRESSION_CONFIG["newey_west_lag"])

STANDARDIZE_NONE = "none"
STANDARDIZE_CROSS_SECTION = "cross_section"
CENTER_NONE = "none"
CENTER_CROSS_SECTION_MEAN = "cross_section_mean"
CURRENT_FACTOR_PLACEHOLDER = "FAC"
MATCHED_RANK_MEAN_PLACEHOLDER = "RANK_MEAN"
STANDARDIZE_ALIASES = {
    "none": STANDARDIZE_NONE,
    "": STANDARDIZE_NONE,
    "no": STANDARDIZE_NONE,
    "不标准化": STANDARDIZE_NONE,
    "不標準化": STANDARDIZE_NONE,
    "cross_section": STANDARDIZE_CROSS_SECTION,
    "cross-section": STANDARDIZE_CROSS_SECTION,
    "cross_sectional": STANDARDIZE_CROSS_SECTION,
    "by_month": STANDARDIZE_CROSS_SECTION,
    "section": STANDARDIZE_CROSS_SECTION,
    "按回归截面标准化": STANDARDIZE_CROSS_SECTION,
    "按回歸截面標準化": STANDARDIZE_CROSS_SECTION,
}
CENTERING_ALIASES = {
    "none": CENTER_NONE,
    "": CENTER_NONE,
    "no": CENTER_NONE,
    "不中心化": CENTER_NONE,
    "cross_section_mean": CENTER_CROSS_SECTION_MEAN,
    "cross-section-mean": CENTER_CROSS_SECTION_MEAN,
    "by_month_mean": CENTER_CROSS_SECTION_MEAN,
    "monthly_demean": CENTER_CROSS_SECTION_MEAN,
    "月度去均值": CENTER_CROSS_SECTION_MEAN,
}


def is_factor_group(factor_spec: object) -> bool:
    """判断一个 factor 配置是否是一组同时入模的变量。"""
    # tuple/list 代表一组需要同时进入同一套回归的 dummy；其他类型按单变量处理。
    return isinstance(factor_spec, (tuple, list))


def factor_columns_for_spec(factor_spec: object) -> list[str]:
    """把单个 factor 配置转换成实际需要读取和入模的列名列表。"""
    # 分组配置逐个转成字符串；单变量配置则包成单元素列表，统一后续处理方式。
    if is_factor_group(factor_spec):
        columns = [str(column) for column in factor_spec]
    else:
        columns = [str(factor_spec)]

    # 空组或空列名无法形成有效设计矩阵，因此在真正读取数据前就报出配置错误。
    if not columns or any(not column for column in columns):
        raise ValueError(f"factor 配置不能为空：{factor_spec!r}")
    # 返回标准化后的列名列表，后续代码无需再区分单变量和变量组。
    return columns


def all_factor_columns(factor_specs: list[object]) -> list[str]:
    """列出所有 factor 配置实际依赖的输入列，去重并保留顺序。"""
    # 先按 registry 中的顺序展开每个单变量或变量组。
    columns: list[str] = []
    for factor_spec in factor_specs:
        columns.extend(factor_columns_for_spec(factor_spec))
    # dict 会保留插入顺序，因此可以在去重后维持稳定的输入列顺序。
    return list(dict.fromkeys(columns))


def clean_factor_label(raw_label: str) -> str:
    """把自动生成的 factor 名称整理成适合写入 CSV 的稳定文本。"""
    # 文件名不友好的符号和连续空白统一替换成下划线。
    label = re.sub(r'[\\/:*?"<>|\s]+', "_", raw_label.strip())
    # 去掉首尾分隔符；如果清理后为空，使用稳定的兜底名称。
    label = label.strip("._-")
    return label or "factor_group"


def infer_factor_group_label(factor_cols: list[str]) -> str:
    """当 registry 没有 suffix 时，从 dummy 列名自动生成组名。"""
    # 同一 dummy 组的列名共享窗口信息，因此只需检查第一列。
    first_col = factor_cols[0]
    # 优先同时提取 m/n 窗口和 pairwise 步长，生成信息最完整的标签。
    match = re.search(r"(m\d+_n\d+).*?(pairwise\d+)", first_col)
    if match:
        return clean_factor_label(f"{match.group(1)}_{match.group(2)}")

    # 旧列名可能没有 pairwise；此时至少保留 m/n 窗口信息。
    match = re.search(r"m\d+_n\d+", first_col)
    if match:
        return clean_factor_label(match.group(0))

    # 如果列名不符合已知模式，就拼接整组列名，避免不同组被误标成同一名称。
    return clean_factor_label("_".join(factor_cols))


def factor_label_for_spec(factor_spec: object) -> str:
    """返回输出表中用于标记当前模型的 factor 名称。"""
    # 单变量模型直接使用原列名，便于从结果追溯到输入数据。
    if not is_factor_group(factor_spec):
        return str(factor_spec)

    # 变量组先转换成稳定 tuple，才能作为 suffix 映射表的 key。
    factor_cols = tuple(factor_columns_for_spec(factor_spec))
    # registry 未显式登记短名称时，从列名模式自动推导。
    suffix = FACTOR_GROUP_SUFFIXES.get(factor_cols)
    if suffix is None:
        suffix = infer_factor_group_label(list(factor_cols))
    # 最后统一清理标签中的特殊字符，保证 CSV 内容稳定。
    return clean_factor_label(str(suffix))


def factor_sample_filter_key(factor_spec: object) -> object:
    """返回 factor_sample_filters 中优先使用的 key。"""
    # 分组配置转成 tuple 才能作为字典 key；单变量继续使用列名字符串。
    if is_factor_group(factor_spec):
        return tuple(factor_columns_for_spec(factor_spec))
    return str(factor_spec)


def parse_args() -> argparse.Namespace:
    """读取命令行参数。

    目前业务配置都来自 registry，命令行只需要声明使用哪个模型版本。
    """
    # 创建完整的命令行解析器，包含帮助信息。
    parser = argparse.ArgumentParser(description="运行 Consistency Fama-MacBeth 回归。")
    # 注册 --model 参数，允许用户指定要运行的回归模型配置。
    parser.add_argument(
        "--model",
        default=MODEL_KEY,
        help="regression_registry.py 中的模型名称，默认 fm_baseline。",
    )
    # 解析并返回命令行参数对象。
    return parser.parse_args()


def normalize_standardize_method(method: object) -> str:
    """把配置中的标准化写法统一成脚本内部使用的取值。

    registry 可能由人工维护，写法容易出现 ``cross-section``、中文描述等小差异。
    这里集中做一次归一化，既让配置更好写，也能在拼错时尽早报出清楚错误。
    """
    # 将输入统一转为小写字符串后查表匹配；None 默认为不标准化。
    normalized = STANDARDIZE_ALIASES.get(
        str(method if method is not None else STANDARDIZE_NONE).strip().lower()
    )
    # 如果查表找不到匹配项，说明配置写法有误，列出合法取值帮助排查。
    if normalized is None:
        available = ", ".join(sorted({STANDARDIZE_NONE, STANDARDIZE_CROSS_SECTION}))
        raise ValueError(f"未知交互项标准化方式：{method!r}；可选值：{available}")
    # 返回归一化后的标准化方式字符串。
    return normalized


def normalize_centering_method(method: object) -> str:
    """把交互变量中心化配置统一成脚本内部使用的取值。"""
    # 配置缺省时保持原模型行为；人工拼错则尽早报错，避免静默跑错口径。
    normalized = CENTERING_ALIASES.get(
        str(method if method is not None else CENTER_NONE).strip().lower()
    )
    if normalized is None:
        available = ", ".join(sorted({CENTER_NONE, CENTER_CROSS_SECTION_MEAN}))
        raise ValueError(f"未知交互变量中心化方式：{method!r}；可选值：{available}")
    return normalized


INTERACTION_CENTERING = normalize_centering_method(RAW_INTERACTION_CENTERING)


def parse_braced_interaction(text: str) -> tuple[str, str]:
    """解析 ``{X1,X2}`` 形式的交互项声明。"""
    # 去掉首尾空白后检查是否以花括号包围。
    stripped = text.strip()
    # 如果格式不是 {…}，说明配置写法不合规，直接报错。
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError(f"字符串交互项必须写成 {{X1,X2}} 形式：{text!r}")

    # 去掉左右花括号后按逗号切分。只允许两个变量，避免把错误配置静默解释成别的模型。
    variables = [part.strip() for part in stripped[1:-1].split(",") if part.strip()]
    # 交互项必须恰好两个变量；多于或少于两个都是配置错误。
    if len(variables) != 2:
        raise ValueError(f"交互项必须恰好包含两个变量：{text!r}")
    # 返回解析出的两个变量名。
    return variables[0], variables[1]


def make_interaction_name(var1: str, var2: str, standardize: str) -> str:
    """生成交互项列名，列名会出现在月度系数和最终结果文件中。"""
    # 原始乘积和截面标准化乘积含义不同，因此标准化版本在列名里加后缀，避免混淆。
    suffix = "" if standardize == STANDARDIZE_NONE else "__zcs"
    # dmcs 表示 demeaned by cross-section，明确区分原始乘积与月度去均值乘积。
    if INTERACTION_CENTERING == CENTER_CROSS_SECTION_MEAN:
        suffix += "__dmcs"
    # 用 __x__ 连接两个变量名，生成形如 var1__x__var2 的交互项列名。
    return f"{var1}__x__{var2}{suffix}"


def resolve_interaction_variable(variable: str, factor_col: str) -> str:
    """把交互项占位符替换成当前 factor 对应的真实列名。"""
    # registry 里写 FAC 时，意思是“当前 factor”，这样不用为 5 个 Consistency 重复登记。
    # 如果变量名等于占位符，替换成当前实际的 Consistency 列名。
    if variable == CURRENT_FACTOR_PLACEHOLDER:
        return factor_col
    # RANK_MEAN 表示当前 FAC 的同一组 (m,n) rank_mean，例如
    # FAC_rank_vol_m3_n6_pairwise1 -> rank_mean_m3_n6_pairwise1。
    if variable == MATCHED_RANK_MEAN_PLACEHOLDER:
        if not factor_col.startswith("FAC_rank_vol_"):
            raise ValueError(f"无法从当前 factor 推导 rank_mean 列名：{factor_col!r}")
        return factor_col.replace("FAC_rank_vol_", "rank_mean_", 1)
    # 非占位符变量直接原样返回。
    return variable


def resolve_current_factor_placeholder(factor_cols: list[str], placeholder_name: str) -> str:
    """把需要唯一当前 factor 的占位符解析成真实列名。"""
    # FAC/RANK_MEAN 都需要一个唯一当前因子来定位真实列；dummy 组无法无歧义推导。
    if len(factor_cols) != 1:
        raise ValueError(
            f"{placeholder_name} 占位符只能用于单 factor 模型；"
            f"当前 factor 组包含多列：{factor_cols}"
        )
    # 单 factor 模型只有一个候选，直接返回其真实列名。
    return factor_cols[0]


def parse_interaction_config(raw_interactions: list[object]) -> list[dict[str, str]]:
    """把 registry 中的交互项配置整理成统一的字典列表。

    支持三类写法：
    1. ``"{X1,X2}"``：最接近公式登记的写法，默认不标准化；
    2. ``["X1", "X2"]`` / ``("X1", "X2")`` / ``{"X1", "X2"}``：默认不标准化；
    3. ``{"variables": ["X1", "X2"], "standardize": "cross_section"}``：
       显式声明两个变量和标准化方式。
    """
    # 用列表收集解析后的交互项配置字典。
    parsed: list[dict[str, str]] = []

    # 逐个遍历 registry 中登记的交互项原始配置。
    for index, item in enumerate(raw_interactions, start=1):
        # 每个交互项默认不做标准化。
        standardize = STANDARDIZE_NONE
        # 默认无自定义列名，后面会自动生成。
        name: str | None = None

        # 根据配置项的类型分别解析：字符串走花括号解析。
        if isinstance(item, str):
            var1, var2 = parse_braced_interaction(item)
        elif isinstance(item, dict):
            # dict 写法用于同时登记变量和标准化方式；支持几个常见字段名，减少配置负担。
            # 依次尝试几种常见的变量字段名，以适配不同配置习惯。
            if "variables" in item:
                variables = item["variables"]
            elif "vars" in item:
                variables = item["vars"]
            elif "columns" in item:
                variables = item["columns"]
            # 也支持用 x1/x2 分别指定两个变量。
            elif {"x1", "x2"}.issubset(item):
                variables = [item["x1"], item["x2"]]
            else:
                raise ValueError(
                    "字典交互项必须包含 variables/vars/columns，"
                    f"或同时包含 x1 和 x2：第 {index} 项 {item!r}"
                )

            # 如果 variables 本身是花括号字符串，则复用花括号解析逻辑。
            if isinstance(variables, str):
                var1, var2 = parse_braced_interaction(variables)
            else:
                # set 无序，先排序以保证列名稳定；其他可迭代类型转为列表。
                variables = sorted(variables) if isinstance(variables, set) else list(variables)
                # 严格要求恰好两个变量。
                if len(variables) != 2:
                    raise ValueError(f"交互项必须恰好包含两个变量：第 {index} 项 {item!r}")
                var1, var2 = str(variables[0]), str(variables[1])

            # 从字典中读取标准化方式，并归一化为脚本内部取值。
            standardize = normalize_standardize_method(item.get("standardize", STANDARDIZE_NONE))
            # 如果字典中显式指定了列名，则使用自定义列名。
            name = str(item["name"]).strip() if item.get("name") else None
        elif isinstance(item, (list, tuple, set)):
            # list/tuple/set 写法：set 无序需排序以稳定列名，list/tuple 保留原序。
            variables = sorted(item) if isinstance(item, set) else list(item)
            # 同样要求恰好两个变量。
            if len(variables) != 2:
                raise ValueError(f"交互项必须恰好包含两个变量：第 {index} 项 {item!r}")
            var1, var2 = str(variables[0]), str(variables[1])
        else:
            # 遇到不支持的类型直接报错，避免静默忽略。
            raise TypeError(f"不支持的交互项配置类型：第 {index} 项 {type(item).__name__}")

        # 统一去掉变量名两端空白。
        var1 = str(var1).strip()
        var2 = str(var2).strip()
        # 变量名为空说明配置有误。
        if not var1 or not var2:
            raise ValueError(f"交互项变量名不能为空：第 {index} 项 {item!r}")
        # 两个变量相同的交互项在统计上没有意义。
        if var1 == var2:
            raise ValueError(f"交互项的两个变量不能相同：第 {index} 项 {item!r}")

        # 把解析后的变量名、标准化方式和列名组装成字典，加入结果列表。
        parsed.append(
            {
                "var1": var1,
                "var2": var2,
                "standardize": standardize,
                "name": name or make_interaction_name(var1, var2, standardize),
            }
        )

    # 检查所有交互项的最终列名是否有重复；重复会导致 DataFrame 列覆盖。
    names = [interaction["name"] for interaction in parsed]
    duplicated_names = sorted({name for name in names if names.count(name) > 1})
    if duplicated_names:
        raise ValueError(f"交互项列名重复，请在 registry 中用 name 显式区分：{duplicated_names}")

    # 返回解析完成的交互项配置列表。
    return parsed


INTERACTIONS = parse_interaction_config(RAW_INTERACTIONS)

# 同一个交互项不能同时走 z-score 和“仅去均值”两套变换，否则语义重复且
# 输出列名难以解释。需要 z-score 时应关闭 interaction_centering。
if INTERACTION_CENTERING != CENTER_NONE and any(
    interaction["standardize"] != STANDARDIZE_NONE for interaction in INTERACTIONS
):
    raise ValueError("interaction_centering 不能与交互项 standardize 同时启用")


def get_interaction_source_columns() -> list[str]:
    """列出构造交互项需要读取的原始变量列。"""
    # 遍历所有交互项配置，收集其中引用的真实列名。
    columns: list[str] = []
    for interaction in INTERACTIONS:
        # FAC 是运行时才替换成当前 Consistency 指标的占位符，不是输入表里的真实列名。
        # RANK_MEAN 也是运行时按当前 Consistency 的 (m,n) 推导，因此这里要展开成
        # registry 中所有单 factor 规格对应的真实列，供输入表完整性检查使用。
        for variable in [interaction["var1"], interaction["var2"]]:
            if variable == CURRENT_FACTOR_PLACEHOLDER:
                continue
            if variable == MATCHED_RANK_MEAN_PLACEHOLDER:
                for factor_spec in CONSISTENCY_COLS:
                    factor_cols = factor_columns_for_spec(factor_spec)
                    factor_col = resolve_current_factor_placeholder(
                        factor_cols,
                        MATCHED_RANK_MEAN_PLACEHOLDER,
                    )
                    columns.append(resolve_interaction_variable(variable, factor_col))
                continue
            columns.append(variable)
    # 用 dict.fromkeys 去重并保持首次出现的顺序。
    return list(dict.fromkeys(columns))


def resolve_variable_for_factor(variable: str, factor_cols: list[str]) -> str:
    """把一个交互变量或主效应变量解析成当前 factor 对应的真实列名。"""
    # FAC 和 RANK_MEAN 都依赖“当前 factor”，必须先确认当前模型只有一个 factor 列。
    if variable in {
        CURRENT_FACTOR_PLACEHOLDER,
        MATCHED_RANK_MEAN_PLACEHOLDER,
    }:
        factor_col = resolve_current_factor_placeholder(factor_cols, variable)
        # 使用当前 factor 列替换占位符，得到本套期限真正使用的输入列。
        return resolve_interaction_variable(variable, factor_col)

    # 普通列名不依赖当前 factor，直接原样返回。
    return variable


def get_interaction_source_columns_for_factor(factor_cols: list[str]) -> list[str]:
    """列出当前 factor 构造交互项真正需要的原始列。

    这个函数与 ``get_interaction_source_columns`` 的用途不同：后者为整张输入表
    汇总所有期限的必需列；本函数只返回当前这套回归的列，避免截面标准化时
    错把其他期限变量的缺失情况纳入当前样本掩码。
    """
    # 按交互项登记顺序解析两侧变量，保证后续样本列清单稳定可读。
    columns: list[str] = []
    for interaction in INTERACTIONS:
        columns.append(resolve_variable_for_factor(interaction["var1"], factor_cols))
        columns.append(resolve_variable_for_factor(interaction["var2"], factor_cols))

    # 同一变量可能出现在多个交互项中，去重后只检查一次非缺失。
    return list(dict.fromkeys(columns))


def standardize_by_cross_section(
    data: pd.DataFrame,
    column: str,
    standardization_mask: pd.Series | None = None,
) -> pd.Series:
    """按回归月份对单个变量做横截面 z-score 标准化。"""

    def zscore(group: pd.Series) -> pd.Series:
        # 标准化只在当月横截面内部进行，避免把不同月份的水平变化混进交互项。
        numeric = pd.to_numeric(group, errors="coerce")
        # 使用总体标准差 ddof=0，使这里的 z-score 与常见截面标准化口径一致。
        std = numeric.std(ddof=0)
        if pd.isna(std) or std == 0:
            # 如果当月变量没有横截面波动，标准化没有定义，后续 dropna 会让这些观测不进回归。
            return pd.Series(np.nan, index=group.index)
        return (numeric - numeric.mean()) / std

    # 默认对传入数据全体做标准化；回归主流程会传入“当前模型可用样本”的掩码，
    # 让标准化均值和标准差真正来自当月回归截面。
    if standardization_mask is None:
        standardization_mask = pd.Series(True, index=data.index)

    # 先创建全缺失结果，只在允许参与当前模型标准化的行上写入 z-score。
    standardized = pd.Series(np.nan, index=data.index, dtype=float)
    # groupby.transform 会把每个月的标准化结果对齐回原始行索引。
    standardized.loc[standardization_mask] = (
        data.loc[standardization_mask].groupby(DATE_COL, sort=False)[column].transform(zscore)
    )
    # 返回与原数据索引完全一致的标准化序列，便于逐元素构造交互项。
    return standardized


def demean_by_cross_section(
    data: pd.DataFrame,
    column: str,
    centering_mask: pd.Series | None = None,
) -> pd.Series:
    """在每个月的实际候选回归样本内，对指定变量仅做去均值。"""
    if centering_mask is None:
        centering_mask = pd.Series(True, index=data.index)

    # 先保持全列缺失，只对当前模型变量完整的观测计算月均值。这样 FAC 和
    # rank_mean 的中心化样本与随后进入 Fama-MacBeth 回归的样本完全一致。
    centered = pd.Series(np.nan, index=data.index, dtype=float)
    numeric = pd.to_numeric(data.loc[centering_mask, column], errors="coerce")
    month_means = numeric.groupby(data.loc[centering_mask, DATE_COL], sort=False).transform(
        "mean"
    )
    centered.loc[centering_mask] = numeric - month_means
    return centered


def make_centered_column_name(column: str) -> str:
    """生成月度截面去均值主效应的稳定列名。"""
    return f"{column}__dmcs"


def get_regression_main_effect_columns(
    factor_cols: list[str], main_effect_cols: list[str]
) -> list[str]:
    """返回真正进入回归的主效应列；启用中心化时替换交互项两侧变量。"""
    original_columns = factor_cols + main_effect_cols
    if INTERACTION_CENTERING == CENTER_NONE or not INTERACTIONS:
        return original_columns

    interaction_sources = set(get_interaction_source_columns_for_factor(factor_cols))
    return [
        make_centered_column_name(column) if column in interaction_sources else column
        for column in original_columns
    ]


def add_interaction_columns(
    data: pd.DataFrame,
    factor_cols: list[str],
    factor_label: str,
    standardization_mask: pd.Series | None = None,
) -> pd.DataFrame:
    """根据 registry 配置生成交互项列。

    ``none`` 直接用两个原始变量相乘；``cross_section`` 则先在每个回归月份内
    分别标准化两个变量，再把标准化后的变量相乘。
    """
    # 如果没有配置任何交互项，直接返回原始数据，不做多余复制。
    if not INTERACTIONS:
        return data

    # 复制一份数据，避免在原始 DataFrame 上添加列影响调用方。
    result = data.copy()
    # 逐个交互项配置生成对应的新列。
    for interaction in INTERACTIONS:
        # 将 FAC/RANK_MEAN 占位符按当前 factor 解析，确定实际参与乘积的两个变量。
        var1_source = interaction["var1"]
        var2_source = interaction["var2"]
        var1 = resolve_variable_for_factor(var1_source, factor_cols)
        var2 = resolve_variable_for_factor(var2_source, factor_cols)
        # 读取预先生成的交互项列名和标准化方式。
        interaction_name = interaction["name"]
        standardize = interaction["standardize"]

        # 替换占位符后如果两个变量变成同一个，交互项没有意义，报错。
        if var1 == var2:
            raise ValueError(
                f"交互项 {interaction_name} 在当前 factor={factor_label} 下变成了同一个变量，"
                "请检查 registry 中的交互项配置。"
            )

        if standardize == STANDARDIZE_NONE:
            if INTERACTION_CENTERING == CENTER_CROSS_SECTION_MEAN:
                # 在当前期限模型的完整候选样本内分别减去 FAC 和 rank_mean 的
                # 当月均值；中心化主效应也写入结果，供设计矩阵直接使用。
                left = demean_by_cross_section(result, var1, standardization_mask)
                right = demean_by_cross_section(result, var2, standardization_mask)
                result[make_centered_column_name(var1)] = left
                result[make_centered_column_name(var2)] = right
            else:
                # 不做任何变换：直接将两个原始变量转为数值后相乘。
                left = pd.to_numeric(result[var1], errors="coerce")
                right = pd.to_numeric(result[var2], errors="coerce")
        elif standardize == STANDARDIZE_CROSS_SECTION:
            # 截面标准化：先在每个回归月份内对两个变量分别做 z-score，再相乘。
            left = standardize_by_cross_section(result, var1, standardization_mask)
            right = standardize_by_cross_section(result, var2, standardization_mask)
        else:
            raise ValueError(f"未知交互项标准化方式：{standardize!r}")

        # 将两个变量（或其标准化版本）逐元素相乘，写入新列。
        result[interaction_name] = left * right

    return result


def get_filter_columns() -> list[str]:
    """列出基础筛选和 per-factor 筛选会用到的全部字段。"""
    # 先收集基础筛选条件中涉及的列名。
    columns = list(SAMPLE_FILTERS)
    # 再追加每个 factor 各自的额外筛选条件涉及的列名。
    for filters in FACTOR_SAMPLE_FILTERS.values():
        columns.extend(filters)
    # 用 dict.fromkeys 去重并保留首次出现的顺序，返回完整的筛选列清单。
    return list(dict.fromkeys(columns))


def get_interaction_columns() -> list[str]:
    """列出所有将进入回归的交互项列名。"""
    # 从已解析的交互项配置中提取每个交互项的最终列名。
    return [interaction["name"] for interaction in INTERACTIONS]


def get_interaction_main_effect_columns(factor_cols: list[str]) -> list[str]:
    """解析当前 factor 回归需要加入的交互变量主效应。

    registry 使用 ``RANK_MEAN`` 时，本函数会根据当前一致性指标的期限，
    找到同期限的排名均值列。已经作为 factor 或控制变量入模的列会被去重，
    避免设计矩阵中出现完全重复的列。
    """
    # 先解析 registry 显式登记的主效应；FAC 主效应通常已由 factor_cols 提供。
    columns: list[str] = []
    for raw_variable in RAW_INTERACTION_MAIN_EFFECTS:
        # 统一去掉配置值两端空白，避免肉眼难发现的列名错误。
        variable = str(raw_variable).strip()
        if not variable:
            raise ValueError("interaction_main_effects 不能包含空变量名")

        # 把 FAC/RANK_MEAN 占位符换成当前期限的实际列名。
        resolved = resolve_variable_for_factor(variable, factor_cols)

        # factor 和控制变量已经在设计矩阵中，只追加尚未入模的主效应。
        if resolved not in factor_cols and resolved not in CONTROL_COLS:
            columns.append(resolved)

    # 去重但保留 registry 顺序，使输出列顺序稳定。
    columns = list(dict.fromkeys(columns))

    # 遵循交互项层级原则：交互项两侧变量都必须有对应主效应。
    # 过去这里完全依赖 interaction_main_effects，漏配时会静默跑成错误模型。
    modeled_main_effects = set(factor_cols + CONTROL_COLS + columns)
    interaction_sources = get_interaction_source_columns_for_factor(factor_cols)
    missing_main_effects = [
        column for column in interaction_sources if column not in modeled_main_effects
    ]
    if missing_main_effects:
        raise ValueError(
            "交互项缺少对应主效应，请在 interaction_main_effects 中补充："
            f"{missing_main_effects}"
        )

    # 返回当前 factor 回归真正需要额外加入的主效应列。
    return columns


def get_all_interaction_main_effect_columns() -> list[str]:
    """列出所有 factor 规格会用到的额外交互主效应列。"""
    # 逐套 factor 解析占位符，因为 RANK_MEAN 在不同期限会对应不同真实列。
    columns: list[str] = []
    for factor_spec in CONSISTENCY_COLS:
        factor_cols = factor_columns_for_spec(factor_spec)
        columns.extend(get_interaction_main_effect_columns(factor_cols))

    # 去重并保留 factor 的登记顺序，供输入列检查和错误信息稳定展示。
    return list(dict.fromkeys(columns))


def get_filters_for_factor(factor_spec: object) -> dict[str, object]:
    """返回某个 factor 实际使用的筛选条件。

    sample_filters 是共同基础口径；factor_sample_filters 是当前 factor 额外叠加的条件。
    如果同一列在两处设置了不同取值，直接报错，避免静默覆盖造成样本口径混乱。
    """
    # 以基础筛选条件为底，准备叠加当前 factor 的额外条件。
    combined_filters = dict(SAMPLE_FILTERS)
    # 获取当前 factor 特有的额外筛选条件；如果没有额外条件，返回空字典。
    factor_key = factor_sample_filter_key(factor_spec)
    factor_filters = FACTOR_SAMPLE_FILTERS.get(factor_key, {})
    if not factor_filters:
        factor_filters = FACTOR_SAMPLE_FILTERS.get(str(factor_key), {})
    factor_label = factor_label_for_spec(factor_spec)
    # 逐条合并额外筛选条件到基础筛选中。
    for column, expected_value in factor_filters.items():
        # 如果同一列在基础筛选和 factor 筛选中取值不同，说明配置矛盾，直接报错。
        if column in combined_filters and combined_filters[column] != expected_value:
            raise ValueError(
                f"{factor_label} 的筛选条件与基础筛选冲突："
                f"{column}={combined_filters[column]!r} vs {expected_value!r}"
            )
        # 把额外条件写入合并字典。
        combined_filters[column] = expected_value
    # 返回合并后的完整筛选条件字典。
    return combined_filters


def apply_sample_filters(
    data: pd.DataFrame,
    sample_filters: dict[str, object],
) -> pd.DataFrame:
    """按照给定筛选条件保留样本行。"""
    # 初始化全 True 掩码，后续逐个条件用 &= 收紧，最终只保留满足所有条件的行。
    mask = pd.Series(True, index=data.index)
    # 遍历每个筛选条件，依次收窄掩码。
    for column, expected_value in sample_filters.items():
        # 上游有时会把 1/0 存成 1.0 或字符串；数值条件优先用数值比较，减少类型误差。
        if isinstance(expected_value, (int, float)) and not isinstance(expected_value, bool):
            # 将列转为数值后与期望值做浮点数比较。
            actual_numeric = pd.to_numeric(data[column], errors="coerce")
            mask &= actual_numeric == float(expected_value)
        else:
            # 非数值条件统一转成字符串后做精确匹配。
            mask &= data[column].astype("string") == str(expected_value)
    # 按最终掩码筛选出符合条件的行，并复制一份以避免 SettingWithCopyWarning。
    return data.loc[mask].copy()


def check_required_columns(df: pd.DataFrame) -> None:
    """检查输入表是否包含回归所需列，避免后面报错位置太晚、太难读。"""
    # 把脚本运行必须用到的列集中列出来，后续检查只围绕这个清单进行。
    # SAMPLE_ALIGNMENT_COLUMNS 是 null 模型用来对齐样本的列，输入表中也必须存在。
    required_cols = (
        [DATE_COL, Y_COL]
        + all_factor_columns(CONSISTENCY_COLS)
        + CONTROL_COLS
        + get_interaction_source_columns()
        + get_all_interaction_main_effect_columns()
        + get_filter_columns()
        + SAMPLE_ALIGNMENT_COLUMNS
    )
    # 同一列可能同时扮演 factor、主效应或交互来源，去重后再检查可避免重复报错。
    required_cols = list(dict.fromkeys(required_cols))
    # 逐列检查输入表里是否存在；缺失列会被收集起来，方便一次性报出完整问题。
    missing_cols = [col for col in required_cols if col not in df.columns]
    # 如果有缺失列，直接停止脚本，避免后续回归时出现更难定位的 KeyError。
    if missing_cols:
        raise ValueError(f"输入表缺少必要列：{missing_cols}")

    # 交互项是脚本新生成的列。如果列名和原始输入列冲突，覆盖原列会让结果很难追溯。
    interaction_name_conflicts = [
        col for col in get_interaction_columns() if col in df.columns
    ]
    if interaction_name_conflicts:
        raise ValueError(
            "交互项生成列名与输入表已有列冲突，请在 registry 中用 name 指定新列名："
            f"{interaction_name_conflicts}"
        )


def ols_cross_section(data: pd.DataFrame, x_cols: list[str]) -> pd.Series:
    """
    对单个月份做一次横截面 OLS。

    这里不用 statsmodels，是为了让脚本只依赖项目当前环境里已有的 numpy/scipy。
    np.linalg.lstsq 可以处理普通最小二乘；如果某个月变量共线导致秩不足，
    主程序会跳过该月并记录失败原因。
    """
    # 把因变量 future_ret_6m 转成 numpy 数组，便于后面用线性代数公式做 OLS。
    y = data[Y_COL].to_numpy(dtype=float)
    # 把本次回归需要的解释变量和控制变量转成二维矩阵。
    x = data[x_cols].to_numpy(dtype=float)
    # 在解释变量矩阵最左侧加一列 1，用来估计截距项 const。
    x = np.column_stack([np.ones(len(x)), x])
    # 系数名称要和矩阵列顺序一致，方便把回归结果还原成带列名的 Series。
    coef_names = ["const"] + x_cols

    # 用最小二乘求解 beta；rank 会告诉我们设计矩阵是否满秩。
    beta, _, rank, _ = np.linalg.lstsq(x, y, rcond=None)
    # 如果矩阵秩小于列数，说明至少有变量完全共线，本月回归结果不可靠。
    if rank < x.shape[1]:
        raise np.linalg.LinAlgError("设计矩阵秩不足，可能存在变量共线")

    # 用估计出来的系数计算每只基金在当月横截面中的拟合收益。
    fitted = x @ beta
    # 残差等于真实未来收益减去模型拟合值。
    residual = y - fitted
    # 残差平方和用于衡量模型没有解释掉的收益差异。
    ss_res = float(np.dot(residual, residual))
    # 总平方和用于衡量当月因变量自身的横截面波动。
    ss_total = float(np.dot(y - y.mean(), y - y.mean()))

    # R 方衡量当月横截面里模型解释了多少收益差异。
    # 如果当月 y 没有波动，ss_total 会等于 0，这时 R 方没有经济含义，记为缺失。
    r_squared = 1.0 - ss_res / ss_total if ss_total > 0 else np.nan
    # 记录当月进入回归的基金数量。
    n_obs = len(y)
    # 记录参数个数，包括截距项和所有解释变量。
    n_params = x.shape[1]
    # 调整 R 方会惩罚变量数量；如果样本数不多于参数数，调整 R 方没有稳定含义。
    adj_r_squared = (
        1.0 - (1.0 - r_squared) * (n_obs - 1) / (n_obs - n_params)
        if ss_total > 0 and n_obs > n_params
        else np.nan
    )

    # 先把 beta 整理成带变量名索引的 Series，便于后续按列拼成 DataFrame。
    result = pd.Series(beta, index=coef_names)
    # 把当月普通 R 方附加到同一行结果中。
    result["r_squared"] = r_squared
    # 把当月调整 R 方也附加到同一行结果中。
    result["adj_r_squared"] = adj_r_squared
    result["n_obs"] = n_obs
    # 返回这个月份的一整行回归输出。
    return result


def newey_west_mean_se(values: pd.Series, lag: int) -> float:
    """
    计算“时间序列均值”的 Newey-West 标准误。

    Fama-MacBeth 的最终系数是每月系数的均值。由于未来 6 个月收益存在重叠，
    月度系数序列可能自相关，所以这里对均值的标准误做 Newey-West 调整。
    """
    # 去掉缺失的月度系数，并转成 numpy 数组，后续按时间序列公式计算。
    x = values.dropna().to_numpy(dtype=float)
    # t 是可用月份数量，也是标准误缩放时使用的时间序列长度。
    t = len(x)
    # 少于两个有效月份时无法估计时间序列波动，因此返回缺失值。
    if t <= 1:
        return np.nan

    # 把月度系数序列减去自身均值，得到用于估计方差和自协方差的中心化序列。
    centered = x - x.mean()
    # 实际可用滞后阶数不能超过 t-1，否则没有足够月份配对计算自协方差。
    max_lag = min(lag, t - 1)

    # gamma_0 是方差项，后面叠加 Bartlett 权重下的自协方差项。
    long_run_var = np.dot(centered, centered) / t
    # 从 1 阶自协方差开始，逐阶加入 Newey-West 的长期方差估计。
    for ell in range(1, max_lag + 1):
        # Bartlett 权重会让越远的滞后项权重越小，避免高阶自协方差过度影响结果。
        weight = 1.0 - ell / (max_lag + 1.0)
        # 计算 ell 阶自协方差：当前值与 ell 期以前的值配对相乘后取平均。
        gamma = np.dot(centered[ell:], centered[:-ell]) / t
        # 自协方差在长期方差中正负两个方向都要计入，所以乘以 2。
        long_run_var += 2.0 * weight * gamma

    # long_run_var 是月度系数序列的长期方差；均值的方差还要除以 t。
    return float(np.sqrt(max(long_run_var, 0.0) / t))


def summarize_factor_sample(
    df: pd.DataFrame,
    factor_label: str,
    required_cols: list[str],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """
    为单个 Consistency 指标生成有效样本，并统计每月可用样本数。

    不在全表统一 dropna，是因为 5 个 Consistency 指标的缺失情况不同。
    每个模型只按自己需要的列判断是否有效。
    """
    # 对当前模型需要的所有列逐行检查，只有这些列都非缺失才是有效样本。
    valid_mask = df[required_cols].notna().all(axis=1)
    # 保留日期列和当前模型需要的列，并复制一份，避免后续筛选影响原始 DataFrame。
    valid_df = df.loc[valid_mask, [DATE_COL] + required_cols].copy()
    # 按月份统计有效横截面样本数，用来判断每个月是否达到回归门槛。
    monthly_n = valid_df.groupby(DATE_COL).size().rename("n_valid")

    # 只保留样本数不低于 MIN_CROSS_SECTION_N 的月份进入 Fama-MacBeth 月度回归。
    eligible_months = monthly_n[monthly_n >= MIN_CROSS_SECTION_N].index
    # 根据合格月份筛出真正用于回归的数据。
    regression_df = valid_df[valid_df[DATE_COL].isin(eligible_months)].copy()

    # 汇总当前指标的样本覆盖情况，方便之后检查不同 Consistency 指标是否样本差异很大。
    sample_summary = {
        "factor": factor_label,
        "valid_rows": int(valid_mask.sum()),
        "valid_months": int(monthly_n.shape[0]),
        "eligible_months": int(len(eligible_months)),
        "min_cross_section_n": int(MIN_CROSS_SECTION_N),
        "monthly_n_min": int(monthly_n.min()) if len(monthly_n) else 0,
        "monthly_n_mean": float(monthly_n.mean()) if len(monthly_n) else np.nan,
        "monthly_n_median": float(monthly_n.median()) if len(monthly_n) else np.nan,
        "monthly_n_max": int(monthly_n.max()) if len(monthly_n) else 0,
    }
    # 返回用于回归的明细数据，以及样本统计摘要。
    return regression_df, sample_summary


def run_factor_regression(df: pd.DataFrame, factor_spec: object) -> tuple[pd.DataFrame, dict[str, object], list[dict[str, object]]]:
    """完成单个 Consistency 指标的月度横截面回归和样本统计。"""
    # 把当前配置解析为真实因子列和稳定的输出标签。
    factor_cols = factor_columns_for_spec(factor_spec)
    factor_label = factor_label_for_spec(factor_spec)
    # 截面标准化应只使用当前模型实际可进入回归的候选样本。
    # 这里先用“原始变量”判断非缺失，随后再生成交互项并做最终 dropna。
    main_effect_cols = get_interaction_main_effect_columns(factor_cols)
    # 这里只使用当前 factor 对应的交互来源列；不能要求其他期限变量也同时非缺失。
    raw_required_cols = (
        [Y_COL]
        + factor_cols
        + main_effect_cols
        + CONTROL_COLS
        + get_interaction_source_columns_for_factor(factor_cols)
    )
    # 同一变量可能出现在 factor、主效应和交互项中，去重后再构造候选样本掩码。
    raw_required_cols = list(dict.fromkeys(raw_required_cols))
    # 只有当前模型全部原始变量均非缺失的行，才参与当月交互变量的截面标准化。
    standardization_mask = df[raw_required_cols].notna().all(axis=1)
    # 交互项要在当前 factor 的筛选样本内生成；如果选择截面标准化，标准化口径也跟着当前样本走。
    df = add_interaction_columns(df, factor_cols, factor_label, standardization_mask)
    # 中心化模型用去均值后的 FAC 和 rank_mean 作为主效应；控制变量不变。
    regression_main_effect_cols = get_regression_main_effect_columns(
        factor_cols, main_effect_cols
    )
    # 遵循交互项层级原则：当前模型依次放入 Consistency、交互变量主效应、
    # 控制变量和交互项。主效应按当前 factor 动态解析，因此每套期限只加入对应的 rank_mean。
    x_cols = (
        regression_main_effect_cols
        + CONTROL_COLS
        + get_interaction_columns()
    )
    # 有效样本需要同时具备因变量、当前 Consistency 指标和所有控制变量。
    required_cols = [Y_COL] + x_cols
    # 当前 df 已经按基础筛选和该 factor 的额外筛选过滤，这里记录过滤后的行数，便于复查口径。
    filtered_rows = int(len(df))
    # 先为当前指标筛样本，并拿到样本数量摘要。
    regression_df, sample_summary = summarize_factor_sample(df, factor_label, required_cols)
    # 把当前 factor 实际使用的筛选条件写入样本摘要，CSV 里用 JSON 字符串保存。
    sample_summary["sample_filters"] = json.dumps(
        get_filters_for_factor(factor_spec), ensure_ascii=False, sort_keys=True
    )
    sample_summary["filtered_rows_before_dropna"] = filtered_rows

    # monthly_rows 用来收集每个月成功回归后的系数行。
    monthly_rows: list[pd.Series] = []
    # skipped_months 用来记录满足样本数门槛但因为共线等问题无法回归的月份。
    skipped_months: list[dict[str, object]] = []

    # 按月份循环；每个月独立做一次横截面 OLS，这正是 Fama-MacBeth 的第一步。
    for month, month_df in regression_df.groupby(DATE_COL, sort=True):
        try:
            # 对当前月份的基金横截面估计一次 OLS，得到当月各变量的系数。
            coef = ols_cross_section(month_df, x_cols)
        except Exception as exc:
            # 如果本月回归失败，记录失败的指标、月份、样本数和原因，之后继续处理其他月份。
            skipped_months.append(
                {
                    "factor": factor_label,
                    "month_date": str(pd.Timestamp(month).date()),
                    "n_obs": int(len(month_df)),
                    "reason": str(exc),
                }
            )
            continue

        # 给当月系数行加上月份，方便后续按时间序列汇总。
        coef[DATE_COL] = month
        # 给当月系数行加上因子名，方便多个 Consistency 指标结果合并。
        coef["factor"] = factor_label
        # 记录当月实际回归样本数，后续可计算平均月度样本量。
        coef["n_obs"] = int(len(month_df))
        # 把本月结果放入列表，循环结束后统一拼成 DataFrame。
        monthly_rows.append(coef)

    # 如果至少有一个月份成功回归，就把所有月份的 Series 合并成系数表。
    if monthly_rows:
        monthly_coef = pd.DataFrame(monthly_rows)
        # 固定列顺序，让输出文件更稳定，也方便人工阅读和后续脚本读取。
        ordered_cols = ["factor", DATE_COL, "n_obs", "r_squared", "adj_r_squared", "const"] + x_cols
        monthly_coef = monthly_coef[ordered_cols]
    else:
        # 如果没有任何月份成功回归，仍返回带正确列名的空表，避免后续 concat 报错。
        monthly_coef = pd.DataFrame(
            columns=["factor", DATE_COL, "n_obs", "r_squared", "adj_r_squared", "const"] + x_cols
        )

    # 记录成功进入最终 Fama-MacBeth 汇总的月份数。
    sample_summary["regression_months"] = int(len(monthly_coef))
    # 记录所有成功回归月份的横截面样本总数。
    sample_summary["regression_rows"] = int(monthly_coef["n_obs"].sum()) if len(monthly_coef) else 0
    # 记录达到样本门槛但实际回归失败的月份数量。
    sample_summary["skipped_months_after_eligibility"] = int(len(skipped_months))
    # 计算月度 R 方的时间序列平均值，用来概括模型解释力。
    sample_summary["avg_r_squared"] = (
        float(monthly_coef["r_squared"].mean()) if len(monthly_coef) else np.nan
    )
    # 计算月度调整 R 方的时间序列平均值。
    sample_summary["avg_adj_r_squared"] = (
        float(monthly_coef["adj_r_squared"].mean()) if len(monthly_coef) else np.nan
    )

    # 返回月度系数、样本摘要和被跳过月份清单。
    return monthly_coef, sample_summary, skipped_months


def build_result_table(monthly_coef: pd.DataFrame, factor_col: str) -> pd.DataFrame:
    """把单个指标的月度系数序列汇总成 Fama-MacBeth 结果表。"""
    # 找出真正的系数列；这些列会被逐一做时间序列均值和显著性检验。
    coef_cols = [
        col
        for col in monthly_coef.columns
        if col not in {"factor", DATE_COL, "n_obs", "r_squared", "adj_r_squared"}
    ]
    # rows 用来逐行收集每个变量的最终 Fama-MacBeth 汇总结果。
    rows = []

    # 对截距、Consistency 指标和每个控制变量分别汇总月度系数序列。
    for variable in coef_cols:
        # 提取当前变量在各个月份的系数，并去掉缺失值。
        series = monthly_coef[variable].dropna()
        # n_months 是当前变量实际参与均值和检验的月份数量。
        n_months = int(len(series))
        # Fama-MacBeth 系数就是月度横截面系数的时间序列均值。
        coef = float(series.mean()) if n_months else np.nan
        # 标准误使用 Newey-West，对月度系数序列可能存在的自相关做调整。
        se = newey_west_mean_se(series, NEWEY_WEST_LAG) if n_months else np.nan
        # t 值等于均值系数除以 Newey-West 标准误；标准误无效时记为缺失。
        t_stat = coef / se if se and not np.isnan(se) and se > 0 else np.nan
        # 用 t 分布计算双侧 p 值；自由度按可用月份数减一处理。
        p_value = (
            float(2.0 * stats.t.sf(abs(t_stat), df=max(n_months - 1, 1)))
            if not np.isnan(t_stat)
            else np.nan
        )

        # 把当前变量的最终结果和辅助统计量整理成一行。
        rows.append(
            {
                "factor": factor_col,
                "variable": variable,
                "coef": coef,
                "newey_west_se": se,
                "t_stat": t_stat,
                "p_value": p_value,
                "n_months": n_months,
                "avg_monthly_n": float(monthly_coef["n_obs"].mean()) if len(monthly_coef) else np.nan,
                "total_regression_obs": int(monthly_coef["n_obs"].sum()) if len(monthly_coef) else 0,
                "avg_r_squared": float(monthly_coef["r_squared"].mean()) if len(monthly_coef) else np.nan,
                "avg_adj_r_squared": (
                    float(monthly_coef["adj_r_squared"].mean()) if len(monthly_coef) else np.nan
                ),
                "newey_west_lag": int(NEWEY_WEST_LAG),
                "min_cross_section_n": int(MIN_CROSS_SECTION_N),
            }
        )

    # 返回当前 Consistency 指标对应的 Fama-MacBeth 结果表。
    return pd.DataFrame(rows)


def significance_stars(p_value: float) -> str:
    """把 p 值转换成论文表格里常见的显著性星号。"""
    # p 值缺失时不显示星号。
    if pd.isna(p_value):
        return ""
    # 1% 显著性水平对应三颗星。
    if p_value < 0.01:
        return "***"
    # 5% 显著性水平对应两颗星。
    if p_value < 0.05:
        return "**"
    # 10% 显著性水平对应一颗星。
    if p_value < 0.1:
        return "*"
    # 不显著时返回空字符串。
    return ""


def build_cross_section_correlation_table(
    df: pd.DataFrame,
    factor_spec: object,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """构建单个 Consistency 指标对应的截面相关系数表。

    这里沿用 Fama-MacBeth 的横截面口径：每个月先单独计算变量相关系数，
    再对每一对变量的月度相关系数取时间序列均值。这样不会把不同月份之间
    的整体水平变化混进当月基金横截面的变量关系里。
    """
    # 先解析当前模型的因子列、输出标签和需要额外加入的交互主效应。
    factor_cols = factor_columns_for_spec(factor_spec)
    factor_label = factor_label_for_spec(factor_spec)
    # 相关性表不使用因变量，因此这里用解释变量及交互项来源变量定义标准化口径。
    main_effect_cols = get_interaction_main_effect_columns(factor_cols)
    # 与回归主流程一致，只使用当前 factor 真正依赖的交互来源列。
    raw_required_cols = (
        factor_cols
        + main_effect_cols
        + CONTROL_COLS
        + get_interaction_source_columns_for_factor(factor_cols)
    )
    # 去重后逐行检查原始解释变量是否完整，得到截面标准化候选样本。
    raw_required_cols = list(dict.fromkeys(raw_required_cols))
    standardization_mask = df[raw_required_cols].notna().all(axis=1)
    # 相关性表和回归使用同一组解释变量，便于检查交互项是否和主效应或控制变量高度相关。
    df = add_interaction_columns(df, factor_cols, factor_label, standardization_mask)
    # 相关性表至少在本回归脚本内部与设计矩阵保持同一变量口径。
    regression_main_effect_cols = get_regression_main_effect_columns(
        factor_cols, main_effect_cols
    )
    variable_order = (
        regression_main_effect_cols
        + CONTROL_COLS
        + get_interaction_columns()
    )
    # 相关系数只能使用解释变量完整的行，因此先按最终变量清单统一 dropna。
    valid_df = df[[DATE_COL] + variable_order].dropna().copy()
    # 统计每月完整样本数，并沿用回归相同的最低横截面样本门槛。
    monthly_n = valid_df.groupby(DATE_COL).size()
    eligible_months = monthly_n[monthly_n >= MIN_CROSS_SECTION_N].index
    # 只保留样本量达标月份，确保相关性诊断与回归月份口径一致。
    valid_df = valid_df[valid_df[DATE_COL].isin(eligible_months)].copy()

    # 没有任何合格月份时，也返回结构完整的空表，保证 main 中可以直接合并和写出。
    if valid_df.empty:
        # 数值矩阵保留变量行列结构，单元格全部为空。
        numeric_table = pd.DataFrame(index=variable_order, columns=variable_order)
        numeric_table = numeric_table.reset_index(names="variable")
        numeric_table.insert(0, "factor", factor_label)
        # 展示矩阵沿用相同结构，后续即使为空也能写出稳定表头。
        display_table = numeric_table.copy()
        # 长格式摘要为空时仍明确声明字段，方便下游读取。
        empty_summary = pd.DataFrame(
            columns=[
                "factor",
                "row_variable",
                "col_variable",
                "mean_corr",
                "p_value",
                "stars",
                "n_months",
            ]
        )
        # 单 factor 和 dummy 组的重点相关性表字段不同，因此分别构造空表结构。
        if len(factor_cols) == 1 and factor_label == factor_cols[0]:
            empty_control = pd.DataFrame(
                columns=["factor", "control_variable", "mean_corr", "p_value", "stars", "n_months"]
            )
        else:
            empty_control = pd.DataFrame(
                columns=[
                    "factor",
                    "row_variable",
                    "control_variable",
                    "mean_corr",
                    "p_value",
                    "stars",
                    "n_months",
                ]
            )
        # 一次返回四类空结果，调用方无需为“无合格月份”另写分支。
        return numeric_table, display_table, empty_summary, empty_control

    # 收集每个月的完整相关系数矩阵，稍后转成长格式做时间序列汇总。
    monthly_corrs: list[pd.DataFrame] = []
    for month, month_df in valid_df.groupby(DATE_COL, sort=True):
        # 某个变量当月没有横截面波动时，corr 会自然得到 NaN；后续汇总会跳过。
        corr = month_df[variable_order].corr()
        # 给矩阵附上月份，并把行索引转成普通列，方便跨月份纵向拼接。
        corr[DATE_COL] = month
        monthly_corrs.append(corr.reset_index(names="row_variable"))

    # 把所有月份的宽矩阵纵向合并，再 melt 成“月份—行变量—列变量—相关系数”结构。
    monthly_corr_df = pd.concat(monthly_corrs, ignore_index=True)
    long_corr = monthly_corr_df.melt(
        id_vars=[DATE_COL, "row_variable"],
        value_vars=variable_order,
        var_name="col_variable",
        value_name="corr",
    )

    # 对每一对变量分别汇总月度相关系数的均值和显著性。
    summary_rows = []
    for row_var in variable_order:
        for col_var in variable_order:
            # 只取当前变量对的有效月份；当月相关系数为 NaN 时自动排除。
            corr_series = long_corr.loc[
                (long_corr["row_variable"] == row_var)
                & (long_corr["col_variable"] == col_var),
                "corr",
            ].dropna()
            # 记录有效月份数并计算月度截面相关系数的时间序列均值。
            n_months = int(len(corr_series))
            mean_corr = float(corr_series.mean()) if n_months else np.nan

            # 对角线固定代表变量自身相关，不做显著性检验。
            if row_var == col_var or n_months <= 1:
                p_value = np.nan
            else:
                # 非对角线且至少有两个有效月份时，对月度相关系数均值做单样本 t 检验。
                _, p_value = stats.ttest_1samp(corr_series, popmean=0.0)
                p_value = float(p_value)

            # 保存当前变量对的完整统计结果；星号只用于展示，不替代原始 p 值。
            summary_rows.append(
                {
                    "factor": factor_label,
                    "row_variable": row_var,
                    "col_variable": col_var,
                    "mean_corr": mean_corr,
                    "p_value": p_value,
                    "stars": significance_stars(p_value),
                    "n_months": n_months,
                }
            )

    # 把逐对变量的字典列表转换成长格式汇总表。
    corr_summary = pd.DataFrame(summary_rows)

    # 初始化纯数值矩阵和展示矩阵；二者使用相同的变量顺序。
    numeric_table = pd.DataFrame(index=variable_order, columns=variable_order, dtype=float)
    display_table = pd.DataFrame(index=variable_order, columns=variable_order, dtype=object)
    for i, row_var in enumerate(variable_order):
        for j, col_var in enumerate(variable_order):
            # 从长格式摘要中定位当前矩阵单元格对应的统计结果。
            row = corr_summary.loc[
                (corr_summary["row_variable"] == row_var)
                & (corr_summary["col_variable"] == col_var)
            ].iloc[0]
            # 数值矩阵的上下三角都保存平均相关系数，便于机器读取。
            numeric_table.loc[row_var, col_var] = row["mean_corr"]

            # 展示矩阵：对角线固定为 1，上三角显示系数，下三角显示显著性星号。
            if i == j:
                display_table.loc[row_var, col_var] = "1.000"
            elif i < j:
                display_table.loc[row_var, col_var] = (
                    f"{row['mean_corr']:.3f}" if pd.notna(row["mean_corr"]) else ""
                )
            else:
                display_table.loc[row_var, col_var] = row["stars"]

    # 合并多个因子的相关矩阵时，需要 factor 列标记每张矩阵来自哪个指标。
    numeric_table = numeric_table.reset_index(names="variable")
    numeric_table.insert(0, "factor", factor_label)
    display_table = display_table.reset_index(names="variable")
    display_table.insert(0, "factor", factor_label)

    # 从完整摘要中提取“当前 factor 与控制变量”的重点组合。启用中心化后，
    # 相关矩阵中的 factor 行名是带 __dmcs 后缀的新列名，不能再用原始列名筛选。
    regression_factor_cols = regression_main_effect_cols[: len(factor_cols)]
    control_corr = corr_summary[
        (corr_summary["row_variable"].isin(regression_factor_cols))
        & (corr_summary["col_variable"].isin(CONTROL_COLS))
    ].copy()
    # 普通单 factor 模型只需保留 control_variable；dummy 组还需保留具体行变量。
    if len(factor_cols) == 1 and factor_label == factor_cols[0]:
        control_corr = control_corr[
            ["factor", "col_variable", "mean_corr", "p_value", "stars", "n_months"]
        ].rename(columns={"col_variable": "control_variable"})
    else:
        control_corr = control_corr[
            ["factor", "row_variable", "col_variable", "mean_corr", "p_value", "stars", "n_months"]
        ].rename(columns={"col_variable": "control_variable"})

    # 返回数值矩阵、展示矩阵、长格式摘要和 factor—控制变量重点摘要。
    return numeric_table, display_table, corr_summary, control_corr

def main() -> None:
    """脚本入口：读取输入、逐个指标回归、写出结果文件。"""
    args = parse_args()
    # 确保输出目录存在；parents=True 会连同中间目录一起创建。
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 从上游生成的 parquet 文件读取基金-月份面板数据。
    df = pd.read_parquet(INPUT_PATH)
    # 先检查必要列是否完整，避免运行到中后段才发现输入表不匹配。
    check_required_columns(df)

    # 收集所有 Consistency 指标的月度回归系数。
    all_monthly_coef = []
    # 收集所有 Consistency 指标的最终 Fama-MacBeth 结果。
    all_results = []
    # 收集每个 Consistency 指标的样本摘要。
    sample_summaries = []
    # 收集所有因为回归失败而跳过的月份记录。
    skipped_months = []
    # 收集每个 Consistency 指标的纯数值相关性矩阵。
    correlation_tables = []
    # 收集每个 Consistency 指标的带星号展示型相关性矩阵。
    correlation_display_tables = []
    # 收集每个 Consistency 指标的长格式相关性汇总。
    correlation_summaries = []
    # 收集 Consistency 与控制变量之间的重点相关性结果。
    consistency_control_corrs = []

    if not CONSISTENCY_COLS:
        # Null model：没有一致性因子，只跑控制变量回归。
        # 先按基础筛选条件过滤样本，所有对齐口径共享同一份基础数据。
        null_df = apply_sample_filters(df, SAMPLE_FILTERS)
        # 回归的解释变量只有控制变量，不包含任何 factor。
        x_cols = CONTROL_COLS[:]
        # controls-only 回归本身需要的列：因变量 + 控制变量。
        controls_required = [Y_COL] + x_cols

        # 如果 registry 配置了 sample_alignment_columns，就按每个对齐列
        # 分别跑一次 controls-only 回归，使样本与对应 factor 的回归完全一致。
        # 如果没有配置，退化为原来的单次全样本 controls-only 回归。
        if SAMPLE_ALIGNMENT_COLUMNS:
            alignment_specs = SAMPLE_ALIGNMENT_COLUMNS
        else:
            alignment_specs = [None]

        # 逐个对齐列循环；每轮产出一组 controls-only 的 Fama-MacBeth 结果。
        for alignment_col in alignment_specs:
            if alignment_col is not None:
                # 有对齐列时，factor_label 带上对齐列名，便于在输出中区分口径。
                factor_label = f"controls_only_aligned_{alignment_col}"
                # 把对齐列加入 dropna 的列清单，但不加入 x_cols，
                # 这样 summarize_factor_sample 会因为对齐列的缺失而丢行，
                # 从而让样本与 fm_baseline 中该 factor 的样本完全一致。
                required_cols = controls_required + [alignment_col]
            else:
                # 没有对齐列时，使用原始的全样本 controls-only 标签。
                factor_label = "controls_only"
                # 不额外加任何列，保持原有行为。
                required_cols = controls_required

            # 按 required_cols 做 dropna 并筛出横截面样本数达标的月份。
            aligned_df, sample_summary = summarize_factor_sample(
                null_df, factor_label, required_cols
            )
            # 把当前使用的筛选条件写入样本摘要，方便事后审计。
            sample_summary["sample_filters"] = json.dumps(
                SAMPLE_FILTERS, ensure_ascii=False, sort_keys=True
            )
            # 记录 dropna 之前的总行数，方便比对样本损耗。
            sample_summary["filtered_rows_before_dropna"] = int(len(null_df))

            # 收集每个月成功回归的系数行。
            monthly_rows: list[pd.Series] = []
            # 收集因回归失败而跳过的月份记录。
            null_skipped: list[dict[str, object]] = []

            # 按月份循环，每个月独立做一次横截面 OLS。
            for month, month_df in aligned_df.groupby(DATE_COL, sort=True):
                try:
                    # 对当月横截面做 OLS，只用控制变量作为解释变量。
                    coef = ols_cross_section(month_df, x_cols)
                except Exception as exc:
                    # 回归失败时记录失败信息，继续处理下一个月份。
                    null_skipped.append({
                        "factor": factor_label,
                        "month_date": str(pd.Timestamp(month).date()),
                        "n_obs": int(len(month_df)),
                        "reason": str(exc),
                    })
                    continue
                # 给当月系数行附上月份和因子标签。
                coef[DATE_COL] = month
                coef["factor"] = factor_label
                # 记录当月实际参与回归的基金数量。
                coef["n_obs"] = int(len(month_df))
                monthly_rows.append(coef)

            # 把所有月份的系数行合并成 DataFrame。
            if monthly_rows:
                monthly_coef = pd.DataFrame(monthly_rows)
                # 固定列顺序，让输出文件稳定且易读。
                ordered_cols = [
                    "factor", DATE_COL, "n_obs", "r_squared",
                    "adj_r_squared", "const",
                ] + x_cols
                monthly_coef = monthly_coef[ordered_cols]
            else:
                # 没有任何月份成功回归时，返回带正确列名的空表。
                monthly_coef = pd.DataFrame(
                    columns=[
                        "factor", DATE_COL, "n_obs", "r_squared",
                        "adj_r_squared", "const",
                    ] + x_cols
                )

            # 记录成功回归的月份数量。
            sample_summary["regression_months"] = int(len(monthly_coef))
            # 记录所有成功回归月份的横截面样本总数。
            sample_summary["regression_rows"] = (
                int(monthly_coef["n_obs"].sum()) if len(monthly_coef) else 0
            )
            # 记录达到样本门槛但回归失败的月份数量。
            sample_summary["skipped_months_after_eligibility"] = int(
                len(null_skipped)
            )
            # 计算月度 R 方的时间序列平均值。
            sample_summary["avg_r_squared"] = (
                float(monthly_coef["r_squared"].mean())
                if len(monthly_coef)
                else np.nan
            )
            # 计算月度调整 R 方的时间序列平均值。
            sample_summary["avg_adj_r_squared"] = (
                float(monthly_coef["adj_r_squared"].mean())
                if len(monthly_coef)
                else np.nan
            )

            # 把当前对齐口径的结果加入总列表。
            all_monthly_coef.append(monthly_coef)
            all_results.append(build_result_table(monthly_coef, factor_label))
            sample_summaries.append(sample_summary)
            skipped_months.extend(null_skipped)
    else:
        # 对每一个 Consistency 指标或 dummy 变量组分别跑一套回归和相关性分析。
        for factor_spec in CONSISTENCY_COLS:
            factor_label = factor_label_for_spec(factor_spec)
            # 每个 factor 先应用共同基础筛选，再叠加自己的 top-half 筛选。
            # 即使 preprocess 已经做过基础筛选，这里再应用一次也能防止误读未清洗表。
            factor_filters = get_filters_for_factor(factor_spec)
            factor_df = apply_sample_filters(df, factor_filters)
            # 跑当前指标的逐月横截面回归，并生成样本统计。
            monthly_coef, sample_summary, skipped = run_factor_regression(factor_df, factor_spec)
            # 把月度系数序列汇总成最终 Fama-MacBeth 均值、标准误、t 值和 p 值。
            result_table = build_result_table(monthly_coef, factor_label)
            # 构建当前指标与控制变量之间的逐月横截面相关性汇总表。
            corr_table, corr_display_table, corr_summary, control_corr = build_cross_section_correlation_table(
                factor_df, factor_spec
            )

            # 把当前指标的月度系数表加入总列表。
            all_monthly_coef.append(monthly_coef)
            # 把当前指标的最终回归结果加入总列表。
            all_results.append(result_table)
            # 把当前指标的样本摘要加入总列表。
            sample_summaries.append(sample_summary)
            # 把当前指标被跳过的月份追加到统一清单。
            skipped_months.extend(skipped)
            # 把当前指标的纯数值相关性矩阵加入总列表。
            correlation_tables.append(corr_table)
            # 把当前指标的带星号展示型相关性矩阵加入总列表。
            correlation_display_tables.append(corr_display_table)
            # 把当前指标的完整相关性汇总加入总列表。
            correlation_summaries.append(corr_summary)
            # 把当前指标和控制变量的相关性摘要加入总列表。
            consistency_control_corrs.append(control_corr)

    # 合并所有指标的月度系数，形成一个统一输出文件。
    monthly_coef_df = pd.concat(all_monthly_coef, ignore_index=True)
    # 合并所有指标的 Fama-MacBeth 汇总结果。
    results_df = pd.concat(all_results, ignore_index=True)
    # 把样本摘要字典列表转换成 DataFrame。
    sample_summary_df = pd.DataFrame(sample_summaries)
    # 把跳过月份记录转换成 DataFrame；如果没有跳过月份，则得到空表。
    skipped_months_df = pd.DataFrame(skipped_months)
    # 合并所有指标的相关性表；null model 没有因子相关性，输出空表。
    correlation_table_df = pd.concat(correlation_tables, ignore_index=True) if correlation_tables else pd.DataFrame()
    correlation_display_table_df = pd.concat(correlation_display_tables, ignore_index=True) if correlation_display_tables else pd.DataFrame()
    correlation_summary_df = pd.concat(correlation_summaries, ignore_index=True) if correlation_summaries else pd.DataFrame()
    consistency_control_corr_df = pd.concat(consistency_control_corrs, ignore_index=True) if consistency_control_corrs else pd.DataFrame()

    # 输出最终 Fama-MacBeth 汇总结果。
    results_df.to_csv(OUTPUT_DIR / "fama_macbeth_results.csv", index=False, encoding="utf-8-sig")
    # 输出逐月横截面回归系数，方便之后复查时间序列。
    monthly_coef_df.to_csv(
        OUTPUT_DIR / "fama_macbeth_monthly_coefficients.csv",
        index=False,
        encoding="utf-8-sig",
    )
    # 输出每个指标的样本量摘要。
    sample_summary_df.to_csv(
        OUTPUT_DIR / "fama_macbeth_sample_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    # 输出回归失败或被跳过月份的明细。
    skipped_months_df.to_csv(
        OUTPUT_DIR / "fama_macbeth_skipped_months.csv",
        index=False,
        encoding="utf-8-sig",
    )
    # 输出纯数值相关性矩阵；上下三角都是平均相关系数，量纲统一。
    correlation_table_df.to_csv(
        OUTPUT_DIR / "correlation_table.csv",
        index=False,
        encoding="utf-8-sig",
    )
    # 输出上三角为平均相关系数、下三角为显著性星号的展示型相关性矩阵。
    correlation_display_table_df.to_csv(
        OUTPUT_DIR / "correlation_table_with_stars.csv",
        index=False,
        encoding="utf-8-sig",
    )
    # 输出完整长格式相关性结果，包含每对变量的均值、p 值、星号和有效月份数。
    correlation_summary_df.to_csv(
        OUTPUT_DIR / "correlation_summary_long.csv",
        index=False,
        encoding="utf-8-sig",
    )
    # 输出 Consistency 与各控制变量的相关性摘要，便于论文或报告中单独引用。
    consistency_control_corr_df.to_csv(
        OUTPUT_DIR / "consistency_control_correlations.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # 记录本次运行的关键参数和输入输出位置，方便未来复现。
    metadata = {
        "run_time": datetime.now().isoformat(timespec="seconds"),
        "model_key": args.model,
        "input_path": str(INPUT_PATH),
        "output_dir": str(OUTPUT_DIR),
        "date_col": DATE_COL,
        "y_col": Y_COL,
        "consistency_cols": [str(factor_spec) for factor_spec in CONSISTENCY_COLS],
        "consistency_input_cols": all_factor_columns(CONSISTENCY_COLS),
        "control_cols": CONTROL_COLS,
        "interaction_main_effects": RAW_INTERACTION_MAIN_EFFECTS,
        "interaction_centering": INTERACTION_CENTERING,
        "interactions": INTERACTIONS,
        "sample_filters": SAMPLE_FILTERS,
        "factor_sample_filters": {
            str(factor): dict(filters)
            for factor, filters in FACTOR_SAMPLE_FILTERS.items()
        },
        "filters_by_factor": {
            factor_label_for_spec(factor_spec): get_filters_for_factor(factor_spec)
            for factor_spec in CONSISTENCY_COLS
        },
        "newey_west_lag": NEWEY_WEST_LAG,
        "min_cross_section_n": MIN_CROSS_SECTION_N,
        "input_rows": int(len(df)),
        "input_months": int(df[DATE_COL].nunique()),
        "note": "输入表已由上游程序完成基础样本筛选、1-rank_vol 构造和月度横截面 1%/99% winsorize；本脚本按 factor 叠加 factor_sample_filters。",
    }
    # 将运行元数据写成 json；ensure_ascii=False 保留中文可读性。
    with open(OUTPUT_DIR / "run_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # 在终端提示主结果输出位置。
    print(f"Fama-MacBeth 回归完成，结果已输出到：{OUTPUT_DIR}")
    # 在终端打印样本摘要，快速检查每个指标的样本覆盖情况。
    print(sample_summary_df.to_string(index=False))
    # 在终端打印重点相关性结果，快速查看 Consistency 与控制变量的关系。
    print("\nConsistency 与控制变量的截面相关系数均值：")
    print(consistency_control_corr_df.to_string(index=False))


if __name__ == "__main__":
    main()
