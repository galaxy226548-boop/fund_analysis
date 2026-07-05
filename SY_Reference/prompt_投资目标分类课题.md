# 交接 Prompt：按基金投資目標分類重構一致性指標（新課題）

（以下全文可直接貼給新會話）

---

# 任務：按基金「投資目標分類」重構一致性指標的排名基準（課題第三部分）

## 項目背景
基金業績一致性研究項目，倉庫 /Users/chloezh/Projects/Fund_Analysis，用 .venv/bin/python 運行，命令在倉庫根目錄執行。已有兩代指標：普通一致性（FAC_rank_vol_m{m}_n{n}_pairwise1 = 1 − 過去 n 期 m 月收益截面排名的標準差；winrates top50 命中系列）和市態條件一致性（FAC_rank_vol_{regime}_...）。現有排名的截面是「月份 × 投資類型（二級分類）」。

本課題的創新：把排名的同類基準從「二級投資類型」改為「投資目標分類」，並對相對類基金改用超額收益排名：
- 分類代碼 1 = 絕對收益類（4,131 只）：用原始 m 月累計收益，在同月同類（代碼1）基金中排名；
- 分類代碼 2 = 相對市場類（僅 252 只，樣本量是重大風險，見「第一階段」）：用基金 m 月收益 − HS300 同期收益，在同月代碼2基金中排名；
- 分類代碼 3 = 相對基準指數類（3,011 只）：用基金 m 月收益 − 該基金自己的基準指數同期收益，在同月代碼3基金中排名。

**必須先向使用者指出的方法論問題**：對代碼2，全組減去同一個 HS300 收益後排名不變（減常數是排名不變變換），所以「HS300 超額」對組內排名類指標是恆等操作；只有代碼3（每只基金減自己的基準）才真正改變排名。請在開工前把這一點連同你的處理建議（例如代碼2直接用原始收益排名並在文檔註明等價性）報給使用者確認。

## 數據源（已探查過的事實）
1. 投資目標分類：A_data/prepared_data/iFind_terminal_fund_center/iFind偏股混合型基金投资目标.xlsx（6,070 行）和 iFind普通股票型基金投资目标.xlsx（1,328 行）。關鍵列：证券代码（如 000006.OF）、投资目标分类代码（1.0/2.0/3.0，各有 2 行 NaN）、基准指数代码（如 000006.BI）、业绩比较基准（文本）。
2. 基準指數淨值：A_data/data/iFind_API/ 下 4 個檔（偏股混合型/普通股票型 × 存續/已到期，檔名含「基准指数净值变化」）。寬表：每行一只基金（列「基准指数」=.BI 代碼、「证券代码」=.OF 代碼），其後每列是月末日期、值是基準指數淨值；**值為 0 表示未成立/缺失，換算收益前必須把 0 當缺失**。基準 m 月收益 = NAV(t)/NAV(t−m) − 1。
3. HS300 月收益：A_data/prepared_data/ifind_edb/HS300_CSI800_CSI1000_mrt.xlsx，列 HS300_monthly_return，日期列「日期」需 .dt.to_period("M") 對齊。
4. 面板：A_data/output/panel_base.parquet（406,918 行，基金月度長表，主鍵 ifind_code+month_date），含 nav、is_sample、is_size_eligible_t、is_insample_future_ret_6m、past_ret_{m}m_1..（過去收益窗口原料列）等。熱力圖面板 panel_base_heatmap_m1_12_n1_12.parquet 同行數。

## 硬性規則
1. Python 檔案裡絕對禁止中文彎引號（“ ” ‘ ’）。
2. 動手寫或改任何 .py 前，先給出方案徵得使用者批准。
3. 只新增列，不改動面板已有列；行數行序不變；腳本可重複運行（先刪自有舊列）；臨時檔+回讀校驗+os.replace 原子寫盤。
4. 先讀這些腳本再動手（照抄工程模式與口徑）：
   - A_data/scripts/3_panel_base_mkt_condition_factors.py（最重要：pyarrow 追加列、暴力復算抽查、校驗表輸出的完整範本；注意其 winrate dummy 用累計編碼 hit_above{k-1}，新指標沿用當前這套編碼）
   - A_data/scripts/3_generate_panel_base.py（past_ret 窗口和排名的原始口徑）
   - A_data/scripts/Config.py（路徑常量、PANEL_PAST_RETURN_COMBOS = 五套主窗口 (3,6)/(6,3)/(6,6)/(6,12)/(12,6)）
   - D_analysis/config/regression_registry.py 開頭的 helper 函數與 fm_baseline 配置（將來建模時的命名兼容性）
