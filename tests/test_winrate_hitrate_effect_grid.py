"""测试连续 Hitrate 线性主效应网格的选择、FDR、完整网格和动态报告。"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT / "D_analysis" / "scripts" / "run_winrate_hitrate_effect_grid.py"
)


def load_script_module():
    """按真实文件路径加载脚本。"""
    spec = importlib.util.spec_from_file_location(
        "run_winrate_hitrate_effect_grid_test", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 Hitrate 效果脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effect_grid = load_script_module()


def make_candidates() -> pd.DataFrame:
    """构造三种口径各30个的完整候选摘要。"""
    rows = []
    for metric, (model_key, display_name) in effect_grid.MODEL_SPECS.items():
        for n in range(2, 7):
            for m in range(1, 7):
                passed = not (m == 6 and n == 6)
                rows.append(
                    {
                        "metric": metric,
                        "display_name": display_name,
                        "model_key": model_key,
                        "m": m,
                        "n": n,
                        "factor": effect_grid.factor_name(metric, m, n),
                        "eligible_months": 47 if not passed else 100,
                        "selection_ready_months": 47 if not passed else 100,
                        "selection_ready_rate": 1.0,
                        "passes_hitrate_gate": passed,
                        "failure_reason_counts": "样本月份不足" if not passed else "{}",
                    }
                )
    return pd.DataFrame(rows)


class WinrateHitrateEffectGridTests(unittest.TestCase):
    """验证效果脚本不再沿用累计 Dummy 的模型范围。"""

    def test_source_has_new_cli_and_no_old_dummy_path_or_fixed_model_count(self) -> None:
        source = SCRIPT_PATH.read_text(encoding="utf-8")
        self.assertIn("--passing-hitrate-models", source)
        self.assertNotIn('"--passing-models"', source)
        self.assertNotIn("winrates_identification_grid", source)
        self.assertNotRegex(source, r"\b64\b")

    def test_fdr_family_size_equals_successful_primary_models(self) -> None:
        results = pd.DataFrame(
            {
                "coef": [0.1, -0.2, 0.3],
                "t_stat": [2.0, -3.0, np.nan],
                "p_value": [0.04, 0.01, np.nan],
                "n_months": [100, 90, 80],
            }
        )
        adjusted, family_size = effect_grid.apply_primary_fdr(results)
        self.assertEqual(family_size, 2)
        self.assertEqual(int(adjusted["q_value"].notna().sum()), 2)
        self.assertFalse(bool(adjusted.loc[2, "estimation_success"]))

    def test_complete_candidate_grid_contains_all_three_m6_n6(self) -> None:
        candidates = make_candidates()
        effect_grid.validate_candidate_summary(candidates)
        for metric in effect_grid.MODEL_SPECS:
            row = candidates.query("metric == @metric and m == 6 and n == 6")
            self.assertEqual(len(row), 1)

    def test_failed_m6_n6_and_m5_n6_keep_their_heatmap_positions(self) -> None:
        candidates = make_candidates()
        results = pd.DataFrame(
            {
                "metric": ["top50"],
                "m": [5],
                "n": [6],
                "estimation_success": [True],
                "beta_full_range_pp": [1.25],
                "n_months": [66],
                "q_value": [0.08],
                "significant_fdr_5pct": [False],
            }
        )
        _, cells = effect_grid.build_effect_grid(results, candidates, "top50")
        self.assertEqual(cells[(5, 6)]["state"], "estimated")
        self.assertEqual(cells[(6, 6)]["state"], "identification_failed")
        self.assertIn("Hitrate ID", cells[(6, 6)]["text"])
        self.assertEqual(cells[(6, 1)]["state"], "design_excluded")

    def test_report_counts_are_computed_from_result_data(self) -> None:
        candidates = make_candidates()
        results = pd.DataFrame(
            {
                "metric": ["top50", "top50", "top33", "bottom33"],
                "display_name": ["Top 50", "Top 50", "Top 33", "Bottom 33"],
                "m": [1, 2, 1, 1],
                "n": [2, 2, 2, 2],
                "coef": [0.1, -0.1, 0.2, -0.2],
                "beta_full_range_pp": [10.0, -10.0, 20.0, -20.0],
                "t_stat": [2.0, -1.0, 3.0, -2.5],
                "p_value": [0.04, 0.30, 0.01, 0.02],
                "q_value": [0.08, 0.30, 0.04, 0.04],
                "n_months": [100, 100, 90, 80],
                "estimation_success": [True, True, True, True],
                "nominal_p_lt_0_05": [True, False, True, True],
                "significant_fdr_5pct": [False, False, True, True],
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "report.md"
            effect_grid.build_report(results, candidates, report_path, 4, 7)
            report = report_path.read_text(encoding="utf-8")
        self.assertIn("family size=4", report)
        self.assertIn("| Top 50 | 30 | 29 | 2 | 1 | 1 | 1 | 0 |", report)
        self.assertIn("| Top 33 | 30 | 29 | 1 | 1 | 0 | 1 | 1 |", report)
        self.assertIn("共有 7 个", report)


if __name__ == "__main__":
    unittest.main()
