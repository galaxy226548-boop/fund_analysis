"""按投资类型批量筛选基金经理团队稳定满 12 个月后的净值样本。

这个脚本会自动寻找两组文件：

1. iFind 净值文件
   A_data/data/iFind_API/iFind{投资类型}净值变化.xlsx

2. Wind 历任经理文件
   A_data/data/Wind_terminal_fund_center/Wind{投资类型}历任经理.xlsx
   或项目中目前实际使用的：
   A_data/data/Wind_terminal_fund_center/Wind{投资类型}历任基金经理.xlsx

文件名中间的“投资类型”必须完全相同。例如：

    iFind普通股票型基金净值变化.xlsx
    Wind普通股票型基金历任基金经理.xlsx

会配成一组，最终输出：

    A_data/output/fund_managers/普通股票型基金净值筛选长表.parquet

脚本只输出 Parquet 文件，不再输出任期、regime 或筛选结果 Excel。
Parquet 会保留原净值长表中的所有有效净值行，不满足条件的行不会被删除，
而是在 is_in_manager_regime 列中标记为 False。

筛选规则：

1. 只要基金经理加入或离开，基金经理团队就发生变化，产生一个新 regime。
2. 一位经理在 end_date 当日仍被视为在任，从次日开始退出团队。
3. 净值日当天，一个 regime 必须已经稳定满 12 个月。
4. 净值日当天仍然处于该 regime，即 month_date 不晚于 regime_end。
5. “至今”的经理使用对应净值文件中的最大 month_date 作为临时结束日。
6. 净值原表中的 0 默认视为无效占位值；可用 --keep-zero-nav 保留。

运行方式：

    python A_data/scripts/2_fund_managers.py

如需查看命令行选项：

    python A_data/scripts/2_fund_managers.py --help
"""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 兼容 Wind Excel 的样式问题
# ---------------------------------------------------------------------------
#
# 项目中的部分 Wind 工作簿含有 name=None 的 Excel 命名样式。
# openpyxl 正常情况下要求样式名称必须是字符串，因此直接读取会报错。
# 下面的小补丁把 None 转成空字符串，只影响读取样式，不会修改原始 Excel。
import openpyxl.styles.named_styles as _named_styles

_ORIGINAL_NAMED_STYLE_INIT = _named_styles._NamedCellStyle.__init__


def _patched_named_style_init(self, name=None, **kwargs):
    """让 openpyxl 可以读取样式名称为空的 Wind 工作簿。"""
    _ORIGINAL_NAMED_STYLE_INIT(self, name="" if name is None else name, **kwargs)


_named_styles._NamedCellStyle.__init__ = _patched_named_style_init


# ---------------------------------------------------------------------------
# 默认路径
# ---------------------------------------------------------------------------

# __file__ 是本脚本自己的路径。
# parents[2] 会从 A_data/scripts/2_fund_managers.py 向上两层，得到项目根目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
A_DATA_ROOT = PROJECT_ROOT / "A_data"

DEFAULT_REGISTRY_PATH = A_DATA_ROOT / "data" / "fund_registry.xlsx"
DEFAULT_NAV_DIR = A_DATA_ROOT / "data" / "iFind_API"
DEFAULT_MANAGER_DIR = A_DATA_ROOT / "data" / "Wind_terminal_fund_center"
DEFAULT_OUTPUT_DIR = A_DATA_ROOT / "output" / "fund_managers"


# 这个正则表达式用来拆解类似下面的文字：
#
#     张琦(20130528-20160727)
#     张露(20170811至今)
#
# 拆解后会得到 manager、start 和 end 三部分。
MANAGER_PATTERN = re.compile(
    r"(?P<manager>[^()（）\r\n]+?)\s*[（(]\s*"
    r"(?P<start>\d{8})\s*(?:-|—|至)\s*(?P<end>\d{8}|今)\s*[）)]"
)


