# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:56:51

## 一、审核口径

- 分析变量数：72。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 45 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| CtrlRetLTM | dummy_top50_highvol_m3_n6_hit_above3_pairwise1 | 0.524 | 0.524 | *** | 99 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n3_hit_above0_pairwise1 | 0.523 | 0.523 | *** | 111 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n3_hit_above1_pairwise1 | 0.592 | 0.592 | *** | 111 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n3_hit_above2_pairwise1 | 0.551 | 0.551 | *** | 111 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n6_hit_above1_pairwise1 | 0.573 | 0.573 | *** | 84 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n6_hit_above2_pairwise1 | 0.615 | 0.615 | *** | 84 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n6_hit_above3_pairwise1 | 0.636 | 0.636 | *** | 84 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n6_hit_above4_pairwise1 | 0.636 | 0.636 | *** | 84 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n6_hit_above5_pairwise1 | 0.556 | 0.556 | *** | 84 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n12_hit_above4_pairwise1 | 0.525 | 0.525 | *** | 57 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n12_hit_above5_pairwise1 | 0.548 | 0.548 | *** | 57 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n12_hit_above6_pairwise1 | 0.564 | 0.564 | *** | 57 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n12_hit_above7_pairwise1 | 0.549 | 0.549 | *** | 57 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m6_n12_hit_above8_pairwise1 | 0.527 | 0.527 | *** | 57 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m12_n6_hit_above0_pairwise1 | 0.544 | 0.544 | *** | 69 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m12_n6_hit_above1_pairwise1 | 0.586 | 0.586 | *** | 69 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m12_n6_hit_above2_pairwise1 | 0.606 | 0.606 | *** | 69 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m12_n6_hit_above3_pairwise1 | 0.619 | 0.619 | *** | 69 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m12_n6_hit_above4_pairwise1 | 0.629 | 0.629 | *** | 69 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_highvol_m12_n6_hit_above5_pairwise1 | 0.611 | 0.611 | *** | 69 | 重点关注相关性风险 |
| CtrlRetLTM | dummy_top50_lowvol_m6_n3_hit_above1_pairwise1 | 0.503 | 0.503 | *** | 128 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次未发现稳定偏高的 VIF 风险变量。

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
