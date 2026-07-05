# 代表参数窗口 × 未来收益期限检验报告

## 口径说明

- 回归方法：逐月横截面 OLS + Fama-MacBeth 时间序列均值。
- 控制变量、最小横截面样本数和 Newey-West 滞后阶数默认沿用 `fm_baseline`。
- 样本分组：Top33 / Mid33 / Bottom33 使用每个窗口自己的 `is_tercile_rank_mean_*`。
- Full sample 不使用 rank_mean 分组筛选。
- rank_mean 是否入模：False。

## 自动回答

### 1. m3 类窗口是否在短期限 Y 下更负？

- m3 类 FAC 平均系数按期限：future_return_12m: -0.0654；future_return_1m: -0.0061；future_return_3m: -0.0246；future_return_6m: -0.0470。
- 初步判断：当前结果不支持短期限更负。

### 2. m3 类窗口是否支持短期均值回归解释？

- 若 m3 类窗口在 1m/3m 下为负且显著，而 6m/12m 弱化，则支持短期均值回归解释。
- 当前 m3 显著记录数：14。

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
- m3_n4 / Full sample / future_return_12m: coef=-0.0508, t=-3.06
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

## 期限结构表预览

| param_category | param_name | sample_group | future_return_12m | future_return_1m | future_return_3m | future_return_6m |
| --- | --- | --- | --- | --- | --- | --- |
| medium_continuation_candidates | m1_n9 | Bottom33 | -0.0902 (-1.41) | -0.0188 (-1.73) | -0.0306 (-1.26) | -0.0497 (-1.37) |
| medium_continuation_candidates | m1_n9 | Bottom50 | -0.0518 (-1.14) | -0.0035 (-0.33) | -0.0189 (-1.01) | -0.0124 (-0.39) |
| medium_continuation_candidates | m1_n9 | Full sample | -0.0503 (-1.77) | -0.0003 (-0.05) | -0.0124 (-0.83) | -0.0308 (-1.58) |
| medium_continuation_candidates | m1_n9 | Mid33 | -0.1288 (-2.21) | -0.0152 (-1.56) | -0.0440 (-1.86) | -0.0569 (-1.36) |
| medium_continuation_candidates | m1_n9 | Top33 | -0.1192 (-2.04) | -0.0100 (-1.20) | -0.0552 (-2.85) | -0.0956 (-3.19) |
| medium_continuation_candidates | m1_n9 | Top50 | -0.0906 (-2.27) | -0.0067 (-0.88) | -0.0276 (-1.27) | -0.0820 (-2.82) |
| medium_continuation_candidates | m5_n12 | Bottom33 | -0.0699 (-1.20) | -0.0087 (-0.78) | -0.0251 (-0.85) | -0.0685 (-1.60) |
| medium_continuation_candidates | m5_n12 | Bottom50 | -0.0988 (-1.53) | -0.0127 (-1.25) | -0.0156 (-0.57) | -0.0521 (-1.23) |
| medium_continuation_candidates | m5_n12 | Full sample | 0.0379 (1.07) | 0.0029 (0.60) | 0.0025 (0.21) | 0.0048 (0.25) |
| medium_continuation_candidates | m5_n12 | Mid33 | -0.0238 (-0.38) | -0.0051 (-0.50) | -0.0006 (-0.03) | 0.0016 (0.05) |
| medium_continuation_candidates | m5_n12 | Top33 | 0.2159 (3.25) | 0.0116 (0.92) | 0.0324 (1.08) | 0.1002 (2.61) |
| medium_continuation_candidates | m5_n12 | Top50 | 0.2003 (3.08) | 0.0062 (0.68) | 0.0209 (0.93) | 0.0657 (2.23) |
| medium_continuation_candidates | m6_n11 | Bottom33 | -0.0836 (-1.23) | -0.0074 (-0.54) | -0.0094 (-0.27) | -0.0523 (-1.09) |
| medium_continuation_candidates | m6_n11 | Bottom50 | -0.0807 (-1.24) | -0.0101 (-0.90) | -0.0068 (-0.23) | -0.0437 (-1.00) |
| medium_continuation_candidates | m6_n11 | Full sample | 0.0243 (0.67) | 0.0021 (0.41) | 0.0038 (0.29) | 0.0046 (0.21) |
| medium_continuation_candidates | m6_n11 | Mid33 | -0.0481 (-0.92) | -0.0090 (-0.98) | -0.0088 (-0.43) | -0.0091 (-0.31) |
| medium_continuation_candidates | m6_n11 | Top33 | 0.1539 (2.90) | 0.0160 (1.51) | 0.0347 (1.42) | 0.0748 (2.81) |
| medium_continuation_candidates | m6_n11 | Top50 | 0.1387 (2.23) | 0.0058 (0.66) | 0.0191 (0.94) | 0.0426 (1.88) |
| medium_continuation_candidates | m6_n12 | Bottom33 | -0.0302 (-0.53) | -0.0049 (-0.40) | -0.0125 (-0.41) | -0.0545 (-1.38) |
| medium_continuation_candidates | m6_n12 | Bottom50 | -0.0823 (-1.41) | -0.0032 (-0.31) | -0.0059 (-0.22) | -0.0392 (-1.04) |
| medium_continuation_candidates | m6_n12 | Full sample | 0.0356 (0.97) | 0.0038 (0.69) | 0.0079 (0.58) | 0.0157 (0.68) |
| medium_continuation_candidates | m6_n12 | Mid33 | -0.0442 (-0.94) | -0.0036 (-0.42) | 0.0002 (0.01) | 0.0076 (0.24) |
| medium_continuation_candidates | m6_n12 | Top33 | 0.1463 (3.48) | 0.0164 (1.51) | 0.0353 (1.46) | 0.0787 (2.66) |
| medium_continuation_candidates | m6_n12 | Top50 | 0.0909 (2.27) | 0.0093 (1.17) | 0.0169 (0.93) | 0.0461 (1.93) |
| neutral_controls | m3_n4 | Bottom33 | -0.0064 (-0.22) | -0.0004 (-0.07) | -0.0086 (-0.90) | -0.0374 (-2.02) |
| neutral_controls | m3_n4 | Bottom50 | -0.0372 (-1.50) | 0.0013 (0.22) | -0.0093 (-1.05) | -0.0248 (-1.62) |
| neutral_controls | m3_n4 | Full sample | -0.0508 (-3.06) | -0.0026 (-0.74) | -0.0120 (-1.54) | -0.0259 (-2.17) |
| neutral_controls | m3_n4 | Mid33 | -0.0704 (-2.65) | -0.0056 (-1.25) | -0.0254 (-1.74) | -0.0530 (-2.77) |
| neutral_controls | m3_n4 | Top33 | -0.0688 (-1.99) | -0.0062 (-1.33) | -0.0196 (-1.48) | -0.0230 (-1.12) |
| neutral_controls | m3_n4 | Top50 | -0.0447 (-1.62) | -0.0056 (-1.67) | -0.0136 (-1.44) | -0.0112 (-0.66) |
