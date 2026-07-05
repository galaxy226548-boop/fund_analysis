"""验证 FAC 热力图的 BH-FDR family 与候选窗口规则。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLOT_SCRIPT = PROJECT_ROOT / "D_analysis" / "scripts" / "plot_consistency_heatmaps.py"
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


plot_module = load_module("fac_heatmap_fdr_test", PLOT_SCRIPT)
registry_module = load_module("fac_heatmap_registry_test", REGISTRY_PATH)


class FacHeatmapFdrTests(unittest.TestCase):
    def test_benjamini_hochberg_matches_known_example_and_keeps_missing(self) -> None:
        p_values = pd.Series([0.01, 0.04, np.nan, 0.03, 0.002])
        actual = plot_module.benjamini_hochberg(p_values)
        expected = pd.Series([0.02, 0.04, np.nan, 0.04, 0.008])
        self.assertTrue(np.allclose(actual, expected, equal_nan=True))

    def test_each_model_is_its_own_fdr_family(self) -> None:
        table = pd.DataFrame(
            {"m": [1, 1, 1], "n": [2, 3, 4], "p_value": [0.01, 0.02, np.nan]}
        )
        full = plot_module.add_fdr_columns(plot_module.HEATMAP_MODELS[0], table)
        subgroup = plot_module.add_fdr_columns(plot_module.HEATMAP_MODELS[1], table)
        self.assertTrue((full["fdr_family_role"] == "primary_full_sample").all())
        self.assertTrue((subgroup["fdr_family_role"] == "exploratory_subgroup").all())
        self.assertEqual(int(full["fdr_family_size"].iloc[0]), 2)
        self.assertNotEqual(full["fdr_family"].iloc[0], subgroup["fdr_family"].iloc[0])

    def test_candidate_rule_separates_primary_exploratory_and_robust(self) -> None:
        rows = []
        specs = {
            (1, 2): {
                "fm_heatmap_full": (True, "positive", 0.01),
                "fm_heatmap_up": (True, "positive", 0.02),
                "fm_heatmap_down": (True, "positive", 0.03),
            },
            (2, 3): {
                "fm_heatmap_full": (False, "negative", 0.20),
                "fm_heatmap_up": (True, "negative", 0.02),
                "fm_heatmap_down": (True, "negative", 0.03),
            },
        }
        model_keys = [model.key for model in plot_module.HEATMAP_MODELS]
        for (m, n), configured in specs.items():
            for model_key in model_keys:
                significant, direction, q_value = configured.get(
                    model_key, (False, "positive", 0.50)
                )
                rows.append(
                    {
                        "m": m,
                        "n": n,
                        "sample_group": model_key,
                        "coef_direction": direction,
                        "is_fdr_significant_5pct": significant,
                        "coef": 0.1 if direction == "positive" else -0.1,
                        "t_stat": 2.5 if significant else 0.5,
                        "q_value": q_value,
                    }
                )
        result = plot_module.build_effective_mn_summary(pd.DataFrame(rows))
        robust = result.loc[(result["m"] == 1) & (result["n"] == 2)].iloc[0]
        exploratory = result.loc[(result["m"] == 2) & (result["n"] == 3)].iloc[0]
        self.assertEqual(
            robust["effectiveness_tier"], "robust_primary_plus_2_exploratory"
        )
        self.assertEqual(exploratory["effectiveness_tier"], "exploratory_2plus")

    def test_registry_contains_full_sample_heatmap_without_group_filter(self) -> None:
        config = registry_module.get_regression_config("fm_heatmap_full")
        self.assertEqual(len(config["factors"]), 132)
        self.assertFalse(any("_n1_" in factor for factor in config["factors"]))
        self.assertEqual(config["factor_sample_filters"], {})
        self.assertIn("match_is_sample_future_ret_6m", config["sample_filters"])

    def test_process_model_writes_q_matrix_and_fdr_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            result_path = root / "results.csv"
            rows = []
            for n, p_value, t_stat in (
                (1, np.nan, np.nan),
                (2, 0.001, 3.5),
                (3, 0.20, 1.3),
            ):
                factor = f"FAC_rank_vol_m1_n{n}_pairwise1"
                rows.append(
                    {
                        "factor": factor,
                        "variable": factor,
                        "coef": 0.02,
                        "t_stat": t_stat,
                        "p_value": p_value,
                        "n_months": 100,
                        "avg_monthly_n": 200,
                    }
                )
            pd.DataFrame(rows).to_csv(result_path, index=False)
            model = plot_module.HeatmapModel(
                key="fm_heatmap_full", label="Full sample", result_path=result_path
            )
            significant, long_table = plot_module.process_model(
                model, root / "output", annotate=False
            )
            group_dir = root / "output" / "fm_heatmap_full"
            self.assertTrue(
                (group_dir / "fm_heatmap_full_fac_bh_q_value_matrix.csv").exists()
            )
            self.assertEqual(int(long_table["fdr_family_size"].iloc[0]), 2)
            self.assertEqual(len(significant), 1)
            self.assertNotIn(1, long_table["n"].tolist())


if __name__ == "__main__":
    unittest.main()
