"""兼容旧路径的回归注册表入口。

新的统一配置文件位于 ``D_analysis/config/regression_registry.py``。这个文件只负责
转发旧导入路径，避免历史脚本或笔记中引用 ``D_analysis/scripts/regression_registry.py``
时立刻失效。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"


def _load_registry_module():
    """按文件路径加载新的配置模块，避免依赖包导入路径。"""

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_registry_module = _load_registry_module()

REGISTRY = _registry_module.REGISTRY
DEFAULT_REGRESSION_KEY = _registry_module.DEFAULT_REGRESSION_KEY
list_regression_keys = _registry_module.list_regression_keys
get_regression_config = _registry_module.get_regression_config
