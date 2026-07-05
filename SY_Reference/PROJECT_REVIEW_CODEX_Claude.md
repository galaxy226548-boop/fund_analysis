# Codex Project Review

审查日期：2026-07-02 初审；2026-07-05 增量复审（America/Los_Angeles）  
审查方式：只读静态审查、Git 工作树边界核对、配置与代表性结果交叉核验、Parquet schema 读取、Excel 文件级轻量盘点。  
安全声明：本轮除本报告外，没有修改、创建、删除、移动或重命名任何项目文件；没有修改数据；没有运行回归、重算或大规模测试；没有 commit；没有调用 DeepSeek。曾按本轮最高优先级要求尝试 `git push origin main`，但当前没有领先远端的本地提交，且 GitHub CLI token 失效/推送无法完成，因此没有远端变更。2026-07-02 初审后经用户明确授权实施的修复，另按下方“后续修复记录”追踪。

后续修复记录（2026-07-02）：用户确认研究对象要求未来收益持有期不跨基金经理 regime 后，已实施 horizon-specific 样本补丁。普通 `future_ret_1m/3m/6m/12m` 模型现在同时要求对应期限的 `is_insample_* = 1` 与 `match_is_sample_* = 1`；C2、C3 已修复并通过 38 个轻量单元测试。2026-07-05 增量核验时，当前 100 个模型 metadata/schema 均显示该筛选已经进入配置；但结果仍未绑定唯一 git commit，不能仅凭目录时间证明完整复现链。

后续修复记录（2026-07-05）：用户接受“按全样本信息静态选择代表份额”的口径，因为该标签仅用于同一 `main_code` 内去重、不作为预测变量；原 C1 降级为已接受的样本构造说明。FAC 热力图已新增 Full sample 主检验模型、BH-FDR 代码并刷新正式 `heatmap_summary`；当前结果是 Full sample 主候选 0 个、探索候选 5 个、稳健候选 0 个。

## 2026-07-05 增量复审结论（相对 commit `845d6b6` / `origin/main`）

### A. 本轮边界与只读验证

- `HEAD` 与 `origin/main` 均为 `845d6b6`；没有本地提交领先远端。因此“上次 push 后新增/更改”就是当前工作树。
- 当前工作树共 3,258 个变更文件：125 个 Markdown、38 个 Python、452 个 JSON、125 个 Excel、2,059 个 CSV、447 个 PNG；大量为批量模型结果。没有变更 Parquet、Pickle 或数据库文件。
- 对 38 个新增/修改 Python 文件做内存 AST 解析：0 个语法错误。
- 对 452 个新增/修改 JSON 做解析：0 个格式错误。
- 当前 registry 有 100 个正式模型；逐一读取其 `preprocess_input_path` 的 Parquet schema，100 个模型均能找到声明的 Y、factor、control、sample filter 与 factor filter 列；没有重复 `output_dir`，普通 `future_ret_{h}m` 模型均同时登记同期限 `is_insample_*` 与 `match_is_sample_*`。
- FDR registry 共 24 个 family（19 active、3 pending、1 blocked、1 not_required）；22 个 active/pending family 的所有来源文件均存在、selector 均能选出非空结果。六个 FAC heatmap family 各为 132 项，已正确排除数学上无定义的 n=1。
- 未运行 pytest、回归、ETL、回测、描述统计或结果重算；Excel 只按路径/文件名/大小盘点，没有打开内容。

### B. 本轮已确认的代码层进展

1. m/n 注释已在核心 Python 中修正：`m=return_horizon`、`n=rank_count`；完全非重叠规格为 `pairwise=m`。
2. 普通未来收益模型的 horizon-specific `is_insample` 与 `match_is_sample` 已通过 registry 统一补齐；100 个当前模型的 schema 静态核验通过。
3. FAC heatmap 从 144 个名义格改为 132 个可定义格（n=2..12）；最新 `heatmap_summary` 已生成 BH-FDR 结果：Full sample 主检验候选为 0，只有 5 个探索分组候选，不能升级为总体主结论。
4. 普通、市态和 benchmark winrate 的活动 registry 已统一为累计 dummy `D_k=1(hitcount>=k)`；旧互斥 `_hitN_` 列由生成脚本定向清理。
5. `bm33` 已降为兼容别名，活动 registry 使用 `bottom33`；跨期限分组新增自身的中位数/三分位标记，避免借用别的分组口径。
6. 新增基准超额一致性、投资目标分类、市态一致性、跨 Y 期限、跨期限 rank-vol、FDR、结果汇总和批量 runner。相对 2026-07-02 的 78 模型冻结点，registry 新增 22 个正式模型，当前合计 100 个。

### C. 本轮新增/更新的高风险发现

#### C6. 状态匹配未来收益没有证明整个预测区间属于同一经理 regime（Critical，需人工确认）

- 位置：`A_data/scripts/3_panel_base_mkt_condition_future_returns.py` 的 `calculate_regime_returns()`。
- 表现：代码对六个被选中的状态月分别检查 `tau-1` 与 `tau` 两端的 `is_sample`、规模资格和 NAV；但跳过的非目标状态月份不检查经理是否变化，也没有生成/使用类似普通未来收益的 `match_is_sample_future_ret_*` 全区间标签。
- 影响：若 t 后发生经理变更，经过新的 12 个月稳定期后 `is_sample` 再次变为真，六个目标状态月可能把前后两任经理的收益复合到同一个 Y。这样 `fm_ymatch_*` 可能不再衡量 t 时点经理/基金 regime 的后续能力，与已确认的“未来持有期不跨经理 regime”原则不一致。
- 建议：先人工确认状态匹配 Y 的研究对象究竟是“基金产品跨经理表现”还是“t 时点经理 regime 表现”。若仍要求同一 regime，应为从 t+1 到第六个目标状态月的整个日历跨度生成同经理/同样本匹配标签，并在 ymatch registry 中筛选。
- 本轮未修改、未重算。

#### M11. 市态重点摘要仍使用名义 |t|，未消费已登记的 FDR 结果（Major）

- 位置：`D_analysis/scripts/summarize_mkt_condition_models.py:39`、`write_headline_findings()`；产物 `mkt_condition_comparison/headline_findings.md`。
- 表现：摘要用 `|t|>=1.96` 选“显著规格”，而 FDR registry 已把市态主效应、交互与边际效应分别登记为跨四类市态的 40 项 family。
- 影响：自动摘要可能把 nominal significance 当作正式结论，与项目当前 BH-FDR 主线不一致；状态匹配 vs 错配只比较两边 |t| 大小，没有对系数差做直接检验。
- 建议：摘要读取统一 FDR 输出中的 q-value；“matched stronger”只作描述统计，待具备 matched-cross 直接 contrast p-value 后再进入正式推断。

#### M12. 市态 winrate 汇总脚本仍匹配旧 `_hitN_`，与当前 `_hit_aboveN_` 不兼容（Major）

- 位置：`summarize_mkt_condition_models.py:296-304` 的正则。
- 表现：正则要求 `_hit(?P<hit>\d+)_pairwise1`；当前回归变量是 `_hit_above{k}_pairwise1`。
- 影响：现存 `winrates_state_vs_plain.csv` 有 297 行，说明它是累计命名迁移前生成的旧产物；按当前脚本重跑会把活动累计 dummy 行全部漏掉，形成“代码—结果”版本漂移。
- 建议：醒来后先补正则与单测，再重建该汇总；在此之前不要把现存表视作当前代码可复现的产物。

#### M13. 脚本管理文档仍把 m/n 和控制变量写反或写旧（Major）

- 位置：`A_data/scripts/腳本管理說明檔案.md:77-80,94,130`。
- 表现：仍写未来期限只有 3/6/12、`m=排名窗口数`、`n=收益期限`、计算 m 个排名；仍把 `CtrlRetLTM` 写成完整 12 个月收益、把 `CtrlVol` 写成“前 12 个月 NAV 的标准差”，标题仍称市态 dummy 为互斥编码。
- 影响：这是最接近运行手册的文档，可能把已经修好的代码口径再次带回错误实现；与当前代码（含 1m Y、11 个月 LTM、12 个单月收益波动率、累计 dummy）冲突。
- 建议：列为 P0 文档修复，采用唯一术语表自动引用，而不是在多个 Markdown 复制口径。

#### M14. PPT 新稿仍使用已被当前结果否定的旧交互结论（Major；延续 C4）

- 位置：`H_presentation/PPT格式.md:43,202-210`。
- 表现：仍声称 beta 控制、聚类标准误、bootstrap，以及 m3_n6/m6_n6 正向显著交互；当前正式模型没有 beta、主体是 Fama-MacBeth + NW(5)，当前含双方主效应的交互项不支持该结论。
- 影响：若直接用于汇报，会把旧模型（遗漏 rank_mean 主效应）的结论包装为当前结果。
- 建议：正式 PPT 暂以“Full sample 热力图经 BH-FDR 无主候选；交互条件效应未获当前模型支持”为准，旧数值全部标 legacy。

#### M15. 基准收益“断档”文档与代码校验范围不一致（Major）

- 位置：`3_panel_base_benchmark_excess_factors.py:15-18,322-339` 与脚本管理文档相应段落。
- 表现：文档称“任一端点缺失（含中途断档）时记缺失”，代码实际只用 `NAV(e)/NAV(e-m)-1` 并检查两个端点；中间月份缺失不会使基准收益缺失。
- 影响：若研究定义要求基准净值月序列完整，当前因子覆盖范围比文档更宽；若端点法本来就是预期，则文档中的“含中途断档”错误。
- 建议：人工确认后统一口径，并增加一个含中间缺口的最小单测。

#### M16. 结果与元数据仍缺少可复现冻结点（Major；更新 M6）

- 当前 100 个正式模型都有 `run_metadata.json`，这是进展；但 105 个一级结果目录 metadata 中，`run_id/script_name/parameters/output_files/git_commit/git_dirty` 覆盖均为 0，只有 100 个使用 `run_time/input_path/model_key`。
- 当前工作树有 3,258 个文件未形成 commit，批量结果无法绑定到唯一代码快照。部分摘要脚本和产物已经出现命名迁移前后的版本漂移。
- 建议：任何进一步正式结论前，先建立“代码 commit + 输入 hash + registry key + run_id + 输出清单”的冻结 manifest。

