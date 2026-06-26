# clean_CSMAR.py 使用说明

`clean_CSMAR.py` 用于清洗 CSMAR 导出的三行表头 Excel 文件，并把清洗结果与数据清单统一写入 `A_data/output`。

## 1. 完成的清洗工作

- 读取 CSMAR 标准三行表头：
  - 第 1 行：英文字段名，作为清洗后数据列名。
  - 第 2 行：中文字段名，用于校验表头一致性。
  - 第 3 行：单位，用于校验表头一致性。
  - 第 4 行开始：正式数据。
- 支持一个或多个 Excel 文件输入；多个文件或多个 sheet 会先检查前三行表头是否完全一致。
- 如果前三行表头一致，会把所有数据行合并为一个输出文件；如果不一致，程序停止并提示不一致的文件和 sheet，不写主输出。
- 清理全空行、空字符串、`NA`、`N/A`、`--`、`-`、`没有单位` 等常见空值。
- 自动识别日期列，例如 `TradingDate`、`Date`、`Accper`、`StartDate`、`EndDate`、`交易日期`、`统计日期` 等。
- 日期类字段会转为 datetime；代码、ID、名称、类别、状态、说明等字段保留为字符串；其他字段尽量转为数值。
- 如果存在 `Typrep` 列，默认只保留 `Typrep == "A"` 的记录。
- 输出为 parquet 时，会使用流式读取 Excel 数据，降低多文件大数据合并时的内存压力；最终 parquet 会按日期升序排列，并把日期保存为 `date` index。
- 输出为 Excel 时，会按用户指定的 `.xlsx`/`.xls` 文件保存。
- 自动推断数据频率，写入 `trading_day`、`daily`、`monthly`、`quarterly`、`semiannually`、`yearly` 或 `unknown`。推断逻辑：
  - 月份只有 12 月 → `yearly`
  - 月份只有 6/12 月 → `semiannually`
  - 月份为 {3,6,9,12,1} 的子集且至少出现其中 4 个 → `quarterly`
  - 日期差 60% 以上为 +1 天、且 +1 与 +3 之和占 90% 以上 → `trading_day`
  - 日期差 80% 以上为 +1 天 → `daily`
  - 月份差 80% 以上为 +1 个月 → `monthly`
  - 以上都不满足 → `unknown`
- 每次运行后更新 `A_data/reference/data_inventory_A.json`：根据输入文件路径（`file_path` 列）定位对应记录，将输出文件路径写入 `clean_data` 列，将推断频率写入 `frequency` 列。
- 自动查找与源 Excel 文件名相关的 `.txt` 说明文件：
  - 搜索源文件所在目录、同级 `txt` 目录（如源文件在 `data_csmar/xlsx` 时会额外搜索 `data_csmar/txt`）和 `A_data/data`。
  - 对类似 `FUND_MKT_Quotation1.xlsx` 的拆分文件，也会匹配去掉末尾数字后的文件名。
  - 找到后复制到 `A_data/output`。
  - 在 `data_inventory.json` 中为说明文件增加记录。
  - 将说明文件内容追加到 `A_data/output/data_guide.md`，并在内容前写入 txt 文件名标题。

## 2. 接收的输入

脚本接收以下输入：

- 一个或多个待清洗 Excel 文件路径。
  - 可以直接作为位置参数传入。
  - 也可以通过 `--files` 传入逗号分隔的路径。
  - 如果命令行没有传入文件路径，程序会进入交互模式，让用户逐行输入路径，空行结束。
- 输出文件名，通过 `--output` 指定；如果不指定，程序会交互询问。
  - 有后缀时按后缀保存，例如 `.parquet`、`.xlsx`、`.xls`。
  - 没有后缀时默认补成 `.parquet`。
  - 输出文件统一保存到 `A_data/output`，除非额外指定 `--output-dir`。
- 数据描述，通过 `--content` 指定；如果不指定，程序会交互询问。
  - 该内容会写入 `data_inventory.json` 的 `content` 字段。
- 可选输出目录：
  - `--output-dir`，默认是 `A_data/output`。

## 3. 命令行调用方式

在项目根目录 `/Users/chloezh/Projects/Fund_Analysis` 下运行。

单文件清洗为 Excel：

```bash
python3 A_data/scripts/clean_CSMAR.py \
  A_data/data/FUND_MainInfo.xlsx \
  --output FUND_MainInfo_clean.xlsx \
  --content 基金基本信息
```

多文件合并清洗为 parquet：

```bash
python3 A_data/scripts/clean_CSMAR.py \
  A_data/data/FUND_MKT_Quotation.xlsx \
  A_data/data/FUND_MKT_Quotation1.xlsx \
  A_data/data/FUND_MKT_Quotation2.xlsx \
  A_data/data/FUND_MKT_Quotation3.xlsx \
  --output FUND_MKT_Quotation_clean.parquet \
  --content 基金行情数据
```

使用 `--files` 传入逗号分隔路径：

```bash
python3 A_data/scripts/clean_CSMAR.py \
  --files "A_data/data/FUND_MKT_Quotation.xlsx,A_data/data/FUND_MKT_Quotation1.xlsx" \
  --output FUND_MKT_Quotation_part.parquet \
  --content 基金行情数据
```

交互式运行：

```bash
python3 A_data/scripts/clean_CSMAR.py
```

交互式运行时，程序会依次要求输入：

1. 待清洗文件路径，可以一行一个，也可以用逗号分隔；输入空行结束。
2. 输出文件名。
3. `content` 数据描述。

指定其他输出目录：

```bash
python3 A_data/scripts/clean_CSMAR.py \
  A_data/data/FUND_MainInfo.xlsx \
  --output FUND_MainInfo_clean.parquet \
  --content 基金基本信息 \
  --output-dir A_data/output
```

运行结束后，主要输出位于：

- `A_data/output/<输出文件名>`
- `A_data/output/data_inventory.json`
- `A_data/output/data_guide.md`，仅当找到相关 `.txt` 说明文件时创建或更新
- 复制后的相关 `.txt` 说明文件
