"""检查滚动与非重叠 winrate 回归配置。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "A_data" / "scripts"
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import Config


def load_registry_module():
    """按真实文件路径加载回归注册表。"""
    spec = importlib.util.spec_from_file_location("regression_registry_test", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归注册表：{REGISTRY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


registry_module = load_registry_module()


class WinrateRegistryTests(unittest.TestCase):
    """验证 m/n、步长、dummy 数量和模型输出目录不会串线。"""

    def test_pairwise1_factor_names_follow_corrected_m_n_semantics(self) -> None:
        config = registry_module.get_regression_config("fm_winrates_top50")
        specs = config["window_specs"]
        factors = config["factors"]

        self.assertEqual(len(specs), len(factors))
        for spec, factor_group in zip(specs, factors):
            m = int(spec["m"])
            n = int(spec["n"])
            pairwise = int(spec["pairwise"])
            self.assertEqual(pairwise, 1)
            self.assertEqual(len(factor_group), n)
            self.assertEqual(
                factor_group[0],
                f"dummy_top50_m{m}_n{n}_hit1_pairwise1",
            )
            self.assertEqual(
                factor_group[-1],
                f"dummy_top50_m{m}_n{n}_hit{n}_pairwise1",
            )

    def test_nonoverlap_specs_match_data_generation_config(self) -> None:
        config = registry_module.get_regression_config(
            "fm_winrates_top50_nonoverlap"
        )
        specs = {
            (int(item["m"]), int(item["n"]), int(item["pairwise"]))
            for item in config["window_specs"]
        }
        expected = set(Config.PANEL_WINRATE_NONOVERLAP_PAST_RETURN_SPECS)
        self.assertEqual(specs, expected)
        self.assertEqual(len(specs), 36)
        self.assertTrue(all(pairwise == m for m, _, pairwise in specs))
        self.assertTrue(
            all(int(item["history_months"]) <= 36 for item in config["window_specs"])
        )

    def test_nonoverlap_models_contain_hitrate_and_full_cumulative_layers(self) -> None:
        """三种口径都应包含36个 hitrate 主模型和36组累计 Dummy。"""
        for metric in ("top50", "top33", "bottom33"):
            config = registry_module.get_regression_config(
                f"fm_winrates_{metric}_nonoverlap"
            )
            scalar_factors = [item for item in config["factors"] if isinstance(item, str)]
            dummy_groups = [item for item in config["factors"] if isinstance(item, tuple)]
            self.assertEqual(len(scalar_factors), 36)
            self.assertEqual(len(dummy_groups), 36)
            self.assertEqual(config["portfolio_sorting_factors"], scalar_factors)

            for spec, hitrate_factor, factor_group in zip(
                config["window_specs"], scalar_factors, dummy_groups
            ):
                m = int(spec["m"])
                n = int(spec["n"])
                pairwise = int(spec["pairwise"])
                self.assertEqual(
                    hitrate_factor,
                    f"hitrate_{metric}_m{m}_n{n}_pairwise{pairwise}",
                )
                self.assertEqual(
                    factor_group,
                    tuple(
                        f"dummy_{metric}_m{m}_n{n}_hit_above{k - 1}_pairwise{pairwise}"
                        for k in range(1, n + 1)
                    ),
                )
                self.assertIn(factor_group, config["factor_group_suffixes"])

    def test_nonoverlap_thresholds_and_source_panel_are_explicit(self) -> None:
        """新模型必须使用 Top50/Top33/Bottom33，并读取扩充后的 heatmap 面板。"""
        self.assertEqual(
            set(registry_module.WINRATE_NONOVERLAP_METRICS),
            {"top50", "top33", "bottom33"},
        )
        for metric in registry_module.WINRATE_NONOVERLAP_METRICS:
            config = registry_module.get_regression_config(
                f"fm_winrates_{metric}_nonoverlap"
            )
            self.assertEqual(
                config["preprocess_input_path"],
                registry_module.HEATMAP_PANEL_INPUT_PATH,
            )
            self.assertEqual(config["y"], "future_ret_6m")
            self.assertEqual(config["min_cross_section_n"], 50)
            self.assertEqual(config["newey_west_lag"], 5)

    def test_nonoverlap_models_have_independent_output_paths(self) -> None:
        path_fields = (
            "preprocess_output_path",
            "preprocess_preview_path",
            "preprocess_summary_path",
            "regression_input_path",
            "correlation_output_dir",
            "output_dir",
        )
        for metric in ("top50", "top33", "bottom33"):
            key = f"fm_winrates_{metric}_nonoverlap"
            config = registry_module.get_regression_config(key)
            for field in path_fields:
                self.assertIn(key, str(config[field]))
            for step in config["pipeline"]:
                for output_path in step.get("outputs", []):
                    self.assertIn(key, str(output_path))


if __name__ == "__main__":
    unittest.main()
