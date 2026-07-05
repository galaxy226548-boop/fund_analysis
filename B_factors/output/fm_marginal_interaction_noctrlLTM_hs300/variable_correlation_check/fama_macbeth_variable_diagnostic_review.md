# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:51:02

## 一、审核口径

- 分析变量数：37。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 27 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| rank_mean_hs300up_m3_n6_pairwise1__dmcs | rank_mean_m3_n6_pairwise1__dmcs | 0.688 | 0.688 | *** | 118 | 重点关注相关性风险 |
| FAC_rank_vol_hs300up_m3_n6_pairwise1__dmcs | FAC_rank_vol_m3_n6_pairwise1__dmcs | 0.560 | 0.560 | *** | 118 | 重点关注相关性风险 |
| rank_mean_hs300up_m6_n3_pairwise1__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.823 | 0.823 | *** | 125 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.517 | 0.517 | *** | 125 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_hs300up_m6_n3_pairwise1__dmcs | 0.516 | 0.516 | *** | 125 | 重点关注相关性风险 |
| rank_mean_hs300up_m6_n6_pairwise1__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.801 | 0.801 | *** | 104 | 重点关注相关性风险 |
| FAC_rank_vol_hs300up_m6_n6_pairwise1__dmcs | FAC_rank_vol_m6_n6_pairwise1__dmcs | 0.546 | 0.546 | *** | 104 | 重点关注相关性风险 |
| rank_mean_hs300up_m6_n12_pairwise1__dmcs | rank_mean_m6_n12_pairwise1__dmcs | 0.789 | 0.789 | *** | 64 | 重点关注相关性风险 |
| FAC_rank_vol_hs300up_m6_n12_pairwise1__dmcs | FAC_rank_vol_m6_n12_pairwise1__dmcs | 0.677 | 0.677 | *** | 64 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.540 | 0.540 | *** | 64 | 重点关注相关性风险 |
| rank_mean_hs300up_m12_n6_pairwise1__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.904 | 0.904 | *** | 77 | 重点关注相关性风险 |
| FAC_rank_vol_hs300up_m12_n6_pairwise1__dmcs | FAC_rank_vol_m12_n6_pairwise1__dmcs | 0.556 | 0.556 | *** | 77 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.535 | 0.535 | *** | 77 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.524 | 0.524 | *** | 77 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_hs300up_m12_n6_pairwise1__dmcs | 0.521 | 0.521 | *** | 77 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_hs300up_m12_n6_pairwise1__dmcs | 0.505 | 0.505 | *** | 77 | 重点关注相关性风险 |
| rank_mean_hs300down_m3_n6_pairwise1__dmcs | rank_mean_m3_n6_pairwise1__dmcs | 0.611 | 0.611 | *** | 115 | 重点关注相关性风险 |
| rank_mean_hs300down_m6_n3_pairwise1__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.786 | 0.786 | *** | 126 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_hs300down_m6_n3_pairwise1__dmcs | 0.527 | 0.527 | *** | 126 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.526 | 0.526 | *** | 126 | 重点关注相关性风险 |
| rank_mean_hs300down_m6_n6_pairwise1__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.701 | 0.701 | *** | 104 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.501 | 0.501 | *** | 104 | 重点关注相关性风险 |
| rank_mean_hs300down_m6_n12_pairwise1__dmcs | rank_mean_m6_n12_pairwise1__dmcs | 0.659 | 0.659 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.524 | 0.524 | *** | 46 | 重点关注相关性风险 |
| FAC_rank_vol_hs300down_m6_n12_pairwise1__dmcs | FAC_rank_vol_m6_n12_pairwise1__dmcs | 0.520 | 0.520 | *** | 46 | 重点关注相关性风险 |
| rank_mean_hs300down_m12_n6_pairwise1__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.856 | 0.856 | *** | 68 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.532 | 0.532 | *** | 68 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次发现 35 个 VIF 风险变量：

