"""批量运行热力图回归模型的 preprocess 和 regression 步骤。

本脚本只负责调度以下热力图专用模型：

    fm_heatmap_up
    fm_heatmap_down
    fm_heatmap_top33
    fm_heatmap_mid33
    fm_heatmap_bm33

它复用 D_analysis/scripts/0_regression_engine.py，并固定只运行
``preprocess`` 和 ``regression`` 两个步骤，避免误触发 portfolio_sorting
或描述性统计。正式运行前会检查热力图专用 panel parquet 是否存在。
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
ENGINE_PATH = PROJECT_ROOT / "D_analysis" / "scripts" / "0_regression_engine.py"
DEFAULT_MODELS = (
    "fm_heatmap_up",
    "fm_heatmap_down",
    "fm_heatmap_top33",
    "fm_heatmap_mid33",
    "fm_heatmap_bm33",
)
RUN_STEPS = ("preprocess", "regression")


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="批量运行热力图回归模型的 preprocess 和 regression。"
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=list(DEFAULT_MODELS),
        help=(
            "要运行的模型 key，可空格分隔，也可用逗号分隔；"
            "默认依次运行全部 5 个热力图模型。"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印每个模型将调用的 engine 命令，不实际运行 preprocess/regression。",
    )
    parser.add_argument(
        "--skip-output-check",
        action="store_true",
        help="传递给 0_regression_engine.py，跳过步骤结束后的关键输出检查。",
    )
    return parser.parse_args()


def choose_python() -> Path:
    """优先使用项目虚拟环境中的 Python。"""
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def load_registry_module():
    """按文件路径加载 registry，以便读取模型配置和输入路径。"""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolve_project_path(path_value: str | Path) -> Path:
    """把 registry 中的项目相对路径转换为绝对路径。"""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def normalize_models(raw_models: list[str]) -> list[str]:
    """整理 --models 输入，支持空格和逗号两种写法。"""
    models: list[str] = []
    for item in raw_models:
        models.extend(part.strip() for part in item.split(",") if part.strip())
    return list(dict.fromkeys(models))


def validate_models(models: list[str]) -> None:
    """只允许本脚本调度热力图专用模型，避免误跑其他实验。"""
    invalid_models = [model for model in models if model not in DEFAULT_MODELS]
    if invalid_models:
        allowed = ", ".join(DEFAULT_MODELS)
        raise ValueError(
            f"run_heatmap_regressions.py 只支持热力图模型：{allowed}；"
            f"收到不支持的模型：{invalid_models}"
        )


def check_heatmap_panel_exists(registry_module, models: list[str]) -> None:
    """运行前检查每个模型登记的热力图 panel 输入是否存在。

    五个模型目前共享同一个输入文件，但这里仍按模型配置读取路径。这样将来如果
    某个模型改用不同输入，检查逻辑也不会静默漏掉。
    """
    missing: list[tuple[str, Path]] = []
    seen_paths: set[Path] = set()
    for model in models:
        config = registry_module.get_regression_config(model)
        input_path = resolve_project_path(str(config["preprocess_input_path"]))
        if input_path in seen_paths:
            continue
        seen_paths.add(input_path)
        if not input_path.exists():
            missing.append((model, input_path))

    if missing:
        details = "\n".join(f"- {model}: {path}" for model, path in missing)
        raise FileNotFoundError(
            "热力图 panel parquet 不存在，请先生成并追加 grouping factors：\n"
            f"{details}"
        )


def build_engine_command(
    python_executable: Path,
    model: str,
    *,
    dry_run: bool,
    skip_output_check: bool,
) -> list[str]:
    """生成调用 0_regression_engine.py 的命令。"""
    command = [
        str(python_executable),
        str(ENGINE_PATH),
        "--model",
        model,
        "--steps",
        *RUN_STEPS,
    ]
    if dry_run:
        command.append("--dry-run")
    if skip_output_check:
        command.append("--skip-output-check")
    return command


def format_command(command: list[str]) -> str:
    """把命令列表格式化成方便阅读的一行。"""
    return " ".join(command)


def run_model(
    model: str,
    python_executable: Path,
    *,
    dry_run: bool,
    skip_output_check: bool,
) -> bool:
    """运行单个模型，并返回是否成功。"""
    command = build_engine_command(
        python_executable,
        model,
        dry_run=dry_run,
        skip_output_check=skip_output_check,
    )

    print("\n" + "=" * 80)
    print(f"开始模型：{model}")
    print(f"命令：{format_command(command)}")

    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode == 0:
        print(f"模型成功：{model}")
        return True

    print(f"模型失败：{model}；returncode={result.returncode}")
    return False


def main() -> None:
    """程序入口：校验输入 → 逐个运行 → 汇总状态。"""
    args = parse_args()
    models = normalize_models(args.models)
    validate_models(models)

    registry_module = load_registry_module()
    check_heatmap_panel_exists(registry_module, models)

    if not ENGINE_PATH.exists():
        raise FileNotFoundError(f"找不到回归 engine：{ENGINE_PATH}")

    python_executable = choose_python()
    print(f"项目根目录：{PROJECT_ROOT}")
    print(f"配置文件：{REGISTRY_PATH}")
    print(f"回归 engine：{ENGINE_PATH}")
    print(f"Python：{python_executable}")
    print(f"运行步骤：{', '.join(RUN_STEPS)}")
    print(f"运行模型：{', '.join(models)}")
    if args.dry_run:
        print("当前为 dry-run：只打印 engine 将执行的命令。")

    succeeded: list[str] = []
    failed: list[str] = []
    for model in models:
        if run_model(
            model,
            python_executable,
            dry_run=args.dry_run,
            skip_output_check=args.skip_output_check,
        ):
            succeeded.append(model)
        else:
            failed.append(model)

    print("\n" + "=" * 80)
    print("批量运行汇总")
    print(f"成功模型数：{len(succeeded)}")
    for model in succeeded:
        print(f"  成功：{model}")
    print(f"失败模型数：{len(failed)}")
    for model in failed:
        print(f"  失败：{model}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n运行前检查失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from None
