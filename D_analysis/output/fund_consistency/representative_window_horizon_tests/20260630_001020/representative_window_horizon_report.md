# 代表参数窗口 × 未来收益期限检验报告

## 口径说明

- 回归方法：逐月横截面 OLS + Fama-MacBeth 时间序列均值。
- 控制变量、最小横截面样本数和 Newey-West 滞后阶数默认沿用 `fm_baseline`。
- 样本分组：Top33 / Mid33 / Bottom33 使用每个窗口自己的 `is_tercile_rank_mean_*`。
- Full sample 不使用 rank_mean 分组筛选。
- rank_mean 是否入模：False。

## 自动回答

### 1. m3 类窗口是否在短期限 Y 下更负？

- m3 类 FAC 平均系数按期限：future_return_12m: -0.0678；future_return_1m: -0.0075；future_return_3m: -0.0273；future_return_6m: -0.0530。
- 初步判断：当前结果不支持短期限更负。

### 2. m3 类窗口是否支持短期均值回归解释？

- 若 m3 类窗口在 1m/3m 下为负且显著，而 6m/12m 弱化，则支持短期均值回归解释。
- 当前 m3 显著记录数：7。

### 3. m6 类窗口是否在 Top33 中保持正向？

- m6 Top33 FAC 平均系数按期限：future_return_12m: 0.1501；future_return_1m: 0.0162；future_return_3m: 0.0350；future_return_6m: 0.0768。
- 初步判断：存在正向证据。

### 4. m6 类窗口适合预测未来几个月收益？

- 建议优先查看 m6_n11 / m6_n12 在 Top33 中 t 值最高的 Y 期限。

### 5. 哪些窗口适合进入下一步组合回测？

- m2_n6 / Top33 / future_return_12m: coef=-0.1481, t=-3.70
- m6_n12 / Top33 / future_return_12m: coef=0.1463, t=3.48
- m2_n7 / Top33 / future_return_12m: coef=-0.1284, t=-3.42
- m2_n6 / Full sample / future_return_12m: coef=-0.0645, t=-3.24
- m5_n12 / Top33 / future_return_12m: coef=0.2159, t=3.25
- m1_n9 / Top33 / future_return_6m: coef=-0.0956, t=-3.19
- m2_n7 / Full sample / future_return_12m: coef=-0.0669, t=-3.01
- m2_n7 / Top33 / future_return_6m: coef=-0.0836, t=-3.00
- m2_n7 / Top33 / future_return_3m: coef=-0.0625, t=-2.95
- m6_n11 / Top33 / future_return_12m: coef=0.1539, t=2.90
- m1_n9 / Top33 / future_return_3m: coef=-0.0552, t=-2.85
- m2_n6 / Top33 / future_return_6m: coef=-0.0801, t=-2.84
- m6_n11 / Top33 / future_return_6m: coef=0.0748, t=2.81
- m3_n6 / Top33 / future_return_3m: coef=-0.0550, t=-2.76
- m3_n6 / Full sample / future_return_12m: coef=-0.0575, t=-2.70
- m6_n12 / Top33 / future_return_6m: coef=0.0787, t=2.66
- m5_n12 / Top33 / future_return_6m: coef=0.1002, t=2.61
- m2_n6 / Top33 / future_return_3m: coef=-0.0489, t=-2.56
- m2_n6 / Full sample / future_return_6m: coef=-0.0402, t=-2.47
- m3_n6 / Full sample / future_return_6m: coef=-0.0344, t=-2.43

## 期限结构表预览

