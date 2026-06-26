"""
散点图：收益水平 (Level) vs 排名波动率 (Rank Volatility)

目的：
    将每个基金-月份观测点画在二维空间中，观察基金业绩"水平"与"一致性"的联合分布。
    这张图可以帮助我们判断"一致地差"的基金到底集中在哪个区域、占多大比例，
    从而决定剔除阈值应该设在后 10%、后 20% 还是其他位置。

坐标轴定义：
    横轴 (X)：CtrlRetLTM 在每个截面（month_date + investment_type）内的排名分位数
              —— 代表该基金当月的长期收益水平，数值越高表现越好
    纵轴 (Y)：rank_vol_* 变量（共 5 个，对应不同 m/n 窗口组合）
              —— 过去多个子期间排名的标准差，数值越小表示排名越稳定（越一致）

四象限解读（横轴越高 = 表现越好，纵轴越低 = 越一致）：
    右下角：稳定且好   —— 收益好且排名一致，理想标的
    左下角：稳定但差   —— 收益差且排名一致，"一致地差" ← 重点识别区域
    右上角：好但不稳定 —— 收益好但排名波动大，时好时坏
    左上角：差且不稳定 —— 收益差且排名波动大

输出：
    一张包含 5 个子图的画布（2 行 3 列），分别对应 5 个 rank_vol 变量。
    保存到 A_data/output/descriptive_analysis/scatter_level_vs_rank_vol.png
"""

# ============================================================
# 导入所需的库
# ============================================================
import pandas as pd       # 用于读取 parquet 数据和数据处理
import numpy as np        # 用于数值计算（中位数等）
import matplotlib.pyplot as plt  # 用于绑制散点图
from pathlib import Path  # 用于跨平台路径处理

# ============================================================
# 定义输入数据路径和输出目录
# ============================================================
# 源数据：panel_base.parquet，包含所有基金-月份的面板数据
DATA_PATH = Path(__file__).resolve().parents[1] / "output" / "panel_base.parquet"

# 输出目录：散点图保存到 descriptive_analysis 文件夹下
OUT_DIR = Path(__file__).resolve().parents[1] / "output" / "descriptive_analysis"
# 如果输出目录不存在，自动创建（包括中间目录）
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 配置 5 个 rank_vol 变量（纵轴）
# ============================================================
# 每个 rank_vol 变量是过去多个子期间排名分位数的标准差：
#   rank_vol_m{m}_n{n}_pairwise1
#   m = 回看的子期间个数
#   n = 每个子期间的收益计算月数
# 数值越小 = 排名越稳定 = 一致性越好
RANK_VOL_COLS = [
    "rank_vol_m3_n6_pairwise1",   # 回看3期，每期6个月收益
    "rank_vol_m6_n3_pairwise1",   # 回看6期，每期3个月收益
    "rank_vol_m6_n6_pairwise1",   # 回看6期，每期6个月收益
    "rank_vol_m6_n12_pairwise1",  # 回看6期，每期12个月收益
    "rank_vol_m12_n6_pairwise1",  # 回看12期，每期6个月收益
]

# 每个 rank_vol 变量对应的简短标签，用于子图标题
RANK_VOL_LABELS = [
    "m3_n6",
    "m6_n3",
    "m6_n6",
    "m6_n12",
    "m12_n6",
]

# ============================================================
# 读取源数据
# ============================================================
# 读取 parquet 格式的面板数据
df = pd.read_parquet(DATA_PATH)

# ============================================================
# 计算横轴变量：CtrlRetLTM 在每个截面内的排名分位数
# ============================================================
# 与 3_generate_panel_base.py 中 add_pairwise_past_rank_columns 保持一致：
#   1. 按 month_date + investment_type 分组（同月同类基金内排名）
#   2. 只对 is_sample=True 且 CtrlRetLTM 非空的行计算排名，其余行为 NaN
# pct=True 返回 [0, 1] 的百分位排名；数值越高代表当月表现越好
rank_sample = df["is_sample"] & df["CtrlRetLTM"].notna()
df["CtrlRetLTM_rank"] = np.nan
df.loc[rank_sample, "CtrlRetLTM_rank"] = (
    df.loc[rank_sample]
    .groupby(["month_date", "investment_type"], sort=False)["CtrlRetLTM"]
    .rank(pct=True)
)

# ============================================================
# 创建画布：2 行 3 列，共 6 格，实际使用 5 格（第 6 格留空）
# ============================================================
fig, axes = plt.subplots(
    nrows=2, ncols=3,
    figsize=(18, 10),   # 整张画布 18x10 英寸
    constrained_layout=True,  # 自动调整子图间距，避免标签重叠
)
# 将 2x3 的 axes 数组展平为一维列表，方便按索引访问
axes_flat = axes.flatten()

