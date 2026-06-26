"""根据基金成立时间、经理任期、规模和份额类别生成筛选表。

本脚本读取 ``A_data/output/fund_managers`` 中的 Parquet 文件，完成：

1. 标记基金是否已经成立满 12 个月；
2. 使用上一步生成的经理团队标签，标记当前经理团队是否稳定满 12 个月；
3. 按主代码汇总月度基金规模，并判断规模是否达到 1 亿元；
4. 每个主代码选择一个数据最完整的代表份额；
5. 生成通过全部信息筛选的 ``is_sample`` 标签。

本脚本不计算收益率。收益率及未来收益由后续面板脚本负责计算。

原始净值行不会因为筛选规则被删除，所有规则都通过布尔标签控制。

运行方式：

    python A_data/scripts/2_fund_filter.py
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
A_DATA_ROOT = PROJECT_ROOT / "A_data"

DEFAULT_INPUT_DIR = A_DATA_ROOT / "output" / "fund_managers"
DEFAULT_REGISTRY_PATH = A_DATA_ROOT / "data" / "fund_registry.xlsx"
DEFAULT_IFIND_DIR = A_DATA_ROOT / "data" / "iFind_API"
DEFAULT_OUTPUT_DIR = A_DATA_ROOT / "prepared_data"

# 规模文件的单位是人民币元，1 亿元等于 100,000,000 元。
SIZE_THRESHOLD = 100_000_000

REQUIRED_SOURCE_COLUMNS = (
    "registry_fund_name",
    "ifind_code",
    "wind_code",
    "investment_type",
    "month_date",
    "nav_value",
    "regime_id",
    "is_in_manager_regime",
)

OUTPUT_COLUMNS = (
    "registry_fund_name",
    "ifind_code",
    "main_code",
    "wind_code",
    "investment_type",
    "month_date",
    "nav",
    "fund_size_t",
    "regime_id",
    "is_establish_1y",
    "is_manager_1y",
    "is_primary_share",
    "is_sample",
    "is_size_eligible_t",
)


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="根据成立时间和基金经理任期生成基金月度筛选表。"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help="基金经理筛选 Parquet 所在目录。",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="包含基金成立日的基金代码映射表。",
    )
    parser.add_argument(
        "--ifind-dir",
        type=Path,
        default=DEFAULT_IFIND_DIR,
        help="iFind 净值变化和基金规模 Excel 所在目录。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="结果输出目录。",
    )
    parser.add_argument(
        "--skip-panel",
        action="store_true",
        help="只生成筛选长表，不继续生成 panel_base。",
    )
    parser.add_argument(
        "--panel-return-type",
        choices=Config.VALID_RETURN_TYPES,
        default=Config.PANEL_RETURN_TYPE,
        help="自动生成 panel_base 时使用的收益率类型。",
    )
    return parser.parse_args()


def require_columns(
    data: pd.DataFrame, columns: Iterable[str], source_path: Path
) -> None:
    """检查数据是否包含程序需要的字段。"""
    missing = [column for column in columns if column not in data.columns]
    if missing:
        raise ValueError(
            f"{source_path} 缺少字段：{missing}；实际字段为：{list(data.columns)}"
        )


def normalize_code(value: object) -> str | None:
    """统一基金代码格式，例如把数字 82 转换成 000082。"""
    if value is None or pd.isna(value):
        return None

    if isinstance(value, (int, np.integer)):
        return f"{int(value):06d}"

    if isinstance(value, (float, np.floating)):
        if np.isnan(value):
            return None
        if float(value).is_integer():
            return f"{int(value):06d}"

    code = str(value).strip().upper().replace(" ", "")
    if not code or code in {"NAN", "NONE", "NAT"}:
        return None
    if re.fullmatch(r"\d+\.0", code):
        return code[:-2].zfill(6)
    if re.fullmatch(r"\d+", code):
        return code.zfill(6)
    return code


def find_source_files(input_dir: Path) -> list[Path]:
    """寻找经理筛选步骤生成的全部 Parquet 文件。"""
    source_files = sorted(input_dir.glob("*净值筛选长表.parquet"))
    if not source_files:
        raise FileNotFoundError(
            f"{input_dir} 中没有找到 *净值筛选长表.parquet。"
        )
    return source_files


def normalize_main_code(value: object) -> str | None:
    """把基金主代码统一为六位数字字符串。"""
    code = normalize_code(value)
    if code is None:
        return None

    # 基金主代码正常情况下没有交易所后缀。
    number_part = code.split(".", maxsplit=1)[0]
    if not number_part.isdigit():
        return None
    return number_part.zfill(6)


def read_fund_registry(registry_path: Path) -> pd.DataFrame:
    """读取每只 iFind 基金的成立日期和基金主代码。"""
    registry = pd.read_excel(registry_path)
    registry.columns = [str(column).strip() for column in registry.columns]
    require_columns(
        registry, ["iFind代码", "基金主代码", "基金成立日"], registry_path
    )

    registry["ifind_code"] = registry["iFind代码"].map(normalize_code)
    registry["main_code"] = registry["基金主代码"].map(normalize_main_code)
    registry["fund_inception_date"] = pd.to_datetime(
        registry["基金成立日"], errors="coerce"
    )

    fund_registry = registry[
        ["ifind_code", "main_code", "fund_inception_date"]
    ].dropna(subset=["ifind_code"])

    # 一个基金代码只能对应一组主代码和成立日。
    unique_values = fund_registry.groupby("ifind_code").agg(
        main_code_count=("main_code", "nunique"),
        inception_date_count=("fund_inception_date", "nunique"),
    )
    conflicting_codes = unique_values[
        (unique_values["main_code_count"] > 1)
        | (unique_values["inception_date_count"] > 1)
    ].index.tolist()
    if conflicting_codes:
        examples = fund_registry[fund_registry["ifind_code"].isin(conflicting_codes[:10])]
        raise ValueError(
            "同一 iFind 代码对应多个主代码或成立日：\n"
            + examples.to_string(index=False)
        )

    return fund_registry.drop_duplicates("ifind_code", keep="first").reset_index(drop=True)


def investment_type_from_source_path(source_path: Path) -> str:
    """从“偏股混合型基金净值筛选长表.parquet”中取出投资类型。"""
    suffix = "净值筛选长表"
    if not source_path.stem.endswith(suffix):
        raise ValueError(f"无法从文件名识别投资类型：{source_path.name}")
    return source_path.stem[: -len(suffix)]


def find_ifind_files(investment_type: str, ifind_dir: Path) -> tuple[Path, Path]:
    """找到同一投资类型的净值变化和基金规模工作簿。"""
    nav_path = ifind_dir / f"iFind{investment_type}净值变化.xlsx"
    size_path = ifind_dir / f"iFind{investment_type}基金规模.xlsx"
    missing = [path for path in (nav_path, size_path) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"缺少 iFind 输入文件：{missing}")
    return nav_path, size_path


def read_ifind_wide(file_path: Path) -> pd.DataFrame:
    """读取 iFind 月度宽表，并标准化代码、日期列和数值。"""
    wide = pd.read_excel(file_path, sheet_name="month")
    if wide.empty or len(wide.columns) < 2:
        raise ValueError(f"{file_path} 的 month sheet 没有可用数据。")

    wide = wide.rename(columns={wide.columns[0]: "ifind_code"})
    wide["ifind_code"] = wide["ifind_code"].map(normalize_code)
    wide = wide.dropna(subset=["ifind_code"]).copy()

    date_mapping = {
        column: pd.to_datetime(column, errors="coerce") for column in wide.columns[1:]
    }
    invalid_columns = [
        column for column, date in date_mapping.items() if pd.isna(date)
    ]
    if invalid_columns:
        raise ValueError(
            f"{file_path.name} 含无法识别的日期列：{invalid_columns[:10]}"
        )

    wide = wide.rename(columns=date_mapping)
    date_columns = list(date_mapping.values())
    wide[date_columns] = wide[date_columns].apply(pd.to_numeric, errors="coerce")

    duplicate_codes = wide["ifind_code"].duplicated(keep=False)
    if duplicate_codes.any():
        examples = wide.loc[duplicate_codes, "ifind_code"].head(10).tolist()
        raise ValueError(f"{file_path.name} 存在重复基金代码：{examples}")
    return wide[["ifind_code", *date_columns]]


def build_size_and_share_labels(
    nav_path: Path,
    size_path: Path,
    fund_registry: pd.DataFrame,
    output_codes: set[str],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """生成主代码月度规模和每个主代码的唯一代表份额。

    代表份额只在实际出现在原型 Parquet 的代码中选择。这样即使 iFind
    工作簿还包含尚未产生有效净值的份额，也不会让一个已有样本的主代码
    因“胜出代码没有输出行”而失去全部代表份额。
    """
    nav_wide = read_ifind_wide(nav_path)
    size_wide = read_ifind_wide(size_path)
    nav_dates = list(nav_wide.columns[1:])
    size_dates = list(size_wide.columns[1:])
    if nav_dates != size_dates:
        raise ValueError(f"{nav_path.name} 与 {size_path.name} 的月份列不一致。")

    registry_columns = fund_registry[["ifind_code", "main_code"]]
    nav_wide = nav_wide.merge(
        registry_columns, on="ifind_code", how="left", validate="one_to_one"
    )
    size_wide = size_wide.merge(
        registry_columns, on="ifind_code", how="left", validate="one_to_one"
    )
    if nav_wide["main_code"].isna().any() or size_wide["main_code"].isna().any():
        raise ValueError("iFind 宽表中存在无法匹配基金主代码的基金。")

    # 0 和负数都不是有效规模。先转成长表，再按主代码和月份求和。
    size_long = size_wide.melt(
        id_vars=["ifind_code", "main_code"],
        value_vars=size_dates,
        var_name="month_date",
        value_name="share_size",
    )
    size_long.loc[size_long["share_size"] <= 0, "share_size"] = np.nan
    main_size = (
        size_long.groupby(["main_code", "month_date"], as_index=False)["share_size"]
        .sum(min_count=1)
        .rename(columns={"share_size": "fund_size_t"})
    )

    # 净值中的 0 或空值都计为缺失。
    nav_values = nav_wide[nav_dates]
    share_scores = nav_wide[["ifind_code", "main_code"]].copy()
    share_scores["nav_missing_count"] = (
        nav_values.isna() | nav_values.eq(0)
    ).sum(axis=1)

    # 累计规模只用于并列决胜。0、空值和负值不计入累计规模。
    size_values = size_wide[size_dates].where(size_wide[size_dates] > 0)
    cumulative_size = size_values.sum(axis=1, min_count=1).fillna(0)
    cumulative_size_by_code = pd.Series(
        cumulative_size.to_numpy(), index=size_wide["ifind_code"]
    )
    share_scores["cumulative_size"] = share_scores["ifind_code"].map(
        cumulative_size_by_code
    ).fillna(0)

    # 只在原型 Parquet 实际包含的基金代码中选择代表份额。
    candidates = share_scores[share_scores["ifind_code"].isin(output_codes)].copy()
    candidates["is_same_as_main_code"] = (
        candidates["ifind_code"].str.split(".").str[0]
        == candidates["main_code"]
    )
    candidates = candidates.sort_values(
        [
            "main_code",
            "nav_missing_count",
            "cumulative_size",
            "is_same_as_main_code",
            "ifind_code",
        ],
        ascending=[True, True, False, False, True],
    )
    primary_codes = candidates.drop_duplicates("main_code", keep="first")
    share_labels = candidates[["ifind_code", "main_code"]].copy()
    share_labels["is_primary_share"] = share_labels["ifind_code"].isin(
        set(primary_codes["ifind_code"])
    )

    all_zero_main_codes = (
        share_scores.groupby("main_code")["nav_missing_count"].min().eq(len(nav_dates))
    )
    diagnostics = {
        "all_zero_main_code_count": int(all_zero_main_codes.sum()),
        "primary_share_count": len(primary_codes),
    }
    return main_size, share_labels, diagnostics


def build_filter_table(
    source: pd.DataFrame,
    fund_registry: pd.DataFrame,
    main_size: pd.DataFrame,
    share_labels: pd.DataFrame,
) -> pd.DataFrame:
    """增加成立、经理、规模、代表份额和最终筛选标签。"""
    result = source.copy()
    result["month_date"] = pd.to_datetime(result["month_date"], errors="coerce")
    if result["month_date"].isna().any():
        raise ValueError("原型 Parquet 中存在无法识别的 month_date。")

    # 原始净值只改列名，不改变数值。
    result = result.rename(columns={"nav_value": "nav"})
    result = result.merge(
        fund_registry,
        on="ifind_code",
        how="left",
        validate="many_to_one",
    )
    if result["main_code"].isna().any():
        missing_codes = result.loc[result["main_code"].isna(), "ifind_code"].unique()
        raise ValueError(f"以下基金无法匹配主代码：{missing_codes[:20].tolist()}")

    eligible_establish_date = result["fund_inception_date"] + pd.DateOffset(
        months=12
    )
    result["is_establish_1y"] = (
        result["fund_inception_date"].notna()
        & (result["month_date"] >= eligible_establish_date)
    )

    # 缺少经理 regime 的记录也会保留，并明确标记为 False。
    result["is_manager_1y"] = result["is_in_manager_regime"].fillna(False).astype(bool)

    result = result.merge(
        main_size,
        on=["main_code", "month_date"],
        how="left",
        validate="many_to_one",
    )
    result["is_size_eligible_t"] = (
        result["fund_size_t"].notna()
        & (result["fund_size_t"] >= SIZE_THRESHOLD)
    )

    result = result.merge(
        share_labels,
        on=["ifind_code", "main_code"],
        how="left",
        validate="many_to_one",
    )
    result["is_primary_share"] = result["is_primary_share"].fillna(False).astype(bool)

    result["is_sample"] = (
        result["is_establish_1y"]
        & result["is_manager_1y"]
        & result["is_primary_share"]
    )

    return result[list(OUTPUT_COLUMNS)].reset_index(drop=True)


def validate_output(
    source: pd.DataFrame, output: pd.DataFrame, main_size: pd.DataFrame
) -> None:
    """写盘前检查行数、主键、原始日期、净值及主要业务规则。"""
    if len(output) != len(source):
        raise AssertionError("输出行数与原型 Parquet 不一致。")

    duplicate_keys = output.duplicated(["ifind_code", "month_date"], keep=False)
    if duplicate_keys.any():
        examples = output.loc[
            duplicate_keys, ["ifind_code", "month_date"]
        ].head(10)
        raise AssertionError(
            "输出中存在重复的基金-月份键：\n" + examples.to_string(index=False)
        )

    source_values = source[
        ["ifind_code", "month_date", "nav_value"]
    ].sort_values(["ifind_code", "month_date"]).reset_index(drop=True)
    output_values = (
        output[["ifind_code", "month_date", "nav"]]
        .rename(columns={"nav": "nav_value"})
        .sort_values(["ifind_code", "month_date"])
        .reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(source_values, output_values, check_dtype=True)

    # 没有经理 regime 的记录不能被标记为经理合格或进入样本。
    missing_regime = output["regime_id"].isna()
    if output.loc[missing_regime, "is_manager_1y"].any():
        raise AssertionError("缺少经理 regime 的记录被错误标记为经理合格。")
    if output.loc[missing_regime, "is_sample"].any():
        raise AssertionError("缺少经理 regime 的记录被错误纳入样本。")

    expected_size_eligible = (
        output["fund_size_t"].notna()
        & (output["fund_size_t"] >= SIZE_THRESHOLD)
    )
    if not output["is_size_eligible_t"].equals(expected_size_eligible):
        raise AssertionError("is_size_eligible_t 与 1 亿元规模门槛不一致。")

    # 规模必须按主代码和完全相同的原始净值日期匹配。
    expected_size = output[["main_code", "month_date"]].merge(
        main_size,
        on=["main_code", "month_date"],
        how="left",
        validate="many_to_one",
    )["fund_size_t"]
    pd.testing.assert_series_equal(
        output["fund_size_t"].reset_index(drop=True),
        expected_size.reset_index(drop=True),
        check_names=False,
    )

    # 标签是基金代码层面的静态标签，同一代码的所有月份必须相同。
    primary_values_per_fund = output.groupby("ifind_code")["is_primary_share"].nunique()
    if (primary_values_per_fund != 1).any():
        raise AssertionError("同一基金代码的 is_primary_share 在不同月份不一致。")

    fund_level_labels = output[
        ["main_code", "ifind_code", "is_primary_share"]
    ].drop_duplicates()
    primary_count_by_main = fund_level_labels.groupby("main_code")[
        "is_primary_share"
    ].sum()
    if (primary_count_by_main != 1).any():
        bad_main_codes = primary_count_by_main[primary_count_by_main != 1].head(20)
        raise AssertionError(
            "以下主代码没有恰好一个代表份额：\n" + bad_main_codes.to_string()
        )

    required_for_sample = (
        output["is_establish_1y"]
        & output["is_manager_1y"]
        & output["is_primary_share"]
    )
    if not output["is_sample"].equals(required_for_sample):
        raise AssertionError("is_sample 与本轮定义不一致。")


def process_one_file(
    source_path: Path,
    fund_registry: pd.DataFrame,
    ifind_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    """处理一份原型 Parquet，并返回用于打印的统计信息。"""
    source = pd.read_parquet(source_path)
    require_columns(source, REQUIRED_SOURCE_COLUMNS, source_path)

    investment_type = investment_type_from_source_path(source_path)
    nav_path, size_path = find_ifind_files(investment_type, ifind_dir)
    main_size, share_labels, diagnostics = build_size_and_share_labels(
        nav_path=nav_path,
        size_path=size_path,
        fund_registry=fund_registry,
        output_codes=set(source["ifind_code"].unique()),
    )

    output = build_filter_table(
        source=source,
        fund_registry=fund_registry,
        main_size=main_size,
        share_labels=share_labels,
    )
    validate_output(source, output, main_size)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / source_path.name
    output.to_parquet(output_path, index=False)

    missing_inception_codes = sorted(
        output.loc[~output["is_establish_1y"] & output["month_date"].notna()]
        .merge(
            fund_registry[["ifind_code", "fund_inception_date"]],
            on="ifind_code",
            how="left",
            validate="many_to_one",
        )
        .loc[lambda frame: frame["fund_inception_date"].isna(), "ifind_code"]
        .unique()
        .tolist()
    )
    missing_manager_codes = sorted(
        output.loc[output["regime_id"].isna(), "ifind_code"].unique().tolist()
    )

    return {
        "source_path": source_path,
        "output_path": output_path,
        "row_count": len(output),
        "fund_count": output["ifind_code"].nunique(),
        "establish_eligible_count": int(output["is_establish_1y"].sum()),
        "manager_eligible_count": int(output["is_manager_1y"].sum()),
        "missing_size_count": int(output["fund_size_t"].isna().sum()),
        "size_eligible_count": int(output["is_size_eligible_t"].sum()),
        "primary_share_count": diagnostics["primary_share_count"],
        "all_zero_main_code_count": diagnostics["all_zero_main_code_count"],
        "sample_count": int(output["is_sample"].sum()),
        "missing_inception_codes": missing_inception_codes,
        "missing_manager_codes": missing_manager_codes,
    }


def print_summary(summary: dict[str, object]) -> None:
    """打印一份输出文件的处理结果。"""
    print("\n" + "=" * 72)
    print(f"来源文件：{summary['source_path']}")
    print(f"基金数量：{summary['fund_count']:,}")
    print(f"基金-月份行数：{summary['row_count']:,}")
    print(f"成立满 12 个月：{summary['establish_eligible_count']:,}")
    print(f"经理团队稳定满 12 个月：{summary['manager_eligible_count']:,}")
    print(f"基金规模缺失：{summary['missing_size_count']:,}")
    print(f"主代码规模不低于 1 亿元：{summary['size_eligible_count']:,}")
    print(f"代表份额基金数：{summary['primary_share_count']:,}")
    print(
        f"净值宽表全期间均为 0 或空值的主代码："
        f"{summary['all_zero_main_code_count']:,}"
    )
    print(f"is_sample=True：{summary['sample_count']:,}")

    missing_inception_codes = summary["missing_inception_codes"]
    if missing_inception_codes:
        print(
            f"缺少成立日的基金（{len(missing_inception_codes)} 只）："
            + ", ".join(missing_inception_codes)
        )
    else:
        print("缺少成立日的基金：无")

    missing_manager_codes = summary["missing_manager_codes"]
    if missing_manager_codes:
        print(
            f"存在经理 regime 缺失记录的基金（{len(missing_manager_codes)} 只）："
            + ", ".join(missing_manager_codes)
        )
    else:
        print("存在经理 regime 缺失记录的基金：无")
    print(f"输出文件：{summary['output_path']}")


def load_panel_module():
    """加载 3_generate_panel_base.py，供自动串联时调用。"""
    panel_script = Path(__file__).with_name("3_generate_panel_base.py")
    spec = importlib.util.spec_from_file_location("generate_panel_base", panel_script)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载面板脚本：{panel_script}")

    panel_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(panel_module)
    return panel_module


def run_panel_base(output_dir: Path, return_type: str) -> dict[str, object]:
    """在筛选长表生成后，继续调用 3_generate_panel_base.py 生成面板。"""
    panel_module = load_panel_module()
    return panel_module.generate_panel(
        source_dir=output_dir,
        output_path=panel_module.DEFAULT_OUTPUT_PATH,
        return_type=return_type,
        write_preview=True,
    )


def main() -> None:
    """程序入口：读取基金映射，生成筛选长表，并可继续生成面板。"""
    args = parse_args()
    if not args.input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在：{args.input_dir}")
    if not args.registry.exists():
        raise FileNotFoundError(f"基金代码映射表不存在：{args.registry}")
    if not args.ifind_dir.exists():
        raise FileNotFoundError(f"iFind 数据目录不存在：{args.ifind_dir}")

    source_files = find_source_files(args.input_dir)
    fund_registry = read_fund_registry(args.registry)

    print(f"发现 {len(source_files)} 份基金经理筛选 Parquet，开始处理。")
    summaries = []
    for source_path in source_files:
        summary = process_one_file(
            source_path=source_path,
            fund_registry=fund_registry,
            ifind_dir=args.ifind_dir,
            output_dir=args.output_dir,
        )
        summaries.append(summary)
        print_summary(summary)

    print("\n" + "=" * 72)
    print(f"全部完成，共生成 {len(summaries)} 份 Parquet 文件。")
    print("本轮尚未应用首个净值出现后的缺失率筛选规则。")

    if args.skip_panel:
        print("已跳过 panel_base 生成。")
    else:
        print("\n" + "=" * 72)
        print("开始自动生成 panel_base。")
        panel_module = load_panel_module()
        panel_summary = panel_module.generate_panel(
            source_dir=args.output_dir,
            output_path=panel_module.DEFAULT_OUTPUT_PATH,
            return_type=args.panel_return_type,
            write_preview=True,
        )
        panel_module.print_panel_summary(panel_summary)


if __name__ == "__main__":
    main()
