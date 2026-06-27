"""A_data 脚本的共享配置。

这里集中管理文件路径、字段名、收益率设置和周期选择，避免各个流程脚本
重复写死输入项。
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
A_DATA_ROOT = PROJECT_ROOT / "A_data"

# panel_base 的输入和输出。
PANEL_SOURCE_DIR = A_DATA_ROOT / "prepared_data"
PANEL_OUTPUT_PATH = A_DATA_ROOT / "output" / "panel_base.parquet"
PANEL_SOURCE_FILE_PATTERN = "*基金净值筛选长表.parquet"

# 收益率计算设置。
PANEL_RETURN_TYPE = "simple"
VALID_RETURN_TYPES = ("simple", "log")
PANEL_FUTURE_RETURN_HORIZONS = (3, 6, 12)
PANEL_INSAMPLE_END_DATE = "2022-12-31"

# 过去收益率窗口设置。
# 项目统一约定：m（rank_count）表示需要观察多少期排名，n（return_horizon）
# 表示每一期收益率覆盖多少个月。pairwise 表示相邻两个收益窗口的起止点
# 向过去移动多少个月。
#
# 原有模型继续使用 pairwise=1，即每个月滚动一次。该常量继续保留，避免已有
# 外部脚本导入时立即失效；新代码应优先读取下面的 PANEL_PAST_RETURN_SPECS。
PANEL_PAST_RETURN_COMBOS = ((3, 6), (6, 3), (6, 6), (6, 12), (12, 6))
PANEL_PAIRWISE = 1

# 新增的非重叠规格。由于 m 是期数、n 是单期收益期限，所以完全不重叠时
# pairwise 应等于 n。这里把最长历史跨度限制为 36 个月：
# (3,6)=18、(6,3)=18、(6,6)=36、(3,12)=36、(12,3)=36。
PANEL_NONOVERLAP_PAST_RETURN_COMBOS = (
    (3, 6),
    (6, 3),
    (6, 6),
    (3, 12),
    (12, 3),
)

# 每个元素均为 (rank_count, return_horizon, pairwise)。显式保存实际步长，
# 可以让同一份 panel_base 同时容纳滚动窗口和非重叠窗口，避免依赖一个会被
# 后续运行改写的全局步长。
PANEL_PAST_RETURN_SPECS = tuple(
    (rank_count, return_horizon, PANEL_PAIRWISE)
    for rank_count, return_horizon in PANEL_PAST_RETURN_COMBOS
) + tuple(
    (rank_count, return_horizon, return_horizon)
    for rank_count, return_horizon in PANEL_NONOVERLAP_PAST_RETURN_COMBOS
)
PANEL_RANK_METHOD = "average"
RANK_VOL_REQUIRE_FULL_WINDOW = True
RANK_VOL_DDOF = 1

# 从基金净值筛选长表中读取的必需字段。
COLUMN_IFIND_CODE = "ifind_code"
COLUMN_INVESTMENT_TYPE = "investment_type"
COLUMN_MONTH_DATE = "month_date"
COLUMN_NAV = "nav"
COLUMN_IS_SAMPLE = "is_sample"
COLUMN_IS_SIZE_ELIGIBLE = "is_size_eligible_t"

PANEL_REQUIRED_COLUMNS = (
    COLUMN_IFIND_CODE,
    COLUMN_INVESTMENT_TYPE,
    COLUMN_MONTH_DATE,
    COLUMN_NAV,
    COLUMN_IS_SAMPLE,
    COLUMN_IS_SIZE_ELIGIBLE,
)

# 当前 panel 输出中，在派生收益率和匹配标签之前保留的基础字段。
PANEL_BASE_OUTPUT_COLUMNS = PANEL_REQUIRED_COLUMNS
