# 代表参数窗口 × 未来收益期限检验报告

## 口径说明

- 回归方法：逐月横截面 OLS + Fama-MacBeth 时间序列均值。
- 控制变量、最小横截面样本数和 Newey-West 滞后阶数默认沿用 `fm_baseline`。
- 样本分组：Top33 / Mid33 / Bottom33 使用每个窗口自己的 `is_tercile_rank_mean_*`。
- Full sample 不使用 rank_mean 分组筛选。
- rank_mean 是否入模：False。

## 自动回答

### 1. m3 类窗口是否在短期限 Y 下更负？

- m3 类 FAC 平均系数按期限：future_return_1m: -0.0133。
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

- m3_n6 / Top33 / future_return_1m: coef=-0.0133, t=-2.40

## 期限结构表预览

| param_category | param_name | sample_group | future_return_1m |
| --- | --- | --- | --- |
| short_reversal_candidates | m3_n6 | Top33 | -0.0133 (-2.40) |
