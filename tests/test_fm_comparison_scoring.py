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


import scoring  # noqa: E402


class TestScoringBasics(unittest.TestCase):
    """样本层识别、邻格构造、FM 分档、样本量扣分。"""

    def setUp(self):
        self.cfg = dict(config.DEFAULT_CONFIG)

    def test_sample_layer(self):
        # 按下划线分词识别：含 up -> up；含 bottom33 -> bottom33；其余 other
        self.assertEqual(scoring.sample_layer("fm_baseline_up"), "up")
        self.assertEqual(scoring.sample_layer("fm_baseline_hs300_up"), "up")
        self.assertEqual(scoring.sample_layer("fm_baseline_up_indvol"), "up")
        self.assertEqual(scoring.sample_layer("fm_baseline_indvol_bottom33"), "bottom33")
        self.assertEqual(scoring.sample_layer("fm_baseline_bottom33"), "bottom33")
        self.assertEqual(scoring.sample_layer("fm_baseline_down_hs300"), "other")
        self.assertEqual(scoring.sample_layer("fm_baseline_mid33"), "other")

    def test_neighbor_cells(self):
        # 轴 m/n 均为 {3,6,12}：邻格 = 恰好沿一条轴走一步（曼哈顿距离 1）
        m_axis, n_axis = [3, 6, 12], [3, 6, 12]
        # m3_n3 与 m3_n6 是邻格；对角 m6_n6 不是
        self.assertIn((3, 6), scoring.neighbor_cells(3, 3, m_axis, n_axis))
        self.assertNotIn((6, 6), scoring.neighbor_cells(3, 3, m_axis, n_axis))
        # 角点 m3_n3 只有 2 个邻格
        self.assertEqual(len(scoring.neighbor_cells(3, 3, m_axis, n_axis)), 2)
        # 中心点 m6_n6 有 4 个邻格
        self.assertEqual(
            sorted(scoring.neighbor_cells(6, 6, m_axis, n_axis)),
            [(3, 6), (6, 3), (6, 12), (12, 6)],
        )
        # 轴随新参数扩展：m 轴加入 24 后 m12 多一个右邻
        self.assertIn((24, 6), scoring.neighbor_cells(12, 6, [3, 6, 12, 24], n_axis))

    def test_build_axes(self):
        m_axis, n_axis = scoring.build_axes([(6, 12), (3, 6), (6, 3), (6, 6)])
        self.assertEqual(m_axis, [3, 6])
        self.assertEqual(n_axis, [3, 6, 12])

    def test_fm_significance_bands(self):
        # 分档边界：>=2.58 满分 40；>=1.96 得 32；恰好 1.96 命中 32 档
        self.assertEqual(scoring.fm_significance_score(-3.60, self.cfg)[0], 40.0)
        self.assertEqual(scoring.fm_significance_score(1.96, self.cfg)[0], 32.0)
        self.assertEqual(scoring.fm_significance_score(-1.73, self.cfg)[0], 24.0)
        self.assertEqual(scoring.fm_significance_score(1.31, self.cfg)[0], 0.0)
        # 缺失 t 值得 0 分，明细里说明原因
        score, detail = scoring.fm_significance_score(None, self.cfg)
        self.assertEqual(score, 0.0)
        self.assertIn("名称", detail)

    def test_sample_penalty_tiers(self):
        # 月份数：<48 -> -10；<60 -> -5；>=60 不扣。样本数：<3000 -> -8；<6000 -> -3
        self.assertEqual(scoring.sample_penalty(47, 7000, self.cfg)[0], -10.0)
        self.assertEqual(scoring.sample_penalty(48, 7000, self.cfg)[0], -5.0)   # 恰好 48 落 <60 档
        self.assertEqual(scoring.sample_penalty(60, 7000, self.cfg)[0], 0.0)    # 恰好 60 不扣
        self.assertEqual(scoring.sample_penalty(67, 4832, self.cfg)[0], -3.0)   # top33 m6_n12 场景
        self.assertEqual(scoring.sample_penalty(67, 2999, self.cfg)[0], -8.0)
        self.assertEqual(scoring.sample_penalty(56, 4832, self.cfg)[0], -8.0)   # 两类扣分叠加 -5 + -3


if __name__ == "__main__":
    unittest.main()
