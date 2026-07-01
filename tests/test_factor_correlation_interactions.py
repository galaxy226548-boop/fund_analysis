"""验证相关性与 VIF 检查会使用交互模型的完整设计矩阵。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "B_factors" / "scripts" / "2_factor_correlation.py"


def load_module():
    """按文件路径加载脚本，避免数字开头的文件名影响普通 import。"""
    spec = importlib.util.spec_from_file_location("factor_correlation_test", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载脚本：{SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FactorCorrelationInteractionTests(unittest.TestCase):
    """检查占位符解析、变量清单和乘积列生成。"""

    def setUp(self) -> None:
        self.module = load_module()
        self.module.INTERACTION_MAIN_EFFECTS = ["RANK_MEAN"]
        self.module.INTERACTIONS = self.module.parse_interaction_config(
            ["{FAC,RANK_MEAN}"]
        )

    def test_full_design_matrix_is_used_for_each_factor(self) -> None:
        factor = "FAC_rank_vol_m3_n6_pairwise1"
        variables = self.module.diagnostic_variables_for_factor(
            factor,
            ["CtrlRetSTR", "CtrlRetLTM"],
        )

        self.assertEqual(
            variables,
            [
                factor,
                "rank_mean_m3_n6_pairwise1",
                "FAC__x__RANK_MEAN",
                "CtrlRetSTR",
                "CtrlRetLTM",
            ],
        )

    def test_interaction_column_uses_matched_rank_mean(self) -> None:
        factor = "FAC_rank_vol_m3_n6_pairwise1"
        data = pd.DataFrame(
            {
                factor: [0.2, 0.5],
                "rank_mean_m3_n6_pairwise1": [0.4, 0.3],
            }
        )

        result = self.module.add_interaction_columns(data, factor)

        self.assertAlmostEqual(result.loc[0, "FAC__x__RANK_MEAN"], 0.08)
        self.assertAlmostEqual(result.loc[1, "FAC__x__RANK_MEAN"], 0.15)


if __name__ == "__main__":
    unittest.main()
