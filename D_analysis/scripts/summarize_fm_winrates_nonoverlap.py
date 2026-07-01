"""汇总 non-overlap 胜率模型的可识别性与相邻 beta 差额，并生成诊断图。

脚本只读取现有回归输出，不会改动任何原始结果。输出集中放到
``D_analysis/output/fund_consistency/fm_winrates_nonoverlap_review``，便于复核。
"""

import os
from pathlib import Path

# 项目环境无法写入用户级 Matplotlib/Fontconfig 缓存，因此把缓存放到项目输出下。
os.environ.setdefault("MPLCONFIGDIR", "/tmp/fund_analysis_matplotlib")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/fund_analysis_cache")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path("D_analysis/output/fund_consistency")
OUTPUT_DIR = ROOT / "fm_winrates_nonoverlap_review"

MODELS = {
    "Top 30": "fm_winrates_top30_nonoverlap",
    "Bottom 30": "fm_winrates_bottom30_nonoverlap",
    "Top 50": "fm_winrates_top50_nonoverlap",
    "Bottom 50": "fm_winrates_bottom50_nonoverlap",
}

SPEC_ORDER = [
    "winrate_m6_n3_pairwise6",
    "winrate_m3_n6_pairwise3",
    "winrate_m6_n6_pairwise6",
    "winrate_m3_n12_pairwise3",
    "winrate_m12_n3_pairwise12",
]

SPEC_LABELS = {
    "winrate_m6_n3_pairwise6": "m=6, n=3",
    "winrate_m3_n6_pairwise3": "m=3, n=6",
    "winrate_m6_n6_pairwise6": "m=6, n=6",
    "winrate_m3_n12_pairwise3": "m=3, n=12",
    "winrate_m12_n3_pairwise12": "m=12, n=3",
}


def load_identification_summary() -> pd.DataFrame:
    """读取四组模型的识别诊断，计算真正可回归月份占比。"""
    rows = []
    for model_label, folder_name in MODELS.items():
        check_dir = ROOT / folder_name / "winrates_check"
        for path in check_dir.glob("*/dummy_identification_summary.csv"):
            data = pd.read_csv(path)
            data.insert(0, "model", model_label)
            rows.append(data)

    result = pd.concat(rows, ignore_index=True)
    result["ready_rate_pct"] = result["regression_ready_rate"] * 100
    return result


def is_conceptually_adjacent(row: pd.Series, factor: str) -> bool:
    """判断是否为按 Hit 顺序相邻的差额。

    m=3、n=12 使用 3/6/9 三个门槛，文件中的 ``is_adjacent`` 因数值差为 3
    被记为 False；研究含义上 3→6 和 6→9 仍是相邻门槛，因此单独纳入。
    """
    if factor == "winrate_m3_n12_pairwise3":
        return (row["lower_order"], row["upper_order"]) in {(3, 6), (6, 9)}
    return bool(row["is_adjacent"])


def load_adjacent_summary() -> pd.DataFrame:
    """汇总 Top/Bottom 50 的相邻 beta 差额及其月度波动。"""
    rows = []
    for model_label in ("Top 50", "Bottom 50"):
        folder_name = MODELS[model_label]
        check_dir = ROOT / folder_name / "winrates_check"

        for test_path in check_dir.glob("*/beta_pairwise_newey_west_tests.csv"):
            factor = test_path.parent.name
            tests = pd.read_csv(test_path)
            tests = tests[
                tests.apply(lambda row: is_conceptually_adjacent(row, factor), axis=1)
            ].copy()

            # 月度差额用来区分“平均差额接近 0”与“每月差额固定”。
            monthly_path = test_path.parent / "beta_pairwise_monthly_differences.csv"
            monthly = pd.read_csv(monthly_path)
            monthly_stats = (
                monthly.groupby("pair")["beta_difference"]
                .agg(monthly_sd="std", positive_share=lambda x: (x > 0).mean())
                .reset_index()
            )
            monthly_stats["same_sign_share"] = monthly_stats["positive_share"].map(
                lambda value: max(value, 1 - value)
            )

            tests = tests.merge(monthly_stats, on="pair", how="left")
            tests.insert(0, "model", model_label)
            tests.insert(1, "spec", factor)
            tests["ci95_low"] = tests["mean_difference"] - 1.96 * tests["newey_west_se"]
            tests["ci95_high"] = tests["mean_difference"] + 1.96 * tests["newey_west_se"]
            rows.append(tests)

    return pd.concat(rows, ignore_index=True)


