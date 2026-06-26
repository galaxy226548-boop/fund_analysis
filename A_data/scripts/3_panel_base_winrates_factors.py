"""为 panel_base.parquet 追加过去收益率排名命中特征。

默认读取并覆盖：

    A_data/output/panel_base.parquet

新增列会放在原有字段的最右侧，并同步刷新：

    A_data/output/panel_base_preview.xlsx
    A_data/output/rank_hit_feature_registry.json
    B_factors/input/panel_base.parquet
    B_factors/input/panel_base_preview.xlsx

本脚本只负责基于已有 past_ret_{m}m_rank_{k} 列生成命中特征，不重新计算
past_ret、rank、控制变量或回归因子。

运行方式：

    .venv/bin/python A_data/scripts/3_panel_base_winrates_factors.py
    .venv/bin/python A_data/scripts/3_panel_base_winrates_factors.py --no-preview
"""

from __future__ import annotations

import argparse
import json
import operator
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import Config


DEFAULT_INPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_OUTPUT_PATH = Config.PANEL_OUTPUT_PATH
DEFAULT_FACTOR_INPUT_DIR = Config.PROJECT_ROOT / "B_factors" / "input"
DEFAULT_RANK_HIT_REGISTRY_PATH = (
    Config.A_DATA_ROOT / "output" / "rank_hit_feature_registry.json"
)
DEFAULT_PREVIEW_ROWS = 1000

# 这里的 m 表示收益率排名窗口长度，如 past_ret_6m_rank_k 中的 6m；
# n 表示统计 rank_1 到 rank_n 共多少期。
RANK_HIT_COMBOS = ((3, 6), (6, 3), (6, 6), (6, 12), (12, 6))

# 重要方向说明：
# 3_generate_panel_base.py 的 add_pairwise_past_rank_columns 使用 pct=True，
# 并在注释中写明 0=最差、1=最好。因此本脚本按“rank 越大，原始过去收益越大”
# 来解释 top/bottom。如果上游排名方向改成反向，不能静默沿用这里的阈值。
RANK_LARGER_MEANS_HIGHER_RETURN = True
RANK_DIRECTION_DESCRIPTION = "rank 越大代表原始过去收益率越大、截面排名越靠前"

# 每个口径的边界集中写在这里。前 50% 与后 50% 使用 >0.5 / <=0.5，
# 避免 rank=0.5 被重复计入；前 30% 与后 30% 使用 >0.7 / <=0.3。
RANK_HIT_THRESHOLDS = {
    "top50": {"operator": ">", "threshold": 0.5, "description": "rank > 0.5"},
    "top30": {"operator": ">", "threshold": 0.7, "description": "rank > 0.7"},
    "bottom50": {"operator": "<=", "threshold": 0.5, "description": "rank <= 0.5"},
    "bottom30": {"operator": "<=", "threshold": 0.3, "description": "rank <= 0.3"},
}

THRESHOLD_OPERATORS: dict[str, Callable[[pd.DataFrame, float], pd.DataFrame]] = {
    ">": operator.gt,
    "<=": operator.le,
}


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(description="为 panel_base 追加排名命中特征。")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="输入 panel_base parquet 文件路径。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="输出 parquet 文件路径；默认覆盖输入文件。",
    )
    parser.add_argument(
        "--preview",
        type=Path,
        default=None,
        help="Excel 预览输出路径；默认跟随 output 生成 *_preview.xlsx。",
    )
    parser.add_argument(
        "--factor-input-dir",
        type=Path,
        default=DEFAULT_FACTOR_INPUT_DIR,
        help="把最终 parquet 和 preview Excel 复制到这个目录，默认 B_factors/input。",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_RANK_HIT_REGISTRY_PATH,
        help="新增排名命中特征清单 JSON 输出路径。",
    )
    parser.add_argument(
        "--preview-rows",
        type=int,
        default=DEFAULT_PREVIEW_ROWS,
        help="Excel preview 输出前多少行。",
    )
    parser.add_argument(
        "--no-preview",
        action="store_true",
        help="只更新 parquet，不更新 Excel 预览。",
    )
    return parser.parse_args()


