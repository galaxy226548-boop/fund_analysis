"""全项目多重检验 family 的集中登记表。

这个文件只负责回答三个问题：

1. 哪些结果属于同一个经济假设 family；
2. p 值从哪个结果文件、哪一列读取；
3. 当前 family 是已启用、待用户审核，还是仅作为研究口径说明保留。

实际 BH 计算、非法 p 值校验和输出落盘统一由 ``apply_fdr.py`` 完成。
把 family 与回归模型分开登记，是因为一个 family 经常横跨多个 registry key，
而 Wald、IUT 等检验甚至不直接对应一个回归模型。

如何阅读这个文件
------------------

所有 family 最终都会登记进 ``FDR_FAMILIES``。虽然下面有些 family 是逐条写出，
有些使用 ``for`` 循环批量生成，但每一项最终都有完全相同的七个字段：

``description``
    给人阅读的中文说明，不参与计算。
``role``
    研究角色，例如主检验、探索性检验或稳健性检验；用于输出 metadata。
``status``
    是否允许默认执行。``active`` 会被 ``--all-active`` 执行；
    ``pending_user_review`` 必须显式加 ``--include-pending``；其他状态默认拒绝执行。
``method``
    多重检验方法。目前统一为 Benjamini-Hochberg。
``q_threshold``
    显著性阈值。目前统一为 0.05。
``sources``
    属于这个 family 的一个或多个结果表，以及从表中选取哪些 p 值。
``notes``
    口径说明和风险提示，不参与计算。

最常见的删改方法
----------------

1. 临时停用一个 family：把 ``status="active"`` 改为 ``status="disabled"``。
   不建议直接删除，因为保留登记可以区分“研究决定不做”和“维护时遗漏”。
2. 把待审核 family 正式启用：把 ``status="pending_user_review"`` 改为
   ``status="active"``。
3. 永久说明无需 FDR：使用 ``status="not_required"``，并在 ``notes`` 写明原因。
4. 修改输入文件：改对应 ``csv_source(path=...)`` 的第一个路径参数。
5. 修改 p 值列：在 ``csv_source`` 中设置 ``p_column="新的列名"``。
6. 修改纳入哪些行：修改 ``selectors``。多个 selector 之间是“并且”关系。
7. 删除循环生成的一组 family：不要逐项寻找生成结果，而是从循环上方的模型列表
   中删除对应模型名。例如热力图 family 由 ``_HEATMAP_MODELS`` 生成。
8. 合并 family：把多个 ``csv_source(...)`` 放进同一个 ``sources=[...]``。
9. 拆分 family：新建两个 ``family(...)`` 定义，并分别给它们不同的 sources/selectors。

selector 写法
-------------

``{"op": "equals", "column": "variable", "value": "某变量"}``
    只保留某列等于固定值的行。
``{"op": "regex", "column": "factor", "pattern": "正则表达式"}``
    用变量名模式筛选窗口或模型。
``{"op": "truthy", "column": "estimation_success"}``
    只保留成功估计的行。
``{"op": "column_equals_column", "left": "variable", "right": "factor"}``
    只保留主因子本身的系数，排除截距和控制变量。

下面每一节还会说明它为什么采用“逐条定义”“多个 source”或“循环生成”。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_METHOD = "benjamini-hochberg"
DEFAULT_Q_THRESHOLD = 0.05


def csv_source(
    path: str,
    *,
    p_column: str = "p_value",
    selectors: list[dict[str, Any]] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """生成一个输入结果表声明，避免在 family 中重复书写固定字段。

    ``path`` 指向 CSV；``p_column`` 告诉执行脚本读取哪一列 p 值；
    ``selectors`` 决定从 CSV 中保留哪些假设；``label`` 是输出中的短名称。
    """

    # 第一步：没有 selector 时使用空列表，表示保留这个 CSV 中的全部结果行。
    normalized_selectors = selectors or []

    # 第二步：如果没有专门写短标签，就使用路径本身，确保审计输出始终有来源名称。
    normalized_label = label or path

    # 第三步：返回统一结构；apply_fdr.py 只读取这个结构，不关心 family 如何生成。
    return {
        "path": path,
        "p_column": p_column,
        "selectors": normalized_selectors,
        "label": normalized_label,
    }


def family(
    description: str,
    role: str,
    sources: list[dict[str, Any]],
    *,
    status: str = "active",
    notes: str = "",
) -> dict[str, Any]:
    """生成一个字段齐全、格式统一的 family 配置。

    下面所有看起来不同的代码最终都调用本函数，因此产生的数据结构完全相同。
    差别只在于：有的 family 读取一个文件，有的读取多个文件；有的逐条写出，
    有的通过循环批量生成同类 family。
    """

    # 第一步：写入会随具体经济假设变化的字段，包括中文说明、角色、状态和来源。
    config = {
        "description": description,
        "role": role,
        "status": status,
        "sources": sources,
        "notes": notes,
    }

    # 第二步：统一补上全项目共同使用的 BH 方法和 q<0.05 阈值。
    # 如果未来某个 family 确实需要不同阈值，应先修改本函数支持显式参数，
    # 不要在下方定义完成后再偷偷覆盖字典字段。
    config["method"] = DEFAULT_METHOD
    config["q_threshold"] = DEFAULT_Q_THRESHOLD

    # 第三步：把完整配置交给 FDR_FAMILIES；执行脚本不会自行猜测缺失字段。
    return config


RESULT_ROOT = "D_analysis/output/fund_consistency"


# 这是本文件唯一的最终登记表。下方每个代码块都只是在向这个字典增加项目。
# key 是命令行 ``--family`` 使用的稳定 family id；value 统一由 family() 生成。
FDR_FAMILIES: dict[str, dict[str, Any]] = {}


# family 定义的统一模板如下。实际代码只会根据需要替换 id、说明、状态和来源：
#
# FDR_FAMILIES["稳定且不重复的_family_id"] = family(
#     description="这组检验共同回答什么经济问题",
#     role="primary_or_exploratory_role",
#     status="active",  # active / pending_user_review / disabled / not_required
#     sources=[
#         csv_source(
#             "D_analysis/output/.../某个结果.csv",
#             p_column="p_value",
#             selectors=[...],
#             label="便于阅读的来源名",
#         )
#     ],
#     notes="为什么这样划分 family，以及应当怎样解释 q 值。",
# )


# ---------------------------------------------------------------------------
# F01-F02：FAC 热力图。Full sample 是唯一主检验；五个分组各自是探索族。
# n=1 产生缺失 p 值时，由 apply_fdr.py 合法排除并登记，不计入 family size。
#
# 【为什么使用循环】六个模型的输入结构和筛选规则完全相同，只有模型名和研究
# 角色不同。循环只是避免复制六段代码，不代表它们被合并成一个 family；循环每
# 运行一次都会产生一个独立 family。
#
# 【如何修改】
# - 停用某个热力图 family：从 _HEATMAP_MODELS 删除对应模型，或在循环内增加
#   单独的状态映射。若希望保留审计记录，推荐改成显式 family 并设 disabled。
# - 修改某个模型的主检验/探索角色：修改右侧的 role 字符串。
# - 合并六个热力图：不能只改这个字典；需要把六个 csv_source 放进同一 family。
# ---------------------------------------------------------------------------
_HEATMAP_MODELS = {
    "fm_heatmap_full": "primary_full_sample",
    "fm_heatmap_up": "exploratory_subgroup",
    "fm_heatmap_down": "exploratory_subgroup",
    "fm_heatmap_top33": "exploratory_subgroup",
    "fm_heatmap_mid33": "exploratory_subgroup",
    "fm_heatmap_bottom33": "exploratory_subgroup",
}
for _model_key, _role in _HEATMAP_MODELS.items():
    FDR_FAMILIES[f"fac_heatmap__{_model_key}"] = family(
        description=f"{_model_key} 全部可估 FAC (m,n) 主效应",
        role=_role,
        status="active",
        sources=[
            csv_source(
                f"{RESULT_ROOT}/{_model_key}/fama_macbeth_results.csv",
                selectors=[
                    {
                        "op": "column_equals_column",
                        "left": "variable",
                        "right": "factor",
                    }
                ],
                label=_model_key,
            )
        ],
        notes="每个 heatmap 模型独立校正；缺失或未定义的 FAC 不进入 family。",
    )


# ---------------------------------------------------------------------------
# F03：连续 HitRate。Top50、Top33、Bottom33 可以被共同挑选来支持同一类
# “方向一致性”结论，因此保持为同一个主 family。
#
# 【为什么逐条定义】这里只有一个 family，但它从一个已经汇总 Top50/Top33/
# Bottom33 的结果表读取 p 值，所以不需要循环。
#
# 【如何修改】如果以后要把 Top50、Top33、Bottom33 拆开，不能只改 description；
# 应建立三个 family，并分别增加 metric==top50/top33/bottom33 的 equals selector。
# ---------------------------------------------------------------------------
FDR_FAMILIES["hitrate_nonoverlap_primary"] = family(
    description="全部成功估计的 non-overlap Top50/Top33/Bottom33 连续 HitRate 主效应",
    role="primary_directional_consistency",
    status="active",
    sources=[
        csv_source(
            f"{RESULT_ROOT}/winrates_hitrate_effect_grid_linear_full/"
            "hitrate_primary_results_fdr.csv",
            selectors=[{"op": "truthy", "column": "estimation_success"}],
            label="continuous_hitrate_primary",
        )
    ],
    notes="读取 raw p_value 后重新统一计算 q_value，不依赖来源文件中已有的 q 值。",
)


# ---------------------------------------------------------------------------
# F04-F07：累计 Hit Dummy。四种经济主张必须分开，不能把单系数、联合检验和
# 方向 IUT 混入同一个 family。
#
# 【为什么写成四段】四个 family 读取的文件或 p 值列不同，而且经济假设不同。
# 为了让用户可以独立停用、改名或拆分，故意不使用循环隐藏这些差异。
#
# 【如何修改】每一段就是一个完整 family。若不再研究某类主张，把该段的
# status 改成 disabled；不要删除另外三段。
# ---------------------------------------------------------------------------
_HIT_DUMMY_ROOT = f"{RESULT_ROOT}/winrates_cumulative_dummy_effects"
# F04：每多跨过一个相邻 Hit 门槛的边际变化。
FDR_FAMILIES["hit_dummy_nonoverlap_adjacent"] = family(
    description="non-overlap 累计 Hit Dummy 的相邻门槛边际效应",
    role="primary_adjacent_marginal_effect",
    status="active",
    sources=[csv_source(f"{_HIT_DUMMY_ROOT}/adjacent_marginal_effects_fdr.csv")],
    notes="全部 Top50/Top33/Bottom33 相邻边际效应共同校正。",
)
# F05：达到某个累计 Hit 水平相对于 Hit0 的总效果。
FDR_FAMILIES["hit_dummy_nonoverlap_cumulative_vs_hit0"] = family(
    description="non-overlap 累计 Hit Dummy 各门槛相对 Hit0 的效应",
    role="primary_cumulative_level_effect",
    status="active",
    sources=[csv_source(f"{_HIT_DUMMY_ROOT}/cumulative_hit_vs_hit0_effects_fdr.csv")],
    notes="全部累计门槛相对 Hit0 的效果共同校正。",
)
# F06：一个模型内所有累计 Dummy 是否联合为零。
FDR_FAMILIES["hit_dummy_nonoverlap_joint_wald"] = family(
    description="non-overlap 累计 Hit Dummy 的模型层联合 HAC-Wald 检验",
    role="primary_joint_model_test",
    status="active",
    sources=[
        csv_source(
            f"{_HIT_DUMMY_ROOT}/model_joint_direction_tests_fdr.csv",
            p_column="joint_p_value",
        )
    ],
    notes="只读取 joint_p_value，不读取同一 CSV 中的方向 IUT p 值。",
)
# F07：所有边际效应是否同时满足预先规定的经济方向。
FDR_FAMILIES["hit_dummy_nonoverlap_direction_iut"] = family(
    description="non-overlap 累计 Hit Dummy 的方向 IUT 检验",
    role="primary_direction_test",
    status="active",
    sources=[
        csv_source(
            f"{_HIT_DUMMY_ROOT}/model_joint_direction_tests_fdr.csv",
            p_column="direction_iut_p_value",
        )
    ],
    notes="只读取 direction_iut_p_value，与联合 Wald 保持为不同 family。",
)


# ---------------------------------------------------------------------------
# F08-F11：标准五窗口 × 四个未来收益期限。Up、Down、Top33、Bottom33 分别
# 构成独立 family；每个 family 合并 y1m/y3m/y6m/y12m，每个 Y 下读取五个
# 预设 FAC 主效应，因此 family size 固定为 20。
#
# 【为什么不加入 heatmap】heatmap 的 132 个窗口承担参数发现任务；这里的五个
# 窗口承担固定规格的跨期限确认任务。把两者混在同一 family 会混淆发现与确认。
#
# 【为什么不跨样本组合并】四个分组高度相关，研究设计采用“组内20项 BH-FDR
# + 跨组同方向重复出现”的两阶段规则。跨组稳健性属于后续汇总判定，不在这里
# 把 80 个 p 值再做一次联合 BH。
#
# 【如何修改】
# - 调整样本组：修改 _STANDARD_FAC_GROUP_MODELS。
# - 调整 Y 期限：修改 _STANDARD_FAC_Y_SUFFIXES。
# - 调整固定窗口：修改 _STANDARD_FAC_PATTERN，并同步更新 description/notes。
# ---------------------------------------------------------------------------
_STANDARD_FAC_GROUP_MODELS = (
    "fm_baseline_up",
    "fm_baseline_down",
    "fm_baseline_top33",
    "fm_baseline_bottom33",
)
_STANDARD_FAC_Y_SUFFIXES = {
    "y1m": "_y1m",
    "y3m": "_y3m",
    "y6m": "",
    "y12m": "_y12m",
}
_STANDARD_FAC_PATTERN = (
    r"^FAC_rank_vol_(?:m3_n6|m6_n3|m6_n6|m6_n12|m12_n6)_pairwise1$"
)
_STANDARD_FAC_SELECTORS = [
    {"op": "regex", "column": "factor", "pattern": _STANDARD_FAC_PATTERN},
    {"op": "column_equals_column", "left": "variable", "right": "factor"},
]

for _model_key in _STANDARD_FAC_GROUP_MODELS:
    FDR_FAMILIES[f"standard_fac_20__{_model_key}"] = family(
        description=f"{_model_key} 的五个固定 FAC 窗口 × 四个未来收益期限",
        role="prespecified_5_windows_x_4_y_horizons",
        status="active",
        sources=[
            csv_source(
                f"{RESULT_ROOT}/{_model_key}{_suffix}/fama_macbeth_results.csv",
                selectors=_STANDARD_FAC_SELECTORS,
                label=f"{_model_key}__{_y_label}",
            )
            for _y_label, _suffix in _STANDARD_FAC_Y_SUFFIXES.items()
        ],
        notes=(
            "每个样本组独立执行20项 BH-FDR；不含132窗口 heatmap，也不跨样本组"
            "合并。跨组稳健性另按同一窗口、同一 Y、同方向且至少两个组各自"
            "q<0.05 判定。"
        ),
    )

# 正式交互项也按 m 分开登记；这里没有 alternative/noctrlLTM，避免把经济口径
# 不同的模型混合。若要停用整组交互 family，可把下面 status 改为 not_required。
for _m in (3, 6, 12):
    FDR_FAMILIES[f"standard_interaction__fm_baseline_interaction__m{_m}"] = family(
        description=f"正式交互模型中 m={_m} 的 FAC×rank_mean 交互项",
        role="prespecified_horizon_interaction",
        status="pending_user_review",
        sources=[
            csv_source(
                f"{RESULT_ROOT}/fm_baseline_interaction/fama_macbeth_results.csv",
                selectors=[
                    {
                        "op": "regex",
                        "column": "factor",
                        "pattern": rf"^FAC_rank_vol_m{_m}_n\d+_pairwise1$",
                    },
                    {"op": "equals", "column": "variable", "value": "FAC__x__RANK_MEAN__dmcs"},
                ],
                label="fm_baseline_interaction",
            )
        ],
        notes="只登记正式交互模型；alternative 和 noctrlLTM 不与其混成一个 family。",
    )


# ---------------------------------------------------------------------------
# F14-F16：市态模型。不同市场状态可能被共同搜索以支持“某种市态有效”，
# 因此跨四类市态合并；主效应、交互效应和边际增量仍分成不同 family。
#
# 【为什么 sources 使用列表推导式】每个市态 family 同时读取 hs300、style、
# size、indvol 四个结果文件。这四个 source 会合并后做一次 BH，而不是各做一次。
#
# 【如何修改】
# - 删除一种市态：从 _MKT_KEYS 删除 key，并同步删除 _MKT_VARIABLE_PREFIX 项。
# - 让四种市态分别校正：需要把一个 family 拆成四个，不能继续使用这里的列表推导。
# - 暂停某一整类结论：修改对应 family 的 status，不影响另外三个市态 family。
# ---------------------------------------------------------------------------
_MKT_KEYS = ("hs300", "style", "size", "indvol")
_MKT_VARIABLE_PREFIX = {
    "hs300": r"hs300(?:up|down)",
    "style": r"(?:growth|value)",
    "size": r"(?:large|small)",
    "indvol": r"(?:highvol|lowvol)",
}
FDR_FAMILIES["market_state_fac_main"] = family(
    description="HS300/风格/规模/行业波动率四类市态 FAC 主效应",
    role="exploratory_market_state_main_effect",
    status="active",
    sources=[
        csv_source(
            f"{RESULT_ROOT}/fm_baseline_{key}/fama_macbeth_results.csv",
            selectors=[
                {
                    "op": "column_equals_column",
                    "left": "variable",
                    "right": "factor",
                }
            ],
            label=f"fm_baseline_{key}",
        )
        for key in _MKT_KEYS
    ],
    notes="四类市态主效应合并为一个探索性 family。",
)
FDR_FAMILIES["market_state_fac_rank_mean_interaction"] = family(
    description="四类市态模型中的 FAC×rank_mean 条件效应",
    role="exploratory_market_state_interaction",
    status="active",
    sources=[
        csv_source(
            f"{RESULT_ROOT}/fm_baseline_interaction_noctrlLTM_{key}/fama_macbeth_results.csv",
            selectors=[{"op": "equals", "column": "variable", "value": "FAC__x__RANK_MEAN__dmcs"}],
            label=f"fm_baseline_interaction_noctrlLTM_{key}",
        )
        for key in _MKT_KEYS
    ],
    notes="只选 FAC__x__RANK_MEAN__dmcs，不把主效应和控制变量放入 family。",
)
FDR_FAMILIES["market_state_marginal_fac_main"] = family(
    description="普通 FAC 同场回归后，四类市态 FAC 的边际主效应",
    role="exploratory_market_state_incremental_main",
    status="active",
    sources=[
        csv_source(
            f"{RESULT_ROOT}/fm_marginal_interaction_noctrlLTM_{key}/fama_macbeth_results.csv",
            selectors=[
                {
                    "op": "regex",
                    "column": "variable",
                    "pattern": rf"^FAC_rank_vol_{_MKT_VARIABLE_PREFIX[key]}_.+__dmcs$",
                }
            ],
            label=f"fm_marginal_interaction_noctrlLTM_{key}",
        )
        for key in _MKT_KEYS
    ],
    notes="正则表达式只保留市态 FAC__dmcs，排除同场的普通 FAC。",
)
FDR_FAMILIES["market_state_marginal_interaction"] = family(
    description="普通交互项同场回归后，四类市态 FAC×rank_mean 的边际交互效应",
    role="exploratory_market_state_incremental_interaction",
    status="active",
    sources=[
        csv_source(
            f"{RESULT_ROOT}/fm_marginal_interaction_noctrlLTM_{key}/fama_macbeth_results.csv",
            selectors=[{"op": "equals", "column": "variable", "value": "FAC__x__RANK_MEAN__dmcs"}],
            label=f"fm_marginal_interaction_noctrlLTM_{key}",
        )
        for key in _MKT_KEYS
    ],
    notes="只保留市态 FAC×rank_mean 交互，普通交互项不进入这个 family。",
)


# ymatch/cross 不能用“一个显著、一个不显著”替代系数差异检验。在直接差异的
# raw p-value 尚未生成前只登记研究状态，不让统一脚本误做校正。
# 【如何修改】以后生成直接差异 p 值后，把 sources 补成 csv_source(...)，再把
# status 改为 active；不要直接把 matched 和 cross 两列各自的 p 值拼进来替代差异检验。
FDR_FAMILIES["market_state_ymatch_minus_cross"] = family(
    description="市态 matched 与 cross/placebo 系数的直接差异检验",
    role="planned_market_state_contrast",
    status="blocked_missing_contrast_pvalues",
    sources=[],
    notes="必须先生成 matched-minus-cross 的直接检验 p 值。",
)


# Benchmark 当前只作为稳健性展示，不凭其显著性建立独立经济结论，因此不做
# 默认 FDR。保留登记项是为了让“未做 FDR”成为明确政策，而不是遗漏。
# 【如何修改】如果未来要从 benchmark 中选择显著结果，补充 sources，并把 status
# 改成 pending_user_review 或 active；只改 status 而 sources 仍为空会被执行脚本拒绝。
FDR_FAMILIES["benchmark_robustness"] = family(
    description="fm_bmk/fm_bmk_objctrl/fm_bmk_up 等 benchmark 稳健性模型",
    role="robustness_not_used_for_discovery",
    status="not_required",
    sources=[],
    notes="若未来从 benchmark 结果中挑选显著结论，应改为 exploratory family。",
)


# F11/F13 暂不登记为可运行 family：代表窗口脚本包含 registry 之外的 9 个
# 后验窗口；而 heatmap 目前没有所有样本组 × 所有未来 Y 的完整对称网格。
# 在研究设计补齐前，静默校正一个不完整子集反而会造成错误安全感。


def get_family(family_id: str) -> dict[str, Any]:
    """按稳定 id 读取一个 family，并返回可安全修改的副本。"""

    # 第一步：先验证 id，拼出完整可选列表，让命令行拼写错误容易定位。
    if family_id not in FDR_FAMILIES:
        available = ", ".join(sorted(FDR_FAMILIES))
        raise KeyError(f"未知 FDR family：{family_id}；可选值：{available}")

    # 第二步：返回深拷贝。调用方即使修改 sources/selectors，也不会污染全局登记表。
    return deepcopy(FDR_FAMILIES[family_id])


def list_families() -> list[tuple[str, str, str]]:
    """生成供 ``apply_fdr.py --list`` 展示的简洁 family 清单。"""

    # 第一步：按 family id 排序，保证每次输出顺序稳定，便于 Git diff 和人工核对。
    ordered_items = sorted(FDR_FAMILIES.items())

    # 第二步：只抽取审核最需要的 id、状态和中文说明；完整 sources 仍保留在登记表中。
    summary: list[tuple[str, str, str]] = []
    for family_id, config in ordered_items:
        summary.append(
            (family_id, str(config["status"]), str(config["description"]))
        )

    # 第三步：把稳定清单交给命令行打印，不在配置文件中直接产生任何输出。
    return summary
