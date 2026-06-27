"""为 panel_base.parquet 追加控制变量列。

默认读取并覆盖：

    A_data/output/panel_base.parquet

新增列会放在原有字段的最右侧：

- CtrlRetLTM：基金过去 2~12 个月累计收益率（剔除最近 1 个月），由 past_ret_12m_1 和 CtrlRetSTR 推算；
- CtrlRetSTR：基金过去 1 个月收益率，要求上一条记录是同一基金的上一个月；
- CtrlVol：当前月份之前 12 个月 CtrlRetSTR 的样本标准差，要求收益率窗口完整且连续；
- fund_size：iFind 宽表中的原始基金规模；
- Ctrl_log_fund_size：fund_size 的自然对数；
- as_<investment_type>：按 investment_type 生成 one-hot 变量，最后一个类型作为基准组不建列。

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_controls_variable.py
    .venv/bin/python A_data/scripts/3_panel_base_controls_variable.py --output A_data/output/panel_base_with_controls.parquet
    .venv/bin/python A_data/scripts/3_panel_base_controls_variable.py --no-preview
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

import Config


DEFAULT_INPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_OUTPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_FUND_SIZE_DIR = Config.A_DATA_ROOT / "data" / "iFind_API"
DEFAULT_FUND_INFO_PATH = (
    Config.A_DATA_ROOT
    / "data"
    / "iFind_terminal_fund_center"
    / "iFind基金基本信息汇总.xlsx"
)
DEFAULT_FACTOR_INPUT_DIR = Config.PROJECT_ROOT / "B_factors" / "input"

# 计算控制变量所需的上游字段，read_panel 时会检查这些列是否存在。
REQUIRED_COLUMNS = (
    Config.COLUMN_IFIND_CODE,
    Config.COLUMN_INVESTMENT_TYPE,
    Config.COLUMN_MONTH_DATE,
    Config.COLUMN_NAV,
    "past_ret_12m_1",
)
# 从 panel 自身 nav/收益率数据计算的三个控制变量名。
# 用于清理旧列（drop_existing_control_columns）和校验新增列顺序（validate_controls）。
CONTROL_COLUMNS = ("CtrlRetLTM", "CtrlRetSTR", "CtrlVol")
# 需要外部 iFind 宽表的基金规模变量，与 CONTROL_COLUMNS 分开管理。
FUND_SIZE_COLUMNS = ("fund_size", "Ctrl_log_fund_size")
# 需要外部基金基本信息表的基金年龄控制变量。
FUND_AGE_COLUMNS = ("基金成立日", "Ctrl_fund_age")


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    # 用 argparse 是为了让脚本既能默认覆盖正式文件，也能在调试时输出到临时文件。
    parser = argparse.ArgumentParser(description="为 panel_base 追加控制变量。")
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
        help="输出 parquet 文件路径；默认覆盖输入文件。",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Excel 预览输出路径；默认跟随 output 生成 *_preview.xlsx。",
    )
    parser.add_argument(
        "--fund-size-dir",
        type=Path,
        default=DEFAULT_FUND_SIZE_DIR,
        help="iFind 基金净值变化宽表所在目录，用于补充 fund_size 和 Ctrl_log_fund_size。",
    )
    parser.add_argument(
        "--fund-info",
        type=Path,
        default=DEFAULT_FUND_INFO_PATH,
        help="iFind 基金基本信息汇总 Excel 路径，用于补充基金成立日和 Ctrl_fund_age。",
    )
    parser.add_argument(
        "--factor-input-dir",
        type=Path,
        default=DEFAULT_FACTOR_INPUT_DIR,
        help="把最终 parquet 和 preview Excel 复制到这个目录，默认 B_factors/input。",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="只更新 parquet，不更新 Excel 预览。",
    )
    return parser.parse_args()


def normalize_code(value: object) -> str | None:
    """把 Excel 中不同格式的基金代码统一成可匹配的字符串。"""
    # iFind 文件里基金代码通常是 000001.OF，但 Excel 有时会把纯数字代码读成数值。
    # 这里复用 2_fund_managers.py 的口径，保证两个脚本对基金代码的理解一致。

    # 1. 空值直接返回 None
    if pd.isna(value):
        return None

    # 2. 整数类型：补零到 6 位（如 1 → "000001"）
    if isinstance(value, (int, np.integer)):
        return f"{int(value):06d}"

    # 3. 浮点类型：NaN 返回 None，整数值的浮点数补零到 6 位
    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return None
        if float(value).is_integer():
            return f"{int(value):06d}"

    # 4. 字符串类型：统一大写、去空格，过滤无效值
    code = str(value).strip().upper().replace(" ", "")
    if not code or code in {"NAN", "NONE", "NAT"} or "数据来源" in code:
        return None
    # 处理 Excel 把 "000001" 读成 "1.0" 的情况
    if code.endswith(".0") and code[:-2].isdigit():
        return code[:-2].zfill(6)
    # 纯数字字符串补零到 6 位
    if code.isdigit():
        return code.zfill(6)
    # 已经带后缀的代码（如 "000001.OF"）直接返回
    return code


def parse_excel_date(value: object) -> pd.Timestamp:
    """把 Excel 日期列名统一转换成 pandas Timestamp。"""
    # iFind 宽表的列名可能已经是 datetime，也可能是 YYYYMMDD、普通日期字符串或 Excel 序号。
    # 统一转换后，后面才能稳定地按 ifind_code + month_date 合并。

    # 1. 空值返回 NaT
    if value is None or pd.isna(value):
        return pd.NaT

    # 2. 已经是 pandas/numpy 时间类型，直接标准化（去掉时分秒）
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).normalize()

    # 3. datetime.date 等具有 year/month/day 属性的对象
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return pd.Timestamp(value).normalize()

    # 4. 数值类型：区分 YYYYMMDD 整数和 Excel 日期序号
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if np.isnan(number):
            return pd.NaT

        integer_text = str(int(number))
        # 8 位整数视为 YYYYMMDD 格式
        if number.is_integer() and len(integer_text) == 8:
            parsed = pd.to_datetime(integer_text, format="%Y%m%d", errors="coerce")
        else:
            # 其他数值视为 Excel 日期序号（以 1899-12-30 为基准）
            parsed = pd.to_datetime(
                number, unit="D", origin="1899-12-30", errors="coerce"
            )
        return pd.Timestamp(parsed).normalize() if not pd.isna(parsed) else pd.NaT

    # 5. 字符串类型：尝试按 YYYYMMDD 或通用格式解析
    text = str(value).strip()
    if text.isdigit() and len(text) == 8:
        parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.to_datetime(text, errors="coerce")
    return pd.Timestamp(parsed).normalize() if not pd.isna(parsed) else pd.NaT


def require_columns(data: pd.DataFrame, source_path: Path) -> None:
    """检查输入文件是否包含控制变量计算需要的字段。"""
    # 后面的收益率和 dummy 变量都依赖这些字段；先检查可以让错误信息更直观。
    missing = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source_path} 缺少字段：{missing}；实际字段为：{list(data.columns)}"
        )


def read_panel(input_path: Path) -> pd.DataFrame:
    """读取 panel_base，并把日期和净值字段转成便于计算的类型。"""
    # 路径不存在时直接报错，避免 pandas 抛出较难定位的底层文件错误。
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")

    # parquet 会保留大部分类型信息，但这里仍统一转换，防止上游文件被 Excel/CSV 中转后类型变乱。
    data = pd.read_parquet(input_path)
    require_columns(data, input_path)

    # copy 一份再改类型，避免后续 pandas 对视图赋值时出现不清楚的警告。
    data = data.copy()
    data[Config.COLUMN_MONTH_DATE] = pd.to_datetime(
        data[Config.COLUMN_MONTH_DATE], errors="coerce"
    )
    data[Config.COLUMN_NAV] = pd.to_numeric(data[Config.COLUMN_NAV], errors="coerce")
    data["past_ret_12m_1"] = pd.to_numeric(data["past_ret_12m_1"], errors="coerce")

    # 日期无法识别会让"前一个月""过去 12 个月"的判断失效，所以不能静默保留。
    if data[Config.COLUMN_MONTH_DATE].isna().any():
        raise ValueError(f"{input_path} 中存在无法识别的 month_date。")
    # nav 是收益率计算分母和波动率来源，缺失或非正数通常说明上游清洗有问题。
    if data[Config.COLUMN_NAV].isna().any() or (data[Config.COLUMN_NAV] <= 0).any():
        raise ValueError(f"{input_path} 中存在缺失或非正数 nav。")

    return data


def drop_existing_control_columns(data: pd.DataFrame) -> pd.DataFrame:
    """删除旧控制变量列，让脚本重复运行时仍然只在最右侧保留一份新列。"""
    # dummy 列名来自 investment_type，因此先根据当前文件里的类型动态拼出可能的旧列名。
    investment_type_dummy_columns = {
        f"{prefix}_{investment_type}"
        for investment_type in get_investment_type_values(data)
        for prefix in ("is", "as")
    }
    # 同时删除早期 is_ 前缀和新版 as_ 前缀，保证脚本重复运行后不会出现两套 dummy。
    columns_to_drop = [
        column
        for column in data.columns
        if column in CONTROL_COLUMNS
        or column in FUND_SIZE_COLUMNS
        or column in FUND_AGE_COLUMNS
        or column in investment_type_dummy_columns
    ]
    return data.drop(columns=columns_to_drop, errors="ignore")


def add_return_control_columns(data: pd.DataFrame) -> pd.DataFrame:
    """计算 CtrlRetLTM、CtrlRetSTR 和 CtrlVol。"""
    # 先按基金和月份排序，后面的 shift(1)、shift(12) 才能代表"同一基金的上一期/过去几期"。
    result = data.sort_values(
        [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    ).reset_index(drop=True)
    # groupby 后的 shift 只会在同一只基金内部移动，不会把上一只基金的记录错接过来。
    grouped = result.groupby(Config.COLUMN_IFIND_CODE, sort=False)
    # Period("M") 只比较年月，不受每个月最后一个交易日具体日期不同的影响。
    current_period = result[Config.COLUMN_MONTH_DATE].dt.to_period("M")

    # 短期收益率只在上一条记录正好是同一基金的上一个月时才有效。
    # 如果中间缺了月份，即使 shift(1) 有值，也不能把它当成"过去 1 个月收益率"。
    previous_nav = grouped[Config.COLUMN_NAV].shift(1)
    previous_date = grouped[Config.COLUMN_MONTH_DATE].shift(1)
    previous_period = previous_date.dt.to_period("M")
    has_previous_month = previous_period == current_period - 1
    # 先向量化算出净值比值，再把月份不连续的位置清成 NaN。
    result["CtrlRetSTR"] = result[Config.COLUMN_NAV] / previous_nav - 1
    result.loc[~has_previous_month, "CtrlRetSTR"] = np.nan

    # 过去 2~12 个月收益率 = 从 12 个月总收益中剔除最近 1 个月的部分。
    # 公式：(1 + R_12m) / (1 + R_1m) - 1，当 CtrlRetSTR 缺失时结果自然为 NaN。
    result["CtrlRetLTM"] = (1 + result["past_ret_12m_1"]) / (1 + result["CtrlRetSTR"]) - 1

    # 调整列顺序，保证输出为 CtrlRetLTM → CtrlRetSTR → CtrlVol，与 CONTROL_COLUMNS 一致。
    ctrl_ret_str = result.pop("CtrlRetSTR")
    result["CtrlRetSTR"] = ctrl_ret_str

    # CtrlVol 使用当前行之前 12 个月的 CtrlRetSTR，不包含当前月自己的 CtrlRetSTR。
    # 每个 CtrlRetSTR 已经要求相邻两个月净值连续；这里还要确保这 12 个收益率月份本身连续。
    previous_return_columns = []
    # 初始都设为 True，再逐个月用 &= 收紧条件；只要一个月份不匹配，整行就会变成 False。
    has_full_previous_12_months = pd.Series(True, index=result.index)
    for offset in range(1, 13):
        # offset=1 表示上个月的 CtrlRetSTR，offset=12 表示往前第 12 个月的 CtrlRetSTR。
        shifted_return = grouped["CtrlRetSTR"].shift(offset)
        shifted_date = grouped[Config.COLUMN_MONTH_DATE].shift(offset)
        shifted_period = shifted_date.dt.to_period("M")
        # 把 12 个 shifted CtrlRetSTR 暂存在列表里，后面横向拼成 12 列窗口。
        previous_return_columns.append(shifted_return)
        has_full_previous_12_months &= shifted_period == current_period - offset

    # 每一行现在都有"前 1 月 CtrlRetSTR、前 2 月 CtrlRetSTR、...、前 12 月 CtrlRetSTR"共 12 个值。
    previous_return_window = pd.concat(previous_return_columns, axis=1)
    # 除了月份连续，还要求 12 个 CtrlRetSTR 都能成功计算；有任一缺失就不算波动率。
    has_full_previous_12_returns = (
        has_full_previous_12_months & previous_return_window.notna().all(axis=1)
    )
    # pandas 的 std 默认会跳过 NaN，所以必须在下一行把不完整窗口清成 NaN。
    result["CtrlVol"] = previous_return_window.std(axis=1, ddof=1)
    result.loc[~has_full_previous_12_returns, "CtrlVol"] = np.nan

    return result


def get_investment_type_values(data: pd.DataFrame) -> list[object]:
    """按数据中首次出现的顺序列出 investment_type 的取值。"""
    # pd.unique 会保留首次出现顺序；最后一个类型后面会作为基准组，不生成 dummy。
    return list(pd.unique(data[Config.COLUMN_INVESTMENT_TYPE].dropna()))


def add_investment_type_dummy_columns(
    data: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    """为 investment_type 生成 dummy 变量，最后一个类型作为基准组。"""
    # copy 后再加列，保持输入 data 本身不被函数意外修改。
    result = data.copy()
    investment_types = get_investment_type_values(result)
    dummy_columns: list[str] = []

    # 只遍历到倒数第二个类型；最后一个类型是回归里的基准组，避免完全共线。
    for investment_type in investment_types[:-1]:
        column = f"as_{investment_type}"
        # True/False 转成 1/0，方便之后直接作为数值型控制变量进入回归。
        result[column] = (
            result[Config.COLUMN_INVESTMENT_TYPE] == investment_type
        ).astype("int64")
        dummy_columns.append(column)

    return result, dummy_columns


def read_one_fund_size_long(fund_size_path: Path) -> pd.DataFrame:
    """读取单个 iFind 基金规模宽表，并转成长表格式的 fund_size 数据。"""

    # 1. 读取 Excel 文件的 month sheet（iFind 导出的宽表格式）
    wide = pd.read_excel(fund_size_path, sheet_name="month")
    if wide.empty or len(wide.columns) < 2:
        raise ValueError(f"{fund_size_path} 的 month sheet 没有可用数据。")

    # 2. 统一第一列列名，提取日期列和基金代码
    wide.columns = ["证券代码", *wide.columns[1:]]
    raw_date_columns = list(wide.columns[1:])
    normalized_codes = wide["证券代码"].map(normalize_code)

    # 3. 删除底部"数据来源"等说明行（这些行基金代码为空）
    valid_code_rows = normalized_codes.notna()
    wide = wide.loc[valid_code_rows, raw_date_columns].copy()
    wide.insert(0, Config.COLUMN_IFIND_CODE, normalized_codes.loc[valid_code_rows].to_numpy())

    # 4. 将宽表列名（日期）统一解析成 Timestamp，检查是否有无法识别的日期
    date_mapping = {column: parse_excel_date(column) for column in raw_date_columns}
    invalid_date_columns = [
        column for column, parsed_date in date_mapping.items() if pd.isna(parsed_date)
    ]
    if invalid_date_columns:
        raise ValueError(
            f"{fund_size_path.name} 含无法识别的日期列：{invalid_date_columns[:10]}"
        )

    # 5. melt 将宽表转为长表：每行变成 (基金代码, 月份, 基金规模)
    long = wide[[Config.COLUMN_IFIND_CODE, *raw_date_columns]].melt(
        id_vars=Config.COLUMN_IFIND_CODE,
        value_vars=raw_date_columns,
        var_name="source_month_date",
        value_name="fund_size",
    )
    # 6. 用之前的映射把原始列名替换为标准化的 Timestamp
    long[Config.COLUMN_MONTH_DATE] = long["source_month_date"].map(date_mapping)
    long["fund_size"] = pd.to_numeric(long["fund_size"], errors="coerce")
    # 7. 删除三列中任一缺失的行
    long = long.dropna(
        subset=[Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE, "fund_size"]
    )

    # 8. 对正数基金规模取自然对数；0 或负数视为无效，保留为 NaN
    long["Ctrl_log_fund_size"] = np.nan
    positive_size = long["fund_size"] > 0
    long.loc[positive_size, "Ctrl_log_fund_size"] = np.log(
        long.loc[positive_size, "fund_size"]
    )
    # 9. 只保留成功计算 log 的行
    long = long.dropna(subset=["Ctrl_log_fund_size"])

    return long[
        [
            Config.COLUMN_IFIND_CODE,
            Config.COLUMN_MONTH_DATE,
            "fund_size",
            "Ctrl_log_fund_size",
        ]
    ]


def read_fund_size_long(fund_size_dir: Path) -> pd.DataFrame:
    """批量读取已合并好的 iFind 主基金规模宽表，并合并成长表。"""
    if not fund_size_dir.exists():
        raise FileNotFoundError(f"iFind 基金规模目录不存在：{fund_size_dir}")

    # 1. 扫描目录下主基金规模文件。已到期基金规模已在 2_fund_filter.py 合并进主表。
    fund_size_paths = sorted(
        path
        for path in fund_size_dir.glob("iFind*基金基金规模.xlsx")
        if not path.name.startswith("~$") and "已到期基金" not in path.name
    )
    if not fund_size_paths:
        raise FileNotFoundError(f"{fund_size_dir} 中没有找到 iFind*基金基金规模.xlsx。")

    # 2. 逐个读取并转为长表，然后纵向拼接
    fund_size_frames = [read_one_fund_size_long(path) for path in fund_size_paths]
    fund_size = pd.concat(fund_size_frames, ignore_index=True)
    fund_size = fund_size.sort_values(
        [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    ).reset_index(drop=True)

    # 3. 检查基金-日期键唯一性，防止 left merge 时行数膨胀
    duplicate_keys = fund_size.duplicated(
        [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE], keep=False
    )
    if duplicate_keys.any():
        examples = fund_size.loc[
            duplicate_keys, [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
        ].head(10)
        raise ValueError(
            "基金规模宽表出现重复基金-日期键，无法安全合并：\n"
            + examples.to_string(index=False)
        )

    return fund_size


def add_fund_size_column(data: pd.DataFrame, fund_size_dir: Path) -> pd.DataFrame:
    """按基金代码和日期，把 fund_size 和 Ctrl_log_fund_size 追加到面板最右侧。"""
    # 先删掉旧列，让脚本重复运行时不会出现两份同名或错位的规模变量。
    base = data.drop(columns=list(FUND_SIZE_COLUMNS), errors="ignore")
    fund_size = read_fund_size_long(fund_size_dir)

    result = base.merge(
        fund_size,
        on=[Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE],
        how="left",
        sort=False,
        validate="many_to_one",
    )
    return result


def read_fund_inception_dates(fund_info_path: Path) -> pd.DataFrame:
    """读取基金基本信息表，整理成 ifind_code 到基金成立日的映射。"""
    if not fund_info_path.exists():
        raise FileNotFoundError(f"基金基本信息文件不存在：{fund_info_path}")

    # 1. 读取 Excel 并检查必需字段
    fund_info = pd.read_excel(fund_info_path)
    missing = [
        column for column in ("证券代码", "基金成立日") if column not in fund_info.columns
    ]
    if missing:
        raise ValueError(
            f"{fund_info_path} 缺少字段：{missing}；实际字段为：{list(fund_info.columns)}"
        )

    # 2. 只保留合并需要的两列，统一基金代码和日期格式
    mapping = fund_info[["证券代码", "基金成立日"]].copy()
    mapping[Config.COLUMN_IFIND_CODE] = mapping["证券代码"].map(normalize_code)
    mapping["基金成立日"] = mapping["基金成立日"].map(parse_excel_date)
    # 3. 删除代码或成立日缺失的行
    mapping = mapping.dropna(subset=[Config.COLUMN_IFIND_CODE, "基金成立日"])
    mapping = mapping[[Config.COLUMN_IFIND_CODE, "基金成立日"]]

    # 4. 检查同一基金代码是否对应多个成立日（不允许一对多）
    conflict_counts = mapping.groupby(Config.COLUMN_IFIND_CODE)["基金成立日"].nunique()
    conflict_codes = conflict_counts[conflict_counts > 1].index.tolist()
    if conflict_codes:
        examples = mapping[mapping[Config.COLUMN_IFIND_CODE].isin(conflict_codes[:10])]
        raise ValueError(
            "同一基金代码对应多个基金成立日，无法安全合并：\n"
            + examples.to_string(index=False)
        )

    # 5. 去重后返回唯一映射表
    return mapping.drop_duplicates(subset=[Config.COLUMN_IFIND_CODE]).reset_index(
        drop=True
    )


def calculate_fund_age_in_months(
    month_date: pd.Series, inception_date: pd.Series
) -> pd.Series:
    """计算每行观测日距离基金成立日已经满了几个月。"""
    # 1. 先按年月差计算粗略月数
    age_months = (
        (month_date.dt.year - inception_date.dt.year) * 12
        + (month_date.dt.month - inception_date.dt.month)
    )
    # 2. 如果观测日的"日"小于成立日的"日"，说明当月还没满整月，少算 1 个月
    has_not_reached_month_day = month_date.dt.day < inception_date.dt.day
    age_months = age_months - has_not_reached_month_day.astype("int64")

    # 3. 缺失成立日时结果置为 NaN；早于成立日的负数保留，便于后续排查
    age_months = age_months.where(inception_date.notna())
    return age_months.astype("Int64")


def add_fund_age_columns(data: pd.DataFrame, fund_info_path: Path) -> pd.DataFrame:
    """把基金成立日和 Ctrl_fund_age 追加到面板最右侧。"""
    # 先删除旧列，保证重复运行时两列仍然只出现一次，并保持在最右侧。
    base = data.drop(columns=list(FUND_AGE_COLUMNS), errors="ignore")
    inception_dates = read_fund_inception_dates(fund_info_path)

    result = base.merge(
        inception_dates,
        on=Config.COLUMN_IFIND_CODE,
        how="left",
        sort=False,
        validate="many_to_one",
    )
    result["Ctrl_fund_age"] = calculate_fund_age_in_months(
        result[Config.COLUMN_MONTH_DATE], result["基金成立日"]
    )
    return result


def drop_negative_fund_age_anomalies(data: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    """根据负基金年龄的形态，删除成立日前异常样本。

    规则分成两类：
    1. 如果某只基金只有 1 条负年龄记录，且年龄为 -1，通常是成立日前一个月末的净值点，
       只删除这 1 行；
    2. 如果负年龄记录不止 1 条，或唯一负年龄不是 -1，说明这只基金的历史记录明显早于成立日，
       删除这只基金的全部面板记录。
    """
    # 1. 找到所有基金年龄为负的行
    negative_age = data["Ctrl_fund_age"] < 0
    if not negative_age.any():
        return data, {
            "dropped_pre_inception_month_end_rows": 0,
            "dropped_full_fund_rows": 0,
            "dropped_full_fund_codes": [],
        }

    single_row_indexes: list[int] = []
    full_drop_codes: list[str] = []

    # 2. 按基金分组，对每只基金的负年龄记录分类处理
    negative_data = data.loc[negative_age, [Config.COLUMN_IFIND_CODE, "Ctrl_fund_age"]]
    for ifind_code, group in negative_data.groupby(Config.COLUMN_IFIND_CODE, sort=True):
        ages = group["Ctrl_fund_age"].astype("int64")
        if len(group) == 1 and int(ages.iloc[0]) == -1:
            # 仅 1 条且年龄为 -1：成立前一个月末的净值点，只删这一行
            single_row_indexes.append(int(group.index[0]))
        else:
            # 多条负年龄或非 -1：历史数据严重早于成立日，整只基金删除
            full_drop_codes.append(ifind_code)

    # 3. 合并两类删除条件，生成最终结果
    full_drop_code_set = set(full_drop_codes)
    rows_to_drop = data.index.isin(single_row_indexes) | data[
        Config.COLUMN_IFIND_CODE
    ].isin(full_drop_code_set)
    result = data.loc[~rows_to_drop].reset_index(drop=True)

    # 4. 返回删除摘要，供 print_summary 输出
    drop_summary = {
        "dropped_pre_inception_month_end_rows": len(single_row_indexes),
        "dropped_full_fund_rows": int(
            data[Config.COLUMN_IFIND_CODE].isin(full_drop_code_set).sum()
        ),
        "dropped_full_fund_codes": full_drop_codes,
    }
    return result, drop_summary


def add_control_variables(data: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """返回追加控制变量后的面板，以及本次新增的 dummy 列名。"""
    # 第一步先清掉旧控制变量，保证新增列始终集中在表格最右侧。
    base = drop_existing_control_columns(data)
    # 第二步计算收益率和波动率相关的三个控制变量。
    with_returns = add_return_control_columns(base)
    # 第三步按 investment_type 补 dummy，同时拿到 dummy 列名用于后续校验和打印。
    with_controls, dummy_columns = add_investment_type_dummy_columns(with_returns)
    return with_controls, dummy_columns


def validate_controls(
    original: pd.DataFrame, result: pd.DataFrame, dummy_columns: list[str]
) -> None:
    """保存前做基础校验，尽早发现错列、错行或 dummy 异常。"""
    # 1. 行数一致性：控制变量只加列，不应增删行
    if len(result) != len(original):
        raise AssertionError("追加控制变量后行数发生变化。")

    # 2. 原始字段顺序保持不变（先模拟清理旧控制变量列再比较）
    original_without_controls = drop_existing_control_columns(original)
    expected_prefix = list(original_without_controls.columns)
    if list(result.columns[: len(expected_prefix)]) != expected_prefix:
        raise AssertionError("原有字段顺序发生变化。")

    # 3. 新增列顺序必须严格为：CONTROL_COLUMNS → dummy → FUND_SIZE → FUND_AGE
    added_columns = list(result.columns[len(expected_prefix) :])
    expected_added_columns = [
        *CONTROL_COLUMNS,
        *dummy_columns,
        *FUND_SIZE_COLUMNS,
        *FUND_AGE_COLUMNS,
    ]
    if added_columns != expected_added_columns:
        raise AssertionError(
            f"新增字段顺序不正确：{added_columns}，预期：{expected_added_columns}"
        )

    # 4. dummy 变量只允许 0/1 整数值
    for column in dummy_columns:
        if not result[column].isin([0, 1]).all():
            raise AssertionError(f"{column} 出现 0/1 之外的取值。")


def get_default_preview_path(output_path: Path) -> Path:
    """根据 parquet 输出路径推导 Excel 预览路径。"""
    # 与 3_generate_panel_base.py 的命名习惯一致：panel_base.parquet -> panel_base_preview.xlsx。
    return output_path.with_name(output_path.stem + "_preview.xlsx")


def copy_outputs_to_factor_input(
    output_path: Path, preview_path: Path | None, factor_input_dir: Path
) -> dict[str, Path | None]:
    """把最终输出文件复制到 B_factors/input，供后续因子脚本使用。"""
    # 这里放在所有写文件逻辑之后执行，确保 B_factors/input 拿到的是最新版本。
    factor_input_dir.mkdir(parents=True, exist_ok=True)

    copied_parquet_path = factor_input_dir / output_path.name
    shutil.copy2(output_path, copied_parquet_path)

    copied_preview_path = None
    if preview_path is not None:
        copied_preview_path = factor_input_dir / preview_path.name
        shutil.copy2(preview_path, copied_preview_path)

    return {
        "copied_parquet_path": copied_parquet_path,
        "copied_preview_path": copied_preview_path,
    }


def generate_controls(
    input_path: Path,
    output_path: Path,
    fund_size_dir: Path,
    fund_info_path: Path,
    factor_input_dir: Path,
    preview_path: Path | None = None,
    write_preview: bool = True,
) -> dict[str, object]:
    """生成控制变量并写出 parquet，返回运行摘要。"""
    # 1. 读入原始面板数据
    original = read_panel(input_path)
    # 2. 计算收益率、波动率控制变量和 investment_type dummy
    with_controls, dummy_columns = add_control_variables(original)
    # 3. 从外部 iFind 宽表补充基金规模（fund_size 和 Ctrl_log_fund_size）
    with_fund_size = add_fund_size_column(with_controls, fund_size_dir)
    # 4. 从基金基本信息表补充成立日和基金年龄（Ctrl_fund_age）
    result = add_fund_age_columns(with_fund_size, fund_info_path)
    # 5. 落盘前校验：行数、列顺序、dummy 值域、LTM 口径一致性
    validate_controls(original, result, dummy_columns)
    # 6. 删除成立日前的异常样本（所有变量计算完毕后再删，不影响滚动窗口）
    result, negative_age_drop_summary = drop_negative_fund_age_anomalies(result)

    # 7. 写出正式 parquet 文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)

    # 8. 可选：同步刷新 Excel 预览（前 1000 行），便于人工检查
    actual_preview_path = None
    if write_preview:
        actual_preview_path = preview_path or get_default_preview_path(output_path)
        actual_preview_path.parent.mkdir(parents=True, exist_ok=True)
        result.head(1000).to_excel(actual_preview_path, index=False)

    # 9. 把输出文件复制到 B_factors/input，供后续因子脚本使用
    copied_outputs = copy_outputs_to_factor_input(
        output_path=output_path,
        preview_path=actual_preview_path,
        factor_input_dir=factor_input_dir,
    )

    # 10. 返回运行摘要字典，便于程序化调用时获取结果
    return {
        "input_path": input_path,
        "output_path": output_path,
        "preview_path": actual_preview_path,
        "copied_parquet_path": copied_outputs["copied_parquet_path"],
        "copied_preview_path": copied_outputs["copied_preview_path"],
        "fund_size_dir": fund_size_dir,
        "fund_info_path": fund_info_path,
        "factor_input_dir": factor_input_dir,
        "row_count": len(result),
        "column_count": len(result.columns),
        "negative_age_drop_summary": negative_age_drop_summary,
        "added_columns": [
            *CONTROL_COLUMNS,
            *dummy_columns,
            *FUND_SIZE_COLUMNS,
            *FUND_AGE_COLUMNS,
        ],
        "non_null_counts": {
            column: int(result[column].notna().sum())
            for column in [
                *CONTROL_COLUMNS,
                *dummy_columns,
                *FUND_SIZE_COLUMNS,
                *FUND_AGE_COLUMNS,
            ]
        },
    }


def print_summary(summary: dict[str, object]) -> None:
    """打印运行摘要，方便在终端快速核对结果。"""
    # 路径信息先打印，用户可以立刻确认是否覆盖了想要的文件。
    print(f"输入路径：{summary['input_path']}")
    print(f"输出路径：{summary['output_path']}")
    if summary["preview_path"] is not None:
        print(f"预览路径：{summary['preview_path']}")
    print(f"B_factors parquet 复制路径：{summary['copied_parquet_path']}")
    if summary["copied_preview_path"] is not None:
        print(f"B_factors preview 复制路径：{summary['copied_preview_path']}")
    print(f"基金规模来源目录：{summary['fund_size_dir']}")
    print(f"基金基本信息路径：{summary['fund_info_path']}")
    # 行列数用于快速发现是否误删行、重复加列或输出到错误文件。
    print(f"输出行数：{summary['row_count']:,}")
    print(f"输出列数：{summary['column_count']:,}")
    negative_age_drop_summary = summary["negative_age_drop_summary"]
    print(
        "负基金年龄处理："
        f"删除成立日前一个月末单条记录 "
        f"{negative_age_drop_summary['dropped_pre_inception_month_end_rows']:,} 行；"
        f"删除异常基金整只基金 "
        f"{len(negative_age_drop_summary['dropped_full_fund_codes']):,} 只、"
        f"{negative_age_drop_summary['dropped_full_fund_rows']:,} 行"
    )
    if negative_age_drop_summary["dropped_full_fund_codes"]:
        print(
            "整只删除的基金代码："
            + "、".join(negative_age_drop_summary["dropped_full_fund_codes"])
        )
    print("新增字段：")
    non_null_counts = summary["non_null_counts"]
    # 控制变量的非缺失数量能帮助判断月份连续性和 dummy 生成是否符合预期。
    for column in summary["added_columns"]:
        print(f"  {column}：非缺失/有效行数 {non_null_counts[column]:,}")


def main() -> None:
    """命令行入口。"""
    # main 只负责串起"解析参数 -> 生成文件 -> 打印摘要"，具体逻辑放在可测试函数里。
    args = parse_args()
    summary = generate_controls(
        input_path=args.input,
        output_path=args.output,
        fund_size_dir=args.fund_size_dir,
        fund_info_path=args.fund_info,
        factor_input_dir=args.factor_input_dir,
        preview_path=args.preview,
        write_preview=not args.no_preview,
    )
    print_summary(summary)


if __name__ == "__main__":
    main()
