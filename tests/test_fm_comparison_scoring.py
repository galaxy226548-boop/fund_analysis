"""fm_comparison 打分引擎与配置的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 把 fm_comparison 目录加入搜索路径，按普通模块导入（目录名带大写前缀，不适合做包名）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = PROJECT_ROOT / "I_Visualization" / "fm_comparison"
sys.path.insert(0, str(PKG_DIR))

import config  # noqa: E402


class TestConfig(unittest.TestCase):
    """校验配置文件的键完整性，防止后续函数取不到参数。"""

    def test_default_config_keys(self):
        # 打分引擎依赖的全部键必须存在
        required = {
            "fm_full", "fm_t_bands",
            "neighbor_full", "neighbor_t_min",
            "ps_full", "ps_p_bands", "ps_direction_conflict_mult",
            "ps_econ_threshold", "ps_econ_mult",
            "r2_individual_full", "r2_family_full",
            "months_penalties", "obs_penalties",
            "corr_pair_penalty", "corr_pair_core_penalty", "corr_cap",
            "vif_penalty", "vif_core_penalty", "vif_cap",
            "replace_margin", "tie_band",
        }
        self.assertTrue(required.issubset(config.DEFAULT_CONFIG.keys()))

    def test_baselines(self):
        # 两条基准：bottom33 与 up（top50 对应 fm_baseline_up）
        self.assertEqual(config.BASELINES["bottom33"]["model"], "fm_baseline_bottom33")
        self.assertEqual(config.BASELINES["bottom33"]["param_key"], "m3_n6")
        self.assertEqual(config.BASELINES["up"]["model"], "fm_baseline_up")
        self.assertEqual(config.BASELINES["up"]["param_key"], "m6_n12")

    def test_paths(self):
        # 总表路径应指向 D_analysis 下的固定位置
        self.assertTrue(str(config.SUMMARY_XLSX).endswith("回归系数显著性_总表.xlsx"))


if __name__ == "__main__":
    unittest.main()