# 如果将来 fund_registry 增加基金成立日，脚本会自动识别下面任意一种列名。
INCEPTION_COLUMN_CANDIDATES = (
    "fund_inception_date",
    "基金成立日",
    "基金成立日期",
    "成立日",
    "成立日期",
)

# fund_registry 的基金名称列在不同版本中使用过“基金名称”和“证券名称”。
# 脚本按顺序寻找，找到其中一个就可以继续运行。
FUND_NAME_COLUMN_CANDIDATES = ("基金名称", "证券名称")


def parse_args() -> argparse.Namespace:
    """读取用户在命令行中传入的选项。"""
    parser = argparse.ArgumentParser(
        description="批量生成各投资类型的基金经理稳定满 12 个月净值样本。"
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="基金代码映射表，默认使用 A_data/data/fund_registry.xlsx。",
    )
    parser.add_argument(
        "--nav-dir",
        type=Path,
        default=DEFAULT_NAV_DIR,
        help="iFind 净值变化 Excel 所在目录。",
    )
    parser.add_argument(
        "--manager-dir",
        type=Path,
        default=DEFAULT_MANAGER_DIR,
        help="Wind 历任基金经理 Excel 所在目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="筛选后 Parquet 文件的输出目录。",
    )
    parser.add_argument(
        "--keep-zero-nav",
        action="store_true",
        help="保留净值为 0 的单元格；默认把 0 当作无效占位值。",
    )
    return parser.parse_args()


def require_columns(data: pd.DataFrame, columns: Iterable[str], source: Path) -> None:
    """检查表格是否包含程序需要的列，缺列时给出容易理解的错误。"""
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source} 缺少字段：{missing}；实际字段为：{list(data.columns)}"
        )


def clean_headers(columns: Iterable[object]) -> list[str]:
    """清理列名中的排序箭头和首尾空格。"""
    return [str(column).replace("↑", "").replace("↓", "").strip() for column in columns]


def normalize_code(value: object) -> str | None:
    """把不同 Excel 格式的基金代码统一成可匹配的字符串。

    例如 Excel 可能把 000082 读取成数字 82.0，本函数会把它恢复成
    6 位字符串 000082。带后缀的 000082.OF 则会保留后缀并转成大写。
    """
    if pd.isna(value):
        return None

    if isinstance(value, (int, np.integer)):
        return f"{int(value):06d}"

    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return None
        if float(value).is_integer():
            return f"{int(value):06d}"

    code = str(value).strip().upper().replace(" ", "")
    if not code or code in {"NAN", "NONE", "NAT"} or "数据来源" in code:
        return None
    if re.fullmatch(r"\d+\.0", code):
        return code[:-2].zfill(6)
    if re.fullmatch(r"\d+", code):
        return code.zfill(6)
    return code


def parse_excel_date(value: object) -> pd.Timestamp:
    """把 Excel 中可能出现的多种日期格式统一成 pandas 日期。

    支持：
    - Excel 已经识别的 datetime；
    - 20170811 这种 YYYYMMDD 格式；
    - 2017-08-11 这种普通日期字符串；
    - 42800 这种 Excel serial number。
    """
    if value is None or pd.isna(value):
        return pd.NaT

    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).normalize()

    # Python datetime/date 对象都有 year、month、day 属性。
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return pd.Timestamp(value).normalize()

    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if np.isnan(number):
            return pd.NaT

        integer_text = str(int(number))
        if number.is_integer() and len(integer_text) == 8:
            parsed = pd.to_datetime(integer_text, format="%Y%m%d", errors="coerce")
        else:
            # Excel 日期序号以 1899-12-30 为常用转换起点。
            parsed = pd.to_datetime(
                number, unit="D", origin="1899-12-30", errors="coerce"
            )
        return pd.Timestamp(parsed).normalize() if not pd.isna(parsed) else pd.NaT

    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        parsed = pd.to_datetime(text, format="%Y%m%d", errors="coerce")
    else:
        parsed = pd.to_datetime(text, errors="coerce")
    return pd.Timestamp(parsed).normalize() if not pd.isna(parsed) else pd.NaT