def read_panel(input_path: Path) -> pd.DataFrame:
    """读取 panel_base，并做最基础的主键字段检查。"""
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在：{input_path}")

    data = pd.read_parquet(input_path)
    required_columns = [
        Config.COLUMN_IFIND_CODE,
        Config.COLUMN_MONTH_DATE,
        Config.COLUMN_INVESTMENT_TYPE,
    ]
    missing = [column for column in required_columns if column not in data.columns]
    if missing:
        raise ValueError(f"{input_path} 缺少基础字段：{missing}")
    return data.copy()


def get_rank_columns(rank_window_m: int, n_periods: int) -> list[str]:
    """根据 m 和 n 拼出需要读取的 rank 列名。"""
    return [
        f"past_ret_{rank_window_m}m_rank_{period_index}"
        for period_index in range(1, n_periods + 1)
    ]


def get_hitrate_column(metric: str, rank_window_m: int, n_periods: int, pairwise: int) -> str:
    """生成命中比例变量名。"""
    return f"hitrate_{metric}_m{rank_window_m}_n{n_periods}_pairwise{pairwise}"


def get_hitcount_column(
    metric: str, rank_window_m: int, n_periods: int, pairwise: int
) -> str:
    """生成命中次数变量名。"""
    return f"hitcount_{metric}_m{rank_window_m}_n{n_periods}_pairwise{pairwise}"


def get_dummy_column(
    metric: str, rank_window_m: int, n_periods: int, hit_k: int, pairwise: int
) -> str:
    """生成命中次数 dummy 变量名。"""
    return (
        f"dummy_{metric}_m{rank_window_m}_n{n_periods}_hit{hit_k}_pairwise{pairwise}"
    )


def make_feature_record(
    variable_name: str,
    rank_window_m: int,
    n_periods: int,
    metric: str,
    variable_type: str,
    pairwise: int,
    hit_k: int | None = None,
) -> dict[str, object]:
    """把单个新增变量整理成 registry 中的一条记录。"""
    record: dict[str, object] = {
        "variable_name": variable_name,
        "m": rank_window_m,
        "n": n_periods,
        "metric": metric,
        "variable_type": variable_type,
        "pairwise": pairwise,
        "rank_direction": RANK_DIRECTION_DESCRIPTION,
    }
    if hit_k is not None:
        record["hit_k"] = hit_k
    return record


def find_existing_output_columns(
    data: pd.DataFrame,
    combos: tuple[tuple[int, int], ...],
    thresholds_config: dict[str, dict[str, object]],
    pairwise: int,
) -> list[str]:
    """检查将要生成的列名是否已经存在，避免误覆盖旧结果。"""
    output_columns: list[str] = []
    for rank_window_m, n_periods in combos:
        for metric in thresholds_config:
            output_columns.append(
                get_hitrate_column(metric, rank_window_m, n_periods, pairwise)
            )
            output_columns.append(
                get_hitcount_column(metric, rank_window_m, n_periods, pairwise)
            )
            output_columns.extend(
                get_dummy_column(metric, rank_window_m, n_periods, hit_k, pairwise)
                for hit_k in range(0, n_periods + 1)
            )
    return [column for column in output_columns if column in data.columns]


