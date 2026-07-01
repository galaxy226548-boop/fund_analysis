"""为 panel_base.parquet 追加排名均值分组因子。

默认读取并覆盖：

    A_data/output/panel_base.parquet
    A_data/output/panel_base_preview.xlsx

热力图模式默认读取并覆盖：

    A_data/output/panel_base_heatmap_m1_12_n1_12.parquet
    A_data/output/panel_base_heatmap_m1_12_n1_12_preview.xlsx

本脚本不会重新生成收益率、排名或控制变量，而是在已有 panel_base 的基础上，
对 Config.PANEL_PAST_RETURN_SPECS 中每个 (m, n, pairwise) 规格追加分组列。
项目统一约定 m 是单期收益期限，n 是排名期数。

- rank_mean_m{m}_n{n}_pairwise1：
  对 past_ret_{m}m_rank_1 到 past_ret_{m}m_rank_{n} 逐行取算术平均；
- is_top_half_rank_mean_m{m}_n{n}_pairwise1：
  在 month_date × investment_type 截面内，按排名均值从小到大计算百分位排名；
  前 30%（排名均值大）标记为 1，后 30%（排名均值小）标记为 -1，
  中间 40% 标记为 0。
- is_median_rank_mean_m{m}_n{n}_pairwise1：
  按排名均值的截面百分位切成二分组；上半组标记为 2，下半组标记为 -2。
- is_tercile_rank_mean_m{m}_n{n}_pairwise1：
  同样按排名均值的截面百分位切成三分组；前 1/3 标记为 3，
  中间 1/3 标记为 2，后 1/3 标记为 1。

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_grouping_factors.py
    .venv/bin/python A_data/scripts/3_panel_base_grouping_factors.py --no-preview
    .venv/bin/python A_data/scripts/3_panel_base_grouping_factors.py --spec-set heatmap --no-preview
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import Config


DEFAULT_INPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_OUTPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_HEATMAP_INPUT_PATH = Config.PANEL_HEATMAP_OUTPUT_PATH
DEFAULT_HEATMAP_OUTPUT_PATH = Config.PANEL_HEATMAP_OUTPUT_PATH
DEFAULT_PREVIEW_ROWS = 1000
PAST_RETURN_SPECS = Config.PANEL_PAST_RETURN_SPECS
INCLUDE_TOP_HALF_GROUPING = True
SPEC_SET_CHOICES = ("baseline", "heatmap")
BOTTOM_GROUP_CUTOFF = 0.30
TOP_GROUP_CUTOFF = 0.70
BOTTOM_TERCILE_CUTOFF = 1 / 3
TOP_TERCILE_CUTOFF = 2 / 3


def parse_args() -> argparse.Namespace:
    """读取命令行参数，默认覆盖 A_data/output 下的正式面板文件。"""
    # argparse 让同一个脚本既能默认覆盖正式文件，也能在调试时指定临时输入/输出。
    parser = argparse.ArgumentParser(description="为 panel_base 追加排名均值分组因子。")
    parser.add_argument(
        "--spec-set",
        choices=SPEC_SET_CHOICES,
        default="baseline",
        help=(
            "过去收益率规格集合：baseline 为原有 panel_base 规格；"
            "heatmap 为 m=1..12、n=1..12、pairwise=1 的热力图专用规格。"
        ),
    )
    # 输入路径默认就是 A_data/output/panel_base.parquet，方便接在上游面板流程后运行。
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            "输入 panel_base parquet 文件路径。未指定时，baseline 读取主面板，"
            "heatmap 读取热力图专用面板。"
        ),
    )
    # 输出路径也默认是正式 panel；如果担心覆盖，可以在命令行传入临时 parquet 路径。
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "输出 parquet 文件路径；未指定时写回对应模式的输入面板，"
            "heatmap 不会覆盖主 panel_base.parquet。"
        ),
    )
    # preview 只是人工快速检查用，不参与后续严肃计算，所以允许单独指定或关闭。
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Excel 预览输出路径；默认跟随 output 生成 *_preview.xlsx。",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=DEFAULT_PREVIEW_ROWS,
        help="Excel 预览保留的前若干行。",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="只更新 parquet，不更新 Excel 预览。",
    )
    return parser.parse_args()


def get_specs_for_spec_set(spec_set: str) -> tuple[tuple[int, int, int], ...]:
    """按运行模式返回过去收益率规格。

    baseline 使用现有面板的原规格；heatmap 使用 1..12 的完整网格。把选择集中在
    一个函数里，后续读列、计算、校验都能共享同一套规格，避免某一步漏切换。
    """
    if spec_set == "baseline":
        return Config.PANEL_PAST_RETURN_SPECS
    if spec_set == "heatmap":
        return Config.PANEL_HEATMAP_PAST_RETURN_SPECS
    raise ValueError(f"未知规格集合：{spec_set}")


def get_default_input_path(spec_set: str) -> Path:
    """按运行模式返回默认输入路径。"""
    if spec_set == "baseline":
        return DEFAULT_INPUT_PATH
    if spec_set == "heatmap":
        return DEFAULT_HEATMAP_INPUT_PATH
    raise ValueError(f"未知规格集合：{spec_set}")


def get_default_output_path(spec_set: str) -> Path:
    """按运行模式返回默认输出路径，确保 heatmap 不覆盖主 panel。"""
    if spec_set == "baseline":
        return DEFAULT_OUTPUT_PATH
    if spec_set == "heatmap":
        return DEFAULT_HEATMAP_OUTPUT_PATH
    raise ValueError(f"未知规格集合：{spec_set}")


def set_grouping_factor_mode(spec_set: str) -> None:
    """切换当前运行使用的规格和列集合。

    baseline 保持脚本原有行为；heatmap 只维护 rank_mean、median、tercile 三类
    用户明确需要的列，方便对 144 个 (m,n) 网格做列数核对。
    """
    global PAST_RETURN_SPECS, INCLUDE_TOP_HALF_GROUPING
    PAST_RETURN_SPECS = get_specs_for_spec_set(spec_set)
    INCLUDE_TOP_HALF_GROUPING = spec_set == "baseline"


def get_rank_mean_column(
    rank_count: int,
    return_horizon: int,
    pairwise: int = Config.PANEL_PAIRWISE,
) -> str:
    """返回指定 (m, n) 组合的排名均值列名。"""
    # 所有新增变量都带上 m、n 和 pairwise 步长，避免不同参数组合的列名混在一起。
    return (
        f"rank_mean_m{return_horizon}_n{rank_count}_"
        f"pairwise{pairwise}"
    )


def get_top_half_column(
    rank_count: int,
    return_horizon: int,
    pairwise: int = Config.PANEL_PAIRWISE,
) -> str:
    """返回指定 (m, n) 组合的高低组标记列名。"""
    # 保留历史列名，避免下游脚本因为字段改名而失效；实际取值已扩展为 -1/0/1 三档。
    return f"is_top_half_{get_rank_mean_column(rank_count, return_horizon, pairwise)}"


def get_median_split_column(
    rank_count: int,
    return_horizon: int,
    pairwise: int = Config.PANEL_PAIRWISE,
) -> str:
    """返回指定 (m, n) 组合的中位数二分列名，取值 -2/2。"""
    return f"is_median_{get_rank_mean_column(rank_count, return_horizon, pairwise)}"


def get_tercile_split_column(
    rank_count: int,
    return_horizon: int,
    pairwise: int = Config.PANEL_PAIRWISE,
) -> str:
    """返回指定 (m, n) 组合的三分组列名，取值 1/2/3。"""
    return f"is_tercile_{get_rank_mean_column(rank_count, return_horizon, pairwise)}"


def get_fac_rank_volatility_column(
    rank_count: int,
    return_horizon: int,
    pairwise: int = Config.PANEL_PAIRWISE,
) -> str:
    """返回已有 FAC_rank_vol 列名，用于定位新增字段应插入的位置。"""
    # 这里不重新计算 FAC_rank_vol，只用同样的命名规则找到已有列。
    return (
        f"FAC_rank_vol_m{return_horizon}_n{rank_count}_"
        f"pairwise{pairwise}"
    )


def get_rank_columns(
    rank_count: int,
    return_horizon: int,
    pairwise: int = Config.PANEL_PAIRWISE,
) -> list[str]:
    """列出某个 (m, n) 组合对应的 m 个截面百分位排名列。"""
    # rank_count=n，所以窗口序号从 1 到 n；return_horizon=m，体现在 past_ret_{m}m。
    columns = []
    for window_index in range(1, rank_count + 1):
        base = f"past_ret_{return_horizon}m_rank_{window_index}"
        columns.append(base if pairwise == 1 else f"{base}_pairwise{pairwise}")
    return columns


def get_added_columns() -> list[str]:
    """列出本脚本负责维护的全部新增列，便于重复运行前先清理旧结果。"""
    columns: list[str] = []
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        columns.extend(
            [
                get_rank_mean_column(rank_count, return_horizon, pairwise),
                get_median_split_column(rank_count, return_horizon, pairwise),
                get_tercile_split_column(rank_count, return_horizon, pairwise),
            ]
        )
        if INCLUDE_TOP_HALF_GROUPING:
            # baseline 继续维护历史 top_half 列；heatmap 模式只生成用户需要的三类列。
            columns.insert(
                len(columns) - 2,
                get_top_half_column(rank_count, return_horizon, pairwise),
            )
    return columns


def get_default_preview_path(output_path: Path) -> Path:
    """根据 parquet 输出路径推导 Excel 预览路径。"""
    # 与上游脚本保持命名习惯：panel_base.parquet -> panel_base_preview.xlsx。
    return output_path.with_name(output_path.stem + "_preview.xlsx")


def require_columns(data: pd.DataFrame, input_path: Path) -> None:
    """检查计算排名均值和高低组所需字段是否齐全。"""
    # month_date 和 investment_type 是截面分组键，没有它们就无法在同类基金内做百分位分组。
    required_columns = [
        Config.COLUMN_MONTH_DATE,
        Config.COLUMN_INVESTMENT_TYPE,
    ]
    # 每个 (m, n) 组合都需要 n 个排名列，还需要对应的 FAC_rank_vol 列来确定插入位置。
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        required_columns.extend(
            get_rank_columns(rank_count, return_horizon, pairwise)
        )
        required_columns.append(
            get_fac_rank_volatility_column(rank_count, return_horizon, pairwise)
        )

    # 先集中报出所有缺失字段，比让 pandas 在后面某一行报 KeyError 更容易定位问题。
    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{input_path} 缺少字段：{missing}；请先确认上游 panel_base 已生成完整排名和 FAC_rank_vol 列。"
        )


def read_panel(input_path: Path) -> pd.DataFrame:
    """读取 panel_base，并统一关键列类型。"""
    # 明确检查文件是否存在，避免 read_parquet 抛出较难读懂的底层错误。
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")

    # copy 一份再改类型，避免后续修改时触发 pandas 的视图/副本警告。
    data = pd.read_parquet(input_path).copy()
    # 读取后立刻检查字段齐全性，失败时还没有开始写出文件，比较安全。
    require_columns(data, input_path)

    # month_date 必须能分组；如果日期解析失败，截面百分位分组就会被错误计算。
    data[Config.COLUMN_MONTH_DATE] = pd.to_datetime(
        data[Config.COLUMN_MONTH_DATE], errors="coerce"
    )
    if data[Config.COLUMN_MONTH_DATE].isna().any():
        raise ValueError(f"{input_path} 中存在无法识别的 month_date。")

    # 排名列理论上已经是数值型；这里再显式转换一次，避免 Excel/CSV 中转后的对象类型干扰均值。
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        for column in get_rank_columns(rank_count, return_horizon, pairwise):
            data[column] = pd.to_numeric(data[column], errors="coerce")

    return data


def add_rank_mean_and_group_columns(data: pd.DataFrame) -> pd.DataFrame:
    """计算排名均值列和高低组标记列。"""
    # 先删除旧结果，保证脚本重复运行时不会出现旧列残留或顺序错位。
    result = data.drop(columns=get_added_columns(), errors="ignore").copy()
    # 高低组是在“同一个月份、同一个投资类型”的基金之间比较，所以这里定义截面分组键。
    group_columns = [Config.COLUMN_MONTH_DATE, Config.COLUMN_INVESTMENT_TYPE]
    # heatmap 模式一次会新增 432 列。先把所有新列存在字典里，最后统一 concat，
    # 可以避免 pandas 因循环逐列插入而产生大量碎片化性能警告。
    new_columns: dict[str, pd.Series] = {}

    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        # 先把本组合涉及的列名都算出来，后面计算和校验都复用这些变量，减少手写列名出错。
        rank_columns = get_rank_columns(rank_count, return_horizon, pairwise)
        rank_mean_column = get_rank_mean_column(
            rank_count, return_horizon, pairwise
        )
        # ranks 是一个只包含 n 个排名列的小表；n 表示排名期数，
        # 后续横向 mean/notna 都针对这 n 列执行。
        ranks = result[rank_columns]

        if Config.RANK_VOL_REQUIRE_FULL_WINDOW:
            # 与 rank_vol 保持一致：严格模式下，n 个排名必须全部非空才计算均值。
            full_window = ranks.notna().all(axis=1)
            # 先把整列设成 NaN，再只给完整窗口填值，这样不完整窗口天然保持缺失。
            rank_mean_values = pd.Series(np.nan, index=result.index, dtype="float64")
            rank_mean_values.loc[full_window] = ranks.loc[full_window].mean(axis=1)
        else:
            # 宽松模式下沿用 pandas 的 skipna 均值；只有 n 个排名全缺失时结果才是 NaN。
            rank_mean_values = ranks.mean(axis=1, skipna=True)
        new_columns[rank_mean_column] = rank_mean_values

        non_missing_rank_mean = rank_mean_values.notna()
        # 在每个截面内重新把 rank_mean 排成百分位：数值越大，百分位越高。
        # pct=True 得到 0 到 1 之间的相对位置；用 method="average" 可以让并列值拿到同一个平均名次，
        # 避免同分基金被硬拆到不同组。大于 70% 是前 30%，小于等于 30% 是后 30%。
        cross_section_rank_pct = rank_mean_values.groupby(
            [result[column] for column in group_columns], sort=False
        ).rank(method="average", pct=True)
        if INCLUDE_TOP_HALF_GROUPING:
            top_half_column = get_top_half_column(
                rank_count, return_horizon, pairwise
            )
            top_half_values = pd.Series(np.nan, index=result.index, dtype="float64")
            # 只给排名均值非缺失的行打 -1/0/1；排名均值是 NaN 的行，分组标记也必须保持 NaN。
            top_half_values.loc[non_missing_rank_mean] = 0
            top_half_values.loc[
                non_missing_rank_mean
                & (cross_section_rank_pct <= BOTTOM_GROUP_CUTOFF)
            ] = -1
            top_half_values.loc[
                non_missing_rank_mean
                & (cross_section_rank_pct > TOP_GROUP_CUTOFF)
            ] = 1
            new_columns[top_half_column] = top_half_values

        median_column = get_median_split_column(
            rank_count, return_horizon, pairwise
        )
        median_values = pd.Series(np.nan, index=result.index, dtype="float64")
        median_values.loc[non_missing_rank_mean & (cross_section_rank_pct <= 0.5)] = -2
        median_values.loc[non_missing_rank_mean & (cross_section_rank_pct > 0.5)] = 2
        new_columns[median_column] = median_values

        tercile_column = get_tercile_split_column(
            rank_count, return_horizon, pairwise
        )
        tercile_values = pd.Series(np.nan, index=result.index, dtype="float64")
        # 三分组沿用同一套截面百分位排名：排名均值越大，组号越高。
        # 这里先把非缺失样本放入中间组，再覆盖底部和顶部，边界规则清晰且便于校验。
        tercile_values.loc[non_missing_rank_mean] = 2
        tercile_values.loc[
            non_missing_rank_mean & (cross_section_rank_pct <= BOTTOM_TERCILE_CUTOFF)
        ] = 1
        tercile_values.loc[
            non_missing_rank_mean & (cross_section_rank_pct > TOP_TERCILE_CUTOFF)
        ] = 3
        new_columns[tercile_column] = tercile_values

    return pd.concat([result, pd.DataFrame(new_columns, index=result.index)], axis=1)


def order_columns_after_fac_rank_vol(data: pd.DataFrame) -> pd.DataFrame:
    """把每组新增列放在对应 FAC_rank_vol 列之后，同时保留其他列原顺序。"""
    # 用 set 做成员判断更快；这里仅用于跳过“临时出现在表尾”的新增列。
    added_column_set = set(get_added_columns())
    ordered_columns: list[str] = []

    # 从左到右扫描现有字段：普通字段原样保留，遇到 FAC_rank_vol 就插入对应的两列。
    for column in data.columns:
        if column in added_column_set:
            # 新增列统一由对应的 FAC_rank_vol 位置插入，避免在原位置重复加入。
            continue
        ordered_columns.append(column)

        # 规格数量很少，直接循环匹配最直观，也方便以后增加组合。
        for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
            fac_column = get_fac_rank_volatility_column(
                rank_count, return_horizon, pairwise
            )
            if column == fac_column:
                added_after_fac = [
                    get_rank_mean_column(rank_count, return_horizon, pairwise),
                    get_median_split_column(rank_count, return_horizon, pairwise),
                    get_tercile_split_column(rank_count, return_horizon, pairwise),
                ]
                if INCLUDE_TOP_HALF_GROUPING:
                    added_after_fac.insert(
                        1, get_top_half_column(rank_count, return_horizon, pairwise)
                    )
                ordered_columns.extend(added_after_fac)

    return data[ordered_columns]


def validate_grouping_factors(original: pd.DataFrame, result: pd.DataFrame) -> None:
    """保存前校验行数、列顺序和核心计算口径。"""
    # 本脚本只追加/刷新列，不应该增加或删除任何基金-月份观测。
    if len(result) != len(original):
        raise AssertionError("追加排名均值分组因子后行数发生变化。")

    # 如果结果前缀仍然完全等于原始列，说明新增列大概率只是被加在表尾，没有插到 FAC 后面。
    original_without_added = original.drop(columns=get_added_columns(), errors="ignore")
    if list(result.columns)[: len(original_without_added.columns)] == list(
        original_without_added.columns
    ):
        raise AssertionError("新增列没有插入到 FAC_rank_vol 后面，请检查列顺序逻辑。")

    # 校验高低组时也必须按同样的截面定义计算百分位排名。
    group_columns = [Config.COLUMN_MONTH_DATE, Config.COLUMN_INVESTMENT_TYPE]
    for return_horizon, rank_count, pairwise in PAST_RETURN_SPECS:
        # 为当前组合准备所有要检查的列名，避免下面的校验逻辑混到其他组合。
        rank_columns = get_rank_columns(rank_count, return_horizon, pairwise)
        rank_mean_column = get_rank_mean_column(
            rank_count, return_horizon, pairwise
        )
        fac_column = get_fac_rank_volatility_column(
            rank_count, return_horizon, pairwise
        )

        median_column = get_median_split_column(
            rank_count, return_horizon, pairwise
        )
        tercile_column = get_tercile_split_column(
            rank_count, return_horizon, pairwise
        )

        fac_index = list(result.columns).index(fac_column)
        expected_after_fac = [
            rank_mean_column,
            median_column,
            tercile_column,
        ]
        if INCLUDE_TOP_HALF_GROUPING:
            top_half_column = get_top_half_column(
                rank_count, return_horizon, pairwise
            )
            expected_after_fac.insert(1, top_half_column)
        actual_after_fac = list(
            result.columns[fac_index + 1 : fac_index + 1 + len(expected_after_fac)]
        )
        if actual_after_fac != expected_after_fac:
            raise AssertionError(
                f"{fac_column} 后的字段顺序不正确：{actual_after_fac}，预期：{expected_after_fac}"
            )

        ranks = result[rank_columns]
        if Config.RANK_VOL_REQUIRE_FULL_WINDOW:
            # 严格模式：只要 m 个排名里有任何一个缺失，rank_mean 就必须缺失。
            full_window = ranks.notna().all(axis=1)
            if result.loc[~full_window, rank_mean_column].notna().any():
                raise AssertionError(
                    f"{rank_mean_column} 在 rank 窗口不完整时出现非缺失值。"
                )
            # 对完整窗口重新算一遍横向均值，确认写入结果不是错列或旧结果。
            expected_mean = ranks.loc[full_window].mean(axis=1)
            if not np.allclose(
                result.loc[full_window, rank_mean_column],
                expected_mean,
                equal_nan=True,
            ):
                raise AssertionError(f"{rank_mean_column} 与排名列算术平均不一致。")
        else:
            # 宽松模式：允许部分排名缺失，用 pandas 默认的 skipna 口径重算均值做对照。
            expected_mean = ranks.mean(axis=1, skipna=True)
            if not np.allclose(result[rank_mean_column], expected_mean, equal_nan=True):
                raise AssertionError(f"{rank_mean_column} 与排名列算术平均不一致。")

        # 排名均值缺失的行不应被强行分组，否则会污染后续分组统计。
        missing_rank_mean = result[rank_mean_column].isna()
        # 只在 rank_mean 非缺失的行比较标记；NaN 行已经在上面单独检查。
        valid_group = result[rank_mean_column].notna()
        # 校验逻辑和生成逻辑保持一致：每个截面按 rank_mean 做百分位排名。
        rank_pct = result.groupby(group_columns, sort=False)[rank_mean_column].rank(
            method="average", pct=True
        )
        if INCLUDE_TOP_HALF_GROUPING:
            top_half_column = get_top_half_column(
                rank_count, return_horizon, pairwise
            )
            if result.loc[missing_rank_mean, top_half_column].notna().any():
                raise AssertionError(f"{top_half_column} 在排名均值缺失时出现非缺失值。")
            # baseline 的历史 top_half 列按后 30% / 中 40% / 前 30% 生成。
            expected_group = pd.Series(0.0, index=result.index)
            expected_group.loc[valid_group & (rank_pct <= BOTTOM_GROUP_CUTOFF)] = -1.0
            expected_group.loc[valid_group & (rank_pct > TOP_GROUP_CUTOFF)] = 1.0
            if not result.loc[valid_group, top_half_column].astype("float64").equals(
                expected_group.loc[valid_group]
            ):
                raise AssertionError(f"{top_half_column} 与截面 30%/40%/30% 分组规则不一致。")

        if result.loc[missing_rank_mean, median_column].notna().any():
            raise AssertionError(f"{median_column} 在排名均值缺失时出现非缺失值。")
        expected_median = pd.Series(np.nan, index=result.index)
        expected_median.loc[valid_group & (rank_pct <= 0.5)] = -2.0
        expected_median.loc[valid_group & (rank_pct > 0.5)] = 2.0
        if not result.loc[valid_group, median_column].astype("float64").equals(
            expected_median.loc[valid_group]
        ):
            raise AssertionError(f"{median_column} 与截面 50%/50% 分组规则不一致。")

        if result.loc[missing_rank_mean, tercile_column].notna().any():
            raise AssertionError(f"{tercile_column} 在排名均值缺失时出现非缺失值。")
        expected_tercile = pd.Series(np.nan, index=result.index)
        expected_tercile.loc[valid_group] = 2.0
        expected_tercile.loc[
            valid_group & (rank_pct <= BOTTOM_TERCILE_CUTOFF)
        ] = 1.0
        expected_tercile.loc[
            valid_group & (rank_pct > TOP_TERCILE_CUTOFF)
        ] = 3.0
        if not result.loc[valid_group, tercile_column].astype("float64").equals(
            expected_tercile.loc[valid_group]
        ):
            raise AssertionError(f"{tercile_column} 与截面 1/3 分组规则不一致。")


def generate_grouping_factors(
    input_path: Path | None = None,
    output_path: Path | None = None,
    preview_path: Path | None = None,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
    write_preview: bool = True,
    spec_set: str = "baseline",
) -> dict[str, object]:
    """生成排名均值分组因子并写出 parquet / preview。"""
    # 先切换模式，再解析默认输入/输出路径；否则 heatmap 会误用主 panel_base。
    set_grouping_factor_mode(spec_set)
    if input_path is None:
        input_path = get_default_input_path(spec_set)
    if output_path is None:
        output_path = get_default_output_path(spec_set)

    # 1. 读取现有 panel，并把分组键和排名列转换成稳定可计算的类型。
    original = read_panel(input_path)
    # 2. 计算本脚本新增的 rank_mean 和分组列。
    with_grouping_factors = add_rank_mean_and_group_columns(original)
    # 3. 调整列顺序，让每组新增列紧跟在对应 FAC_rank_vol 后面。
    result = order_columns_after_fac_rank_vol(with_grouping_factors)
    # 4. 写文件之前做完整校验，尽量把错误拦在覆盖正式文件之前。
    validate_grouping_factors(original, result)

    # 5. 写出正式 parquet；默认路径会覆盖 A_data/output/panel_base.parquet。
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)

    # 6. 可选写出 Excel preview，方便打开前 1000 行人工检查新增列是否在正确位置。
    actual_preview_path = None
    if write_preview:
        actual_preview_path = preview_path or get_default_preview_path(output_path)
        actual_preview_path.parent.mkdir(parents=True, exist_ok=True)
        result.head(preview_rows).to_excel(actual_preview_path, index=False)

    # 7. 汇总新增列的非缺失数量，用于终端输出和后续快速核对。
    added_columns = get_added_columns()
    return {
        "spec_set": spec_set,
        "input_path": input_path,
        "output_path": output_path,
        "preview_path": actual_preview_path,
        "row_count": len(result),
        "column_count": len(result.columns),
        "added_columns": added_columns,
        "non_null_counts": {
            column: int(result[column].notna().sum()) for column in added_columns
        },
    }


def print_summary(summary: dict[str, object]) -> None:
    """打印运行摘要，方便快速核对新增字段。"""
    # 先打印路径，用户可以确认本次到底覆盖了哪个 parquet 和 preview。
    print(f"规格集合：{summary['spec_set']}")
    print(f"输入路径：{summary['input_path']}")
    print(f"输出路径：{summary['output_path']}")
    if summary["preview_path"] is not None:
        print(f"预览路径：{summary['preview_path']}")
    # 行列数是最直接的完整性信号：行数不该变，列数应随规格集合稳定增加。
    print(f"输出行数：{summary['row_count']:,}")
    print(f"输出列数：{summary['column_count']:,}")
    print("新增字段：")
    non_null_counts = summary["non_null_counts"]
    # 逐列打印非缺失数量，便于发现某个组合因为上游排名缺失而异常全空。
    for column in summary["added_columns"]:
        print(f"  {column}：非缺失/有效行数 {non_null_counts[column]:,}")


def main() -> None:
    """命令行入口。"""
    # main 保持很薄：只负责解析参数、调用主流程、打印摘要，方便以后在测试中直接调用函数。
    args = parse_args()
    summary = generate_grouping_factors(
        input_path=args.input,
        output_path=args.output,
        preview_path=args.preview,
        preview_rows=args.preview_rows,
        write_preview=not args.no_preview,
        spec_set=args.spec_set,
    )
    print_summary(summary)


if __name__ == "__main__":
    main()