def investment_type_from_nav_path(nav_path: Path) -> str:
    """从 iFind{投资类型}净值变化.xlsx 中取出“投资类型”。"""
    prefix = "iFind"
    suffix = "净值变化"
    stem = nav_path.stem

    if not stem.startswith(prefix) or not stem.endswith(suffix):
        raise ValueError(f"净值文件名不符合 iFind{{投资类型}}净值变化.xlsx：{nav_path.name}")

    investment_type = stem[len(prefix) : -len(suffix)].strip()
    if not investment_type:
        raise ValueError(f"净值文件名中没有投资类型：{nav_path.name}")
    return investment_type


def discover_input_pairs(nav_dir: Path, manager_dir: Path) -> list[tuple[str, Path, Path]]:
    """自动寻找全部净值文件，并为每个文件找到同类型的经理文件。

    返回值中的每一项都是：

        (投资类型, iFind净值路径, Wind经理路径)
    """
    nav_paths = sorted(nav_dir.glob("iFind*净值变化.xlsx"))
    if not nav_paths:
        raise FileNotFoundError(f"{nav_dir} 中没有找到 iFind*净值变化.xlsx。")

    pairs: list[tuple[str, Path, Path]] = []
    missing_manager_files: list[str] = []

    for nav_path in nav_paths:
        investment_type = investment_type_from_nav_path(nav_path)

        # 同时兼容用户描述的“历任经理”和现有文件的“历任基金经理”。
        possible_manager_paths = [
            manager_dir / f"Wind{investment_type}历任经理.xlsx",
            manager_dir / f"Wind{investment_type}历任基金经理.xlsx",
        ]
        existing_paths = [path for path in possible_manager_paths if path.exists()]

        if not existing_paths:
            expected = " 或 ".join(path.name for path in possible_manager_paths)
            missing_manager_files.append(f"{nav_path.name} -> {expected}")
            continue

        if len(existing_paths) > 1:
            raise ValueError(
                f"投资类型“{investment_type}”同时存在两份经理文件：{existing_paths}。"
                "请保留其中一份，避免程序无法判断应该使用哪份。"
            )

        pairs.append((investment_type, nav_path, existing_paths[0]))

    if missing_manager_files:
        raise FileNotFoundError(
            "以下净值文件没有找到同投资类型的 Wind 历任经理文件：\n"
            + "\n".join(missing_manager_files)
        )
    return pairs


