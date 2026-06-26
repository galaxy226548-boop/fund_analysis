# B_factors 清洗流程說明

這個資料夾負責把上游產生的基金月度面板資料，清洗成後續回歸或分組分析可以直接使用的 `panel_base.parquet`。

目前主線流程是 `fm_baseline`，也就是 Fama-MacBeth baseline 用的一套 Consistency 因子清洗口徑。

## 目前有哪些重要檔案

- `config/fm_baseline.json`
  - JSON 版配置範例/快照，寫清楚輸入路徑、輸出路徑、要保留哪些欄位、怎麼篩樣本、哪些欄位要 winsorize、哪些因子要生成 q5/q10 分組標籤。
  - 日常更推薦讓 runner 直接讀 `D_analysis/config/regression_registry.py`，避免同一套口徑手工維護兩份。
- `scripts/run_factor_pipeline.py`
  - 新的配置驅動 runner。默認讀取 `D_analysis/config/regression_registry.py` 裡的 `fm_baseline`，按固定 step 順序執行清洗；也可以用 `--config` 讀 JSON。
- `scripts/1_fund_consistency_factors_clear.py`
  - 舊的大腳本，已保留。它和新 runner 目前應該生成一致結果。
- `scripts/tools/factor_pipeline_tools.py`
  - 共用工具函數，例如篩樣本、轉數值、winsorize、生成 q5/q10 分組。
- `scripts/steps/`
  - 拆開後的單步 CLI 腳本。它們主要方便逐步檢查，不是日常最推薦入口。
- `output/panel_base.parquet`
  - 最終清洗後的主輸出文件。
- `output/panel_base_preview.xlsx`
  - 預覽用 Excel，一般只放前若干行，方便人工快速查看。
- `output/panel_base_summary.json`
  - 清洗摘要，記錄行數、篩選條件、winsorize 配置和輸出欄位。

## 日常應該怎麼跑

在項目根目錄執行：

```bash
.venv/bin/python B_factors/scripts/run_factor_pipeline.py
```

這條命令會直接讀：

```text
D_analysis/config/regression_registry.py
```

裡面的 `fm_baseline`。這是目前推薦方式，因為只需要維護 registry 一個地方。

如果你想測試 JSON 範例配置，也可以：

```bash
.venv/bin/python B_factors/scripts/run_factor_pipeline.py --config B_factors/config/fm_baseline.json
```

跑完後主要看三個輸出：

```text
B_factors/output/panel_base.parquet
B_factors/output/panel_base_preview.xlsx
B_factors/output/panel_base_summary.json
```

如果只想跑舊大腳本，也可以：

```bash
.venv/bin/python B_factors/scripts/1_fund_consistency_factors_clear.py
```

目前我已經比對過：舊大腳本和新 runner 生成的 `panel_base.parquet` 行數、列名、逐列內容一致。

## `fm_baseline.json` 裡每個欄位是什麼

JSON 文件本身不能寫 `//` 或 `#` 註解，所以配置開頭用了 `_note` 和 `_field_notes` 來保存說明文字。這些欄位是合法 JSON，runner 會忽略它們。

真正參與處理的欄位是：

- `name`
  - 這套清洗配置的名稱。目前 runner 只接受 `fm_baseline`。
- `description`
  - 給人看的描述，不參與計算。
- `input_path`
  - 原始輸入 parquet。
- `output_path`
  - 最終清洗後 parquet 的輸出位置。
- `preview_path`
  - 預覽 Excel 的輸出位置。
- `summary_path`
  - 清洗摘要 JSON 的輸出位置。
- `date_col`
  - 月份/日期欄位。winsorize 和 q5/q10 分組都按這個欄位分月處理。
- `id_columns`
  - 識別基金月份觀測值的基礎欄位，例如基金代碼、月份、投資類型。
- `sample_filters`
  - 樣本篩選條件。例如 `"is_insample_future_ret_6m": 1` 表示只保留這個欄位等於 1 的行。
- `sample_flag_columns`
  - 樣本標記欄位，會保留到最終輸出，方便之後知道資料用了哪個樣本口徑。
- `y_columns`
  - 因變量欄位。目前是 `future_ret_6m`。
