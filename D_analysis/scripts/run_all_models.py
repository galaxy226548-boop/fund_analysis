"""批量运行 regression registry 中的全部正式模型。

默认对每个模型依次执行 ``preprocess`` 和 ``regression``，并在单个模型失败后
继续运行其余模型。模型列表直接读取 regression_registry，因此新增模型后无需
手工更新本脚本；``bm33`` 等兼容别名不会出现在正式列表中。

常用方式：

    # 先检查将运行的全部命令，不实际计算
    .venv/bin/python D_analysis/scripts/run_all_models.py --dry-run

    # 正式运行全部模型
    .venv/bin/python D_analysis/scripts/run_all_models.py

    # 只运行指定模型，支持空格或逗号分隔
    .venv/bin/python D_analysis/scripts/run_all_models.py \
        --models fm_baseline,fm_baseline_interaction fm_heatmap_full

    # 只运行名称中包含 heatmap 的模型
    .venv/bin/python D_analysis/scripts/run_all_models.py --include '*heatmap*'

    # 额外运行相关性检查；某模型没有该步骤时会自动跳过该步骤
    .venv/bin/python D_analysis/scripts/run_all_models.py \
        --steps preprocess correlation_check regression
"""

from __future__ import annotations

import argparse
import fnmatch
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
ENGINE_PATH = PROJECT_ROOT / "D_analysis" / "scripts" / "0_regression_engine.py"
RESULT_SORTING_PATH = PROJECT_ROOT / "D_analysis" / "scripts" / "result_sorting.py"
DEFAULT_STEPS = ("preprocess", "regression")
DEFAULT_LOG_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "all_models_run_logs"
)


