"""测试替代排名波动率脚本的核心计算口径。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "A_data" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import Config


def load_script():
    """按路径加载数字开头的脚本。"""
    script_path = SCRIPT_DIR / "3_panel_base_volatility_alternative.py"
    spec = importlib.util.spec_from_file_location(
        "panel_base_volatility_alternative_for_test", script_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载测试脚本：{script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


module = load_script()


class AlternativeVolatilityTests(unittest.TestCase):
    """使用小型合成面板验证排名、选月和标准差。"""

    def test_one_month_rank_uses_same_category_and_window_eligibility(self) -> None:
        """并列收益取平均排名，不合格基金不进入排名分母。"""
        dates = pd.to_datetime(["2020-01-31", "2020-02-29"])
        rows = []
        for code, end_nav in (("F1", 1.1), ("F2", 1.2), ("F3", 1.2)):
            for month_index, month_date in enumerate(dates):
                rows.append(
                    {
                        Config.COLUMN_IFIND_CODE: code,
                        Config.COLUMN_INVESTMENT_TYPE: "类型A",
                        Config.COLUMN_MONTH_DATE: month_date,
                        Config.COLUMN_NAV: 1.0 if month_index == 0 else end_nav,
                        Config.COLUMN_IS_SAMPLE: True,
                        Config.COLUMN_IS_SIZE_ELIGIBLE: not (
                            code == "F3" and month_index == 0
                        ),
                    }
                )
        data = pd.DataFrame(rows)
        ranks = module.calculate_past_1m_rank(data)
        february = data[Config.COLUMN_MONTH_DATE] == dates[1]
        actual = dict(
            zip(
                data.loc[february, Config.COLUMN_IFIND_CODE],
                ranks.loc[february],
            )
        )
        self.assertAlmostEqual(actual["F1"], 0.5)
        self.assertAlmostEqual(actual["F2"], 1.0)
        self.assertTrue(np.isnan(actual["F3"]))

    def test_cross_horizon_volatility_requires_all_four_ranks(self) -> None:
        """四期限标准差使用 ddof=1，任一排名缺失则结果缺失。"""
        data = pd.DataFrame(
            {
                module.ONE_MONTH_RANK_COLUMN: [0.1, 0.1],
                "past_ret_3m_rank_1": [0.2, np.nan],
                "past_ret_6m_rank_1": [0.3, 0.3],
                "past_ret_12m_rank_1": [0.4, 0.4],
            }
        )
        result = module.calculate_cross_horizon_volatility(data)
        self.assertAlmostEqual(result.iloc[0], np.std([0.1, 0.2, 0.3, 0.4], ddof=1))
        self.assertTrue(np.isnan(result.iloc[1]))

    def test_cross_horizon_group_splits_keep_missing_rank_mean_missing(self) -> None:
        """排名均值缺失时，中位数和三分位分组都应保持缺失。"""
        data = pd.DataFrame(
            {
                Config.COLUMN_MONTH_DATE: pd.to_datetime(
                    ["2020-01-31", "2020-01-31", "2020-01-31"]
                ),
                Config.COLUMN_INVESTMENT_TYPE: ["类型A", "类型A", "类型A"],
                module.CROSS_HORIZON_RANK_MEAN_COLUMN: [0.2, np.nan, 0.8],
            }
        )

        median = module.calculate_cross_horizon_median_split(data)
        tercile = module.calculate_cross_horizon_tercile_split(data)

        self.assertTrue(np.isnan(median.iloc[1]))
        self.assertTrue(np.isnan(tercile.iloc[1]))
        self.assertEqual(median.dropna().tolist(), [-2.0, 2.0])
        self.assertEqual(tercile.dropna().tolist(), [2.0, 3.0])

    def test_cross_horizon_group_splits_respect_percentile_boundaries(self) -> None:
        """验证 1/3、0.5、2/3 边界：等于边界时落入较低一侧。"""
        data = pd.DataFrame(
            {
                Config.COLUMN_MONTH_DATE: pd.to_datetime(["2020-01-31"] * 7),
                Config.COLUMN_INVESTMENT_TYPE: ["类型A"] * 7,
                module.CROSS_HORIZON_RANK_MEAN_COLUMN: [
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    np.nan,
                ],
            }
        )

        median = module.calculate_cross_horizon_median_split(data)
        tercile = module.calculate_cross_horizon_tercile_split(data)

        expected_median = pd.Series(
            [-2.0, -2.0, -2.0, 2.0, 2.0, 2.0, np.nan],
            dtype="float64",
        )
        expected_tercile = pd.Series(
            [1.0, 1.0, 2.0, 2.0, 3.0, 3.0, np.nan],
            dtype="float64",
        )
        self.assertTrue(median.equals(expected_median))
        self.assertTrue(tercile.equals(expected_tercile))

    def test_market_direction_aligns_by_month_not_exact_day(self) -> None:
        """交易日月末和自然月末不同也应映射到同一个月。"""
        data = pd.DataFrame(
            {Config.COLUMN_MONTH_DATE: pd.to_datetime(["2020-01-30", "2020-02-28"])}
        )
        directions = pd.Series(
            [1, -1],
            index=pd.period_range("2020-01", periods=2, freq="M"),
            dtype="int8",
        )
        result = module.attach_market_direction(data, directions)
        self.assertEqual(result.tolist(), [1, -1])

    def test_market_state_volatility_uses_recent_state_months(self) -> None:
        """上涨和下跌指标分别使用最近n个对应状态月，而非最近n个自然月。"""
        periods = pd.period_range("2020-01", periods=14, freq="M")
        dates = periods.to_timestamp("M")
        directions = pd.Series(
            [1 if index % 2 == 0 else -1 for index in range(len(periods))],
            index=periods,
            dtype="int8",
        )
        ranks = np.arange(1, len(periods) + 1, dtype="float64") / 20
        data = pd.DataFrame(
            {
                Config.COLUMN_IFIND_CODE: "F1",
                Config.COLUMN_MONTH_DATE: dates,
                module.ONE_MONTH_RANK_COLUMN: ranks,
            }
        )
        result = module.add_market_state_volatilities(data, directions)

        # 最后一个月是下跌月：最近3个下跌月为第10、12、14个月。
        expected_down = np.std(ranks[[9, 11, 13]], ddof=1)
        self.assertAlmostEqual(
            result.iloc[-1]["rank_vol_down_n3_pairwise1"], expected_down
        )
        # 最近3个上涨月为第9、11、13个月。
        expected_up = np.std(ranks[[8, 10, 12]], ddof=1)
        self.assertAlmostEqual(
            result.iloc[-1]["rank_vol_up_n3_pairwise1"], expected_up
        )
        self.assertTrue(np.isnan(result.iloc[-1]["rank_vol_up_n12_pairwise1"]))
        self.assertTrue(np.isnan(result.iloc[-1]["rank_vol_down_n12_pairwise1"]))

    def test_missing_rank_in_selected_market_month_invalidates_window(self) -> None:
        """选中的状态月份缺排名时不能跳到更早月份补足。"""
        periods = pd.period_range("2020-01", periods=8, freq="M")
        directions = pd.Series(1, index=periods, dtype="int8")
        ranks = np.arange(1, 9, dtype="float64") / 10
        ranks[-2] = np.nan
        data = pd.DataFrame(
            {
                Config.COLUMN_IFIND_CODE: "F1",
                Config.COLUMN_MONTH_DATE: periods.to_timestamp("M"),
                module.ONE_MONTH_RANK_COLUMN: ranks,
            }
        )
        result = module.add_market_state_volatilities(data, directions)
        self.assertTrue(np.isnan(result.iloc[-1]["rank_vol_up_n3_pairwise1"]))

    def test_owned_columns_are_exactly_the_requested_fields(self) -> None:
        """脚本只管理本任务需要的字段，避免误删其他上游或下游变量。"""
        columns = module.get_owned_output_columns()
        expected_columns = [
            module.ONE_MONTH_RANK_COLUMN,
            module.CROSS_HORIZON_VOLATILITY_COLUMN,
            module.CROSS_HORIZON_RANK_MEAN_COLUMN,
            module.CROSS_HORIZON_MEDIAN_COLUMN,
            module.CROSS_HORIZON_TERCILE_COLUMN,
            module.MARKET_DIRECTION_COLUMN,
            "rank_vol_up_n3_pairwise1",
            "rank_vol_up_n6_pairwise1",
            "rank_vol_up_n12_pairwise1",
            "rank_vol_down_n3_pairwise1",
            "rank_vol_down_n6_pairwise1",
            "rank_vol_down_n12_pairwise1",
        ]
        self.assertEqual(columns, expected_columns)
        self.assertFalse(
            any(
                "_m" in column
                for column in columns
                if "rank_vol_up" in column or "rank_vol_down" in column
            )
        )


if __name__ == "__main__":
    unittest.main()
