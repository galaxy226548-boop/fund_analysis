"""批量检查三种非重叠 winrate 模型的月度样本可识别性。

本脚本只检查完整样本数和设计矩阵秩，不估计 Fama-MacBeth 收益效果。
每个规格使用累积 Dummy（Dk=1(hitcount>=k)），并把它们还原成精确的
hit0～hitn 组，以便报告最小组别样本数和具体缺失组。
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any

# 避免 matplotlib 在用户目录写字体缓存；项目工作区只保存最终图表。
os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib-winrate-identification")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECK_PATH = PROJECT_ROOT / "D_analysis" / "scripts" / "winrates_check.py"
DEFAULT_PANEL = (
    PROJECT_ROOT / "A_data" / "output" / "panel_base_heatmap_m1_12_n1_12.parquet"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_identification_grid"
)
MODEL_SPECS = {
    "top50": ("fm_winrates_top50_nonoverlap", "Top 50"),
    "top33": ("fm_winrates_top33_nonoverlap", "Top 33"),
    "bottom33": ("fm_winrates_bottom33_nonoverlap", "Bottom 33"),
}
LABEL_PATTERN = re.compile(
    r"^winrate_cumulative_m(?P<m>[1-6])_n(?P<n>[1-6])_pairwise(?P<pairwise>[1-6])$"
)


def load_check_module() -> Any:
    """按文件路径加载现有诊断函数，避免复制两套 rank 检查逻辑。"""
    spec = importlib.util.spec_from_file_location("winrates_check_grid", CHECK_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载诊断模块：{CHECK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    """读取路径和初步通过门槛；默认值对应本轮研究设计。"""
    parser = argparse.ArgumentParser(description="批量检查 winrate 模型月度可识别性。")
    parser.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--min-ready-months", type=int, default=60)
    parser.add_argument("--min-ready-rate", type=float, default=0.70)
    return parser.parse_args()


def cumulative_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    """选出 m=1..6、n=2..6 且 pairwise=m 的累积 Dummy 规格。"""
    suffixes = dict(config.get("factor_group_suffixes", {}))
    result: list[dict[str, Any]] = []
    for raw_factor in config.get("factors", []):
        if not isinstance(raw_factor, (tuple, list)):
            continue
        factor = tuple(str(column) for column in raw_factor)
        label = str(suffixes.get(factor, ""))
        match = LABEL_PATTERN.fullmatch(label)
        if match is None:
            continue
        m = int(match.group("m"))
        n = int(match.group("n"))
        pairwise = int(match.group("pairwise"))
        if n >= 2 and pairwise == m:
            result.append(
                {"factor_spec": factor, "factor": label, "m": m, "n": n}
            )
    result.sort(key=lambda item: (item["n"], item["m"]))
    if len(result) != 30:
        raise ValueError(f"预期每个口径有 30 个规格，实际找到 {len(result)} 个。")
    return result


def broad_failure_counts(monthly: pd.DataFrame) -> dict[str, int]:
    """把逐月的细分原因压缩成稳定的四类失败计数。"""
    eligible = monthly["eligible_n"].astype(bool)
    dummy_ok = monthly["dummy_full_rank"].astype(bool)
    full_ok = monthly["full_model_rank"].astype(bool)
    return {
        "below_cross_section_threshold_months": int((~eligible).sum()),
        "missing_dummy_group_months": int(
            (eligible & ~dummy_ok & monthly["missing_groups"].fillna("").ne("")).sum()
        ),
        "other_dummy_rank_failure_months": int(
            (eligible & ~dummy_ok & monthly["missing_groups"].fillna("").eq("")).sum()
        ),
        "control_rank_failure_months": int((eligible & dummy_ok & ~full_ok).sum()),
    }


def summarize_one(
    monthly: pd.DataFrame,
    metric: str,
    display_name: str,
    model_key: str,
    spec: dict[str, Any],
    min_ready_months: int,
    min_ready_rate: float,
) -> dict[str, Any]:
    """把一个规格的逐月结果压缩成用户要求的一行。"""
    eligible = monthly["eligible_n"].astype(bool)
    dummy_ok = monthly["dummy_full_rank"].astype(bool)
    full_ok = monthly["full_model_rank"].astype(bool)
    eligible_months = int(eligible.sum())
    ready_months = int((eligible & full_ok).sum())
    ready_rate = ready_months / eligible_months if eligible_months else np.nan

    eligible_group_n = monthly.loc[eligible, "min_group_n"].dropna()
    exact_reason_counts = Counter(
        reason
        for reason in monthly.loc[~monthly["regression_ready"], "failure_reason"]
        if isinstance(reason, str) and reason
    )
    row: dict[str, Any] = {
        "metric": metric,
        "display_name": display_name,
        "model_key": model_key,
        "m": int(spec["m"]),
        "n": int(spec["n"]),
        "pairwise": int(spec["m"]),
        "factor": str(spec["factor"]),
        "eligible_months": eligible_months,
        "dummy_full_rank_months": int((eligible & dummy_ok).sum()),
        "full_model_rank_months": ready_months,
        "ready_rate": ready_rate,
        # 这里取所有合格月份中的最小值；0 表示至少有一个合格月份缺少某个 hit 组。
        "min_group_n": int(eligible_group_n.min()) if not eligible_group_n.empty else np.nan,
        "median_min_group_n": float(eligible_group_n.median())
        if not eligible_group_n.empty
        else np.nan,
        "failure_reason_counts": json.dumps(
            dict(sorted(exact_reason_counts.items())), ensure_ascii=False
        ),
    }
    row.update(broad_failure_counts(monthly))
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
    """画 6×6 热力图；n=1 按研究设计排除并显示为灰色。"""
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
        f"{display_name} win-rate model identification\n"
        "Cell = full-model-rank months / eligible months"
    )

    for n in range(1, 7):
        for m in range(1, 7):
            y, x = 6 - n, m - 1
            if n == 1:
                ax.text(x, y, "Excluded\n(n=1)", ha="center", va="center", fontsize=9)
                continue
            row = lookup[(m, n)]
            ready = int(row["full_model_rank_months"])
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
            # 通过门槛已用粗体和 ✓ 标出。这里不再叠加矩形边框，因为部分
            # macOS/Matplotlib 组合会把空心 patch 错误渲染成黑色实心块。

    ax.set_xticks(np.arange(-0.5, 6, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 6, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.86)
    colorbar.set_label("Ready rate (%)")
    fig.text(
        0.5,
        0.015,
        f"✓ Initial gate: ready months ≥ {min_ready_months} and ready rate ≥ {min_ready_rate:.0%}. "
        "n=1 excluded because consistency is undefined.",
        ha="center",
        fontsize=9.5,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """读取三批必要列，运行 90 个规格并写出表格、图和元数据。"""
    args = parse_args()
    panel_path = args.panel if args.panel.is_absolute() else PROJECT_ROOT / args.panel
    output_dir = (
        args.output_dir
        if args.output_dir.is_absolute()
        else PROJECT_ROOT / args.output_dir
    )
    if not panel_path.exists():
        raise FileNotFoundError(f"找不到 heatmap 面板：{panel_path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    check = load_check_module()

    all_summary: list[dict[str, Any]] = []
    all_monthly: list[pd.DataFrame] = []
    for metric, (model_key, display_name) in MODEL_SPECS.items():
        config = check.load_regression_config(model_key)
        specs = cumulative_specs(config)

        # 每次只读一个口径需要的 120 个 Dummy 及公共字段，降低 1GB 面板的峰值内存。
        base_columns = [
            str(config["date_col"]),
            str(config["y"]),
            *[str(column) for column in config.get("controls", [])],
            *[str(column) for column in config.get("sample_filters", {})],
        ]
        factor_columns = [
            column for spec in specs for column in spec["factor_spec"]
        ]
        read_columns = list(dict.fromkeys([*base_columns, *factor_columns]))
        panel = pd.read_parquet(panel_path, columns=read_columns)

        for spec in specs:
            required = list(dict.fromkeys([*base_columns, *spec["factor_spec"]]))
            sample, factor_cols, control_cols = check.prepare_regression_sample(
                panel[required], config, spec["factor_spec"], spec["factor"]
            )
            monthly = check.build_monthly_identification(
                sample=sample,
                factor_cols=factor_cols,
                control_cols=control_cols,
                date_col=str(config["date_col"]),
                min_cross_section_n=int(config["min_cross_section_n"]),
            )
            monthly.insert(0, "metric", metric)
            monthly.insert(1, "model_key", model_key)
            monthly.insert(2, "m", int(spec["m"]))
            monthly.insert(3, "n", int(spec["n"]))
            monthly.insert(4, "factor", str(spec["factor"]))
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

    summary.to_csv(output_dir / "winrate_identification_summary.csv", index=False)
    monthly.to_csv(output_dir / "winrate_monthly_identification.csv", index=False)
    passing.to_csv(output_dir / "passing_models.csv", index=False)

    for metric, (_, display_name) in MODEL_SPECS.items():
        plot_heatmap(
            summary.loc[summary["metric"].eq(metric)],
            display_name,
            output_dir / f"{metric}_identification_heatmap.png",
            args.min_ready_months,
            args.min_ready_rate,
        )

    metadata = {
        "panel_path": str(panel_path),
        "models_checked": list(MODEL_SPECS),
        "specifications_per_model": 30,
        "total_specifications": int(len(summary)),
        "m_values": list(range(1, 7)),
        "n_values": list(range(2, 7)),
        "pairwise_rule": "pairwise=m",
        "min_cross_section_n": 50,
        "effect_regressions_run": False,
        "initial_gate": {
            "full_model_rank_months_at_least": args.min_ready_months,
            "ready_rate_at_least": args.min_ready_rate,
        },
        "passing_model_count": int(len(passing)),
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：{len(summary)} 个规格；通过初步门槛 {len(passing)} 个。")
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    main()
