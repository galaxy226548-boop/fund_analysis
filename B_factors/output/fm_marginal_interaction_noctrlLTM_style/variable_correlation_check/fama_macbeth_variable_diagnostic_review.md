# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:51:50

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
| rank_mean_growth_m3_n6_pairwise1__dmcs | rank_mean_m3_n6_pairwise1__dmcs | 0.591 | 0.591 | *** | 108 | 重点关注相关性风险 |
| FAC_rank_vol_growth_m3_n6_pairwise1__dmcs | FAC_rank_vol_m3_n6_pairwise1__dmcs | 0.501 | 0.501 | *** | 108 | 重点关注相关性风险 |
| rank_mean_growth_m6_n3_pairwise1__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.764 | 0.764 | *** | 123 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.526 | 0.526 | *** | 123 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_growth_m6_n3_pairwise1__dmcs | 0.512 | 0.512 | *** | 123 | 重点关注相关性风险 |
| rank_mean_growth_m6_n6_pairwise1__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.731 | 0.731 | *** | 100 | 重点关注相关性风险 |
| rank_mean_growth_m6_n12_pairwise1__dmcs | rank_mean_m6_n12_pairwise1__dmcs | 0.796 | 0.796 | *** | 36 | 重点关注相关性风险 |
| FAC_rank_vol_growth_m6_n12_pairwise1__dmcs | FAC_rank_vol_m6_n12_pairwise1__dmcs | 0.721 | 0.721 | *** | 36 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.547 | 0.547 | *** | 36 | 重点关注相关性风险 |
| rank_mean_growth_m12_n6_pairwise1__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.863 | 0.863 | *** | 70 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.528 | 0.528 | *** | 70 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_growth_m12_n6_pairwise1__dmcs | 0.518 | 0.518 | *** | 70 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.504 | 0.504 | *** | 70 | 重点关注相关性风险 |
| FAC_rank_vol_growth_m12_n6_pairwise1__dmcs | FAC_rank_vol_m12_n6_pairwise1__dmcs | 0.503 | 0.503 | *** | 70 | 重点关注相关性风险 |
| rank_mean_m3_n6_pairwise1__dmcs | rank_mean_value_m3_n6_pairwise1__dmcs | 0.626 | 0.626 | *** | 114 | 重点关注相关性风险 |
| FAC_rank_vol_m3_n6_pairwise1__dmcs | FAC_rank_vol_value_m3_n6_pairwise1__dmcs | 0.536 | 0.536 | *** | 114 | 重点关注相关性风险 |
| rank_mean_m6_n3_pairwise1__dmcs | rank_mean_value_m6_n3_pairwise1__dmcs | 0.771 | 0.771 | *** | 129 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_value_m6_n3_pairwise1__dmcs | 0.520 | 0.520 | *** | 129 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.519 | 0.519 | *** | 129 | 重点关注相关性风险 |
| rank_mean_m6_n6_pairwise1__dmcs | rank_mean_value_m6_n6_pairwise1__dmcs | 0.707 | 0.707 | *** | 104 | 重点关注相关性风险 |
| FAC_rank_vol_m6_n6_pairwise1__dmcs | FAC_rank_vol_value_m6_n6_pairwise1__dmcs | 0.504 | 0.504 | *** | 104 | 重点关注相关性风险 |
| rank_mean_m6_n12_pairwise1__dmcs | rank_mean_value_m6_n12_pairwise1__dmcs | 0.604 | 0.604 | *** | 58 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.571 | 0.571 | *** | 58 | 重点关注相关性风险 |
| FAC_rank_vol_m6_n12_pairwise1__dmcs | FAC_rank_vol_value_m6_n12_pairwise1__dmcs | 0.531 | 0.531 | *** | 58 | 重点关注相关性风险 |
| rank_mean_m12_n6_pairwise1__dmcs | rank_mean_value_m12_n6_pairwise1__dmcs | 0.791 | 0.791 | *** | 79 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.539 | 0.539 | *** | 79 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次发现 44 个 VIF 风险变量：

