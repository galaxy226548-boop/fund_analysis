"""
合并 iFind / Wind 基本信息文件，并生成基金注册表。

当前纳入偏股混合型基金和普通股票型基金。Excel 文件使用 calamine
读取，因为部分 Wind 文件包含 openpyxl 无法解析的异常样式定义。
"""
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
IFIND_DIR = PROJECT_ROOT / "A_data/data/iFind_terminal_fund_center"
WIND_DIR = PROJECT_ROOT / "A_data/data/Wind_terminal_fund_center"
CSMAR_FILE = PROJECT_ROOT / "A_data/data/data_csmar/xlsx/FUND_MainInfo.xlsx"
REGISTRY_OUT = PROJECT_ROOT / "A_data/data/fund_registry.xlsx"
ENGINE = "calamine"

# 明确列出基金类型，避免通配符误读上一次生成的“基金基本信息汇总.xlsx”。
FUND_TYPES = ("偏股混合型基金", "普通股票型基金")
WIND_SORT_MARKS = "↑↓"


def read_excel(path: Path, **kwargs) -> pd.DataFrame:
    """统一读取 Excel，并在依赖缺失时给出可直接执行的修复提示。"""
    if not path.exists():
        raise FileNotFoundError(f"未找到输入文件：{path}")

    try:
        return pd.read_excel(path, engine=ENGINE, **kwargs)
    except ImportError as exc:
        raise RuntimeError(
            "读取 Excel 需要 python-calamine，请先运行："
            ".venv/bin/python -m pip install -r requirements.txt"
        ) from exc


def normalize_wind_columns(df: pd.DataFrame) -> pd.DataFrame:
    """去掉 Wind 导出列名里可能残留的排序箭头。"""
    normalized = df.copy()
    normalized.columns = [
        str(column).strip().rstrip(WIND_SORT_MARKS) for column in normalized.columns
    ]
    return normalized


def is_meaningless_tail_row(row: pd.Series) -> bool:
    """判断 Wind 导出表末尾的单行是否只是空行或文件来源说明。"""
    values = row.dropna()
    if values.empty:
        return True

    # Wind 终端常在最后一行第一列写“数据来源：Wind”，这一行不是基金记录。
    text_values = values.astype(str).str.strip()
    return text_values.str.contains("数据来源", na=False).any()


