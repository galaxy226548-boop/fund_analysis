# Fama-MacBeth 变量相关性与 VIF 输出说明

本目录由脚本 `B_factors/scripts/2_factor_correlation.py` 生成，用来检查进入
Fama-MacBeth 横截面回归的解释变量之间是否存在明显相关性或多重共线性。

默认输入文件是：

```bash
B_factors/output/panel_base.parquet
```

默认输出目录是：

```bash
B_factors/output/variable_correlation_check/
```

## 一、计算口径

### 1. 变量来源

如果运行脚本时不手动指定变量，脚本会从：

```bash
B_factors/scripts/1_fund_consistency_factors_clear.py
```

动态读取：

- `CONSISTENCY_COLUMNS`
- `CONTROL_COLUMNS`

最终分析变量为：

```python
CONSISTENCY_COLUMNS + CONTROL_COLUMNS
```

如果运行时使用 `--variables col1,col2,...`，脚本会只使用这组手动指定变量，
并忽略默认的 Consistency / Control 分组。

### 2. 相关系数口径

相关系数不是直接对全样本 pooled 面板计算，而是采用 Fama-MacBeth 的月度横截面口径：

1. 按 `month_date` 分月。
2. 每个月只保留所有分析变量均非缺失的样本。
3. 如果某个月完整样本数小于 `MIN_CROSS_SECTION_N`，该月跳过。
4. 对每个月的基金横截面计算 Pearson 相关系数矩阵。
5. 对每一对变量的月度相关系数取时间序列均值。
6. 对非对角线变量对做单样本 t 检验，检验“月度相关系数均值是否显著不等于 0”。

因此，表里的相关系数应理解为“平均月度横截面相关系数”，不是 pooled 相关系数。

### 3. VIF 口径

VIF 分两种：

- 月度 VIF：每个月单独用当月横截面样本计算一次 VIF，再对月度 VIF 做时间序列汇总。
- 整体 VIF：把所有月份 pooled 到一起计算一次 VIF，仅作为补充诊断。

月度 VIF 更贴近 Fama-MacBeth 每月横截面回归的设定；整体 VIF 可以帮助快速观察全样本平均意义上的共线性。

## 二、输出文件说明

### 1. `fama_macbeth_correlation_summary_long.csv`

长格式相关系数结果。每一行是一对变量的相关性汇总。

主要字段：

- `row_variable`：相关矩阵的行变量。
- `col_variable`：相关矩阵的列变量。
- `mean_corr`：这对变量的月度横截面 Pearson 相关系数的时间序列均值。
- `p_value`：对月度相关系数序列做单样本 t 检验得到的 p 值。
- `stars`：显著性星号，`***`、`**`、`*` 分别代表 1%、5%、10% 显著性水平。
- `n_months`：这对变量有多少个月能计算出有效相关系数。

解读方式：

- `mean_corr` 越接近 1 或 -1，表示两变量在月度横截面里平均相关性越强。
- 对角线变量与自身相关，`mean_corr` 为 1，通常不用解读 `p_value`。
- `stars` 说明平均相关系数是否显著不为 0，但“显著”不等于“经济上很大”；还要看 `mean_corr` 的绝对值。

### 2. `fama_macbeth_correlation_table.csv`

宽格式纯数值相关系数矩阵。

特点：

- 行和列都是分析变量。
- 单元格是 `mean_corr`。
- 上三角和下三角对称。
- 适合后续程序读取、画热力图或导入 Excel 做格式化。

解读方式：

- 绝对值在 0.3 以下通常表示线性相关性较弱。
- 绝对值在 0.3 到 0.7 之间表示中等相关，需要结合变量含义判断。
- 绝对值超过 0.7 时，建议重点检查是否存在明显变量重叠或多重共线性风险。

这些阈值只是经验参考，不是硬性统计规则。

### 3. `fama_macbeth_correlation_table_with_stars.csv`

带显著性星号的展示型相关系数矩阵。

特点：

- 行和列都是分析变量。
- 非对角线单元格形如 `0.481***`。
- 数字表示平均月度横截面相关系数。
- 星号表示这对变量的月度相关系数均值是否显著不为 0。
- 这是 CSV 文件，只保存表格内容，不保存单元格居中、颜色等展示样式。

解读方式：

