"""export 导出功能的单元测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = PROJECT_ROOT / "I_Visualization" / "fm_comparison"
sys.path.insert(0, str(PKG_DIR))

import config  # noqa: E402
import export  # noqa: E402


class TestExport(unittest.TestCase):
    """校验导出文件的 sheet 结构与内容。"""

    def test_export_ranking(self):
        # 最小 scores 表：两行候选 + 明细列表
        scores = pd.DataFrame({
            "model": ["m_a", "m_b"], "param_key": ["m3_n6", "m6_n6"],
            "layer": ["bottom33", "bottom33"], "total": [68.0, 40.0],
            "badge": ["优先关注", ""], "is_baseline": [False, True],
            "明细": [
                [{"名称": "FM显著性", "公式": "f", "代入": "x", "得分": 40.0}],
                [{"名称": "FM显著性", "公式": "f", "代入": "y", "得分": 24.0}],
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_ranking(scores, dict(config.DEFAULT_CONFIG), Path(tmp))
            self.assertTrue(path.exists())
            self.assertTrue(path.name.startswith("fm_ps_指标可行性排名_"))
            # 三个 sheet 齐全
            sheets = pd.ExcelFile(path).sheet_names
            self.assertEqual(sheets, ["排名总表", "打分明细", "权重快照"])
            # 排名总表按 total 降序且不含明细对象列
            rank = pd.read_excel(path, sheet_name="排名总表")
            self.assertEqual(rank.iloc[0]["model"], "m_a")
            self.assertNotIn("明细", rank.columns)
            # 打分明细逐行展开
            detail = pd.read_excel(path, sheet_name="打分明细")
            self.assertEqual(len(detail), 2)
            self.assertIn("公式", detail.columns)


if __name__ == "__main__":
    unittest.main()
