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
# m 表示后续排名波动率需要的排名个数，n 表示每次排名使用过去 n 个月收益。
# PANEL_PAIRWISE 表示相邻两个收益率窗口之间相隔几个月；1 为逐月前推。
PANEL_PAST_RETURN_COMBOS = ((3, 6), (6, 3), (6, 6), (6, 12), (12, 6))
PANEL_PAIRWISE = 1
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