#### M17. `model_map.html` 仍保留 6 个 `bm33` 旧 key（Major/版本管理）

- 静态解析显示：100 个正式 registry key 全部能映射，但 `model_map.html` 额外保留 6 个不在正式 registry 的 `bm33` key。
- 影响：结果汇总和人工导航仍可能把兼容别名/旧目录误当独立模型，尤其在旧产物重新出现时造成重复展示。
- 建议：保留 alias 只应在 registry 兼容入口；展示层统一 canonical `bottom33`，旧 key 移到明确的 legacy 区。

### D. 本轮新增模型地图（相对 78 模型冻结点）

| 新增模型族 | 数量 | Y / 核心 X | 目的 | 当前风险 |
|---|---:|---|---|---|
| 单窗口分组的 y1m/y3m/y12m | 15 | `future_ret_1m/3m/12m`；五个标准 FAC | 检查 Up/Down/Top33/Mid33/Bottom33 的期限结构 | 必须以同期限两类样本标签解释；静态配置已通过 |
| 跨期限 FAC 的交互/base 补充 | 3 | 跨 1/3/6/12m rank-vol、rank_mean、交互 | 补齐含/不含 LTM 和 base 主效应对照 | 交互结论仍受 C4 约束 |
| 基准超额一致性 | 4 | benchmark-excess FAC、累计 HitRate；`future_ret_6m` | 剥离基金自身基准风格；替换投资目标 dummy；上半组 | 断档口径需确认；因子仍按“月份×投资类型”排名 |
| 合计 | 22 | — | registry 从 78 增至 100 | 结果需绑定冻结 manifest |

### E. 本轮问题计数口径

- 当前仍需处置的 Critical：2 个——C4（PPT/解释与正式交互结果相反）、C6（状态匹配 Y 可能跨经理 regime）。
- 当前 Major：17 个编号项中，M3/M4 的核心代码已修复但文档/展示仍有残留；本轮新增 M11-M17。为避免把“已修复代码、待刷新结果”和“完全未处理”混成一个数字，最终摘要以“2 个 active Critical、17 个 Major 追踪项”报告。

## 1. 本次审查范围

本次盘点覆盖：

- `.md`：本轮相对上次 push 有 125 个新增/修改文件。优先全文检查项目说明、脚本管理、研究计划、PPT 与任务文档；批量生成诊断报告按结构抽样。
- `.py`：本轮 38 个新增/修改文件，全部完成只读 AST 解析（0 个语法错误）；重点审查 A_data 面板/变量生成、B_factors 清洗、D_analysis registry、Fama-MacBeth、FDR、结果汇总、市态和 winrate 脚本。
- `.json`：本轮 452 个新增/修改文件，全部解析通过；重点检查 panel summary、run metadata、portfolio registry、FDR metadata 与特征 registry。
- `.xlsx`：本轮 125 个新增/修改文件。仅记录路径、文件名、修改时间、大小与可能用途；未打开、修改、重算、清洗或导出原始 Excel。
- `.csv/.parquet`：不做系统数据审计；仅只读检查文件清单、Parquet schema、少量关键列非空计数以及代表性回归 CSV，以核对文档结论。

未做事项：没有执行单元测试（避免任何测试副作用），没有运行回归/回测/ETL，没有核验每一个数值结果的可重复性。因此，本报告是“代码与逻辑一致性审查”，不是完整的实证复现审计。

## 2. 项目结构概览

| 目录 | 当前用途判断 | 备注 |
|---|---|---|
| `A_data/` | 原始/清洗数据、基金筛选、面板、控制变量、分组、市态、未来收益与描述统计 | 主数据流水线上游；包含大量会覆盖输出的脚本 |
| `B_factors/` | 按 registry 对面板选列、筛样本、缩尾、生成分组标签与相关性/VIF | 每个模型通常有独立清洗面板；README 已落后于代码 |
| `C_positions/` | 持仓模块预留 | 当前未见主线代码 |
| `D_analysis/` | 统一回归 registry、Fama-MacBeth、组合排序、热力图、winrate、市态模型、RBSA | 当前实证主线核心；模型登记 100 个 |
| `E_backtesting/` | 回测模块接口草案 | 已有接口设计 Markdown，尚未见对应主线实现代码 |
| `F_grouping/` | 分组模块预留 | 当前未见主线文件 |
| `G_engine/` | 引擎模块预留 | 当前未见主线文件 |
| `H_presentation/` | PPT、storyline、图表展示材料 | 存在正式版、拷贝、模板和其他课题 PPT 混放 |
| `I_visualization/` | 清洗覆盖审计 Streamlit 工具 | 文档仍指向旧项目 `MAIN_STYLE_ROTATION`，不是当前主线 |
| `SY_Reference/` | 研究计划、文献、日志、操作说明、任务进度 | 设计信息丰富，但候选方案、已实现方案和旧结论混在一起 |
| `tests/` | 变量/registry/识别逻辑单元测试 | 本次未运行 |
| `SY_Baseline/`、`data_csmar/` | 基准/外部资料或数据 | 本次未深入数据内容 |

当前仓库不是干净工作树，已有大量 modified/untracked 代码与结果。这些均视为用户现有状态，本次没有触碰。

## 3. 研究主线理解

### 3.1 当前真正的主线

当前主要研究问题是：主动权益基金过去业绩的“一致性/方向一致性”能否预测未来收益，以及这种预测力是否随历史排名水平、形成窗口、预测期限和市场状态而变化。

- 核心自变量：
  - `FAC_rank_vol_m{m}_n{n}_pairwise{p}`：`1 - n 期排名分位数的样本标准差`，越大表示排名越稳定；它只有稳定性，没有好坏方向。
  - `rank_mean_*`：同一组 n 期排名均值，越大表示历史表现越好。
  - `hitrate_top50/top33/bottom33_*` 和累计 dummy：带方向的一致性。
  - 跨期限排名波动率、市态条件 FAC、市态 HitRate。
- 核心因变量：`future_ret_1m/3m/6m/12m`；主模型使用 `future_ret_6m`。另有“未来最近 6 个指定市态月”的状态匹配收益。
- 控制变量：`CtrlRetSTR`、`CtrlRetLTM`、`CtrlVol`、基金类型 dummy、`Ctrl_log_fund_size`、`Ctrl_fund_age`。
- 主要模型：逐月横截面 OLS + Fama-MacBeth 月度系数均值 + Newey-West 标准误；另有分组回归、交互模型、组合排序、热力图、winrate/HitRate、市态匹配与错配模型。
- 当前输出：主要在 `B_factors/output/{model}/` 和 `D_analysis/output/fund_consistency/{model}/`；描述统计在 `A_data/output/descriptive_analysis/`。
- 最适合 PPT 的结果：基准/分组 Fama-MacBeth 表、窗口热力图、HitRate 窗口图、Top33/Bottom33 期限结构、市态匹配与错配对照、组合分组图。

### 3.2 独立的 RBSA 支线

根目录 `项目介绍.md` 只介绍 `D_analysis/scripts/RBSA.py`：以成长/价值/现金暴露判断风格、比较未来 4 周收益。这是另一条研究支线，不足以解释当前基金一致性主线。项目顶层缺少能连接两条支线的总 README。

### 3.3 无法完全确认的内容

- 当前 PPT 最终应以“排名一致性”还是“市态一致性”为唯一主叙事，文件中没有冻结声明。
- 研究计划列出的 alpha、Sharpe、Sortino、24/36 月未来收益、持仓集中度等多数仍是候选，不能视作已实现。
- 基金经理 regime 已按用户确认的严格口径处理：预测时点要求经理团队稳定满 12 个月，普通未来 Y 还需对应期限的 `match_is_sample_future_ret_* = 1`，避免持有期跨 regime；受影响结果仍需按新筛选重跑。

## 4. 核心变量地图