def add_rank_hit_features(
    df: pd.DataFrame,
    rank_window_m: int,
    n_periods: int,
    thresholds_config: dict[str, dict[str, object]],
    pairwise: int = 1,
    require_full_window: bool = True,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """为一个 (m,n) 组合追加 hitrate、hitcount 和 dummy 变量。

    只有 rank_1 到 rank_n 全部非缺失时，才计算有效值；否则该组合下所有
    hitrate、hitcount、dummy 都保留 NaN。dummy_hit0 到 dummy_hitn 会全部生成，
    但带截距项回归时不能同时放入全部 dummy，需要省略一个基准组，避免
    dummy variable trap。
    """
    rank_cols = get_rank_columns(rank_window_m, n_periods)
    missing_rank_cols = [column for column in rank_cols if column not in df.columns]
    if missing_rank_cols:
        print(
            f"跳过 m={rank_window_m}, n={n_periods}：缺少 rank 列 "
            f"{missing_rank_cols}"
        )
        return df, []

    result = df.copy()
    rank_values = result[rank_cols].apply(pd.to_numeric, errors="coerce")
    invalid_rank_mask = rank_values.notna() & ~rank_values.apply(
        lambda column: column.between(0, 1)
    )
    if invalid_rank_mask.any().any():
        invalid_columns = invalid_rank_mask.any(axis=0)
        bad_columns = invalid_columns[invalid_columns].index.tolist()
        raise ValueError(
            f"m={rank_window_m}, n={n_periods} 的 rank 列出现 [0,1] 之外取值："
            f"{bad_columns}"
        )

    # require_full_window=True 是本研究口径的核心：n 代表固定历史期数，
    # 如果只用部分非缺失列算比例，会把不同历史长度的样本混在一起。
    if require_full_window:
        valid_window = rank_values.notna().all(axis=1)
    else:
        valid_window = rank_values.notna().any(axis=1)

    records: list[dict[str, object]] = []
    for metric, threshold_config in thresholds_config.items():
        op_text = str(threshold_config["operator"])
        threshold = float(threshold_config["threshold"])
        if op_text not in THRESHOLD_OPERATORS:
            raise ValueError(f"不支持的阈值比较符：{op_text}")

        hit_flags = THRESHOLD_OPERATORS[op_text](rank_values, threshold)
        hitcount_col = get_hitcount_column(metric, rank_window_m, n_periods, pairwise)
        hitrate_col = get_hitrate_column(metric, rank_window_m, n_periods, pairwise)

        # NaN 与阈值比较会得到 False，所以必须先按 valid_window 清掉无效窗口；
        # 否则缺失 rank 会被误当作“未命中”。
        hitcount = hit_flags.sum(axis=1).astype("float64")
        hitcount.loc[~valid_window] = np.nan
        result[hitcount_col] = hitcount
        result[hitrate_col] = hitcount / n_periods

        records.append(
            make_feature_record(
                hitrate_col, rank_window_m, n_periods, metric, "hitrate", pairwise
            )
        )
        records.append(
            make_feature_record(
                hitcount_col, rank_window_m, n_periods, metric, "hitcount", pairwise
            )
        )

        for hit_k in range(0, n_periods + 1):
            dummy_col = get_dummy_column(
                metric, rank_window_m, n_periods, hit_k, pairwise
            )
            dummy_values = (hitcount == hit_k).astype("float64")
            dummy_values.loc[~valid_window] = np.nan
            result[dummy_col] = dummy_values
            records.append(
                make_feature_record(
                    dummy_col,
                    rank_window_m,
                    n_periods,
                    metric,
                    "dummy",
                    pairwise,
                    hit_k=hit_k,
                )
            )

    return result, records


def validate_rank_hit_features(
    data: pd.DataFrame,
    feature_records: list[dict[str, object]],
) -> None:
    """对新增 hitrate、hitcount 和 dummy 做基础校验。"""
    records_by_combo: dict[tuple[int, int, str, int], dict[str, object]] = {}
    for record in feature_records:
        key = (
            int(record["m"]),
            int(record["n"]),
            str(record["metric"]),
            int(record["pairwise"]),
        )
        combo_records = records_by_combo.setdefault(
            key, {"hitrate": None, "hitcount": None, "dummy": []}
        )
        variable_type = str(record["variable_type"])
        if variable_type == "dummy":
            combo_records["dummy"].append(record)
        else:
            combo_records[variable_type] = record

    for (rank_window_m, n_periods, metric, pairwise), combo_records in records_by_combo.items():
        hitrate_record = combo_records["hitrate"]
        hitcount_record = combo_records["hitcount"]
        dummy_records = sorted(
            combo_records["dummy"], key=lambda record: int(record["hit_k"])
        )

        if hitrate_record is None or hitcount_record is None:
            raise AssertionError(f"m={rank_window_m}, n={n_periods}, {metric} 缺少核心变量。")

        hitrate_col = str(hitrate_record["variable_name"])
        hitcount_col = str(hitcount_record["variable_name"])
        hitrate = data[hitrate_col]
        hitcount = data[hitcount_col]

        # 1. hitrate 必须在 [0,1] 或 NaN。
        valid_hitrate = hitrate.dropna()
        if not valid_hitrate.between(0, 1).all():
            raise AssertionError(f"{hitrate_col} 出现 [0,1] 之外取值。")

        # 2. hitcount 必须是 0~n 的整数或 NaN。
        valid_hitcount = hitcount.dropna()
        if not valid_hitcount.between(0, n_periods).all():
            raise AssertionError(f"{hitcount_col} 出现 0~{n_periods} 之外取值。")
        if not np.isclose(valid_hitcount, np.round(valid_hitcount)).all():
            raise AssertionError(f"{hitcount_col} 出现非整数取值。")

        # 3. hitrate 必须等于 hitcount / n。
        comparable = hitrate.notna() & hitcount.notna()
        if not np.isclose(hitrate.loc[comparable], hitcount.loc[comparable] / n_periods).all():
            raise AssertionError(f"{hitrate_col} 与 {hitcount_col}/{n_periods} 不一致。")

        # 4. rank 完整非缺失的样本中，dummy_hit0 到 dummy_hitn 的行和必须等于 1。
        expected_dummy_count = n_periods + 1
        if len(dummy_records) != expected_dummy_count:
            raise AssertionError(
                f"m={rank_window_m}, n={n_periods}, {metric} 的 dummy 数量不正确。"
            )
        dummy_cols = [str(record["variable_name"]) for record in dummy_records]
        dummy_values = data[dummy_cols]
        valid_window = hitcount.notna()
        dummy_sum = dummy_values.loc[valid_window].sum(axis=1)
        if not np.isclose(dummy_sum, 1).all():
            raise AssertionError(
                f"m={rank_window_m}, n={n_periods}, {metric} 的 dummy 行和不等于 1。"
            )
        if dummy_values.loc[~valid_window].notna().any().any():
            raise AssertionError(
                f"m={rank_window_m}, n={n_periods}, {metric} 的缺失窗口 dummy 未保持 NaN。"
            )


def build_rank_hit_feature_registry(
    feature_records: list[dict[str, object]],
    skipped_combos: list[dict[str, object]],
) -> dict[str, object]:
    """整理本次新增变量清单，写入轻量 JSON registry。"""
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rank_direction": RANK_DIRECTION_DESCRIPTION,
        "rank_larger_means_higher_return": RANK_LARGER_MEANS_HIGHER_RETURN,
        "thresholds": RANK_HIT_THRESHOLDS,
        "dummy_regression_note": (
            "dummy_hit0 到 dummy_hitn 会全部生成；带截距项回归不能同时放入全部 "
            "dummy，需要省略一个基准组，避免 dummy variable trap。"
        ),
        "features": feature_records,
        "skipped_combos": skipped_combos,
    }


