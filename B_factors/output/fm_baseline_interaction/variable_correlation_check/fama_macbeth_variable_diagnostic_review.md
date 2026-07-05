# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:34:33

## 一、审核口径

- 分析变量数：17。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 8 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetLTM | rank_mean_m3_n6_pairwise1__dmcs | 0.730 | 0.730 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m6_n3_pairwise1__dmcs | 0.732 | 0.732 | *** | 135 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.524 | 0.524 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m6_n6_pairwise1__dmcs | 0.839 | 0.839 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m6_n12_pairwise1__dmcs | 0.865 | 0.865 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | rank_mean_m12_n6_pairwise1__dmcs | 0.866 | 0.866 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | FAC__x__RANK_MEAN__dmcs | 0.537 | 0.537 | *** | 101 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.535 | 0.535 | *** | 101 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次发现 10 个 VIF 风险变量：

| variable | mean_vif | median_vif | p90_vif | max_vif | ok_months | failed_or_skipped_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rank_mean_m3_n6_pairwise1__dmcs | 4.009 | 3.925 | 5.708 | 8.157 | 131 | 84 | VIF 风险 |
| CtrlRetLTM | 3.690 | 3.649 | 5.239 | 7.302 | 131 | 84 | VIF 风险 |
| CtrlRetLTM | 3.700 | 3.549 | 5.498 | 7.853 | 131 | 84 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 3.819 | 3.664 | 5.267 | 7.359 | 131 | 84 | VIF 风险 |
| CtrlRetLTM | 6.447 | 6.347 | 9.182 | 13.257 | 117 | 98 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 6.060 | 5.711 | 8.814 | 11.771 | 117 | 98 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 6.635 | 6.286 | 9.390 | 12.839 | 96 | 119 | VIF 风险 |
| CtrlRetLTM | 6.344 | 5.878 | 9.242 | 14.392 | 96 | 119 | VIF 风险 |
| CtrlRetLTM | 6.206 | 5.794 | 9.001 | 12.831 | 96 | 119 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 5.716 | 5.478 | 8.353 | 10.195 | 96 | 119 | VIF 风险 |

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
