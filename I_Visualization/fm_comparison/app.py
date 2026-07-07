"""fm_comparison：Fama-MacBeth + Portfolio Sorting 指标可行性比较页面。

运行方式：

    .venv/bin/streamlit run I_Visualization/fm_comparison/app.py

页面中心为"擂台式"左右对照：左边挑战者（新指标的整个族），右边守擂者
（现役最优组合所在族，高亮现役格）。分数只作每格脚注，计算明细可在页面
底部逐项展开复算。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# 让 config / data_loader / scoring / export 按普通模块导入（与测试同一套路径处理）
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import data_loader  # noqa: E402
import export  # noqa: E402
import scoring  # noqa: E402

st.set_page_config(page_title="FM+PS 指标可行性比较", layout="wide")


@st.cache_data(show_spinner="正在解析总表……")
def load_tables(xlsx_path: str, mtime: float) -> dict[str, pd.DataFrame]:
    """读取并解析总表；mtime 参与缓存键，文件更新后自动失效。"""
    return data_loader.load_all(Path(xlsx_path))


def build_cfg_from_sidebar() -> dict:
    """侧栏滑条生成本次会话生效的打分配置（基于默认配置的副本）。"""
    cfg = dict(config.DEFAULT_CONFIG)
    st.sidebar.header("打分权重")
    # 四维满分：分档比例不变，随满分整体缩放
    cfg["fm_full"] = float(st.sidebar.slider("FM 显著性满分", 0, 60, int(cfg["fm_full"])))
    cfg["neighbor_full"] = float(st.sidebar.slider("邻格稳健性满分", 0, 20, int(cfg["neighbor_full"])))
    cfg["ps_full"] = float(st.sidebar.slider("多空显著性满分", 0, 50, int(cfg["ps_full"])))
    cfg["r2_individual_full"] = float(st.sidebar.slider("R² 个体满分", 0, 20, int(cfg["r2_individual_full"])))
    cfg["r2_family_full"] = float(st.sidebar.slider("R² 族满分", 0, 20, int(cfg["r2_family_full"])))
    st.sidebar.header("阈值")
    cfg["ps_econ_threshold"] = st.sidebar.slider("经济显著性阈值（月均多空，%）", 0.0, 1.0, cfg["ps_econ_threshold"] * 100, 0.05) / 100
    cfg["replace_margin"] = float(st.sidebar.slider("优先关注的领先分差", 0, 30, int(cfg["replace_margin"])))
    cfg["tie_band"] = float(st.sidebar.slider("色点判平的分差带", 0, 15, int(cfg["tie_band"])))
    return cfg


def fm_cell_text(row, score: float, champion: bool, dot: str) -> str:
    """组装网格单元格文本：系数+星号、t 值、分数脚注、现役标记与优劣色点。"""
    stars = "*" * int(row["stars"])
    mark = "★现役 " if champion else ""
    return f"{mark}{dot}{row['coef']:.2f}{stars}\n(t={row['t_stat']:.2f})\n[分 {score:.1f}]"


def render_fm_grid(side_scores: pd.DataFrame, champion_key: str | None, defender_total: float | None, cfg: dict):
    """渲染一侧的 FM 系数 m×n 网格（含分数脚注与优/平/劣色点）。"""
    grid = {}
    for _, row in side_scores.iterrows():
        dot = ""
        # 只有存在守擂总分时才给挑战者格子标色点
        if defender_total is not None and row["param_key"] != champion_key:
            diff = row["total"] - defender_total
            dot = "🟢" if diff > cfg["tie_band"] else ("🟡" if diff >= -cfg["tie_band"] else "🔴")
        grid[(row["m"], row["n"])] = fm_cell_text(row, row["total"], row["param_key"] == champion_key, dot)
    m_axis = sorted({k[0] for k in grid})
    n_axis = sorted({k[1] for k in grid})
    table = pd.DataFrame(
        [[grid.get((m, n), "") for n in n_axis] for m in m_axis],
        index=[f"m{m}" for m in m_axis], columns=[f"n{n}" for n in n_axis],
    )
    st.dataframe(table, use_container_width=True)


def render_side(title: str, side_scores: pd.DataFrame, all_scores: pd.DataFrame, tables: dict, champion_key: str | None, defender_total: float | None, cfg: dict):
    """渲染擂台一侧的四个块：FM 网格 / 覆盖与 R² / 多空 / 共线性诊断。"""
    model = side_scores["model"].iloc[0]
    # 族平均 R² 必须按模型的全部市态状态池化（不能只用当前选中的单一市态），
    # 因为 scoring.score_all 里驱动 r2_score 的 family_avg 就是这样算的
    # （family_avg = base.groupby("model")["avg_r2"].mean()，跨 growth/value 等状态合并）；
    # 若在这里改回只用 side_scores（已按市态过滤），会与实际打分口径脱节。
    fam_r2 = all_scores[all_scores["model"] == model]["avg_r2"].mean()
    st.subheader(title)
    st.markdown("**① FM 系数网格**")
    render_fm_grid(side_scores, champion_key, defender_total, cfg)
    st.markdown(f"**② 覆盖与回归质量**（族平均 R² = {fam_r2:.3f}）")
    st.dataframe(
        side_scores[["param_key", "n_months", "avg_funds", "n_obs", "avg_r2"]]
        .rename(columns={"param_key": "参数", "n_months": "月份数", "avg_funds": "月均基金数", "n_obs": "样本数", "avg_r2": "平均R²"}),
        use_container_width=True, hide_index=True,
    )
    st.markdown("**③ 多空收益**")
    ps_view = side_scores[["param_key", "long_short", "p_value"]].copy()
    ps_view["long_short"] = ps_view["long_short"].map(lambda v: f"{v:.2%}" if pd.notna(v) else "无记录")
    st.dataframe(
        ps_view.rename(columns={"param_key": "参数", "long_short": "月均多空", "p_value": "p值"}),
        use_container_width=True, hide_index=True,
    )
    st.markdown("**④ 共线性诊断**")
    diag = tables["diag"]
    diag_fam = diag[diag["model"] == model]
    if diag_fam.empty:
        st.caption("无相关性/VIF 风险记录")
    else:
        st.dataframe(diag_fam[["kind", "var_1", "var_2", "n_flagged", "involves_core"]], use_container_width=True, hide_index=True)


def render_breakdown(scores: pd.DataFrame, models: list[str]):
    """页面底部的"分数计算明细"：选任一格，逐项展开公式与代入值。"""
    pool = scores[scores["model"].isin(models)]
    options = [f"{r.model} × {r.param_key}（总分 {r.total:.1f}）" for r in pool.itertuples()]
    if not options:
        return
    picked = st.selectbox("选择要复算的候选格", options)
    row = pool.iloc[options.index(picked)]
    st.dataframe(pd.DataFrame(row["明细"]), use_container_width=True, hide_index=True)
    st.caption(f"总分 = 各项得分之和 = {row['total']:.2f}")


def main():
    """页面入口：侧栏配置 -> 加载与打分 -> 三个 Tab。"""
    st.title("Fama-MacBeth + Portfolio Sorting 指标可行性比较")
    # ---- 侧栏：数据源与配置 ----
    st.sidebar.header("数据源")
    xlsx_path = st.sidebar.text_input("总表路径", str(config.SUMMARY_XLSX))
    if st.sidebar.button("重新加载"):
        st.cache_data.clear()
    cfg = build_cfg_from_sidebar()

    path = Path(xlsx_path)
    if not path.exists():
        st.error(f"总表不存在：{path}")
        st.stop()
    tables = load_tables(str(path), path.stat().st_mtime)
    scores = scoring.attach_badges(scoring.score_all(tables, cfg), config.BASELINES, cfg)

    tab1, tab2, tab3 = st.tabs(["擂台对比", "可行性排行榜", "打分说明"])

    # ---- Tab1 擂台对比 ----
    with tab1:
        models = sorted(scores["model"].unique())

        def _state_options(model: str) -> list[str]:
            # 该模型下出现过的市态状态去重集合；""代表无市态前缀
            return sorted(scores[scores["model"] == model]["state"].unique())

        left, right = st.columns(2)
        with left:
            challenger = st.selectbox("挑战者（新指标族）", models, index=0)
            ch_states = _state_options(challenger)
            # 只有一个状态时不显示下拉，直接用该状态；同一模型可能同时含
            # growth/value 等两个市态，必须选定后再画网格，否则会互相覆盖
            challenger_state = ch_states[0] if len(ch_states) <= 1 else st.selectbox(
                "挑战者市态", ch_states, index=0, key="challenger_state",
            )
        # 守擂者按挑战者的样本层自动带出，可手动改
        layer = scoring.sample_layer(challenger)
        default_base = config.BASELINES.get(layer)
        with right:
            defender_model = st.selectbox(
                "守擂者（基准族）", models,
                index=models.index(default_base["model"]) if default_base and default_base["model"] in models else 0,
            )
            defender_states = _state_options(defender_model)
            defender_state = defender_states[0] if len(defender_states) <= 1 else st.selectbox(
                "守擂者市态", defender_states, index=0, key="defender_state",
            )
            defender_params = sorted(
                scores[(scores["model"] == defender_model) & (scores["state"] == defender_state)]["param_key"].unique()
            )
            default_param = default_base["param_key"] if default_base else defender_params[0]
            champion_key = st.selectbox(
                "现役参数组合", defender_params,
                index=defender_params.index(default_param) if default_param in defender_params else 0,
            )
        ch_scores = scores[(scores["model"] == challenger) & (scores["state"] == challenger_state)]
        df_scores = scores[(scores["model"] == defender_model) & (scores["state"] == defender_state)]
        champ_rows = df_scores[df_scores["param_key"] == champion_key]
        defender_total = float(champ_rows["total"].iloc[0]) if not champ_rows.empty else None
        col_l, col_r = st.columns(2)
        with col_l:
            state_suffix = f"（{challenger_state}）" if challenger_state else ""
            render_side(f"挑战者：{challenger}{state_suffix}", ch_scores, scores, tables, None, defender_total, cfg)
        with col_r:
            state_suffix = f"（{defender_state}）" if defender_state else ""
            render_side(f"守擂者：{defender_model}{state_suffix}", df_scores, scores, tables, champion_key, None, cfg)
        with st.expander("分数计算明细（点开逐项复算）"):
            render_breakdown(scores, [challenger, defender_model])

    # ---- Tab2 可行性排行榜 ----
    with tab2:
        f1, f2, f3, f4 = st.columns(4)
        batches = f1.multiselect("批次", sorted(scores["batch"].unique()))
        layers = f2.multiselect("样本层", sorted(scores["layer"].unique()))
        params = f3.multiselect("参数组合", sorted(scores["param_key"].unique()))
        # 市态状态筛选：""代表无市态前缀，用"（无）"占位方便点选
        state_options = sorted(scores["state"].unique())
        state_labels = {s: (s if s else "（无）") for s in state_options}
        picked_labels = f4.multiselect("市态", [state_labels[s] for s in state_options])
        states = [s for s in state_options if state_labels[s] in picked_labels]
        view = scores.copy()
        if batches:
            view = view[view["batch"].isin(batches)]
        if layers:
            view = view[view["layer"].isin(layers)]
        if params:
            view = view[view["param_key"].isin(params)]
        if states:
            view = view[view["state"].isin(states)]
        view = view.sort_values("total", ascending=False)
        show_cols = ["model", "state", "param_key", "layer", "total", "fm_score", "neighbor_score",
                     "ps_sig_score", "r2_score", "sample_pen", "collin_pen",
                     "vs_baseline", "badge", "is_baseline", "batch"]
        # 基准行高亮：按 is_baseline 上底色
        styled = view[show_cols].style.apply(
            lambda r: ["background-color: #fff3cd"] * len(r) if r["is_baseline"] else [""] * len(r), axis=1,
        ).format({c: "{:.1f}" for c in ["total", "fm_score", "neighbor_score", "ps_sig_score", "r2_score", "sample_pen", "collin_pen", "vs_baseline"]}, na_rep="-")
        st.dataframe(styled, use_container_width=True, hide_index=True)
        if st.button("导出可行性排名 xlsx"):
            out = export.export_ranking(scores, cfg, config.OUTPUT_DIR)
            st.success(f"已导出：{out}")

    # ---- Tab3 打分说明 ----
    with tab3:
        # 先把各分档规则拼成字符串，避免在 f-string 表达式里嵌套同引号 f-string
        total_full = (
            cfg["fm_full"] + cfg["neighbor_full"] + cfg["ps_full"]
            + cfg["r2_individual_full"] + cfg["r2_family_full"]
        )
        fm_rule = "; ".join(f"|t|>={t}→{f * cfg['fm_full']:g}" for t, f in cfg["fm_t_bands"])
        ps_rule = "; ".join(f"p<{t}→{f * cfg['ps_full']:g}" for t, f in cfg["ps_p_bands"])
        months_rule = "; ".join(f"<{t}→{p:g}" for t, p in cfg["months_penalties"])
        obs_rule = "; ".join(f"<{t}→{p:g}" for t, p in cfg["obs_penalties"])
        st.markdown(f"""