| 变量 | 含义/方向 | 生成脚本 | 主要输入 | 输出位置 | 文档一致性 | 备注 |
|---|---|---|---|---|---|---|
| `past_ret_{m}m_{k}` | 第 k 个过去 m 月收益；`pairwise` 控制窗口移动步长 | `A_data/scripts/3_generate_panel_base.py` | 筛选后月度 NAV | `A_data/output/panel_base*.parquet` | 一致 | m=收益期限，n=排名期数；已修正周边注释中写反的 m/n |
| `past_ret_{m}m_rank_{k}` | 同月、同 investment_type 截面百分位；越大越好 | 同上 | 过去收益、样本/规模标签 | 同上 | 一致 | `pct=True`；Top 方向统一为大值 |
| `rank_vol_m{m}_n{n}` | n 个排名的样本标准差；越小越稳定 | 同上 | n 个 rank | 同上 | 一致 | `ddof=1`；n=1 全部 NaN；写反的 m/n 注释已修正 |
| `FAC_rank_vol_*` | `1-rank_vol`；越大越稳定 | 同上 | rank_vol | 同上 | 普通 FAC 一致 | 只是稳定性的单调反向，不含历史表现好坏方向；市态 FAC 是另一套明确命名的口径 |
| `rank_mean_*` | n 个排名均值；越大历史表现越好 | `3_panel_base_grouping_factors.py` | n 个 rank | panel parquet | 一致 | 用于分组或交互主效应 |
| Top50/Bottom50 | `is_median_rank_mean_*` 的截面二分组，或单期 rank 的 Top50 命中口径 | grouping/winrates 脚本 | rank_mean 或 rank | panel parquet | 各自实现一致、概念容易混淆 | 两类变量列名不重叠；历史 `is_top_half_*` 实为 Top30/Mid40/Bottom30，并非二分组 |
| Top33/Mid33/Bottom33 | 单一 `(m,n)` 的 rank_mean 截面三分组，或跨 1/3/6/12 月期限的 rank_mean 三分组 | grouping/volatility alternative | rank_mean | panel parquet | 各自实现一致、经济口径不同 | 两脚本输出列名不重叠；新 registry key 与输出路径已统一使用 `bottom33`，`bm33` 仅保留为旧命令兼容别名 |
| HitRate | `hitcount/n`；Top 指标越大越好，Bottom 指标越大越差 | `3_panel_base_winrates_factors.py` | n 个排名 | heatmap panel；registry JSON | 当前代码一致 | 新非重叠模型 `pairwise=m` |
| 累计 Hit dummy | `Dk=1(hitcount>=k)` | 同上 | hitcount | heatmap panel | 当前普通、非重叠与市态模型已统一 | 旧结果仍可能含互斥 `hit1..hitn`；旧 n=12 结果曾临时改用 3/6/9 累计门槛，重跑后应按新 metadata 识别 |
| 跨期限排名波动率 | 同一时点 1/3/6/12 月收益排名的标准差 | `3_panel_base_volatility_alternative.py` | 四个期限排名 | panel parquet | 研究计划有对应候选 | 另生成跨期限 rank_mean 与分组 |
| 市态变量 | HS300 涨跌、成长/价值占优、大/小盘占优、行业波动率高/低 | `3_panel_base_mkt_condition.py` | 指数与行业月度数据 | 两个 panel parquet | 新任务文档一致 | 月末可观察；状态定义需在 PPT 明示 |
| 市态 FAC/HitRate | 最近 n 个指定市态月的排名稳定性/命中率 | `3_panel_base_mkt_condition_factors.py` | 市态列、当月 `past_ret_m_rank_1` | 两个 panel parquet | 脚本主动声明与普通 FAC 不同 | 使用“历史各月自身截面排名”，与普通 FAC 的 t 时点重排分母池不同 |
| 普通未来收益 | `NAV_{t+h}/NAV_t-1` | `3_generate_panel_base.py` | NAV | panel parquet | 一致 | 回归现同时要求对应 `is_insample_*` 与 `match_is_sample_*`，避免未来持有期跨基金经理 regime |
| 市态匹配未来收益 | 未来最近 6 个指定市态月的单月收益复合 | `3_panel_base_mkt_condition_future_returns.py` | NAV、市态、样本与规模标签 | panel parquet | 新任务文档一致 | 日历跨度可变，故不做普通固定期组合排序 |
| `CtrlRetSTR` | 当月 1 月收益 | `3_panel_base_controls_variable.py` | NAV | panel parquet | 基本一致 | 在 month_date=t 使用 t-1→t |
| `CtrlRetLTM` | 12 月收益剔除最近 1 月，实质 `NAV_{t-1}/NAV_{t-12}-1` | 同上 | `past_ret_12m_1`、STR | panel parquet | 文档写法有歧义 | 代码称“过去2~12月”，需统一时间下标 |
| `CtrlVol` | 截至当前月的 12 个单月收益 `R_{t-11}...R_t` 的样本标准差 | 同上 | STR | panel parquet | 已按用户确认口径统一 | 包含 month_date=t 的当月收益，要求 12 个月连续完整 |
| 规模/年龄/类型 | log(AUM)、成立月份数、类型 dummy | 同上 | iFind 规模、成立日 | panel parquet | 基本一致 | 类型 dummy 加截距等价于当前两类基金的类型固定效应 |
| 交互项 | 月度截面去均值后的 FAC × rank_mean 等 | 回归脚本运行时生成 | B_factors 面板 | 回归 CSV/metadata | 当前 storyline 已过时 | 当前结果与文档中的正向显著交互结论相反 |
| “标准化变量” | 当前主要交互为去均值，不除以标准差 | `consistency_fama_mac_regression.py` | factor/rank_mean | 内存/回归结果 | 文档常混称标准化 | 应区分 centering 与 z-score |

## 5. 模型地图

所有主 Fama-MacBeth 模型均按月做横截面 OLS，含截距；没有基金固定效应，基金类型通过一个 dummy 控制。月度系数时间序列使用 Newey-West，主配置 lag=5，横截面最小样本量通常为 50。`regression_registry.py` 当前共登记 100 个模型，按变量口径和研究目的可分为 FAC 核心、排名均值分组、跨期限替代指标、热力图、Winrate/HitRate、市态条件、基准超额等模型族。下方 5.1 保留 2026-07-02 的 78 模型基线清单；新增 22 个模型见本报告开头 D 表，两部分合计覆盖当前 100 个正式 key。

### 5.1 基线模型清单（78 个）

