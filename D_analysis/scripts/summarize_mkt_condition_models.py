"""汇总市态一致性模型结果，并与普通一致性模型并排对比。

读取 D_analysis/output/fund_consistency/ 下 32 个市态模型（fm_baseline_{dim}、
fm_baseline_interaction_noctrlLTM_{dim}、fm_marginal_interaction_noctrlLTM_{dim}、
fm_winrates_top50_{dim}、fm_ymatch_{dim}_{regime}、fm_ymatch_cross_{dim}_{regime}）
以及参照旧模型（fm_baseline、fm_baseline_interaction_noctrlLTM、fm_winrates_top50）
的 fama_macbeth_results.csv，生成以下对比表：

    D_analysis/output/fund_consistency/mkt_condition_comparison/
        all_mkt_state_results_long.csv     全部市态模型结果长表
        m1_state_vs_plain.csv              市态 M1 vs 普通 M1 的 FAC 主效应
        interaction_state_vs_plain.csv     市态 M3' vs 普通 M3' 的交互项
        marginal_summary.csv               marginal 模型各项系数 + VIF 诊断
        ymatch_matched_vs_cross.csv        状态匹配 vs 错配反证
        winrates_state_vs_plain.csv        市态 winrates dummy vs 普通 top50
        headline_findings.md               自动生成的重点结果摘要

运行方式：

    .venv/bin/python D_analysis/scripts/summarize_mkt_condition_models.py
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = PROJECT_ROOT / "D_analysis" / "output" / "fund_consistency"
VIF_ROOT = PROJECT_ROOT / "B_factors" / "output"
OUTPUT_DIR = RESULTS_ROOT / "mkt_condition_comparison"

DIM_REGIMES = {
    "hs300": ("hs300up", "hs300down"),
    "style": ("growth", "value"),
    "size": ("large", "small"),
    "indvol": ("highvol", "lowvol"),
}
REGIME_TO_DIM = {
    regime: dim for dim, regimes in DIM_REGIMES.items() for regime in regimes
}
WINDOW_SPECS = ((3, 6), (6, 3), (6, 6), (6, 12), (12, 6))

STATE_FAC_PATTERN = re.compile(
    r"^FAC_rank_vol_(?P<regime>[a-z0-9]+)_m(?P<m>\d+)_n(?P<n>\d+)_pairwise1$"
)
PLAIN_FAC_PATTERN = re.compile(
    r"^FAC_rank_vol_m(?P<m>\d+)_n(?P<n>\d+)_pairwise1$"
)
T_SIGNIFICANT = 1.96

RESULT_COLUMNS = [
    "model",
    "factor",
    "variable",
    "coef",
    "newey_west_se",
    "t_stat",
    "p_value",
    "n_months",
    "avg_monthly_n",
    "avg_adj_r_squared",
]


def load_model_results(model_key: str) -> pd.DataFrame | None:
    """读取单个模型的 Fama-MacBeth 结果，缺失时返回 None 并提示。"""
    path = RESULTS_ROOT / model_key / "fama_macbeth_results.csv"
    if not path.exists():
        print(f"[警告] 缺少结果文件，跳过：{path}")
        return None
    data = pd.read_csv(path)
    data.insert(0, "model", model_key)
    missing = [column for column in RESULT_COLUMNS if column not in data.columns]
    if missing:
        raise ValueError(f"{path} 缺少字段：{missing}")
    return data[RESULT_COLUMNS]


def parse_state_fac(name: str) -> dict[str, object] | None:
    """解析市态 FAC 列名，返回 regime/dim/m/n；不匹配返回 None。"""
    match = STATE_FAC_PATTERN.fullmatch(str(name))
    if match is None:
        return None
    regime = match.group("regime")
    if regime not in REGIME_TO_DIM:
        return None
    return {
        "dim": REGIME_TO_DIM[regime],
        "regime": regime,
        "m": int(match.group("m")),
        "n": int(match.group("n")),
    }


def extract_factor_rows(results: pd.DataFrame, centered: bool) -> pd.DataFrame:
    """提取每套回归中市态 FAC 主效应所在的行。"""
    suffix = "__dmcs" if centered else ""
    rows = []
    for _, row in results.iterrows():
        parsed = parse_state_fac(str(row["factor"]))
        if parsed is None:
            continue
        if str(row["variable"]) != f"{row['factor']}{suffix}":
            continue
        rows.append({**row.to_dict(), **parsed})
    return pd.DataFrame(rows)


def build_m1_comparison(
    state_results: pd.DataFrame, plain_results: pd.DataFrame | None
) -> pd.DataFrame:
    """市态 M1 的 FAC 主效应与普通 fm_baseline 并排。"""
    state_rows = extract_factor_rows(state_results, centered=False)
    if plain_results is not None:
        plain_rows = plain_results[
            plain_results["variable"] == plain_results["factor"]
        ].copy()
        plain_rows["window"] = plain_rows["factor"].str.replace(
            "FAC_rank_vol_", "", regex=False
        )
        plain_lookup = plain_rows.set_index("window")
    else:
        plain_lookup = None

    records = []
    for _, row in state_rows.iterrows():
        window = f"m{row['m']}_n{row['n']}_pairwise1"
        record = {
            "dim": row["dim"],
            "regime": row["regime"],
            "window": f"m{row['m']}_n{row['n']}",
            "state_coef": row["coef"],
            "state_t": row["t_stat"],
            "state_n_months": row["n_months"],
            "state_adj_r2": row["avg_adj_r_squared"],
        }
        if plain_lookup is not None and window in plain_lookup.index:
            plain = plain_lookup.loc[window]
            record.update(
                {
                    "plain_coef": plain["coef"],
                    "plain_t": plain["t_stat"],
                    "plain_n_months": plain["n_months"],
                    "plain_adj_r2": plain["avg_adj_r_squared"],
                }
            )
        records.append(record)
    return pd.DataFrame(records).sort_values(["dim", "regime", "window"])


def build_interaction_comparison(
    state_results: pd.DataFrame, plain_results: pd.DataFrame | None
) -> pd.DataFrame:
    """市态 M3' 与普通 M3' 的交互项系数对比。"""
    records = []
    interaction_variable = "FAC__x__RANK_MEAN__dmcs"

    def collect(results: pd.DataFrame, label: str) -> None:
        interaction_rows = results[
            results["variable"] == interaction_variable
        ]
        for _, row in interaction_rows.iterrows():
            parsed = parse_state_fac(str(row["factor"]))
            if parsed is not None:
                dim, regime = parsed["dim"], parsed["regime"]
                window = f"m{parsed['m']}_n{parsed['n']}"
            else:
                plain = PLAIN_FAC_PATTERN.fullmatch(str(row["factor"]))
                if plain is None:
                    continue
                dim, regime = "plain", "plain"
                window = f"m{plain.group('m')}_n{plain.group('n')}"
            records.append(
                {
                    "source": label,
                    "dim": dim,
                    "regime": regime,
                    "window": window,
                    "interaction_coef": row["coef"],
                    "interaction_t": row["t_stat"],
                    "n_months": row["n_months"],
                    "avg_adj_r2": row["avg_adj_r_squared"],
                }
            )

    collect(state_results, "state")
    if plain_results is not None:
        collect(plain_results, "plain")
    return pd.DataFrame(records).sort_values(
        ["source", "dim", "regime", "window"]
    )


def load_overall_vif(model_key: str) -> pd.DataFrame | None:
    """读取模型的整体 VIF 诊断。"""
    path = (
        VIF_ROOT
        / model_key
        / "variable_correlation_check"
        / "fama_macbeth_overall_vif.csv"
    )
    if not path.exists():
        print(f"[警告] 缺少 VIF 文件：{path}")
        return None
    return pd.read_csv(path)


def build_marginal_summary(marginal_results: pd.DataFrame) -> pd.DataFrame:
    """marginal 模型：市态/普通主效应与交互项系数 + VIF 上限。"""
    variable_labels = {
        "state_fac": lambda factor: f"{factor}__dmcs",
        "plain_fac": lambda factor: (
            PLAIN_FAC_PATTERN.pattern
        ),
    }
    del variable_labels  # 逐行解析更直观，保留字典反而难读。

    records = []
    for model_key, model_rows in marginal_results.groupby("model"):
        vif = load_overall_vif(str(model_key))
        for factor, factor_rows in model_rows.groupby("factor"):
            parsed = parse_state_fac(str(factor))
            if parsed is None:
                continue
            window_suffix = f"m{parsed['m']}_n{parsed['n']}_pairwise1"
            wanted = {
                "state_fac": f"{factor}__dmcs",
                "state_rank_mean": (
                    f"rank_mean_{parsed['regime']}_{window_suffix}__dmcs"
                ),
                "plain_fac": f"FAC_rank_vol_{window_suffix}__dmcs",
                "plain_rank_mean": f"rank_mean_{window_suffix}__dmcs",
                "state_interaction": "FAC__x__RANK_MEAN__dmcs",
                "plain_interaction": "FAC_PLAIN__x__RANK_MEAN_PLAIN__dmcs",
            }
            record: dict[str, object] = {
                "model": model_key,
                "dim": parsed["dim"],
                "regime": parsed["regime"],
                "window": f"m{parsed['m']}_n{parsed['n']}",
            }
            indexed = factor_rows.set_index("variable")
            for label, variable in wanted.items():
                if variable in indexed.index:
                    record[f"{label}_coef"] = indexed.loc[variable, "coef"]
                    record[f"{label}_t"] = indexed.loc[variable, "t_stat"]
            record["n_months"] = factor_rows["n_months"].iloc[0]
            record["avg_adj_r2"] = factor_rows["avg_adj_r_squared"].iloc[0]
            if vif is not None:
                factor_vif = vif[vif["factor"] == factor]
                if len(factor_vif):
                    record["max_vif"] = factor_vif["vif"].max()
                    record["vif_all_ok"] = bool(
                        (factor_vif["status"] == "ok").all()
                    )
            records.append(record)
    return pd.DataFrame(records).sort_values(["dim", "regime", "window"])


def build_ymatch_comparison(all_results: pd.DataFrame) -> pd.DataFrame:
    """状态匹配 vs 错配反证：同一 FAC 在两种 Y 下的系数对比。"""
    records: dict[tuple[str, str, str], dict[str, object]] = {}
    for _, row in all_results.iterrows():
        model = str(row["model"])
        if not model.startswith("fm_ymatch_"):
            continue
        if str(row["variable"]) != str(row["factor"]):
            continue
        parsed = parse_state_fac(str(row["factor"]))
        if parsed is None:
            continue
        kind = "cross" if model.startswith("fm_ymatch_cross_") else "matched"
        key = (
            str(parsed["dim"]),
            str(parsed["regime"]),
            f"m{parsed['m']}_n{parsed['n']}",
        )
        record = records.setdefault(
            key, {"dim": key[0], "regime": key[1], "window": key[2]}
        )
        record[f"{kind}_coef"] = row["coef"]
        record[f"{kind}_t"] = row["t_stat"]
        record[f"{kind}_n_months"] = row["n_months"]
    result = pd.DataFrame(list(records.values()))
    if len(result):
        result["matched_stronger"] = (
            result.get("matched_t", pd.Series(dtype=float)).abs()
            > result.get("cross_t", pd.Series(dtype=float)).abs()
        )
    return result.sort_values(["dim", "regime", "window"])


def build_winrates_comparison(all_results: pd.DataFrame) -> pd.DataFrame:
    """市态与普通 top50 winrates 的 dummy 系数长表。"""
    dummy_rows = all_results[
        all_results["variable"].str.startswith("dummy_top50")
    ].copy()
    parsed = dummy_rows["variable"].str.extract(
        r"^dummy_top50_?(?P<regime>[a-z0-9]*?)_m(?P<m>\d+)_n(?P<n>\d+)"
        r"_hit(?P<hit>\d+)_pairwise1$"
    )
    dummy_rows["regime"] = parsed["regime"].replace("", "plain")
    dummy_rows["dim"] = dummy_rows["regime"].map(REGIME_TO_DIM).fillna("plain")
    dummy_rows["window"] = "m" + parsed["m"] + "_n" + parsed["n"]
    dummy_rows["hit_k"] = pd.to_numeric(parsed["hit"])
    keep = [
        "model",
        "dim",
        "regime",
        "window",
        "hit_k",
        "coef",
        "t_stat",
        "n_months",
    ]
    return (
        dummy_rows.dropna(subset=["hit_k"])[keep]
        .sort_values(["dim", "regime", "window", "hit_k"])
        .reset_index(drop=True)
    )


def write_headline_findings(
    m1: pd.DataFrame,
    interaction: pd.DataFrame,
    marginal: pd.DataFrame,
    ymatch: pd.DataFrame,
    output_path: Path,
) -> None:
    """把显著结果写成 markdown 摘要，供人工快速浏览。"""
    lines = [
        "# 市态一致性模型重点结果（自动生成）",
        "",
        f"显著性阈值：|t| >= {T_SIGNIFICANT}（Newey-West）。",
        "有效月份 < 60 的结果需谨慎解读（growth/large 的 m6_n12 规格）。",
        "",
        "## 一、市态 FAC 主效应显著的规格（M1 对照）",
        "",
    ]
    significant_m1 = m1[m1["state_t"].abs() >= T_SIGNIFICANT]
    if len(significant_m1):
        lines.append(
            "```\n" + significant_m1.round(3).to_string(index=False) + "\n```"
        )
    else:
        lines.append("（无显著规格）")

    lines += ["", "## 二、市态交互项显著的规格（M3' 对照）", ""]
    state_interaction = interaction[
        (interaction["source"] == "state")
        & (interaction["interaction_t"].abs() >= T_SIGNIFICANT)
    ]
    if len(state_interaction):
        lines.append(
            "```\n" + state_interaction.round(3).to_string(index=False) + "\n```"
        )
    else:
        lines.append("（无显著规格）")

    lines += [
        "",
        "## 三、marginal 模型中市态项在普通项同场时仍显著的规格",
        "",
    ]
    if len(marginal):
        survived = marginal[
            marginal.get("state_fac_t", pd.Series(dtype=float)).abs()
            >= T_SIGNIFICANT
        ]
        if len(survived):
            lines.append("```\n" + survived.round(3).to_string(index=False) + "\n```")
        else:
            lines.append("（无：市态 FAC 的信息被普通项吸收）")

    lines += ["", "## 四、状态匹配 vs 错配反证", ""]
    if len(ymatch):
        matched_significant = ymatch[
            ymatch.get("matched_t", pd.Series(dtype=float)).abs()
            >= T_SIGNIFICANT
        ]
        lines.append(
            f"匹配项显著规格数：{len(matched_significant)} / {len(ymatch)}；"
            "其中匹配 |t| 大于错配 |t| 的规格数："
            f"{int(ymatch['matched_stronger'].sum())} / {len(ymatch)}。"
        )
        lines.append("")
        if len(matched_significant):
            lines.append(
                "```\n" + matched_significant.round(3).to_string(index=False) + "\n```"
            )
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    """汇总全部市态模型结果并写出对比表。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    state_model_keys: list[str] = []
    for dim, regimes in DIM_REGIMES.items():
        state_model_keys += [
            f"fm_baseline_{dim}",
            f"fm_baseline_interaction_noctrlLTM_{dim}",
            f"fm_marginal_interaction_noctrlLTM_{dim}",
            f"fm_winrates_top50_{dim}",
        ]
        for regime in regimes:
            state_model_keys += [
                f"fm_ymatch_{dim}_{regime}",
                f"fm_ymatch_cross_{dim}_{regime}",
            ]

    frames = [
        results
        for key in state_model_keys
        if (results := load_model_results(key)) is not None
    ]
    all_state = pd.concat(frames, ignore_index=True)
    all_state.to_csv(
        OUTPUT_DIR / "all_mkt_state_results_long.csv", index=False
    )

    plain_baseline = load_model_results("fm_baseline")
    plain_interaction = load_model_results("fm_baseline_interaction_noctrlLTM")
    plain_winrates = load_model_results("fm_winrates_top50")

    m1 = build_m1_comparison(
        all_state[all_state["model"].str.fullmatch(r"fm_baseline_[a-z0-9]+")],
        plain_baseline,
    )
    m1.to_csv(OUTPUT_DIR / "m1_state_vs_plain.csv", index=False)

    interaction = build_interaction_comparison(
        all_state[
            all_state["model"].str.startswith(
                "fm_baseline_interaction_noctrlLTM_"
            )
        ],
        plain_interaction,
    )
    interaction.to_csv(
        OUTPUT_DIR / "interaction_state_vs_plain.csv", index=False
    )

    marginal = build_marginal_summary(
        all_state[
            all_state["model"].str.startswith(
                "fm_marginal_interaction_noctrlLTM_"
            )
        ]
    )
    marginal.to_csv(OUTPUT_DIR / "marginal_summary.csv", index=False)

    ymatch = build_ymatch_comparison(all_state)
    ymatch.to_csv(OUTPUT_DIR / "ymatch_matched_vs_cross.csv", index=False)

    winrates_frames = [
        all_state[all_state["model"].str.startswith("fm_winrates_top50_")]
    ]
    if plain_winrates is not None:
        winrates_frames.append(plain_winrates)
    winrates = build_winrates_comparison(
        pd.concat(winrates_frames, ignore_index=True)
    )
    winrates.to_csv(
        OUTPUT_DIR / "winrates_state_vs_plain.csv", index=False
    )

    write_headline_findings(
        m1,
        interaction,
        marginal,
        ymatch,
        OUTPUT_DIR / "headline_findings.md",
    )

    print(f"输出目录：{OUTPUT_DIR}")
    print(f"模型结果长表行数：{len(all_state):,}")
    print(f"M1 对比规格数：{len(m1)}")
    print(f"交互对比行数：{len(interaction)}")
    print(f"marginal 规格数：{len(marginal)}")
    print(f"ymatch 对比规格数：{len(ymatch)}")
    print(f"winrates dummy 行数：{len(winrates)}")


if __name__ == "__main__":
    main()