- 适合直接复制到报告或论文附录中。
- 如果一个单元格有很多星号，但相关系数绝对值很小，说明统计显著但经济关系未必强。
- 如果相关系数绝对值很大，即使没有星号，也应该结合 `n_months` 和样本情况复查。
- 如果需要真正居中显示，应另行导出 Excel 或 HTML；CSV 本身无法保存居中格式。

### 4. `fama_macbeth_monthly_vif_long.csv`

月度 VIF 明细长表。每一行是“某个月、某个变量”的 VIF 结果。

主要字段：

- `month_date`：月份。
- `variable`：变量名。
- `vif`：该变量在该月横截面中的 VIF。
- `n_obs`：该月完整变量样本数。
- `status`：计算状态。
- `reason`：跳过或失败原因。

`status` 的含义：

- `ok`：该月该变量成功计算 VIF。
- `skipped`：该月样本数不足，没有计算 VIF。
- `failed`：样本数足够，但由于变量无波动、矩阵秩不足、相关矩阵无法求逆等原因，VIF 无法稳定计算。

解读方式：

- 这是最细的诊断表，适合定位某些月份是否存在异常共线性。
- 如果某个变量在很多月份 `failed`，说明这个变量可能在月度横截面中经常没有波动，或者和其他变量高度共线。
- 如果早期月份大量 `skipped`，通常是因为上游数据覆盖不足，不一定代表变量本身有问题。

### 5. `fama_macbeth_time_series_vif_summary.csv`

月度 VIF 的时间序列汇总表。每一行是一个变量。

主要字段：

- `variable`：变量名。
- `mean_vif`：成功计算月份中，月度 VIF 的均值。
- `median_vif`：月度 VIF 的中位数。
- `p90_vif`：月度 VIF 的 90 分位数。
- `max_vif`：月度 VIF 的最大值。
- `ok_months`：成功计算 VIF 的月份数。
- `failed_or_skipped_months`：跳过或失败的月份数。

解读方式：

- 优先看 `mean_vif`、`median_vif` 和 `p90_vif`，它们比单个月最大值更稳定。
- `max_vif` 可以帮助发现个别月份的极端共线性。
- 如果 `ok_months` 很少，说明该变量的 VIF 汇总可信度有限。

常见经验判断：

- VIF 接近 1：变量几乎不能被其他解释变量线性解释，共线性风险低。
- VIF 大于 5：需要关注，可能存在中等偏高的共线性。
- VIF 大于 10：通常表示较强共线性，应重点检查变量设计。

这些阈值是经验规则，最终仍要结合研究设计和回归结果判断。

### 6. `fama_macbeth_overall_vif.csv`

整体 pooled VIF 结果。脚本把所有月份的完整样本合在一起，计算一次 VIF。

主要字段：

- `variable`：变量名。
- `vif`：pooled 样本下的 VIF。
- `n_obs`：pooled 完整样本数。
- `status`：计算状态。
- `reason`：失败原因。

解读方式：

- 这个表是补充诊断，不是 Fama-MacBeth 的主口径。
- 如果 pooled VIF 很高，但月度 VIF 不高，可能说明共线性主要来自跨月份均值差异。
- 如果 pooled VIF 和月度 VIF 都高，则更有理由怀疑变量之间存在稳定的横截面共线性。

### 7. `fama_macbeth_variable_correlation_metadata.json`

本次运行的元信息文件，用来复现和审计结果。

主要内容：

- `run_time`：脚本运行时间。
- `input_path`：输入 parquet 路径。
- `output_dir`：输出目录。
- `date_col`：日期列名。
- `min_cross_section_n`：月度最小样本数门槛。
- `source_config_script`：默认变量清单来源脚本。
- `variable_source_info`：最终变量列表及其来源。
- `input_rows`：输入表行数。
- `input_months`：输入表月份数。
- `correlation`：相关系数计算中的有效月份和跳过月份信息。
- `vif`：VIF 计算中的成功、失败、pooled 状态等信息。

解读方式：

- 如果需要确认某次结果到底用了哪些变量，应先看 `variable_source_info.variables`。
- 如果输出结果和预期不一致，应检查 `input_path`、`min_cross_section_n` 和变量来源。
- 如果相关系数有效月份数偏少，应查看 `correlation.skipped_months`。

### 8. `result_fama_macbeth_correlation_risk_pairs.csv`

最终相关性审核结果文件。每一行是一组被标注为存在相关性风险的唯一变量对。

筛选规则：

