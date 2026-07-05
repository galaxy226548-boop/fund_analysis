"""验证滚动与非重叠收益窗口可以安全共存。"""

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


def load_script(module_name: str, filename: str):
    """按文件路径加载以数字开头、无法普通 import 的项目脚本。"""
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载测试脚本：{filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


panel_module = load_script("generate_panel_base_for_test", "3_generate_panel_base.py")
grouping_module = load_script(
    "panel_base_grouping_for_test", "3_panel_base_grouping_factors.py"
)
winrate_module = load_script(
    "panel_base_winrates_for_test", "3_panel_base_winrates_factors.py"
)


class PanelPairwiseSpecTests(unittest.TestCase):
    """使用小型合成面板检查窗口偏移、命名和命中恒等式。"""

    @classmethod
    def setUpClass(cls) -> None:
        # 40 个月足以覆盖本次最长 36 个月历史；多只基金让截面排名有意义。
        dates = pd.date_range("2018-01-31", periods=40, freq="ME")
        rows = []
        for fund_index, monthly_rate in enumerate((0.003, 0.006, 0.009, 0.012), 1):
            for month_index, month_date in enumerate(dates):
                rows.append(
                    {
                        Config.COLUMN_IFIND_CODE: f"F{fund_index}",
                        Config.COLUMN_INVESTMENT_TYPE: "测试基金",
                        Config.COLUMN_MONTH_DATE: month_date,
                        Config.COLUMN_NAV: (1 + monthly_rate) ** month_index,
                        Config.COLUMN_IS_SAMPLE: True,
                        Config.COLUMN_IS_SIZE_ELIGIBLE: True,
                    }
                )
        cls.source = pd.DataFrame(rows)
        cls.panel = panel_module.add_period_columns(
            cls.source, return_type="simple"
        )

    def test_config_uses_unambiguous_m_n_and_expected_steps(self) -> None:
        """m 是收益期限、n 是期数，非重叠步长必须等于 m。"""
        nonoverlap_specs = {
            spec for spec in Config.PANEL_PAST_RETURN_SPECS if spec[2] != 1
        }
        self.assertEqual(
            nonoverlap_specs,
            {
                (6, 3, 6),
                (3, 6, 3),
                (6, 6, 6),
                (3, 12, 3),
                (12, 3, 12),
            },
        )
        self.assertTrue(all(pairwise == return_horizon for return_horizon, _, pairwise in nonoverlap_specs))
        self.assertTrue(all(rank_count * return_horizon <= 36 for return_horizon, rank_count, _ in nonoverlap_specs))

    def test_winrate_grid_is_complete_and_included_in_heatmap_panel_specs(self) -> None:
        """新 winrate 网格应覆盖 m,n=1..6，并由 heatmap 大面板统一生成。"""
        specs = set(Config.PANEL_WINRATE_NONOVERLAP_PAST_RETURN_SPECS)
        self.assertEqual(
            specs,
            {
                (m, n, m)
                for m in range(1, 7)
                for n in range(1, 7)
            },
        )
        self.assertEqual(len(specs), 36)
        self.assertTrue(specs.issubset(set(Config.PANEL_HEATMAP_PAST_RETURN_SPECS)))

    def test_winrate_generator_only_requests_active_registry_specs(self) -> None:
        """生成器不能误请求 heatmap 面板没有维护的旧非重叠规格。"""
        expected_rolling = {
            (m, n, Config.PANEL_PAIRWISE)
            for m, n in Config.PANEL_PAST_RETURN_COMBOS
        }
        expected_nonoverlap = set(Config.PANEL_WINRATE_NONOVERLAP_PAST_RETURN_SPECS)
        actual = set(winrate_module.RANK_HIT_SPECS)
        self.assertEqual(actual, expected_rolling | expected_nonoverlap)
        self.assertNotIn((3, 12, 3), actual)
        self.assertNotIn((12, 3, 12), actual)
        self.assertTrue(actual.issubset(set(Config.PANEL_HEATMAP_PAST_RETURN_SPECS)))

    def test_winrate_rebuild_identifies_legacy_mutually_exclusive_columns(self) -> None:
        """重建累计编码时，应定向清理旧 hit0..hitn 列。"""
        legacy_columns = set(winrate_module.get_legacy_mutually_exclusive_columns())
        self.assertIn("dummy_top50_m3_n6_hit0_pairwise1", legacy_columns)
        self.assertIn("dummy_top50_m3_n6_hit6_pairwise1", legacy_columns)
        self.assertNotIn("dummy_top50_m3_n6_hit_above0_pairwise1", legacy_columns)

    def test_pairwise1_keeps_legacy_name_and_numerical_window(self) -> None:
        """旧滚动列不改名，第二个3个月窗口仍是 t-4 到 t-1。"""
        fund = self.panel.loc[self.panel[Config.COLUMN_IFIND_CODE] == "F2"].reset_index(drop=True)
        row_index = len(fund) - 1
        expected = fund.loc[row_index - 1, Config.COLUMN_NAV] / fund.loc[
            row_index - 4, Config.COLUMN_NAV
        ] - 1
        self.assertAlmostEqual(fund.loc[row_index, "past_ret_3m_2"], expected)
        self.assertNotIn("past_ret_3m_2_pairwise1", self.panel.columns)

        rank_columns = [f"past_ret_3m_rank_{index}" for index in range(1, 7)]
        valid = fund[rank_columns].notna().all(axis=1)
        expected_volatility = fund.loc[valid, rank_columns].std(axis=1, ddof=1)
        self.assertTrue(
            np.allclose(
                fund.loc[valid, "rank_vol_m3_n6_pairwise1"],
                expected_volatility,
            )
        )

    def test_nonoverlap_windows_use_n_month_step_and_explicit_suffix(self) -> None:
        """两个3个月非重叠窗口分别使用 t-3→t 与 t-6→t-3。"""
        fund = self.panel.loc[self.panel[Config.COLUMN_IFIND_CODE] == "F3"].reset_index(drop=True)
        row_index = len(fund) - 1
        first_expected = fund.loc[row_index, Config.COLUMN_NAV] / fund.loc[
            row_index - 3, Config.COLUMN_NAV
        ] - 1
        second_expected = fund.loc[row_index - 3, Config.COLUMN_NAV] / fund.loc[
            row_index - 6, Config.COLUMN_NAV
        ] - 1
        self.assertAlmostEqual(
            fund.loc[row_index, "past_ret_3m_1_pairwise3"], first_expected
        )
        self.assertAlmostEqual(
            fund.loc[row_index, "past_ret_3m_2_pairwise3"], second_expected
        )
        self.assertIn("past_ret_3m_rank_2_pairwise3", self.panel.columns)
        self.assertIn(
            "match_is_sample_past_ret_3m_2_pairwise3", self.panel.columns
        )

    def test_grouping_reads_rank_columns_from_matching_pairwise_spec(self) -> None:
        """排名均值不能误读另一个步长下的同期限 rank。"""
        result = grouping_module.add_rank_mean_and_group_columns(self.panel)
        rank_columns = grouping_module.get_rank_columns(6, 3, 3)
        mean_column = grouping_module.get_rank_mean_column(6, 3, 3)
        valid = result[rank_columns].notna().all(axis=1)
        expected = result.loc[valid, rank_columns].mean(axis=1)
        self.assertTrue(
            np.allclose(result.loc[valid, mean_column], expected, equal_nan=True)
        )
        ordered = grouping_module.order_columns_after_fac_rank_vol(result)
        grouping_module.validate_grouping_factors(self.panel, ordered)

    def test_all_output_names_match_their_actual_pairwise(self) -> None:
        """每套规格的高层列名和底层 rank 后缀都必须记录真实步长。"""
        generated_names = set()
        for return_horizon, rank_count, pairwise in Config.PANEL_PAST_RETURN_SPECS:
            rank_columns = winrate_module.get_rank_columns(
                rank_count, return_horizon, pairwise
            )
            expected_rank_suffix = "" if pairwise == 1 else f"_pairwise{pairwise}"
            self.assertTrue(
                all(column.endswith(expected_rank_suffix) for column in rank_columns)
            )
            names = {
                panel_module.get_rank_volatility_column(
                    rank_count, return_horizon, pairwise
                ),
                grouping_module.get_rank_mean_column(
                    rank_count, return_horizon, pairwise
                ),
                winrate_module.get_hitrate_column(
                    "top50", rank_count, return_horizon, pairwise
                ),
            }
            self.assertTrue(
                all(name.endswith(f"pairwise{pairwise}") for name in names)
            )
            self.assertTrue(generated_names.isdisjoint(names))
            generated_names.update(names)

    def test_synthetic_panel_passes_full_panel_validation(self) -> None:
        """小面板也要通过正式写盘前使用的完整校验。"""
        panel_module.validate_panel(self.panel, source_row_count=len(self.source))

    def test_winrate_m_controls_rank_count_and_hitrate_denominator(self) -> None:
        """m3_n6 必须读取6个3个月 rank，并以6作为 hitrate 分母。"""
        rank_columns = winrate_module.get_rank_columns(6, 3, 3)
        self.assertEqual(len(rank_columns), 6)
        self.assertEqual(rank_columns[0], "past_ret_3m_rank_1_pairwise3")
        self.assertEqual(rank_columns[-1], "past_ret_3m_rank_6_pairwise3")

        result, records = winrate_module.add_rank_hit_features(
            self.panel,
            rank_count=6,
            return_horizon=3,
            thresholds_config={"top50": winrate_module.RANK_HIT_THRESHOLDS["top50"]},
            pairwise=3,
        )
        hitcount_column = "hitcount_top50_m3_n6_pairwise3"
        hitrate_column = "hitrate_top50_m3_n6_pairwise3"
        valid = result[hitcount_column].notna()
        self.assertTrue(
            np.allclose(
                result.loc[valid, hitrate_column],
                result.loc[valid, hitcount_column] / 6,
            )
        )

        dummy_columns = [
            f"dummy_top50_m3_n6_hit_above{k - 1}_pairwise3"
            for k in range(1, 7)
        ]
        expected_dummy_sum = result.loc[valid, hitcount_column]
        self.assertTrue(
            np.allclose(result.loc[valid, dummy_columns].sum(axis=1), expected_dummy_sum)
        )
        self.assertEqual(len([r for r in records if r["variable_type"] == "dummy"]), 6)
        winrate_module.validate_rank_hit_features(result, records)

    def test_all_specs_use_dk_equal_hitcount_at_least_k(self) -> None:
        """累计 Dummy 必须逐档满足 Dk=1(hitcount>=k)，缺失窗口保持 NaN。"""
        hitcounts = [0, 1, 3, 4, 6]
        rows = []
        for hitcount in hitcounts:
            # Top50 使用 rank > 0.5；前 hitcount 列放 0.75，其余放 0.25，
            # 这样可以精确构造 0 到 6 的代表性命中次数。
            rows.append(
                {
                    f"past_ret_3m_rank_{index}_pairwise3": (
                        0.75 if index <= hitcount else 0.25
                    )
                    for index in range(1, 7)
                }
            )

        # 最后一行故意缺一个 rank，用来确认缺失历史不会被误判为未命中。
        missing_row = {
            f"past_ret_3m_rank_{index}_pairwise3": 0.75
            for index in range(1, 7)
        }
        missing_row["past_ret_3m_rank_6_pairwise3"] = np.nan
        rows.append(missing_row)
        source = pd.DataFrame(rows)

        result, records = winrate_module.add_rank_hit_features(
            source,
            rank_count=6,
            return_horizon=3,
            thresholds_config=winrate_module.RANK_HIT_THRESHOLDS,
            pairwise=3,
        )
        top50_columns = [
            f"dummy_top50_m3_n6_hit_above{k - 1}_pairwise3"
            for k in range(1, 7)
        ]
        expected = np.array(
            [
                [0, 0, 0, 0, 0, 0],  # hit=0
                [1, 0, 0, 0, 0, 0],  # hit=1
                [1, 1, 1, 0, 0, 0],  # hit=3
                [1, 1, 1, 1, 0, 0],  # hit=4
                [1, 1, 1, 1, 1, 1],  # hit=6
            ],
            dtype="float64",
        )
        self.assertTrue(np.array_equal(result.loc[:4, top50_columns], expected))
        self.assertTrue(result.loc[5, top50_columns].isna().all())

        for metric in winrate_module.RANK_HIT_THRESHOLDS:
            metric_records = [
                record
                for record in records
                if record["metric"] == metric
                and record["variable_type"] == "dummy"
            ]
            self.assertEqual(len(metric_records), 6)
            self.assertEqual(
                tuple(record["minimum_hits"] for record in metric_records),
                (1, 2, 3, 4, 5, 6),
            )
            self.assertTrue(
                all(record["comparison_operator"] == ">=" for record in metric_records)
            )
        winrate_module.validate_rank_hit_features(result, records)

    def test_top33_and_bottom33_leave_a_middle_rank_band(self) -> None:
        """Top33 与 Bottom33 必须使用 2/3、1/3 边界，而不是旧 30% 门槛。"""
        source = pd.DataFrame(
            {
                "past_ret_2m_rank_1_pairwise2": [0.2, 0.5, 0.8],
                "past_ret_2m_rank_2_pairwise2": [0.3, 0.5, 0.7],
            }
        )
        result, records = winrate_module.add_rank_hit_features(
            source,
            rank_count=2,
            return_horizon=2,
            thresholds_config=winrate_module.RANK_HIT_THRESHOLDS,
            pairwise=2,
        )
        self.assertEqual(result["hitcount_bottom33_m2_n2_pairwise2"].tolist(), [2, 0, 0])
        self.assertEqual(result["hitcount_top33_m2_n2_pairwise2"].tolist(), [0, 0, 2])
        self.assertEqual(result["hitcount_top50_m2_n2_pairwise2"].tolist(), [0, 0, 2])
        winrate_module.validate_rank_hit_features(result, records)


if __name__ == "__main__":
    unittest.main()