# ============================================================
# 逐个 rank_vol 变量绘制子图
# ============================================================
for i, (rv_col, rv_label) in enumerate(zip(RANK_VOL_COLS, RANK_VOL_LABELS)):
    ax = axes_flat[i]

    # ----------------------------------------------------------
    # 筛选数据：同时需要横轴（CtrlRetLTM_rank）和纵轴（当前 rank_vol 列）都非空
    # ----------------------------------------------------------
    mask = df["CtrlRetLTM_rank"].notna() & df[rv_col].notna()
    x = df.loc[mask, "CtrlRetLTM_rank"].values   # 横轴：收益水平分位数
    y = df.loc[mask, rv_col].values               # 纵轴：排名波动率（越小越一致）
    n_obs = mask.sum()                             # 有效观测数量

    # ----------------------------------------------------------
    # 绘制散点图
    # ----------------------------------------------------------
    # s=1: 点很小（样本量大，避免重叠）
    # alpha=0.15: 半透明（密集区域通过叠加颜色深浅体现密度）
    # rasterized=True: 光栅化散点，减小文件体积
    ax.scatter(x, y, s=1, alpha=0.15, color="steelblue", rasterized=True)

    # ----------------------------------------------------------
    # 添加参考线，用于划分四象限
    # ----------------------------------------------------------
    # 垂直参考线：横轴 = 0.5，分隔"差"（左）和"好"（右）
    ax.axvline(0.5, ls="--", lw=0.6, color="grey")

    # 水平参考线：纵轴 = rank_vol 的中位数，分隔"一致"（下）和"不一致"（上）
    median_y = np.nanmedian(y)
    ax.axhline(median_y, ls="--", lw=0.6, color="grey")

    # ----------------------------------------------------------
    # 计算四个象限的样本占比
    # ----------------------------------------------------------
    # 用横轴 0.5 和纵轴中位数划分四象限
    pct_bl = ((x < 0.5) & (y <= median_y)).sum() / n_obs * 100  # 左下：一致地差
    pct_br = ((x >= 0.5) & (y <= median_y)).sum() / n_obs * 100  # 右下：一致地好
    pct_tl = ((x < 0.5) & (y > median_y)).sum() / n_obs * 100   # 左上：差且不稳定
    pct_tr = ((x >= 0.5) & (y > median_y)).sum() / n_obs * 100   # 右上：好但不稳定

    # ----------------------------------------------------------
    # 在四个角落添加象限标注文字和占比
    # ----------------------------------------------------------
    # 左下角：差但一致 —— "一致地差"，红色标注，重点关注区域
    ax.text(0.02, 0.02, f"Consistently Bad\n{pct_bl:.1f}%", transform=ax.transAxes,
            fontsize=8, color="red", fontstyle="italic")
    # 右下角：好且一致 —— "一致地好"，绿色标注
    ax.text(0.72, 0.02, f"Consistently Good\n{pct_br:.1f}%", transform=ax.transAxes,
            fontsize=8, color="green", fontstyle="italic")
    # 左上角：差且不一致，灰色标注
    ax.text(0.02, 0.93, f"Bad & Unstable\n{pct_tl:.1f}%", transform=ax.transAxes,
            fontsize=8, color="grey", fontstyle="italic")
    # 右上角：好但不一致，灰色标注
    ax.text(0.72, 0.93, f"Good but Unstable\n{pct_tr:.1f}%", transform=ax.transAxes,
            fontsize=8, color="grey", fontstyle="italic")

    # ----------------------------------------------------------
    # 设置坐标轴标签和标题
    # ----------------------------------------------------------
    ax.set_xlabel("CtrlRetLTM Rank Percentile (Level)")
    ax.set_ylabel(f"Rank Vol ({rv_label})")
    ax.set_title(f"{rv_label}  (N={n_obs:,})")
    # 横轴范围固定为 [0, 1]
    ax.set_xlim(0, 1)

# ============================================================
# 隐藏第 6 格（2行3列 = 6格，只用了5格，最后一格留空）
# ============================================================
axes_flat[5].set_visible(False)

# ============================================================
# 添加整张画布的总标题
# ============================================================
fig.suptitle(
    "Return Level (CtrlRetLTM Rank)  vs  Rank Volatility (rank_vol)",
    fontsize=14, fontweight="bold",
)

# ============================================================
# 保存图像
# ============================================================
out_path = OUT_DIR / "scatter_level_vs_rank_vol.png"
# 保存为 PNG 格式，分辨率 200 DPI
fig.savefig(out_path, dpi=200)
# 关闭画布，释放内存
plt.close(fig)

print(f"Saved -> {out_path}")
print("Done.")
