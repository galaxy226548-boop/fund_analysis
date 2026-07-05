# 代表参数窗口 × 未来收益期限检验报告

## 口径说明

- 回归方法：逐月横截面 OLS + Fama-MacBeth 时间序列均值。
- 控制变量、最小横截面样本数和 Newey-West 滞后阶数默认沿用 `fm_baseline`。
- 样本分组：Top33 / Mid33 / Bottom33 使用每个窗口自己的 `is_tercile_rank_mean_*`。
- Full sample 不使用 rank_mean 分组筛选。
- rank_mean 是否入模：False。

## 自动回答

### 1. m3 类窗口是否在短期限 Y 下更负？

- m3 类 FAC 平均系数按期限：future_return_12m: -0.0605；future_return_1m: -0.0033；future_return_3m: -0.0194；future_return_6m: -0.0350。
- 初步判断：当前结果不支持短期限更负。

### 2. m3 类窗口是否支持短期均值回归解释？

- 若 m3 类窗口在 1m/3m 下为负且显著，而 6m/12m 弱化，则支持短期均值回归解释。
- 当前 m3 显著记录数：1。

### 3. m6 类窗口是否在 Top33 中保持正向？

- m6 Top33 FAC 平均系数按期限：无可用结果。
- 初步判断：当前未看到稳定正向证据。

### 4. m6 类窗口适合预测未来几个月收益？

- 建议优先查看 m6_n11 / m6_n12 在 Top33 中 t 值最高的 Y 期限。

### 5. 哪些窗口适合进入下一步组合回测？

- 当前没有 `|t_FAC| >= 1.96` 且位于 Top33/Full sample 的候选。

## 期限结构表预览

| param_category | param_name | sample_group | future_return_12m | future_return_1m | future_return_3m | future_return_6m |
| --- | --- | --- | --- | --- | --- | --- |
| medium_continuation_candidates | m1_n9 | Bottom50 | -0.0518 (-1.14) | -0.0035 (-0.33) | -0.0189 (-1.01) | -0.0124 (-0.39) |
| medium_continuation_candidates | m1_n9 | Top50 | -0.0906 (-2.27) | -0.0067 (-0.88) | -0.0276 (-1.27) | -0.0820 (-2.82) |
| medium_continuation_candidates | m5_n12 | Bottom50 | -0.0988 (-1.53) | -0.0127 (-1.25) | -0.0156 (-0.57) | -0.0521 (-1.23) |
| medium_continuation_candidates | m5_n12 | Top50 | 0.2003 (3.08) | 0.0062 (0.68) | 0.0209 (0.93) | 0.0657 (2.23) |
| medium_continuation_candidates | m6_n11 | Bottom50 | -0.0807 (-1.24) | -0.0101 (-0.90) | -0.0068 (-0.23) | -0.0437 (-1.00) |
| medium_continuation_candidates | m6_n11 | Top50 | 0.1387 (2.23) | 0.0058 (0.66) | 0.0191 (0.94) | 0.0426 (1.88) |
| medium_continuation_candidates | m6_n12 | Bottom50 | -0.0823 (-1.41) | -0.0032 (-0.31) | -0.0059 (-0.22) | -0.0392 (-1.04) |
| medium_continuation_candidates | m6_n12 | Top50 | 0.0909 (2.27) | 0.0093 (1.17) | 0.0169 (0.93) | 0.0461 (1.93) |
| neutral_controls | m12_n6 | Bottom50 | -0.0601 (-1.26) | 0.0057 (0.52) | 0.0026 (0.11) | -0.0230 (-0.70) |
| neutral_controls | m12_n6 | Top50 | 0.0330 (0.75) | -0.0048 (-0.46) | -0.0006 (-0.03) | 0.0164 (0.62) |
| neutral_controls | m9_n6 | Bottom50 | -0.0862 (-1.54) | -0.0018 (-0.19) | -0.0046 (-0.21) | -0.0092 (-0.28) |
| neutral_controls | m9_n6 | Top50 | 0.0536 (0.73) | -0.0035 (-0.33) | 0.0019 (0.07) | 0.0188 (0.62) |
| short_reversal_candidates | m2_n6 | Bottom50 | -0.0345 (-1.08) | 0.0001 (0.02) | -0.0197 (-1.58) | -0.0298 (-1.08) |
| short_reversal_candidates | m2_n6 | Top50 | -0.1081 (-3.60) | -0.0089 (-1.36) | -0.0238 (-1.54) | -0.0505 (-2.23) |
| short_reversal_candidates | m2_n7 | Bottom50 | -0.0739 (-1.77) | -0.0057 (-0.59) | -0.0166 (-1.25) | -0.0214 (-0.66) |
| short_reversal_candidates | m2_n7 | Top50 | -0.0880 (-2.35) | -0.0064 (-0.76) | -0.0297 (-1.65) | -0.0500 (-1.99) |
| short_reversal_candidates | m3_n6 | Bottom50 | -0.0717 (-2.31) | -0.0041 (-0.66) | -0.0158 (-1.50) | -0.0399 (-1.86) |
| short_reversal_candidates | m3_n6 | Top50 | -0.0492 (-1.54) | -0.0026 (-0.31) | -0.0230 (-1.43) | -0.0301 (-1.25) |