| variable | mean_vif | median_vif | p90_vif | max_vif | ok_months | failed_or_skipped_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rank_mean_hs300up_m3_n6_pairwise1__dmcs | 53.301 | 4.434 | 17.857 | 5232.384 | 114 | 101 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 52.617 | 4.348 | 14.802 | 5225.668 | 114 | 101 | VIF 风险 |
| FAC_rank_vol_hs300up_m3_n6_pairwise1__dmcs | 7.061 | 1.850 | 5.761 | 477.619 | 114 | 101 | VIF 风险 |
| FAC_rank_vol_m3_n6_pairwise1__dmcs | 7.172 | 1.811 | 5.641 | 483.392 | 114 | 101 | VIF 风险 |
| rank_mean_hs300up_m6_n3_pairwise1__dmcs | 2003.266 | 10.874 | 4477.193 | 37059.645 | 116 | 99 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 2003.266 | 10.807 | 4453.579 | 37096.253 | 116 | 99 | VIF 风险 |
| FAC_rank_vol_hs300up_m6_n3_pairwise1__dmcs | 97.681 | 1.707 | 171.592 | 2357.119 | 116 | 99 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 97.595 | 1.641 | 170.236 | 2345.677 | 116 | 99 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 96.410 | 2.022 | 144.115 | 2302.828 | 116 | 99 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 96.507 | 2.151 | 140.522 | 2308.619 | 116 | 99 | VIF 风险 |
| rank_mean_hs300up_m6_n6_pairwise1__dmcs | 60.378 | 6.053 | 35.664 | 4674.568 | 100 | 115 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 60.304 | 5.995 | 33.511 | 4686.394 | 100 | 115 | VIF 风险 |
| FAC_rank_vol_m6_n6_pairwise1__dmcs | 4.714 | 1.765 | 5.163 | 207.528 | 100 | 115 | VIF 风险 |
| FAC_rank_vol_hs300up_m6_n6_pairwise1__dmcs | 4.659 | 1.633 | 5.053 | 205.851 | 100 | 115 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 6.820 | 4.162 | 16.045 | 38.156 | 64 | 151 | VIF 风险 |
| rank_mean_hs300up_m6_n12_pairwise1__dmcs | 6.923 | 4.252 | 15.806 | 41.021 | 64 | 151 | VIF 风险 |
| rank_mean_hs300up_m12_n6_pairwise1__dmcs | 101.352 | 9.734 | 71.062 | 5597.166 | 77 | 138 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 100.683 | 10.135 | 67.331 | 5601.182 | 77 | 138 | VIF 风险 |
| FAC_rank_vol_hs300up_m12_n6_pairwise1__dmcs | 7.260 | 1.830 | 8.357 | 315.531 | 77 | 138 | VIF 风险 |
| FAC_rank_vol_m12_n6_pairwise1__dmcs | 7.288 | 1.773 | 8.187 | 315.229 | 77 | 138 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 7.075 | 2.055 | 7.880 | 280.010 | 77 | 138 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 7.156 | 2.069 | 7.791 | 286.635 | 77 | 138 | VIF 风险 |
| rank_mean_hs300down_m3_n6_pairwise1__dmcs | 4.620 | 2.802 | 9.415 | 23.152 | 107 | 108 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 4.349 | 3.027 | 8.650 | 23.552 | 107 | 108 | VIF 风险 |
| rank_mean_hs300down_m6_n3_pairwise1__dmcs | 1772.946 | 7.395 | 55.664 | 50447.112 | 121 | 94 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 1774.891 | 7.265 | 54.416 | 50431.346 | 121 | 94 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 95.627 | 1.426 | 7.775 | 3849.018 | 121 | 94 | VIF 风险 |
| FAC_rank_vol_hs300down_m6_n3_pairwise1__dmcs | 95.703 | 1.473 | 7.773 | 3853.833 | 121 | 94 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 80.087 | 1.949 | 5.669 | 2557.502 | 121 | 94 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 80.228 | 1.869 | 5.132 | 2546.671 | 121 | 94 | VIF 风险 |
| rank_mean_hs300down_m6_n6_pairwise1__dmcs | 5.790 | 3.898 | 10.797 | 67.561 | 98 | 117 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 5.787 | 3.924 | 10.220 | 60.979 | 98 | 117 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 3.543 | 2.867 | 6.120 | 11.048 | 46 | 169 | VIF 风险 |
| rank_mean_hs300down_m12_n6_pairwise1__dmcs | 11.120 | 6.739 | 22.749 | 121.225 | 67 | 148 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 10.917 | 6.097 | 20.967 | 116.056 | 67 | 148 | VIF 风险 |

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
