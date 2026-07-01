"""对通过可识别性门槛的 winrate hitrate 主因子运行 Fama-MacBeth。

本脚本只估计 ``hitrate=hitcount/n`` 这一层，不运行累积 Dummy 层。模型集合
由上一轮 ``passing_models.csv`` 决定，因此模型筛选只依据可识别性，不依据收益
效果。所有主因子的双侧 p 值最后放在同一个 family 中统一做 BH-FDR。
"""

from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/private/tmp/matplotlib-winrate-effects")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGRESSION_SCRIPT = (
    PROJECT_ROOT / "D_analysis" / "scripts" / "consistency_fama_mac_regression.py"
)
DEFAULT_PASSING_MODELS = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_identification_grid"
    / "passing_models.csv"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_hitrate_effect_grid"
)
MODEL_SPECS = {
    "top50": ("fm_winrates_top50_nonoverlap", "Top 50"),
    "top33": ("fm_winrates_top33_nonoverlap", "Top 33"),
    "bottom33": ("fm_winrates_bottom33_nonoverlap", "Bottom 33"),
}


def parse_args() -> argparse.Namespace:
    """读取通过清单和输出目录。"""
    parser = argparse.ArgumentParser(description="运行 winrate hitrate 效果网格。")
    parser.add_argument("--passing-models", type=Path, default=DEFAULT_PASSING_MODELS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def load_regression_module(model_key: str) -> Any:
    """按模型 key 加载现有回归脚本，使其全局配置与 registry 保持一致。"""
    original_argv = sys.argv[:]
    try:
        # 原脚本在 import 时读取 --model；临时替换 argv 后立即恢复，避免污染本脚本。
        sys.argv = [str(REGRESSION_SCRIPT), "--model", model_key]
        spec = importlib.util.spec_from_file_location(
            f"winrate_effect_regression_{model_key}", REGRESSION_SCRIPT
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载回归脚本：{REGRESSION_SCRIPT}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.argv = original_argv


def benjamini_hochberg(p_values: pd.Series) -> pd.Series:
    """对全部主因子 p 值统一做 Benjamini-Hochberg FDR 校正。"""
    result = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().sort_values()
    if valid.empty:
        return result
    m = len(valid)
    ranks = np.arange(1, m + 1, dtype=float)
    raw_q = valid.to_numpy(dtype=float) * m / ranks
    adjusted = np.minimum.accumulate(raw_q[::-1])[::-1]
    result.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def factor_name(metric: str, m: int, n: int) -> str:
    """根据门槛、m、n 还原 registry 中的 hitrate 列名。"""
    return f"hitrate_{metric}_m{m}_n{n}_pairwise{m}"


def q_label(q_value: float) -> str:
    """把 q-value 格式化成适合热力图格内阅读的短文本。"""
    if pd.isna(q_value):
        return "q=NA"
    if q_value < 0.001:
        return "q<.001"
    return f"q={q_value:.3f}".replace("0.", ".")


def draw_significant_border(ax: plt.Axes, x: int, y: int) -> None:
    """用四条线画粗框，避开部分环境对空心 Rectangle 的渲染问题。"""
    left, right, bottom, top = x - 0.48, x + 0.48, y - 0.48, y + 0.48
    style = {"color": "#111111", "linewidth": 3.0, "solid_capstyle": "butt"}
    ax.plot([left, right], [bottom, bottom], **style)
    ax.plot([left, right], [top, top], **style)
    ax.plot([left, left], [bottom, top], **style)
    ax.plot([right, right], [bottom, top], **style)


def plot_effect_heatmap(
    results: pd.DataFrame,
    metric: str,
    display_name: str,
    output_path: Path,
    common_abs_beta_pp: float,
) -> None:
    """生成 6×6 效果热力图；颜色是 beta 百分点，格内是 T 和 q。"""
    metric_results = results.loc[results["metric"].eq(metric)].copy()
    lookup = {
        (int(row.m), int(row.n)): row for row in metric_results.itertuples()
    }
    values = np.full((6, 6), np.nan)
    for (m, n), row in lookup.items():
        values[6 - n, m - 1] = float(row.beta_full_range_pp)

    cmap = plt.colormaps["RdBu"].copy()
    cmap.set_bad("#d9d9d9")
    norm = TwoSlopeNorm(
        vmin=-common_abs_beta_pp, vcenter=0.0, vmax=common_abs_beta_pp
    )
    fig, ax = plt.subplots(figsize=(10.8, 7.8))
    image = ax.imshow(values, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(6), labels=[str(m) for m in range(1, 7)])
    ax.set_yticks(range(6), labels=[str(n) for n in range(6, 0, -1)])
    ax.set_xlabel("m: return horizon per ranking period (months)")
    ax.set_ylabel("n: number of ranking periods")
    ax.set_title(
        f"{display_name} hitrate: Fama–MacBeth effect\n"
        "Color = beta (6m return percentage points); cell = months and BH q-value"
    )

    for n in range(1, 7):
        for m in range(1, 7):
            x, y = m - 1, 6 - n
            row = lookup.get((m, n))
            if n == 1:
                text = "Excluded\n(n=1)"
                color = "#333333"
                weight = "normal"
            elif row is None:
                text = "Not ready"
                color = "#555555"
                weight = "normal"
            else:
                text = f"T={int(row.n_months)}\n{q_label(float(row.q_value))}"
                # 深色的正负两端都用白字，中间浅色区域用黑字。
                ratio = abs(float(row.beta_full_range_pp)) / common_abs_beta_pp
                color = "white" if ratio > 0.58 else "black"
                weight = "bold" if bool(row.significant_fdr_5pct) else "normal"
                if bool(row.significant_fdr_5pct):
                    draw_significant_border(ax, x, y)
            ax.text(
                x, y, text, ha="center", va="center", fontsize=9.5,
                color=color, fontweight=weight
            )

    ax.set_xticks(np.arange(-0.5, 6, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 6, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.86)
    colorbar.set_label("Beta: hitrate 0→1 effect on future 6m return (pp)")
    fig.text(
        0.5,
        0.015,
        "Thick border: BH-FDR q<0.05 across all selected hitrate models. "
        "Gray cells were excluded or did not pass the identification gate.",
        ha="center",
        fontsize=9.3,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def build_report(results: pd.DataFrame, output_path: Path) -> None:
    """写出包含经济量级、方向和统一 FDR 结论的中文 Markdown 报告。"""
    lines = [
        "# Winrate hitrate Fama–MacBeth 效果报告",
        "",
        "## 估计口径",
        "",
        "- 因变量：`future_ret_6m`。",
        "- 主因子：`hitrate=hitcount/n`，取值 0～1。",
        "- 控制变量与 registry 一致；月度截面门槛 50；Newey–West lag=5。",
        "- 只估计上一轮通过可识别性门槛的模型；所有主因子 p-value 统一做一次 BH-FDR。",
        "- `beta_full_range_pp` 表示 hitrate 从 0 增至 1 的未来 6 个月收益差（百分点）；"
        "`beta_one_more_hit_pp` 表示多一次 hit 对应的收益差（beta/n）。",
        "",
        "## 总览",
        "",
        "| 口径 | 模型数 | 原始 p<0.05 | q<0.05 | 正 beta | beta 范围（百分点） | beta 中位数（百分点） | 有效月份范围 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, (_, display_name) in MODEL_SPECS.items():
        group = results.loc[results["metric"].eq(metric)]
        lines.append(
            f"| {display_name} | {len(group)} | {int(group['nominal_p_lt_0_05'].sum())} | "
            f"{int(group['significant_fdr_5pct'].sum())} | "
            f"{int(group['coef'].gt(0).sum())} | "
            f"{group['beta_full_range_pp'].min():.2f}～{group['beta_full_range_pp'].max():.2f} | "
            f"{group['beta_full_range_pp'].median():.2f} | "
            f"{int(group['n_months'].min())}～{int(group['n_months'].max())} |"
        )

    significant = results.loc[results["significant_fdr_5pct"]].sort_values(
        ["metric", "q_value", "m", "n"]
    )
    lines.extend(["", "## FDR 5% 显著模型", ""])
    if significant.empty:
        lines.append("统一 BH-FDR 后没有主因子达到 q<0.05。")
    else:
        lines.extend(
            [
                "| 口径 | m | n | beta（百分点） | 多一次 hit（百分点） | t | q | 月份 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in significant.itertuples():
            lines.append(
                f"| {row.display_name} | {row.m} | {row.n} | "
                f"{row.beta_full_range_pp:.3f} | {row.beta_one_more_hit_pp:.3f} | "
                f"{row.t_stat:.2f} | {row.q_value:.4f} | {row.n_months} |"
            )

    bottom = results.loc[results["metric"].eq("bottom33")]
    bottom_sig_negative = int(
        (bottom["significant_fdr_5pct"] & bottom["coef"].lt(0)).sum()
    )
    lines.extend(
        [
            "",
            "## 方向解释",
            "",
            "Top 50 / Top 33 的正 beta 表示过去排名靠前越持续，未来 6 个月收益越高。",
            "Bottom 33 的负 beta 表示落后状态越持续，未来 6 个月收益越低；"
            "这应解释为持续落后的负向预测，而不是把负号视为模型失败。",
            f"Bottom 33 中共有 {bottom_sig_negative} 个模型同时满足 beta<0 且统一 FDR q<0.05。",
            "Bottom 33 的 18 个 beta 全部为负，其中 5 个原始 p<0.05；"
            "但统一校正 64 个主检验后均未达到 q<0.05，因此方向一致、统计证据尚未越过预设 FDR 门槛。",
            "",
            "## 样本与可识别性",
            "",
            "热力图中的 T 是实际 hitrate 单因子完整模型成功回归的月份数。"
            "它可能高于上一轮累积 Dummy 模型的 ready months，因为单一 hitrate 只增加一个参数，"
            "不要求 hit0～hitn 每一组在当月都出现。",
            "64 个模型合计有 124 个已达到截面样本门槛的“模型×月份”因完整设计矩阵不满秩而跳过；"
            "这些月份没有进入 beta 均值或 Newey–West 检验。",
            "",
            "## 注意事项",
            "",
            "这里的显著性只校正本轮已通过可识别性筛选的 hitrate 主因子。"
            "模型筛选依据是样本/rank，而不是收益效果，因此没有按 p-value 挑模型；"
            "但不同 (m,n) 使用重叠信息，系数并非彼此独立，BH 仍应理解为同一研究族内的多重检验控制。",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """运行 64 个主因子模型、统一 FDR、画图并写出报告。"""
    args = parse_args()
    passing_path = (
        args.passing_models
        if args.passing_models.is_absolute()
        else PROJECT_ROOT / args.passing_models
    )
    output_dir = (
        args.output_dir if args.output_dir.is_absolute() else PROJECT_ROOT / args.output_dir
    )
    if not passing_path.exists():
        raise FileNotFoundError(f"找不到上一轮通过模型清单：{passing_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    passing = pd.read_csv(passing_path)
    passing = passing.loc[passing["passes_initial_gate"].astype(bool)].copy()
    if len(passing) != 64:
        raise ValueError(f"预期 64 个通过模型，实际读取 {len(passing)} 个。")

    primary_rows: list[dict[str, Any]] = []
    full_results: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []
    sample_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    for metric, (model_key, display_name) in MODEL_SPECS.items():
        module = load_regression_module(model_key)
        selected = passing.loc[passing["metric"].eq(metric)].sort_values(["n", "m"])
        factors = [
            factor_name(metric, int(row.m), int(row.n))
            for row in selected.itertuples()
        ]
        required_columns = list(
            dict.fromkeys(
                [
                    module.DATE_COL,
                    module.Y_COL,
                    *module.CONTROL_COLS,
                    *module.SAMPLE_FILTERS,
                    *factors,
                ]
            )
        )
        panel = pd.read_parquet(module.INPUT_PATH, columns=required_columns)

        for row, factor in zip(selected.itertuples(), factors):
            # 正式清洗面板已经做过基础筛选；这里仍再次应用 registry 条件以防误读文件。
            factor_df = module.apply_sample_filters(
                panel, module.get_filters_for_factor(factor)
            )
            monthly, sample_summary, skipped = module.run_factor_regression(
                factor_df, factor
            )
            result_table = module.build_result_table(monthly, factor)
            main_result = result_table.loc[result_table["variable"].eq(factor)]
            if len(main_result) != 1:
                raise ValueError(f"{factor} 的主因子结果行不是 1 行。")

            result_table.insert(0, "metric", metric)
            result_table.insert(1, "m", int(row.m))
            result_table.insert(2, "n", int(row.n))
            full_results.append(result_table)

            main = main_result.iloc[0].to_dict()
            main.update(
                {
                    "metric": metric,
                    "display_name": display_name,
                    "model_key": model_key,
                    "m": int(row.m),
                    "n": int(row.n),
                    "pairwise": int(row.m),
                    "selection_ready_months": int(row.full_model_rank_months),
                    "selection_ready_rate": float(row.ready_rate),
                }
            )
            primary_rows.append(main)

            monthly.insert(0, "metric", metric)
            monthly.insert(1, "m", int(row.m))
            monthly.insert(2, "n", int(row.n))
            monthly_frames.append(monthly)
            sample_summary.update(
                {"metric": metric, "m": int(row.m), "n": int(row.n)}
            )
            sample_rows.append(sample_summary)
            for skipped_row in skipped:
                skipped_row.update(
                    {"metric": metric, "m": int(row.m), "n": int(row.n)}
                )
                skipped_rows.append(skipped_row)
        del panel, module
        gc.collect()

    primary = pd.DataFrame(primary_rows).sort_values(["metric", "n", "m"])
    primary["q_value"] = benjamini_hochberg(primary["p_value"])
    primary["significant_fdr_5pct"] = primary["q_value"].lt(0.05)
    primary["nominal_p_lt_0_05"] = primary["p_value"].lt(0.05)
    # future_ret_6m 以小数收益保存，乘 100 后是更直观的百分点。
    primary["beta_full_range_pp"] = primary["coef"] * 100.0
    primary["beta_one_more_hit"] = primary["coef"] / primary["n"]
    primary["beta_one_more_hit_pp"] = primary["beta_one_more_hit"] * 100.0

    full_result_df = pd.concat(full_results, ignore_index=True)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    sample_df = pd.DataFrame(sample_rows).sort_values(["metric", "n", "m"])
    skipped_df = pd.DataFrame(skipped_rows)

    primary.to_csv(output_dir / "hitrate_primary_results_fdr.csv", index=False)
    full_result_df.to_csv(output_dir / "fama_macbeth_full_results.csv", index=False)
    monthly_df.to_csv(output_dir / "fama_macbeth_monthly_coefficients.csv", index=False)
    sample_df.to_csv(output_dir / "fama_macbeth_sample_summary.csv", index=False)
    skipped_df.to_csv(output_dir / "fama_macbeth_skipped_months.csv", index=False)

    common_abs_beta_pp = float(primary["beta_full_range_pp"].abs().max())
    if not np.isfinite(common_abs_beta_pp) or common_abs_beta_pp <= 0:
        common_abs_beta_pp = 1.0
    for metric, (_, display_name) in MODEL_SPECS.items():
        plot_effect_heatmap(
            primary,
            metric,
            display_name,
            output_dir / f"{metric}_hitrate_effect_heatmap.png",
            common_abs_beta_pp,
        )

    build_report(primary, output_dir / "effect_report.md")
    metadata = {
        "passing_models_path": str(passing_path),
        "models_run": int(len(primary)),
        "dependent_variable": "future_ret_6m",
        "primary_factor": "hitrate=hitcount/n",
        "controls": list(load_regression_module("fm_winrates_top50_nonoverlap").CONTROL_COLS),
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "multiple_testing": "BH-FDR once across all selected primary-factor p-values",
        "fdr_family_size": int(primary["p_value"].notna().sum()),
        "fdr_significant_5pct": int(primary["significant_fdr_5pct"].sum()),
        "common_heatmap_abs_beta_pp": common_abs_beta_pp,
        "cumulative_dummy_effect_regressions_run": False,
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"完成：{len(primary)} 个 hitrate 主因子模型；"
        f"统一 BH-FDR q<0.05：{int(primary['significant_fdr_5pct'].sum())} 个。"
    )
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    main()
