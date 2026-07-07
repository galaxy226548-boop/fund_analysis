"""data_loader 的单元测试：块切分、单元格解析、批次去重。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = PROJECT_ROOT / "I_Visualization" / "fm_comparison"
sys.path.insert(0, str(PKG_DIR))

import data_loader  # noqa: E402


class TestBasicParsers(unittest.TestCase):
    """基础解析函数：不接触真实 Excel，全部用合成数据。"""

    def test_split_header_blocks(self):
        # 模拟一个 sheet 里两个批次块、表头行重复出现的结构
        raw = pd.DataFrame([
            ["来源批次", "模型目录", "月份数"],
            ["b_001", "m_a", 60],
            ["b_001", "m_b", 55],
            ["来源批次", "模型目录", "月份数"],
            ["b_002", "m_c", 48],
        ])
        blocks = data_loader.split_header_blocks(raw)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(list(blocks[0].columns), ["来源批次", "模型目录", "月份数"])
        self.assertEqual(len(blocks[0]), 2)
        self.assertEqual(blocks[1].iloc[0]["模型目录"], "m_c")

    def test_parse_coef_cell(self):
        # 标准格式：系数 + 星号 + 换行 + t 值
        self.assertEqual(data_loader.parse_coef_cell("-0.07*\n(t=-1.73)"), (-0.07, -1.73, 1))
        self.assertEqual(data_loader.parse_coef_cell("0.08***\n(t=2.74)"), (0.08, 2.74, 3))
        self.assertEqual(data_loader.parse_coef_cell("0.04\n(t=1.31)"), (0.04, 1.31, 0))
        # 异常输入返回 None
        self.assertIsNone(data_loader.parse_coef_cell(float("nan")))
        self.assertIsNone(data_loader.parse_coef_cell(None))
        self.assertIsNone(data_loader.parse_coef_cell("不适用"))

    def test_parse_param(self):
        # 无市态前缀：state 为空字符串
        self.assertEqual(data_loader.parse_param("m3_n6_pairwise1"), ("", 3, 6, "m3_n6"))
        self.assertEqual(data_loader.parse_param("m12_n6_pairwise1"), ("", 12, 6, "m12_n6"))
        # 带市态状态前缀：growth/value、highvol/lowvol、hs300up/hs300down、large/small
        # 必须保留，否则不同市态的结果会被压成同一格造成重复合并
        self.assertEqual(data_loader.parse_param("growth_m3_n3_pairwise1"), ("growth", 3, 3, "growth_m3_n3"))
        self.assertEqual(data_loader.parse_param("hs300up_m6_n12_pairwise1"), ("hs300up", 6, 12, "hs300up_m6_n12"))
        self.assertIsNone(data_loader.parse_param("模型参数"))

    def test_batch_run_no(self):
        self.assertEqual(data_loader.batch_run_no("6_市态条件一致性_回归系数显著性_004"), 4)
        self.assertEqual(data_loader.batch_run_no("无尾号批次"), -1)

    def test_keep_latest_batch(self):
        # 同一模型出现在 001 与 004 两个批次时，只保留 004 的行
        df = pd.DataFrame({
            "batch": ["x_001", "x_001", "x_004", "y_002"],
            "model": ["m_a", "m_b", "m_a", "m_c"],
            "val": [1, 2, 3, 4],
        })
        kept = data_loader.keep_latest_batch(df)
        self.assertEqual(kept[kept["model"] == "m_a"]["val"].tolist(), [3])
        # 其余模型不受影响
        self.assertEqual(sorted(kept["model"].tolist()), ["m_a", "m_b", "m_c"])


if __name__ == "__main__":
    unittest.main()
