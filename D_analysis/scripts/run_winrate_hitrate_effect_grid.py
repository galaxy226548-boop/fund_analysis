"""运行通过独立连续变量识别的 winrate Hitrate 线性主效应网格。

本脚本只估计 ``hitrate=hitcount/n`` 的线性主效应。模型选择来自独立 Hitrate
识别流程，完整候选摘要用于保留未通过识别的格子；脚本不读取累计 Dummy 的通过
清单，也不运行累计 Dummy、联合 Wald 或 IUT 检验。
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
HITRATE_IDENTIFICATION_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_hitrate_identification_grid"
)
DEFAULT_PASSING_HITRATE_MODELS = (
    HITRATE_IDENTIFICATION_DIR / "passing_hitrate_models.csv"
)
DEFAULT_HITRATE_IDENTIFICATION_SUMMARY = (
    HITRATE_IDENTIFICATION_DIR / "winrate_hitrate_identification_summary.csv"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "D_analysis"
    / "output"
    / "fund_consistency"
    / "winrates_hitrate_effect_grid_linear_full"
)
MODEL_SPECS = {
    "top50": ("fm_winrates_top50_nonoverlap", "Top 50"),
    "top33": ("fm_winrates_top33_nonoverlap", "Top 33"),
    "bottom33": ("fm_winrates_bottom33_nonoverlap", "Bottom 33"),
}
GATE_FIELD_CANDIDATES = ("passes_hitrate_gate", "passes_initial_gate")
READY_MONTHS_FIELD_CANDIDATES = ("ready_months", "full_model_rank_months")


def parse_args() -> argparse.Namespace:
    """读取独立 Hitrate 识别文件和新输出目录。"""
    parser = argparse.ArgumentParser(
        description="运行独立连续 Hitrate 识别后的线性主效应网格。"
    )
    parser.add_argument(
        "--passing-hitrate-models",
        type=Path,
        default=DEFAULT_PASSING_HITRATE_MODELS,
        help="独立 Hitrate 识别流程输出的通过模型清单。",
    )
    parser.add_argument(
        "--hitrate-identification-summary",
        type=Path,
        default=DEFAULT_HITRATE_IDENTIFICATION_SUMMARY,
        help="包含90个候选（含未通过模型）的独立 Hitrate 识别摘要。",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def project_path(path: Path) -> Path:
    """把相对路径解释为项目根目录下的路径。"""
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_regression_module(model_key: str) -> Any:
    """按模型 key 加载主回归函数，使控制变量和筛选条件保持一致。"""
    original_argv = sys.argv[:]
    try:
        # 主回归脚本在 import 时解析 --model，因此这里只在加载期间临时替换 argv。
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
    """对成功估计的全部 Hitrate 主因子统一做一次 BH-FDR。"""
    result = pd.Series(np.nan, index=p_values.index, dtype=float)
    valid = p_values.dropna().sort_values()
    if valid.empty:
        return result
    family_size = len(valid)
    ranks = np.arange(1, family_size + 1, dtype=float)
    raw_q = valid.to_numpy(dtype=float) * family_size / ranks
    adjusted = np.minimum.accumulate(raw_q[::-1])[::-1]
    result.loc[valid.index] = np.clip(adjusted, 0.0, 1.0)
    return result


def apply_primary_fdr(results: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """标记成功估计行，并返回动态计算的 FDR family size。"""
    output = results.copy()
    required = ["coef", "t_stat", "p_value", "n_months"]
    missing = [column for column in required if column not in output.columns]
    if missing:
        raise ValueError(f"主结果缺少 FDR 所需字段：{missing}")

    # 没有有效 p 值的模型不能进入 BH family；保留该行便于审计估计失败原因。
    output["estimation_success"] = (
        pd.to_numeric(output["coef"], errors="coerce").notna()
        & pd.to_numeric(output["t_stat"], errors="coerce").notna()
        & pd.to_numeric(output["p_value"], errors="coerce").notna()
        & pd.to_numeric(output["n_months"], errors="coerce").gt(0)
    )
    fdr_p_values = pd.to_numeric(output["p_value"], errors="coerce").where(
        output["estimation_success"]
    )
    output["q_value"] = benjamini_hochberg(fdr_p_values)
    output["significant_fdr_5pct"] = output["q_value"].lt(0.05)
    output["nominal_p_lt_0_05"] = (
        output["estimation_success"]
        & pd.to_numeric(output["p_value"], errors="coerce").lt(0.05)
    )
    return output, int(output["estimation_success"].sum())


def factor_name(metric: str, m: int, n: int) -> str:
    """生成非重叠 Hitrate 字符串因子名。"""
    return f"hitrate_{metric}_m{m}_n{n}_pairwise{m}"


def coerce_boolean(series: pd.Series, field_name: str) -> pd.Series:
    """安全解析 CSV 布尔列，避免字符串 ``False`` 被当成真值。"""
    if pd.api.types.is_bool_dtype(series):
        return series.astype(bool)
    normalized = series.astype("string").str.strip().str.lower()
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
        "yes": True,
        "no": False,
    }
    parsed = normalized.map(mapping)
    if parsed.isna().any():
        bad_values = sorted(series.loc[parsed.isna()].astype(str).unique())
        raise ValueError(f"{field_name} 出现无法识别的布尔值：{bad_values}")
    return parsed.astype(bool)


def first_existing_field(
    columns: pd.Index, candidates: tuple[str, ...], description: str
) -> str:
    """在兼容字段名中选择实际存在的一项，并在缺失时明确报错。"""
    for field in candidates:
        if field in columns:
            return field
    raise ValueError(f"识别文件缺少{description}字段；支持：{list(candidates)}")


def normalize_identification_frame(
    frame: pd.DataFrame, source_name: str
) -> tuple[pd.DataFrame, dict[str, str]]:
    """把上一轮实际字段映射为效果脚本内部的稳定字段。"""
    required = {"metric", "m", "n", "factor", "ready_rate"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{source_name} 缺少必要字段：{missing}")

    gate_field = first_existing_field(
        frame.columns, GATE_FIELD_CANDIDATES, "Hitrate gate"
    )
    ready_months_field = first_existing_field(
        frame.columns, READY_MONTHS_FIELD_CANDIDATES, "ready months"
    )
    output = frame.copy()
    output["passes_hitrate_gate"] = coerce_boolean(
        output[gate_field], gate_field
    )
    output["selection_ready_months"] = pd.to_numeric(
        output[ready_months_field], errors="raise"
    ).astype(int)
    output["selection_ready_rate"] = pd.to_numeric(
        output["ready_rate"], errors="raise"
    )
    output["m"] = pd.to_numeric(output["m"], errors="raise").astype(int)
    output["n"] = pd.to_numeric(output["n"], errors="raise").astype(int)
    return output, {
        "gate_field": gate_field,
        "ready_months_field": ready_months_field,
        "ready_rate_field": "ready_rate",
    }


def validate_candidate_summary(candidates: pd.DataFrame) -> None:
    """确认完整候选网格是三种口径各30个，并明确包含三个 m6_n6。"""
    if set(candidates["metric"].astype(str)) != set(MODEL_SPECS):
        raise AssertionError("识别摘要必须恰好包含 Top50、Top33、Bottom33。")
    if candidates.duplicated(["metric", "m", "n"]).any():
        raise AssertionError("识别摘要存在重复的 metric/m/n 候选。")

    for metric in MODEL_SPECS:
        metric_rows = candidates.loc[candidates["metric"].eq(metric)]
        actual_grid = {
            (int(row.m), int(row.n)) for row in metric_rows.itertuples()
        }
        expected_grid = {(m, n) for m in range(1, 7) for n in range(2, 7)}
        if actual_grid != expected_grid:
            missing = sorted(expected_grid - actual_grid)
            extra = sorted(actual_grid - expected_grid)
            raise AssertionError(
                f"{metric} 候选网格不完整；缺少={missing}，多出={extra}。"
            )
        required_factor = factor_name(metric, 6, 6)
        if required_factor not in set(metric_rows["factor"].astype(str)):
            raise AssertionError(f"{metric} 候选缺少 {required_factor}。")
    if len(candidates) != sum(30 for _ in MODEL_SPECS):
        raise AssertionError(f"完整候选应为90个，实际为 {len(candidates)} 个。")


def validate_passing_models(
    passing: pd.DataFrame, candidates: pd.DataFrame
) -> None:
    """确认通过清单与完整摘要中的 Hitrate gate 完全一致。"""
    if not passing["passes_hitrate_gate"].all():
        raise AssertionError("通过清单中包含未通过独立 Hitrate gate 的模型。")
    if passing.duplicated(["metric", "m", "n"]).any():
        raise AssertionError("通过清单存在重复模型。")

    summary_passed = candidates.loc[
        candidates["passes_hitrate_gate"], ["metric", "m", "n"]
    ]
    passing_keys = {
        (str(row.metric), int(row.m), int(row.n)) for row in passing.itertuples()
    }
    summary_keys = {
        (str(row.metric), int(row.m), int(row.n))
        for row in summary_passed.itertuples()
    }
    if passing_keys != summary_keys:
        raise AssertionError(
            "通过清单与完整识别摘要的 gate 结果不一致；"
            f"仅清单={sorted(passing_keys - summary_keys)}，"
            f"仅摘要={sorted(summary_keys - passing_keys)}。"
        )


def q_label(q_value: float) -> str:
    """把 q-value 格式化成热力图格内短文本。"""
    if pd.isna(q_value):
        return "q=NA"
    if q_value < 0.001:
        return "q<.001"
    return f"q={q_value:.3f}".replace("0.", ".")


def build_effect_grid(
    results: pd.DataFrame,
    candidates: pd.DataFrame,
    metric: str,
) -> tuple[np.ndarray, dict[tuple[int, int], dict[str, Any]]]:
    """构造固定6×6热力图数据，确保失败的 m6_n6 仍保留明确位置。"""
    metric_candidates = candidates.loc[candidates["metric"].eq(metric)]
    candidate_lookup = {
        (int(row.m), int(row.n)): row for row in metric_candidates.itertuples()
    }
    metric_results = results.loc[results["metric"].eq(metric)]
    result_lookup = {
        (int(row.m), int(row.n)): row for row in metric_results.itertuples()
    }

    values = np.full((6, 6), np.nan)
    cells: dict[tuple[int, int], dict[str, Any]] = {}
    for n in range(1, 7):
        for m in range(1, 7):
            if n == 1:
                cells[(m, n)] = {
                    "state": "design_excluded",
                    "text": "Design excluded\n(n=1)",
                }
                continue

            candidate = candidate_lookup.get((m, n))
            if candidate is None:
                raise AssertionError(f"{metric} 热力图缺少候选格 m{m}_n{n}。")
            result = result_lookup.get((m, n))
            if result is not None and bool(result.estimation_success):
                beta_pp = float(result.beta_full_range_pp)
                values[6 - n, m - 1] = beta_pp
                cells[(m, n)] = {
                    "state": "estimated",
                    "text": (
                        f"β={beta_pp:.2f}pp\nT={int(result.n_months)}\n"
                        f"{q_label(float(result.q_value))}"
                    ),
                    "beta_pp": beta_pp,
                    "significant": bool(result.significant_fdr_5pct),
                }
            elif not bool(candidate.passes_hitrate_gate):
                cells[(m, n)] = {
                    "state": "identification_failed",
                    "text": "Hitrate ID\nfailed",
                }
            else:
                cells[(m, n)] = {
                    "state": "regression_failed",
                    "text": "Regression\nfailed",
                }
    return values, cells


def draw_significant_border(ax: plt.Axes, x: int, y: int) -> None:
    """用四条线画显著性粗框，避免空心 patch 的跨平台渲染问题。"""
    left, right, bottom, top = x - 0.48, x + 0.48, y - 0.48, y + 0.48
    style = {"color": "#111111", "linewidth": 3.0, "solid_capstyle": "butt"}
    ax.plot([left, right], [bottom, bottom], **style)
    ax.plot([left, right], [top, top], **style)
    ax.plot([left, left], [bottom, top], **style)
    ax.plot([right, right], [bottom, top], **style)


def plot_effect_heatmap(
    results: pd.DataFrame,
    candidates: pd.DataFrame,
    metric: str,
    display_name: str,
    output_path: Path,
    common_abs_beta_pp: float,
) -> None:
    """基于完整候选网格绘制连续 Hitrate 线性主效应热力图。"""
    values, cells = build_effect_grid(results, candidates, metric)
    cmap = plt.colormaps["RdBu"].copy()
    cmap.set_bad("#d9d9d9")
    norm = TwoSlopeNorm(
        vmin=-common_abs_beta_pp, vcenter=0.0, vmax=common_abs_beta_pp
    )
    fig, ax = plt.subplots(figsize=(11.2, 8.2))
    image = ax.imshow(values, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(6), labels=[str(m) for m in range(1, 7)])
    ax.set_yticks(range(6), labels=[str(n) for n in range(6, 0, -1)])
    ax.set_xlabel("m: return horizon per ranking period (months)")
    ax.set_ylabel("n: number of ranking periods")
    ax.set_title(
        f"{display_name} continuous Hitrate main effect\n"
        "Color = beta (6m return pp); cell = beta, months and BH q-value"
    )

    for (m, n), cell in cells.items():
        x, y = m - 1, 6 - n
        state = str(cell["state"])
        if state == "estimated":
            ratio = abs(float(cell["beta_pp"])) / common_abs_beta_pp
            color = "white" if ratio > 0.58 else "black"
            weight = "bold" if bool(cell["significant"]) else "normal"
            if bool(cell["significant"]):
                draw_significant_border(ax, x, y)
        else:
            color = "#444444"
            weight = "normal"
        ax.text(
            x,
            y,
            str(cell["text"]),
            ha="center",
            va="center",
            fontsize=8.7,
            color=color,
            fontweight=weight,
        )

    ax.set_xticks(np.arange(-0.5, 6, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 6, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.5)
    ax.tick_params(which="minor", bottom=False, left=False)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.86)
    colorbar.set_label("Beta: Hitrate 0→1 effect on future 6m return (pp)")
    fig.text(
        0.5,
        0.015,
        "Thick border: q<0.05 in one BH-FDR family across all successful Hitrate effects. "
        "Gray: n=1 excluded, Hitrate ID failed, or regression failed.",
        ha="center",
        fontsize=9.2,
        color="#444444",
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    fig.savefig(output_path, dpi=220, bbox_inches="tight")
    plt.close(fig)


def build_report(
    results: pd.DataFrame,
    candidates: pd.DataFrame,
    output_path: Path,
    fdr_family_size: int,
    skipped_month_count: int,
) -> None:
    """按实际数据动态生成连续 Hitrate 主效应中文报告。"""
    successful = results.loc[results["estimation_success"]].copy()
    lines = [
        "# 连续 Hitrate 独立识别后的 Fama–MacBeth 主效应报告",
        "",
        "## 估计与多重检验口径",
        "",
        "- 因变量：`future_ret_6m`；主因子：`hitrate=hitcount/n`。",
        "- 只运行独立连续 Hitrate 识别通过的模型；不使用累计 Dummy 通过清单。",
        "- n=1 按研究设计排除；完整候选为 m=1..6、n=2..6、pairwise=m。",
        f"- 本轮成功估计 {len(successful)} 个主因子，全部放入同一个 BH-FDR family；family size={fdr_family_size}。",
        "- FDR family 不包含累计 Dummy、联合 Wald 或 IUT 检验。",
        "- `beta_full_range_pp` 是 Hitrate 从0增至1对应的未来6个月收益差（百分点）。",
        "",
        "## 动态结果总览",
        "",
        "| 口径 | 候选 | 识别通过 | 成功估计 | 正 beta | 负 beta | 原始 p<0.05 | q<0.05 | beta范围（pp） | 有效月份范围 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for metric, (_, display_name) in MODEL_SPECS.items():
        metric_candidates = candidates.loc[candidates["metric"].eq(metric)]
        group = successful.loc[successful["metric"].eq(metric)]
        beta_range = (
            f"{group['beta_full_range_pp'].min():.2f}～{group['beta_full_range_pp'].max():.2f}"
            if not group.empty
            else "NA"
        )
        month_range = (
            f"{int(group['n_months'].min())}～{int(group['n_months'].max())}"
            if not group.empty
            else "NA"
        )
        lines.append(
            f"| {display_name} | {len(metric_candidates)} | "
            f"{int(metric_candidates['passes_hitrate_gate'].sum())} | {len(group)} | "
            f"{int(group['coef'].gt(0).sum())} | {int(group['coef'].lt(0).sum())} | "
            f"{int(group['nominal_p_lt_0_05'].sum())} | "
            f"{int(group['significant_fdr_5pct'].sum())} | {beta_range} | {month_range} |"
        )

    significant = successful.loc[successful["significant_fdr_5pct"]].sort_values(
        ["metric", "q_value", "m", "n"]
    )
    lines.extend(["", "## BH-FDR 5% 显著模型", ""])
    if significant.empty:
        lines.append("统一 BH-FDR 后没有连续 Hitrate 主因子达到 q<0.05。")
    else:
        lines.extend(
            [
                "| 口径 | m | n | beta（pp） | t | 原始p | q | 月份 |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in significant.itertuples():
            lines.append(
                f"| {row.display_name} | {row.m} | {row.n} | "
                f"{row.beta_full_range_pp:.3f} | {row.t_stat:.2f} | "
                f"{row.p_value:.5f} | {row.q_value:.5f} | {row.n_months} |"
            )

    failed = candidates.loc[~candidates["passes_hitrate_gate"]].sort_values(
        ["metric", "n", "m"]
    )
    lines.extend(["", "## 未通过连续 Hitrate 识别的候选", ""])
    if failed.empty:
        lines.append("全部候选均通过连续 Hitrate 识别。")
    else:
        lines.extend(
            [
                "| 口径 | m | n | eligible months | ready months | ready rate | 失败原因 |",
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for row in failed.itertuples():
            reason = str(getattr(row, "failure_reason_counts", ""))
            lines.append(
                f"| {row.display_name} | {row.m} | {row.n} | "
                f"{int(row.eligible_months)} | {int(row.selection_ready_months)} | "
                f"{float(row.selection_ready_rate):.1%} | {reason} |"
            )

    lines.extend(
        [
            "",
            "## 方向与样本说明",
            "",
        ]
    )
    for metric, (_, display_name) in MODEL_SPECS.items():
        group = successful.loc[successful["metric"].eq(metric)]
        lines.append(
            f"- {display_name}：正 beta {int(group['coef'].gt(0).sum())} 个，"
            f"负 beta {int(group['coef'].lt(0).sum())} 个；"
            f"原始 p<0.05 为 {int(group['nominal_p_lt_0_05'].sum())} 个，"
            f"统一 q<0.05 为 {int(group['significant_fdr_5pct'].sum())} 个。"
        )
    lines.extend(
        [
            f"- 合格截面月份中共有 {skipped_month_count} 个“模型×月份”因实际回归矩阵问题被跳过。",
            "- Top口径正 beta 表示靠前状态越持续、未来收益越高；Bottom口径负 beta 表示落后状态越持续、未来收益越低。",
            "- 各 (m,n) 使用重叠信息，BH 结果应理解为同一研究族内的多重检验控制。",
        ]
    )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_identification_gate_metadata(passing_path: Path) -> dict[str, Any]:
    """读取同目录 metadata，用于记录实际 gate 门槛和字段语义。"""
    metadata_path = passing_path.parent / "run_metadata.json"
    if not metadata_path.exists():
        return {}
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def main() -> None:
    """运行所有通过独立 Hitrate 识别的模型，统一 FDR 并写出新结果。"""
    args = parse_args()
    passing_path = project_path(args.passing_hitrate_models)
    identification_summary_path = project_path(args.hitrate_identification_summary)
    output_dir = project_path(args.output_dir)
    if not passing_path.exists():
        raise FileNotFoundError(f"找不到独立 Hitrate 通过清单：{passing_path}")
    if not identification_summary_path.exists():
        raise FileNotFoundError(
            f"找不到完整 Hitrate 识别摘要：{identification_summary_path}"
        )

    passing_raw = pd.read_csv(passing_path)
    candidates_raw = pd.read_csv(identification_summary_path)
    passing, passing_fields = normalize_identification_frame(
        passing_raw, "Hitrate 通过清单"
    )
    candidates, summary_fields = normalize_identification_frame(
        candidates_raw, "Hitrate 识别摘要"
    )
    validate_candidate_summary(candidates)
    validate_passing_models(passing, candidates)
    identification_metadata = read_identification_gate_metadata(passing_path)
    gate_metadata = dict(identification_metadata.get("initial_gate", {}))
    min_ready_months = gate_metadata.get("ready_months_at_least")

    output_dir.mkdir(parents=True, exist_ok=True)
    primary_rows: list[dict[str, Any]] = []
    full_results: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []
    sample_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []

    for metric, (model_key, display_name) in MODEL_SPECS.items():
        module = load_regression_module(model_key)
        selected = passing.loc[passing["metric"].eq(metric)].sort_values(["n", "m"])
        factors = [str(row.factor) for row in selected.itertuples()]
        for row, factor in zip(selected.itertuples(), factors):
            expected = factor_name(metric, int(row.m), int(row.n))
            if factor != expected:
                raise AssertionError(f"识别清单因子名不符合窗口：{factor} != {expected}")

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
            # 再次应用 registry 筛选，防止清洗面板被替换后样本口径静默变化。
            factor_df = module.apply_sample_filters(
                panel, module.get_filters_for_factor(factor)
            )
            monthly, sample_summary, skipped = module.run_factor_regression(
                factor_df, factor
            )
            result_table = module.build_result_table(monthly, factor)
            main_result = result_table.loc[result_table["variable"].eq(factor)]
            if len(main_result) != 1:
                raise ValueError(f"{factor} 的主因子结果行不是1行。")

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
                    "selection_ready_months": int(row.selection_ready_months),
                    "selection_full_model_rank_months": int(
                        getattr(row, "full_model_rank_months")
                    ),
                    "selection_ready_rate": float(row.selection_ready_rate),
                    "selection_gate_field": passing_fields["gate_field"],
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
    primary, fdr_family_size = apply_primary_fdr(primary)
    # future_ret_6m 以小数收益保存，乘100后转换为百分点。
    primary["beta_full_range_pp"] = primary["coef"] * 100.0
    primary["beta_one_more_hit"] = primary["coef"] / primary["n"]
    primary["beta_one_more_hit_pp"] = primary["beta_one_more_hit"] * 100.0

    if min_ready_months is not None:
        too_few = primary.loc[
            primary["estimation_success"]
            & primary["n_months"].lt(int(min_ready_months))
        ]
        if not too_few.empty:
            bad = too_few[["metric", "m", "n", "n_months"]].to_dict("records")
            raise AssertionError(
                f"存在实际回归月份少于识别门槛却进入结果的模型：{bad}"
            )

    full_result_df = pd.concat(full_results, ignore_index=True)
    monthly_df = pd.concat(monthly_frames, ignore_index=True)
    sample_df = pd.DataFrame(sample_rows).sort_values(["metric", "n", "m"])
    skipped_df = pd.DataFrame(skipped_rows)

    primary.to_csv(output_dir / "hitrate_primary_results_fdr.csv", index=False)
    full_result_df.to_csv(output_dir / "fama_macbeth_full_results.csv", index=False)
    monthly_df.to_csv(output_dir / "fama_macbeth_monthly_coefficients.csv", index=False)
    sample_df.to_csv(output_dir / "fama_macbeth_sample_summary.csv", index=False)
    skipped_df.to_csv(output_dir / "fama_macbeth_skipped_months.csv", index=False)

    successful = primary.loc[primary["estimation_success"]]
    common_abs_beta_pp = float(successful["beta_full_range_pp"].abs().max())
    if not np.isfinite(common_abs_beta_pp) or common_abs_beta_pp <= 0:
        common_abs_beta_pp = 1.0
    for metric, (_, display_name) in MODEL_SPECS.items():
        plot_effect_heatmap(
            primary,
            candidates,
            metric,
            display_name,
            output_dir / f"{metric}_hitrate_effect_heatmap.png",
            common_abs_beta_pp,
        )

    skipped_month_count = int(len(skipped_df))
    build_report(
        primary,
        candidates,
        output_dir / "effect_report.md",
        fdr_family_size,
        skipped_month_count,
    )
    metadata = {
        "passing_hitrate_models_path": str(passing_path),
        "hitrate_identification_summary_path": str(identification_summary_path),
        "identification_field_mapping": {
            "passing_file": passing_fields,
            "summary_file": summary_fields,
            "internal_gate_field": "passes_hitrate_gate",
        },
        "identification_gate": gate_metadata,
        "candidate_models": int(len(candidates)),
        "identification_passed_models": int(len(passing)),
        "models_run": int(len(primary)),
        "models_successfully_estimated": fdr_family_size,
        "successful_models_by_metric": {
            metric: int(
                (primary["metric"].eq(metric) & primary["estimation_success"]).sum()
            )
            for metric in MODEL_SPECS
        },
        "dependent_variable": "future_ret_6m",
        "primary_factor": "continuous hitrate=hitcount/n",
        "controls": list(
            load_regression_module("fm_winrates_top50_nonoverlap").CONTROL_COLS
        ),
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "multiple_testing": (
            "One BH-FDR family across every successfully estimated continuous "
            "Hitrate primary factor; excludes cumulative Dummy, Wald and IUT tests"
        ),
        "fdr_family_size": fdr_family_size,
        "fdr_significant_5pct": int(primary["significant_fdr_5pct"].sum()),
        "common_heatmap_abs_beta_pp": common_abs_beta_pp,
        "skipped_model_months_after_eligibility": skipped_month_count,
        "models_below_identification_ready_month_threshold_in_results": 0,
        "heatmap_grid": {
            "m_values": list(range(1, 7)),
            "n_values": list(range(2, 7)),
            "n1_status": "excluded_by_research_design",
            "failed_identification_cells_retained": True,
        },
        "cumulative_dummy_effect_regressions_run": False,
        "joint_wald_or_iut_tests_in_fdr": False,
    }
    (output_dir / "run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"完成：独立 Hitrate 识别通过 {len(passing)} 个，"
        f"成功估计并进入统一 BH-FDR {fdr_family_size} 个；"
        f"q<0.05 为 {int(primary['significant_fdr_5pct'].sum())} 个。"
    )
    for metric in MODEL_SPECS:
        count = int(
            (primary["metric"].eq(metric) & primary["estimation_success"]).sum()
        )
        print(f"{metric}：成功估计 {count} 个。")
    print(f"输出目录：{output_dir}")


if __name__ == "__main__":
    main()
