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


import pandas as pd  # noqa: E402


class TestScoringAdvanced(unittest.TestCase):
    """邻格稳健性、PS 折扣叠乘、R² 分位、共线性扣分。"""

    def setUp(self):
        self.cfg = dict(config.DEFAULT_CONFIG)

    def _family(self):
        # 构造一个族的 FM 表：m6_n6 为本格（coef 为负），四个邻格中两个"同号且 |t|>=1.645"
        return pd.DataFrame({
            "m":      [6,     3,     6,     6,     12],
            "n":      [6,     6,     3,     12,    6],
            "coef":   [-0.05, -0.07, -0.04, 0.03,  -0.06],
            "t_stat": [-2.0,  -1.73, -0.9,  2.1,   -1.8],
        })

    def test_neighbor_robustness(self):
        # 4 个邻格里：m3_n6(-1.73 同号显著) 和 m12_n6(-1.8 同号显著) 命中，m6_n3 不显著，m6_n12 异号
        score, detail = scoring.neighbor_robustness_score(6, 6, -0.05, self._family(), self.cfg)
        self.assertAlmostEqual(score, 10.0 * 2 / 4)
        self.assertIn("2/4", detail["代入"])

    def test_neighbor_no_data(self):
        # 族里只有本格自己 -> 无邻格数据，得 0 并在明细里说明
        alone = pd.DataFrame({"m": [6], "n": [6], "coef": [-0.05], "t_stat": [-2.0]})
        score, detail = scoring.neighbor_robustness_score(6, 6, -0.05, alone, self.cfg)
        self.assertEqual(score, 0.0)
        self.assertIn("无邻格", detail["代入"])

    def test_ps_score_bands_and_discounts(self):
        # p=0.006, 收益 -2.5%/月, FM 系数同为负 -> 满分 30 无折扣
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.025, -0.06, self.cfg)[0], 30.0)
        # 方向冲突：FM 系数为正、多空收益为负 -> ×0.5
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.025, 0.08, self.cfg)[0], 15.0)
        # 经济显著性：|收益| 0.2%/月 < 0.3% -> ×0.8
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.002, -0.06, self.cfg)[0], 24.0)
        # 两个折扣叠乘 ×0.4
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.002, 0.08, self.cfg)[0], 12.0)
        # 分档边界：恰好 p=0.05 落入 <0.10 档（24 -> 18）
        self.assertAlmostEqual(scoring.ps_score(0.05, -0.025, -0.06, self.cfg)[0], 18.0)
        # 无 PS 记录得 0
        score, detail = scoring.ps_score(None, None, -0.06, self.cfg)
        self.assertEqual(score, 0.0)
        self.assertIn("无PS记录", detail["代入"])

    def test_r2_quality(self):
        pool = pd.Series([0.20, 0.24, 0.28, 0.32])
        fam_pool = pd.Series([0.22, 0.26, 0.30])
        # r2=0.28 在 pool 中分位 (2 + 0.5)/4 = 0.625；族 0.26 在 fam_pool 中分位 0.5
        score, detail = scoring.r2_quality_score(0.28, pool, 0.26, fam_pool, self.cfg)
        self.assertAlmostEqual(score, 0.625 * 12 + 0.5 * 8)
        self.assertEqual(detail["得分"], score)

    def test_collinearity_penalty(self):
        # 1 组非核心风险对、5 个参数组合中标记 3 次 -> -2 × 0.6 = -1.2
        diag = pd.DataFrame([
            {"kind": "corr", "var_1": "Ctrl_a", "var_2": "as_b", "n_flagged": 3, "involves_core": False},
        ])
        score, _ = scoring.collinearity_penalty(diag, 5, self.cfg)
        self.assertAlmostEqual(score, -1.2)
        # 含核心变量的对 -5；持续性超过 1 封顶；corr 合计不低于 -8
        diag2 = pd.DataFrame([
            {"kind": "corr", "var_1": "FAC_rank_vol", "var_2": "Ctrl_a", "n_flagged": 9, "involves_core": True},
            {"kind": "corr", "var_1": "Ctrl_a", "var_2": "as_b", "n_flagged": 5, "involves_core": False},
            {"kind": "corr", "var_1": "Ctrl_c", "var_2": "as_d", "n_flagged": 5, "involves_core": False},
        ])
        score2, _ = scoring.collinearity_penalty(diag2, 5, self.cfg)
        self.assertAlmostEqual(score2, -8.0)  # -5 + -2 + -2 = -9 -> 封顶 -8
        # VIF：核心变量自身超标 -8，非核心 -4，合计封顶 -12
        diag3 = pd.DataFrame([
            {"kind": "vif", "var_1": "FAC_rank_vol", "var_2": None, "n_flagged": 5, "involves_core": True},
            {"kind": "vif", "var_1": "Ctrl_a", "var_2": None, "n_flagged": 5, "involves_core": False},
            {"kind": "vif", "var_1": "Ctrl_b", "var_2": None, "n_flagged": 5, "involves_core": False},
        ])
        score3, _ = scoring.collinearity_penalty(diag3, 5, self.cfg)
        self.assertAlmostEqual(score3, -12.0)  # -8 + -4 + -4 = -16 -> 封顶 -12
        # 无风险 -> 0
        empty = pd.DataFrame(columns=["kind", "var_1", "var_2", "n_flagged", "involves_core"])
        self.assertEqual(scoring.collinearity_penalty(empty, 5, self.cfg)[0], 0.0)


