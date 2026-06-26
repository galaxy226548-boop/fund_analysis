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
