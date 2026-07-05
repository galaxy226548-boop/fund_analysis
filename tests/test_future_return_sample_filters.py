"""检查普通未来收益模型不会跨样本截止日或基金经理 regime。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
PIPELINE_PATH = PROJECT_ROOT / "B_factors" / "scripts" / "run_factor_pipeline.py"
REPRESENTATIVE_PATH = (
    PROJECT_ROOT
    / "D_analysis"
    / "scripts"
    / "run_representative_window_horizon_tests.py"
)


def load_module(name: str, path: Path):
    """按文件路径加载模块，避免测试依赖当前工作目录。"""

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载模块：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


registry = load_module("future_filter_registry_test", REGISTRY_PATH)
pipeline = load_module("future_filter_pipeline_test", PIPELINE_PATH)
representative = load_module("future_filter_representative_test", REPRESENTATIVE_PATH)


class FutureReturnSampleFilterTests(unittest.TestCase):
    """验证固定期限 Y 与筛选期限一致，特殊市态 Y 不受误伤。"""

    def test_all_plain_future_return_models_use_matching_two_layer_filters(self) -> None:
        """所有普通 Y 都应同时检查样本截止日和持有期连续可用性。"""

        for key in registry.list_regression_keys():
            config = registry.get_regression_config(key)
            y_column = str(config["y"])
            match = registry.PLAIN_FUTURE_RETURN_PATTERN.fullmatch(y_column)
            if match is None:
                continue

            horizon = int(match.group(1))
            expected = {
                f"is_insample_future_ret_{horizon}m": 1,
                f"match_is_sample_future_ret_{horizon}m": 1,
            }
            self.assertEqual(config["sample_filters"], expected, msg=key)
            for column in expected:
                self.assertIn(column, config["sample_flag_columns"], msg=key)

    def test_twelve_month_heatmap_model_no_longer_inherits_six_month_flags(self) -> None:
        """12m 派生模型必须使用 12m 的两层筛选。"""

        config = registry.get_regression_config("fm_heatmap_top33_y12m")
        self.assertEqual(
            config["sample_filters"],
            {
                "is_insample_future_ret_12m": 1,
                "match_is_sample_future_ret_12m": 1,
            },
        )
        self.assertNotIn("is_insample_future_ret_6m", config["sample_flag_columns"])

    def test_market_state_matched_returns_keep_their_special_filters(self) -> None:
        """状态匹配 Y 已逐目标月校验，不应套用普通 future match 列。"""

        config = registry.get_regression_config("fm_ymatch_hs300_hs300up")
        self.assertEqual(
            config["sample_filters"],
            {"is_insample_future_ret_6m_hs300up": 1},
        )

    def test_pipeline_keeps_every_base_sample_filter_column(self) -> None:
        """即使调用者未同步 sample_flag_columns，基础筛选列也不能被删掉。"""

        config = {
            "id_columns": ["ifind_code", "month_date"],
            "sample_flag_columns": ["is_insample_future_ret_6m"],
            "sample_filters": {
                "is_insample_future_ret_6m": 1,
                "match_is_sample_future_ret_6m": 1,
            },
            "y_columns": ["future_ret_6m"],
            "factor_columns": ["FAC"],
            "control_columns": ["CtrlVol"],
            "extra_columns": [],
            "factor_sample_filters": {},
        }
        columns = pipeline.keep_columns(config)
        self.assertIn("match_is_sample_future_ret_6m", columns)
        self.assertEqual(len(columns), len(set(columns)))

    def test_representative_horizon_filters_are_horizon_specific(self) -> None:
        """短期限模型不能被错误要求未来 12 个月持续在样本内。"""

        for horizon in (1, 3, 6, 12):
            self.assertEqual(
                representative.get_future_return_sample_filters(
                    f"future_ret_{horizon}m"
                ),
                {
                    f"is_insample_future_ret_{horizon}m": 1,
                    f"match_is_sample_future_ret_{horizon}m": 1,
                },
            )


if __name__ == "__main__":
    unittest.main()
