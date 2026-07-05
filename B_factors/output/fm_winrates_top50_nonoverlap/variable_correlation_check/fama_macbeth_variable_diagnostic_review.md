# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:58:12

## 一、审核口径

- 分析变量数：168。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 70 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetSTR | hitrate_top50_m1_n1_pairwise1 | 0.780 | 0.780 | *** | 160 | 重点关注相关性风险 |
| CtrlRetSTR | hitrate_top50_m1_n2_pairwise1 | 0.551 | 0.551 | *** | 159 | 重点关注相关性风险 |
| CtrlRetSTR | hitrate_top50_m2_n1_pairwise2 | 0.539 | 0.539 | *** | 159 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m2_n4_pairwise2 | 0.570 | 0.570 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m2_n5_pairwise2 | 0.646 | 0.646 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m2_n6_pairwise2 | 0.715 | 0.715 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m3_n3_pairwise3 | 0.610 | 0.610 | *** | 134 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m3_n4_pairwise3 | 0.727 | 0.727 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m3_n5_pairwise3 | 0.663 | 0.663 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m3_n6_pairwise3 | 0.615 | 0.615 | *** | 97 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m4_n2_pairwise4 | 0.568 | 0.568 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m4_n3_pairwise4 | 0.725 | 0.725 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m4_n4_pairwise4 | 0.648 | 0.648 | *** | 106 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m4_n5_pairwise4 | 0.590 | 0.590 | *** | 90 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m4_n6_pairwise4 | 0.528 | 0.528 | *** | 74 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m5_n2_pairwise5 | 0.653 | 0.653 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m5_n3_pairwise5 | 0.675 | 0.675 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m5_n4_pairwise5 | 0.596 | 0.596 | *** | 90 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m5_n5_pairwise5 | 0.523 | 0.523 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m6_n2_pairwise6 | 0.735 | 0.735 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m6_n3_pairwise6 | 0.620 | 0.620 | *** | 97 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top50_m6_n4_pairwise6 | 0.527 | 0.527 | *** | 74 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| CtrlRetSTR | dummy_top50_m1_n1_hit_above0_pairwise1 | 0.780 | 0.780 | *** | 160 | 重点关注相关性风险 |
| CtrlRetSTR | dummy_top50_m2_n1_hit_above0_pairwise2 | 0.539 | 0.539 | *** | 159 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m2_n5_hit_above2_pairwise2 | 0.554 | 0.554 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m2_n6_hit_above2_pairwise2 | 0.574 | 0.574 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m2_n6_hit_above3_pairwise2 | 0.600 | 0.600 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m3_n3_hit_above1_pairwise3 | 0.535 | 0.535 | *** | 134 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m3_n4_hit_above1_pairwise3 | 0.587 | 0.587 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m3_n4_hit_above2_pairwise3 | 0.606 | 0.606 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m3_n5_hit_above2_pairwise3 | 0.562 | 0.562 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m3_n6_hit_above3_pairwise3 | 0.505 | 0.505 | *** | 97 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m4_n3_hit_above1_pairwise4 | 0.634 | 0.634 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m4_n3_hit_above2_pairwise4 | 0.503 | 0.503 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m4_n4_hit_above1_pairwise4 | 0.525 | 0.525 | *** | 106 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m4_n4_hit_above2_pairwise4 | 0.538 | 0.538 | *** | 106 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m4_n5_hit_above2_pairwise4 | 0.508 | 0.508 | *** | 90 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m5_n2_hit_above0_pairwise5 | 0.530 | 0.530 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m5_n2_hit_above1_pairwise5 | 0.547 | 0.547 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m5_n3_hit_above1_pairwise5 | 0.593 | 0.593 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m5_n4_hit_above2_pairwise5 | 0.510 | 0.510 | *** | 90 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n2_hit_above0_pairwise6 | 0.591 | 0.591 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n2_hit_above1_pairwise6 | 0.620 | 0.620 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_m6_n3_hit_above1_pairwise6 | 0.545 | 0.545 | *** | 97 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次未发现稳定偏高的 VIF 风险变量。

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
