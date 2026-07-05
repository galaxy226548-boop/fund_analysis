# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:55:47

## 一、审核口径

- 分析变量数：39。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 26 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetLTM | dummy_top50_m3_n6_hit_above2_pairwise1 | 0.528 | 0.528 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m3_n6_hit_above3_pairwise1 | 0.550 | 0.550 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n3_hit_above0_pairwise1 | 0.537 | 0.537 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n3_hit_above1_pairwise1 | 0.581 | 0.581 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n3_hit_above2_pairwise1 | 0.566 | 0.566 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n6_hit_above0_pairwise1 | 0.531 | 0.531 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n6_hit_above1_pairwise1 | 0.606 | 0.606 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n6_hit_above2_pairwise1 | 0.638 | 0.638 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n6_hit_above3_pairwise1 | 0.646 | 0.646 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n6_hit_above4_pairwise1 | 0.633 | 0.633 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n6_hit_above5_pairwise1 | 0.577 | 0.577 | *** | 124 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above2_pairwise1 | 0.525 | 0.525 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above3_pairwise1 | 0.582 | 0.582 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above4_pairwise1 | 0.629 | 0.629 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above5_pairwise1 | 0.661 | 0.661 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above6_pairwise1 | 0.680 | 0.680 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above7_pairwise1 | 0.663 | 0.663 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above8_pairwise1 | 0.634 | 0.634 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above9_pairwise1 | 0.587 | 0.587 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n12_hit_above10_pairwise1 | 0.506 | 0.506 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m12_n6_hit_above0_pairwise1 | 0.617 | 0.617 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m12_n6_hit_above1_pairwise1 | 0.660 | 0.660 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m12_n6_hit_above2_pairwise1 | 0.679 | 0.679 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m12_n6_hit_above3_pairwise1 | 0.694 | 0.694 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m12_n6_hit_above4_pairwise1 | 0.694 | 0.694 | *** | 101 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m12_n6_hit_above5_pairwise1 | 0.668 | 0.668 | *** | 101 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次未发现稳定偏高的 VIF 风险变量。

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