def _toy_tables():
    """构造两个族（挑战者/守擂者）各两个参数组合的完整四表，用于汇总测试。"""
    coverage = pd.DataFrame({
        "batch": ["b_001"] * 4,
        "model": ["fm_baseline_bottom33", "fm_baseline_bottom33",
                  "fm_baseline_indvol_bottom33", "fm_baseline_indvol_bottom33"],
        "param": ["m3_n6_pairwise1", "m6_n6_pairwise1"] * 2,
        "state": [""] * 4,
        "param_key": ["m3_n6", "m6_n6"] * 2,
        "m": [3, 6] * 2, "n": [6, 6] * 2,
        "n_months": [65, 63, 62, 61],
        "avg_funds": [108.0, 101.0, 90.0, 88.0],
        "n_obs": [7038.0, 6390.0, 5580.0, 5368.0],
        "avg_r2": [0.27, 0.24, 0.30, 0.29],
        "avg_adj_r2": [0.21, 0.18, 0.24, 0.23],
    })
    fm = coverage[["batch", "model", "param", "state", "param_key", "m", "n"]].copy()
    fm["variable"] = "FAC_rank_vol"
    fm["coef"] = [-0.09, -0.01, -0.12, -0.10]
    fm["t_stat"] = [-3.60, -0.16, -3.80, -2.20]
    fm["stars"] = [3, 0, 3, 2]
    ps = fm[["batch", "model", "variable", "param", "state", "param_key", "m", "n"]].copy()
    ps["long_short"] = [-0.016, -0.005, -0.020, -0.015]
    ps["t_stat"] = [-2.03, -0.68, -2.60, -1.90]
    ps["p_value"] = [0.050, 0.504, 0.012, 0.065]
    diag = pd.DataFrame(columns=["batch", "model", "kind", "var_1", "var_2", "n_flagged", "involves_core"])
    return {"coverage": coverage, "fm": fm, "ps": ps, "diag": diag}


class TestScoreAll(unittest.TestCase):
    """汇总打分与擂台徽章。"""

    def setUp(self):
        self.cfg = dict(config.DEFAULT_CONFIG)
        self.tables = _toy_tables()

    def test_score_all_shape_and_total(self):
        scores = scoring.score_all(self.tables, self.cfg)
        # 4 个候选各一行，总分 = 四维得分 + 两类扣分之和
        self.assertEqual(len(scores), 4)
        row = scores[(scores["model"] == "fm_baseline_bottom33") & (scores["param_key"] == "m3_n6")].iloc[0]
        expected = (
            row["fm_score"] + row["neighbor_score"] + row["ps_sig_score"]
            + row["r2_score"] + row["sample_pen"] + row["collin_pen"]
        )
        self.assertAlmostEqual(row["total"], expected)
        # 明细列表覆盖全部六个组成部分
        self.assertEqual(len(row["明细"]), 6)
        # 样本层识别正确
        self.assertTrue((scores["layer"] == "bottom33").all())

    def test_attach_badges(self):
        scores = scoring.score_all(self.tables, self.cfg)
        badged = scoring.attach_badges(scores, config.BASELINES, self.cfg)
        # 基准行被标出且自己不参与打徽章
        base_row = badged[(badged["model"] == "fm_baseline_bottom33") & (badged["param_key"] == "m3_n6")].iloc[0]
        self.assertTrue(base_row["is_baseline"])
        self.assertEqual(base_row["badge"], "")
        # 挑战者 m3_n6：FM 更显著、PS 更显著、R² 更高 -> 总分应高于基准，拿到徽章
        ch = badged[(badged["model"] == "fm_baseline_indvol_bottom33") & (badged["param_key"] == "m3_n6")].iloc[0]
        self.assertGreater(ch["total"], base_row["total"])
        self.assertIn(ch["badge"], ("可能可替代基准", "优先关注"))
        self.assertAlmostEqual(ch["vs_baseline"], ch["total"] - base_row["total"])


if __name__ == "__main__":
    unittest.main()