def plot_sample_stability(summary: pd.DataFrame) -> None:
    """用热图呈现完整模型真正可回归的月份比例，并标注 n/N。"""
    rates = summary.pivot(index="model", columns="factor", values="ready_rate_pct")
    rates = rates.loc[list(MODELS), SPEC_ORDER]

    ready = summary.pivot(index="model", columns="factor", values="full_model_rank_months")
    ready = ready.loc[list(MODELS), SPEC_ORDER]
    eligible = summary.pivot(index="model", columns="factor", values="eligible_months")
    eligible = eligible.loc[list(MODELS), SPEC_ORDER]
    annotations = np.empty_like(rates, dtype=object)
    for row in range(rates.shape[0]):
        for col in range(rates.shape[1]):
            annotations[row, col] = (
                f"{rates.iloc[row, col]:.0f}%\n"
                f"{int(ready.iloc[row, col])}/{int(eligible.iloc[row, col])} months"
            )

    fig, ax = plt.subplots(figsize=(12, 4.7))
    image = ax.imshow(rates.to_numpy(), cmap="RdYlGn", vmin=0, vmax=100, aspect="auto")
    colorbar = fig.colorbar(image, ax=ax, pad=0.02)
    colorbar.set_label("Regression-ready months / eligible months (%)")
    for row in range(rates.shape[0]):
        for col in range(rates.shape[1]):
            ax.text(col, row, annotations[row, col], ha="center", va="center", fontsize=9)

    # 白色分隔线让每个模型格子在不依赖 seaborn 的情况下仍保持清晰。
    ax.set_xticks(np.arange(-0.5, rates.shape[1], 1), minor=True)
    ax.set_yticks(np.arange(-0.5, rates.shape[0], 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", bottom=False, left=False)
    ax.set_title("Non-overlap win-rate models: monthly regression readiness", pad=15, weight="bold")
    ax.set_xlabel("Model specification")
    ax.set_ylabel("")
    ax.set_xticks(np.arange(len(SPEC_ORDER)))
    ax.set_xticklabels([SPEC_LABELS[item] for item in SPEC_ORDER], rotation=0)
    ax.set_yticks(np.arange(len(MODELS)))
    ax.set_yticklabels(list(MODELS))
    fig.text(
        0.01,
        0.01,
        "A month is regression-ready only when the cross-section is eligible and the full design matrix has full rank.",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(OUTPUT_DIR / "sample_stability_regression_ready_rate.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def short_pair_label(pair: str) -> str:
    """把文件中的长变量名缩短成适合图表横轴的标签。"""
    return pair.replace("beta_", "").replace("-beta_", " – ").replace("hit_above", ">")


def plot_adjacent_differences(summary: pd.DataFrame) -> None:
    """按五种规格绘制 Top/Bottom 50 相邻 beta 差额与 NW 置信区间。"""
    colors = {"Top 50": "#2563EB", "Bottom 50": "#E76F51"}
    fig, axes = plt.subplots(3, 2, figsize=(14, 13))
    axes = axes.flatten()

    for ax, spec in zip(axes, SPEC_ORDER):
        data = summary[summary["spec"] == spec].copy()
        pairs = (
            data[["lower_order", "upper_order", "pair"]]
            .drop_duplicates()
            .sort_values(["lower_order", "upper_order"])["pair"]
            .tolist()
        )
        x = np.arange(len(pairs))
        width = 0.36

        for offset, model in ((-width / 2, "Top 50"), (width / 2, "Bottom 50")):
            model_data = data[data["model"] == model].set_index("pair").loc[pairs]
            means = model_data["mean_difference"].to_numpy() * 100
            errors = model_data["newey_west_se"].to_numpy() * 1.96 * 100
            bars = ax.bar(
                x + offset,
                means,
                width,
                yerr=errors,
                capsize=3,
                label=model,
                color=colors[model],
                alpha=0.88,
            )
            # 星号只代表未经多重检验校正的 5% 显著性；图下注明 FDR 结论。
            for bar, p_value in zip(bars, model_data["p_value"]):
                if p_value < 0.05:
                    y = bar.get_height()
                    ax.text(
                        bar.get_x() + bar.get_width() / 2,
                        y + (0.22 if y >= 0 else -0.35),
                        "*",
                        ha="center",
                        va="bottom" if y >= 0 else "top",
                        fontsize=13,
                        weight="bold",
                    )

        ax.axhline(0, color="#333333", linewidth=0.9)
        ax.set_title(SPEC_LABELS[spec], weight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels([short_pair_label(pair) for pair in pairs], rotation=35, ha="right")
        ax.set_ylabel("Mean beta difference (percentage points)")
        ax.grid(axis="y", color="#DDDDDD", linewidth=0.7)

    axes[-1].axis("off")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=2, frameon=False, bbox_to_anchor=(0.5, 0.965))
    fig.suptitle(
        "Adjacent beta differences: Top 50 vs Bottom 50\n(mean with 95% Newey–West confidence interval)",
        y=0.995,
        weight="bold",
        fontsize=15,
    )
    fig.text(
        0.01,
        0.01,
        "* raw p < 0.05. No adjacent comparison remains significant at 5% after within-family FDR correction.",
        fontsize=9,
        color="#555555",
    )
    fig.tight_layout(rect=(0, 0.035, 1, 0.94))
    fig.savefig(OUTPUT_DIR / "top_bottom50_adjacent_beta_differences.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    """执行汇总、导出审计表，并生成两张研究诊断图。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    identification = load_identification_summary()
    adjacent = load_adjacent_summary()

    identification.to_csv(OUTPUT_DIR / "sample_identification_summary.csv", index=False)
    adjacent[
        [
            "model",
            "spec",
            "pair",
            "mean_difference",
            "newey_west_se",
            "ci95_low",
            "ci95_high",
            "t_stat",
            "p_value",
            "family_fdr_q_value",
            "n_months",
            "monthly_sd",
            "positive_share",
            "same_sign_share",
        ]
    ].to_csv(OUTPUT_DIR / "top_bottom50_adjacent_beta_summary.csv", index=False)

    plot_sample_stability(identification)
    plot_adjacent_differences(adjacent)


if __name__ == "__main__":
    main()