def read_nav_long(
    nav_path: Path, keep_zero_nav: bool
) -> tuple[pd.DataFrame, pd.Timestamp, set[str]]:
    """把 iFind 净值宽表转换成长表。

    宽表是一行一只基金、每个月一个日期列；长表是一行一个基金月份。
    例如原来 100 只基金、120 个月，转换后最多会有 12,000 行。
    """
    wide = pd.read_excel(nav_path, sheet_name="month")
    if wide.empty or len(wide.columns) < 2:
        raise ValueError(f"{nav_path} 的 month sheet 没有可用净值数据。")

    # 第一列按业务定义就是证券代码。这里统一列名，避免导出软件附加空格。
    wide.columns = ["证券代码", *wide.columns[1:]]
    raw_date_columns = list(wide.columns[1:])
    normalized_codes = wide["证券代码"].map(normalize_code)

    # 删除底部“数据来源”等说明行，以及没有代码的空行。
    valid_code_rows = normalized_codes.notna()
    wide = wide.loc[valid_code_rows, raw_date_columns].copy()
    wide.insert(0, "ifind_code", normalized_codes.loc[valid_code_rows].to_numpy())
    original_codes = set(wide["ifind_code"].unique())
    date_mapping = {column: parse_excel_date(column) for column in raw_date_columns}
    invalid_date_columns = [
        column for column, parsed_date in date_mapping.items() if pd.isna(parsed_date)
    ]
    if invalid_date_columns:
        raise ValueError(
            f"{nav_path.name} 含无法识别的日期列：{invalid_date_columns[:10]}"
        )

    # melt 是 pandas 中“宽表转长表”的标准方法。
    long = wide[["ifind_code", *raw_date_columns]].melt(
        id_vars="ifind_code",
        value_vars=raw_date_columns,
        var_name="source_month_date",
        value_name="nav_value",
    )
    long["month_date"] = long["source_month_date"].map(date_mapping)
    long["nav_value"] = pd.to_numeric(long["nav_value"], errors="coerce")
    long = long.dropna(subset=["month_date", "nav_value"])

    # 项目中的 iFind 文件使用 0 表示该月没有有效净值，而不是真实净值为 0。
    if not keep_zero_nav:
        long = long[long["nav_value"] != 0]

    long = (
        long[["ifind_code", "month_date", "nav_value"]]
        .sort_values(["ifind_code", "month_date"])
        .reset_index(drop=True)
    )

    # 每只基金每个月应该只有一条记录。重复时直接报错，避免悄悄选错数据。
    duplicate_keys = long.duplicated(["ifind_code", "month_date"], keep=False)
    if duplicate_keys.any():
        examples = long.loc[duplicate_keys, ["ifind_code", "month_date"]].head(10)
        raise ValueError(
            f"{nav_path.name} 出现重复基金-月份键：\n{examples.to_string(index=False)}"
        )

    effective_end_date = max(date_mapping.values())
    return long, effective_end_date, original_codes