- 删除变量和自身相关的对角线行。
- 将 A-B 和 B-A 视为同一组，只保留一次。
- 计算 `abs_mean_corr = abs(mean_corr)`。
- 保留 `abs_mean_corr >= 0.50` 的变量对。
- 如果 `stars` 不为空，标注为 `重点关注相关性风险`。

主要字段：

- `variable_1` / `variable_2`：风险变量对。
- `mean_corr`：平均月度横截面相关系数，保留正负方向。
- `abs_mean_corr`：相关系数绝对值，用于判断风险大小。
- `p_value` / `stars`：月度相关系数均值的显著性检验结果。
- `n_months`：有效月份数。
- `risk_level`：风险等级。
- `review_note`：人工复核建议。

解读方式：

- 这是最建议优先查看的相关性风险结果表。
- `abs_mean_corr >= 0.50` 是为了抓出中高相关变量对，比 0.70 更审慎，又不会像 0.30 那样提示过多弱相关。
- `stars` 不用于决定是否存在风险，只用于把已达到阈值的变量对升级为重点关注。

### 9. `result_fama_macbeth_vif_risk_variables.csv`

最终 VIF 审核结果文件。每一行是一个被标注为 VIF 风险的变量。

筛选规则：

- 使用 `fama_macbeth_time_series_vif_summary.csv` 中的 `p90_vif`。
- 保留 `p90_vif > 5` 的变量。
- 按 `p90_vif` 从高到低排序。

主要字段：

- `variable`：变量名。
- `mean_vif` / `median_vif` / `p90_vif` / `max_vif`：月度 VIF 的时间序列统计。
- `ok_months`：成功计算 VIF 的月份数。
- `failed_or_skipped_months`：跳过或失败月份数。
- `risk_metric`：本次使用的审核指标，默认为 `p90_vif`。
- `risk_threshold`：本次使用的审核阈值，默认为 5。
- `risk_level`：风险等级。
- `review_note`：人工复核建议。

解读方式：

- `p90_vif > 5` 表示较高月份的 VIF 已经进入需要关注的区间。
- 使用 `p90_vif` 是为了代表较高月份的常态风险，同时避免 `max_vif` 被单个月份异常放大。
- 如果这个文件为空，说明按当前主口径没有发现稳定偏高的 VIF 风险变量。

### 10. `fama_macbeth_variable_diagnostic_review.md`

人工可读审核报告。它把相关性风险和 VIF 风险汇总到一份 Markdown 文件里。

主要内容：

- 本次使用的审核阈值。
- 相关性风险变量对清单。
- VIF 风险变量清单。
- 对当前结果的简短解读和后续检查建议。

解读方式：

- 如果只是想快速看结论，可以先打开这个文件。
- 如果需要后续筛选、排序或粘贴到 Excel，使用两个 `result_` 前缀 CSV。

## 三、相关系数和 VIF 的一般判断标准

下面的区间是经验判断，主要用于快速筛查。它们不是硬性统计规则，也不代表必须机械删除变量。真正是否需要调整，仍要结合变量的经济含义、研究设计、回归结果稳定性和样本覆盖情况判断。

### 1. 相关系数怎么看

这里主要看 `fama_macbeth_correlation_table.csv` 或
`fama_macbeth_correlation_summary_long.csv` 里的 `mean_corr`，并关注绝对值：

| `abs(mean_corr)` 区间 | 一般判断 | 建议处理 |
| --- | --- | --- |
| `< 0.30` | 相关性较低，通常 OK | 一般不需要因为相关性单独调整变量。 |
| `0.30 - 0.50` | 有一定相关性，但通常不算严重 | 可以保留；如果两个变量经济含义很接近，再进一步检查。 |
| `0.50 - 0.70` | 相关性偏高，需要留意 | 建议检查变量定义是否重叠，并结合 VIF、回归系数稳定性判断是否保留。 |
| `0.70 - 0.80` | 相关性较高 | 建议重点检查；如果变量含义高度相似，可以考虑二选一、合成指标或分开做稳健性回归。 |
| `> 0.80` | 相关性很高 | 通常需要认真处理，除非两个变量必须同时进入模型且有明确经济理由。 |
| `> 0.90` | 极高相关 | 很可能存在重复变量、机械构造关系或严重共线性，通常不建议同时放入同一个模型。 |

解读时要注意：