def write_rank_hit_feature_registry(registry: dict[str, object], registry_path: Path) -> None:
    """保存新增变量清单 JSON。"""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def get_default_preview_path(output_path: Path) -> Path:
    """根据 parquet 输出路径推导 Excel 预览路径。"""
    return output_path.with_name(output_path.stem + "_preview.xlsx")


def copy_outputs_to_factor_input(
    output_path: Path, preview_path: Path | None, factor_input_dir: Path
) -> dict[str, Path | None]:
    """把最终输出文件复制到 B_factors/input，供后续因子脚本使用。"""
    factor_input_dir.mkdir(parents=True, exist_ok=True)

    copied_parquet_path = factor_input_dir / output_path.name
    shutil.copy2(output_path, copied_parquet_path)

    copied_preview_path = None
    if preview_path is not None:
        copied_preview_path = factor_input_dir / preview_path.name
        shutil.copy2(preview_path, copied_preview_path)

    return {
        "copied_parquet_path": copied_parquet_path,
        "copied_preview_path": copied_preview_path,
    }


def generate_rank_hit_features(
    input_path: Path,
    output_path: Path,
    factor_input_dir: Path,
    registry_path: Path,
    preview_path: Path | None = None,
    write_preview: bool = True,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
) -> dict[str, object]:
    """生成排名命中特征并写出 parquet、preview 和 registry。"""
    original = read_panel(input_path)
    existing_output_columns = find_existing_output_columns(
        original,
        combos=RANK_HIT_COMBOS,
        thresholds_config=RANK_HIT_THRESHOLDS,
        pairwise=Config.PANEL_PAIRWISE,
    )
    if existing_output_columns:
        raise ValueError(
            "输入数据中已经存在本脚本将生成的列。为避免覆盖已有列，请先确认这些列是否"
            f"可以重建：{existing_output_columns[:20]}"
        )

    print(f"排名方向：{RANK_DIRECTION_DESCRIPTION}")
    result = original
    feature_records: list[dict[str, object]] = []
    skipped_combos: list[dict[str, object]] = []
    for rank_window_m, n_periods in RANK_HIT_COMBOS:
        rank_cols = get_rank_columns(rank_window_m, n_periods)
        missing_rank_cols = [column for column in rank_cols if column not in result.columns]
        if missing_rank_cols:
            skipped_combos.append(
                {
                    "m": rank_window_m,
                    "n": n_periods,
                    "missing_rank_columns": missing_rank_cols,
                }
            )
            print(
                f"跳过 m={rank_window_m}, n={n_periods}：缺少 rank 列 "
                f"{missing_rank_cols}"
            )
            continue

        result, combo_records = add_rank_hit_features(
            result,
            rank_window_m=rank_window_m,
            n_periods=n_periods,
            thresholds_config=RANK_HIT_THRESHOLDS,
            pairwise=Config.PANEL_PAIRWISE,
            require_full_window=True,
        )
        feature_records.extend(combo_records)

    validate_rank_hit_features(result, feature_records)

    registry = build_rank_hit_feature_registry(feature_records, skipped_combos)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_parquet(output_path, index=False)
    write_rank_hit_feature_registry(registry, registry_path)

    actual_preview_path = None
    if write_preview:
        actual_preview_path = preview_path or get_default_preview_path(output_path)
        actual_preview_path.parent.mkdir(parents=True, exist_ok=True)
        result.head(preview_rows).to_excel(actual_preview_path, index=False)

    copied_outputs = copy_outputs_to_factor_input(
        output_path=output_path,
        preview_path=actual_preview_path,
        factor_input_dir=factor_input_dir,
    )

    return {
        "input_path": input_path,
        "output_path": output_path,
        "preview_path": actual_preview_path,
        "registry_path": registry_path,
        "copied_parquet_path": copied_outputs["copied_parquet_path"],
        "copied_preview_path": copied_outputs["copied_preview_path"],
        "factor_input_dir": factor_input_dir,
        "row_count": len(result),
        "column_count": len(result.columns),
        "added_columns": [record["variable_name"] for record in feature_records],
        "feature_records": feature_records,
        "skipped_combos": skipped_combos,
    }


