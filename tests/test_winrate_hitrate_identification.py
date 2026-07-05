"""测试 Hitrate 连续主变量的独立月度识别逻辑。"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / "D_analysis"
    / "scripts"
    / "run_winrate_hitrate_identification_grid.py"
)


def load_script_module():
    """按真实路径加载脚本，测试不依赖项目是否安装为 Python 包。"""
    spec = importlib.util.spec_from_file_location(
        "run_winrate_hitrate_identification_grid_test", SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 Hitrate 识别脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hitrate_grid = load_script_module()


class WinrateHitrateIdentificationTests(unittest.TestCase):
    """验证候选清单和连续变量识别条件没有沿用 Dummy 门槛。"""

    def test_candidate_grid_has_30_per_metric_and_all_m6_n6(self) -> None:
        specs_by_metric = {}
        for metric, (model_key, _) in hitrate_grid.MODEL_SPECS.items():
            config = hitrate_grid.load_regression_config(model_key)
            specs = hitrate_grid.hitrate_specs(config, metric)
            specs_by_metric[metric] = specs
            self.assertEqual(len(specs), 30)
            self.assertTrue(all(isinstance(item["factor"], str) for item in specs))
            self.assertIn(
                f"hitrate_{metric}_m6_n6_pairwise6",
                {item["factor"] for item in specs},
            )

        # 这个函数同时断言三种口径合计恰好为 90 个候选。
        hitrate_grid.validate_candidate_grid(specs_by_metric)

    def test_m1_n6_without_hit6_still_passes_continuous_identification(self) -> None:
        """没有 Hit6 组不妨碍有变化的 Hitrate 连续变量通过识别。"""
        factor = "hitrate_bottom33_m1_n6_pairwise1"
        n_obs = 60
        # 只使用 0/6～5/6，刻意不提供 hitcount=6（即 Hitrate=1）的样本。
        hitrates = np.tile(np.arange(6, dtype=float) / 6, 10)
        sample = pd.DataFrame(
            {
                "month_date": pd.Timestamp("2020-01-31"),
                factor: hitrates,
                # 控制变量与 Hitrate 不共线，完整矩阵应当满秩。
                "control": np.linspace(-1.0, 1.0, n_obs) ** 2,
            }
        )

        monthly = hitrate_grid.build_monthly_hitrate_identification(
            sample=sample,
            factor=factor,
            control_cols=["control"],
            date_col="month_date",
            min_cross_section_n=50,
        )
        row = monthly.iloc[0]
        self.assertNotIn(1.0, set(sample[factor]))
        self.assertEqual(int(row["hitrate_nunique"]), 6)
        self.assertTrue(bool(row["hitrate_has_variation"]))
        self.assertTrue(bool(row["hitrate_full_rank"]))
        self.assertTrue(bool(row["full_model_rank"]))
        self.assertTrue(bool(row["regression_ready"]))

    def test_constant_hitrate_fails_even_with_enough_observations(self) -> None:
        factor = "hitrate_top50_m2_n2_pairwise2"
        sample = pd.DataFrame(
            {
                "month_date": pd.Timestamp("2020-01-31"),
                factor: np.full(60, 0.5),
                "control": np.linspace(-1.0, 1.0, 60),
            }
        )
        monthly = hitrate_grid.build_monthly_hitrate_identification(
            sample, factor, ["control"], "month_date", 50
        )
        row = monthly.iloc[0]
        self.assertTrue(bool(row["eligible_n"]))
        self.assertFalse(bool(row["hitrate_has_variation"]))
        self.assertFalse(bool(row["hitrate_full_rank"]))
        self.assertFalse(bool(row["regression_ready"]))


if __name__ == "__main__":
    unittest.main()
