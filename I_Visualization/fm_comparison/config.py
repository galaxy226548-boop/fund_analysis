"""fm_comparison 页面的集中配置：路径、打分权重、基准与配对规则。

所有可调参数集中在此，页面侧栏基于 DEFAULT_CONFIG 生成副本后覆盖，
打分引擎（scoring.py）只通过 cfg 字典读取，不直接 import 本模块的具体数值。
"""

from pathlib import Path

# ---- 路径 ----
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_XLSX = (
    PROJECT_ROOT
    / "D_analysis" / "output" / "fama_macbeth_results_reading"
    / "回归系数显著性" / "回归系数显著性_总表.xlsx"
)
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# ---- 核心变量前缀：共线性风险对/VIF 变量是否"含核心变量"按此前缀判断 ----
CORE_VARIABLE_PREFIX = "FAC"

# ---- 默认打分配置（spec 第 4 节；侧栏可实时覆盖）----
DEFAULT_CONFIG = {
    # FM 显著性：|t| 分档 (阈值, 满分占比)，从高到低匹配，乘 fm_full
    "fm_full": 40.0,
    "fm_t_bands": [(2.58, 1.0), (1.96, 0.8), (1.65, 0.6)],
    # 邻格稳健性：邻格中"同号且 |t|>=neighbor_t_min"的比例 × neighbor_full
    "neighbor_full": 10.0,
    "neighbor_t_min": 1.645,  # p<0.1 的 |t| 近似阈值（FM 表只有 t 值）
    # 多空显著性：p 分档 (阈值, 满分占比)，乘 ps_full，再乘折扣系数
    "ps_full": 30.0,
    "ps_p_bands": [(0.01, 1.0), (0.05, 0.8), (0.10, 0.6), (0.15, 1 / 3)],
    "ps_direction_conflict_mult": 0.5,  # FM 系数方向与多空收益方向冲突
    "ps_econ_threshold": 0.003,         # 月均多空 |收益| < 0.3%/月 触发经济显著性折扣
    "ps_econ_mult": 0.8,
    # 回归质量：个体 R² 分位数 × 12 + 族平均 R² 分位数 × 8
    "r2_individual_full": 12.0,
    "r2_family_full": 8.0,
    # 样本量扣分：(阈值, 扣分) 升序排列，命中最严档，不叠加
    "months_penalties": [(48, -10.0), (60, -5.0)],
    "obs_penalties": [(3000, -8.0), (6000, -3.0)],
    # 共线性扣分：每组唯一风险对基础扣分 × 持续性系数，族内合计有上限
    "corr_pair_penalty": -2.0,
    "corr_pair_core_penalty": -5.0,  # 风险对含核心 FAC 变量时的加重档
    "corr_cap": -8.0,
    "vif_penalty": -4.0,
    "vif_core_penalty": -8.0,        # 核心 FAC 变量自身 VIF 超标时的加重档
    "vif_cap": -12.0,
    # 擂台判定
    "replace_margin": 10.0,  # 领先基准 >= 此分差 → "优先关注"
    "tie_band": 5.0,         # 与守擂现役格分差绝对值 <= 此值 → 色点标"平"
}

# ---- 基准（守擂者）：按样本层配对；top50 对应模型目录 fm_baseline_up ----
BASELINES = {
    "bottom33": {"model": "fm_baseline_bottom33", "param_key": "m3_n6"},
    "up": {"model": "fm_baseline_up", "param_key": "m6_n12"},
}