| 文件名（registry key） | 模型族 | 脚本/registry | Y | 核心解释变量 X | 控制变量 | 输出 | 回答的问题 | 风险 |
|---|---|---|---|---|---|---|---|---|
| fm_null（M0） | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | (无，仅控制变量) | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_null`：fama_macbeth_results.csv, run_metadata.json | 控制变量本身能解释多少未来收益，作为 R²/系数基准对照（不含一致性因子） | 样本靠 sample_alignment_columns 与 fm_baseline 对齐，需确认对齐样本与 fm_baseline 完全一致才能比较 R² |
| fm_baseline（M1） | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 5 个标准窗口 FAC_rank_vol（m3n6/m6n3/m6n6/m6n12/m12n6） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline`：+portfolio_sorting | 排名一致性（不区分历史好坏、不带方向）本身是否预测未来收益 | 代表份额静态去重口径已由用户接受并需披露；C2 regime 约束已修复但结果待重跑；窗口选择仍依赖热力图搜索 |
| fm_baseline_up | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 5 窗口 FAC（样本限定 rank_mean 中位数以上） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_up`：+descriptive | 一致性效应是否只在历史表现较好（中位数以上）的基金中成立 | up/down 命名实际是中位数二分组，与历史 Top30/Bottom30 口径不同，需在 PPT 中说明 |
| fm_baseline_down | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 5 窗口 FAC（样本限定 rank_mean 中位数以下） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_down`：+descriptive | 一致性效应在历史表现较差的基金中是否依然成立、或方向是否反转 | 同上；中位数以下组基金数量、存续期可能系统性偏短，需关注样本量 |
| fm_baseline_interaction_base（M2） | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 5 窗口 FAC + 对应 5 个 rank_mean 主效应（不含交互项） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_base`：+portfolio_sorting | 加入历史排名水平（rank_mean）主效应后，一致性系数是否仍稳健（排除 rank_mean 混淆） | rank_mean 与 FAC 可能存在共线性，需看 correlation_check 的 VIF |
| fm_baseline_interaction_base_noctrlmomentum | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 M2（5 窗口 FAC + 5 个 rank_mean 主效应，不含交互项） | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_base_noctrlmomentum` | 去掉长期动量控制变量 CtrlRetLTM 后，M2 的结论（一致性 + rank_mean 主效应）是否稳健 | 作为 M2 的稳健性检验，需与 M2 并列解读，不能单独作为正式结论 |
| fm_baseline_interaction_noctrlLTM（M3'） | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 5 窗口 FAC（月度截面去均值）+ 对应 rank_mean（去均值）主效应 + FAC×rank_mean 交互项（去均值） | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM`：+portfolio_sorting | 一致性效应是否依赖历史排名水平（交互项显著性与方向），剔除长期动量控制变量的版本 | C4：当前去均值交互结果与 PPT storyline 旧结论方向相反；旧结果遗漏 rank_mean 主效应，口径不可比 |
| fm_baseline_interaction（M3） | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 M3'，但控制变量含 CtrlRetLTM（去均值 FAC + rank_mean 主效应 + 交互项） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction`：+portfolio_sorting | 同 M3'，标准 6 控制变量版本，是当前正式交互模型口径 | 同 C4：交互项在当前口径下不显著、符号不稳定，与 storyline 核心叙事冲突 |
| fm_baseline_interaction_alternative（M4） | ① FAC 核心基础序列（M0-M4） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 5 窗口 FAC + FAC×CtrlRetLTM 交互项（用长期动量而非 rank_mean 作条件变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_alternative`：+portfolio_sorting | 用控制变量（长期收益率）而不是平均排名作为条件变量时，一致性效应是否稳健、交互是否显著 | 交互项仍全部不显著；FAC 单因子稳健性优于交互项本身 |
| fm_baseline_top33 | ② 排名均值三分组序列（Top33/Mid33/Bottom33） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 5 窗口 FAC（样本限定 rank_mean 前三分组（Top33）） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_top33`：+descriptive | 一致性效应是否集中在 rank_mean 前三分组（Top33）（比中位数二分更细的非线性/极端组检验） | 三分组样本量比二分组更小，标准误可能不稳定；tercile 定义需与热力图/市态模型的 tercile 口径保持一致 |
| fm_baseline_mid33 | ② 排名均值三分组序列（Top33/Mid33/Bottom33） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 5 窗口 FAC（样本限定 rank_mean 中三分组（Mid33）） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_mid33`：+descriptive | 一致性效应是否集中在 rank_mean 中三分组（Mid33）（比中位数二分更细的非线性/极端组检验） | 三分组样本量比二分组更小，标准误可能不稳定；tercile 定义需与热力图/市态模型的 tercile 口径保持一致 |
| fm_baseline_bottom33 | ② 排名均值三分组序列（Top33/Mid33/Bottom33） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 同 5 窗口 FAC（样本限定 rank_mean 后三分组（Bottom33）） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_bottom33`：+descriptive | 一致性效应是否集中在 rank_mean 后三分组（Bottom33）（比中位数二分更细的非线性/极端组检验） | 三分组样本量比二分组更小，标准误可能不稳定；tercile 定义需与热力图/市态模型的 tercile 口径保持一致 |
| fm_baseline_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_rank_vol_across_horizons` | 跨期限一致性（同时看 1/3/6/12 月排名是否一致）本身能否预测未来 6 个月收益 | 样本量随子分组进一步变小；该变量把 4 个期限压缩成一个标量，经济含义与单一 (m,n) FAC 不同，需在文档中明确区分 |
| fm_baseline_up_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_up_rank_vol_across_horizons` | 该效应是否只在历史表现较好的基金中成立 | 样本量随子分组进一步变小；该变量把 4 个期限压缩成一个标量，经济含义与单一 (m,n) FAC 不同，需在文档中明确区分 |
| fm_baseline_down_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_down_rank_vol_across_horizons` | 该效应在历史表现较差基金中是否成立/反转 | 样本量随子分组进一步变小；该变量把 4 个期限压缩成一个标量，经济含义与单一 (m,n) FAC 不同，需在文档中明确区分 |
| fm_baseline_top33_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_top33_rank_vol_across_horizons` | 该效应是否集中在跨期限排名最好的分组 | 样本量随子分组进一步变小；该变量把 4 个期限压缩成一个标量，经济含义与单一 (m,n) FAC 不同，需在文档中明确区分 |
| fm_baseline_mid33_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_mid33_rank_vol_across_horizons` | 该效应是否集中在跨期限排名中间的分组 | 样本量随子分组进一步变小；该变量把 4 个期限压缩成一个标量，经济含义与单一 (m,n) FAC 不同，需在文档中明确区分 |
| fm_baseline_bottom33_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_bottom33_rank_vol_across_horizons` | 该效应在跨期限排名最差分组是否成立/反转 | 样本量随子分组进一步变小；该变量把 4 个期限压缩成一个标量，经济含义与单一 (m,n) FAC 不同，需在文档中明确区分 |
| fm_baseline_interaction_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m + 对应 rank_mean_across_horizons 主效应 + 二者交互项（去均值） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_rank_vol_across_horizons`：+portfolio_sorting | 跨期限一致性效应是否依赖跨期限历史排名水平（对照 M3 的跨期限版本） | 同 C4 类交互项解读风险；另有显式 `noctrlLTM` 版本作五控制变量对照 |
| fm_baseline_interaction_alternative_rank_vol_across_horizons | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） + FAC×CtrlRetLTM 交互项 | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_alternative_rank_vol_across_horizons`：+portfolio_sorting | 跨期限一致性效应是否依赖长期动量水平（对照 M4 的跨期限版本） | 同 M4：交互项预期同样不显著 |
| fm_baseline_up_rank_vol_across_horizons_y1m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_1m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_up_rank_vol_across_horizons_y1m` | 跨期限一致性效应（中位数以上样本）随预测期限改为 1m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_up_rank_vol_across_horizons_y3m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_3m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_up_rank_vol_across_horizons_y3m` | 跨期限一致性效应（中位数以上样本）随预测期限改为 3m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_up_rank_vol_across_horizons_y12m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_12m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_up_rank_vol_across_horizons_y12m` | 跨期限一致性效应（中位数以上样本）随预测期限改为 12m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_down_rank_vol_across_horizons_y1m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_1m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_down_rank_vol_across_horizons_y1m` | 跨期限一致性效应（中位数以下样本）随预测期限改为 1m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_down_rank_vol_across_horizons_y3m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_3m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_down_rank_vol_across_horizons_y3m` | 跨期限一致性效应（中位数以下样本）随预测期限改为 3m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_down_rank_vol_across_horizons_y12m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_12m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_down_rank_vol_across_horizons_y12m` | 跨期限一致性效应（中位数以下样本）随预测期限改为 12m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_top33_rank_vol_across_horizons_y1m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_1m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_top33_rank_vol_across_horizons_y1m` | 跨期限一致性效应（前 1/3样本）随预测期限改为 1m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_top33_rank_vol_across_horizons_y3m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_3m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_top33_rank_vol_across_horizons_y3m` | 跨期限一致性效应（前 1/3样本）随预测期限改为 3m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_top33_rank_vol_across_horizons_y12m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_12m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_top33_rank_vol_across_horizons_y12m` | 跨期限一致性效应（前 1/3样本）随预测期限改为 12m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_mid33_rank_vol_across_horizons_y1m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_1m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_mid33_rank_vol_across_horizons_y1m` | 跨期限一致性效应（中 1/3样本）随预测期限改为 1m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_mid33_rank_vol_across_horizons_y3m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_3m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_mid33_rank_vol_across_horizons_y3m` | 跨期限一致性效应（中 1/3样本）随预测期限改为 3m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_mid33_rank_vol_across_horizons_y12m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_12m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_mid33_rank_vol_across_horizons_y12m` | 跨期限一致性效应（中 1/3样本）随预测期限改为 12m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_bottom33_rank_vol_across_horizons_y1m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_1m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_bottom33_rank_vol_across_horizons_y1m` | 跨期限一致性效应（后 1/3样本）随预测期限改为 1m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_bottom33_rank_vol_across_horizons_y3m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_3m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_bottom33_rank_vol_across_horizons_y3m` | 跨期限一致性效应（后 1/3样本）随预测期限改为 3m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_baseline_bottom33_rank_vol_across_horizons_y12m | ③ 跨期限排名波动率替代指标序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_12m | rank_vol_across_horizons_1m_3m_6m_12m（同一时点 1/3/6/12 月收益排名的跨期限标准差，单一变量） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_bottom33_rank_vol_across_horizons_y12m` | 跨期限一致性效应（后 1/3样本）随预测期限改为 12m 后是否依然成立，用于构建期限结构 | 由 run_representative_window_horizon_tests.py 统一调度；参数来自前序热力图挑选，存在选择后推断风险（对应审查 C5） |
| fm_heatmap_up | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_6m | m=1..12 × n=2..12，pairwise=1 | 6 个标准控制变量 | `fm_heatmap_up` + `heatmap_summary` | 中位数以上探索族 | 已刷新 BH-FDR；仅作探索 |
| fm_heatmap_down | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_6m | m=1..12 × n=2..12，pairwise=1 | 6 个标准控制变量 | `fm_heatmap_down` + `heatmap_summary` | 中位数以下探索族 | 已刷新 BH-FDR；仅作探索 |
| fm_heatmap_top33 | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_6m | m=1..12 × n=2..12，pairwise=1 | 6 个标准控制变量 | `fm_heatmap_top33` + `heatmap_summary` | Top33 探索族 | 已刷新 BH-FDR；仅作探索 |
| fm_heatmap_mid33 | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_6m | m=1..12 × n=2..12，pairwise=1 | 6 个标准控制变量 | `fm_heatmap_mid33` + `heatmap_summary` | Mid33 探索族 | 已刷新 BH-FDR；仅作探索 |
| fm_heatmap_bottom33 | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_6m | m=1..12 × n=2..12，pairwise=1 | 6 个标准控制变量 | `fm_heatmap_bottom33` + `heatmap_summary` | Bottom33 探索族 | 已刷新 BH-FDR；仅作探索 |
| fm_heatmap_full | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_6m | m=1..12 × n=2..12，pairwise=1 | 6 个标准控制变量 | `fm_heatmap_full` + `heatmap_summary` | 唯一 Full sample 主检验族 | 已刷新 BH-FDR；主候选 0 个 |
| fm_heatmap_top33_y12m | ④ 热力图窗口搜索序列 | 132 个可定义格 | future_ret_12m | m=1..12 × n=2..12，Top33 样本 | 6 个标准控制变量 | `fm_heatmap_top33_y12m` | 预测期限拉长到 12 个月后窗口是否变化 | 当前 registry/metadata 使用 12m 的 `is_insample` 与 `match_is_sample`；仍属选择后探索 |
| fm_winrates_top50 | ⑤ 带方向一致性（Winrate/HitRate）序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 5 组滚动累积 hit dummy（(m,n,pairwise)=(3,6,1)/(6,3,1)/(6,6,1)/(6,12,1)/(12,6,1)；每组 D_k=1(命中次数≥k) 逐级 dummy） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top50`：+descriptive_dummy +portfolio_sorting | 排名进入前 50% 的月份数每多跨过一个门槛，对未来收益的边际贡献是否显著（带方向的一致性，与不带方向的 FAC 对照） | 累积 dummy 组内共线性天然较高，需结合 hitrate 主效应模型（见下）交叉验证 |
| fm_winrates_top50_nonoverlap | ⑤ 带方向一致性（Winrate/HitRate）序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 两层：36 个 hitrate 线性主效应（m,n=1..6，pairwise=m 完全不重叠）+ 36 组累积 hit dummy（次级模型） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top50_nonoverlap`：+descriptive_dummy +portfolio_sorting | 完全不重叠、遍历 m,n=1..6 的排名前 50%命中比例对未来收益的线性效应，以及命中次数的边际效应是否单调 | M6：部分模型缺主 run_metadata；M5：与旧 top30/50 互斥 dummy 结果同 key 不同口径，需确认结果目录已是新口径（36 hitrate+36 累积 dummy）后再引用 |
| fm_winrates_top33_nonoverlap | ⑤ 带方向一致性（Winrate/HitRate）序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 两层：36 个 hitrate 线性主效应（m,n=1..6，pairwise=m 完全不重叠）+ 36 组累积 hit dummy（次级模型） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top33_nonoverlap`：+descriptive_dummy +portfolio_sorting | 完全不重叠、遍历 m,n=1..6 的排名前 33%命中比例对未来收益的线性效应，以及命中次数的边际效应是否单调 | M6：部分模型缺主 run_metadata；M5：与旧 top30/50 互斥 dummy 结果同 key 不同口径，需确认结果目录已是新口径（36 hitrate+36 累积 dummy）后再引用 |
| fm_winrates_bottom33_nonoverlap | ⑤ 带方向一致性（Winrate/HitRate）序列 | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 两层：36 个 hitrate 线性主效应（m,n=1..6，pairwise=m 完全不重叠）+ 36 组累积 hit dummy（次级模型） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_bottom33_nonoverlap`：+descriptive_dummy +portfolio_sorting | 完全不重叠、遍历 m,n=1..6 的排名后 33%（表现最差）命中比例对未来收益的线性效应，以及命中次数的边际效应是否单调 | M6：部分模型缺主 run_metadata；M5：与旧 top30/50 互斥 dummy 结果同 key 不同口径，需确认结果目录已是新口径（36 hitrate+36 累积 dummy）后再引用 |
| fm_baseline_hs300 | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（5 窗口 × hs300up/hs300down 两个方向），对照普通 5 窗口 FAC | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_hs300` | 在特定市态（HS300 涨跌）下，历史一致性对未来收益是否有增量解释力，与普通 FAC（fm_baseline）对照 | M9：市态 FAC 用历史各月自身截面排名，普通 FAC 用 t 月重排的排名池，分母池不同，系数不能直接跨模型比较 |
| fm_baseline_interaction_noctrlLTM_hs300 | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（去均值）+ 10 个市态 rank_mean 主效应（去均值）+ FAC×rank_mean 交互项 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM_hs300`：+portfolio_sorting | HS300 涨跌市态下，一致性效应是否依赖市态期内的历史排名水平 | 同 M9；交互项解读需同时参考 ① 中 C4 的教训（先看是否遗漏主效应） |
| fm_marginal_interaction_noctrlLTM_hs300 | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 市态 FAC_c(5)+市态 rank_mean_c(5)+市态交互_c + 同期限普通 FAC_c(5)+普通 rank_mean_c(5)+普通交互_c，市态与普通两组变量同场回归 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_marginal_interaction_noctrlLTM_hs300` | HS300 涨跌市态一致性相对于同期限普通一致性是否有边际增量解释力（隔离"市态选月"与"排名池变化"两个效应） | 市态与普通变量高度共线（同源排名），说明文件已声明结论需以 correlation_check 的 VIF 诊断为前提，不能只看系数显著性 |
| fm_winrates_top50_hs300 | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 组市态累积 hit dummy（5 窗口 × hs300up/hs300down，市态月份内排名前 50% 累计命中） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top50_hs300` | HS300 涨跌市态月份内，排名前 50% 的命中次数对未来收益的边际影响 | 市态月份窗口最大回看 48 个月，早期样本可能因市态月不足而被截断，需检查样本量 |
| fm_ymatch_hs300_hs300up | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_hs300up | 5 个 hs300up 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_hs300_hs300up` | 上涨月的历史一致性能否预测"未来最近 6 个上涨月"的复合收益（状态匹配假设） | Y 的日历跨度不固定（取决于未来最近 6 个指定市态月何时出现），不能做固定期限组合排序 |
| fm_ymatch_cross_hs300_hs300up | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_hs300down | 同 5 个 hs300up 市态 FAC，但 Y 换成未来 下跌月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_hs300_hs300up` | 上涨月一致性对"未来异状态（下跌月）"收益是否同样有效，作为状态匹配假设的反证：若匹配组显著而错配组不显著，支持"状态匹配能力"假设 | 同上日历跨度问题；需与 fm_ymatch_hs300_hs300up 成对比较才有意义，不能单独解读 |
| fm_ymatch_hs300_hs300down | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_hs300down | 5 个 hs300down 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_hs300_hs300down` | 下跌月的历史一致性能否预测"未来最近 6 个下跌月"的复合收益（状态匹配假设） | 日历跨度问题同 fm_ymatch_hs300_hs300up |
| fm_ymatch_cross_hs300_hs300down | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_hs300up | 同 5 个 hs300down 市态 FAC，但 Y 换成未来 上涨月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_hs300_hs300down` | 下跌月一致性对"未来异状态（上涨月）"收益是否同样有效，作为状态匹配假设的反证 | 同上；需与 fm_ymatch_hs300_hs300down 成对比较 |
| fm_baseline_style | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（5 窗口 × growth/value 两个方向），对照普通 5 窗口 FAC | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_style` | 在特定市态（成长/价值占优）下，历史一致性对未来收益是否有增量解释力，与普通 FAC（fm_baseline）对照 | M9：市态 FAC 用历史各月自身截面排名，普通 FAC 用 t 月重排的排名池，分母池不同，系数不能直接跨模型比较 |
| fm_baseline_interaction_noctrlLTM_style | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（去均值）+ 10 个市态 rank_mean 主效应（去均值）+ FAC×rank_mean 交互项 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM_style`：+portfolio_sorting | 成长/价值占优市态下，一致性效应是否依赖市态期内的历史排名水平 | 同 M9；交互项解读需同时参考 ① 中 C4 的教训（先看是否遗漏主效应） |
| fm_marginal_interaction_noctrlLTM_style | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 市态 FAC_c(5)+市态 rank_mean_c(5)+市态交互_c + 同期限普通 FAC_c(5)+普通 rank_mean_c(5)+普通交互_c，市态与普通两组变量同场回归 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_marginal_interaction_noctrlLTM_style` | 成长/价值占优市态一致性相对于同期限普通一致性是否有边际增量解释力（隔离"市态选月"与"排名池变化"两个效应） | 市态与普通变量高度共线（同源排名），说明文件已声明结论需以 correlation_check 的 VIF 诊断为前提，不能只看系数显著性 |
| fm_winrates_top50_style | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 组市态累积 hit dummy（5 窗口 × growth/value，市态月份内排名前 50% 累计命中） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top50_style` | 成长/价值占优市态月份内，排名前 50% 的命中次数对未来收益的边际影响 | 市态月份窗口最大回看 48 个月，早期样本可能因市态月不足而被截断，需检查样本量 |
| fm_ymatch_style_growth | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_growth | 5 个 growth 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_style_growth` | 成长占优月的历史一致性能否预测"未来最近 6 个成长占优月"的复合收益（状态匹配假设） | Y 的日历跨度不固定（取决于未来最近 6 个指定市态月何时出现），不能做固定期限组合排序 |
| fm_ymatch_cross_style_growth | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_value | 同 5 个 growth 市态 FAC，但 Y 换成未来 价值占优月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_style_growth` | 成长占优月一致性对"未来异状态（价值占优月）"收益是否同样有效，作为状态匹配假设的反证：若匹配组显著而错配组不显著，支持"状态匹配能力"假设 | 同上日历跨度问题；需与 fm_ymatch_style_growth 成对比较才有意义，不能单独解读 |
| fm_ymatch_style_value | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_value | 5 个 value 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_style_value` | 价值占优月的历史一致性能否预测"未来最近 6 个价值占优月"的复合收益（状态匹配假设） | 日历跨度问题同 fm_ymatch_style_growth |
| fm_ymatch_cross_style_value | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_growth | 同 5 个 value 市态 FAC，但 Y 换成未来 成长占优月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_style_value` | 价值占优月一致性对"未来异状态（成长占优月）"收益是否同样有效，作为状态匹配假设的反证 | 同上；需与 fm_ymatch_style_value 成对比较 |
| fm_baseline_size | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（5 窗口 × large/small 两个方向），对照普通 5 窗口 FAC | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_size` | 在特定市态（大/小盘占优）下，历史一致性对未来收益是否有增量解释力，与普通 FAC（fm_baseline）对照 | M9：市态 FAC 用历史各月自身截面排名，普通 FAC 用 t 月重排的排名池，分母池不同，系数不能直接跨模型比较 |
| fm_baseline_interaction_noctrlLTM_size | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（去均值）+ 10 个市态 rank_mean 主效应（去均值）+ FAC×rank_mean 交互项 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM_size`：+portfolio_sorting | 大/小盘占优市态下，一致性效应是否依赖市态期内的历史排名水平 | 同 M9；交互项解读需同时参考 ① 中 C4 的教训（先看是否遗漏主效应） |
| fm_marginal_interaction_noctrlLTM_size | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 市态 FAC_c(5)+市态 rank_mean_c(5)+市态交互_c + 同期限普通 FAC_c(5)+普通 rank_mean_c(5)+普通交互_c，市态与普通两组变量同场回归 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_marginal_interaction_noctrlLTM_size` | 大/小盘占优市态一致性相对于同期限普通一致性是否有边际增量解释力（隔离"市态选月"与"排名池变化"两个效应） | 市态与普通变量高度共线（同源排名），说明文件已声明结论需以 correlation_check 的 VIF 诊断为前提，不能只看系数显著性 |
| fm_winrates_top50_size | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 组市态累积 hit dummy（5 窗口 × large/small，市态月份内排名前 50% 累计命中） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top50_size` | 大/小盘占优市态月份内，排名前 50% 的命中次数对未来收益的边际影响 | 市态月份窗口最大回看 48 个月，早期样本可能因市态月不足而被截断，需检查样本量 |
| fm_ymatch_size_large | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_large | 5 个 large 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_size_large` | 大盘占优月的历史一致性能否预测"未来最近 6 个大盘占优月"的复合收益（状态匹配假设） | Y 的日历跨度不固定（取决于未来最近 6 个指定市态月何时出现），不能做固定期限组合排序 |
| fm_ymatch_cross_size_large | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_small | 同 5 个 large 市态 FAC，但 Y 换成未来 小盘占优月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_size_large` | 大盘占优月一致性对"未来异状态（小盘占优月）"收益是否同样有效，作为状态匹配假设的反证：若匹配组显著而错配组不显著，支持"状态匹配能力"假设 | 同上日历跨度问题；需与 fm_ymatch_size_large 成对比较才有意义，不能单独解读 |
| fm_ymatch_size_small | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_small | 5 个 small 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_size_small` | 小盘占优月的历史一致性能否预测"未来最近 6 个小盘占优月"的复合收益（状态匹配假设） | 日历跨度问题同 fm_ymatch_size_large |
| fm_ymatch_cross_size_small | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_large | 同 5 个 small 市态 FAC，但 Y 换成未来 大盘占优月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_size_small` | 小盘占优月一致性对"未来异状态（大盘占优月）"收益是否同样有效，作为状态匹配假设的反证 | 同上；需与 fm_ymatch_size_small 成对比较 |
| fm_baseline_indvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（5 窗口 × highvol/lowvol 两个方向），对照普通 5 窗口 FAC | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_indvol` | 在特定市态（行业波动率高/低）下，历史一致性对未来收益是否有增量解释力，与普通 FAC（fm_baseline）对照 | M9：市态 FAC 用历史各月自身截面排名，普通 FAC 用 t 月重排的排名池，分母池不同，系数不能直接跨模型比较 |
| fm_baseline_interaction_noctrlLTM_indvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 个市态 FAC（去均值）+ 10 个市态 rank_mean 主效应（去均值）+ FAC×rank_mean 交互项 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM_indvol`：+portfolio_sorting | 行业波动率高/低市态下，一致性效应是否依赖市态期内的历史排名水平 | 同 M9；交互项解读需同时参考 ① 中 C4 的教训（先看是否遗漏主效应） |
| fm_marginal_interaction_noctrlLTM_indvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 市态 FAC_c(5)+市态 rank_mean_c(5)+市态交互_c + 同期限普通 FAC_c(5)+普通 rank_mean_c(5)+普通交互_c，市态与普通两组变量同场回归 | 5个：STR+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_marginal_interaction_noctrlLTM_indvol` | 行业波动率高/低市态一致性相对于同期限普通一致性是否有边际增量解释力（隔离"市态选月"与"排名池变化"两个效应） | 市态与普通变量高度共线（同源排名），说明文件已声明结论需以 correlation_check 的 VIF 诊断为前提，不能只看系数显著性 |
| fm_winrates_top50_indvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline: `run_factor_pipeline.py`→`2_factor_correlation.py`→`consistency_fama_mac_regression.py`（部分含 `portfolio_sorting.py`） | future_ret_6m | 10 组市态累积 hit dummy（5 窗口 × highvol/lowvol，市态月份内排名前 50% 累计命中） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_winrates_top50_indvol` | 行业波动率高/低市态月份内，排名前 50% 的命中次数对未来收益的边际影响 | 市态月份窗口最大回看 48 个月，早期样本可能因市态月不足而被截断，需检查样本量 |
| fm_ymatch_indvol_highvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_highvol | 5 个 highvol 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_indvol_highvol` | 高波动月的历史一致性能否预测"未来最近 6 个高波动月"的复合收益（状态匹配假设） | Y 的日历跨度不固定（取决于未来最近 6 个指定市态月何时出现），不能做固定期限组合排序 |
| fm_ymatch_cross_indvol_highvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_lowvol | 同 5 个 highvol 市态 FAC，但 Y 换成未来 低波动月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_indvol_highvol` | 高波动月一致性对"未来异状态（低波动月）"收益是否同样有效，作为状态匹配假设的反证：若匹配组显著而错配组不显著，支持"状态匹配能力"假设 | 同上日历跨度问题；需与 fm_ymatch_indvol_highvol 成对比较才有意义，不能单独解读 |
| fm_ymatch_indvol_lowvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_lowvol | 5 个 lowvol 市态 FAC（标准 5 窗口） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_indvol_lowvol` | 低波动月的历史一致性能否预测"未来最近 6 个低波动月"的复合收益（状态匹配假设） | 日历跨度问题同 fm_ymatch_indvol_highvol |
| fm_ymatch_cross_indvol_lowvol | ⑥ 市态条件一致性序列（4 类条件 × 8 个子模型 = 32 个） | registry pipeline（无 portfolio_sorting 步骤） | future_ret_6m_highvol | 同 5 个 lowvol 市态 FAC，但 Y 换成未来 高波动月复合收益（错配对照） | 6个：STR+LTM+Vol+类型dummy+规模+基金年龄 | `D_analysis/output/fund_consistency/fm_ymatch_cross_indvol_lowvol` | 低波动月一致性对"未来异状态（高波动月）"收益是否同样有效，作为状态匹配假设的反证 | 同上；需与 fm_ymatch_indvol_lowvol 成对比较 |

