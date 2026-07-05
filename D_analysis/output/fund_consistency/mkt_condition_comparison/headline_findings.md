# 市态一致性模型重点结果（自动生成）

显著性阈值：|t| >= 1.96（Newey-West）。
有效月份 < 60 的结果需谨慎解读（growth/large 的 m6_n12 规格）。

## 一、市态 FAC 主效应显著的规格（M1 对照）

```
   dim  regime window  state_coef  state_t  state_n_months  state_adj_r2  plain_coef  plain_t  plain_n_months  plain_adj_r2
 hs300 hs300up m12_n6       0.039    2.093              95         0.183      -0.021   -0.707             108         0.199
indvol  lowvol m6_n12       0.077    3.916              61         0.202       0.016    0.680             108         0.193
  size   large m12_n6       0.065    2.517              80         0.189      -0.021   -0.707             108         0.199
  size   small  m3_n6      -0.030   -2.161             137         0.174      -0.034   -2.429             153         0.176
```

## 二、市态交互项显著的规格（M3' 对照）

```
source    dim  regime window  interaction_coef  interaction_t  n_months  avg_adj_r2
 state indvol highvol m12_n6             0.395          2.298        77       0.191
 state   size   small m6_n12             0.547          2.040        85       0.180
```

## 三、marginal 模型中市态项在普通项同场时仍显著的规格

```
                                   model    dim    regime window  state_fac_coef  state_fac_t  state_rank_mean_coef  state_rank_mean_t  plain_fac_coef  plain_fac_t  plain_rank_mean_coef  plain_rank_mean_t  state_interaction_coef  state_interaction_t  plain_interaction_coef  plain_interaction_t  n_months  avg_adj_r2  max_vif  vif_all_ok
 fm_marginal_interaction_noctrlLTM_hs300  hs300 hs300down m12_n6           0.056        2.362                -0.032             -0.817          -0.057       -1.329                 0.019              0.560                   0.232                1.859                   0.083                0.638        85       0.222    3.505        True
fm_marginal_interaction_noctrlLTM_indvol indvol    lowvol m6_n12           0.154        2.136                 0.072              0.750          -0.081       -0.960                -0.077             -0.843                   0.263                1.069                  -0.074               -0.316        61       0.244    2.239        True
 fm_marginal_interaction_noctrlLTM_style  style     value  m6_n6          -0.098       -2.144                 0.017              0.255           0.087        1.766                 0.003              0.043                   0.088                0.865                   0.024                0.206       113       0.212    2.323        True
```

## 四、状态匹配 vs 错配反证

匹配项显著规格数：3 / 40；其中匹配 |t| 大于错配 |t| 的规格数：23 / 40。

```
   dim regime window  matched_coef  matched_t  matched_n_months  cross_coef  cross_t  cross_n_months  matched_stronger
indvol lowvol m6_n12         0.082      5.285                57       0.085    4.035              58              True
  size  small m6_n12         0.122      1.986                34      -0.102   -1.693              40              True
 style growth m12_n6        -0.125     -2.969                44       0.025    0.697              60              True
```