| param_category | param_name | sample_group | future_return_12m | future_return_1m | future_return_3m | future_return_6m |
| --- | --- | --- | --- | --- | --- | --- |
| medium_continuation_candidates | m1_n9 | Bottom33 | -0.0902 (-1.41) | -0.0188 (-1.73) | -0.0306 (-1.26) | -0.0497 (-1.37) |
| medium_continuation_candidates | m1_n9 | Full sample | -0.0503 (-1.77) | -0.0003 (-0.05) | -0.0124 (-0.83) | -0.0308 (-1.58) |
| medium_continuation_candidates | m1_n9 | Mid33 | -0.1288 (-2.21) | -0.0152 (-1.56) | -0.0440 (-1.86) | -0.0569 (-1.36) |
| medium_continuation_candidates | m1_n9 | Top33 | -0.1192 (-2.04) | -0.0100 (-1.20) | -0.0552 (-2.85) | -0.0956 (-3.19) |
| medium_continuation_candidates | m5_n12 | Bottom33 | -0.0699 (-1.20) | -0.0087 (-0.78) | -0.0251 (-0.85) | -0.0685 (-1.60) |
| medium_continuation_candidates | m5_n12 | Full sample | 0.0379 (1.07) | 0.0029 (0.60) | 0.0025 (0.21) | 0.0048 (0.25) |
| medium_continuation_candidates | m5_n12 | Mid33 | -0.0238 (-0.38) | -0.0051 (-0.50) | -0.0006 (-0.03) | 0.0016 (0.05) |
| medium_continuation_candidates | m5_n12 | Top33 | 0.2159 (3.25) | 0.0116 (0.92) | 0.0324 (1.08) | 0.1002 (2.61) |
| medium_continuation_candidates | m6_n11 | Bottom33 | -0.0836 (-1.23) | -0.0074 (-0.54) | -0.0094 (-0.27) | -0.0523 (-1.09) |
| medium_continuation_candidates | m6_n11 | Full sample | 0.0243 (0.67) | 0.0021 (0.41) | 0.0038 (0.29) | 0.0046 (0.21) |
| medium_continuation_candidates | m6_n11 | Mid33 | -0.0481 (-0.92) | -0.0090 (-0.98) | -0.0088 (-0.43) | -0.0091 (-0.31) |
| medium_continuation_candidates | m6_n11 | Top33 | 0.1539 (2.90) | 0.0160 (1.51) | 0.0347 (1.42) | 0.0748 (2.81) |
| medium_continuation_candidates | m6_n12 | Bottom33 | -0.0302 (-0.53) | -0.0049 (-0.40) | -0.0125 (-0.41) | -0.0545 (-1.38) |
| medium_continuation_candidates | m6_n12 | Full sample | 0.0356 (0.97) | 0.0038 (0.69) | 0.0079 (0.58) | 0.0157 (0.68) |
| medium_continuation_candidates | m6_n12 | Mid33 | -0.0442 (-0.94) | -0.0036 (-0.42) | 0.0002 (0.01) | 0.0076 (0.24) |
| medium_continuation_candidates | m6_n12 | Top33 | 0.1463 (3.48) | 0.0164 (1.51) | 0.0353 (1.46) | 0.0787 (2.66) |
| neutral_controls | m12_n6 | Bottom33 | -0.1700 (-1.93) | -0.0013 (-0.09) | -0.0340 (-1.02) | -0.1056 (-1.78) |
| neutral_controls | m12_n6 | Full sample | -0.0305 (-0.65) | -0.0014 (-0.21) | -0.0081 (-0.48) | -0.0210 (-0.71) |
| neutral_controls | m12_n6 | Mid33 | -0.0084 (-0.22) | -0.0077 (-0.78) | 0.0025 (0.14) | 0.0118 (0.53) |
| neutral_controls | m12_n6 | Top33 | 0.0469 (0.72) | -0.0025 (-0.18) | -0.0022 (-0.08) | 0.0135 (0.37) |
| neutral_controls | m9_n6 | Bottom33 | -0.0995 (-1.48) | 0.0053 (0.50) | 0.0142 (0.44) | 0.0070 (0.15) |
| neutral_controls | m9_n6 | Full sample | -0.0582 (-1.54) | -0.0027 (-0.47) | -0.0150 (-0.98) | -0.0317 (-1.48) |
| neutral_controls | m9_n6 | Mid33 | -0.0946 (-1.49) | -0.0171 (-1.37) | -0.0276 (-0.89) | -0.0244 (-0.64) |
| neutral_controls | m9_n6 | Top33 | 0.0429 (0.68) | -0.0109 (-0.76) | -0.0134 (-0.41) | 0.0365 (0.96) |
| short_reversal_candidates | m2_n6 | Bottom33 | -0.0393 (-0.91) | -0.0016 (-0.18) | -0.0093 (-0.57) | -0.0438 (-1.41) |
| short_reversal_candidates | m2_n6 | Full sample | -0.0645 (-3.24) | -0.0044 (-0.83) | -0.0183 (-1.76) | -0.0402 (-2.47) |
| short_reversal_candidates | m2_n6 | Mid33 | -0.1009 (-2.74) | -0.0132 (-1.79) | -0.0475 (-2.44) | -0.0748 (-2.81) |
| short_reversal_candidates | m2_n6 | Top33 | -0.1481 (-3.70) | -0.0130 (-1.69) | -0.0489 (-2.56) | -0.0801 (-2.84) |
| short_reversal_candidates | m2_n7 | Bottom33 | -0.0593 (-1.35) | -0.0105 (-1.39) | -0.0188 (-1.20) | -0.0466 (-1.54) |
| short_reversal_candidates | m2_n7 | Full sample | -0.0669 (-3.01) | -0.0050 (-0.81) | -0.0200 (-1.82) | -0.0388 (-2.16) |