### 当前生效的打分规则（随侧栏实时更新）

**四个维度（总分 {total_full:g}）**

| 维度 | 满分 | 规则 |
|---|---|---|
| FM 显著性 | {cfg['fm_full']:g} | {fm_rule}；否则 0 |
| 邻格稳健性 | {cfg['neighbor_full']:g} | 邻格（沿一条轴走一步）中同号且 \\|t\\|>={cfg['neighbor_t_min']} 的比例 × 满分 |
| 多空显著性 | {cfg['ps_full']:g} | {ps_rule}；方向冲突 ×{cfg['ps_direction_conflict_mult']}；\\|月均多空\\|<{cfg['ps_econ_threshold']:.1%} ×{cfg['ps_econ_mult']} |
| 回归质量 | {cfg['r2_individual_full'] + cfg['r2_family_full']:g} | 个体 R² 全体分位 ×{cfg['r2_individual_full']:g} + 族均 R² 跨族分位 ×{cfg['r2_family_full']:g} |

**扣分项（只扣分不剔除）**

- 月份数：{months_rule}（取最严档）
- 样本数（月份×月均基金）：{obs_rule}（取最严档）
- 相关性风险：每组唯一对 {cfg['corr_pair_penalty']:g}（含核心 FAC 变量 {cfg['corr_pair_core_penalty']:g}）× 持续性，上限 {cfg['corr_cap']:g}
- VIF 风险：每变量 {cfg['vif_penalty']:g}（核心变量自身 {cfg['vif_core_penalty']:g}）× 持续性，上限 {cfg['vif_cap']:g}

**擂台判定**：up 系对比 `fm_baseline_up × m6_n12`，bottom33 系对比 `fm_baseline_bottom33 × m3_n6`；
总分超过基准 → "可能可替代基准"；领先 >= {cfg['replace_margin']:g} 分 → "优先关注"。
""")


main()
