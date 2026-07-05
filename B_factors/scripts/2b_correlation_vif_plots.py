"""把变量相关性检查的 CSV 结果画成图表。

这个脚本不重新计算相关系数和 VIF，只读取
``B_factors/scripts/2_factor_correlation.py`` 已经输出的结果文件：

    <correlation_output_dir>/fama_macbeth_correlation_table.csv
    <correlation_output_dir>/fama_macbeth_correlation_table_with_stars.csv
    <correlation_output_dir>/fama_macbeth_overall_vif.csv
    <correlation_output_dir>/fama_macbeth_monthly_vif_long.csv

每个 factor 生成三张图，写入 ``<correlation_output_dir>/figures/``：

1. corr_heatmap_<factor>.png    相关系数热力图（标注系数值和显著性星号）
2. vif_overall_<factor>.png     整体 VIF 条形图（VIF=5/10 参考线）
3. vif_monthly_<factor>.png     月度 VIF 时间序列图（看共线性的时变性）

全部画完后写 ``figures/plots_manifest.json``，供 engine 的输出检查使用。

运行方式：

    .venv/bin/python B_factors/scripts/2b_correlation_vif_plots.py --model fm_baseline_interaction
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = PROJECT_ROOT / "D_analysis" / "config" / "regression_registry.py"
DEFAULT_MODEL_KEY = "fm_baseline"

# VIF 经验阈值：5 以上提示中度共线性，10 以上通常认为需要处理。
VIF_WARN_THRESHOLD = 5.0
VIF_RISK_THRESHOLD = 10.0

# 变量数超过这个值时热力图不再逐格标注数字，避免文字挤成一团。
HEATMAP_ANNOTATION_MAX_VARS = 25


def configure_chinese_font() -> None:
    """为图表配置中文字体，避免变量名里的中文显示成方框。"""

    candidate_fonts = (
        "Arial Unicode MS",
        "Heiti TC",
        "Songti SC",
        "STHeiti",
        "PingFang SC",
        "Noto Sans CJK SC",
        "SimHei",
    )
    for font_name in candidate_fonts:
        try:
            font_manager.findfont(font_name, fallback_to_default=False)
        except ValueError:
            continue
        plt.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        return


def load_regression_config(model_key: str) -> dict[str, object]:
    """从统一注册表读取模型配置。"""

    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到回归配置注册表：{REGISTRY_PATH}")

    spec = importlib.util.spec_from_file_location(
        "fund_consistency_regression_registry", REGISTRY_PATH
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载回归配置注册表：{REGISTRY_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.get_regression_config(model_key)


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""

    parser = argparse.ArgumentParser(
        description="把变量相关性检查结果画成热力图和 VIF 图表。"
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_KEY,
        help="registry 中的模型 key，用来定位 correlation_output_dir。",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="相关性检查结果目录；默认取 registry 的 correlation_output_dir。",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="图表输出目录；默认是 <input-dir>/figures。",
    )
    return parser.parse_args()


def sanitize_for_filename(text: str) -> str:
    """把 factor 名转成安全的文件名片段。"""

    return re.sub(r"[^0-9A-Za-z_-]+", "_", text).strip("_")


def read_result_csv(input_dir: Path, filename: str) -> pd.DataFrame:
    """读取相关性检查输出的 CSV（带 BOM），缺文件时给出可操作的报错。"""

    path = input_dir / filename
    if not path.exists():
        raise FileNotFoundError(
            f"找不到 {path}；请先运行 2_factor_correlation.py 生成相关性检查结果。"
        )
    return pd.read_csv(path, encoding="utf-8-sig")


def extract_factor_block(
    corr_table: pd.DataFrame, factor: str
) -> tuple[pd.DataFrame, list[str]]:
    """取出单个 factor 的方阵相关系数块。

    宽表里每个 factor 只在自己用到的变量列上有值，其余列为空；
    这里按行内变量顺序同时约束行和列，得到对齐的方阵。
    """

    block = corr_table.loc[corr_table["factor"] == factor]
    variables = [
        variable
        for variable in block["variable"].tolist()
        if variable in block.columns
    ]
    matrix = block.set_index("variable").loc[variables, variables]
    return matrix.astype(float), variables


def plot_correlation_heatmap(
    corr_table: pd.DataFrame,
    corr_table_with_stars: pd.DataFrame,
    factor: str,
    output_path: Path,
) -> None:
    """画单个 factor 的相关系数热力图，标注系数值和显著性星号。"""

    matrix, variables = extract_factor_block(corr_table, factor)
    n_vars = len(variables)
    if n_vars == 0:
        raise ValueError(f"相关系数表里没有 factor={factor} 的变量块。")

    stars_block = (
        corr_table_with_stars.loc[corr_table_with_stars["factor"] == factor]
        .set_index("variable")
        .loc[variables, variables]
    )

    fig_size = max(6.0, 0.75 * n_vars + 2.5)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size * 0.9))
    image = ax.imshow(matrix.to_numpy(), cmap="RdBu_r", vmin=-1.0, vmax=1.0)

    ax.set_xticks(range(n_vars))
    ax.set_yticks(range(n_vars))
    ax.set_xticklabels(variables, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(variables, fontsize=8)

    if n_vars <= HEATMAP_ANNOTATION_MAX_VARS:
        values = matrix.to_numpy()
        for row in range(n_vars):
            for col in range(n_vars):
                value = values[row, col]
                if np.isnan(value):
                    continue
                # 深色格子用白字，浅色格子用黑字，保证可读。
                text_color = "white" if abs(value) > 0.6 else "black"
                ax.text(
                    col,
                    row,
                    str(stars_block.iat[row, col]),
                    ha="center",
                    va="center",
                    fontsize=7,
                    color=text_color,
                )

    fig.colorbar(image, ax=ax, shrink=0.8, label="Fama-MacBeth 月均相关系数")
    ax.set_title(f"{factor}\n变量相关系数热力图（* p<0.1, ** p<0.05, *** p<0.01）")
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_overall_vif_bar(
    overall_vif: pd.DataFrame, factor: str, output_path: Path
) -> None:
    """画单个 factor 的整体 VIF 条形图，附 5/10 参考线。"""

    block = overall_vif.loc[
        (overall_vif["factor"] == factor) & (overall_vif["status"] == "ok")
    ].copy()
    if block.empty:
        raise ValueError(f"整体 VIF 表里没有 factor={factor} 的可用结果。")

    block = block.sort_values("vif")
    colors = [
        "#c0392b"
        if vif >= VIF_RISK_THRESHOLD
        else "#e67e22"
        if vif >= VIF_WARN_THRESHOLD
        else "#2e86c1"
        for vif in block["vif"]
    ]

    fig_height = max(3.5, 0.45 * len(block) + 1.5)
    fig, ax = plt.subplots(figsize=(9, fig_height))
    ax.barh(block["variable"], block["vif"], color=colors)
    ax.axvline(
        VIF_WARN_THRESHOLD, color="#e67e22", linestyle="--", linewidth=1,
        label=f"VIF={VIF_WARN_THRESHOLD:.0f}",
    )
    ax.axvline(
        VIF_RISK_THRESHOLD, color="#c0392b", linestyle="--", linewidth=1,
        label=f"VIF={VIF_RISK_THRESHOLD:.0f}",
    )
    ax.set_xlabel("VIF（整体样本）")
    ax.set_title(f"{factor}\n整体 VIF")
    ax.tick_params(axis="y", labelsize=8)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def plot_monthly_vif_lines(
    monthly_vif: pd.DataFrame, factor: str, output_path: Path
) -> None:
    """画单个 factor 的月度 VIF 时间序列图。"""

    block = monthly_vif.loc[
        (monthly_vif["factor"] == factor) & (monthly_vif["status"] == "ok")
    ].copy()
    if block.empty:
        raise ValueError(f"月度 VIF 表里没有 factor={factor} 的可用结果。")

    block["month_date"] = pd.to_datetime(block["month_date"])
    pivot = block.pivot_table(
        index="month_date", columns="variable", values="vif"
    ).sort_index()

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for variable in pivot.columns:
        ax.plot(pivot.index, pivot[variable], linewidth=1.2, label=variable)

    ax.axhline(
        VIF_WARN_THRESHOLD, color="#e67e22", linestyle="--", linewidth=1
    )
    ax.axhline(
        VIF_RISK_THRESHOLD, color="#c0392b", linestyle="--", linewidth=1
    )
    ax.set_xlabel("月份")
    ax.set_ylabel("VIF（当月横截面）")
    ax.set_title(f"{factor}\n月度 VIF 时间序列（虚线为 VIF=5/10）")
    ax.legend(fontsize=7, loc="center left", bbox_to_anchor=(1.01, 0.5))
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def main() -> None:
    """程序入口。"""

    configure_chinese_font()
    args = parse_args()

    config = load_regression_config(args.model)
    input_dir = args.input_dir
    if input_dir is None:
        input_dir = PROJECT_ROOT / str(config["correlation_output_dir"])
    output_dir = args.output_dir if args.output_dir is not None else input_dir / "figures"
    output_dir.mkdir(parents=True, exist_ok=True)

    corr_table = read_result_csv(input_dir, "fama_macbeth_correlation_table.csv")
    corr_table_with_stars = read_result_csv(
        input_dir, "fama_macbeth_correlation_table_with_stars.csv"
    )
    overall_vif = read_result_csv(input_dir, "fama_macbeth_overall_vif.csv")
    monthly_vif = read_result_csv(input_dir, "fama_macbeth_monthly_vif_long.csv")

    factors = list(dict.fromkeys(corr_table["factor"].tolist()))
    if not factors:
        raise ValueError(f"{input_dir} 的相关系数表为空，无法画图。")

    figures: list[dict[str, str]] = []
    for factor in factors:
        factor_slug = sanitize_for_filename(str(factor))

        heatmap_path = output_dir / f"corr_heatmap_{factor_slug}.png"
        plot_correlation_heatmap(
            corr_table, corr_table_with_stars, str(factor), heatmap_path
        )
        figures.append({"factor": str(factor), "type": "corr_heatmap", "file": heatmap_path.name})

        overall_path = output_dir / f"vif_overall_{factor_slug}.png"
        plot_overall_vif_bar(overall_vif, str(factor), overall_path)
        figures.append({"factor": str(factor), "type": "vif_overall", "file": overall_path.name})

        monthly_path = output_dir / f"vif_monthly_{factor_slug}.png"
        plot_monthly_vif_lines(monthly_vif, str(factor), monthly_path)
        figures.append({"factor": str(factor), "type": "vif_monthly", "file": monthly_path.name})

        print(f"已生成 {factor} 的 3 张图表。")

    manifest = {
        "model": args.model,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "n_factors": len(factors),
        "figures": figures,
    }
    manifest_path = output_dir / "plots_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"相关性可视化完成，共 {len(figures)} 张图表，输出目录：{output_dir}")


if __name__ == "__main__":
    main()
