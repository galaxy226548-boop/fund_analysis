# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-03T00:39:34

## 一、审核口径

- 分析变量数：39。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 21 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetLTM | dummy_top50_bmk_m3_n6_hit_above3_pairwise1 | 0.505 | 0.505 | *** | 126 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n3_hit_above1_pairwise1 | 0.533 | 0.533 | *** | 126 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n3_hit_above2_pairwise1 | 0.518 | 0.518 | *** | 126 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n6_hit_above1_pairwise1 | 0.546 | 0.546 | *** | 118 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n6_hit_above2_pairwise1 | 0.576 | 0.576 | *** | 118 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n6_hit_above3_pairwise1 | 0.580 | 0.580 | *** | 118 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n6_hit_above4_pairwise1 | 0.567 | 0.567 | *** | 118 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n6_hit_above5_pairwise1 | 0.517 | 0.517 | *** | 118 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above3_pairwise1 | 0.540 | 0.540 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above4_pairwise1 | 0.577 | 0.577 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above5_pairwise1 | 0.598 | 0.598 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above6_pairwise1 | 0.611 | 0.611 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above7_pairwise1 | 0.597 | 0.597 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above8_pairwise1 | 0.565 | 0.565 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m6_n12_hit_above9_pairwise1 | 0.516 | 0.516 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m12_n6_hit_above0_pairwise1 | 0.565 | 0.565 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m12_n6_hit_above1_pairwise1 | 0.601 | 0.601 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m12_n6_hit_above2_pairwise1 | 0.616 | 0.616 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m12_n6_hit_above3_pairwise1 | 0.624 | 0.624 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m12_n6_hit_above4_pairwise1 | 0.624 | 0.624 | *** | 93 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_bmk_m12_n6_hit_above5_pairwise1 | 0.599 | 0.599 | *** | 93 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次未发现稳定偏高的 VIF 风险变量。

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
