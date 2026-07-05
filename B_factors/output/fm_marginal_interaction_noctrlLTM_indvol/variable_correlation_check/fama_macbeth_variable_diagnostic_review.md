# Fama-MacBeth 变量相关性与 VIF 审核报告

生成时间：2026-07-02T20:51:18

## 一、审核口径

- 分析变量数：37。
- 相关性风险：非对角线变量对的 `abs(mean_corr) >= 0.50`。
- 重点关注相关性风险：达到相关性风险阈值，且 `stars` 不为空。
- VIF 风险：`p90_vif > 5.0`。
- 相关系数有效月份数：0。

阈值说明：相关系数使用绝对值，是因为高正相关和高负相关都可能造成共线性风险；`0.50` 用来抓出中高相关变量对。VIF 使用 `p90_vif`，是为了代表较高月份的常态风险，同时避免 `max_vif` 被个别月份异常放大。

## 二、相关性风险变量对

按 `abs(mean_corr) >= 0.50` 口径，本次发现 33 组相关性风险变量对：

| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- |
| rank_mean_highvol_m3_n6_pairwise1__dmcs | rank_mean_m3_n6_pairwise1__dmcs | 0.758 | 0.758 | *** | 99 | 重点关注相关性风险 |
| FAC_rank_vol_highvol_m3_n6_pairwise1__dmcs | FAC_rank_vol_m3_n6_pairwise1__dmcs | 0.654 | 0.654 | *** | 99 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.556 | 0.556 | *** | 99 | 重点关注相关性风险 |
| rank_mean_highvol_m6_n3_pairwise1__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.871 | 0.871 | *** | 111 | 重点关注相关性风险 |
| FAC_rank_vol_highvol_m6_n3_pairwise1__dmcs | FAC_rank_vol_m6_n3_pairwise1__dmcs | 0.611 | 0.611 | *** | 111 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.600 | 0.600 | *** | 111 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.516 | 0.516 | *** | 111 | 重点关注相关性风险 |
| rank_mean_highvol_m6_n6_pairwise1__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.880 | 0.880 | *** | 83 | 重点关注相关性风险 |
| FAC_rank_vol_highvol_m6_n6_pairwise1__dmcs | FAC_rank_vol_m6_n6_pairwise1__dmcs | 0.749 | 0.749 | *** | 83 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.668 | 0.668 | *** | 83 | 重点关注相关性风险 |
| rank_mean_highvol_m6_n12_pairwise1__dmcs | rank_mean_m6_n12_pairwise1__dmcs | 0.917 | 0.917 | *** | 57 | 重点关注相关性风险 |
| FAC_rank_vol_highvol_m6_n12_pairwise1__dmcs | FAC_rank_vol_m6_n12_pairwise1__dmcs | 0.824 | 0.824 | *** | 57 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.722 | 0.722 | *** | 57 | 重点关注相关性风险 |
| rank_mean_highvol_m12_n6_pairwise1__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.965 | 0.965 | *** | 69 | 重点关注相关性风险 |
| FAC_rank_vol_highvol_m12_n6_pairwise1__dmcs | FAC_rank_vol_m12_n6_pairwise1__dmcs | 0.821 | 0.821 | *** | 69 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.810 | 0.810 | *** | 69 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.538 | 0.538 | *** | 69 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_highvol_m12_n6_pairwise1__dmcs | 0.536 | 0.536 | *** | 69 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_highvol_m12_n6_pairwise1__dmcs | 0.531 | 0.531 | *** | 69 | 重点关注相关性风险 |
| FAC__x__RANK_MEAN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.517 | 0.517 | *** | 69 | 重点关注相关性风险 |
| rank_mean_lowvol_m3_n6_pairwise1__dmcs | rank_mean_m3_n6_pairwise1__dmcs | 0.573 | 0.573 | *** | 121 | 重点关注相关性风险 |
| FAC_rank_vol_lowvol_m3_n6_pairwise1__dmcs | FAC_rank_vol_m3_n6_pairwise1__dmcs | 0.522 | 0.522 | *** | 121 | 重点关注相关性风险 |
| rank_mean_lowvol_m6_n3_pairwise1__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.685 | 0.685 | *** | 128 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m6_n3_pairwise1__dmcs | 0.521 | 0.521 | *** | 128 | 重点关注相关性风险 |
| rank_mean_lowvol_m6_n6_pairwise1__dmcs | rank_mean_m6_n6_pairwise1__dmcs | 0.611 | 0.611 | *** | 102 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.516 | 0.516 | *** | 87 | 重点关注相关性风险 |
| rank_mean_lowvol_m6_n12_pairwise1__dmcs | rank_mean_m6_n12_pairwise1__dmcs | 0.723 | 0.723 | *** | 46 | 重点关注相关性风险 |
| FAC_rank_vol_lowvol_m6_n12_pairwise1__dmcs | FAC_rank_vol_m6_n12_pairwise1__dmcs | 0.603 | 0.603 | *** | 46 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.531 | 0.531 | *** | 46 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | FAC__x__RANK_MEAN__dmcs | 0.524 | 0.524 | *** | 46 | 重点关注相关性风险 |
| rank_mean_lowvol_m12_n6_pairwise1__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.651 | 0.651 | *** | 77 | 重点关注相关性风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | rank_mean_m12_n6_pairwise1__dmcs | 0.535 | 0.535 | *** | 77 | 重点关注相关性风险 |
| Ctrl_fund_age | as_偏股混合型基金 | 0.526 | 0.526 | *** | 77 | 重点关注相关性风险 |

