"""验证长期动量和波动率控制变量使用统一的信息窗口。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "A_data" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import Config


def load_controls_module():
    """按文件路径加载以数字开头的控制变量脚本。"""
    path = SCRIPT_DIR / "3_panel_base_controls_variable.py"
    spec = importlib.util.spec_from_file_location("controls_window_test", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载控制变量脚本：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


controls_module = load_controls_module()


class ControlReturnWindowTests(unittest.TestCase):
    """用非恒定月收益区分是否错误包含或排除了当前月。"""

    def test_ltm_excludes_current_month_and_volatility_includes_it(self) -> None:
        dates = pd.date_range("2023-01-31", periods=15, freq="ME")
        monthly_returns = np.linspace(0.001, 0.015, len(dates) - 1)
        nav = [1.0]
        for monthly_return in monthly_returns:
            nav.append(nav[-1] * (1 + monthly_return))

        data = pd.DataFrame(
            {
                Config.COLUMN_IFIND_CODE: "TEST",
                Config.COLUMN_INVESTMENT_TYPE: "测试基金",
                Config.COLUMN_MONTH_DATE: dates,
                Config.COLUMN_NAV: nav,
            }
        )
        data["past_ret_12m_1"] = (
            data[Config.COLUMN_NAV]
            / data[Config.COLUMN_NAV].shift(12)
            - 1
        )

        result = controls_module.add_return_control_columns(data)
        row = len(result) - 1

        # 过去 12 个月剔除最近 1 个月，等价于 11 个单月收益
        # R_{t-11}...R_{t-1} 的复合收益，NAV 端点为 t-12 和 t-1。
        expected_ltm = nav[row - 1] / nav[row - 12] - 1
        self.assertAlmostEqual(result.loc[row, "CtrlRetLTM"], expected_ltm)

        # 波动率使用截至 t 的 12 个单月收益 R_{t-11}...R_t，包含当前月。
        expected_volatility = np.std(monthly_returns[-12:], ddof=1)
        self.assertAlmostEqual(result.loc[row, "CtrlVol"], expected_volatility)


if __name__ == "__main__":
    unittest.main()
