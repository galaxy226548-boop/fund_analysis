"""按配置运行 B_factors 因子清洗流水线。

当前 runner 默认从 D_analysis/config/regression_registry.py 读取 fm_baseline，
也保留读取 JSON 配置的能力。这样可以避免同一套变量口径手工维护两份。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = PROJECT_ROOT / "B_factors" / "scripts"

if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from tools.factor_pipeline_tools import (
    add_quantile_groups,
    apply_sample_filters,
    build_summary,
    coerce_numeric_columns,
    normalize_month_date,
    require_columns,
    winsorize_by_month,
)


DEFAULT_CONFIG_PATH = PROJECT_ROOT / "B_factors" / "config" / "fm_baseline.json"
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_PREVIEW_ROWS = 5000
DEFAULT_STEPS = [
    "select_columns",
    "sample_filter",
    "coerce_numeric",
    "winsorize",
    "quantile_group",
    "export_summary_preview",
]


def parse_args() -> argparse.Namespace:
    """读取 runner 参数；默认跑 registry 里的 fm_baseline，也支持其他模型 key。"""

    parser = argparse.ArgumentParser(description="运行 B_factors 配置驱动清洗流水线。")
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--config",
        type=Path,
        default=None,
        help="pipeline 配置 JSON 路径；不传时默认读取 registry 中 --registry-key 指定的模型。",
    )
    source_group.add_argument(
        "--registry-key",
        default="fm_baseline",
        help="从 D_analysis/config/regression_registry.py 读取的配置 key。",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=DEFAULT_PREVIEW_ROWS,
        help="预览 Excel 最多输出多少行。",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="只输出 parquet 和 summary，不生成预览 Excel。",
    )
    return parser.parse_args()


def project_path(path_value: str | Path) -> Path:
    """把配置中的项目相对路径转成绝对路径。"""

    path = Path(path_value)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_config(config_path: Path) -> dict[str, Any]:
    """读取并做最小校验，避免误把未来模型配置传进当前 runner。"""

    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    # JSON 配置只要求有 name，具体模型名不再限制为 fm_baseline，方便复用同一套 runner。
    if not config.get("name"):
        raise ValueError("pipeline 配置缺少 name 字段。")
    return config


def load_registry_entry(registry_key: str) -> dict[str, Any]:
    """从统一 registry 读取配置，避免 B_factors 和 D_analysis 手工维护两份口径。"""

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(registry_key)


def config_from_registry(registry_key: str, registry_config: dict[str, Any]) -> dict[str, Any]:
    """把 regression_registry.py 的字段转换成 runner 使用的配置结构。"""

    return {
        # name 记录当前模型 key，summary 和日志里可以直接看出这次跑的是哪个 registry 配置。
        "name": registry_key,
        "description": registry_config.get("description", ""),
        "input_path": registry_config["preprocess_input_path"],
        "output_path": registry_config["preprocess_output_path"],
        "preview_path": registry_config["preprocess_preview_path"],
        "summary_path": registry_config["preprocess_summary_path"],
        "date_col": registry_config["date_col"],
        "id_columns": list(registry_config["id_columns"]),
        "sample_filters": dict(registry_config["sample_filters"]),
        "factor_sample_filters": {
            str(factor): dict(filters)
            for factor, filters in dict(registry_config.get("factor_sample_filters", {})).items()
        },
        "sample_flag_columns": list(registry_config["sample_flag_columns"]),
        "y_columns": [registry_config["y"]],
        "factor_columns": list(registry_config["factors"]),
        "control_columns": list(registry_config["controls"]),
        "extra_columns": list(registry_config.get("extra_columns", [])),
        "winsorize": {
            "group_column": registry_config["winsorize"]["group_column"],
            "lower_quantile": registry_config["winsorize"]["lower_quantile"],
            "upper_quantile": registry_config["winsorize"]["upper_quantile"],
            "columns": list(registry_config["winsorize"]["columns"]),
        },
        "factor_group_suffixes": dict(registry_config["factor_group_suffixes"]),
        "steps": list(DEFAULT_STEPS),
    }


def resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    """根据命令行参数决定从 JSON 还是 registry 读取配置。"""

    if args.config is not None:
        return load_config(args.config)
    return config_from_registry(args.registry_key, load_registry_entry(args.registry_key))


def keep_columns(config: dict[str, Any]) -> list[str]:
    """按旧大脚本的列顺序拼出 KEEP_COLUMNS。"""

    base_columns = (
        list(config["id_columns"])
        + list(config["sample_flag_columns"])
        + list(config["y_columns"])
        + list(config["factor_columns"])
        + list(config["control_columns"])
        + list(config.get("extra_columns", []))
    )
    # factor_sample_filters 用到的列必须保留到 preprocess 输出，供后续回归/相关性按 factor 再筛选。
    factor_filter_columns = [
        column
        for filters in dict(config.get("factor_sample_filters", {})).values()
        for column in filters
    ]
    return base_columns + [
        column for column in dict.fromkeys(factor_filter_columns) if column not in base_columns
    ]


def write_outputs(
    data: pd.DataFrame,
    output_path: Path,
    preview_path: Path,
    summary_path: Path,
    summary: dict[str, object],
    preview_rows: int,
    no_preview: bool,
) -> None:
    """写出最终 parquet、preview Excel 和 summary JSON。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(output_path, index=False)

    if not no_preview:
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        data.head(preview_rows).to_excel(preview_path, index=False)

    with summary_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
        file.write("\n")


