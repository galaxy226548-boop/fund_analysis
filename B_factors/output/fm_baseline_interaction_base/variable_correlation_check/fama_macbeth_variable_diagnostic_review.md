# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:35:01

## 一、审核口径

- 分析变量数：16。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 5 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetLTM | rank_mean_m3_n6_pairwise1 | 0.730 | 0.730 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m6_n3_pairwise1 | 0.732 | 0.732 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m6_n6_pairwise1 | 0.839 | 0.839 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m6_n12_pairwise1 | 0.865 | 0.865 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m12_n6_pairwise1 | 0.866 | 0.866 | *** | 101 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次发现 9 个 VIF 风险变量：

| variable | mean_vif | median_vif | p90_vif | max_vif | ok_months | failed_or_skipped_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CtrlRetLTM | 3.595 | 3.511 | 5.150 | 6.342 | 131 | 84 | VIF 风险 |
| CtrlRetLTM | 3.590 | 3.481 | 5.241 | 7.835 | 131 | 84 | VIF 风险 |
| rank_mean_m6_n3_pairwise1 | 3.532 | 3.396 | 5.081 | 7.075 | 131 | 84 | VIF 风险 |
| CtrlRetLTM | 6.173 | 5.909 | 8.809 | 12.871 | 117 | 98 | VIF 风险 |
| rank_mean_m6_n6_pairwise1 | 5.794 | 5.492 | 8.436 | 11.768 | 117 | 98 | VIF 风险 |
| CtrlRetLTM | 5.895 | 5.635 | 8.612 | 14.239 | 96 | 119 | VIF 风险 |
| rank_mean_m6_n12_pairwise1 | 5.596 | 5.347 | 7.712 | 12.713 | 96 | 119 | VIF 风险 |
| rank_mean_m12_n6_pairwise1 | 5.527 | 5.371 | 8.273 | 10.066 | 96 | 119 | VIF 风险 |
| CtrlRetLTM | 5.785 | 5.568 | 8.079 | 11.456 | 96 | 119 | VIF 风险 |

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