## 三、VIF 风险变量

按 `p90_vif > 5.0` 口径，本次发现 60 个 VIF 风险变量：

| variable | mean_vif | median_vif | p90_vif | max_vif | ok_months | failed_or_skipped_months | risk_level |
| --- | --- | --- | --- | --- | --- | --- | --- |
| rank_mean_highvol_m3_n6_pairwise1__dmcs | 1107.054 | 9.094 | 68.463 | 18584.562 | 98 | 117 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 1104.199 | 7.213 | 67.373 | 18547.958 | 98 | 117 | VIF 风险 |
| FAC_rank_vol_m3_n6_pairwise1__dmcs | 165.652 | 3.416 | 13.281 | 4345.219 | 98 | 117 | VIF 风险 |
| FAC_rank_vol_highvol_m3_n6_pairwise1__dmcs | 165.746 | 3.305 | 12.273 | 4365.166 | 98 | 117 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 148.245 | 2.330 | 8.338 | 3234.124 | 98 | 117 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 147.928 | 2.475 | 7.806 | 3218.081 | 98 | 117 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 10563.356 | 16.742 | 42485.923 | 120942.685 | 108 | 107 | VIF 风险 |
| rank_mean_highvol_m6_n3_pairwise1__dmcs | 10564.446 | 15.965 | 42474.640 | 120881.396 | 108 | 107 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 426.999 | 2.655 | 1435.999 | 6455.579 | 108 | 107 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 426.969 | 2.432 | 1434.362 | 6451.350 | 108 | 107 | VIF 风险 |
| FAC_rank_vol_highvol_m6_n3_pairwise1__dmcs | 430.579 | 2.253 | 1425.888 | 6962.695 | 108 | 107 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 430.488 | 2.175 | 1424.987 | 6976.823 | 108 | 107 | VIF 风险 |
| rank_mean_highvol_m6_n6_pairwise1__dmcs | 1877.688 | 20.441 | 5085.790 | 45593.285 | 83 | 132 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 1878.222 | 19.398 | 5075.557 | 45573.534 | 83 | 132 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 98.550 | 3.022 | 202.827 | 1756.462 | 83 | 132 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 98.573 | 3.000 | 199.937 | 1759.366 | 83 | 132 | VIF 风险 |
| FAC_rank_vol_m6_n6_pairwise1__dmcs | 86.120 | 3.950 | 134.662 | 1506.708 | 83 | 132 | VIF 风险 |
| FAC_rank_vol_highvol_m6_n6_pairwise1__dmcs | 86.144 | 3.757 | 133.949 | 1506.217 | 83 | 132 | VIF 风险 |
| rank_mean_highvol_m6_n12_pairwise1__dmcs | 20.478 | 13.837 | 43.936 | 71.286 | 57 | 158 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 20.327 | 13.737 | 42.981 | 74.155 | 57 | 158 | VIF 风险 |
| FAC_rank_vol_m6_n12_pairwise1__dmcs | 7.723 | 4.887 | 19.457 | 30.729 | 57 | 158 | VIF 风险 |
| FAC_rank_vol_highvol_m6_n12_pairwise1__dmcs | 7.567 | 4.683 | 18.818 | 30.051 | 57 | 158 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 5.134 | 3.786 | 11.501 | 22.506 | 57 | 158 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 5.073 | 3.663 | 11.038 | 22.318 | 57 | 158 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 1959.791 | 59.219 | 7677.738 | 36714.348 | 69 | 146 | VIF 风险 |
| rank_mean_highvol_m12_n6_pairwise1__dmcs | 1961.330 | 61.271 | 7650.109 | 36685.236 | 69 | 146 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 100.881 | 5.886 | 228.649 | 2362.738 | 69 | 146 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 101.504 | 6.061 | 228.078 | 2367.188 | 69 | 146 | VIF 风险 |
| FAC_rank_vol_m12_n6_pairwise1__dmcs | 83.108 | 4.955 | 162.106 | 1920.920 | 69 | 146 | VIF 风险 |
| FAC_rank_vol_highvol_m12_n6_pairwise1__dmcs | 82.700 | 4.779 | 149.604 | 1925.008 | 69 | 146 | VIF 风险 |
| rank_mean_lowvol_m3_n6_pairwise1__dmcs | 700.383 | 1.926 | 3221.817 | 10021.615 | 115 | 100 | VIF 风险 |
| rank_mean_m3_n6_pairwise1__dmcs | 697.010 | 2.593 | 3195.349 | 9978.047 | 115 | 100 | VIF 风险 |
| FAC_rank_vol_lowvol_m3_n6_pairwise1__dmcs | 76.687 | 1.641 | 281.768 | 1226.930 | 115 | 100 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 78.467 | 1.382 | 279.193 | 1195.053 | 115 | 100 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 78.713 | 1.744 | 278.503 | 1199.083 | 115 | 100 | VIF 风险 |
| FAC_rank_vol_m3_n6_pairwise1__dmcs | 76.236 | 1.583 | 271.080 | 1230.916 | 115 | 100 | VIF 风险 |
| rank_mean_lowvol_m6_n3_pairwise1__dmcs | 2751.829 | 4.737 | 7101.154 | 47096.412 | 122 | 93 | VIF 风险 |
| rank_mean_m6_n3_pairwise1__dmcs | 2754.019 | 4.966 | 7086.809 | 47064.139 | 122 | 93 | VIF 风险 |
| FAC_rank_vol_m6_n3_pairwise1__dmcs | 94.882 | 1.418 | 372.909 | 2260.749 | 122 | 93 | VIF 风险 |
| FAC_rank_vol_lowvol_m6_n3_pairwise1__dmcs | 94.898 | 1.312 | 369.685 | 2259.988 | 122 | 93 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 124.558 | 1.787 | 353.137 | 5528.469 | 122 | 93 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 124.836 | 1.795 | 349.325 | 5563.551 | 122 | 93 | VIF 风险 |
| rank_mean_m6_n6_pairwise1__dmcs | 645.723 | 3.018 | 2842.321 | 12175.890 | 87 | 128 | VIF 风险 |
| rank_mean_lowvol_m6_n6_pairwise1__dmcs | 645.875 | 2.108 | 2833.592 | 12248.663 | 87 | 128 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 38.091 | 1.687 | 151.646 | 536.522 | 87 | 128 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 38.097 | 1.453 | 151.260 | 534.687 | 87 | 128 | VIF 风险 |
| FAC_rank_vol_lowvol_m6_n6_pairwise1__dmcs | 29.536 | 1.362 | 133.447 | 333.117 | 87 | 128 | VIF 风险 |
| FAC_rank_vol_m6_n6_pairwise1__dmcs | 29.567 | 1.505 | 132.312 | 327.546 | 87 | 128 | VIF 风险 |
| rank_mean_lowvol_m6_n12_pairwise1__dmcs | 329.335 | 2.876 | 1167.630 | 3884.073 | 46 | 169 | VIF 风险 |
| rank_mean_m6_n12_pairwise1__dmcs | 328.714 | 3.384 | 1166.915 | 3857.899 | 46 | 169 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 31.532 | 1.749 | 108.195 | 361.240 | 46 | 169 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 31.322 | 1.517 | 106.016 | 362.835 | 46 | 169 | VIF 风险 |
| FAC_rank_vol_m6_n12_pairwise1__dmcs | 27.996 | 1.881 | 95.242 | 270.586 | 46 | 169 | VIF 风险 |
| FAC_rank_vol_lowvol_m6_n12_pairwise1__dmcs | 28.018 | 1.722 | 94.450 | 274.549 | 46 | 169 | VIF 风险 |
| rank_mean_lowvol_m12_n6_pairwise1__dmcs | 713.398 | 2.673 | 3333.205 | 8174.314 | 77 | 138 | VIF 风险 |
| rank_mean_m12_n6_pairwise1__dmcs | 714.036 | 3.143 | 3326.524 | 8183.511 | 77 | 138 | VIF 风险 |
| FAC_rank_vol_lowvol_m12_n6_pairwise1__dmcs | 30.921 | 1.276 | 132.298 | 335.496 | 77 | 138 | VIF 风险 |
| FAC_rank_vol_m12_n6_pairwise1__dmcs | 31.023 | 1.338 | 130.575 | 334.472 | 77 | 138 | VIF 风险 |
| FAC__x__RANK_MEAN__dmcs | 26.161 | 1.612 | 117.701 | 275.737 | 77 | 138 | VIF 风险 |
| FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs | 26.535 | 1.766 | 114.615 | 279.526 | 77 | 138 | VIF 风险 |

## 四、建议解读

- `stars` 只用于提示统计显著性，不代表相关系数大小；真正判断风险时应优先看 `abs_mean_corr`。
- 如果相关性风险变量对同时具有相近经济含义，建议考虑二选一、合成指标或分模型做稳健性检验。
- 如果 VIF 风险为空，说明按当前主口径没有发现稳定偏高的多重共线性；仍可查看 `max_vif` 识别个别月份异常。
- CSV 文件不保存单元格居中等展示样式；如需居中展示，应另行导出 Excel 或 HTML。
