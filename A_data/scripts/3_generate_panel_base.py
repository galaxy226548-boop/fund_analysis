"""从基金净值筛选长表生成多周期收益率面板。

输入文件：

    A_data/prepared_data/*基金净值筛选长表.parquet

默认输出文件：

    A_data/output/panel_base.parquet

热力图专用输出文件：

    A_data/output/panel_base_heatmap_m1_12_n1_12.parquet

脚本按配置生成逐步前推的过去收益率窗口，并计算未来 3、6、12 个月
被解释变量收益率。收益率可以选择：

- simple：简单收益率，净值比值减 1；
- log：对数收益率，净值比值取自然对数。

每个收益率都有一个对应的 ``match_is_sample`` 标签。收益率本身只要求
起点和终点净值存在，不受标签影响。

运行方式：

    python A_data/scripts/3_generate_panel_base.py
    python A_data/scripts/3_generate_panel_base.py --return-type log
    python A_data/scripts/3_generate_panel_base.py --spec-set heatmap

整体流程概览：
    1. 读取筛选长表（每个投资类型一份 parquet 文件）
    2. 纵向拼接所有投资类型
    3. 计算未来收益率（被解释变量）：future_ret_3m / 6m / 12m
    4. 计算过去收益率窗口（解释变量的原料）：past_ret_Xm_Y
       —— 按 PANEL_PAIRWISE 步长逐步前推，生成多个重叠或不重叠的子期间
    5. 对每个过去收益率做截面百分位排名：past_ret_Xm_rank_Y
       —— 在同一 month_date、同一 investment_type 内排名
    6. 对多个子期间的排名计算标准差：rank_vol_m{m}_n{n}_pairwise1
       —— 这就是"排名波动率"，衡量基金排名的稳定性
    7. 计算排名波动率的反向指标：FAC_rank_vol = 1 - rank_vol
       —— FAC 越大 = 排名越稳定（越一致）
    8. 校验并输出
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import Config


# ============================================================
# 从 Config 模块读取项目级别的路径和参数配置
# ============================================================
PROJECT_ROOT = Config.PROJECT_ROOT          # 项目根目录
A_DATA_ROOT = Config.A_DATA_ROOT            # A_data 目录
DEFAULT_SOURCE_DIR = Config.PANEL_SOURCE_DIR    # 筛选长表所在目录
DEFAULT_OUTPUT_PATH = Config.PANEL_OUTPUT_PATH  # 面板输出路径
DEFAULT_HEATMAP_OUTPUT_PATH = Config.PANEL_HEATMAP_OUTPUT_PATH

# 未来收益率的期限列表，例如 [3, 6, 12] 表示未来 3/6/12 个月
FUTURE_RETURN_HORIZONS = Config.PANEL_FUTURE_RETURN_HORIZONS

# 面板所需的源数据字段（基金代码、月份、净值、是否在样本内等）
REQUIRED_COLUMNS = Config.PANEL_REQUIRED_COLUMNS

# 原有 pairwise=1 组合继续单独保留，主要用于兼容已有调用方。
PAST_RETURN_COMBOS = Config.PANEL_PAST_RETURN_COMBOS

# 多步长统一规格。每个元素依次为：单期收益期限 m、排名期数 n、实际步长。
# 例如 (6, 3, 6) 表示回看 3 个互不重叠的 6 个月收益窗口。
PAST_RETURN_SPECS = Config.PANEL_PAST_RETURN_SPECS

SPEC_SET_CHOICES = ("baseline", "heatmap")


def parse_args() -> argparse.Namespace:
    """读取命令行参数，允许用户在运行时指定收益率类型、源目录和输出路径。"""
    parser = argparse.ArgumentParser(description="生成基金多周期收益率面板。")
    parser.add_argument(
        "--spec-set",
        choices=SPEC_SET_CHOICES,
        default="baseline",
        help=(
            "过去收益率规格集合：baseline 为原有规格；"
            "heatmap 为 m=1..12、n=1..12、pairwise=1，并补充 winrate 所需"
            "m,n=1..6、pairwise=m 的非重叠规格。"
        ),
    )
    parser.add_argument(
        "--return-type",
        choices=Config.VALID_RETURN_TYPES,
        default=Config.PANEL_RETURN_TYPE,
        help="收益率类型：simple 为简单收益率，log 为对数收益率。",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=DEFAULT_SOURCE_DIR,
        help="基金净值筛选长表所在目录。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "面板输出路径。未指定时，baseline 写入默认 panel_base.parquet，"
            "heatmap 写入热力图专用 parquet。"
        ),
    )
    return parser.parse_args()


def get_specs_for_spec_set(spec_set: str) -> tuple[tuple[int, int, int], ...]:
    """按命令行选择返回过去收益率规格。

    baseline 保持项目原有规格不变；heatmap 使用 1..12 滚动完整网格，并补入
    1..6 的非重叠 winrate 网格。
    返回 tuple 是为了让后续校验和循环逻辑拿到不可变、可复现的配置快照。
    """
    if spec_set == "baseline":
        return Config.PANEL_PAST_RETURN_SPECS
    if spec_set == "heatmap":
        return Config.PANEL_HEATMAP_PAST_RETURN_SPECS
    raise ValueError(f"未知规格集合：{spec_set}")


def get_default_output_path(spec_set: str) -> Path:
    """按规格集合返回默认输出路径，避免热力图模式覆盖基准面板。"""
    if spec_set == "baseline":
        return DEFAULT_OUTPUT_PATH
    if spec_set == "heatmap":
        return DEFAULT_HEATMAP_OUTPUT_PATH
    raise ValueError(f"未知规格集合：{spec_set}")


def set_past_return_specs(specs: Iterable[tuple[int, int, int]]) -> None:
    """切换当前运行使用的过去收益率规格。

    本脚本中很多列名函数会共享同一套规格。集中在入口处切换全局变量，
    可以让 baseline 和 heatmap 共用同一条计算流水线，又不改变默认行为。
    """
    global PAST_RETURN_SPECS
    PAST_RETURN_SPECS = tuple(specs)


def require_columns(
    data: pd.DataFrame, columns: Iterable[str], source_path: Path
) -> None:
    """检查输入 DataFrame 是否包含程序需要的全部字段。

    如果有缺失字段，直接抛出 ValueError 并列出缺少哪些列，
    避免后续计算因列名不存在而报出难以定位的 KeyError。
    """
    # 找出 REQUIRED_COLUMNS 中不在实际列名里的字段
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source_path} 缺少字段：{missing}；实际字段为：{list(data.columns)}"
        )


def find_source_files(source_dir: Path) -> list[Path]:
    """在指定目录中搜索所有基金净值筛选长表文件。

    文件名需匹配 Config.PANEL_SOURCE_FILE_PATTERN（如 "*基金净值筛选长表.parquet"）。
    返回排序后的文件列表，保证处理顺序稳定可复现。
    """
    # glob 匹配所有以"基金净值筛选长表.parquet"结尾的文件，sorted 保证顺序稳定
    source_files = sorted(source_dir.glob(Config.PANEL_SOURCE_FILE_PATTERN))
    if not source_files:
        raise FileNotFoundError(
            f"{source_dir} 中没有找到 {Config.PANEL_SOURCE_FILE_PATTERN}。"
        )
    return source_files


def read_filter_table(source_path: Path) -> pd.DataFrame:
    """读取一份筛选长表，只保留面板需要的字段，并做类型和缺失值检查。

    处理步骤：
    1. 读取 parquet 文件
    2. 检查必需字段是否齐全
    3. 只保留面板所需列（丢弃多余字段）
    4. 强制类型转换（日期、净值、布尔标签）
    5. 校验净值和日期没有异常
    """
    data = pd.read_parquet(source_path)
    require_columns(data, REQUIRED_COLUMNS, source_path)

    # 只保留面板所需列，避免带入多余字段
    data = data[list(REQUIRED_COLUMNS)].copy()

    # 强制类型转换，防止上游存储格式不一致导致计算错误
    # 将 month_date 转为 datetime 类型
    data[Config.COLUMN_MONTH_DATE] = pd.to_datetime(
        data[Config.COLUMN_MONTH_DATE], errors="coerce"
    )
    # 将净值转为数值类型
    data[Config.COLUMN_NAV] = pd.to_numeric(data[Config.COLUMN_NAV], errors="coerce")

    # is_sample 缺失值视为不在样本内（False）
    data[Config.COLUMN_IS_SAMPLE] = (
        data[Config.COLUMN_IS_SAMPLE].fillna(False).astype(bool)
    )
    # is_size_eligible 缺失值视为不满足规模条件（False）
    data[Config.COLUMN_IS_SIZE_ELIGIBLE] = (
        data[Config.COLUMN_IS_SIZE_ELIGIBLE].fillna(False).astype(bool)
    )

    # 净值和日期有问题时直接报错，避免后续计算产生静默 NaN
    if data[Config.COLUMN_MONTH_DATE].isna().any():
        raise ValueError(
            f"{source_path.name} 中存在无法识别的 {Config.COLUMN_MONTH_DATE}。"
        )
    if data[Config.COLUMN_NAV].isna().any() or (data[Config.COLUMN_NAV] <= 0).any():
        raise ValueError(f"{source_path.name} 中存在缺失或非正数净值。")

    return data


def calculate_return(
    start_nav: pd.Series, end_nav: pd.Series, return_type: str
) -> pd.Series:
    """根据起点净值和终点净值计算收益率。

    参数：
        start_nav: 期初净值序列
        end_nav: 期末净值序列
        return_type: "simple" 或 "log"

    计算方式：
        simple（简单收益率）：(终值 - 起值) / 起值 = 终值/起值 - 1
        log（对数收益率）：ln(终值/起值)，满足时间可加性
    """
    nav_ratio = end_nav / start_nav
    if return_type == "simple":
        # 简单收益率：(终值 - 起值) / 起值 = 终值/起值 - 1
        return nav_ratio - 1
    # 对数收益率：ln(终值/起值)，满足时间可加性
    return np.log(nav_ratio)


def validate_past_return_specs() -> None:
    """检查多步长规格，尽早拦截重复、非正数或伪非重叠配置。"""
    seen: set[tuple[int, int, int]] = set()
    for spec in PAST_RETURN_SPECS:
        if len(spec) != 3:
            raise ValueError(f"过去收益率规格必须为三元组，当前为 {spec!r}。")
        return_horizon, rank_count, pairwise = spec
        values = (return_horizon, rank_count, pairwise)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in values
        ):
            raise ValueError(f"过去收益率规格必须全部为正整数，当前为 {spec!r}。")
        if pairwise not in {1, return_horizon}:
            raise ValueError(
                "当前只支持 pairwise=1 或完全非重叠的 "
                f"pairwise=return_horizon，当前为 {spec!r}。"
            )
        if spec in seen:
            raise ValueError(f"过去收益率规格重复：{spec!r}。")
        seen.add(spec)


def get_pairwise_past_return_windows() -> dict[tuple[int, int], int]:
    """返回每个 ``(return_horizon, pairwise)`` 所需的最大窗口数。

    同一收益期限和步长可能服务多个 rank_count，因此只生成到最大期数即可。
    把 pairwise 放进字典键，是为了让滚动与非重叠窗口在同一面板中并存。
    """
    validate_past_return_specs()
    windows: dict[tuple[int, int], int] = {}
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        key = (return_horizon, pairwise)
        windows[key] = max(windows.get(key, 0), rank_count)
    return dict(sorted(windows.items()))


def get_past_return_column(
    return_horizon: int, window_index: int, pairwise: int
) -> str:
    """生成过去收益率列名；pairwise1 保留历史名称以兼容旧模型。"""
    base = f"past_ret_{return_horizon}m_{window_index}"
    return base if pairwise == 1 else f"{base}_pairwise{pairwise}"


def get_past_match_column(
    return_horizon: int, window_index: int, pairwise: int
) -> str:
    """生成窗口匹配标签列名。"""
    return f"match_is_sample_{get_past_return_column(return_horizon, window_index, pairwise)}"


def get_past_rank_column(
    return_horizon: int, window_index: int, pairwise: int
) -> str:
    """生成截面排名列名；新增步长必须显式写进名称。"""
    base = f"past_ret_{return_horizon}m_rank_{window_index}"
    return base if pairwise == 1 else f"{base}_pairwise{pairwise}"


def get_pairwise_past_return_columns() -> list[str]:
    """列出所有按步长前推的 past return 列名。

    例如 return_horizon=6, rank_count=12 时，生成：
        past_ret_6m_1, past_ret_6m_2, ..., past_ret_6m_12
    其中 past_ret_6m_1 是距当前最近的 6 个月收益率，
    past_ret_6m_2 是再往前推一步（PANEL_PAIRWISE 个月）的 6 个月收益率，
    以此类推。
    """
    columns: list[str] = []
    for (return_horizon, pairwise), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            columns.append(
                get_past_return_column(return_horizon, window_index, pairwise)
            )
    return columns


def get_pairwise_past_match_columns() -> list[str]:
    """列出所有按步长前推的 past return 的 match 标签列名。

    match 标签表示该窗口内所有月份的 is_sample 和 is_size_eligible 是否都为 True。
    只有 match=True 的窗口才参与排名计算。

    列名格式：match_is_sample_past_ret_{return_horizon}m_{window_index}
    """
    columns: list[str] = []
    for (return_horizon, pairwise), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            columns.append(get_past_match_column(return_horizon, window_index, pairwise))
    return columns


def get_pairwise_past_rank_columns() -> list[str]:
    """列出所有 past return 的截面百分位排名列名。

    排名是在同一 month_date + investment_type 截面内计算的，
    值域为 [0, 1]，越高代表该基金在当月同类基金中表现越好。

    列名格式：past_ret_{return_horizon}m_rank_{window_index}
    """
    columns: list[str] = []
    for (return_horizon, pairwise), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            columns.append(get_past_rank_column(return_horizon, window_index, pairwise))
    return columns


def get_rank_volatility_column(
    rank_count: int, return_horizon: int, pairwise: int = Config.PANEL_PAIRWISE
) -> str:
    """返回指定 (m, n) 组合的排名波动率列名。

    排名波动率 = 多个子期间排名的标准差。
    列名格式：rank_vol_m{return_horizon}_n{rank_count}_pairwise{step}
    例如 rank_vol_m6_n12_pairwise1 表示：
        回看 12 个子期间（n=12），每个子期间计算 6 个月收益率（m=6），步长为 1
    """
    return (
        f"rank_vol_m{return_horizon}_n{rank_count}_"
        f"pairwise{pairwise}"
    )


def get_rank_volatility_columns() -> list[str]:
    """列出所有排名波动率列名（rank_vol_*）。"""
    return [
        get_rank_volatility_column(rank_count, return_horizon, pairwise)
        for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS
    ]


def get_fac_rank_volatility_column(
    rank_count: int, return_horizon: int, pairwise: int = Config.PANEL_PAIRWISE
) -> str:
    """返回排名波动率反向指标的列名。

    FAC = 1 - rank_vol，方向反转后，FAC 越大 = 排名越稳定 = 一致性越好。
    列名在原变量前加 "FAC_" 前缀。
    """
    return f"FAC_{get_rank_volatility_column(rank_count, return_horizon, pairwise)}"


def get_fac_rank_volatility_columns() -> list[str]:
    """列出所有排名波动率反向指标列名（FAC_rank_vol_*）。"""
    return [
        get_fac_rank_volatility_column(rank_count, return_horizon, pairwise)
        for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS
    ]


def get_future_return_columns() -> list[str]:
    """列出未来收益率相关的所有列名。

    包含三类列：
    1. future_ret_{horizon}m —— 未来收益率本身
    2. match_is_sample_future_ret_{horizon}m —— 窗口内是否都在样本内
    3. is_insample_future_ret_{horizon}m —— 是否在样本内期间（按截止日期判断）
    """
    return_columns = [
        f"future_ret_{horizon}m" for horizon in FUTURE_RETURN_HORIZONS
    ]
    match_columns = [
        f"match_is_sample_future_ret_{horizon}m"
        for horizon in FUTURE_RETURN_HORIZONS
    ]
    return [*return_columns, *match_columns, *get_future_insample_columns()]


def get_future_insample_columns() -> list[str]:
    """列出不同未来收益率口径下的样本内标记列名。

    用于区分样本内（用于模型训练）和样本外（用于模型验证）数据。
    """
    return [
        f"is_insample_future_ret_{horizon}m"
        for horizon in FUTURE_RETURN_HORIZONS
    ]


def add_future_return_columns(
    result: pd.DataFrame,
    grouped: pd.core.groupby.DataFrameGroupBy,
    current_period: pd.Series,
    return_type: str,
) -> pd.DataFrame:
    """为每个基金-月份计算未来收益率（被解释变量）和样本匹配标签。

    对每个 horizon（如 3/6/12 个月）：
    1. 通过 shift(-horizon) 获取 horizon 个月后的净值
    2. 校验偏移后的日期是否恰好是当前月份 + horizon 个月
       （如果中间有缺失月份，shift 会拿到错误的行，此时标记为 NaN）
    3. 计算收益率
    4. 生成 match 标签：从当前月到 horizon 个月后的每个月都必须 is_sample=True
    """
    for horizon in FUTURE_RETURN_HORIZONS:
        # --- 步骤 1：获取 horizon 个月后的净值和日期 ---
        # shift(-horizon) 在同一基金组内向前看 horizon 行
        future_nav = grouped[Config.COLUMN_NAV].shift(-horizon)
        future_date = grouped[Config.COLUMN_MONTH_DATE].shift(-horizon)
        future_period = future_date.dt.to_period("M")

        # --- 步骤 2：校验日期连续性 ---
        # 确保 shift 后的日期恰好是当前月份 + horizon 个月
        # 如果中间有月份缺失，shift 拿到的行实际对应更远的未来，需要标记为无效
        has_future_endpoint = future_period == current_period + horizon

        # --- 步骤 3：计算未来收益率 ---
        return_column = f"future_ret_{horizon}m"
        result[return_column] = calculate_return(
            result[Config.COLUMN_NAV], future_nav, return_type
        )
        # 日期不连续的行，收益率设为 NaN（无效）
        result.loc[~has_future_endpoint, return_column] = np.nan

        # --- 步骤 4：生成 match 标签 ---
        # match = 从当前月到 horizon 个月后的每个中间月份都必须 is_sample=True
        # 且每个中间月份的日期都必须恰好对应预期的月份（无缺失）
        match_column = f"match_is_sample_future_ret_{horizon}m"
        future_match = pd.Series(True, index=result.index)
        for offset in range(0, horizon + 1):
            # 逐个检查从 0（当前月）到 horizon（未来月）的每个偏移位置
            shifted_sample = (
                grouped[Config.COLUMN_IS_SAMPLE].shift(-offset).fillna(False)
            )
            shifted_date = grouped[Config.COLUMN_MONTH_DATE].shift(-offset)
            shifted_period = shifted_date.dt.to_period("M")
            # 偏移后的月份是否恰好是当前月份 + offset 个月
            is_expected_month = shifted_period == current_period + offset
            # 必须同时满足：is_sample=True 且日期正确
            future_match &= shifted_sample & is_expected_month
        result[match_column] = future_match

    return result


def add_insample_future_return_columns(result: pd.DataFrame) -> pd.DataFrame:
    """按未来收益率期限加入"是否在样本内期间"的标记列。

    逻辑：如果当前 month_date <= (样本内截止日 - horizon 个月)，
    则这笔观测的未来 horizon 个月收益率完全落在样本内期间，标记为 1；否则为 0。
    这用于后续区分样本内（模型训练）和样本外（模型验证）。
    """
    insample_end = pd.Timestamp(Config.PANEL_INSAMPLE_END_DATE)
    for horizon in FUTURE_RETURN_HORIZONS:
        # 截止日期往前推 horizon 个月，得到最晚可用的预测时点
        cutoff = insample_end - pd.DateOffset(months=horizon)
        column = f"is_insample_future_ret_{horizon}m"
        result[column] = (
            result[Config.COLUMN_MONTH_DATE] <= cutoff
        ).astype("int64")

    return result


def add_pairwise_past_return_columns(
    result: pd.DataFrame,
    grouped: pd.core.groupby.DataFrameGroupBy,
    current_period: pd.Series,
    return_type: str,
) -> pd.DataFrame:
    """生成按 PANEL_PAIRWISE 步长逐步前推的过去收益率窗口和样本匹配标签。

    核心逻辑（以 return_horizon=6, PANEL_PAIRWISE=1 为例）：
        window_index=1: 从 t-6 到 t（最近 6 个月的收益率）
        window_index=2: 从 t-7 到 t-1（往前推 1 个月的 6 个月收益率）
        window_index=3: 从 t-8 到 t-2（再往前推 1 个月）
        ...以此类推

    每个窗口都会同时生成：
    1. past_ret_{horizon}m_{index} —— 收益率本身
    2. match_is_sample_past_ret_{horizon}m_{index} —— 窗口内所有月份是否都满足
       is_sample=True 且 is_size_eligible=True 且日期连续
    """
    # 多步长会新增较多列，先用字典收集，最后一次性拼接。这样可避免 pandas
    # 因逐列插入产生高度碎片化的 DataFrame，正式大面板运行会稳定很多。
    new_columns: dict[str, pd.Series] = {}
    for (return_horizon, step), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            # --- 计算当前窗口的起止偏移量 ---
            # end_offset: 窗口终点距当前月份的偏移（月数），0 表示当前月
            end_offset = (window_index - 1) * step
            # start_offset: 窗口起点距当前月份的偏移（月数）
            start_offset = end_offset + return_horizon
            # 例如 window_index=2, step=1, return_horizon=6:
            #   end_offset=1, start_offset=7
            #   即从 t-7 到 t-1 的 6 个月收益率

            # --- 获取窗口起止点的净值和日期 ---
            # shift(正数) 在同一基金组内向过去看
            start_nav = grouped[Config.COLUMN_NAV].shift(start_offset)
            start_date = grouped[Config.COLUMN_MONTH_DATE].shift(start_offset)
            start_period = start_date.dt.to_period("M")

            end_nav = grouped[Config.COLUMN_NAV].shift(end_offset)
            end_date = grouped[Config.COLUMN_MONTH_DATE].shift(end_offset)
            end_period = end_date.dt.to_period("M")

            # --- 校验日期连续性 ---
            # 确保终点日期 = 当前月份 - end_offset
            # 且起点日期 + return_horizon = 终点日期（起止间距正好等于 return_horizon 个月）
            has_endpoints = (
                (end_period == current_period - end_offset)
                & (start_period + return_horizon == end_period)
            )

            # --- 计算过去收益率 ---
            return_column = get_past_return_column(
                return_horizon, window_index, step
            )
            return_values = calculate_return(start_nav, end_nav, return_type)
            # 日期不连续的行，收益率设为 NaN
            return_values.loc[~has_endpoints] = np.nan
            new_columns[return_column] = return_values

            # --- 生成 match 标签 ---
            # 窗口内每个月都必须满足 is_sample=True 且 is_size_eligible=True 且日期正确
            match_column = get_past_match_column(
                return_horizon, window_index, step
            )
            window_match = pd.Series(True, index=result.index)
            for offset in range(end_offset, start_offset + 1):
                # 逐个检查窗口内的每个月份
                shifted_sample = (
                    grouped[Config.COLUMN_IS_SAMPLE].shift(offset).fillna(False)
                )
                shifted_size_eligible = (
                    grouped[Config.COLUMN_IS_SIZE_ELIGIBLE]
                    .shift(offset)
                    .fillna(False)
                )
                shifted_date = grouped[Config.COLUMN_MONTH_DATE].shift(offset)
                shifted_period = shifted_date.dt.to_period("M")
                # 偏移后的月份是否恰好是当前月份 - offset 个月
                is_expected_month = current_period == shifted_period + offset
                # 三个条件同时满足：在样本内、满足规模条件、日期连续
                window_match &= (
                    shifted_sample & shifted_size_eligible & is_expected_month
                )
            new_columns[match_column] = window_match

    return pd.concat([result, pd.DataFrame(new_columns, index=result.index)], axis=1)


def add_pairwise_past_rank_columns(result: pd.DataFrame) -> pd.DataFrame:
    """对每个过去收益率窗口，在截面内计算百分位排名。

    排名规则：
    - 按 month_date + investment_type 分组（同月同类基金之间排名）
    - 只对同时满足 is_sample=True、match=True、收益率非空的样本计算排名
    - 使用 pct=True 返回 [0, 1] 的百分位排名（0 = 最差，1 = 最好）
    - 排名方法由 Config.PANEL_RANK_METHOD 决定（如 "average"）

    这些排名是后续计算排名波动率 (rank_vol) 的原料。
    """
    group_columns = [Config.COLUMN_MONTH_DATE, Config.COLUMN_INVESTMENT_TYPE]
    new_columns: dict[str, pd.Series] = {}
    for (return_horizon, pairwise), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            return_column = get_past_return_column(
                return_horizon, window_index, pairwise
            )
            match_column = get_past_match_column(
                return_horizon, window_index, pairwise
            )
            rank_column = get_past_rank_column(
                return_horizon, window_index, pairwise
            )

            # 只对满足所有条件的样本计算排名
            rank_sample = (
                result[Config.COLUMN_IS_SAMPLE]    # 在样本内
                & result[match_column]              # 窗口内所有月份都满足条件
                & result[return_column].notna()     # 收益率非空
            )
            # 先全部初始化为 NaN，再只给允许进入排名截面的样本填值。
            rank_values = pd.Series(np.nan, index=result.index, dtype="float64")
            # 只对满足条件的行计算截面百分位排名
            rank_values.loc[rank_sample] = (
                result.loc[rank_sample]
                .groupby(group_columns, sort=False)[return_column]
                .rank(method=Config.PANEL_RANK_METHOD, pct=True)
            )
            new_columns[rank_column] = rank_values

    return pd.concat([result, pd.DataFrame(new_columns, index=result.index)], axis=1)


def add_rank_volatility_columns(result: pd.DataFrame) -> pd.DataFrame:
    """对每个 (m, n) 组合，计算过去 m 个子期间排名的标准差（排名波动率）。

    这是本面板最核心的变量之一。

    计算逻辑：
    1. 取出 past_ret_{n}m_rank_1 到 past_ret_{n}m_rank_{m} 这 m 列排名
    2. 对每行（基金-月份），计算这 m 个排名的样本标准差（ddof 由 Config 配置）
    3. 如果 RANK_VOL_REQUIRE_FULL_WINDOW=True，则必须 m 个排名全部非空才计算；
       否则只要超过 ddof 个非空排名即可

    含义：
    - rank_vol 越小 → 该基金在过去 m 个子期间的排名越稳定（一致性好）
    - rank_vol 越大 → 排名波动大，可能时好时坏

    注意：这里的"标准差"和散点图脚本中直接对 rank 列取 std 的效果完全相同，
    区别在于这里有更严格的缺失值处理和 match 标签过滤。
    """
    new_columns: dict[str, pd.Series] = {}
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        # 收集需要的排名列名（共 rank_count 列）
        rank_columns = [
            get_past_rank_column(return_horizon, window_index, pairwise)
            for window_index in range(1, rank_count + 1)
        ]
        volatility_column = get_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )
        ranks = result[rank_columns]

        if Config.RANK_VOL_REQUIRE_FULL_WINDOW:
            # 严格模式：必须所有子期间排名都非空才计算波动率
            full_window = ranks.notna().all(axis=1)
            volatility = pd.Series(np.nan, index=result.index, dtype="float64")
            volatility.loc[full_window] = ranks.loc[full_window].std(
                axis=1, ddof=Config.RANK_VOL_DDOF
            )
        else:
            # 宽松模式：只要非空排名数 > ddof 就可以计算
            enough_observations = ranks.notna().sum(axis=1) > Config.RANK_VOL_DDOF
            volatility = ranks.std(
                axis=1, ddof=Config.RANK_VOL_DDOF, skipna=True
            )
            volatility.loc[~enough_observations] = np.nan
        new_columns[volatility_column] = volatility

    return pd.concat([result, pd.DataFrame(new_columns, index=result.index)], axis=1)


def add_fac_rank_volatility_columns(result: pd.DataFrame) -> pd.DataFrame:
    """生成排名波动率的反向指标：FAC_rank_vol = 1 - rank_vol。

    为什么要做反向：
    - 原始 rank_vol 越大 = 排名越不稳定（越不一致）
    - 取 1 减去后，FAC 越大 = 排名越稳定（越一致）
    - 这样在后续回归或排序分析中，"更大 = 更好"更直观

    如果原始 rank_vol 缺失，1 - NaN = NaN，自然保留为缺失值。
    """
    new_columns: dict[str, pd.Series] = {}
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        volatility_column = get_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )
        fac_column = get_fac_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )
        new_columns[fac_column] = 1 - result[volatility_column]

    return pd.concat([result, pd.DataFrame(new_columns, index=result.index)], axis=1)


def add_period_columns(data: pd.DataFrame, return_type: str) -> pd.DataFrame:
    """主计算流水线：按顺序计算未来收益率、过去收益率、排名、波动率等全部衍生字段。

    调用顺序：
    1. add_future_return_columns —— 未来收益率（被解释变量）
    2. add_insample_future_return_columns —— 样本内/外标记
    3. add_pairwise_past_return_columns —— 过去收益率窗口
    4. add_pairwise_past_rank_columns —— 对过去收益率做截面排名
    5. add_rank_volatility_columns —— 对排名计算标准差（排名波动率）
    6. add_fac_rank_volatility_columns —— 反向指标 FAC = 1 - rank_vol
    """
    # 先按基金代码和时间排序，确保 shift 操作对应正确的相邻月份
    result = data.sort_values(
        [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    ).reset_index(drop=True)

    # 按基金代码分组，后续所有 shift 操作都在同一基金内进行
    grouped = result.groupby(Config.COLUMN_IFIND_CODE, sort=False)

    # 转为月度 Period，用于后续校验起止端点是否恰好相差 horizon 个月
    current_period = result[Config.COLUMN_MONTH_DATE].dt.to_period("M")

    # --- 步骤 1：计算未来收益率 ---
    result = add_future_return_columns(
        result=result,
        grouped=grouped,
        current_period=current_period,
        return_type=return_type,
    )

    # --- 步骤 2：标记样本内/外 ---
    result = add_insample_future_return_columns(result)

    # --- 步骤 3：计算过去收益率窗口 ---
    result = add_pairwise_past_return_columns(
        result=result,
        grouped=grouped,
        current_period=current_period,
        return_type=return_type,
    )

    # --- 步骤 4：对过去收益率做截面排名 ---
    result = add_pairwise_past_rank_columns(result)

    # --- 步骤 5：计算排名波动率 ---
    result = add_rank_volatility_columns(result)

    # --- 步骤 6：计算排名波动率反向指标 ---
    result = add_fac_rank_volatility_columns(result)

    return result


def build_panel(source_files: list[Path], return_type: str) -> pd.DataFrame:
    """合并全部投资类型的筛选长表，并生成最终面板。

    步骤：
    1. 读取所有筛选长表并纵向拼接
    2. 检查是否有重复的基金-月份记录
    3. 调用 add_period_columns 计算所有衍生字段
    4. 按预定义的列顺序整理输出
    """
    # 读取并拼接所有投资类型的长表
    parts = [read_filter_table(source_path) for source_path in source_files]
    # 纵向拼接所有投资类型的长表，重置索引避免跨文件索引冲突
    data = pd.concat(parts, ignore_index=True)

    # 同一基金同一月份不应出现两条记录，若有则说明上游数据有问题
    duplicate_keys = data.duplicated(
        [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE], keep=False
    )
    if duplicate_keys.any():
        examples = data.loc[
            duplicate_keys, [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
        ].head(10)
        raise ValueError(
            "发现重复的基金-月份键：\n" + examples.to_string(index=False)
        )

    # 调用主计算流水线
    panel = add_period_columns(data, return_type)

    # 按固定列顺序输出，方便下游脚本按名称引用
    future_return_columns = get_future_return_columns()
    pairwise_past_columns = [
        *get_pairwise_past_return_columns(),    # 过去收益率
        *get_pairwise_past_match_columns(),     # match 标签
        *get_pairwise_past_rank_columns(),      # 截面排名
        *get_rank_volatility_columns(),         # 排名波动率
        *get_fac_rank_volatility_columns(),     # 排名波动率反向指标
    ]
    columns = [
        *Config.PANEL_BASE_OUTPUT_COLUMNS,      # 基础字段（代码、月份、净值等）
        *future_return_columns,                 # 未来收益率相关
        *pairwise_past_columns,                 # 过去收益率相关
    ]
    return panel[columns].sort_values(
        [Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]
    ).reset_index(drop=True)


def validate_panel(panel: pd.DataFrame, source_row_count: int) -> None:
    """保存前对面板进行全面校验。

    校验内容：
    1. 行数完整性：面板行数 == 源数据总行数（不多不少）
    2. 唯一性：无重复基金-月份键
    3. 未来收益率：match=True 时收益率不能为 NaN
    4. 过去收益率：match=True 时收益率不能为 NaN
    5. 排名范围：排名值必须在 [0, 1] 之间
    6. 排名样本：非样本行的排名必须为 NaN
    7. 排名波动率：不能出现负数
    8. FAC 指标：必须等于 1 - rank_vol
    9. 完整窗口约束：如果配置要求完整窗口，则不完整窗口的波动率必须为 NaN
    """
    # --- 校验 1：行数完整性 ---
    # 面板不应新增或丢失行，行数必须与原始长表总行数完全一致
    if len(panel) != source_row_count:
        raise AssertionError("面板行数与筛选长表总行数不一致。")

    # --- 校验 2：唯一性 ---
    # 再次确认没有重复键（build_panel 已检查一次，这里作为最终防线）
    if panel.duplicated([Config.COLUMN_IFIND_CODE, Config.COLUMN_MONTH_DATE]).any():
        raise AssertionError("面板中存在重复的基金-月份键。")

    # --- 校验 3-4：未来收益率的 match 标签和收益率一致性 ---
    for horizon in FUTURE_RETURN_HORIZONS:
        return_column = f"future_ret_{horizon}m"
        match_column = f"match_is_sample_future_ret_{horizon}m"
        insample_column = f"is_insample_future_ret_{horizon}m"

        # match 列必须是布尔类型
        if panel[match_column].dtype != bool:
            raise AssertionError(f"{match_column} 不是布尔类型。")
        # match=True 的行，收益率不能为空（如果 match 说窗口完整，收益率一定能算出来）
        if panel.loc[panel[match_column], return_column].isna().any():
            raise AssertionError(
                f"{match_column}=True 时出现缺失的 {return_column}。"
            )
        # insample 标记不能有空值
        if panel[insample_column].isna().any():
            raise AssertionError(f"{insample_column} 出现缺失值。")
        # insample 标记只能是 0 或 1
        if not panel[insample_column].isin([0, 1]).all():
            raise AssertionError(f"{insample_column} 出现 0/1 之外的值。")

    # --- 校验 5-6：过去收益率排名的有效性 ---
    for (return_horizon, pairwise), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            return_column = get_past_return_column(
                return_horizon, window_index, pairwise
            )
            match_column = get_past_match_column(
                return_horizon, window_index, pairwise
            )
            # match 列必须是布尔类型
            if panel[match_column].dtype != bool:
                raise AssertionError(f"{match_column} 不是布尔类型。")
            # match=True 时收益率不能为空
            if panel.loc[panel[match_column], return_column].isna().any():
                raise AssertionError(
                    f"{match_column}=True 时出现缺失的 {return_column}。"
                )
            # 排名值必须在 [0, 1] 之间
            rank_column = get_past_rank_column(
                return_horizon, window_index, pairwise
            )
            rank_values = panel[rank_column].dropna()
            if not rank_values.between(0, 1).all():
                raise AssertionError(f"{rank_column} 出现 0 到 1 之外的值。")
            # 非排名样本（不满足 is_sample & match & 收益率非空）的排名必须为 NaN
            rank_allowed = (
                panel[Config.COLUMN_IS_SAMPLE]
                & panel[match_column]
                & panel[return_column].notna()
            )
            if panel.loc[~rank_allowed, rank_column].notna().any():
                raise AssertionError(f"{rank_column} 在非排名样本中出现非缺失值。")

    # --- 校验 7-9：排名波动率和 FAC 指标 ---
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        rank_columns = [
            get_past_rank_column(return_horizon, window_index, pairwise)
            for window_index in range(1, rank_count + 1)
        ]
        volatility_column = get_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )
        fac_column = get_fac_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )

        # 排名波动率不能为负数（标准差 >= 0）
        volatility_values = panel[volatility_column].dropna()
        if (volatility_values < 0).any():
            raise AssertionError(f"{volatility_column} 出现负数。")

        # FAC 必须精确等于 1 - rank_vol
        expected_fac = 1 - panel[volatility_column]
        if not panel[fac_column].equals(expected_fac):
            raise AssertionError(f"{fac_column} 不等于 1 - {volatility_column}。")

        # 如果配置要求完整窗口，则不完整窗口的波动率必须为 NaN
        if Config.RANK_VOL_REQUIRE_FULL_WINDOW:
            full_window = panel[rank_columns].notna().all(axis=1)
            if panel.loc[~full_window, volatility_column].notna().any():
                raise AssertionError(
                    f"{volatility_column} 在 rank 窗口不完整时出现非缺失值。"
                )


def generate_panel(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    output_path: Path | None = None,
    return_type: str = Config.PANEL_RETURN_TYPE,
    spec_set: str = "baseline",
    write_preview: bool = True,
) -> dict[str, object]:
    """生成面板文件的主入口函数。

    完整流程：
    1. 查找源文件
    2. 统计源数据总行数（用于后续校验）
    3. 构建面板（调用 build_panel）
    4. 校验面板（调用 validate_panel）
    5. 保存 parquet 和可选的 Excel 预览
    6. 返回运行摘要字典
    """
    # 根据运行模式切换过去收益率规格。默认 baseline 完全沿用原有规格；
    # heatmap 则使用 m=1..12、n=1..12 的专用网格，并默认写入独立文件。
    set_past_return_specs(get_specs_for_spec_set(spec_set))
    if output_path is None:
        output_path = get_default_output_path(spec_set)

    if not source_dir.exists():
        raise FileNotFoundError(f"输入目录不存在：{source_dir}")

    source_files = find_source_files(source_dir)

    # 提前统计原始行数，用于 validate_panel 的完整性校验
    # 只读取单列以节省内存
    source_row_count = sum(
        len(pd.read_parquet(path, columns=[Config.COLUMN_IFIND_CODE]))
        for path in source_files
    )

    # 构建面板
    panel = build_panel(source_files, return_type)
    # 校验面板
    validate_panel(panel, source_row_count)

    # 保存输出
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(output_path, index=False)

    # Excel 预览只取前 1000 行，方便快速人工核查，不影响正式 parquet 输出
    preview_path = None
    if write_preview:
        preview_path = output_path.with_name(output_path.stem + "_preview.xlsx")
        panel.head(1000).to_excel(preview_path, index=False)

    # --- 统计各周期有效样本数量，用于打印摘要 ---
    future_match_counts = {}
    for horizon in FUTURE_RETURN_HORIZONS:
        future_match_counts[f"future_ret_{horizon}m"] = int(
            panel[f"match_is_sample_future_ret_{horizon}m"].sum()
        )
    pairwise_match_counts = {}
    pairwise_rank_counts = {}
    rank_volatility_counts = {}
    for (return_horizon, pairwise), rank_count in get_pairwise_past_return_windows().items():
        for window_index in range(1, rank_count + 1):
            key = get_past_return_column(return_horizon, window_index, pairwise)
            match_column = get_past_match_column(
                return_horizon, window_index, pairwise
            )
            rank_column = get_past_rank_column(
                return_horizon, window_index, pairwise
            )
            pairwise_match_counts[key] = int(
                panel[match_column].sum()
            )
            pairwise_rank_counts[key] = int(
                panel[rank_column].notna().sum()
            )
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        volatility_column = get_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )
        rank_volatility_counts[volatility_column] = int(
            panel[volatility_column].notna().sum()
        )

    return {
        "spec_set": spec_set,
        "return_type": return_type,
        "source_file_count": len(source_files),
        "row_count": len(panel),
        "output_path": output_path,
        "preview_path": preview_path,
        "future_match_counts": future_match_counts,
        "pairwise_match_counts": pairwise_match_counts,
        "pairwise_rank_counts": pairwise_rank_counts,
        "rank_volatility_counts": rank_volatility_counts,
    }


def print_panel_summary(summary: dict[str, object]) -> None:
    """打印面板生成摘要，展示各周期的有效样本数量。"""
    print(f"规格集合：{summary['spec_set']}")
    print(f"收益率类型：{summary['return_type']}")
    print(f"来源文件数：{summary['source_file_count']}")
    print(f"输出行数：{summary['row_count']:,}")
    print(f"输出路径：{summary['output_path']}")
    if summary["preview_path"] is not None:
        print(f"预览路径：{summary['preview_path']}")

    future_match_counts = summary["future_match_counts"]
    for horizon in FUTURE_RETURN_HORIZONS:
        print(
            f"未来 {horizon} 个月被解释变量匹配样本："
            f"{future_match_counts[f'future_ret_{horizon}m']:,}"
        )

    pairwise_match_counts = summary["pairwise_match_counts"]
    pairwise_rank_counts = summary["pairwise_rank_counts"]
    rank_volatility_counts = summary["rank_volatility_counts"]
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        spec = (return_horizon, rank_count, pairwise)
        print(f"过去收益率窗口规格 {spec}：")
        for window_index in range(1, rank_count + 1):
            key = get_past_return_column(return_horizon, window_index, pairwise)
            print(
                f"  {key} 匹配样本："
                f"{pairwise_match_counts[key]:,}；排名样本："
                f"{pairwise_rank_counts[key]:,}"
            )
        volatility_column = get_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )
        print(
            f"  {volatility_column} 非缺失样本："
            f"{rank_volatility_counts[volatility_column]:,}"
        )


def run_downstream_scripts() -> None:
    """运行基准面板的后续脚本。

    这些脚本默认读取 A_data/output/panel_base.parquet。热力图模式写入的是专用
    parquet，因此不自动运行它们，避免用户只想生成热力图面板时误触发默认流程。
    """
    import subprocess
    import sys

    scripts_dir = Path(__file__).parent
    for script in ("3_panel_base_controls_variable.py", "3_panel_base_grouping_factors.py"):
        script_path = scripts_dir / script
        print(f"\n{'=' * 60}")
        print(f"自动运行：{script_path}")
        print(f"{'=' * 60}\n")
        result = subprocess.run([sys.executable, str(script_path)])
        if result.returncode != 0:
            print(f"\n{script} 运行失败（returncode={result.returncode}），中止后续脚本。")
            sys.exit(result.returncode)


def main() -> argparse.Namespace:
    """命令行入口：解析参数 → 生成面板 → 打印摘要。"""
    args = parse_args()
    summary = generate_panel(
        source_dir=args.source_dir,
        output_path=args.output,
        return_type=args.return_type,
        spec_set=args.spec_set,
        write_preview=True,
    )
    print_panel_summary(summary)
    return args


if __name__ == "__main__":
    parsed_args = main()

    # 保持默认行为不变：无参数或显式 baseline 时，仍在生成基准 panel_base 后
    # 自动运行控制变量和分组因子脚本。heatmap 只产出专用 parquet。
    if parsed_args.spec_set == "baseline":
        run_downstream_scripts()
