# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:51:34

## 一、审核口径

- 分析变量数：37。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 26 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| rank_mean_large_m3_n6_pairwise1__dmcs | rank_mean_m3_n6_pairwise1__dmcs | 0.646 | 0.646 | *** | 114 | 重点关注相关性风险 |
| FAC_rank_vol_large_m3_n6_pairwise1__dmcs | FAC_rank_vol_m3_n6_pairwise1__dmcs | 0.527 | 0.527 | *** | 114 | 重点关注相关性风险 |
| rank_mean_large_m6_n3_pairwise1__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.804 | 0.804 | *** | 129 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.518 | 0.518 | *** | 129 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_large_m6_n3_pairwise1__dmcs | 0.515 | 0.515 | *** | 129 | 重点关注相关性风险 |
| rank_mean_large_m6_n6_pairwise1__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.745 | 0.745 | *** | 100 | 重点关注相关性风险 |
| rank_mean_large_m6_n12_pairwise1__dmcs | rank_mean_m6_n12_pairwise1__dmcs | 0.769 | 0.769 | *** | 57 | 重点关注相关性风险 |
| FAC_rank_vol_large_m6_n12_pairwise1__dmcs | FAC_rank_vol_m6_n12_pairwise1__dmcs | 0.623 | 0.623 | *** | 57 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.558 | 0.558 | *** | 57 | 重点关注相关性风险 |
| rank_mean_large_m12_n6_pairwise1__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.898 | 0.898 | *** | 63 | 重点关注相关性风险 |
| FAC_rank_vol_large_m12_n6_pairwise1__dmcs | FAC_rank_vol_m12_n6_pairwise1__dmcs | 0.572 | 0.572 | *** | 63 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.571 | 0.571 | *** | 63 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.545 | 0.545 | *** | 63 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.539 | 0.539 | *** | 63 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_large_m12_n6_pairwise1__dmcs | 0.521 | 0.521 | *** | 63 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_large_m12_n6_pairwise1__dmcs | 0.514 | 0.514 | *** | 63 | 重点关注相关性风险 |
| rank_mean_m3_n6_pairwise1__dmcs | rank_mean_small_m3_n6_pairwise1__dmcs | 0.624 | 0.624 | *** | 115 | 重点关注相关性风险 |
| FAC_rank_vol_m3_n6_pairwise1__dmcs | FAC_rank_vol_small_m3_n6_pairwise1__dmcs | 0.507 | 0.507 | *** | 115 | 重点关注相关性风险 |
| rank_mean_m6_n3_pairwise1__dmcs | rank_mean_small_m6_n3_pairwise1__dmcs | 0.793 | 0.793 | *** | 126 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.525 | 0.525 | *** | 126 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_small_m6_n3_pairwise1__dmcs | 0.508 | 0.508 | *** | 126 | 重点关注相关性风险 |
| rank_mean_m6_n6_pairwise1__dmcs | rank_mean_small_m6_n6_pairwise1__dmcs | 0.736 | 0.736 | *** | 104 | 重点关注相关性风险 |
| rank_mean_m6_n12_pairwise1__dmcs | rank_mean_small_m6_n12_pairwise1__dmcs | 0.704 | 0.704 | *** | 56 | 重点关注相关性风险 |
| FAC_rank_vol_m6_n12_pairwise1__dmcs | FAC_rank_vol_small_m6_n12_pairwise1__dmcs | 0.571 | 0.571 | *** | 56 | 重点关注相关性风险 |
| rank_mean_m12_n6_pairwise1__dmcs | rank_mean_small_m12_n6_pairwise1__dmcs | 0.831 | 0.831 | *** | 87 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.533 | 0.533 | *** | 87 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次发现 33 个 VIF 风险变量：

