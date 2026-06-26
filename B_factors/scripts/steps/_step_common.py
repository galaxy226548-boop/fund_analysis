"""B_factors 分步 CLI 共用的小工具。

这些函数只负责读取当前项目的 fm_baseline 配置，并把配置整理成各个 step
需要的列清单。暂时不做配置驱动 runner，是为了先验证“拆成小脚本”不会改变
原来的处理口径。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_ROOT = PROJECT_ROOT / "B_factors" / "scripts"
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"

if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))


def load_regression_config() -> dict[str, Any]:
    """读取 fm_baseline 配置，保证分步脚本和旧大脚本使用同一套口径。"""

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config("fm_baseline")


def project_path(relative_path: str) -> Path:
    """把 registry 里的项目相对路径转成绝对路径。"""

    return PROJECT_ROOT / relative_path


def keep_columns(config: dict[str, Any]) -> list[str]:
    """按旧大脚本的顺序整理最终保留列。"""

    base_columns = (
        list(config["id_columns"])
        + list(config["sample_flag_columns"])
        + [str(config["y"])]
        + list(config["factors"])
        + list(config["controls"])
    )
    # factor_sample_filters 的列不一定是回归变量，但后续回归会用它们逐 factor 筛选样本。
    factor_filter_columns = [
        column
        for filters in dict(config.get("factor_sample_filters", {})).values()
        for column in filters
    ]
    return base_columns + [
        column for column in dict.fromkeys(factor_filter_columns) if column not in base_columns
    ]


def factor_filter_columns(config: dict[str, Any]) -> list[str]:
    """列出所有 per-factor 样本筛选列。"""
    # 单独提供这个函数，是为了 Step 01 做 required_columns 检查时也能复用同一口径。
    columns = [
        column
        for filters in dict(config.get("factor_sample_filters", {})).values()
        for column in filters
    ]
    return list(dict.fromkeys(columns))


def winsorize_settings(config: dict[str, Any]) -> dict[str, Any]:
    """取出 winsorize 相关设置，并做必要的类型转换。"""

    winsorize_config = config["winsorize"]
    return {
        "group_column": str(winsorize_config["group_column"]),
        "lower_quantile": float(winsorize_config["lower_quantile"]),
        "upper_quantile": float(winsorize_config["upper_quantile"]),
        "columns": list(winsorize_config["columns"]),
    }
