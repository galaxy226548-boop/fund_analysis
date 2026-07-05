"""验证标准 FAC 五窗口 × 四期限的 FDR family 登记。"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "scripts" / "fdr_registry.py"


def load_registry_module():
    """按路径加载 FDR registry，避免依赖 scripts 目录是 Python package。"""
    spec = importlib.util.spec_from_file_location(
        "standard_fac_fdr_registry_test_module", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{REGISTRY_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


registry = load_registry_module()


class StandardFacFdrRegistryTests(unittest.TestCase):
    def test_each_target_group_has_one_active_four_source_family(self) -> None:
        groups = ("up", "down", "top33", "bottom33")
        expected_labels = {"y1m", "y3m", "y6m", "y12m"}

        for group in groups:
            model = f"fm_baseline_{group}"
            family_id = f"standard_fac_20__{model}"
            config = registry.get_family(family_id)

            self.assertEqual(config["status"], "active")
            self.assertEqual(len(config["sources"]), 4)
            labels = {
                source["label"].removeprefix(f"{model}__")
                for source in config["sources"]
            }
            self.assertEqual(labels, expected_labels)

    def test_selector_matches_exactly_the_five_fixed_windows(self) -> None:
        config = registry.get_family("standard_fac_20__fm_baseline_up")
        pattern = config["sources"][0]["selectors"][0]["pattern"]
        expected = {
            "FAC_rank_vol_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1",
        }
        candidates = {
            f"FAC_rank_vol_m{m}_n{n}_pairwise1"
            for m in range(1, 13)
            for n in range(2, 13)
        }
        self.assertEqual({value for value in candidates if re.match(pattern, value)}, expected)

    def test_obsolete_model_by_m_families_are_not_registered(self) -> None:
        obsolete = [
            family_id
            for family_id in registry.FDR_FAMILIES
            if family_id.startswith("standard_fac__")
        ]
        self.assertEqual(obsolete, [])


if __name__ == "__main__":
    unittest.main()
