"""独立检查三种非重叠 winrate Hitrate 主变量的月度可识别性。

本脚本只处理字符串型 ``hitrate=hitcount/n`` 因子。连续变量是否可识别，取决于
月度横截面内是否有变化，以及加入截距、控制变量后的设计矩阵是否满秩；这里不会
读取累计 Dummy 的通过清单，也不会要求 Hit0～Hitn 每一组都出现。
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

# 避免 matplotlib 在用户目录写缓存；项目目录只保存最终热力图。
os.environ.setdefault(
    "MPLCONFIGDIR", "/private/tmp/matplotlib-winrate-hitrate-identification"
)

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_PANEL = (
    PROJECT_ROOT / "A_data" / "output" / "panel_base_heatmap_m1_12_n1_12.parquet"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_hitrate_identification_grid"
)
MODEL_SPECS = {
    "top50": ("fm_winrates_top50_nonoverlap", "Top 50"),
    "top33": ("fm_winrates_top33_nonoverlap", "Top 33"),
    "bottom33": ("fm_winrates_bottom33_nonoverlap", "Bottom 33"),
}
FACTOR_PATTERN = re.compile(
    r"^hitrate_(?P<metric>top50|top33|bottom33)_"
    r"m(?P<m>[1-6])_n(?P<n>[1-6])_pairwise(?P<pairwise>[1-6])$"
)


def parse_args() -> argparse.Namespace:
    """读取输入、输出和模型通过门槛。"""
    parser = argparse.ArgumentParser(
        description="批量检查 winrate Hitrate 连续主变量的月度可识别性。"
    )
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-ready-months", type=int, default=60)
    parser.add_argument("--min-ready-rate", type=float, default=0.70)
    return parser.parse_args()


def load_regression_config(model_key: str) -> dict[str, Any]:
    """直接读取统一 registry，避免依赖累计 Dummy 诊断脚本。"""
    spec = importlib.util.spec_from_file_location(
        "winrate_hitrate_identification_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return dict(module.get_regression_config(model_key))


def hitrate_specs(config: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    """只枚举 m=1..6、n=2..6、pairwise=m 的字符串型 Hitrate 因子。"""
    result: list[dict[str, Any]] = []
    for raw_factor in config.get("factors", []):
        # tuple/list 属于累计 Dummy 层，必须在入口处明确排除。
        if not isinstance(raw_factor, str):
            continue
        match = FACTOR_PATTERN.fullmatch(raw_factor)
        if match is None or match.group("metric") != metric:
            continue
        m = int(match.group("m"))
        n = int(match.group("n"))
        pairwise = int(match.group("pairwise"))
        if n >= 2 and pairwise == m:
            result.append(
                {
                    "factor": raw_factor,
                    "factor_spec": raw_factor,
                    "m": m,
                    "n": n,
                    "pairwise": pairwise,
                }
            )

    result.sort(key=lambda item: (item["n"], item["m"]))
    factors = [str(item["factor"]) for item in result]
    expected_m6_n6 = f"hitrate_{metric}_m6_n6_pairwise6"
    if len(result) != 30:
        raise AssertionError(f"{metric} 应有 30 个 Hitrate 候选，实际为 {len(result)} 个。")
    if len(factors) != len(set(factors)):
        raise AssertionError(f"{metric} 的 Hitrate 候选存在重复。")
    if expected_m6_n6 not in factors:
        raise AssertionError(f"{metric} 候选缺少 {expected_m6_n6}。")
    return result


def validate_candidate_grid(
    specs_by_metric: dict[str, list[dict[str, Any]]],
) -> None:
    """对 90 个候选及三个 m6_n6 做一次跨模型硬校验。"""
    if set(specs_by_metric) != set(MODEL_SPECS):
        raise AssertionError("候选口径必须恰好为 Top50、Top33、Bottom33。")
    counts = {metric: len(specs) for metric, specs in specs_by_metric.items()}
    if any(count != 30 for count in counts.values()) or sum(counts.values()) != 90:
        raise AssertionError(f"候选数应为每种口径 30 个、合计 90 个，实际为 {counts}。")
    for metric, specs in specs_by_metric.items():
        factors = {str(item["factor"]) for item in specs}
        required = f"hitrate_{metric}_m6_n6_pairwise6"
        if required not in factors:
            raise AssertionError(f"候选清单缺少 {required}。")


def build_filter_mask(series: pd.Series, expected_value: Any) -> pd.Series:
    """兼容数值和字符串筛选值，与主回归的样本筛选口径一致。"""
    expected_numeric = pd.to_numeric(
        pd.Series([expected_value]), errors="coerce"
    ).iloc[0]
    if pd.notna(expected_numeric):
        return pd.to_numeric(series, errors="coerce") == expected_numeric
    return series.astype("string") == str(expected_value)


def apply_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    """应用 registry 中声明的基础样本筛选。"""
    result = df.copy()
    for column, expected_value in filters.items():
        if column not in result.columns:
            raise ValueError(f"输入面板缺少样本筛选列：{column}")
        result = result.loc[build_filter_mask(result[column], expected_value)].copy()
    return result


def factor_filters(config: dict[str, Any], factor: str) -> dict[str, Any]:
    """合并基础筛选与可能按单个 Hitrate 登记的额外筛选。"""
    filters = dict(config.get("sample_filters", {}))
    extra = dict(config.get("factor_sample_filters", {})).get(factor, {})
    filters.update(dict(extra or {}))
    return filters


def prepare_hitrate_sample(
    panel: pd.DataFrame,
    config: dict[str, Any],
    factor: str,
) -> tuple[pd.DataFrame, list[str]]:
    """构造 Y、Hitrate 和 controls 均完整的主回归样本。"""
    if config.get("interactions"):
        raise ValueError("Hitrate 识别脚本暂不支持带交互项的模型。")

    date_col = str(config["date_col"])
    y_col = str(config["y"])
    control_cols = [str(column) for column in config.get("controls", [])]
    filters = factor_filters(config, factor)
    required = list(
        dict.fromkeys([date_col, y_col, factor, *control_cols, *filters])
    )
    missing = [column for column in required if column not in panel.columns]
    if missing:
        raise ValueError(f"输入面板缺少必要列：{missing}")

    filtered = apply_filters(panel, filters)
    numeric_cols = [y_col, factor, *control_cols]
    for column in numeric_cols:
        filtered[column] = pd.to_numeric(filtered[column], errors="coerce")

    # “完整样本数”按实际完整模型计算，避免用较宽的 Hitrate-only 样本夸大可用性。
    complete = filtered.dropna(subset=numeric_cols).copy()
    complete[date_col] = pd.to_datetime(complete[date_col], errors="coerce")
    complete = complete.dropna(subset=[date_col])
    return complete, control_cols


def matrix_rank_with_const(values: pd.DataFrame) -> tuple[int, int]:
    """返回加截距后的实际矩阵秩和设计矩阵列数。"""
    matrix = values.to_numpy(dtype=float)
    matrix = np.column_stack([np.ones(len(matrix)), matrix])
    return int(np.linalg.matrix_rank(matrix)), int(matrix.shape[1])


def build_monthly_hitrate_identification(
    sample: pd.DataFrame,
    factor: str,
    control_cols: list[str],
    date_col: str,
    min_cross_section_n: int,
) -> pd.DataFrame:
    """逐月检查样本数、Hitrate 变化和两套设计矩阵的秩。"""
    rows: list[dict[str, Any]] = []
    for month, month_df in sample.groupby(date_col, sort=True):
        n_obs = int(len(month_df))
        hitrate = month_df[factor]
        hitrate_rank, hitrate_columns = matrix_rank_with_const(month_df[[factor]])
        full_rank, full_columns = matrix_rank_with_const(
            month_df[[factor, *control_cols]]
        )
        has_variation = bool(hitrate.nunique(dropna=True) >= 2)
        eligible_n = n_obs >= min_cross_section_n
        hitrate_full_rank = hitrate_rank == hitrate_columns
        full_model_rank = full_rank == full_columns
        regression_ready = bool(
            eligible_n and has_variation and hitrate_full_rank and full_model_rank
        )

        reasons: list[str] = []
        if not eligible_n:
            reasons.append("完整样本少于月度门槛")
        if eligible_n and not has_variation:
            reasons.append("Hitrate横截面无变化")
        if eligible_n and has_variation and not hitrate_full_rank:
            reasons.append("const+Hitrate不满秩")
        if eligible_n and has_variation and hitrate_full_rank and not full_model_rank:
            reasons.append("const+Hitrate+controls不满秩")

        rows.append(
            {
                "month_date": pd.Timestamp(month).strftime("%Y-%m-%d"),
                "complete_case_n": n_obs,
                "min_cross_section_n": min_cross_section_n,
                "eligible_n": eligible_n,
                "hitrate_nunique": int(hitrate.nunique(dropna=True)),
                "hitrate_min": float(hitrate.min()),
                "hitrate_max": float(hitrate.max()),
                "hitrate_has_variation": has_variation,
                "hitrate_matrix_rank": hitrate_rank,
                "hitrate_matrix_columns": hitrate_columns,
                "hitrate_full_rank": hitrate_full_rank,
                "full_matrix_rank": full_rank,
                "full_matrix_columns": full_columns,
                "full_model_rank": full_model_rank,
                "regression_ready": regression_ready,
                "failure_reason": ";".join(reasons),
            }
        )
    return pd.DataFrame(rows)


def summarize_one(
    monthly: pd.DataFrame,
    metric: str,
    display_name: str,
    model_key: str,
    spec: dict[str, Any],
    min_ready_months: int,
    min_ready_rate: float,
) -> dict[str, Any]:
    """把单个 Hitrate 候选的逐月结果压缩为一行。"""
    eligible = monthly["eligible_n"].astype(bool)
    variation = monthly["hitrate_has_variation"].astype(bool)
    hitrate_rank_ok = monthly["hitrate_full_rank"].astype(bool)
    full_rank_ok = monthly["full_model_rank"].astype(bool)
    ready = monthly["regression_ready"].astype(bool)
    eligible_months = int(eligible.sum())
    ready_months = int(ready.sum())
    ready_rate = ready_months / eligible_months if eligible_months else np.nan
    exact_reason_counts = Counter(
        reason
        for reason in monthly.loc[~ready, "failure_reason"]
        if isinstance(reason, str) and reason
    )

    row: dict[str, Any] = {
        "metric": metric,
        "display_name": display_name,
        "model_key": model_key,
        "m": int(spec["m"]),
        "n": int(spec["n"]),
        "pairwise": int(spec["pairwise"]),
        "factor": str(spec["factor"]),
        "months_with_complete_cases": int(len(monthly)),
        "eligible_months": eligible_months,
        "hitrate_variation_months": int((eligible & variation).sum()),
        "hitrate_full_rank_months": int((eligible & hitrate_rank_ok).sum()),
        "full_model_rank_months": int((eligible & full_rank_ok).sum()),
        "ready_months": ready_months,
        "ready_rate": ready_rate,
        "failure_reason_counts": json.dumps(
            dict(sorted(exact_reason_counts.items())), ensure_ascii=False
        ),
    }
    row["passes_initial_gate"] = bool(
        ready_months >= min_ready_months and ready_rate >= min_ready_rate
    )
    return row


def plot_heatmap(
    metric_summary: pd.DataFrame,
    display_name: str,
    output_path: Path,
    min_ready_months: int,
    min_ready_rate: float,
) -> None:
    """绘制 Hitrate 连续变量的 6×6 月度识别热力图。"""
    rates = np.full((6, 6), np.nan)
    lookup: dict[tuple[int, int], pd.Series] = {}
    for _, row in metric_summary.iterrows():
        m, n = int(row["m"]), int(row["n"])
        rates[6 - n, m - 1] = float(row["ready_rate"]) * 100
        lookup[(m, n)] = row

    cmap = plt.colormaps["RdYlGn"].copy()
    cmap.set_bad("#d9d9d9")
    fig, ax = plt.subplots(figsize=(10.8, 7.8))
    image = ax.imshow(rates, vmin=0, vmax=100, cmap=cmap, aspect="auto")
    ax.set_xticks(range(6), labels=[str(m) for m in range(1, 7)])
    ax.set_yticks(range(6), labels=[str(n) for n in range(6, 0, -1)])
    ax.set_xlabel("m: return horizon per ranking period (months)")
    ax.set_ylabel("n: number of ranking periods")
    ax.set_title(
        f"{display_name} Hitrate identification\n"
        "Cell = ready months / eligible months"
    )

    for n in range(1, 7):
        for m in range(1, 7):
            y, x = 6 - n, m - 1
            if n == 1:
                ax.text(x, y, "Excluded\n(n=1)", ha="center", va="center", fontsize=9)
                continue
            row = lookup[(m, n)]
            ready = int(row["ready_months"])
            eligible = int(row["eligible_months"])
            rate = float(row["ready_rate"]) * 100
            passed = bool(row["passes_initial_gate"])
            text_color = "white" if rate < 25 or rate > 82 else "black"
            ax.text(
                x,
                y,
                f"{ready}/{eligible}\n{rate:.0f}%" + ("  ✓" if passed else ""),
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold" if passed else "normal",
                color=text_color,
            )

    ax.set_xticks(np.arange(-0.5, 6, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 6, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.86)
    colorbar.set_label("Ready rate (%)")
    fig.text(
        0.5,
        0.015,
        f"✓ Gate: ready months ≥ {min_ready_months} and ready rate ≥ {min_ready_rate:.0%}. "
        "Ready requires N≥50, Hitrate variation, and both design matrices full rank.",
        ha="center",
        fontsize=9.2,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """运行 90 个 Hitrate 候选并写出独立明细、摘要、清单、图和元数据。"""
    args = parse_args()
    panel_path = args.panel if args.panel.is_absolute() else PROJECT_ROOT / args.panel
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else PROJECT_ROOT / args.output_dir
    )
    if not panel_path.exists():
        raise FileNotFoundError(f"找不到 heatmap 面板：{panel_path}")

    configs = {
        metric: load_regression_config(model_key)
        for metric, (model_key, _) in MODEL_SPECS.items()
    }
    specs_by_metric = {
        metric: hitrate_specs(configs[metric], metric) for metric in MODEL_SPECS
    }
    validate_candidate_grid(specs_by_metric)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_summary: list[dict[str, Any]] = []
    all_monthly: list[pd.DataFrame] = []
    controls_by_metric: dict[str, list[str]] = {}
    for metric, (model_key, display_name) in MODEL_SPECS.items():
        config = configs[metric]
        specs = specs_by_metric[metric]
        controls_by_metric[metric] = [
            str(column) for column in config.get("controls", [])
        ]

        # 每次只读取一个口径的 30 个 Hitrate 与公共列，控制大面板的内存占用。
        base_columns = [
            str(config["date_col"]),
            str(config["y"]),
            *controls_by_metric[metric],
            *[str(column) for column in config.get("sample_filters", {})],
        ]
        factor_columns = [str(spec["factor"]) for spec in specs]
        read_columns = list(dict.fromkeys([*base_columns, *factor_columns]))
        panel = pd.read_parquet(panel_path, columns=read_columns)

        for spec in specs:
            factor = str(spec["factor"])
            required = list(dict.fromkeys([*base_columns, factor]))
            sample, control_cols = prepare_hitrate_sample(
                panel[required], config, factor
            )
            monthly = build_monthly_hitrate_identification(
                sample=sample,
                factor=factor,
                control_cols=control_cols,
                date_col=str(config["date_col"]),
                min_cross_section_n=int(config["min_cross_section_n"]),
            )
            monthly.insert(0, "metric", metric)
            monthly.insert(1, "model_key", model_key)
            monthly.insert(2, "m", int(spec["m"]))
            monthly.insert(3, "n", int(spec["n"]))
            monthly.insert(4, "pairwise", int(spec["pairwise"]))
            monthly.insert(5, "factor", factor)
            all_monthly.append(monthly)
            all_summary.append(
                summarize_one(
                    monthly,
                    metric,
                    display_name,
                    model_key,
                    spec,
                    args.min_ready_months,
                    args.min_ready_rate,
                )
            )
        del panel
        gc.collect()

    summary = pd.DataFrame(all_summary).sort_values(["metric", "n", "m"])
    monthly = pd.concat(all_monthly, ignore_index=True).sort_values(
        ["metric", "n", "m", "month_date"]
    )
    passing = summary.loc[summary["passes_initial_gate"]].copy()

    summary.to_csv(output_dir / "winrate_hitrate_identification_summary.csv", index=False)
    monthly.to_csv(output_dir / "winrate_hitrate_monthly_identification.csv", index=False)
    passing.to_csv(output_dir / "passing_hitrate_models.csv", index=False)

    for metric, (_, display_name) in MODEL_SPECS.items():
        plot_heatmap(
            summary.loc[summary["metric"].eq(metric)],
            display_name,
            output_dir / f"{metric}_hitrate_identification_heatmap.png",
            args.min_ready_months,
            args.min_ready_rate,
        )

    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "panel_path": str(panel_path),
        "output_dir": str(output_dir),
        "models_checked": list(MODEL_SPECS),
        "candidate_factors": {
            metric: [str(spec["factor"]) for spec in specs]
            for metric, specs in specs_by_metric.items()
        },
        "specifications_per_model": 30,
        "total_specifications": int(len(summary)),
        "m_values": list(range(1, 7)),
        "n_values": list(range(2, 7)),
        "pairwise_rule": "pairwise=m",
        "identification_conditions": [
            "complete_case_n >= 50",
            "Hitrate has monthly cross-sectional variation",
            "const + Hitrate is full rank",
            "const + Hitrate + controls is full rank",
        ],
        "controls_by_metric": controls_by_metric,
        "initial_gate": {
            "ready_months_at_least": args.min_ready_months,
            "ready_rate_at_least": args.min_ready_rate,
        },
        "passing_model_count": int(len(passing)),
        "passing_model_count_by_metric": {
            metric: int(passing["metric"].eq(metric).sum()) for metric in MODEL_SPECS
        },
        "reads_cumulative_dummy_passing_models": False,
        "effect_regressions_run": False,
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：{len(summary)} 个 Hitrate 规格；通过初步门槛 {len(passing)} 个。")
    for metric in MODEL_SPECS:
        print(f"{metric}：{int(passing['metric'].eq(metric).sum())}/30 通过。")
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    main()