### 5.2 registry 之外的两类模型

| 文件名 | 模型族 | 脚本/registry | Y | 核心 X | 控制变量 | 输出 | 回答的问题 | 风险 |
|---|---|---|---|---|---|---|---|---|
| RBSA | 独立支线，非 fund_consistency registry | `D_analysis/scripts/RBSA.py` | 未来 4 周收益/超额收益 | 成长-价值净暴露（约束滚动回归系数） | 约束滚动回归自身的时间窗口，无 registry 控制变量 | `D_analysis/output/RBSA/` | 踩对成长/价值风格是否带来超额收益 | 与一致性主线完全独立，但根目录 `项目介绍.md` 只介绍它，容易被误当作项目主线（对应审查 M1） |
| 面板回归（固定效应+聚类SE） | 研究计划中提出，未落实 | 无（仅 `SY_Reference` 文档提出） | 未落实 | 未落实 | 文档提出时间/基金固定效应与聚类 SE，但无代码 | 无明确当前产物 | 作为横截面 Fama-MacBeth 之外的替代识别方式 | 当前没有实现，不能在报告或 PPT 中称"已完成面板回归"（对应审查 M2） |

### 5.3 模型之间怎么比较、怎么用

模型地图的价值在于"哪些模型该放在一起比较"。下面先给出①FAC 核心基础序列（M0-M4）的完整对比逻辑作为示范，再给出②-⑥各序列的比较原则。