| variable | mean_vif | median_vif | p90_vif | max_vif | ok_months | failed_or_skipped_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rank_mean_m3_n6_pairwise1__dmcs | 216.503 | 3.412 | 10.114 | 14669.112 | 108 | 107 | VIF 风险 |
| rank_mean_large_m3_n6_pairwise1__dmcs | 216.316 | 3.080 | 9.769 | 14670.131 | 108 | 107 | VIF 风险 |
| rank_mean_large_m6_n3_pairwise1__dmcs | 2505.244 | 6.847 | 13985.928 | 34811.988 | 123 | 92 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 2502.530 | 6.660 | 13943.919 | 34794.937 | 123 | 92 | VIF 风险 |
| FAC_rank_vol_large_m6_n3_pairwise1__dmcs | 116.009 | 1.596 | 354.356 | 2094.018 | 123 | 92 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 115.740 | 1.532 | 342.134 | 2083.777 | 123 | 92 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 108.422 | 1.895 | 327.374 | 2302.828 | 123 | 92 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 108.524 | 1.908 | 324.390 | 2308.619 | 123 | 92 | VIF 风险 |
| rank_mean_large_m6_n6_pairwise1__dmcs | 382.470 | 3.875 | 31.161 | 12321.580 | 92 | 123 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 382.851 | 4.037 | 30.870 | 12354.044 | 92 | 123 | VIF 风险 |
| rank_mean_large_m6_n12_pairwise1__dmcs | 5.750 | 3.149 | 12.998 | 24.246 | 57 | 158 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 5.847 | 3.596 | 12.726 | 23.513 | 57 | 158 | VIF 风险 |
| rank_mean_large_m12_n6_pairwise1__dmcs | 391.470 | 11.446 | 85.158 | 9871.370 | 63 | 152 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 390.242 | 10.584 | 80.956 | 9878.338 | 63 | 152 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 15.142 | 2.134 | 8.096 | 319.017 | 63 | 152 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 15.089 | 2.003 | 7.371 | 319.574 | 63 | 152 | VIF 风险 |
| FAC_rank_vol_m12_n6_pairwise1__dmcs | 12.163 | 1.988 | 6.181 | 298.622 | 63 | 152 | VIF 风险 |
| FAC_rank_vol_large_m12_n6_pairwise1__dmcs | 12.061 | 1.869 | 6.047 | 295.611 | 63 | 152 | VIF 风险 |
| rank_mean_small_m3_n6_pairwise1__dmcs | 6.171 | 3.777 | 9.642 | 104.003 | 107 | 108 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 5.670 | 3.294 | 8.841 | 100.676 | 107 | 108 | VIF 风险 |
| rank_mean_small_m6_n3_pairwise1__dmcs | 2299.709 | 9.321 | 5327.038 | 67216.146 | 120 | 95 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 2298.339 | 8.955 | 5312.538 | 67126.963 | 120 | 95 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 131.739 | 1.838 | 144.845 | 6056.470 | 120 | 95 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 131.568 | 1.964 | 144.754 | 6073.134 | 120 | 95 | VIF 风险 |
| FAC_rank_vol_small_m6_n3_pairwise1__dmcs | 140.678 | 1.390 | 137.670 | 6301.646 | 120 | 95 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 140.641 | 1.426 | 136.324 | 6299.283 | 120 | 95 | VIF 风险 |
| rank_mean_small_m6_n6_pairwise1__dmcs | 12.730 | 4.886 | 22.973 | 304.103 | 101 | 114 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 12.199 | 5.070 | 18.470 | 298.850 | 101 | 114 | VIF 风险 |
| rank_mean_small_m6_n12_pairwise1__dmcs | 5.209 | 3.102 | 8.466 | 41.504 | 56 | 159 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 5.193 | 3.349 | 8.253 | 41.852 | 56 | 159 | VIF 风险 |
| rank_mean_small_m12_n6_pairwise1__dmcs | 22.226 | 5.856 | 45.901 | 434.785 | 86 | 129 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 21.632 | 5.689 | 41.544 | 412.435 | 86 | 129 | VIF 风险 |
| FAC_rank_vol_small_m12_n6_pairwise1__dmcs | 2.475 | 1.387 | 5.457 | 13.765 | 86 | 129 | VIF 风险 |

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