def print_summary(summary: dict[str, object]) -> None:
    """打印运行摘要，方便在终端快速核对结果。"""
    print(f"输入路径：{summary['input_path']}")
    print(f"输出路径：{summary['output_path']}")
    if summary["preview_path"] is not None:
        print(f"预览路径：{summary['preview_path']}")
    print(f"变量清单 JSON：{summary['registry_path']}")
    print(f"B_factors parquet 复制路径：{summary['copied_parquet_path']}")
    if summary["copied_preview_path"] is not None:
        print(f"B_factors preview 复制路径：{summary['copied_preview_path']}")
    print(f"输出行数：{summary['row_count']:,}")
    print(f"输出列数：{summary['column_count']:,}")
    print(f"新增变量数：{len(summary['added_columns']):,}")

    if summary["skipped_combos"]:
        print("跳过的 (m,n) 组合：")
        for item in summary["skipped_combos"]:
            print(
                f"  m={item['m']}, n={item['n']}，缺少："
                + "、".join(item["missing_rank_columns"])
            )
    else:
        print("所有 (m,n) 组合均已生成，未跳过。")

    print("新增变量清单：")
    for record in summary["feature_records"]:
        hit_k_text = ""
        if record["variable_type"] == "dummy":
            hit_k_text = f"，hit_k={record['hit_k']}"
        print(
            f"  {record['variable_name']}：m={record['m']}，n={record['n']}，"
            f"口径={record['metric']}，类型={record['variable_type']}{hit_k_text}"
        )


def main() -> None:
    """命令行入口。"""
    args = parse_args()
    summary = generate_rank_hit_features(
        input_path=args.input,
        output_path=args.output,
        factor_input_dir=args.factor_input_dir,
        registry_path=args.registry,
        preview_path=args.preview,
        write_preview=not args.no_preview,
        preview_rows=args.preview_rows,
    )
    print_summary(summary)


if __name__ == "__main__":
    main()
