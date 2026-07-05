"""按统一注册表运行基金一致性回归流水线。

运行方式：

    .venv/bin/python D_analysis/scripts/0_regression_engine.py
    .venv/bin/python D_analysis/scripts/0_regression_engine.py --model fm_baseline
    .venv/bin/python D_analysis/scripts/0_regression_engine.py --steps preprocess regression
    .venv/bin/python D_analysis/scripts/0_regression_engine.py --dry-run

这个 engine 借鉴 ``A_data/scripts/0_engine.py`` 的组织方式，但这里不是根据文件
更新时间自动判断，而是根据 ``D_analysis/config/regression_registry.py`` 中登记的
模型流水线顺序执行。registry 负责描述“做什么”，engine 负责“按顺序跑起来”。
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"


def load_registry_module():
    """按文件路径加载 registry，避免要求 D_analysis 是 Python 包。"""

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


REGISTRY_MODULE = load_registry_module()


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""

    parser = argparse.ArgumentParser(description="运行基金一致性回归流水线。")
    parser.add_argument(
        "--model",
        default=REGISTRY_MODULE.DEFAULT_REGRESSION_KEY,
        help="要运行的模型版本；默认使用 registry 中的 DEFAULT_REGRESSION_KEY。",
    )
    parser.add_argument(
        "--steps",
        nargs="+",
        default=None,
        help="只运行指定步骤，例如 preprocess correlation_check regression。",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="只列出 registry 中已经登记的模型和步骤，不实际运行。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将要运行的命令和检查的输出文件，不实际执行脚本。",
    )
    parser.add_argument(
        "--skip-output-check",
        action="store_true",
        help="跳过每个步骤结束后的关键输出文件存在性检查。",
    )
    return parser.parse_args()


def choose_python() -> Path:
    """优先使用项目虚拟环境中的 Python。"""

    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def resolve_project_path(path_text: str) -> Path:
    """把 registry 中的项目相对路径解析成绝对路径。"""

    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def format_command(command: Iterable[str]) -> str:
    """把命令列表整理成便于复制检查的一行文本。"""

    return " ".join(command)


def get_pipeline_steps(config: dict[str, object]) -> list[dict[str, object]]:
    """从模型配置中读取流水线步骤，并做最基本的结构校验。"""

    steps = config.get("pipeline")
    if not isinstance(steps, list) or not steps:
        raise ValueError("模型配置缺少非空 pipeline；请先在 registry 中声明步骤。")

    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("pipeline 中每个步骤都必须是对象。")
        if "name" not in step or "script" not in step:
            raise ValueError(f"pipeline 步骤缺少 name 或 script：{step}")
    return steps


def select_steps(
    pipeline_steps: list[dict[str, object]],
    selected_names: list[str] | None,
) -> list[dict[str, object]]:
    """根据 --steps 选择要执行的步骤，保持 registry 中声明的原始顺序。"""

    if selected_names is None:
        return pipeline_steps

    available_names = [str(step["name"]) for step in pipeline_steps]
    unknown_names = [name for name in selected_names if name not in available_names]
    if unknown_names:
        raise ValueError(
            f"未知步骤：{unknown_names}；可用步骤：{available_names}"
        )

    selected_name_set = set(selected_names)
    return [step for step in pipeline_steps if str(step["name"]) in selected_name_set]


def list_models() -> None:
    """打印 registry 中已经登记的模型和步骤。"""

    print(f"配置文件：{REGISTRY_PATH}")
    for model_key in REGISTRY_MODULE.list_regression_keys():
        config = REGISTRY_MODULE.get_regression_config(model_key)
        print("\n" + "=" * 80)
        print(f"模型：{model_key}")
        print(f"说明：{config.get('description', '')}")
        for step in get_pipeline_steps(config):
            print(f"- {step['name']}: {step['script']}")


def render_step_arg(raw_arg: object, model_key: str) -> str:
    """把 registry 中的 step 参数模板渲染成真实命令行参数。

    目前只支持 ``{model}`` 占位符。这样 registry 里可以写
    ``["--model", "{model}"]``，engine 在运行 ``--model fm_baseline_down``
    时会自动传给子脚本 ``--model fm_baseline_down``。
    """
    # 先统一转成字符串，保持原来 args 支持数字、Path 等对象时的行为。
    arg_text = str(raw_arg)
    # 只替换明确约定的 {model}，不做复杂模板引擎，避免 registry 参数被意外解释。
    return arg_text.replace("{model}", model_key)


def build_step_command(
    step: dict[str, object],
    python_executable: Path,
    model_key: str,
) -> list[str]:
    """把单个步骤配置转换成 subprocess 可执行的命令列表。"""

    script_path = resolve_project_path(str(step["script"]))
    if not script_path.exists():
        raise FileNotFoundError(f"步骤脚本不存在：{script_path}")

    raw_args = step.get("args", [])
    if not isinstance(raw_args, list):
        raise ValueError(f"{step['name']} 的 args 必须是列表。")

    # args 中允许使用 {model} 占位符，让同一份 pipeline 可以复用于多个模型配置。
    rendered_args = [render_step_arg(arg, model_key) for arg in raw_args]
    return [str(python_executable), str(script_path), *rendered_args]


def check_step_outputs(step: dict[str, object]) -> None:
    """检查步骤声明的关键输出是否已经生成。"""

    outputs = step.get("outputs", [])
    if not isinstance(outputs, list):
        raise ValueError(f"{step['name']} 的 outputs 必须是列表。")

    missing_outputs = [
        str(resolve_project_path(str(output_path)))
        for output_path in outputs
        if not resolve_project_path(str(output_path)).exists()
    ]
    if missing_outputs:
        missing_text = "\n".join(f"- {path}" for path in missing_outputs)
        raise FileNotFoundError(
            f"{step['name']} 运行后缺少关键输出文件：\n{missing_text}"
        )


def run_step(
    step: dict[str, object],
    python_executable: Path,
    model_key: str,
    *,
    dry_run: bool,
    skip_output_check: bool,
) -> None:
    """运行一个流水线步骤。"""

    step_name = str(step["name"])
    command = build_step_command(step, python_executable, model_key)

    print("\n" + "=" * 80)
    print(f"开始步骤：{step_name}")
    print(f"命令：{format_command(command)}")

    if dry_run:
        print("--dry-run 模式：未运行脚本。")
        outputs = step.get("outputs", [])
        if outputs:
            print("将检查的关键输出：")
            for output_path in outputs:
                print(f"- {resolve_project_path(str(output_path))}")
        return

    subprocess.run(command, cwd=PROJECT_ROOT, check=True)

    if not skip_output_check:
        check_step_outputs(step)
        print(f"关键输出检查通过：{step_name}")
    print(f"步骤完成：{step_name}")


def main() -> None:
    """程序入口。"""

    args = parse_args()
    if args.list:
        list_models()
        return

    config = REGISTRY_MODULE.get_regression_config(args.model)
    pipeline_steps = get_pipeline_steps(config)
    steps_to_run = select_steps(pipeline_steps, args.steps)
    python_executable = choose_python()

    print(f"项目根目录：{PROJECT_ROOT}")
    print(f"配置文件：{REGISTRY_PATH}")
    print(f"模型版本：{args.model}")
    print(f"Python：{python_executable}")
    print("执行步骤：" + ", ".join(str(step["name"]) for step in steps_to_run))

    for step in steps_to_run:
        run_step(
            step,
            python_executable,
            args.model,
            dry_run=args.dry_run,
            skip_output_check=args.skip_output_check,
        )

    print("\n流水线执行完成。")


if __name__ == "__main__":
    main()


# 新增/改名 registry 模型后的标准收尾流程（2026-07-05 添加跨期限 base 系列模型时
# 用过一次，后续每次新增或重命名模型都应重复这一整套步骤，而不是只跑 engine）：
#
#   1. 对每个新增/改名的模型分别跑一次完整流水线（engine 会自动依次执行
#      preprocess → correlation_check → correlation_plots → regression →
#      portfolio_sorting）：
#
#        .venv/bin/python D_analysis/scripts/0_regression_engine.py --model <model_key>
#
#      本次实际执行过的例子：
#        .venv/bin/python D_analysis/scripts/0_regression_engine.py --model fm_baseline_interaction_rank_vol_across_horizons_noctrlLTM
#        .venv/bin/python D_analysis/scripts/0_regression_engine.py --model fm_baseline_interaction_rank_vol_across_horizons
#        .venv/bin/python D_analysis/scripts/0_regression_engine.py --model fm_baseline_interaction_base_rank_vol_across_horizons
#        .venv/bin/python D_analysis/scripts/0_regression_engine.py --model fm_baseline_interaction_base_noctrlmomentum_rank_vol_across_horizons
#
#   2. 在 I_Visualization/model_map.html 里补上新模型对应的行（main-row +
#      detail-row），并检查/更新末尾 JS 公式生成器里 key.includes(...) 的分支，
#      避免新 key 被更早的通用分支误匹配（例如 "interaction_base_xxx" 系列必须
#      写在通用 "interaction_base" 分支之前）。
#
#   3. 汇总并生成学术表格（该脚本会重新读取 model_map.html 做模型分组，因此必须
#      在第 2 步更新完 model_map.html 之后再跑，否则新模型会被扔进"未映射模型"）：
#
#        .venv/bin/python D_analysis/scripts/result_sorting.py
#
#      跑完检查终端输出的"共处理 N 个模型"是否等于 registry 模型总数，且没有打印
#      "以下模型未出现在 model_map.html" 的提示。
