"""验证统一 FDR 脚本生成 FAC 热力图时的网格和写文件规则。"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "D_analysis" / "scripts"
APPLY_FDR_PATH = SCRIPT_DIR / "apply_fdr.py"


def load_module():
    """从脚本路径加载模块，并确保同目录下的 registry 可以被导入。"""
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "apply_fdr_heatmap_test_module", APPLY_FDR_PATH
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载模块：{APPLY_FDR_PATH}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPT_DIR))


apply_fdr = load_module()


def make_frame() -> pd.DataFrame:
    """构造一个很小但同时含显著、非显著和缺失值的 FAC 长表。"""
    return pd.DataFrame(
        {
            "variable": [
                "FAC_rank_vol_m1_n2_pairwise1",
                "FAC_rank_vol_m2_n3_pairwise1",
                "FAC_rank_vol_m12_n12_pairwise1",
            ],
            "t_stat": [np.nan, -2.5, 0.4],
            "p_value": [np.nan, 0.02, 0.70],
            "q_value": [np.nan, 0.01, 0.80],
        }
    )


class ApplyFdrHeatmapTests(unittest.TestCase):
    def test_parse_fac_heatmap_coordinates_is_strict(self) -> None:
        self.assertEqual(
            apply_fdr.parse_fac_heatmap_coordinates(
                "FAC_rank_vol_m3_n11_pairwise1"
            ),
            (3, 11),
        )
        self.assertIsNone(
            apply_fdr.parse_fac_heatmap_coordinates(
                "FAC_rank_vol_m3_n11_pairwise2"
            )
        )
        self.assertIsNone(
            apply_fdr.parse_fac_heatmap_coordinates(
                "prefix_FAC_rank_vol_m3_n11_pairwise1"
            )
        )

    def test_build_matrices_preserves_12_by_11_coordinates(self) -> None:
        t_matrix, q_matrix = apply_fdr.build_fac_heatmap_matrices(make_frame())
        self.assertEqual(t_matrix.shape, (12, 11))
        self.assertEqual(q_matrix.shape, (12, 11))
        self.assertAlmostEqual(float(t_matrix.loc[2, 3]), -2.5)
        self.assertAlmostEqual(float(q_matrix.loc[2, 3]), 0.01)
        self.assertAlmostEqual(float(t_matrix.loc[12, 12]), 0.4)
        self.assertTrue(np.isnan(t_matrix.loc[1, 2]))

    def test_n1_coordinate_is_rejected(self) -> None:
        frame = make_frame()
        frame.loc[0, "variable"] = "FAC_rank_vol_m1_n1_pairwise1"
        with self.assertRaisesRegex(ValueError, "n=2..12"):
            apply_fdr.build_fac_heatmap_matrices(frame)

    def test_duplicate_coordinates_raise_clear_error(self) -> None:
        frame = make_frame()
        frame = pd.concat([frame, frame.iloc[[1]]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "同一个 \\(m,n\\) 出现多行"):
            apply_fdr.build_fac_heatmap_matrices(frame)

    def test_writer_creates_generic_heatmap_and_skips_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_dir = Path(temporary_dir)
            ordinary = apply_fdr.write_fdr_heatmap(
                make_frame(),
                family_id="hitrate_nonoverlap_primary",
                q_threshold=0.05,
                output_dir=output_dir,
                dry_run=False,
                annotate=False,
            )
            dry_run = apply_fdr.write_fdr_heatmap(
                make_frame(),
                family_id="fac_heatmap__fm_heatmap_full",
                q_threshold=0.05,
                output_dir=output_dir,
                dry_run=True,
                annotate=False,
            )
            self.assertEqual(ordinary, output_dir / apply_fdr.FDR_HEATMAP_FILENAME)
            assert ordinary is not None
            self.assertTrue(ordinary.exists())
            self.assertIsNone(dry_run)

    def test_standard_fac_20_uses_five_by_four_grid(self) -> None:
        rows = []
        for y_horizon in apply_fdr.STANDARD_FAC_Y_HORIZONS:
            for window in apply_fdr.STANDARD_FAC_WINDOWS:
                rows.append(
                    {
                        "source_label": f"fm_baseline_up__{y_horizon}",
                        "variable": f"FAC_rank_vol_{window}_pairwise1",
                        "t_stat": -2.0,
                        "q_value": 0.02,
                    }
                )
        t_matrix, q_matrix = apply_fdr.build_standard_fac_20_matrices(
            pd.DataFrame(rows)
        )
        self.assertEqual(t_matrix.shape, (5, 4))
        self.assertEqual(q_matrix.shape, (5, 4))
        self.assertEqual(list(t_matrix.index), list(apply_fdr.STANDARD_FAC_WINDOWS))
        self.assertEqual(
            list(t_matrix.columns), list(apply_fdr.STANDARD_FAC_Y_HORIZONS)
        )

    def test_writer_creates_png_for_heatmap_family(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_dir = Path(temporary_dir)
            output_path = apply_fdr.write_fdr_heatmap(
                make_frame(),
                family_id="fac_heatmap__fm_heatmap_full",
                q_threshold=0.05,
                output_dir=output_dir,
                dry_run=False,
                annotate=True,
            )
            self.assertEqual(
                output_path, output_dir / apply_fdr.FAC_HEATMAP_FILENAME
            )
            assert output_path is not None
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
