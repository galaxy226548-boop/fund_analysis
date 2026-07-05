# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:54:58

## 一、审核口径

- 分析变量数：168。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 73 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetSTR | hitrate_top33_m1_n1_pairwise1 | 0.771 | 0.771 | *** | 160 | 重点关注相关性风险 |
| CtrlRetSTR | hitrate_top33_m1_n2_pairwise1 | 0.548 | 0.548 | *** | 159 | 重点关注相关性风险 |
| CtrlRetSTR | hitrate_top33_m2_n1_pairwise2 | 0.534 | 0.534 | *** | 159 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m2_n4_pairwise2 | 0.578 | 0.578 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m2_n5_pairwise2 | 0.651 | 0.651 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m2_n6_pairwise2 | 0.716 | 0.716 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m3_n3_pairwise3 | 0.620 | 0.620 | *** | 134 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m3_n4_pairwise3 | 0.724 | 0.724 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m3_n5_pairwise3 | 0.661 | 0.661 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m3_n6_pairwise3 | 0.619 | 0.619 | *** | 97 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m4_n2_pairwise4 | 0.582 | 0.582 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m4_n3_pairwise4 | 0.726 | 0.726 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m4_n4_pairwise4 | 0.650 | 0.650 | *** | 106 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m4_n5_pairwise4 | 0.583 | 0.583 | *** | 90 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m4_n6_pairwise4 | 0.523 | 0.523 | *** | 74 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m5_n2_pairwise5 | 0.663 | 0.663 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m5_n3_pairwise5 | 0.671 | 0.671 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m5_n4_pairwise5 | 0.592 | 0.592 | *** | 90 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m5_n5_pairwise5 | 0.518 | 0.518 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.504 | 0.504 | *** | 68 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m6_n2_pairwise6 | 0.737 | 0.737 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m6_n3_pairwise6 | 0.624 | 0.624 | *** | 97 | 重点关注相关性风险 |
| CtrlRetLTM | hitrate_top33_m6_n4_pairwise6 | 0.526 | 0.526 | *** | 74 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.565 | 0.565 | *** | 53 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.600 | 0.600 | *** | 42 | 重点关注相关性风险 |
| CtrlRetSTR | dummy_top33_m1_n1_hit_above0_pairwise1 | 0.771 | 0.771 | *** | 160 | 重点关注相关性风险 |
| CtrlRetSTR | dummy_top33_m2_n1_hit_above0_pairwise2 | 0.534 | 0.534 | *** | 159 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m2_n4_hit_above1_pairwise2 | 0.501 | 0.501 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m2_n5_hit_above1_pairwise2 | 0.538 | 0.538 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m2_n5_hit_above2_pairwise2 | 0.533 | 0.533 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m2_n6_hit_above1_pairwise2 | 0.548 | 0.548 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m2_n6_hit_above2_pairwise2 | 0.606 | 0.606 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m2_n6_hit_above3_pairwise2 | 0.519 | 0.519 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m3_n3_hit_above1_pairwise3 | 0.537 | 0.537 | *** | 134 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m3_n4_hit_above1_pairwise3 | 0.623 | 0.623 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m3_n4_hit_above2_pairwise3 | 0.535 | 0.535 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m3_n5_hit_above1_pairwise3 | 0.545 | 0.545 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m3_n5_hit_above2_pairwise3 | 0.543 | 0.543 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m3_n6_hit_above2_pairwise3 | 0.529 | 0.529 | *** | 97 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m4_n2_hit_above0_pairwise4 | 0.508 | 0.508 | *** | 135 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m4_n3_hit_above0_pairwise4 | 0.545 | 0.545 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m4_n3_hit_above1_pairwise4 | 0.629 | 0.629 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m4_n4_hit_above1_pairwise4 | 0.559 | 0.559 | *** | 106 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m5_n2_hit_above0_pairwise5 | 0.586 | 0.586 | *** | 128 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m5_n3_hit_above0_pairwise5 | 0.504 | 0.504 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m5_n3_hit_above1_pairwise5 | 0.581 | 0.581 | *** | 109 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m5_n4_hit_above1_pairwise5 | 0.507 | 0.507 | *** | 90 | 重点关注相关性风险 |
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
| CtrlRetLTM | dummy_top33_m6_n2_hit_above0_pairwise6 | 0.642 | 0.642 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m6_n2_hit_above1_pairwise6 | 0.563 | 0.563 | *** | 121 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top33_m6_n3_hit_above1_pairwise6 | 0.541 | 0.541 | *** | 97 | 重点关注相关性风险 |
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