#### 5.3.1 FAC 核心基础序列（M0-M4）——示范

| 模型 | 说明 | 回答的问题 |
|---|---|---|
| fm_null（M0） | Y = Ctrl(6) | 控制变量本身能解释多少收益，作为基准对照 |
| fm_baseline（M1） | Y = FAC(5) + Ctrl(6) | 稳定性本身是否预测收益 |
| fm_baseline_interaction_base（M2） | Y = FAC(5) + rank_mean(5) + Ctrl(6) | 加入历史排名水平后，一致性系数是否仍稳健 |
| fm_baseline_interaction_noctrlLTM（M3'） | Y = FAC(5) + rank_mean_c(5) + interaction_c + Ctrl(5) | 一致性效应是否依赖历史排名水平（不含长期动量控制变量的版本） |
| fm_baseline_interaction（M3） | Y = FAC(5) + rank_mean_c(5) + interaction_c + Ctrl(6) | 同 M3'，标准 6 控制变量口径，为当前正式交互模型 |
| fm_baseline_interaction_alternative（M4） | Y = FAC(5) + CtrlRetLTM:FAC + Ctrl(6) | 用长期收益率（而非平均排名）作条件变量时，一致性效应是否稳健 |

比较逻辑（M1→M2→M3→M4 层层递进地给 FAC 加约束条件，逐步排除混淆、检验交互）：

1. **M1 vs M0**：Consistency（FAC）加入后，只在 m3_n6 窗口有增量解释力，其余窗口相对 M0 的边际贡献有限。
2. **M2 vs M1**：加入 rank_mean 主效应后，m3_n6 的 FAC 系数仍有解释力，符号仍然为负（一致性越高、未来收益越好）。
3. **M2 vs M3**：加入交互项后，m3_n6 的单因子（中心化后）仍显著，但交互项本身都不显著，且交互项系数方向不稳定；无论是否加入长期收益率 CtrlRetLTM，m3_n6 的单因子都显著——说明当前口径下"一致性效应有条件于历史好坏"这一叙事不成立。
4. **M4**：改用控制变量（CtrlRetLTM）而不是平均排名（rank_mean）来构造交互项，m3_n6 的单因子依然稳定，m6_n3 的单因子也出现显著性（且符号均为负），但交互项依然全部不显著——进一步确认"一致性效应的条件依赖性"在当前口径下缺乏证据支持，PPT 核心叙事应以单因子稳健性为主，交互结论需谨慎处理（对应审查 C4）。

另有一个稳健性版本 `fm_baseline_interaction_base_noctrlmomentum`，是 M2 去掉 CtrlRetLTM 后的版本，用于在剔除长期动量控制变量时复核 M2 的结论是否依然成立，应与 M2 并列解读而非单独引用。

#### 5.3.2 ② 排名均值三分组序列——怎么用

`fm_baseline_up/down`（中位数二分）与 `fm_baseline_top33/mid33/bottom33`（三分组）应配对比较：前者判断效应是否随历史表现"正负两分"，后者进一步检验是否只在极端组（Top33 或 Bottom33）成立、还是在中间组（Mid33）同样成立。若三分组结果与二分组方向一致但极端组效应更强，说明效应是单调的；若 Mid33 也显著而 Top33/Bottom33 不显著，则提示可能是非线性甚至反向关系，需要重新审视 M2/M3 的交互项设定。

#### 5.3.3 ③ 跨期限替代变量序列——怎么用

`fm_baseline_rank_vol_across_horizons` 系列与①的 `fm_baseline`（标准 5 窗口 FAC）是**同一问题的两种度量方式**：前者要求基金在 1/3/6/12 月四个期限的排名同时一致，是更严格的一致性定义；后者只看单一 (m,n) 窗口。两者结果一致，则说明"一致性预测收益"的结论对度量方式稳健；若跨期限版本效应消失，说明标准 FAC 的显著性可能来自某个特定窗口的偶然性，需要用④热力图确认该窗口是否稳健。y1m/y3m/y12m 的期限结构变体则用于回答"该效应在多长的预测窗口内成立"，与①⑤在 future_ret_6m 上的结论共同构成完整的期限证据链。

#### 5.3.4 ④ 热力图序列——怎么用

热力图包含 `fm_heatmap_full` 与 `fm_heatmap_up/down/top33/mid33/bottom33`。Full sample 是唯一主检验族，五个分组各自是独立探索族。每个模型内所有成功估计且 p-value 有效的 FAC `(m,n)` 主效应进入同一次 BH 校正；n=1 的未定义 FAC 不进入 family。正式候选规则为：主检验候选要求 Full sample `q<0.05`；探索候选要求至少两个探索分组 `q<0.05` 且方向一致；稳健候选要求 Full sample 显著，且至少两个探索分组与其同方向显著。旧的 `|t|>=1.96` 和“至少 2/3 个分组显著”仅保留为 raw 诊断信息，不再作为正式窗口标准。BH-FDR 不能消除在同一数据上挑选窗口后继续推断的 data snooping，因此热力图仍应标注探索/筛选属性。

#### 5.3.5 ⑤ Winrate/HitRate 序列——怎么用

`fm_winrates_top50`（5 个滚动窗口累积 dummy）与①的 `fm_baseline`（FAC）应对照解读："FAC 越高"（排名波动率越小）与"排名进入前 50% 的月份越多"是两种不同的一致性定义——前者不带方向，后者带方向。若两者结论一致（都显著且经济含义相符），说明"一致性"效应无论用哪种方式度量都稳健；若只有其中一种显著，需要区分是"稳定性本身"还是"稳定地表现好"在起作用。`fm_winrates_top50/top33/bottom33_nonoverlap`（非重叠版）则是同一问题在完全不重叠窗口下的稳健性检验，三个 key 应放在一起比较：top50 和 top33 方向一致但强度不同可验证单调性，bottom33（表现最差方向）若同样显著且符号相反，则进一步确认这是双向对称的一致性效应而非单边噪音。