5. 使用者近期修過 bug（未來收益 regime 對齊、熱力圖 FDR），一切以當前工作區代碼為準，不要按舊描述臆測。

## 執行階段（每階段結束向使用者匯報再進下一階段）

### 第一階段：分類映射 + 樣本量門檻檢查（必須先做，是 go/no-go 閘門）
1. 合併兩張投資目標表，把 证券代码(.OF) 映射到面板 ifind_code（先檢查面板 ifind_code 的格式再定映射規則），生成月度面板新列 objective_class（1/2/3/NaN）。
2. 產出檢查表：每月 is_sample=True 基金中三類各有多少只；特別是代碼2的月度數量分佈（min/median），對照回歸的 min_cross_section_n=50。
3. 面板中匹配不到分類的基金數量與清單樣本。
4. **拿檢查結果向使用者匯報並等待決策**：代碼2是否併入代碼3、還是單獨保留但不做 FM 回歸。同時報告上文「代碼2排名不變性」問題。

### 第二階段：基準超額收益（僅代碼3需要）
1. 從 4 個基準淨值檔構建 (ifind_code, month) → 基準指數 m 月收益（m=3/6/12），0 視為缺失。
2. 校驗：抽 10 只基金人工核對基準收益與淨值比值；統計代碼3基金中基準淨值覆蓋率；報告 .BI 淨值中途斷檔的處理（斷檔月的超額收益記缺失，不填補）。

### 第三階段：目標分類版因子構造
新腳本 A_data/scripts/3_panel_base_objective_factors.py：
- 排名截面 = 月份 × objective_class（取代月份 × investment_type；這是設計假設，先向使用者確認）；代碼1/2 用原始 m 月收益排名，代碼3 用超額收益排名。
- 對五套主窗口 (m,n) 生成：FAC_rank_vol_obj_m{m}_n{n}_pairwise1（=1−排名標準差）、rank_mean_obj_...、is_median_/is_tercile_...（邊界抄 3_panel_base_grouping_factors.py）、hitcount/hitrate_top50_obj_... 與累計 dummy hit_above{k-1}（命中=組內排名>0.5，只做 top50）。
- 注意：每只基金的指標只在其所屬類的組內排名上計算，但列是全體基金共用的（不同類的值來自不同分母組）。
- 驗證：純 Python 暴力復算抽樣（獨立代碼路徑）；rank_mean∈[0,1]；行數主鍵原列不變；輸出校驗表（各類覆蓋率、每窗口有效月份數≥50 統計）。
- 寫入 panel_base.parquet 與熱力圖面板（按主鍵對齊）。

### 第四階段（若額度允許才做，否則記錄計劃）
(m,n) 口徑：主結果只用五套預先指定窗口；12×12 全網格作穩健性、配 FDR 校正（與現有熱力圖流程一致）——不做自由尋優，避免 p-hacking。模型登記（registry 工廠模式仿 make_mkt_state_models）與回歸留給下一階段，控制變量中投資類型 dummy 是否換成目標分類 dummy 需使用者拍板。

## 已知踩坑
- 面板 month_date 是 timestamp，月份比較先 to_period("M")；PeriodIndex 差值不能直接和整數比（先 .asi8）。
- 樣本內標記列叫 is_insample_future_ret_6m。
- 熱力圖面板 2,500+ 列，用 pyarrow read_table + append_column，不要整表進 pandas。
- zsh 下 for m in $VAR 不分詞，批量循環用文件逐行讀。
- 完成每個小任務提醒使用者查 /usage；若使用者說額度低於 18%，改為生成給其他 AI 的交接 prompt。
