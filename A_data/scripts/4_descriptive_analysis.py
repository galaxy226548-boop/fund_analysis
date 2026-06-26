"""
批量运行 panel_base.parquet 的描述性统计分析。

这个脚本本身不直接计算统计量，而是作为“总控脚本”：
它会调用 4_descriptive_analysis_tool.py 多次，分别生成多组分析结果。

第 1 组：原型默认系列 X（全样本），也就是若干 rank volatility 指标。
第 2 组：原型默认系列 Y（全样本），也就是未来 3/6/12 个月收益率。
第 3 组：原型默认系列 X（未来 6 月收益，样本内），只保留未来 6 月收益样本内的行。
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# 项目根目录。
# __file__ 是当前脚本路径；parents[2] 表示往上两级，回到 Fund_Analysis 目录。
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 真正负责做描述性统计、画图、写 Excel 的工具脚本。
TOOL_SCRIPT = PROJECT_ROOT / "A_data/scripts/4_descriptive_analysis_tool.py"

# 本次两组分析都使用同一个输入文件。
INPUT_FILE = PROJECT_ROOT / "A_data/output/panel_base.parquet"
REGISTRY_PATH = PROJECT_ROOT / "D_analysis/config/regression_registry.py"
DEFAULT_MODEL_KEY = "fm_baseline"


@dataclass(frozen=True)
class DescriptiveBatch:
    """
    保存“一批描述性统计任务”的基本信息。

    可以把它理解成一个小表格的一行：
    - name：这一批结果的中文名字，也会作为输出文件名前缀。
    - columns：这一批要分析哪些列。
    - filter_column：如果需要先筛选样本，就填写筛选列名；不筛选时留空。
    - filter_value：筛选列需要等于什么值；不筛选时留空。

    frozen=True 表示创建后不希望再修改，避免后面不小心改错配置。
    """

    name: str
    columns: tuple[str, ...]
    filter_column: str | None = None
    filter_value: str | None = None


# 这里集中列出所有要跑的分析批次。
# 如果以后要新增一组描述性统计，通常只需要在 BATCHES 里再加一个 DescriptiveBatch。
BATCHES = (
    DescriptiveBatch(
        name="原型默认系列X（全样本）",
        columns=(
            "rank_vol_m3_n6_pairwise1",
            "rank_vol_m6_n3_pairwise1",
            "rank_vol_m6_n6_pairwise1",
            "rank_vol_m6_n12_pairwise1",
            "rank_vol_m12_n6_pairwise1",
        ),
    ),
    DescriptiveBatch(
        name="原型默认系列Y（全样本）",
        columns=(
            "future_ret_3m",
            "future_ret_6m",
            "future_ret_12m",
        ),
    ),
    DescriptiveBatch(
        name="原型默认系列X（未来6月收益，样本内）",
        columns=(
            "rank_vol_m3_n6_pairwise1",
            "rank_vol_m6_n3_pairwise1",
            "rank_vol_m6_n6_pairwise1",
            "rank_vol_m6_n12_pairwise1",
            "rank_vol_m12_n6_pairwise1",
        ),
        filter_column="is_insample_future_ret_6m",
        filter_value="1",
    ),
)


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(description="批量运行描述性统计分析。")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_KEY,
        help="regression_registry.py 中的模型名称；若该模型没有 descriptive 配置，则使用脚本默认批次。",
    )
    return parser.parse_args()


def resolve_project_path(path_text: str | Path) -> Path:
    """把 registry 中的项目相对路径转成绝对路径。"""
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_regression_config(model_key: str) -> dict[str, Any]:
    """从 regression_registry.py 读取指定模型配置。"""
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    # 按文件路径加载 registry，避免要求 D_analysis 是 Python 包。
    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry",
        REGISTRY_PATH,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(model_key)


def build_default_descriptive_plan() -> tuple[Path, Path | None, tuple[DescriptiveBatch, ...]]:
    """返回脚本原有的默认描述性统计计划。"""
    # 没有 registry descriptive 配置时，完全沿用原来的输入文件和 BATCHES。
    return INPUT_FILE, None, BATCHES


def build_registry_descriptive_plan(
    config: dict[str, Any],
) -> tuple[Path, Path | None, tuple[DescriptiveBatch, ...]]:
    """把 registry 中的 descriptive 配置转换成脚本可执行的批次。"""
    descriptive_config = config.get("descriptive")
    if not descriptive_config:
        return build_default_descriptive_plan()
    if not isinstance(descriptive_config, dict):
        raise ValueError("descriptive 配置必须是对象。")

    # input_path 决定描述性统计读取哪张表；不写时回退到 A_data/output/panel_base.parquet。
    input_path = resolve_project_path(
        str(descriptive_config.get("input_path", INPUT_FILE))
    )
    output_dir = descriptive_config.get("output_dir")
    resolved_output_dir = (
        resolve_project_path(str(output_dir)) if output_dir is not None else None
    )
    name_prefix = str(descriptive_config.get("prefix", "")).strip()

    raw_batches = descriptive_config.get("batches", [])
    if not isinstance(raw_batches, list) or not raw_batches:
        raise ValueError("descriptive.batches 必须是非空列表。")

    batches: list[DescriptiveBatch] = []
    for raw_batch in raw_batches:
        if not isinstance(raw_batch, dict):
            raise ValueError(f"descriptive.batches 中每一项都必须是对象：{raw_batch}")

        # 每个 batch 至少要有 name 和 columns；filter 可选。
        raw_name = str(raw_batch["name"])
        batch_name = f"{name_prefix}_{raw_name}" if name_prefix else raw_name
        columns = tuple(str(column) for column in raw_batch["columns"])
        batches.append(
            DescriptiveBatch(
                name=batch_name,
                columns=columns,
                filter_column=raw_batch.get("filter_column"),
                filter_value=(
                    None
                    if raw_batch.get("filter_value") is None
                    else str(raw_batch.get("filter_value"))
                ),
            )
        )

    return input_path, resolved_output_dir, tuple(batches)


def run_batch(
    batch: DescriptiveBatch,
    input_file: Path,
    output_dir: Path | None,
) -> None:
    """
    运行单个分析批次。

    参数 batch 里已经包含了：
    - 输出文件名前缀；
    - 要分析的列名列表。
    - 可选的筛选条件。

    这里会把这些信息组装成命令行参数，然后交给工具脚本执行。
    """

    # sys.executable 表示“当前正在使用的 Python 解释器”。
    # 这样做的好处是：如果我们用 .venv/bin/python 运行本脚本，
    # 那么它调用工具脚本时也会继续使用同一个虚拟环境。
    command = [
        sys.executable,
        str(TOOL_SCRIPT),
        "--input",
        str(input_file),
        "--columns",
        *batch.columns,
        "--prefix",
        batch.name,
    ]
    if output_dir is not None:
        command.extend(["--output-dir", str(output_dir)])

    # 只有配置了筛选条件的批次，才给工具脚本传 --filter-column / --filter-value。
    # 这样前两个“全样本”批次仍然会使用完整数据，不受第三个批次影响。
    if batch.filter_column is not None and batch.filter_value is not None:
        command.extend(
            [
                "--filter-column",
                batch.filter_column,
                "--filter-value",
                batch.filter_value,
            ]
        )

    # 打印当前批次名称，方便在终端里看进度。
    print(f"\n开始生成：{batch.name}")

    # check=True 表示如果工具脚本报错，就立刻让整个脚本失败。
    # 这样可以避免前面失败了、后面还继续跑，导致用户误以为全部成功。
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    """按顺序运行 BATCHES 里配置好的所有描述性统计批次。"""
    args = parse_args()
    config = load_regression_config(args.model)
    input_file, output_dir, batches = build_registry_descriptive_plan(config)

    print(f"模型版本：{args.model}")
    print(f"输入文件：{input_file}")
    if output_dir is not None:
        print(f"输出目录：{output_dir}")

    for batch in batches:
        run_batch(batch, input_file=input_file, output_dir=output_dir)


if __name__ == "__main__":
    # 只有当用户直接运行这个文件时，才执行 main()。
    # 如果以后别的脚本 import 这个文件，则不会自动开始跑分析。
    main()