#### 5.3.6 ⑥ 市态条件序列——怎么用

每个市态条件（hs300/style/size/indvol）内部有固定的比较链条：
- **baseline vs ①的 fm_baseline**：市态 FAC 是否比普通 FAC 有更强/更弱的解释力（但受 M9 影响，两者排名分母池不同，只能看方向和显著性模式，不能直接比较系数大小）。
- **interaction_noctrlLTM**：市态条件下是否也存在①中 M3 类似的交互项不稳定问题。
- **marginal**：市态一致性与普通一致性同场回归后谁能存活，用于回答"市态选月"与"排名池变化"两个效应哪个是真正的驱动力（结论必须先看 VIF，共线性预期很高）。
- **winrates_top50**：市态下的带方向版本，与⑤的全样本版本对照。
- **ymatch vs ymatch_cross**（如 hs300up vs cross_hs300up）：这是⑥最核心的因果检验——若"匹配"组（同状态预测同状态）显著而"错配"组（同状态预测异状态）不显著，才能支持"状态匹配能力"这一假设；若两组都显著或都不显著，则说明该市态条件本身不构成有效的识别变量，需要在 PPT 中避免过度解读。

### 5.4 FAC 热力图 BH-FDR 的实现与结果状态

- Full sample registry：`D_analysis/config/regression_registry.py` 中的 `fm_heatmap_full`。
- 六模型批量运行：`D_analysis/scripts/run_heatmap_regressions.py`。
- BH-FDR、q-value 矩阵、候选分类与汇总：`D_analysis/scripts/plot_consistency_heatmaps.py`。
- 测试：`tests/test_fac_heatmap_fdr.py`；已覆盖 BH 已知样例、family 隔离、候选分类、Full sample registry 和 q-value 矩阵落盘。实现阶段记录为完整轻量测试 48 项通过，其中新增 FAC FDR 测试 5 项通过。
- 每个模型的预期新增输出：`*_fac_p_value_matrix.csv`、`*_fac_bh_q_value_matrix.csv`。
- `heatmap_summary` 的预期新增/更新输出：含 q-value/family/family role/family size 的 `all_groups_summary.csv`、`heatmap_fdr_significant_fac_summary_q_lt_0_05.csv`、`heatmap_nominal_fac_summary_p_lt_0_05.csv`、`effective_mn_summary.csv`、`fdr_metadata.json` 和 `heatmap_conclusion.md`。
- 当前状态（2026-07-05 增量核验）：正式 `heatmap_summary` 已刷新并含 q-value 矩阵与 `fdr_metadata.json`；六个 family 各 132 项。Full sample 主候选 0 个、探索候选 5 个、稳健候选 0 个。

## 6. 发现的问题

### Critical

#### C2. 普通未来收益原先未执行持有期连续样本/经理 regime 约束（已修复，结果待重跑）

- 位置：`2_fund_managers.py` 与 `2_fund_filter.py` 已正确执行“预测时点 t 的经理团队稳定满 12 个月”门槛；`3_generate_panel_base.py:429-483` 生成持有期逐月检查的 `match_is_sample_future_ret_*`。原 registry 只使用 `is_insample_future_ret_*`。
- 原表现：t 时点入样资格正确，但 Y 只需 t 与 t+h NAV 存在，未来持有期可能跨经理变更。
- 修复：`get_regression_config()` 现在按 Y 期限自动追加对应 `match_is_sample_future_ret_{h}m = 1`；代表窗口期限脚本同步采用相同筛选。
- 后续：受影响的正式模型需要从 B_factors preprocess 开始重跑，旧结果不能自动视为新口径结果。
- 需人工确认：否（用户已确认采用同一 regime 口径）。

#### C3. `fm_heatmap_top33_y12m` 原先错用 6 个月样本截止标记（已修复，结果待重跑）

- 位置：`D_analysis/config/regression_registry.py:1869-1948`。
- 表现：派生函数替换 `y` 和 winsorize 列，但没有把 `sample_filters={is_insample_future_ret_6m:1}`、`sample_flag_columns` 改成 12m。已生成 summary 明确记录 156,184 行和 6m 标记。
- 影响：若样本内截止为 2022-12，部分 12 月 Y 延伸到截止日之后；属于样本内/样本外口径错误。该目录虽无主回归 metadata，但其 B_factors 面板可被组合排序直接读取。
- 修复：registry 读取时会根据普通 Y 自动规范化同期限 `is_insample` 与 `match_is_sample`；12m 模型现为两项 12m 筛选，并已增加 registry 单测。
- 需人工确认：否（错误明确）。

#### C4. PPT storyline 的交互项核心结论与当前结果相反

- 位置：`H_presentation/fund_consistency_storyline.md:198-211`（`PPT格式.md` 同步复制）；当前结果 `D_analysis/output/fund_consistency/fm_baseline_interaction/fama_macbeth_results.csv`。
- 表现：文档声称 m3_n6/m6_n6 交互显著为正、m6_n3 边缘显著；当前去均值交互结果分别约 t=-0.45、-0.44、-1.18，均不显著，且符号为负。`noctrlLTM` 版本也均不显著。
- 已确认的版本差异：Git 历史中的旧正向结果模型只加入 FAC、控制变量和 `FAC × rank_mean`，没有加入 `rank_mean` 主效应，违反交互项层级原则；当前模型同时加入 FAC 与 rank_mean 主效应，再构造月度截面去均值交互。因此两组系数不是同一模型口径，旧正向交互不能直接移植到当前模型。
- 影响：当前“FAC×方向有条件效应”的核心叙事不能由现有最新结果支持；若直接进入 PPT，会形成实质错误结论。
- 建议：完成 regime、CtrlVol 等新口径重跑后，以包含双方主效应的当前模型为正式结论；旧结果仅作为“遗漏 rank_mean 主效应的历史版本”归档。
- 需人工确认：是（决定保留哪个模型口径）。

#### C5. 热力图多重检验代码与正式汇总均已刷新，选择后推断风险仍存在

- 位置：`D_analysis/scripts/plot_consistency_heatmaps.py`；`D_analysis/output/fund_consistency/heatmap_summary/`。
- 原表现：五个样本组 × 144 个 `(m,n)` 单元按 `|t|>=1.96` 挑选候选，没有 FDR/FWER 或留出样本。
- 已修复代码：新增 `fm_heatmap_full` 主检验族；Full sample 与五个探索分组分别做模型内 BH-FDR；无效 p-value 不进入 family；正式候选规则改为基于 `q<0.05` 和方向一致性。
- 已完成：正式 `heatmap_summary` 已按新代码刷新；Full sample 主候选 0 个，五个探索分组合计形成 5 个探索候选，稳健候选 0 个。
- 尚存风险：BH 不能修复在同一数据上选择代表窗口后再次检验的选择后推断问题。
- 建议：冻结候选规则；探索候选后续使用时间切分、样本外验证或预注册确认。
- 需人工确认：是（确认探索结果与验证结果的边界），但不再需要确认是否采用 BH-FDR。

### Major

#### M1. 顶层文档无法解释当前项目主线

- `项目介绍.md` 只解释 RBSA；没有顶层 README 串起 A→B→D→H。
- 影响：新协作者可能把 RBSA 当作唯一主线，无法判断 100 个 registry 模型的权威版本。
- 建议：建立顶层总览和“当前正式结果”索引。

#### M2. 文档声称的模型、控制项和推断方式与代码不一致

- `fund_consistency_storyline.md:45` 声称控制 beta、主体面板/横截面使用聚类标准误、组合层用 bootstrap。
- 实际 registry 没有 beta；主实现是 Fama-MacBeth + 月度系数 NW(5)；无基金 FE；组合排序主实现为普通或 NW t 值。
- 研究计划还写时间固定效应、基金固定效应/双向聚类等，但当前没有面板模型产物。
- 建议：把“计划”“当前已实现”“稳健性待做”分栏，不要混写完成时。

#### M3. m/n 与 pairwise 的核心代码已修正，运行手册仍然错误

- 代码当前统一：m=return_horizon，n=rank_count，完全不重叠时 `pairwise=m`。
- 核心 Python docstring 已修正；但 `A_data/scripts/腳本管理說明檔案.md:77-80` 仍把 m/n 写反，PPT/旧 storyline 仍有 `pairwise=n` 等残留。
- 影响：容易再次生成错列名、错窗口或误读历史跨度。
- 建议：建立唯一术语表，并在所有文档中引用。

#### M4. n=1 的 FAC 热力图规格数学上无定义（代码与正式汇总已修复）

- `RANK_VOL_DDOF=1`，单个排名的样本标准差为 NaN；实查 12 个 `FAC_rank_vol_m*_n1` 非空数均为 0。
- 当前 registry 与正式 summary 已从 n=2 开始，每个 family 为 132 项；旧 12×12 图或文档若仍流通，仍可能把“未定义”误读为“不显著”。
- 建议：归档旧 144 格产物，展示层只保留 132 格口径。

#### M5. 研究故事仍使用旧 Top30/Bottom30 与旧 dummy 结果

- 当前 registry 明确用 Top50/Top33/Bottom33，且新 nonoverlap 主层是 HitRate、次层是累计 dummy。
- storyline 仍大量描述 top30/bottom30、互斥 hit dummy、特殊 n=12 三档规则和旧 `fm_winrates_top50_nonoverlap` 结果。
- 影响：PPT 可能引用已被替代的模型；Top50 与 Bottom50 的完全对称结果部分是互补编码的机械关系，不能当独立验证。
- 建议：为旧结果加“archived”标签，主文只引用新三口径正式 run。

#### M6. 结果版本与可追踪元数据不足

- 当前 100 个正式模型均有主 `run_metadata.json`；但一级结果目录中的 metadata 仍缺少统一 run_id、代码快照和输出清单。
- 批量 JSON 普遍没有 `run_id`、`script_name`、`parameters`、`output_files`；字段名混用 `run_time`/`generated_at`。
- 大量固定目录被后续运行覆盖，storyline 没有记录引用结果的 run hash/mtime。
- 建议：统一 manifest，至少写 run_id、generated_at、git commit/dirty、input hash、script、registry key、参数、输出清单。

#### M7. 操作说明与 B_factors README 已过时

