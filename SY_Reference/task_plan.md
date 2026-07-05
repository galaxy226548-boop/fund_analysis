# 市態一致性課題任務計劃（無人值守執行記錄）

更新時間：2026-07-02（Claude 自動維護）

## 任務狀態總覽

| 階段 | 內容 | 狀態 |
|---|---|---|
| P1 | 市態列腳本 3_panel_base_mkt_condition.py | completed |
| P2 | 市態條件因子腳本 3_panel_base_mkt_condition_factors.py（回看上限 48） | completed |
| P3 | 狀態匹配 Y 腳本 3_panel_base_mkt_condition_future_returns.py（外部 AI 完成，已驗收通過） | completed |
| P4 | registry 登記市態模型 + 引擎伴生因子支持 + 冒煙測試 | completed |
| P5 | 全量跑批 32 個市態模型 + 與舊模型對比表 | completed |
| P6 | 熱力圖穩健性 + PPT 更新 | suspended |

## P5 執行狀態

- fm_baseline_hs300 冒煙測試：四步全過，結果結構正確（10 因子 × 8 變量，n_months 與 P2 診斷吻合）。
- 其餘 31 個模型跑批：2026-07-02 08:53 啟動，後台順序執行，日誌見
  `/private/tmp/claude-501/-Users-chloezh-Projects-Fund-Analysis/65c83424-a650-486d-a359-01208971052f/scratchpad/mkt_state_batch.log`，
  失敗的模型會標記 `!!! FAILED: {key}` 且不中斷後續模型。
- 跑批完成後的下一步：彙總對比表（市態 vs 普通模型的係數/t 值/adj R²/VIF），輸出到
  `D_analysis/output/fund_consistency/mkt_condition_comparison/`。
- 已建一次性定時任務 `resume-mkt-condition-batch`（2026-07-02 14:30 本地時間觸發）：
  若本會話因額度中斷，新會話會讀本文件接續；若跑批仍在進行（日誌 15 分鐘內有更新）則不重複啟動。

## 無人值守期間的自主決策記錄

（每條決策附理由，供使用者回來後審查）

1. **marginal 模型補入普通 rank_mean 主效應**：使用者的公式只寫了一個 rank_mean_c，但回歸引擎的交互項層級守衛（get_interaction_main_effect_columns）強制要求交互項兩側變量都有主效應，普通交互項 FAC_c:rank_mean_c 缺普通 rank_mean 主效應會直接報錯。故 marginal 模型 = 市態 FAC_c + 市態 rank_mean_c + 市態交互_c + 普通 FAC_c + 普通 rank_mean_c + 普通交互_c + Ctrl(5)。
2. **引擎新增 FAC_PLAIN / RANK_MEAN_PLAIN 佔位符**（consistency_fama_mac_regression.py 和 2_factor_correlation.py 各加一處解析）：從市態因子名 FAC_rank_vol_{regime}_m*_n*_pairwise* 剝離 regime 片段推導同期限普通列。portfolio_sorting.py 未改——marginal 模型的組合排序用默認因子（市態 FAC 本身），不涉及新佔位符。
3. **marginal 的 winsorize 覆蓋普通 FAC**：普通 FAC 在 fm_baseline 裡本來就縮尾，進 marginal 保持同口徑；rank_mean 系列按現有慣例不縮尾。
4. **ymatch 模型的樣本標記**：用 Y 對應 regime 的 is_insample_future_ret_6m_{regime}（=第 6 個未來市態月不晚於 2022-12）；cross 反證模型用「Y 側」regime 的標記（樣本由因變量定義）。
5. **市態 winrates 僅登記 top50 dummy 組口徑**（鏡像 fm_winrates_top50），hitrate 列已在面板中備好但暫不單獨建模，待 top50 結果出來再決定是否補 hitrate 主效應層。
6. **32 個模型 key 全部走四步 pipeline**（preprocess → correlation_check → regression → portfolio_sorting），不含 descriptive 步驟（非必要，後續按需補）。

7. **ymatch 系列移除 portfolio_sorting 步驟**：狀態匹配 Y 的日曆持有期逐月不同，固定持有期的組合排序方法論不適用（排序腳本也明確拒絕解析此類 Y 列名）。16 個 ymatch 模型的回歸結果本身完整有效。
8. **對比腳本 summarize_mkt_condition_models.py 的 markdown 輸出改用 to_string**：.venv 缺 tabulate 依賴，避免安裝新包。
9. **定時任務 resume-mkt-condition-batch 已停用**：跑批在本會話內全部完成，無需額度重置後接續。

## P5 結果摘要（詳見 D_analysis/output/fund_consistency/mkt_condition_comparison/headline_findings.md）

- 32 個模型全部跑通（ymatch 的組合排序步驟按決策 7 移除）。
- **總體信號偏弱**：市態 M1 的 40 個規格中僅 4 個顯著（5% 水平下期望假陽性約 2 個）；M3' 交互 2/40；狀態匹配 3/40 顯著、匹配強於錯配僅 23/40。向使用者匯報時需如實說明。
- **最一致的信號集群：lowvol（低行業波動市態）× m6_n12**——M1 t=+3.92、marginal 中市態 FAC 仍 t=+2.14（普通項同場、VIF 全 ok）、狀態匹配 t=+5.29 且強於錯配。方向為正：低波動市裡排名越穩定的基金未來收益越高。注意該規格有效月份僅 57–61 個月。
- 兩個符號翻轉案例：hs300up m12_n6 與 large m12_n6 的市態 FAC 顯著為正而普通 FAC 為負。
- marginal 模型共線性擔憂未成真：月內去均值後 VIF 全部 < 3.6。
- style 維度的狀態匹配反證出現反直覺結果（growth m12_n6 匹配項顯著為負），需人工解讀。

## 障礙記錄

（需要使用者提供資訊才能繼續的任務記在這裡，狀態改 suspended）

- **P6 suspended**，兩個子項都需要使用者決策：
  1. 熱力圖穩健性：全網格市態因子 = 144 窗口 × 8 regime × 多列族，列數會爆炸（數萬列），需要使用者確認範圍（建議只對 lowvol/hs300 兩個維度、FAC+rank_mean 兩個列族做全網格）；
  2. PPT 更新：總體結果偏弱、僅個別規格集群顯著，敘事定調（「市態拆分無增量」vs「僅低波動市態有狀態依賴性」）應由使用者決定，不宜自主代筆結論。

## 新方向登記（2026-07-02，使用者提出）

**Q 系列：按投資目標分類重構一致性指標**（絕對收益類 4,131 只 / 相對市場類 252 只 / 相對基準指數類 3,011 只；相對類用超額收益排名）。交接 prompt 已備好：SY_Reference/prompt_投资目标分类课题.md，計劃在新會話執行。兩個開工前必須解決的方法論問題已寫入 prompt：① 相對市場類全組減同一 HS300 收益對組內排名是恆等變換；② 相對市場類僅 252 只，月度截面大概率不足 50。