- 正相关和负相关都可能造成共线性风险，所以重点看绝对值。
- `stars` 只表示平均相关系数是否显著不为 0，不代表相关性大小。样本月份多时，较小的相关系数也可能显著。
- 如果两个变量相关系数高，但 VIF 不高，说明它们和其他变量一起进入模型时未必造成严重多重共线性。
- 如果多个变量两两相关都不算特别高，但 VIF 偏高，可能是多个变量组合起来存在共线性。

### 2. VIF 怎么看

这里优先看 `fama_macbeth_time_series_vif_summary.csv`，尤其是：

- `median_vif`：典型月份的共线性水平。
- `mean_vif`：平均共线性水平。
- `p90_vif`：偏高月份的共线性水平。
- `max_vif`：极端月份是否出现严重共线性。

常见经验区间：

| VIF 区间 | 一般判断 | 建议处理 |
| --- | --- | --- |
| `< 2` | 共线性风险很低 | 通常 OK。 |
| `2 - 5` | 轻度到中度共线性 | 多数情况下可以接受；如果变量系数不稳定，再进一步检查。 |
| `5 - 10` | 共线性偏高 | 需要重点关注；建议检查相关变量定义、回归结果稳定性和稳健性模型。 |
| `> 10` | 共线性较严重 | 通常建议调整变量组合，例如删除、合并、替换变量，或分模型展示。 |
| `> 20` | 非常严重 | 基本说明该变量能被其他解释变量高度线性解释，通常不适合同模型保留。 |

本项目更建议按下面方式判断：

- 如果 `median_vif < 5` 且 `p90_vif < 10`，一般可以认为月度横截面共线性整体可接受。
- 如果 `median_vif < 5` 但 `max_vif` 很高，通常是少数月份异常；可以到 `fama_macbeth_monthly_vif_long.csv` 定位具体月份。
- 如果 `mean_vif`、`median_vif`、`p90_vif` 都偏高，说明共线性不是偶发问题，建议调整变量组合。
- 如果 `failed_or_skipped_months` 很多，要先看失败原因；样本不足和矩阵秩不足代表的问题不同。

### 3. 什么时候需要改变量

一般可以按下面顺序判断是否需要调整变量：

1. 先看相关性审核结果，找出 `abs(mean_corr) >= 0.50` 的变量对。
2. 再看这些变量的 VIF，尤其是 `median_vif` 和 `p90_vif`。
3. 如果相关系数高、VIF 也高，并且变量经济含义相近，优先考虑调整。
4. 如果相关系数高但两个变量代表不同经济含义，可以保留一个主模型，再做删除其中一个变量的稳健性检验。
5. 如果只是 `stars` 显著但相关系数绝对值不大，通常不需要因为显著性星号而修改变量。

常见处理方式包括：

- 删除经济含义重复或构造方式高度相近的变量。
- 在多个相近变量中保留理论上最重要、解释最清楚的一个。
- 把高度相关的一组变量合成为一个指标。
- 分模型放入高度相关变量，避免在同一个回归里同时出现。
- 保留主变量，把其他高度相关变量作为稳健性检验。

## 四、建议的检查顺序

建议按下面顺序检查：

1. 先打开 `fama_macbeth_variable_diagnostic_review.md`，快速看本次审核结论。
2. 查看 `result_fama_macbeth_correlation_risk_pairs.csv`，确认需要重点关注的相关性风险变量对。
3. 查看 `result_fama_macbeth_vif_risk_variables.csv`，确认是否存在 `p90_vif > 5` 的 VIF 风险变量。
4. 再打开 `fama_macbeth_variable_correlation_metadata.json`，确认输入路径、变量列表和样本门槛正确。
5. 如需追溯明细，查看 `fama_macbeth_correlation_summary_long.csv` 和 `fama_macbeth_time_series_vif_summary.csv`。
6. 如发现 VIF 异常，再打开 `fama_macbeth_monthly_vif_long.csv` 定位具体月份和失败原因。
7. 最后用 `fama_macbeth_overall_vif.csv` 作为 pooled 口径的补充对照。

## 五、命令示例

默认变量口径：

```bash
.venv/bin/python B_factors/scripts/2_factor_correlation.py
```

指定完整变量列表：

```bash
.venv/bin/python B_factors/scripts/2_factor_correlation.py \
  --variables FAC_rank_vol_m6_n6_pairwise1,CtrlRetSTR,CtrlVol,Ctrl_log_fund_size
```

指定输出目录：

```bash
.venv/bin/python B_factors/scripts/2_factor_correlation.py \
  --output-dir B_factors/output/variable_correlation_check_custom
```