def step_select_columns(state: dict[str, Any], config: dict[str, Any]) -> None:
    """读取原始数据，统一日期类型，并只保留配置声明的列。"""

    input_path = project_path(config["input_path"])
    data = pd.read_parquet(input_path)
    state["original_rows"] = len(data)

    columns = keep_columns(config)
    # runner 的 preprocess 只应用基础 sample_filters，但必须检查并保留所有 per-factor 筛选列。
    factor_filter_columns = [
        column
        for filters in dict(config.get("factor_sample_filters", {})).values()
        for column in filters
    ]
    required_columns = set(columns) | set(config["sample_filters"]) | set(factor_filter_columns)
    require_columns(data, required_columns, input_path)

    data = normalize_month_date(data, str(config["date_col"]))
    state["data"] = data.loc[:, columns].copy()


def step_sample_filter(state: dict[str, Any], config: dict[str, Any]) -> None:
    """按照配置中的 sample_filters 筛选样本。"""

    data = apply_sample_filters(state["data"], dict(config["sample_filters"]))
    state["data"] = data
    state["insample_rows"] = len(data)


def step_coerce_numeric(state: dict[str, Any], config: dict[str, Any]) -> None:
    """把 winsorize 需要的连续变量转成数值列。"""

    state["data"] = coerce_numeric_columns(
        state["data"],
        list(config["winsorize"]["columns"]),
    )


def step_winsorize(state: dict[str, Any], config: dict[str, Any]) -> None:
    """按配置声明的分组列和分位点做 winsorize。"""

    winsorize_config = config["winsorize"]
    state["data"] = winsorize_by_month(
        data=state["data"],
        columns=list(winsorize_config["columns"]),
        group_column=str(winsorize_config["group_column"]),
        lower_quantile=float(winsorize_config["lower_quantile"]),
        upper_quantile=float(winsorize_config["upper_quantile"]),
    )


def step_quantile_group(state: dict[str, Any], config: dict[str, Any]) -> None:
    """按月为 Consistency 因子生成 q5/q10 标签。"""

    state["data"] = add_quantile_groups(
        data=state["data"],
        group_column=str(config["winsorize"]["group_column"]),
        factor_group_suffixes=dict(config["factor_group_suffixes"]),
    )


def step_export_summary_preview(
    state: dict[str, Any],
    config: dict[str, Any],
    *,
    preview_rows: int,
    no_preview: bool,
) -> None:
    """写出最终 parquet、summary JSON 和 preview Excel。"""

    data = state["data"]
    input_path = project_path(config["input_path"])
    output_path = project_path(config["output_path"])
    preview_path = project_path(config["preview_path"])
    summary_path = project_path(config["summary_path"])
    summary_preview_path = None if no_preview else preview_path
    winsorize_config = config["winsorize"]

    summary = build_summary(
        input_path=input_path,
        output_path=output_path,
        preview_path=summary_preview_path,
        original_rows=int(state["original_rows"]),
        insample_rows=int(state["insample_rows"]),
        output_rows=len(data),
        output_columns=list(data.columns),
        sample_filters=dict(config["sample_filters"]),
        factor_sample_filters={
            str(factor): dict(filters)
            for factor, filters in dict(config.get("factor_sample_filters", {})).items()
        },
        winsor_group_column=str(winsorize_config["group_column"]),
        winsor_lower_quantile=float(winsorize_config["lower_quantile"]),
        winsor_upper_quantile=float(winsorize_config["upper_quantile"]),
        winsorize_columns=list(winsorize_config["columns"]),
        keep_columns=keep_columns(config),
    )
    write_outputs(
        data=data,
        output_path=output_path,
        preview_path=preview_path,
        summary_path=summary_path,
        summary=summary,
        preview_rows=preview_rows,
        no_preview=no_preview,
    )
    state["output_path"] = output_path
    state["preview_path"] = summary_preview_path
    state["summary_path"] = summary_path


STEP_FUNCTIONS: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]] = {
    "select_columns": step_select_columns,
    "sample_filter": step_sample_filter,
    "coerce_numeric": step_coerce_numeric,
    "winsorize": step_winsorize,
    "quantile_group": step_quantile_group,
}


def run_pipeline(
    config: dict[str, Any],
    *,
    preview_rows: int,
    no_preview: bool,
) -> dict[str, Any]:
    """按配置中的 steps 顺序执行流水线。"""

    state: dict[str, Any] = {}
    for step_name in config["steps"]:
        if step_name == "export_summary_preview":
            step_export_summary_preview(
                state,
                config,
                preview_rows=preview_rows,
                no_preview=no_preview,
            )
            continue

        try:
            step_function = STEP_FUNCTIONS[step_name]
        except KeyError as error:
            raise ValueError(f"未知 pipeline step：{step_name}") from error
        step_function(state, config)
        data = state.get("data")
        if isinstance(data, pd.DataFrame):
            print(f"{step_name}: shape={data.shape}")

    return state


def main() -> None:
    """命令行入口。"""

    args = parse_args()
    config = resolve_config(args)
    state = run_pipeline(
        config,
        preview_rows=args.preview_rows,
        no_preview=args.no_preview,
    )

    print(f"原始样本行数：{state['original_rows']}")
    print(f"样本内行数：{state['insample_rows']}")
    print(f"输出行数：{len(state['data'])}")
    print(f"输出 parquet：{state['output_path']}")
    if state["preview_path"] is not None:
        print(f"输出 preview Excel：{state['preview_path']}")
    print(f"输出 summary：{state['summary_path']}")


if __name__ == "__main__":
    main()