def parse_manager_tenures(
    manager_path: Path, effective_end_date: pd.Timestamp
) -> pd.DataFrame:
    """把 Wind 的“基金经理(历任)”文字解析成一行一段任期的数据。"""
    source = pd.read_excel(manager_path)
    source.columns = clean_headers(source.columns)
    require_columns(source, ["证券代码", "证券简称", "基金经理(历任)"], manager_path)

    records: list[dict[str, object]] = []
    parse_errors: list[str] = []

    for _, row in source.iterrows():
        wind_code = normalize_code(row["证券代码"])
        manager_text = row["基金经理(历任)"]
        if wind_code is None or pd.isna(manager_text):
            continue

        text = str(manager_text).strip()
        matches = list(MANAGER_PATTERN.finditer(text))

        # 把已经成功匹配的部分删除。如果还有文字残留，说明格式没有完全解析。
        residue = MANAGER_PATTERN.sub("", text)
        residue = re.sub(r"[\s;；,，]+", "", residue)
        if residue or not matches:
            parse_errors.append(f"{wind_code}: {text}")
            continue

        for match in matches:
            start_date = pd.to_datetime(match.group("start"), format="%Y%m%d")
            is_current_manager = match.group("end") == "今"

            # “至今”没有真实结束日，因此使用本投资类型净值数据的截止日。
            end_date = (
                effective_end_date
                if is_current_manager
                else pd.to_datetime(match.group("end"), format="%Y%m%d")
            )
            records.append(
                {
                    "wind_code": wind_code,
                    "fund_name": str(row["证券简称"]).strip(),
                    "manager": match.group("manager").strip(),
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

    if parse_errors:
        raise ValueError(
            f"{manager_path.name} 中有基金经理字段未能完整解析（最多显示 10 条）：\n"
            + "\n".join(parse_errors[:10])
        )

    tenures = pd.DataFrame.from_records(records)
    if tenures.empty:
        raise ValueError(f"{manager_path} 没有解析出任何基金经理任期。")
    return tenures.sort_values(
        ["wind_code", "start_date", "end_date", "manager"]
    ).reset_index(drop=True)


def build_manager_regimes(
    tenures: pd.DataFrame, effective_end_date: pd.Timestamp
) -> pd.DataFrame:
    """根据经理加入和离开事件，生成基金经理团队稳定区间。

    这里使用 Counter 记录每位经理当前是否在任：

    - start_date 当天，计数加 1；
    - end_date 的次日，计数减 1。

    因此 end_date 当日仍属于原来的经理团队。
    """
    records: list[dict[str, object]] = []

    # groupby 后，每次只处理一只 Wind 基金。
    for wind_code, group in tenures.groupby("wind_code", sort=True):
        events: dict[pd.Timestamp, Counter[str]] = defaultdict(Counter)
        fund_name = group["fund_name"].dropna().astype(str).iloc[0]

        for row in group.itertuples(index=False):
            # 如果经理上任日在净值数据截止日之后，他不会影响当前样本。
            if row.start_date > effective_end_date:
                continue

            clipped_end = min(row.end_date, effective_end_date)
            if clipped_end < row.start_date:
                continue

            events[row.start_date][row.manager] += 1
            events[clipped_end + pd.Timedelta(days=1)][row.manager] -= 1

        event_dates = sorted(date for date in events if date <= effective_end_date)
        if not event_dates:
            continue

        active_counts: Counter[str] = Counter()
        raw_intervals: list[dict[str, object]] = []

        for position, event_date in enumerate(event_dates):
            # 先应用当天的加入或退出变化，再确定当天开始的经理团队。
            active_counts.update(events[event_date])
            active_counts = Counter(
                {manager: count for manager, count in active_counts.items() if count > 0}
            )

            next_date = (
                event_dates[position + 1]
                if position + 1 < len(event_dates)
                else effective_end_date + pd.Timedelta(days=1)
            )
            regime_end = min(next_date - pd.Timedelta(days=1), effective_end_date)

            # 没有经理的空档期不生成 regime。
            if event_date > regime_end or not active_counts:
                continue

            # 姓名排序后再拼接，避免“张三|李四”和“李四|张三”被误认为不同团队。
            manager_names = tuple(sorted(active_counts))

            # 如果事件发生了，但团队名单实际没有变化，就和上一段合并。
            if raw_intervals and raw_intervals[-1]["manager_names"] == manager_names:
                raw_intervals[-1]["regime_end"] = regime_end
            else:
                raw_intervals.append(
                    {
                        "regime_start": event_date,
                        "regime_end": regime_end,
                        "manager_names": manager_names,
                    }
                )

        for regime_id, interval in enumerate(raw_intervals, start=1):
            regime_start = interval["regime_start"]
            records.append(
                {
                    "wind_code": wind_code,
                    "fund_name": fund_name,
                    "regime_id": regime_id,
                    "regime_start": regime_start,
                    "regime_end": interval["regime_end"],
                    "manager_team": "|".join(interval["manager_names"]),
                    "manager_count": len(interval["manager_names"]),
                    "eligible_start": regime_start + pd.DateOffset(months=12),
                }
            )

    regimes = pd.DataFrame.from_records(records)
    if regimes.empty:
        raise ValueError("没有生成任何基金经理团队 regime。")
    return regimes.sort_values(["wind_code", "regime_id"]).reset_index(drop=True)


def read_registry(registry_path: Path) -> tuple[pd.DataFrame, str | None]:
    """读取 Wind 与 iFind 代码映射，并自动寻找可选的基金成立日。"""
    registry = pd.read_excel(registry_path)
    registry.columns = clean_headers(registry.columns)
    require_columns(registry, ["iFind代码", "Wind代码"], registry_path)

    fund_name_column = next(
        (column for column in FUND_NAME_COLUMN_CANDIDATES if column in registry.columns),
        None,
    )
    if fund_name_column is None:
        raise ValueError(
            f"{registry_path} 缺少基金名称列；可接受列名："
            f"{list(FUND_NAME_COLUMN_CANDIDATES)}"
        )

    registry["ifind_code"] = registry["iFind代码"].map(normalize_code)
    registry["wind_code"] = registry["Wind代码"].map(normalize_code)
    registry["registry_fund_name"] = (
        registry[fund_name_column].astype("string").str.strip()
    )

    inception_column = next(
        (column for column in INCEPTION_COLUMN_CANDIDATES if column in registry.columns),
        None,
    )
    if inception_column:
        registry["fund_inception_date"] = registry[inception_column].map(parse_excel_date)
    else:
        registry["fund_inception_date"] = pd.NaT

    mapping = registry[
        ["wind_code", "ifind_code", "registry_fund_name", "fund_inception_date"]
    ].dropna(subset=["wind_code", "ifind_code"])
    mapping = mapping.drop_duplicates().reset_index(drop=True)

    # 一个 Wind 代码可以映射到多个 iFind 代码，这是正常情况。
    # 反过来，一个 iFind 代码若对应多个 Wind 代码，就无法判断该用哪套经理历史。
    conflicts = mapping.groupby("ifind_code")["wind_code"].nunique()
    conflict_codes = conflicts[conflicts > 1].index.tolist()
    if conflict_codes:
        examples = mapping[mapping["ifind_code"].isin(conflict_codes[:10])]
        raise ValueError(
            "同一 iFind 代码映射到多个 Wind 代码，无法安全匹配：\n"
            + examples.to_string(index=False)
        )

    mapping = mapping.drop_duplicates(subset=["wind_code", "ifind_code"], keep="first")
    return mapping, inception_column


def expand_regimes_to_ifind(regimes: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    """把 Wind 层面的 regime 扩展到对应的一个或多个 iFind 代码。"""
    expanded = regimes.merge(mapping, on="wind_code", how="inner", validate="many_to_many")

    # 目前 registry 没有成立日时，base_start 就是 regime_start。
    # 将来若补充成立日，则使用 max(成立日, regime_start) 再加 12 个月。
    base_start = expanded["regime_start"].copy()
    has_inception = expanded["fund_inception_date"].notna()
    base_start.loc[has_inception] = expanded.loc[
        has_inception, ["regime_start", "fund_inception_date"]
    ].max(axis=1)
    expanded["eligible_start"] = base_start + pd.DateOffset(months=12)

    return expanded.sort_values(
        ["ifind_code", "regime_start", "regime_id"]
    ).reset_index(drop=True)


def assign_regimes_to_nav(nav_long: pd.DataFrame, expanded: pd.DataFrame) -> pd.DataFrame:
    """给每条基金月度净值找到当时对应的经理团队 regime。

    np.searchsorted 会在已经按日期排序的 regime 中快速寻找：
    “最后一个 regime_start 不晚于 month_date 的 regime”。
    找到后还要检查 month_date 是否不晚于 regime_end。
    """
    regime_columns = [
        "regime_id",
        "regime_start",
        "regime_end",
        "manager_team",
        "manager_count",
        "fund_inception_date",
        "eligible_start",
    ]

    result = nav_long.copy()
    for column in regime_columns:
        result[column] = pd.NA

    # 先按 iFind 代码做成字典，循环时不需要反复扫描整个 regime 表。
    regime_groups = {
        code: group.reset_index(drop=True)
        for code, group in expanded.groupby("ifind_code")
    }

    for ifind_code, nav_group in result.groupby("ifind_code", sort=False):
        regimes = regime_groups.get(ifind_code)
        if regimes is None or regimes.empty:
            continue

        starts = regimes["regime_start"].to_numpy(dtype="datetime64[ns]")
        ends = regimes["regime_end"].to_numpy(dtype="datetime64[ns]")
        dates = nav_group["month_date"].to_numpy(dtype="datetime64[ns]")

        positions = np.searchsorted(starts, dates, side="right") - 1
        valid = positions >= 0
        valid_positions = positions[valid]
        valid[valid] &= dates[valid] <= ends[valid_positions]
        if not valid.any():
            continue

        target_index = nav_group.index.to_numpy()[valid]
        matched = regimes.iloc[positions[valid]][regime_columns].copy()
        matched.index = target_index

        for column in regime_columns:
            result.loc[target_index, column] = matched[column]

    # 初始化时使用 pd.NA，匹配后再把日期和整数列恢复成正确类型。
    for column in (
        "regime_start",
        "regime_end",
        "fund_inception_date",
        "eligible_start",
    ):
        result[column] = pd.to_datetime(result[column], errors="coerce")
    result["regime_id"] = pd.to_numeric(result["regime_id"], errors="coerce").astype(
        "Int64"
    )
    result["manager_count"] = pd.to_numeric(
        result["manager_count"], errors="coerce"
    ).astype("Int64")

    # 这个布尔列按净值观测日判断，不强制要求团队持续到自然月最后一天。
    # 例如 5 月净值日是 5 月 29 日，只要 5 月 29 日当天团队已经稳定满
    # 12 个月且尚未结束，该净值点就标记为 True。
    result["is_in_manager_regime"] = (
        result["regime_id"].notna()
        & (result["month_date"] >= result["eligible_start"])
        & (result["month_date"] >= result["regime_start"])
        & (result["month_date"] <= result["regime_end"])
    )
    return result


def validate_results(
    regimes: pd.DataFrame,
    output: pd.DataFrame,
    original_nav_row_count: int,
) -> None:
    """在保存前做几项关键检查，避免把逻辑错误写入最终文件。"""
    if (regimes["regime_start"] > regimes["regime_end"]).any():
        raise AssertionError("regime 存在开始日晚于结束日。")

    # 同一基金的两个 regime 不应该有日期重叠。
    for _, group in regimes.groupby("wind_code"):
        ordered = group.sort_values("regime_start")
        previous_end = ordered["regime_end"].shift(1)
        if (ordered["regime_start"] <= previous_end).fillna(False).any():
            raise AssertionError("同一 Wind 基金的 regime 存在重叠。")

    # 现在不删除未入样行，所以输出行数必须与原净值长表完全一致。
    if len(output) != original_nav_row_count:
        raise AssertionError("输出行数与原净值长表不一致，可能误删了净值记录。")

    expected_columns = [
        "registry_fund_name",
        "ifind_code",
        "wind_code",
        "investment_type",
        "month_date",
        "nav_value",
        "regime_id",
        "is_in_manager_regime",
    ]
    if list(output.columns) != expected_columns:
        raise AssertionError("最终输出列名或列顺序不符合要求。")


def process_one_investment_type(
    investment_type: str,
    nav_path: Path,
    manager_path: Path,
    mapping: pd.DataFrame,
    inception_column: str | None,
    output_dir: Path,
    keep_zero_nav: bool,
) -> dict[str, object]:
    """完成一个投资类型从读取到保存的全部步骤。"""
    nav_long, effective_end_date, original_codes = read_nav_long(
        nav_path, keep_zero_nav
    )
    tenures = parse_manager_tenures(manager_path, effective_end_date)
    regimes = build_manager_regimes(tenures, effective_end_date)
    expanded = expand_regimes_to_ifind(regimes, mapping)

    # 先只使用 fund_registry 把基金名称和 Wind 代码拼到净值表上。
    # how="left" 表示即使 registry 没有匹配，净值行也会保留下来。
    mapped_nav = nav_long.merge(
        mapping[
            [
                "ifind_code",
                "wind_code",
                "registry_fund_name",
                "fund_inception_date",
            ]
        ],
        on="ifind_code",
        how="left",
        validate="many_to_one",
    )
    nav_with_regime = assign_regimes_to_nav(mapped_nav, expanded)

    # 保留 regime_id，后续计算相邻月份回报时，
    # 可以检查两个净值点是否属于同一个基金经理团队 regime。
    nav_with_regime["investment_type"] = investment_type
    output_columns = [
        "registry_fund_name",
        "ifind_code",
        "wind_code",
        "investment_type",
        "month_date",
        "nav_value",
        "regime_id",
        "is_in_manager_regime",
    ]
    output = (
        nav_with_regime[output_columns]
        .sort_values(["ifind_code", "month_date"])
        .reset_index(drop=True)
    )

    validate_results(regimes, output, len(nav_long))

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{investment_type}净值筛选长表.parquet"
    output.to_parquet(output_path, index=False)

    matched_codes = original_codes & set(expanded["ifind_code"].unique())
    eligible_count = int(nav_with_regime["is_in_manager_regime"].sum())

    # 返回一个普通字典，供 main() 在终端打印诊断信息。
    return {
        "investment_type": investment_type,
        "nav_path": nav_path,
        "manager_path": manager_path,
        "output_path": output_path,
        "effective_end_date": effective_end_date,
        "original_fund_count": len(original_codes),
        "matched_fund_count": len(matched_codes),
        "unmatched_codes": sorted(original_codes - matched_codes),
        "total_row_count": len(output),
        "eligible_count": eligible_count,
        "ineligible_count": len(output) - eligible_count,
        "inception_column": inception_column,
    }


def print_summary(summary: dict[str, object]) -> None:
    """把一个投资类型的处理结果用容易阅读的方式打印到终端。"""
    print("\n" + "=" * 72)
    print(f"投资类型：{summary['investment_type']}")
    print(f"iFind 净值文件：{summary['nav_path']}")
    print(f"Wind 经理文件：{summary['manager_path']}")
    print(f"净值截止日：{summary['effective_end_date']:%Y-%m-%d}")
    print(f"原始 iFind 基金数：{summary['original_fund_count']}")
    print(f"成功匹配基金经理信息的基金数：{summary['matched_fund_count']}")
    print(f"输出基金-月份总数：{summary['total_row_count']:,}")
    print(f"is_in_manager_regime=True：{summary['eligible_count']:,}")
    print(f"is_in_manager_regime=False：{summary['ineligible_count']:,}")

    unmatched_codes = summary["unmatched_codes"]
    if unmatched_codes:
        print(f"未匹配基金代码（{len(unmatched_codes)} 只）：{', '.join(unmatched_codes)}")
    else:
        print("未匹配基金代码：无")

    if summary["inception_column"]:
        print(f"成立日口径：使用 registry 字段 {summary['inception_column']}")
    else:
        print("成立日口径：registry 未提供成立日，使用 regime_start + 12个月")
    print(f"输出文件：{summary['output_path']}")


def main() -> None:
    """程序入口：发现全部文件配对，然后逐个投资类型处理。"""
    args = parse_args()

    if not args.registry.exists():
        raise FileNotFoundError(f"基金代码映射表不存在：{args.registry}")
    if not args.nav_dir.exists():
        raise FileNotFoundError(f"iFind 净值目录不存在：{args.nav_dir}")
    if not args.manager_dir.exists():
        raise FileNotFoundError(f"Wind 经理目录不存在：{args.manager_dir}")

    # registry 对所有投资类型都相同，因此只读取一次，减少重复工作。
    mapping, inception_column = read_registry(args.registry)
    input_pairs = discover_input_pairs(args.nav_dir, args.manager_dir)

    print(f"发现 {len(input_pairs)} 个投资类型，开始批量处理。")
    summaries = []
    for investment_type, nav_path, manager_path in input_pairs:
        print(f"\n正在处理：{investment_type}")
        summary = process_one_investment_type(
            investment_type=investment_type,
            nav_path=nav_path,
            manager_path=manager_path,
            mapping=mapping,
            inception_column=inception_column,
            output_dir=args.output_dir,
            keep_zero_nav=args.keep_zero_nav,
        )
        summaries.append(summary)
        print_summary(summary)

    print("\n" + "=" * 72)
    print(f"全部完成，共输出 {len(summaries)} 个 Parquet 文件：")
    for summary in summaries:
        print(f"- {summary['output_path']}")


if __name__ == "__main__":
    main()