| variable | mean_vif | median_vif | p90_vif | max_vif | ok_months | failed_or_skipped_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rank_mean_growth_m3_n6_pairwise1__dmcs | 851.775 | 3.402 | 24.586 | 30741.746 | 102 | 113 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 850.981 | 2.874 | 22.154 | 30709.269 | 102 | 113 | VIF 风险 |
| FAC_rank_vol_growth_m3_n6_pairwise1__dmcs | 75.414 | 1.677 | 5.538 | 3301.281 | 102 | 113 | VIF 风险 |
| FAC_rank_vol_m3_n6_pairwise1__dmcs | 75.466 | 1.757 | 5.455 | 3295.170 | 102 | 113 | VIF 风险 |
| rank_mean_growth_m6_n3_pairwise1__dmcs | 5233.915 | 7.572 | 16118.783 | 100613.150 | 113 | 102 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 5234.596 | 7.270 | 16102.165 | 100837.756 | 113 | 102 | VIF 风险 |
| FAC_rank_vol_growth_m6_n3_pairwise1__dmcs | 211.935 | 1.418 | 564.009 | 6301.646 | 113 | 102 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 212.049 | 1.412 | 563.592 | 6299.283 | 113 | 102 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 213.601 | 1.994 | 550.015 | 6073.134 | 113 | 102 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 213.477 | 1.837 | 548.999 | 6056.470 | 113 | 102 | VIF 风险 |
| rank_mean_growth_m6_n6_pairwise1__dmcs | 450.275 | 4.177 | 34.496 | 15657.988 | 99 | 116 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 450.124 | 3.994 | 32.819 | 15674.782 | 99 | 116 | VIF 风险 |
| rank_mean_growth_m6_n12_pairwise1__dmcs | 11.233 | 4.399 | 26.525 | 64.270 | 36 | 179 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 10.809 | 4.199 | 24.986 | 62.680 | 36 | 179 | VIF 风险 |
| FAC_rank_vol_m6_n12_pairwise1__dmcs | 3.721 | 2.421 | 5.409 | 17.317 | 36 | 179 | VIF 风险 |
| FAC_rank_vol_growth_m6_n12_pairwise1__dmcs | 3.756 | 2.464 | 5.269 | 17.640 | 36 | 179 | VIF 风险 |
| rank_mean_growth_m12_n6_pairwise1__dmcs | 645.946 | 7.462 | 78.525 | 13556.226 | 69 | 146 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 646.942 | 7.617 | 72.655 | 13597.535 | 69 | 146 | VIF 风险 |
| FAC_rank_vol_m12_n6_pairwise1__dmcs | 24.508 | 1.601 | 9.360 | 388.450 | 69 | 146 | VIF 风险 |
| FAC_rank_vol_growth_m12_n6_pairwise1__dmcs | 24.287 | 1.606 | 9.297 | 388.544 | 69 | 146 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 23.408 | 1.914 | 7.293 | 452.005 | 69 | 146 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 23.339 | 1.982 | 7.100 | 454.134 | 69 | 146 | VIF 风险 |
| rank_mean_value_m3_n6_pairwise1__dmcs | 200.135 | 3.564 | 15.053 | 7142.551 | 109 | 106 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 200.045 | 3.874 | 14.287 | 7130.630 | 109 | 106 | VIF 风险 |
| FAC_rank_vol_value_m3_n6_pairwise1__dmcs | 23.852 | 1.726 | 5.285 | 808.699 | 109 | 106 | VIF 风险 |
| rank_mean_value_m6_n3_pairwise1__dmcs | 3896.254 | 8.211 | 16108.327 | 58452.698 | 124 | 91 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 3896.551 | 8.356 | 16081.918 | 58462.461 | 124 | 91 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 135.073 | 1.605 | 514.676 | 2834.847 | 124 | 91 | VIF 风险 |
| FAC_rank_vol_value_m6_n3_pairwise1__dmcs | 135.190 | 1.676 | 511.920 | 2826.677 | 124 | 91 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 137.801 | 1.897 | 459.965 | 3287.665 | 124 | 91 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 137.661 | 1.977 | 459.081 | 3266.408 | 124 | 91 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 316.076 | 5.331 | 40.111 | 11604.989 | 99 | 116 | VIF 风险 |
| rank_mean_value_m6_n6_pairwise1__dmcs | 316.438 | 5.253 | 39.921 | 11603.675 | 99 | 116 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 23.427 | 1.801 | 6.161 | 925.069 | 99 | 116 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 23.353 | 1.791 | 5.535 | 915.422 | 99 | 116 | VIF 风险 |
| FAC_rank_vol_m6_n6_pairwise1__dmcs | 21.221 | 1.614 | 5.322 | 866.085 | 99 | 116 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 5.503 | 3.432 | 13.513 | 24.842 | 58 | 157 | VIF 风险 |
| rank_mean_value_m6_n12_pairwise1__dmcs | 5.313 | 3.099 | 13.214 | 24.246 | 58 | 157 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 375.994 | 10.075 | 83.903 | 9878.338 | 79 | 136 | VIF 风险 |
| rank_mean_value_m12_n6_pairwise1__dmcs | 376.100 | 9.986 | 83.902 | 9871.370 | 79 | 136 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 12.933 | 1.933 | 7.938 | 269.112 | 79 | 136 | VIF 风险 |
| FAC_rank_vol_m12_n6_pairwise1__dmcs | 12.983 | 1.695 | 7.301 | 314.058 | 79 | 136 | VIF 风险 |
| FAC_rank_vol_value_m12_n6_pairwise1__dmcs | 12.992 | 1.670 | 7.271 | 318.090 | 79 | 136 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 12.796 | 1.870 | 6.998 | 269.140 | 79 | 136 | VIF 风险 |

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