- `SY_Reference/操作说明.md` 写 `preapred_data`、不存在的 `descriptive_analysis.py`，且示例输入指向 `A_data/output`，当前脚本名为 `4_descriptive_analysis.py`。
- `B_factors/README.md` 多处说 runner 只支持 `fm_baseline`；当前代码明确支持其他 registry key。
- 影响：按文档操作会失败或误用默认输出。

#### M8. 市态任务状态文档与实际产物不同步

- `SY_Reference/task_plan.md` 仍写 31 个模型跑批进行中；检查时 32 个市态模型主 run metadata 已基本生成至 08:59，比较目录也已存在。
- 影响：恢复任务可能重复跑批；也无法确认比较表是否最终完成。
- 建议：完成批次后原子更新状态并记录成功/失败模型清单。

#### M9. 普通 FAC 与市态 FAC 的排名分母池不同

- 市态脚本已诚实注明：普通 FAC 会在 t 月按当前截面重排历史窗口，市态 FAC 读取历史月份各自的截面排名。
- 影响：两者差异不只是“选取市态月”，边际模型系数比较同时混入排名池定义差异。
- 建议：PPT/论文明确披露；最好增加同排名口径的对照版本，隔离“市态选月”和“排名基准变化”。

#### M10. 控制变量时间下标不够清楚

- `CtrlRetLTM` 实际为 `NAV_{t-1}/NAV_{t-12}-1`，等价于复合 `R_{t-11}...R_{t-1}`；`CtrlVol` 已按用户口径改为 offset 0..11，即 `R_{t-11}...R_t`，包含 month_date=t 的当月收益。
- 文档只写过去 12 月累计收益/波动率，有时写 `Ret_{t-12,t-2}`，没有统一“month_date=t 代表何时可交易”。
- 影响：不能确认控制项是否与文献定义完全一致，也容易误称所有 X 都滞后一期。
- 建议：画一条时间轴并固定 t 的定义。

### Minor

1. `3_generate_panel_base.py` 顶部仍说只生成未来 3/6/12 月，实际含 1 月。
2. `get_rank_volatility` docstring 中 m/n 文字写反，但循环与列名实现正确。
3. `fm_baseline_up/down` 名称实际按中位数组；历史 `is_top_half_*` 又是 30/40/30，命名容易误导。
4. `bottom33` 已成为统一机器 key；`bm33` 只保留为旧命令兼容别名，`down` 仍表示中位数下半组，不能与 Bottom33 混称。
5. `I_visualization/和Claude同步项目进度.md` 的默认路径仍是旧项目 `MAIN_STYLE_ROTATION`。
6. `CLAUDE.md` 关于中文引号的示例显示异常，规则本身合理但文本可重写。
7. 生成的诊断 Markdown 多达数十份且内容高度重复，应在目录层增加索引，不宜逐份作为权威文档。
8. JSON 文献抽取文件与运行 manifest 混在同一扩展名统计中，建议按用途分目录并加 schema/version。
9. `H_presentation/~$基金一致性课题汇报.pptx` 是 Office 临时锁文件，容易误入版本管理。
10. 代码兼容入口 `D_analysis/scripts/regression_registry.py` 不是重复配置，只是转发；应在文件清单中标为 compatibility shim，避免误删。
11. `A_data/scripts/2_fund_filter.py` 按全样本 NAV 完整度、累计规模和主代码同名规则静态选择代表份额，包含全样本信息。用户接受该规则，因为它只用于同一 `main_code` 内去重、不作为预测变量；方法说明仍应披露这一点，不再作为 Critical 或强制 point-in-time 改造项。

## 7. 疑似过时文件 / 重复文件清单

| 文件/目录 | 判断理由 | 建议（本次不处理） |
|---|---|---|
| `H_presentation/基金一致性课题汇报拷貝.pptx` | 与正式汇报同名拷贝 | 确认后移入 archive，并记录最终版 |
| `H_presentation/~$基金一致性课题汇报.pptx` | Office 临时锁文件 | 关闭 Office 后确认是否可删 |
| `H_presentation/PPT格式.md` | 与 storyline 大段重复且含同样旧结论 | 只保留模板规则，研究内容引用单一来源 |
| `B_factors/bin/archived_quantile_group_logic.py` | 文件名已标 archived | 保留到 archive 目录，禁止主流程导入 |
| `B_factors/output/runner_compare/old_big_script*` | 旧大脚本对比产物 | 标记 validation snapshot 与日期 |
| `B_factors/output/registry_runner_compare/old_big_script.parquet` | 同上且目录重复 | 合并索引，不直接删除 |
| `B_factors/output/baseline_original/`、`baseline_current/` | 同类结果多版本 | 写比较说明与生成日期 |
| `B_factors/output/debug_steps/`、`debug_factor_filters_steps/` | 调试中间结果 | 迁入明确的 scratch/archive |
| `B_factors/output/fm_winrates_top30_nonoverlap/`、`bottom30_nonoverlap/`、`bottom50_nonoverlap/` | 已被新 Top33/Bottom33 设计替代 | 标记 legacy，不作为当前结论来源 |
| `D_analysis/output/fund_consistency/fm_winrates_top50_nonoverlap/` | 现有 run 是旧互斥 dummy 配置，当前 registry 同 key 已变成 36 HitRate+累计 dummy | 高风险同 key 不同模型；必须版本化 key 后再跑 |
| `D_analysis/output/fund_consistency/representative_window_horizon_tests/20260630_*` | 同日四个版本，差异需读 metadata 才知道 | 增加 `latest_valid` manifest，禁止凭时间猜 |
| `D_analysis/scripts/summarize_fm_winrates_nonoverlap.py` | 仍硬编码 Top30/Bottom30 | 标记 legacy 或升级后再用 |
| `项目介绍.md` | 只介绍 RBSA，作为项目总说明已过时 | 改名 RBSA_README 或扩写总览 |
| `SY_Reference/操作说明.md` | 路径与脚本名过时 | 下一轮修订 |
| `B_factors/README.md` | runner 能力说明过时 | 下一轮修订 |
| `I_visualization/和Claude同步项目进度.md` | 指向旧项目路径 | 标记历史交接文档 |
| `A_data/prepared_data/FUND_MKT_Quotation_stream_test.parquet` | 文件名明确 test | 确认是否被任何主流程引用后归档 |

特别风险：`fm_winrates_top50_nonoverlap` 的目录结果时间为 2026-06-27，metadata 仍列 5 组旧互斥 dummy；当前同名 registry 已是 72 个 factor spec（36 HitRate + 36 累计 dummy 组）。这是“同 key 语义漂移”，不能仅凭目录名认定结果对应当前代码。

## 8. 建议修改清单

### P0：必须确认/修复

1. 确认状态匹配 Y 是否必须保持 t 时点经理 regime；若是，补全区间匹配标签后再重跑 ymatch。
2. 冻结正式交互模型口径；撤下 PPT/storyline 中与当前结果不符的旧交互结论。
3. 修复市态摘要对累计 `_hit_aboveN_` 的解析，并让摘要消费 FDR q-value，而不是只看 `|t|>=1.96`。
4. 为同 key 语义漂移的 `fm_winrates_top50_nonoverlap` 建立版本化/冻结说明，不能覆盖解释旧结果。

### P1：建议修复

1. 建立顶层 README、数据流程图、变量字典和模型索引。
2. 统一 m/n/pairwise、Top/Bottom、up/down/bottom33 展示命名，并在新结果中停止使用旧 `bm33` 路径。
3. 统一 run manifest 并记录输入/代码 hash。
4. 把计划模型与已实现模型分开；修正文档中 beta、FE、cluster、bootstrap 的完成状态。
5. 对普通 FAC 与市态 FAC 增加同口径对照。
6. 修订操作说明和 B_factors README。
7. 给 100 个 registry key 增加 status：primary/exploratory/legacy/pending。

### P2：可选优化

1. 归档调试、旧 top30、旧大脚本对比与 PPT 拷贝。
2. FAC heatmap 明确从 n=2 开始。
3. 统一中文简体注释与文档语言。
4. 为批量诊断 Markdown/Excel 添加自动索引页。
5. 增加只读 lint/registry schema 检查与“文档引用结果是否匹配 metadata”的自动校验。

## 9. 后续建议

按优先级建议下一轮做 5 件事：

1. **冻结仍未确定的研究口径**：代表份额静态去重和经理 regime 的 Y 已确认；下一步只需冻结正式交互模型以及热力图探索结果如何进入验证阶段。
2. **建立可复现冻结点**：指定 3–5 个 primary model key，生成统一 manifest，并把当前 PPT 每个数字绑定到具体结果文件与 run id。
3. **完成修复闭环**：12m 样本标记代码已修复，下一步处理同 key 语义漂移与 n=1 heatmap 展示，并为新增规则补充小型单测。
4. **再做有限重跑**：只重跑受 P0 影响的主模型和对照，不先跑全部 100 个模型。
5. **最后更新文档/PPT**：以修复后的 frozen results 自动生成结论表，删除“计划即完成”的表达。

## 10. 最终摘要

1. 初始只读审查是否修改项目文件：否（仅新建本审核报告）；后续已按用户明确授权实施并记录修复。
2. 是否 commit：否。
3. 是否 push：否；已尝试，但当前无本地提交可推，且 GitHub CLI token 失效/联网推送未完成。由于用户禁止 commit，本报告保留为未提交文件，不能进入远端提交历史。
4. Critical 问题数量：当前 active 2 个（C4、C6）；C1 已降级，C2/C3 已修复，C5 的代码与正式汇总已完成、仅余选择后推断风险。
5. Major 问题数量：17 个追踪项（其中部分为“代码已修复、旧文档/旧结果待归档”）。
6. 最需要人工确认的 3 个问题：
   - 状态匹配未来收益是否必须限制在同一经理 regime；
   - 正式交互模型是否彻底放弃旧“正向显著交互”叙事；
   - WinRate/市态汇总的旧结果采用何种版本化与归档方案。
7. 是否建议下一轮开始修改：可以，但应先处理 C6 与 PPT 旧结论，再修摘要/FDR 接口；不要直接全量重跑 100 个模型。