- `factor_columns`
  - 核心 Consistency 因子欄位。這些欄位會進入最終輸出，也會生成 q5/q10 分組標籤。
- `control_columns`
  - 控制變量欄位。
- `winsorize`
  - 極端值處理設定。
  - `group_column` 表示按哪一欄分組，目前是按 `month_date` 分月。
  - `lower_quantile` 和 `upper_quantile` 是裁剪分位點，目前是 1% 和 99%。
  - `columns` 是要做 winsorize 的欄位。
- `factor_group_suffixes`
  - q5/q10 分組標籤的命名映射。key 是原始因子欄位，value 是輸出標籤使用的短名稱。
- `steps`
  - runner 的執行順序。目前是：
    - `select_columns`
    - `sample_filter`
    - `coerce_numeric`
    - `winsorize`
    - `quantile_group`
    - `export_summary_preview`

## 如果要逐步檢查

可以看這份臨時運行說明：

```text
B_factors/scripts/steps/run_steps_debug.md
```

它會把每一步結果輸出到 `B_factors/output/debug_steps/`。中間文件含義如下：

- `01_selected_columns.parquet`
  - 只保留配置裡指定的欄位。
- `02_sample_filtered.parquet`
  - 根據 `sample_filters` 篩選樣本後的資料。
- `03_numeric_coerced.parquet`
  - 把 winsorize 需要的連續變量轉成數值型後的資料。
- `04_winsorized.parquet`
  - 完成按月 winsorize 後的資料。
- `05_grouped.parquet`
  - 生成 q5/q10 分組標籤後的資料，也就是最終 parquet 的主要內容。

## 之後新增其他清洗方法要怎麼做

如果新方法仍然使用目前這套處理步驟，也就是：

```text
選列 -> 篩樣本 -> 轉數值 -> winsorize -> 生成 q5/q10 -> 導出 summary/preview
```

那麼有兩種方式。

更推薦的方式是：先在

```text
D_analysis/config/regression_registry.py
```

新增一個模型 key，因為 runner 現在可以直接從 registry 讀配置。這樣 B_factors 和 D_analysis 不需要各自手工改一份。

另一種方式是複製 JSON 範例：

```text
B_factors/config/fm_baseline.json
```

另存為例如：

```text
B_factors/config/my_new_model.json
```

然後修改裡面的：

- `name`
- `description`
- `input_path`
- `output_path`
- `preview_path`
- `summary_path`
- `sample_filters`
- `y_columns`
- `factor_columns`
- `control_columns`
- `winsorize.columns`
- `factor_group_suffixes`

但是要注意：**目前 `run_factor_pipeline.py` 程式碼仍然只支持 `fm_baseline`。**

也就是說，現階段不是「只要新增 registry key 或 JSON 就能直接跑新模型」。現在的狀態是：

1. JSON 格式已經設計成可複製、可改欄位。
2. runner 可以從 registry 轉換出 B_factors 清洗配置。
3. runner 的處理流程已經配置化。
4. 但 runner 裡還有一個保守限制：只允許 `fm_baseline`。

下一步如果要正式支持多個模型，需要把 runner 裡這個限制放開，並加上基本檢查，例如：

- 配置文件必須包含必要欄位。
- `steps` 只能使用已支持的 step 名稱。
- 每個輸出路徑最好不要互相覆蓋。
- 新配置跑完後要和預期結果或中間檢查文件比對。

如果新清洗方法只是換欄位、換樣本、換輸出位置，通常只需要在 registry 新增一個模型配置，然後小改 runner 放開多 key 支持。

如果新清洗方法需要新的處理步驟，例如不做 q5/q10、改成 z-score 標準化、改 winsorize 方法、加入新的缺失值處理，那就不只是改 JSON，還需要新增工具函數和 runner step。

## 建議的安全檢查

每次改配置或 runner 後，建議至少檢查：

```text
行數是否符合預期
列數是否符合預期
列名是否符合預期
關鍵欄位缺失值是否符合預期
q5/q10 標籤分布是否合理
```

目前可以用這個腳本做基本檢查：

```bash
.venv/bin/python B_factors/scripts/check_panel_base_baseline.py
```

它會讀取 `B_factors/output/panel_base.parquet`，輸出行數、列數、列名、缺失值、數值列統計和 q5/q10 分布。