def drop_meaningless_tail_rows(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    """只检查并删除表格最下面两行中的无意义尾行。"""
    cleaned = df.copy()
    removed = 0

    # 需求只要求检查最下面两行，因此最多循环两次；每删一行后继续看新的最后一行。
    for _ in range(2):
        if cleaned.empty:
            break
        if not is_meaningless_tail_row(cleaned.iloc[-1]):
            break
        cleaned = cleaned.iloc[:-1].copy()
        removed += 1

    if removed:
        print(f"清理尾行：{path.name} 删除 {removed} 行")
    return cleaned


def merge_wind_existing_basic_info() -> None:
    """先把 Wind 中不同存续状态的基本信息文件合并回对应基金类型主文件。"""
    for fund_type in FUND_TYPES:
        base_file = WIND_DIR / f"{fund_type}基本信息.xlsx"
        extra_files = sorted(WIND_DIR.glob(f"Wind{fund_type}*基本信息.xlsx"))
        if not extra_files:
            continue

        # 主文件决定最终列顺序；列名先去掉 Wind 排序箭头，避免“同一列”被误判为不同列。
        base = normalize_wind_columns(
            drop_meaningless_tail_rows(read_excel(base_file), base_file)
        )
        frames = [base]

        for extra_file in extra_files:
            extra = normalize_wind_columns(
                drop_meaningless_tail_rows(read_excel(extra_file), extra_file)
            )
            missing_columns = [
                column for column in base.columns if column not in extra.columns
            ]
            extra_only_columns = [
                column for column in extra.columns if column not in base.columns
            ]
            if missing_columns or extra_only_columns:
                raise ValueError(
                    f"{extra_file.name} 与 {base_file.name} 列名不一致："
                    f"缺少主文件列 {missing_columns}；额外列 {extra_only_columns}"
                )

            # 使用主文件列顺序对齐，保证后续读取 Wind 基本信息时得到稳定的列结构。
            frames.append(extra.reindex(columns=base.columns))

        merged = pd.concat(frames, ignore_index=True)
        before_dedup = len(merged)
        # 让脚本可以重复运行：如果主文件已经合并过同一批补充记录，重复行会在这里被去掉。
        merged = merged.drop_duplicates(ignore_index=True)
        merged.to_excel(base_file, index=False)
        print(
            f"Wind 存续状态基本信息合并：{fund_type} "
            f"{len(base)} 行 + {sum(len(frame) for frame in frames[1:])} 行，"
            f"去重 {before_dedup - len(merged)} 行 -> {base_file}"
        )


def normalize_fund_code(value):
    """将 Excel 中可能以数字或浮点数保存的基金主代码统一为六位字符串。"""
    if pd.isna(value) or str(value).strip().lower() in {"", "nan"}:
        return pd.NA

    text = str(value).strip()
    try:
        return str(int(float(text))).zfill(6)
    except ValueError:
        # 非纯数字代码不应被静默删除，保留原值以便后续人工核查。
        return text.zfill(6)


def main() -> None:
    # 先把 Wind 终端按存续状态单独导出的基本信息补回主文件，再进入原有汇总流程。
    merge_wind_existing_basic_info()

    # iFind 文件名带有 iFind 前缀，Wind 文件名没有此前缀。
    ifind_files = [IFIND_DIR / f"iFind{fund_type}基本信息.xlsx" for fund_type in FUND_TYPES]
    wind_files = [WIND_DIR / f"{fund_type}基本信息.xlsx" for fund_type in FUND_TYPES]

    # 合并两类基金的基本信息，汇总文件仅作为输出，不参与下一次输入。
    ifind_all = pd.concat([read_excel(path) for path in ifind_files], ignore_index=True)
    ifind_out = IFIND_DIR / "iFind基金基本信息汇总.xlsx"
    ifind_all.to_excel(ifind_out, index=False)
    print(f"iFind 汇总：{len(ifind_all)} 行 -> {ifind_out}")

    wind_all = pd.concat([read_excel(path) for path in wind_files], ignore_index=True)
    wind_out = WIND_DIR / "Wind基金基本信息汇总.xlsx"
    wind_all.to_excel(wind_out, index=False)
    print(f"Wind 汇总：{len(wind_all)} 行 -> {wind_out}")

    # 注册表直接取自两类 iFind 合并数据，因此普通股票型基金也会进入结果。
    src = ifind_all[
        ifind_all["证券代码"].notna()
        & ~ifind_all["证券代码"].astype(str).str.contains("数据来源", na=False)
    ].copy()

    keep = {
        "证券代码": "iFind代码",
        "证券名称": "证券名称",
        "基金主代码（官方）": "基金主代码",
        "基金成立日": "基金成立日",
        "投资类型（二级分类）": "投资类型（二级）",
    }
    registry = src[list(keep)].rename(columns=keep)
    registry["基金主代码"] = registry["基金主代码"].map(normalize_fund_code)

    # 将平台代码放到描述字段之后，便于人工查看注册表。
    cols = [column for column in registry.columns if column != "iFind代码"] + ["iFind代码"]
    registry = registry[cols]

    # 日期统一为 date，防止 Excel 时间部分影响跨数据源匹配。
    wind_all["基金成立日"] = pd.to_datetime(wind_all["基金成立日"], errors="coerce").dt.date
    registry["基金成立日"] = pd.to_datetime(
        registry["基金成立日"], errors="coerce"
    ).dt.date
    wind_all["基金主代码(官方)"] = wind_all["基金主代码(官方)"].map(normalize_fund_code)

    # Wind 同一主代码和成立日可能有多条份额记录，沿用原逻辑保留一条代码。
    wind_key = (
        wind_all[["基金主代码(官方)", "基金成立日", "证券代码"]]
        .rename(columns={"基金主代码(官方)": "基金主代码", "证券代码": "Wind代码"})
        .drop_duplicates(subset=["基金主代码", "基金成立日"])
    )
    registry = registry.merge(wind_key, on=["基金主代码", "基金成立日"], how="left")
    matched_wind = registry["Wind代码"].notna().sum()
    print(f"匹配到 Wind 代码：{matched_wind} / {len(registry)} 行")

    # CSMAR 前两行是字段说明，不属于实际基金记录。
    csmar = read_excel(CSMAR_FILE, header=0, skiprows=[1, 2])
    csmar.columns = csmar.columns.str.strip()
    csmar["InceptionDate"] = pd.to_datetime(
        csmar["InceptionDate"], errors="coerce"
    ).dt.date
    csmar["MasterFundCode"] = csmar["MasterFundCode"].map(normalize_fund_code)

    csmar_key = (
        csmar[["MasterFundCode", "InceptionDate", "FundID"]]
        .rename(
            columns={
                "MasterFundCode": "基金主代码",
                "InceptionDate": "基金成立日",
                "FundID": "CSMAR代码",
            }
        )
        .drop_duplicates(subset=["基金主代码", "基金成立日"])
    )
    registry = registry.merge(csmar_key, on=["基金主代码", "基金成立日"], how="left")
    matched_csmar = registry["CSMAR代码"].notna().sum()
    print(f"匹配到 CSMAR 代码：{matched_csmar} / {len(registry)} 行")

    registry.to_excel(REGISTRY_OUT, index=False)
    type_counts = registry["投资类型（二级）"].value_counts(dropna=False).to_dict()
    print(f"注册表：{len(registry)} 行 -> {REGISTRY_OUT}")
    print(f"基金类型分布：{type_counts}")
    print(f"列顺序：{registry.columns.tolist()}")


if __name__ == "__main__":
    main()