def load_registry_module():
    """从真实路径加载 registry，避免依赖 Python package 安装状态。"""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置：{REGISTRY_PATH}")
    spec = importlib.util.spec_from_file_location("all_models_registry", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置：{REGISTRY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def choose_python() -> Path:
    """优先使用项目虚拟环境，保证 pandas/statsmodels 等依赖版本一致。"""
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    return venv_python if venv_python.exists() else Path(sys.executable)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量运行全部基金一致性回归模型。")
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="只运行指定模型；支持空格或逗号分隔。默认运行全部正式 registry key。",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="只保留匹配 glob 的模型，可重复传入，例如 --include '*heatmap*'。",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="排除匹配 glob 的模型，可重复传入。",
    )
    parser.add_argument(
        "--steps",
        nargs="+",
        default=list(DEFAULT_STEPS),
        help="希望运行的步骤；模型没有某一步时自动跳过。默认 preprocess regression。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印命令并调用 engine 的 dry-run，不做实际计算。",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="遇到第一个失败模型就停止；默认记录失败并继续运行其他模型。",
    )
    parser.add_argument(
        "--skip-output-check",
        action="store_true",
        help="让 engine 跳过每一步的关键输出存在性检查。",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=DEFAULT_LOG_DIR,
        help="正式运行的 JSON 汇总日志目录。",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出筛选后的模型及实际步骤，不运行。",
    )
    parser.add_argument(
        "--skip-result-sorting",
        action="store_true",
        help=(
            "正式运行结束后不自动运行 result_sorting.py 刷新 "
            "fama_macbeth_results汇总.xlsx 与 portfolio_sorting汇总.xlsx。"
        ),
    )
    return parser.parse_args()


def normalize_requested_models(raw_models: list[str] | None) -> list[str] | None:
    """支持 ``a b`` 和 ``a,b`` 两种模型输入方式，并保持用户顺序。"""
    if raw_models is None:
        return None
    models: list[str] = []
    for item in raw_models:
        models.extend(part.strip() for part in item.split(",") if part.strip())
    return list(dict.fromkeys(models))


def select_models(registry_module, args: argparse.Namespace) -> list[str]:
    """从正式 key 中应用显式列表、include 和 exclude 筛选。"""
    available = registry_module.list_regression_keys()
    requested = normalize_requested_models(args.models)
    if requested is None:
        selected = list(available)
    else:
        unknown = [model for model in requested if model not in available]
        if unknown:
            raise ValueError(f"以下模型不是正式 registry key：{unknown}")
        selected = requested

    if args.include:
        selected = [
            model
            for model in selected
            if any(fnmatch.fnmatch(model, pattern) for pattern in args.include)
        ]
    if args.exclude:
        selected = [
            model
            for model in selected
            if not any(fnmatch.fnmatch(model, pattern) for pattern in args.exclude)
        ]
    if not selected:
        raise ValueError("筛选后没有需要运行的模型。")
    return selected


def available_pipeline_steps(config: dict[str, object]) -> list[str]:
    """读取模型实际声明的步骤，顺序以 registry 为准。"""
    pipeline = config.get("pipeline")
    if not isinstance(pipeline, list) or not pipeline:
        raise ValueError("模型配置缺少非空 pipeline。")
    return [str(step["name"]) for step in pipeline]


def select_steps_for_model(
    config: dict[str, object], requested_steps: list[str]
) -> list[str]:
    """只保留模型真正支持的步骤，避免可选步骤导致整批任务中断。"""
    available = available_pipeline_steps(config)
    requested_set = set(requested_steps)
    return [step for step in available if step in requested_set]


def build_engine_command(
    python_executable: Path,
    model: str,
    steps: list[str],
    *,
    dry_run: bool,
    skip_output_check: bool,
) -> list[str]:
    command = [
        str(python_executable),
        str(ENGINE_PATH),
        "--model",
        model,
        "--steps",
        *steps,
    ]
    if dry_run:
        command.append("--dry-run")
    if skip_output_check:
        command.append("--skip-output-check")
    return command


def print_model_list(
    registry_module, models: list[str], requested_steps: list[str]
) -> None:
    print(f"模型数量：{len(models)}")
    for index, model in enumerate(models, start=1):
        config = registry_module.get_regression_config(model)
        steps = select_steps_for_model(config, requested_steps)
        print(f"{index:>3}. {model}: {', '.join(steps) if steps else '无匹配步骤'}")


def write_run_summary(log_dir: Path, summary: dict[str, object]) -> Path:
    """正式运行结束后保存机器可读日志，便于定位失败模型后续补跑。"""
    target_dir = log_dir if log_dir.is_absolute() else PROJECT_ROOT / log_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(summary["run_id"])
    path = target_dir / f"{run_id}.json"
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def refresh_result_summaries(python_executable: Path) -> bool:
    """正式运行后刷新两个汇总工作簿，让 Excel 结果与最新回归输出保持同步。"""
    command = [str(python_executable), str(RESULT_SORTING_PATH)]
    print("\n" + "=" * 88)
    print("刷新汇总工作簿（result_sorting.py）")
    print("命令：" + " ".join(command))
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        print(
            "警告：result_sorting.py 刷新失败（常见原因：Excel 正打开汇总文件导致无法写入）。"
            "回归结果本身不受影响，关闭 Excel 后可手动重跑该脚本补齐。",
            file=sys.stderr,
        )
    return result.returncode == 0


def main() -> None:
    args = parse_args()
    if not ENGINE_PATH.exists():
        raise FileNotFoundError(f"找不到回归 engine：{ENGINE_PATH}")

    registry_module = load_registry_module()
    models = select_models(registry_module, args)
    if args.list:
        print_model_list(registry_module, models, args.steps)
        return

    python_executable = choose_python()
    print(f"项目根目录：{PROJECT_ROOT}")
    print(f"模型总数：{len(models)}")
    print(f"请求步骤：{', '.join(args.steps)}")
    print(f"Python：{python_executable}")
    if args.dry_run:
        print("当前为 dry-run，不会计算或覆盖结果。")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    started_at = datetime.now().isoformat(timespec="seconds")
    records: list[dict[str, object]] = []

    for index, model in enumerate(models, start=1):
        config = registry_module.get_regression_config(model)
        steps = select_steps_for_model(config, args.steps)
        print("\n" + "#" * 88)
        print(f"[{index}/{len(models)}] 模型：{model}")
        if not steps:
            print("跳过：该模型没有请求的步骤。")
            records.append({"model": model, "status": "skipped", "steps": []})
            continue

        command = build_engine_command(
            python_executable,
            model,
            steps,
            dry_run=args.dry_run,
            skip_output_check=args.skip_output_check,
        )
        print("命令：" + " ".join(command))
        started = time.monotonic()
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        elapsed = round(time.monotonic() - started, 3)
        status = "success" if result.returncode == 0 else "failed"
        records.append(
            {
                "model": model,
                "status": status,
                "returncode": int(result.returncode),
                "steps": steps,
                "elapsed_seconds": elapsed,
                "command": command,
            }
        )
        print(f"状态：{status}；耗时：{elapsed:.1f}s")
        if result.returncode != 0 and args.stop_on_error:
            print("--stop-on-error 已启用，停止后续模型。")
            break

    succeeded = [record["model"] for record in records if record["status"] == "success"]
    failed = [record["model"] for record in records if record["status"] == "failed"]
    skipped = [record["model"] for record in records if record["status"] == "skipped"]
    summary: dict[str, object] = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "dry_run": bool(args.dry_run),
        "requested_steps": list(args.steps),
        "selected_model_count": len(models),
        "attempted_model_count": len(records),
        "success_count": len(succeeded),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "succeeded_models": succeeded,
        "failed_models": failed,
        "skipped_models": skipped,
        "models": records,
    }

    print("\n" + "=" * 88)
    print("全部模型运行汇总")
    print(f"成功：{len(succeeded)}；失败：{len(failed)}；跳过：{len(skipped)}")
    if failed:
        print("失败模型：" + ", ".join(str(model) for model in failed))

    if not args.dry_run:
        summary_path = write_run_summary(args.log_dir, summary)
        print(f"运行日志：{summary_path}")
        # 只要有模型真正跑成功，结果目录就变了，两个汇总工作簿需要同步刷新。
        if succeeded and not args.skip_result_sorting:
            refresh_result_summaries(python_executable)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n批量运行失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from None
