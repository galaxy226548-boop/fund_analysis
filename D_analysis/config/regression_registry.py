"""基金一致性回归实验的统一注册表。

这个文件是回归流水线的起点：用户先在这里声明一个模型版本，再由
``D_analysis/scripts/0_regression_engine.py`` 按照配置中的步骤依次运行清洗、
变量相关性检查和回归脚本。

每个版本是一套完整的实验口径：上游清洗读写路径、样本筛选、变量清单、
回归脚本和输出路径都集中写在这里。这样做可以避免以后只改了一处变量清单，
另一处仍然沿用旧口径。
"""

from __future__ import annotations

from copy import deepcopy
import re


# winrate 统一口径：m 是单期过去收益期限（月），n 是排名/命中期数。
# 每个规格依次记录 (m, n, pairwise)，避免再次把 m、n 的含义写反。
WINRATE_TOP50_PAIRWISE1_SPECS = (
    (3, 6, 1),
    (6, 3, 1),
    (6, 6, 1),
    (6, 12, 1),
    (12, 6, 1),
)
# 新 winrate 研究遍历 m,n=1..6，且完全不重叠，因此 pairwise=m。
WINRATE_NONOVERLAP_SPECS = tuple(
    (m, n, m)
    for m in range(1, 7)
    for n in range(1, 7)
)

# 热力图口径：m 是单期过去收益期限（月），n 是排名期数，pairwise 固定为 1。
# n=1 时跨排名期的标准差没有定义，因此正式网格从 n=2 开始。这里集中生成
# 12×11 的完整网格，避免在具体模型里手写 132 个变量名。
HEATMAP_PAIRWISE1_SPECS = tuple(
    (m, n, 1)
    for m in range(1, 13)
    for n in range(2, 13)
)
HEATMAP_PANEL_INPUT_PATH = "A_data/output/panel_base_heatmap_m1_12_n1_12.parquet"


def make_winrate_dummy_group(
    metric: str, m: int, n: int, pairwise: int
) -> tuple[str, ...]:
    """生成统一的累计 hit dummy 组，保留函数名兼容现有调用。"""
    return make_cumulative_winrate_dummy_group(metric, m, n, pairwise)


def make_cumulative_winrate_dummy_group(
    metric: str, m: int, n: int, pairwise: int
) -> tuple[str, ...]:
    """生成 Dk=1(hitcount>=k) 累积 dummy 组。

    列名 ``hit_above{k-1}`` 与 ``hitcount>=k`` 等价；保留这个命名是为了
    复用现有描述统计与月度识别检查中的累计 dummy 解析逻辑。
    """
    return tuple(
        f"dummy_{metric}_m{m}_n{n}_hit_above{k - 1}_pairwise{pairwise}"
        for k in range(1, n + 1)
    )


def make_winrate_hitrate_factor(
    metric: str, m: int, n: int, pairwise: int
) -> str:
    """生成主模型使用的命中比例变量名。"""
    return f"hitrate_{metric}_m{m}_n{n}_pairwise{pairwise}"


def make_top50_dummy_group(m: int, n: int, pairwise: int) -> tuple[str, ...]:
    """生成 top50 口径的累计 dummy 组。"""
    return make_winrate_dummy_group("top50", m, n, pairwise)


def make_winrate_factor_groups(
    metric: str,
    specs: tuple[tuple[int, int, int], ...],
) -> list[tuple[str, ...]]:
    """把窗口规格转换成指定命中口径的累计 dummy tuple 列表。"""
    return [
        make_winrate_dummy_group(metric, m, n, pairwise)
        for m, n, pairwise in specs
    ]


def make_top50_factor_groups(
    specs: tuple[tuple[int, int, int], ...],
) -> list[tuple[str, ...]]:
    """把多套窗口规格转换成回归脚本需要的 dummy tuple 列表。"""
    return make_winrate_factor_groups("top50", specs)


def make_winrate_group_suffixes(
    metric: str,
    specs: tuple[tuple[int, int, int], ...],
) -> dict[tuple[str, ...], str]:
    """生成指定命中口径的 dummy 组到输出短名称映射。"""
    return {
        make_winrate_dummy_group(metric, m, n, pairwise): (
            f"winrate_m{m}_n{n}_pairwise{pairwise}"
        )
        for m, n, pairwise in specs
    }


def make_top50_group_suffixes(
    specs: tuple[tuple[int, int, int], ...],
) -> dict[tuple[str, ...], str]:
    """生成 dummy 组到输出短名称的稳定映射。"""
    return make_winrate_group_suffixes("top50", specs)


def make_nonoverlap_winrate_factors(
    metric: str,
    specs: tuple[tuple[int, int, int], ...],
) -> list[object]:
    """生成两层模型：先放 hitrate 主模型，再放累计 dummy 次要模型。"""
    hitrate_factors = [
        make_winrate_hitrate_factor(metric, m, n, pairwise)
        for m, n, pairwise in specs
    ]
    cumulative_groups = [
        make_cumulative_winrate_dummy_group(metric, m, n, pairwise)
        for m, n, pairwise in specs
    ]
    return [*hitrate_factors, *cumulative_groups]


def make_nonoverlap_winrate_group_suffixes(
    metric: str,
    specs: tuple[tuple[int, int, int], ...],
) -> dict[tuple[str, ...], str]:
    """为累计 dummy 层生成稳定且明确的结果标签。"""
    return {
        make_cumulative_winrate_dummy_group(metric, m, n, pairwise): (
            f"winrate_cumulative_m{m}_n{n}_pairwise{pairwise}"
        )
        for m, n, pairwise in specs
    }


def make_window_spec_metadata(
    specs: tuple[tuple[int, int, int], ...],
) -> list[dict[str, int]]:
    """把规格写成含义明确的元数据，供输出和人工审计使用。"""
    return [
        {
            "m": m,
            "n": n,
            "rank_count": n,
            "return_horizon": m,
            "pairwise": pairwise,
            "history_months": m + (n - 1) * pairwise,
        }
        for m, n, pairwise in specs
    ]


REGISTRY = {
    "fm_baseline": {
        "description": "Fama-MacBeth 基础模型：一致性主效应 + 控制变量",
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {
            "is_insample_future_ret_6m": 1,
        },
        "sample_flag_columns": [
            "is_insample_future_ret_6m",
            "is_top_half_rank_mean_m3_n6_pairwise1",
            "is_top_half_rank_mean_m6_n3_pairwise1",
            "is_top_half_rank_mean_m6_n6_pairwise1",
            "is_top_half_rank_mean_m6_n12_pairwise1",
            "is_top_half_rank_mean_m12_n6_pairwise1",
        ],
        "pipeline": [
            {
                "name": "preprocess",
                "script": "B_factors/scripts/run_factor_pipeline.py",
                "args": ["--registry-key", "{model}"],
                "outputs": [
                    "B_factors/output/panel_base.parquet",
                    "B_factors/output/panel_base_summary.json",
                ],
            },
            {
                "name": "correlation_check",
                "script": "B_factors/scripts/2_factor_correlation.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "B_factors/output/variable_correlation_check/fama_macbeth_correlation_summary_long.csv",
                    "B_factors/output/variable_correlation_check/fama_macbeth_time_series_vif_summary.csv",
                ],
            },
            {
                "name": "regression",
                "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_baseline/run_metadata.json",
                ],
            },
            {
                "name": "portfolio_sorting",
                "script": "D_analysis/scripts/portfolio_sorting.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline/portfolio_sorting/portfolio_sorting_registry.json",
                ],
            },
        ],
        # 兼容旧脚本里使用的单字段路径。后续如果新增模型，建议优先维护 pipeline。
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "correlation_script": "B_factors/scripts/2_factor_correlation.py",
        "preprocess_input_path": "A_data/output/panel_base.parquet",
        "preprocess_output_path": "B_factors/output/panel_base.parquet",
        "preprocess_preview_path": "B_factors/output/panel_base_preview.xlsx",
        "preprocess_summary_path": "B_factors/output/panel_base_summary.json",
        "regression_input_path": "B_factors/output/panel_base.parquet",
        "correlation_output_dir": "B_factors/output/variable_correlation_check",
        "y": "future_ret_6m",
        "factors": [
            "FAC_rank_vol_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1",
        ],
        # sample_filters 是五个指标共同满足的基础样本口径；
        # factor_sample_filters 是单个指标额外叠加的筛选条件。
        "factor_sample_filters": {
        },
        "controls": [
            "CtrlRetSTR",
            "CtrlRetLTM",
            "CtrlVol",
            "as_偏股混合型基金",
            "Ctrl_log_fund_size",
            "Ctrl_fund_age",
        ],
        "interactions": [],
        "output_dir": "D_analysis/output/fund_consistency/fm_baseline",
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            # 哑变量 as_偏股混合型基金 不做 winsorize，避免把 0/1 含义改掉。
            "columns": [
                "future_ret_6m",
                "FAC_rank_vol_m3_n6_pairwise1",
                "FAC_rank_vol_m6_n3_pairwise1",
                "FAC_rank_vol_m6_n6_pairwise1",
                "FAC_rank_vol_m6_n12_pairwise1",
                "FAC_rank_vol_m12_n6_pairwise1",
                "CtrlRetSTR",
                "CtrlRetLTM",
                "CtrlVol",
                "Ctrl_log_fund_size",
                "Ctrl_fund_age",
            ],
        },
        # q5/q10 分组标签的输出后缀。key 是输入因子列，value 是输出标签里的短名称。
        "factor_group_suffixes": {
            "FAC_rank_vol_m3_n6_pairwise1": "consistency_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1": "consistency_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1": "consistency_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1": "consistency_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1": "consistency_m12_n6_pairwise1",
        },
    },
    "fm_baseline_up": {
        "description": "Fama-MacBeth 基础模型（上半组）：一致性主效应 + 控制变量，中位数以上样本",
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {
            "is_insample_future_ret_6m": 1,
        },
        "sample_flag_columns": [
            "is_insample_future_ret_6m",
            "is_median_rank_mean_m3_n6_pairwise1",
            "is_median_rank_mean_m6_n3_pairwise1",
            "is_median_rank_mean_m6_n6_pairwise1",
            "is_median_rank_mean_m6_n12_pairwise1",
            "is_median_rank_mean_m12_n6_pairwise1",
        ],
        "pipeline": [
            {
                "name": "preprocess",
                "script": "B_factors/scripts/run_factor_pipeline.py",
                "args": ["--registry-key", "{model}"],
                "outputs": [
                    "B_factors/output/fm_baseline_up/panel_base.parquet",
                    "B_factors/output/fm_baseline_up/panel_base_summary.json",
                ],
            },
            {
                "name": "descriptive",
                "script": "A_data/scripts/4_descriptive_analysis.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "A_data/output/descriptive_analysis/fm_baseline_up/fm_baseline_up_y_future_ret_6m_descriptive.xlsx",
                ],
            },
            {
                "name": "correlation_check",
                "script": "B_factors/scripts/2_factor_correlation.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "B_factors/output/fm_baseline_up/variable_correlation_check/fama_macbeth_correlation_summary_long.csv",
                    "B_factors/output/fm_baseline_up/variable_correlation_check/fama_macbeth_time_series_vif_summary.csv",
                ],
            },
            {
                "name": "regression",
                "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_up/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_baseline_up/run_metadata.json",
                ],
            },
            {
                "name": "portfolio_sorting",
                "script": "D_analysis/scripts/portfolio_sorting.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_up/portfolio_sorting/portfolio_sorting_registry.json",
                ],
            },
        ],
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "correlation_script": "B_factors/scripts/2_factor_correlation.py",
        "preprocess_input_path": "A_data/output/panel_base.parquet",
        "preprocess_output_path": "B_factors/output/fm_baseline_up/panel_base.parquet",
        "preprocess_preview_path": "B_factors/output/fm_baseline_up/panel_base_preview.xlsx",
        "preprocess_summary_path": "B_factors/output/fm_baseline_up/panel_base_summary.json",
        "regression_input_path": "B_factors/output/fm_baseline_up/panel_base.parquet",
        "correlation_output_dir": "B_factors/output/fm_baseline_up/variable_correlation_check",
        "descriptive": {
            "input_path": "B_factors/output/fm_baseline_up/panel_base.parquet",
            "output_dir": "A_data/output/descriptive_analysis/fm_baseline_up",
            "prefix": "fm_baseline_up",
            "batches": [
                {
                    "name": "y_future_ret_6m",
                    "columns": ["future_ret_6m"],
                },
                {
                    "name": "factor_m3_n6_up",
                    "columns": ["FAC_rank_vol_m3_n6_pairwise1"],
                    "filter_column": "is_median_rank_mean_m3_n6_pairwise1",
                    "filter_value": 2,
                },
                {
                    "name": "factor_m6_n3_up",
                    "columns": ["FAC_rank_vol_m6_n3_pairwise1"],
                    "filter_column": "is_median_rank_mean_m6_n3_pairwise1",
                    "filter_value": 2,
                },
                {
                    "name": "factor_m6_n6_up",
                    "columns": ["FAC_rank_vol_m6_n6_pairwise1"],
                    "filter_column": "is_median_rank_mean_m6_n6_pairwise1",
                    "filter_value": 2,
                },
                {
                    "name": "factor_m6_n12_up",
                    "columns": ["FAC_rank_vol_m6_n12_pairwise1"],
                    "filter_column": "is_median_rank_mean_m6_n12_pairwise1",
                    "filter_value": 2,
                },
                {
                    "name": "factor_m12_n6_up",
                    "columns": ["FAC_rank_vol_m12_n6_pairwise1"],
                    "filter_column": "is_median_rank_mean_m12_n6_pairwise1",
                    "filter_value": 2,
                },
            ],
        },
        "y": "future_ret_6m",
        "factors": [
            "FAC_rank_vol_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1",
        ],
        "factor_sample_filters": {
            "FAC_rank_vol_m3_n6_pairwise1": {
                "is_median_rank_mean_m3_n6_pairwise1": 2,
            },
            "FAC_rank_vol_m6_n3_pairwise1": {
                "is_median_rank_mean_m6_n3_pairwise1": 2,
            },
            "FAC_rank_vol_m6_n6_pairwise1": {
                "is_median_rank_mean_m6_n6_pairwise1": 2,
            },
            "FAC_rank_vol_m6_n12_pairwise1": {
                "is_median_rank_mean_m6_n12_pairwise1": 2,
            },
            "FAC_rank_vol_m12_n6_pairwise1": {
                "is_median_rank_mean_m12_n6_pairwise1": 2,
            },
        },
        "controls": [
            "CtrlRetSTR",
            "CtrlRetLTM",
            "CtrlVol",
            "as_偏股混合型基金",
            "Ctrl_log_fund_size",
            "Ctrl_fund_age",
        ],
        "interactions": [],
        "output_dir": "D_analysis/output/fund_consistency/fm_baseline_up",
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "columns": [
                "future_ret_6m",
                "FAC_rank_vol_m3_n6_pairwise1",
                "FAC_rank_vol_m6_n3_pairwise1",
                "FAC_rank_vol_m6_n6_pairwise1",
                "FAC_rank_vol_m6_n12_pairwise1",
                "FAC_rank_vol_m12_n6_pairwise1",
                "CtrlRetSTR",
                "CtrlRetLTM",
                "CtrlVol",
                "Ctrl_log_fund_size",
                "Ctrl_fund_age",
            ],
        },
        "factor_group_suffixes": {
            "FAC_rank_vol_m3_n6_pairwise1": "consistency_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1": "consistency_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1": "consistency_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1": "consistency_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1": "consistency_m12_n6_pairwise1",
        },
    },
    "fm_baseline_down": {
        "description": "Fama-MacBeth 基础模型（下半组）：一致性主效应 + 控制变量，中位数以下样本",
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {
            "is_insample_future_ret_6m": 1,
        },
        "sample_flag_columns": [
            "is_insample_future_ret_6m",
            "is_median_rank_mean_m3_n6_pairwise1",
            "is_median_rank_mean_m6_n3_pairwise1",
            "is_median_rank_mean_m6_n6_pairwise1",
            "is_median_rank_mean_m6_n12_pairwise1",
            "is_median_rank_mean_m12_n6_pairwise1",
        ],
        "pipeline": [
            {
                "name": "preprocess",
                "script": "B_factors/scripts/run_factor_pipeline.py",
                "args": ["--registry-key", "{model}"],
                "outputs": [
                    "B_factors/output/fm_baseline_down/panel_base.parquet",
                    "B_factors/output/fm_baseline_down/panel_base_summary.json",
                ],
            },
            {
                "name": "descriptive",
                "script": "A_data/scripts/4_descriptive_analysis.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "A_data/output/descriptive_analysis/fm_baseline_down/fm_baseline_down_y_future_ret_6m_descriptive.xlsx",
                ],
            },
            {
                "name": "correlation_check",
                "script": "B_factors/scripts/2_factor_correlation.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "B_factors/output/fm_baseline_down/variable_correlation_check/fama_macbeth_correlation_summary_long.csv",
                    "B_factors/output/fm_baseline_down/variable_correlation_check/fama_macbeth_time_series_vif_summary.csv",
                ],
            },
            {
                "name": "regression",
                "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_down/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_baseline_down/run_metadata.json",
                ],
            },
            {
                "name": "portfolio_sorting",
                "script": "D_analysis/scripts/portfolio_sorting.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_down/portfolio_sorting/portfolio_sorting_registry.json",
                ],
            },
        ],
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "correlation_script": "B_factors/scripts/2_factor_correlation.py",
        "preprocess_input_path": "A_data/output/panel_base.parquet",
        "preprocess_output_path": "B_factors/output/fm_baseline_down/panel_base.parquet",
        "preprocess_preview_path": "B_factors/output/fm_baseline_down/panel_base_preview.xlsx",
        "preprocess_summary_path": "B_factors/output/fm_baseline_down/panel_base_summary.json",
        "regression_input_path": "B_factors/output/fm_baseline_down/panel_base.parquet",
        "correlation_output_dir": "B_factors/output/fm_baseline_down/variable_correlation_check",
        "descriptive": {
            "input_path": "B_factors/output/fm_baseline_down/panel_base.parquet",
            "output_dir": "A_data/output/descriptive_analysis/fm_baseline_down",
            "prefix": "fm_baseline_down",
            "batches": [
                {
                    "name": "y_future_ret_6m",
                    "columns": ["future_ret_6m"],
                },
                {
                    "name": "factor_m3_n6_down",
                    "columns": ["FAC_rank_vol_m3_n6_pairwise1"],
                    "filter_column": "is_median_rank_mean_m3_n6_pairwise1",
                    "filter_value": -2,
                },
                {
                    "name": "factor_m6_n3_down",
                    "columns": ["FAC_rank_vol_m6_n3_pairwise1"],
                    "filter_column": "is_median_rank_mean_m6_n3_pairwise1",
                    "filter_value": -2,
                },
                {
                    "name": "factor_m6_n6_down",
                    "columns": ["FAC_rank_vol_m6_n6_pairwise1"],
                    "filter_column": "is_median_rank_mean_m6_n6_pairwise1",
                    "filter_value": -2,
                },
                {
                    "name": "factor_m6_n12_down",
                    "columns": ["FAC_rank_vol_m6_n12_pairwise1"],
                    "filter_column": "is_median_rank_mean_m6_n12_pairwise1",
                    "filter_value": -2,
                },
                {
                    "name": "factor_m12_n6_down",
                    "columns": ["FAC_rank_vol_m12_n6_pairwise1"],
                    "filter_column": "is_median_rank_mean_m12_n6_pairwise1",
                    "filter_value": -2,
                },
            ],
        },
        "y": "future_ret_6m",
        "factors": [
            "FAC_rank_vol_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1",
        ],
        "factor_sample_filters": {
            "FAC_rank_vol_m3_n6_pairwise1": {
                "is_median_rank_mean_m3_n6_pairwise1": -2,
            },
            "FAC_rank_vol_m6_n3_pairwise1": {
                "is_median_rank_mean_m6_n3_pairwise1": -2,
            },
            "FAC_rank_vol_m6_n6_pairwise1": {
                "is_median_rank_mean_m6_n6_pairwise1": -2,
            },
            "FAC_rank_vol_m6_n12_pairwise1": {
                "is_median_rank_mean_m6_n12_pairwise1": -2,
            },
            "FAC_rank_vol_m12_n6_pairwise1": {
                "is_median_rank_mean_m12_n6_pairwise1": -2,
            },
        },
        "controls": [
            "CtrlRetSTR",
            "CtrlRetLTM",
            "CtrlVol",
            "as_偏股混合型基金",
            "Ctrl_log_fund_size",
            "Ctrl_fund_age",
        ],
        "interactions": [],
        "output_dir": "D_analysis/output/fund_consistency/fm_baseline_down",
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "columns": [
                "future_ret_6m",
                "FAC_rank_vol_m3_n6_pairwise1",
                "FAC_rank_vol_m6_n3_pairwise1",
                "FAC_rank_vol_m6_n6_pairwise1",
                "FAC_rank_vol_m6_n12_pairwise1",
                "FAC_rank_vol_m12_n6_pairwise1",
                "CtrlRetSTR",
                "CtrlRetLTM",
                "CtrlVol",
                "Ctrl_log_fund_size",
                "Ctrl_fund_age",
            ],
        },
        "factor_group_suffixes": {
            "FAC_rank_vol_m3_n6_pairwise1": "consistency_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1": "consistency_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1": "consistency_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1": "consistency_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1": "consistency_m12_n6_pairwise1",
        },
    },
    "fm_baseline_interaction_noctrlLTM": {
        "description": "Fama-MacBeth 基础模型 + 月度去均值后的 FAC、对应 rank_mean 及其交互项 + 5 个控制变量（不含 CtrlRetLTM）",
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {
            "is_insample_future_ret_6m": 1,
        },
        "sample_flag_columns": [
            "is_insample_future_ret_6m",
            "is_top_half_rank_mean_m3_n6_pairwise1",
            "is_top_half_rank_mean_m6_n3_pairwise1",
            "is_top_half_rank_mean_m6_n6_pairwise1",
            "is_top_half_rank_mean_m6_n12_pairwise1",
            "is_top_half_rank_mean_m12_n6_pairwise1",
        ],
        "pipeline": [
            {
                "name": "preprocess",
                "script": "B_factors/scripts/run_factor_pipeline.py",
                "args": ["--registry-key", "{model}"],
                "outputs": [
                    "B_factors/output/fm_baseline_interaction_noctrlLTM/panel_base.parquet",
                    "B_factors/output/fm_baseline_interaction_noctrlLTM/panel_base_summary.json",
                ],
            },
            {
                "name": "correlation_check",
                "script": "B_factors/scripts/2_factor_correlation.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "B_factors/output/fm_baseline_interaction_noctrlLTM/variable_correlation_check/fama_macbeth_correlation_summary_long.csv",
                    "B_factors/output/fm_baseline_interaction_noctrlLTM/variable_correlation_check/fama_macbeth_time_series_vif_summary.csv",
                ],
            },
            {
                "name": "regression",
                "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM/run_metadata.json",
                ],
            },
            {
                "name": "portfolio_sorting",
                "script": "D_analysis/scripts/portfolio_sorting.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM/portfolio_sorting/portfolio_sorting_registry.json",
                ],
            },
        ],
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "correlation_script": "B_factors/scripts/2_factor_correlation.py",
        "preprocess_input_path": "A_data/output/panel_base.parquet",
        "preprocess_output_path": "B_factors/output/fm_baseline_interaction_noctrlLTM/panel_base.parquet",
        "preprocess_preview_path": "B_factors/output/fm_baseline_interaction_noctrlLTM/panel_base_preview.xlsx",
        "preprocess_summary_path": "B_factors/output/fm_baseline_interaction_noctrlLTM/panel_base_summary.json",
        "regression_input_path": "B_factors/output/fm_baseline_interaction_noctrlLTM/panel_base.parquet",
        "correlation_output_dir": "B_factors/output/fm_baseline_interaction_noctrlLTM/variable_correlation_check",
        "y": "future_ret_6m",
        "factors": [
            "FAC_rank_vol_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1",
        ],
        "factor_sample_filters": {
        },
        "portfolio_sorting_factors": ["{FAC,RANK_MEAN}"],
        "controls": [
            "CtrlRetSTR",
            "CtrlVol",
            "as_偏股混合型基金",
            "Ctrl_log_fund_size",
            "Ctrl_fund_age",
        ],
        "extra_columns": [
            "rank_mean_m3_n6_pairwise1",
            "rank_mean_m6_n3_pairwise1",
            "rank_mean_m6_n6_pairwise1",
            "rank_mean_m6_n12_pairwise1",
            "rank_mean_m12_n6_pairwise1",
        ],
        # 遵循交互项的层级原则：除了 FAC 主效应和 FAC x rank_mean 外，
        # 每套期限的回归还要加入与当前 FAC 对应的 rank_mean 主效应。
        "interaction_main_effects": ["RANK_MEAN"],
        "interactions": ["{FAC,RANK_MEAN}"],
        # Fama-MacBeth 第一步是逐月横截面回归，因此中心化也应在每个月的
        # 实际候选回归样本内完成。这里只减去当月均值，不除以标准差；
        # 回归脚本随后使用中心化后的 FAC、rank_mean 主效应及二者乘积。
        "interaction_centering": "cross_section_mean",
        "output_dir": "D_analysis/output/fund_consistency/fm_baseline_interaction_noctrlLTM",
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "columns": [
                "future_ret_6m",
                "FAC_rank_vol_m3_n6_pairwise1",
                "FAC_rank_vol_m6_n3_pairwise1",
                "FAC_rank_vol_m6_n6_pairwise1",
                "FAC_rank_vol_m6_n12_pairwise1",
                "FAC_rank_vol_m12_n6_pairwise1",
                "CtrlRetSTR",
                "CtrlVol",
                "Ctrl_log_fund_size",
                "Ctrl_fund_age",
            ],
        },
        "factor_group_suffixes": {
            "FAC_rank_vol_m3_n6_pairwise1": "consistency_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1": "consistency_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1": "consistency_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1": "consistency_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1": "consistency_m12_n6_pairwise1",
        },
    },
    "fm_winrates_top50": {
        "description": "Fama-MacBeth 带方向一致性模型（排名前50%月份占比）：一致性主效应 + 控制变量",
        "window_policy": "pairwise=1，逐月滚动；m=单期收益期限（月），n=排名期数",
        "window_specs": make_window_spec_metadata(WINRATE_TOP50_PAIRWISE1_SPECS),
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {
            "is_insample_future_ret_6m": 1,
        },
        "sample_flag_columns": [
            "is_insample_future_ret_6m"
        ],
        "pipeline": [
            {
                "name": "preprocess",
                "script": "B_factors/scripts/run_factor_pipeline.py",
                "args": ["--registry-key", "{model}"],
                "outputs": [
                    "B_factors/output/fm_winrates_top50/panel_base.parquet",
                    "B_factors/output/fm_winrates_top50/panel_base_summary.json",
                ],
            },
            {
                "name": "descriptive",
                "script": "A_data/scripts/4_dummy_descriptive_analysis.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_winrates_top50/descriptive_dummy/fm_winrates_top50_dummy_descriptive.xlsx",
                ],
            },
            {
                "name": "correlation_check",
                "script": "B_factors/scripts/2_factor_correlation.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "B_factors/output/fm_winrates_top50/variable_correlation_check/fama_macbeth_correlation_summary_long.csv",
                    "B_factors/output/fm_winrates_top50/variable_correlation_check/fama_macbeth_time_series_vif_summary.csv",
                ],
            },
            {
                "name": "regression",
                "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_winrates_top50/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_winrates_top50/run_metadata.json",
                ],
            },
            {
                "name": "portfolio_sorting",
                "script": "D_analysis/scripts/portfolio_sorting.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_winrates_top50/portfolio_sorting/portfolio_sorting_registry.json",
                ],
            },
        ],
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "correlation_script": "B_factors/scripts/2_factor_correlation.py",
        # 累计 dummy 由 winrates 特征脚本统一写入 heatmap 大面板；滚动规格与
        # 非重叠规格从同一来源读取，避免继续依赖主面板里的旧互斥列。
        "preprocess_input_path": HEATMAP_PANEL_INPUT_PATH,
        "preprocess_output_path": "B_factors/output/fm_winrates_top50/panel_base.parquet",
        "preprocess_preview_path": "B_factors/output/fm_winrates_top50/panel_base_preview.xlsx",
        "preprocess_summary_path": "B_factors/output/fm_winrates_top50/panel_base_summary.json",
        "regression_input_path": "B_factors/output/fm_winrates_top50/panel_base.parquet",
        "correlation_output_dir": "B_factors/output/fm_winrates_top50/variable_correlation_check",
        "descriptive": {

        },
        "y": "future_ret_6m",
        "factors": make_top50_factor_groups(WINRATE_TOP50_PAIRWISE1_SPECS),
        "factor_sample_filters": {
        },
        "controls": [
            "CtrlRetSTR",
            "CtrlRetLTM",
            "CtrlVol",
            "as_偏股混合型基金",
            "Ctrl_log_fund_size",
            "Ctrl_fund_age",
        ],
        "interactions": [],
        "output_dir": "D_analysis/output/fund_consistency/fm_winrates_top50",
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "columns": [
                "future_ret_6m",
                "CtrlRetSTR",
                "CtrlRetLTM",
                "CtrlVol",
                "Ctrl_log_fund_size",
                "Ctrl_fund_age",
            ],
        },
        "factor_group_suffixes": make_top50_group_suffixes(
            WINRATE_TOP50_PAIRWISE1_SPECS
        ),
    },
    "fm_null": {
        "description": "Fama-MacBeth 空模型：仅控制变量，不含一致性因子，用作 baseline 对照",
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {
            "is_insample_future_ret_6m": 1,
        },
        "sample_flag_columns": [
            "is_insample_future_ret_6m",
        ],
        "pipeline": [
            {
                "name": "preprocess",
                "script": "B_factors/scripts/run_factor_pipeline.py",
                "args": ["--registry-key", "{model}"],
                "outputs": [
                    "B_factors/output/fm_null/panel_base.parquet",
                    "B_factors/output/fm_null/panel_base_summary.json",
                ],
            },
            {
                "name": "regression",
                "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_null/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_null/run_metadata.json",
                ],
            },
        ],
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "preprocess_input_path": "A_data/output/panel_base.parquet",
        "preprocess_output_path": "B_factors/output/fm_null/panel_base.parquet",
        "preprocess_preview_path": "B_factors/output/fm_null/panel_base_preview.xlsx",
        "preprocess_summary_path": "B_factors/output/fm_null/panel_base_summary.json",
        # 回归读取 fm_baseline 的面板，因为 fm_null 自身的 parquet 不含 factor 列，
        # 而 sample_alignment_columns 需要这些列来做 dropna 对齐样本。
        "regression_input_path": "B_factors/output/panel_base.parquet",
        "y": "future_ret_6m",
        "factors": [],
        # 样本对齐列：null 模型没有 factor，但需要按这些列做 dropna，
        # 使每个口径的 controls-only 回归样本与 fm_baseline 中对应
        # factor 的样本完全一致，从而让 R² 可以直接比较。
        "sample_alignment_columns": [
            "FAC_rank_vol_m3_n6_pairwise1",
            "FAC_rank_vol_m6_n3_pairwise1",
            "FAC_rank_vol_m6_n6_pairwise1",
            "FAC_rank_vol_m6_n12_pairwise1",
            "FAC_rank_vol_m12_n6_pairwise1",
        ],
        "factor_sample_filters": {},
        "controls": [
            "CtrlRetSTR",
            "CtrlRetLTM",
            "CtrlVol",
            "as_偏股混合型基金",
            "Ctrl_log_fund_size",
            "Ctrl_fund_age",
        ],
        "interactions": [],
        "output_dir": "D_analysis/output/fund_consistency/fm_null",
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "columns": [
                "future_ret_6m",
                "CtrlRetSTR",
                "CtrlRetLTM",
                "CtrlVol",
                "Ctrl_log_fund_size",
                "Ctrl_fund_age",
            ],
        },
        "factor_group_suffixes": {},
    },
}


# base 模型完整继承无长期动量控制变量的 interaction 模型，只删除乘积交互项。
# 因此每套回归仍保留 FAC、对应期限的 rank_mean 主项及全部控制变量。
_rank_mean_base_key = "fm_baseline_interaction_base"
_rank_mean_base_config = deepcopy(
    REGISTRY["fm_baseline_interaction_noctrlLTM"]
)
_rank_mean_base_preprocess_dir = f"B_factors/output/{_rank_mean_base_key}"
_rank_mean_base_regression_dir = (
    f"D_analysis/output/fund_consistency/{_rank_mean_base_key}"
)

_rank_mean_base_config.update(
    {
        "description": (
            "Fama-MacBeth 基础模型：FAC + 对应 rank_mean 主效应 + "
            "控制变量，不含交互项"
        ),
        "preprocess_output_path": (
            f"{_rank_mean_base_preprocess_dir}/panel_base.parquet"
        ),
        "preprocess_preview_path": (
            f"{_rank_mean_base_preprocess_dir}/panel_base_preview.xlsx"
        ),
        "preprocess_summary_path": (
            f"{_rank_mean_base_preprocess_dir}/panel_base_summary.json"
        ),
        "regression_input_path": (
            f"{_rank_mean_base_preprocess_dir}/panel_base.parquet"
        ),
        "correlation_output_dir": (
            f"{_rank_mean_base_preprocess_dir}/variable_correlation_check"
        ),
        "interactions": [],
        "output_dir": _rank_mean_base_regression_dir,
    }
)

# base 是包含六个控制变量的对照模型，因此补回从 noctrlLTM 配置复制时
# 缺少的长期动量控制变量及其缩尾配置。
_rank_mean_base_config["controls"].insert(1, "CtrlRetLTM")
_rank_mean_base_config["winsorize"]["columns"].insert(
    _rank_mean_base_config["winsorize"]["columns"].index("CtrlRetSTR") + 1,
    "CtrlRetLTM",
)

# 每一步都写入 base 模型自己的目录，避免覆盖 interaction 模型的结果。
for _step in _rank_mean_base_config["pipeline"]:
    _step_name = _step["name"]
    if _step_name == "preprocess":
        _step["outputs"] = [
            f"{_rank_mean_base_preprocess_dir}/panel_base.parquet",
            f"{_rank_mean_base_preprocess_dir}/panel_base_summary.json",
        ]
    elif _step_name == "correlation_check":
        _step["outputs"] = [
            f"{_rank_mean_base_preprocess_dir}/variable_correlation_check/"
            "fama_macbeth_correlation_summary_long.csv",
            f"{_rank_mean_base_preprocess_dir}/variable_correlation_check/"
            "fama_macbeth_time_series_vif_summary.csv",
        ]
    elif _step_name == "regression":
        _step["outputs"] = [
            f"{_rank_mean_base_regression_dir}/fama_macbeth_results.csv",
            f"{_rank_mean_base_regression_dir}/run_metadata.json",
        ]
    elif _step_name == "portfolio_sorting":
        _step["outputs"] = [
            f"{_rank_mean_base_regression_dir}/portfolio_sorting/"
            "portfolio_sorting_registry.json"
        ]

REGISTRY[_rank_mean_base_key] = _rank_mean_base_config


# 该稳健性模型仅删除长期动量控制变量 CtrlRetLTM；FAC、对应 rank_mean
# 主效应及其他控制变量均与 base 模型保持一致。
_rank_mean_no_ltm_key = "fm_baseline_interaction_base_noctrlmomentum"
_rank_mean_no_ltm_config = deepcopy(REGISTRY[_rank_mean_base_key])
_rank_mean_no_ltm_config["description"] = (
    "Fama-MacBeth 基础模型：FAC + 对应 rank_mean 主效应，不含交互项和长期动量控制变量 CtrlRetLTM"
)
_rank_mean_no_ltm_config["controls"] = [
    column
    for column in _rank_mean_no_ltm_config["controls"]
    if column != "CtrlRetLTM"
]
_rank_mean_no_ltm_config["winsorize"]["columns"] = [
    column
    for column in _rank_mean_no_ltm_config["winsorize"]["columns"]
    if column != "CtrlRetLTM"
]

# 将所有模型专属路径替换为新 key，保证两套结果可以并列比较而不会相互覆盖。
for _path_key in (
    "preprocess_output_path",
    "preprocess_preview_path",
    "preprocess_summary_path",
    "regression_input_path",
    "correlation_output_dir",
    "output_dir",
):
    _rank_mean_no_ltm_config[_path_key] = str(
        _rank_mean_no_ltm_config[_path_key]
    ).replace(_rank_mean_base_key, _rank_mean_no_ltm_key)

for _step in _rank_mean_no_ltm_config["pipeline"]:
    _step["outputs"] = [
        str(_output_path).replace(
            _rank_mean_base_key, _rank_mean_no_ltm_key
        )
        for _output_path in _step.get("outputs", [])
    ]

REGISTRY[_rank_mean_no_ltm_key] = _rank_mean_no_ltm_config


# 新的标准 interaction 模型以 base 为唯一基础，只增加 FAC 与对应期限
# rank_mean 的乘积项。rank_mean 主效应已经由 base 保留，满足交互项层级原则。
_interaction_key = "fm_baseline_interaction"
_interaction_config = deepcopy(REGISTRY[_rank_mean_base_key])
_interaction_config["description"] = (
    "Fama-MacBeth 基础模型：FAC + 对应 rank_mean 主效应及交互项 + 六个控制变量"
)
_interaction_config["interactions"] = ["{FAC,RANK_MEAN}"]

for _path_key in (
    "preprocess_output_path",
    "preprocess_preview_path",
    "preprocess_summary_path",
    "regression_input_path",
    "correlation_output_dir",
    "output_dir",
):
    _interaction_config[_path_key] = str(
        _interaction_config[_path_key]
    ).replace(_rank_mean_base_key, _interaction_key)

for _step in _interaction_config["pipeline"]:
    _step["outputs"] = [
        str(_output_path).replace(_rank_mean_base_key, _interaction_key)
        for _output_path in _step.get("outputs", [])
    ]

REGISTRY[_interaction_key] = _interaction_config


# alternative 模型从普通 baseline 出发：保留 FAC 和六个控制变量，并只增加
# FAC × CtrlRetLTM。CtrlRetLTM 已在 controls 中，因此无需重复登记额外主效应。
_interaction_alternative_key = "fm_baseline_interaction_alternative"
_interaction_alternative_config = deepcopy(REGISTRY["fm_baseline"])
_interaction_alternative_config.update(
    {
        "description": (
            "Fama-MacBeth 基础模型：FAC + FAC 与 CtrlRetLTM 的交互项 + "
            "六个控制变量"
        ),
        "interactions": ["{FAC,CtrlRetLTM}"],
        "interaction_main_effects": [],
        "interaction_centering": "cross_section_mean",
        "portfolio_sorting_factors": ["{FAC,CtrlRetLTM}"],
    }
)

# 普通 baseline 的清洗输出目录没有模型 key，不能用字符串替换；这里逐项明确
# 设置 alternative 的专属路径，防止覆盖 baseline 或其他 interaction 结果。
_interaction_alternative_preprocess_dir = (
    f"B_factors/output/{_interaction_alternative_key}"
)
_interaction_alternative_regression_dir = (
    f"D_analysis/output/fund_consistency/{_interaction_alternative_key}"
)
_interaction_alternative_config.update(
    {
        "preprocess_output_path": (
            f"{_interaction_alternative_preprocess_dir}/panel_base.parquet"
        ),
        "preprocess_preview_path": (
            f"{_interaction_alternative_preprocess_dir}/panel_base_preview.xlsx"
        ),
        "preprocess_summary_path": (
            f"{_interaction_alternative_preprocess_dir}/panel_base_summary.json"
        ),
        "regression_input_path": (
            f"{_interaction_alternative_preprocess_dir}/panel_base.parquet"
        ),
        "correlation_output_dir": (
            f"{_interaction_alternative_preprocess_dir}/variable_correlation_check"
        ),
        "output_dir": _interaction_alternative_regression_dir,
    }
)

for _step in _interaction_alternative_config["pipeline"]:
    _step_name = _step["name"]
    if _step_name == "preprocess":
        _step["outputs"] = [
            f"{_interaction_alternative_preprocess_dir}/panel_base.parquet",
            f"{_interaction_alternative_preprocess_dir}/panel_base_summary.json",
        ]
    elif _step_name == "correlation_check":
        _step["outputs"] = [
            f"{_interaction_alternative_preprocess_dir}/variable_correlation_check/"
            "fama_macbeth_correlation_summary_long.csv",
            f"{_interaction_alternative_preprocess_dir}/variable_correlation_check/"
            "fama_macbeth_time_series_vif_summary.csv",
        ]
    elif _step_name == "regression":
        _step["outputs"] = [
            f"{_interaction_alternative_regression_dir}/fama_macbeth_results.csv",
            f"{_interaction_alternative_regression_dir}/run_metadata.json",
        ]
    elif _step_name == "portfolio_sorting":
        _step["outputs"] = [
            f"{_interaction_alternative_regression_dir}/portfolio_sorting/"
            "portfolio_sorting_registry.json"
        ]

REGISTRY[_interaction_alternative_key] = _interaction_alternative_config


BASELINE_TERCILE_GROUPS = {
    "top33": {
        "label": "前三分组",
        "description": "排名均值前 1/3 样本",
        "filter_value": 3,
    },
    "mid33": {
        "label": "中三分组",
        "description": "排名均值中间 1/3 样本",
        "filter_value": 2,
    },
    "bottom33": {
        "label": "后三分组",
        "description": "排名均值后 1/3 样本",
        "filter_value": 1,
    },
}


def make_tercile_flag(factor: str) -> str:
    """根据 FAC_rank_vol 因子列名推导对应的三分组样本标记列。"""
    return "is_tercile_rank_mean_" + factor.removeprefix("FAC_rank_vol_")


def make_baseline_tercile_config(group_key: str) -> dict[str, object]:
    """从 baseline 配置派生排名均值三分组回归配置。"""
    if group_key not in BASELINE_TERCILE_GROUPS:
        raise ValueError(f"不支持的 baseline 三分组：{group_key}")

    group_config = BASELINE_TERCILE_GROUPS[group_key]
    model_key = f"fm_baseline_{group_key}"
    config = deepcopy(REGISTRY["fm_baseline_up"])
    config["description"] = (
        "Fama-MacBeth 基础模型"
        f"（{group_config['label']}）：一致性主效应 + 控制变量，"
        f"{group_config['description']}"
    )

    factors = list(config["factors"])
    factor_flags = {factor: make_tercile_flag(factor) for factor in factors}
    filter_value = int(group_config["filter_value"])
    config["sample_flag_columns"] = [
        "is_insample_future_ret_6m",
        *factor_flags.values(),
    ]
    config["factor_sample_filters"] = {
        factor: {flag: filter_value}
        for factor, flag in factor_flags.items()
    }

    # 三个新模型各自写入独立目录，避免覆盖现有 up/down 输出。
    preprocess_dir = f"B_factors/output/{model_key}"
    descriptive_dir = f"A_data/output/descriptive_analysis/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    config.update(
        {
            "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
            "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
            "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
            "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
            "correlation_output_dir": (
                f"{preprocess_dir}/variable_correlation_check"
            ),
            "output_dir": regression_dir,
        }
    )

    direction = group_key
    config["descriptive"] = {
        "input_path": f"{preprocess_dir}/panel_base.parquet",
        "output_dir": descriptive_dir,
        "prefix": model_key,
        "batches": [
            {
                "name": "y_future_ret_6m",
                "columns": ["future_ret_6m"],
            },
            *[
                {
                    "name": (
                        f"factor_{factor.removeprefix('FAC_rank_vol_')}_{direction}"
                    ),
                    "columns": [factor],
                    "filter_column": flag,
                    "filter_value": filter_value,
                }
                for factor, flag in factor_flags.items()
            ],
        ],
    }

    for step in config["pipeline"]:
        step_name = str(step["name"])
        if step_name == "preprocess":
            step["outputs"] = [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ]
        elif step_name == "descriptive":
            step["outputs"] = [
                f"{descriptive_dir}/{model_key}_y_future_ret_6m_descriptive.xlsx"
            ]
        elif step_name == "correlation_check":
            step["outputs"] = [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ]
        elif step_name == "regression":
            step["outputs"] = [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ]
        elif step_name == "portfolio_sorting":
            step["outputs"] = [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ]

    return config


for _tercile_group_key in BASELINE_TERCILE_GROUPS:
    REGISTRY[f"fm_baseline_{_tercile_group_key}"] = (
        make_baseline_tercile_config(_tercile_group_key)
    )


# 跨期限替代指标只对应一条回归，而原始 baseline 会分别对五个 FAC 指标回归。
# interaction 使用与替代波动率完全一致的四期限排名均值。
# up/down 使用跨期限排名均值自身的中位数组，保证分组口径与替代指标一致。
CROSS_HORIZON_FACTOR = "rank_vol_across_horizons_1m_3m_6m_12m"
CROSS_HORIZON_RANK_MEAN = "rank_mean_across_horizons_1m_3m_6m_12m"
CROSS_HORIZON_MEDIAN_FLAG = (
    "is_median_rank_mean_across_horizons_1m_3m_6m_12m"
)
CROSS_HORIZON_TERCILE_FLAG = (
    "is_tercile_rank_mean_across_horizons_1m_3m_6m_12m"
)
CROSS_HORIZON_MODEL_SOURCES = {
    "fm_baseline_rank_vol_across_horizons": "fm_baseline",
    "fm_baseline_down_rank_vol_across_horizons": "fm_baseline_down",
    "fm_baseline_up_rank_vol_across_horizons": "fm_baseline_up",
    # is_interaction 分支会剔除 CtrlRetLTM，所以这套跨期限交互模型本质上
    # 一直是 noctrlLTM 口径；显式加上后缀，避免和下面补回 CtrlRetLTM 的
    # fm_baseline_interaction_rank_vol_across_horizons 混淆。
    "fm_baseline_interaction_rank_vol_across_horizons_noctrlLTM": (
        "fm_baseline_interaction"
    ),
    "fm_baseline_interaction_alternative_rank_vol_across_horizons": (
        "fm_baseline_interaction_alternative"
    ),
    # base 模型只有 FAC + rank_mean 主效应、不含交互项，跨期限版本同样只
    # 替换 FAC 和 rank_mean 为对应的跨期限列，不构造乘积项。
    "fm_baseline_interaction_base_rank_vol_across_horizons": (
        "fm_baseline_interaction_base"
    ),
    "fm_baseline_interaction_base_noctrlmomentum_rank_vol_across_horizons": (
        "fm_baseline_interaction_base_noctrlmomentum"
    ),
}


def make_cross_horizon_config(
    model_key: str, source_model_key: str
) -> dict[str, object]:
    """复制 baseline 规格，并改成单一跨期限排名波动率指标。"""
    config = deepcopy(REGISTRY[source_model_key])
    config["description"] = (
        str(config["description"])
        + "；替代指标为过去 1/3/6/12 个月收益排名的跨期限波动率"
    )
    config["factors"] = [CROSS_HORIZON_FACTOR]
    config["factor_group_suffixes"] = {
        CROSS_HORIZON_FACTOR: "rank_vol_across_horizons_1m_3m_6m_12m"
    }

    # 每个新模型使用独立的清洗、诊断和回归目录，避免覆盖原 baseline 结果。
    preprocess_dir = f"B_factors/output/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    config.update(
        {
            "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
            "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
            "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
            "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
            "correlation_output_dir": (
                f"{preprocess_dir}/variable_correlation_check"
            ),
            "output_dir": regression_dir,
        }
    )

    # 替代指标是连续变量，和原 FAC 一样按月进行 1%/99% 缩尾。
    original_factors = set(REGISTRY[source_model_key]["factors"])
    config["winsorize"]["columns"] = [
        column
        for column in config["winsorize"]["columns"]
        if column not in original_factors
    ]
    config["winsorize"]["columns"].insert(1, CROSS_HORIZON_FACTOR)

    is_up = source_model_key == "fm_baseline_up"
    is_down = source_model_key == "fm_baseline_down"
    is_interaction = source_model_key == "fm_baseline_interaction"
    is_base_main_effect = source_model_key in {
        "fm_baseline_interaction_base",
        "fm_baseline_interaction_base_noctrlmomentum",
    }
    if is_up or is_down:
        # 原模型按每个 FAC 对应的 rank_mean 分组；替代模型只有一个跨期限指标，
        # 因此使用同一组四期限 rank_mean 自身的中位数组，2 为上组、-2 为下组。
        filter_value = 2 if is_up else -2
        direction = "up" if is_up else "down"
        config["sample_flag_columns"] = [
            "is_insample_future_ret_6m",
            CROSS_HORIZON_MEDIAN_FLAG,
        ]
        config["factor_sample_filters"] = {
            CROSS_HORIZON_FACTOR: {
                CROSS_HORIZON_MEDIAN_FLAG: filter_value,
            }
        }
        config["descriptive"] = {
            "input_path": f"{preprocess_dir}/panel_base.parquet",
            "output_dir": f"A_data/output/descriptive_analysis/{model_key}",
            "prefix": model_key,
            "batches": [
                {
                    "name": "y_future_ret_6m",
                    "columns": ["future_ret_6m"],
                },
                {
                    "name": f"factor_cross_horizon_{direction}",
                    "columns": [CROSS_HORIZON_FACTOR],
                    "filter_column": CROSS_HORIZON_MEDIAN_FLAG,
                    "filter_value": filter_value,
                },
            ],
        }
    else:
        config["sample_flag_columns"] = ["is_insample_future_ret_6m"]
        config["factor_sample_filters"] = {}

    if is_interaction:
        # 新因子名不含原 FAC 的 m/n 后缀，无法使用 RANK_MEAN 自动推导，
        # 所以显式写出口径匹配的四期限排名均值列。
        interaction = f"{{FAC,{CROSS_HORIZON_RANK_MEAN}}}"
        config["extra_columns"] = [CROSS_HORIZON_RANK_MEAN]
        config["interaction_main_effects"] = [CROSS_HORIZON_RANK_MEAN]
        config["interactions"] = [interaction]
        # 与 fm_baseline_interaction_noctrlLTM 保持一致：FAC、rank_mean 主效应
        # 及交互项均按月度截面去均值处理。
        config["interaction_centering"] = "cross_section_mean"
        config["portfolio_sorting_factors"] = [interaction]
        config["controls"] = [
            column for column in config["controls"] if column != "CtrlRetLTM"
        ]
        config["winsorize"]["columns"] = [
            column
            for column in config["winsorize"]["columns"]
            if column != "CtrlRetLTM"
        ]
        # description 是从 fm_baseline_interaction（六个控制变量）继承来的文案；
        # 剔除 CtrlRetLTM 后实际只剩五个控制变量，必须同步更正，否则会和
        # controls 列表本身矛盾。
        config["description"] = config["description"].replace(
            "六个控制变量", "五个控制变量"
        )
    elif is_base_main_effect:
        # base 系列模型没有交互项，只需要把 FAC 对应的 rank_mean 主效应换成
        # 跨期限排名均值；同样因为列名前缀不匹配，不能用 RANK_MEAN 占位符。
        config["extra_columns"] = [CROSS_HORIZON_RANK_MEAN]
        config["interaction_main_effects"] = [CROSS_HORIZON_RANK_MEAN]
        config["portfolio_sorting_factors"] = [
            f"{{FAC,{CROSS_HORIZON_RANK_MEAN}}}"
        ]
        # interactions 保持源模型的 []，controls 保持源模型口径（base 含
        # CtrlRetLTM，noctrlmomentum 不含），不做任何增删。

    # pipeline 的关键输出检查也必须指向新目录；description 步骤只存在于
    # up/down 模型，因此按步骤名称分别生成路径。
    for step in config["pipeline"]:
        step_name = str(step["name"])
        if step_name == "preprocess":
            step["outputs"] = [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ]
        elif step_name == "descriptive":
            step["outputs"] = [
                "A_data/output/descriptive_analysis/"
                f"{model_key}/{model_key}_y_future_ret_6m_descriptive.xlsx"
            ]
        elif step_name == "correlation_check":
            step["outputs"] = [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ]
        elif step_name == "regression":
            step["outputs"] = [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ]
        elif step_name == "portfolio_sorting":
            step["outputs"] = [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ]

    return config


for _model_key, _source_model_key in CROSS_HORIZON_MODEL_SOURCES.items():
    REGISTRY[_model_key] = make_cross_horizon_config(
        _model_key, _source_model_key
    )


# fm_baseline_interaction_rank_vol_across_horizons_noctrlLTM 剔除了 CtrlRetLTM；
# 这里补回 CtrlRetLTM，得到与 fm_baseline_interaction（不带 noctrlLTM 后缀 =
# 六个控制变量）同样的命名习惯的跨期限版本。除控制变量外与 noctrlLTM 版本
# 完全一致：同一个跨期限 FAC、同一个 CROSS_HORIZON_RANK_MEAN 主效应及交互项。
_rvh_noctrlltm_key = "fm_baseline_interaction_rank_vol_across_horizons_noctrlLTM"
_rvh_with_ltm_key = "fm_baseline_interaction_rank_vol_across_horizons"
_rvh_with_ltm_config = deepcopy(REGISTRY[_rvh_noctrlltm_key])
_rvh_with_ltm_config["description"] = (
    "Fama-MacBeth 基础模型：FAC + 对应 rank_mean 主效应及交互项 + 六个控制变量"
    "；替代指标为过去 1/3/6/12 个月收益排名的跨期限波动率"
)
_rvh_with_ltm_config["controls"].insert(1, "CtrlRetLTM")
_rvh_with_ltm_config["winsorize"]["columns"].insert(
    _rvh_with_ltm_config["winsorize"]["columns"].index("CtrlRetSTR") + 1,
    "CtrlRetLTM",
)

_rvh_with_ltm_preprocess_dir = f"B_factors/output/{_rvh_with_ltm_key}"
_rvh_with_ltm_regression_dir = (
    f"D_analysis/output/fund_consistency/{_rvh_with_ltm_key}"
)
_rvh_with_ltm_config.update(
    {
        "preprocess_output_path": (
            f"{_rvh_with_ltm_preprocess_dir}/panel_base.parquet"
        ),
        "preprocess_preview_path": (
            f"{_rvh_with_ltm_preprocess_dir}/panel_base_preview.xlsx"
        ),
        "preprocess_summary_path": (
            f"{_rvh_with_ltm_preprocess_dir}/panel_base_summary.json"
        ),
        "regression_input_path": (
            f"{_rvh_with_ltm_preprocess_dir}/panel_base.parquet"
        ),
        "correlation_output_dir": (
            f"{_rvh_with_ltm_preprocess_dir}/variable_correlation_check"
        ),
        "output_dir": _rvh_with_ltm_regression_dir,
    }
)

for _step in _rvh_with_ltm_config["pipeline"]:
    _step_name = _step["name"]
    if _step_name == "preprocess":
        _step["outputs"] = [
            f"{_rvh_with_ltm_preprocess_dir}/panel_base.parquet",
            f"{_rvh_with_ltm_preprocess_dir}/panel_base_summary.json",
        ]
    elif _step_name == "correlation_check":
        _step["outputs"] = [
            f"{_rvh_with_ltm_preprocess_dir}/variable_correlation_check/"
            "fama_macbeth_correlation_summary_long.csv",
            f"{_rvh_with_ltm_preprocess_dir}/variable_correlation_check/"
            "fama_macbeth_time_series_vif_summary.csv",
        ]
    elif _step_name == "regression":
        _step["outputs"] = [
            f"{_rvh_with_ltm_regression_dir}/fama_macbeth_results.csv",
            f"{_rvh_with_ltm_regression_dir}/run_metadata.json",
        ]
    elif _step_name == "portfolio_sorting":
        _step["outputs"] = [
            f"{_rvh_with_ltm_regression_dir}/portfolio_sorting/"
            "portfolio_sorting_registry.json"
        ]

REGISTRY[_rvh_with_ltm_key] = _rvh_with_ltm_config


CROSS_HORIZON_TERCILE_GROUPS = {
    "top33": {
        "label": "前三分组",
        "description": "跨期限排名均值前 1/3 样本",
        "filter_value": 3,
    },
    "mid33": {
        "label": "中三分组",
        "description": "跨期限排名均值中间 1/3 样本",
        "filter_value": 2,
    },
    "bottom33": {
        "label": "后三分组",
        "description": "跨期限排名均值后 1/3 样本",
        "filter_value": 1,
    },
}


def make_cross_horizon_tercile_config(group_key: str) -> dict[str, object]:
    """从 fm_baseline_up_rank_vol_across_horizons 派生跨期限三分组配置。"""
    if group_key not in CROSS_HORIZON_TERCILE_GROUPS:
        raise ValueError(f"不支持的跨期限三分组：{group_key}")

    group_config = CROSS_HORIZON_TERCILE_GROUPS[group_key]
    model_key = f"fm_baseline_{group_key}_rank_vol_across_horizons"
    config = deepcopy(REGISTRY["fm_baseline_up_rank_vol_across_horizons"])
    config["description"] = (
        "Fama-MacBeth 基础模型"
        f"（{group_config['label']}）：跨期限排名波动率主效应 + 控制变量，"
        f"{group_config['description']}"
    )

    filter_value = int(group_config["filter_value"])
    config["sample_flag_columns"] = [
        "is_insample_future_ret_6m",
        CROSS_HORIZON_TERCILE_FLAG,
    ]
    config["factor_sample_filters"] = {
        CROSS_HORIZON_FACTOR: {
            CROSS_HORIZON_TERCILE_FLAG: filter_value,
        }
    }

    # 三个三分组模型各自写入独立目录，避免覆盖中位数组或原 baseline 输出。
    preprocess_dir = f"B_factors/output/{model_key}"
    descriptive_dir = f"A_data/output/descriptive_analysis/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    config.update(
        {
            "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
            "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
            "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
            "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
            "correlation_output_dir": (
                f"{preprocess_dir}/variable_correlation_check"
            ),
            "output_dir": regression_dir,
        }
    )

    config["descriptive"] = {
        "input_path": f"{preprocess_dir}/panel_base.parquet",
        "output_dir": descriptive_dir,
        "prefix": model_key,
        "batches": [
            {
                "name": "y_future_ret_6m",
                "columns": ["future_ret_6m"],
            },
            {
                "name": f"factor_cross_horizon_{group_key}",
                "columns": [CROSS_HORIZON_FACTOR],
                "filter_column": CROSS_HORIZON_TERCILE_FLAG,
                "filter_value": filter_value,
            },
        ],
    }

    for step in config["pipeline"]:
        step_name = str(step["name"])
        if step_name == "preprocess":
            step["outputs"] = [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ]
        elif step_name == "descriptive":
            step["outputs"] = [
                f"{descriptive_dir}/{model_key}_y_future_ret_6m_descriptive.xlsx"
            ]
        elif step_name == "correlation_check":
            step["outputs"] = [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ]
        elif step_name == "regression":
            step["outputs"] = [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ]
        elif step_name == "portfolio_sorting":
            step["outputs"] = [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ]

    return config


for _group_key in CROSS_HORIZON_TERCILE_GROUPS:
    REGISTRY[f"fm_baseline_{_group_key}_rank_vol_across_horizons"] = (
        make_cross_horizon_tercile_config(_group_key)
    )


CROSS_HORIZON_ALTERNATE_Y_HORIZONS = (1, 3, 12)


def make_cross_horizon_y_horizon_config(
    model_key: str, source_model_key: str, horizon: int
) -> dict[str, object]:
    """从某个跨期限模型（6m 版本）派生指定未来收益期限的版本。"""
    config = deepcopy(REGISTRY[source_model_key])
    y_col = f"future_ret_{horizon}m"
    old_y_col = str(config["y"])
    old_insample_flag = "is_insample_future_ret_6m"
    new_insample_flag = f"is_insample_future_ret_{horizon}m"

    # y 变成 1m/3m/12m 时，样本内标记也必须同步切换到同期限；
    # 否则会用 6m 的可回归样本去估计其他期限收益，样本口径会错位。
    config["description"] = (
        str(config["description"])
        + f"；未来收益期限改为 {horizon} 个月"
    )
    config["y"] = y_col
    config["sample_filters"] = {
        (new_insample_flag if column == old_insample_flag else column): value
        for column, value in config["sample_filters"].items()
    }
    config["sample_flag_columns"] = [
        new_insample_flag if column == old_insample_flag else column
        for column in config["sample_flag_columns"]
    ]

    # 清洗脚本只保留 registry["y"] 对应的一列未来收益；winsorize
    # 清单也要同步替换，否则新 y 不会按月缩尾。
    config["winsorize"]["columns"] = [
        y_col if column == old_y_col else column
        for column in config["winsorize"]["columns"]
    ]

    # 每个期限版本写到独立目录，避免覆盖同分组 6m 默认模型的结果。
    preprocess_dir = f"B_factors/output/{model_key}"
    descriptive_dir = f"A_data/output/descriptive_analysis/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    config.update(
        {
            "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
            "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
            "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
            "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
            "correlation_output_dir": (
                f"{preprocess_dir}/variable_correlation_check"
            ),
            "output_dir": regression_dir,
        }
    )

    descriptive_config = deepcopy(config["descriptive"])
    descriptive_config.update(
        {
            "input_path": f"{preprocess_dir}/panel_base.parquet",
            "output_dir": descriptive_dir,
            "prefix": model_key,
        }
    )
    descriptive_batches = deepcopy(descriptive_config["batches"])
    descriptive_batches[0] = {
        "name": f"y_future_ret_{horizon}m",
        "columns": [y_col],
    }
    descriptive_config["batches"] = descriptive_batches
    config["descriptive"] = descriptive_config

    for step in config["pipeline"]:
        step_name = str(step["name"])
        if step_name == "preprocess":
            step["outputs"] = [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ]
        elif step_name == "descriptive":
            step["outputs"] = [
                f"{descriptive_dir}/{model_key}_y_future_ret_{horizon}m_descriptive.xlsx"
            ]
        elif step_name == "correlation_check":
            step["outputs"] = [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ]
        elif step_name == "regression":
            step["outputs"] = [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ]
        elif step_name == "portfolio_sorting":
            step["outputs"] = [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ]

    return config


_CROSS_HORIZON_GROUP_KEYS = ("up", "down", "top33", "mid33", "bottom33")
for _group_key in _CROSS_HORIZON_GROUP_KEYS:
    _base_key = f"fm_baseline_{_group_key}_rank_vol_across_horizons"
    for _horizon in CROSS_HORIZON_ALTERNATE_Y_HORIZONS:
        _new_key = f"{_base_key}_y{_horizon}m"
        REGISTRY[_new_key] = make_cross_horizon_y_horizon_config(
            _new_key, _base_key, _horizon
        )


# 单窗口 FAC（m3_n6/m6_n3/m6_n6/m6_n12/m12_n6, pairwise1）分层模型的
# 其他未来收益期限版本。派生逻辑与跨期限系列完全一致：y、样本内标记、
# winsorize 收益列和输出目录一起切换；median/tercile 分组标记只依赖
# 历史排名信息，不随 y 期限变化，因此原样保留。
_SINGLE_WINDOW_GROUP_KEYS = ("up", "down", "top33", "mid33", "bottom33")
for _group_key in _SINGLE_WINDOW_GROUP_KEYS:
    _base_key = f"fm_baseline_{_group_key}"
    for _horizon in CROSS_HORIZON_ALTERNATE_Y_HORIZONS:
        _new_key = f"{_base_key}_y{_horizon}m"
        REGISTRY[_new_key] = make_cross_horizon_y_horizon_config(
            _new_key, _base_key, _horizon
        )


HEATMAP_GROUP_MODELS = {
    "fm_heatmap_full": {
        "label": "热力图全样本",
        "description": "不按 rank_mean 分组的全样本主检验",
        "flag_prefix": None,
        "filter_value": None,
    },
    "fm_heatmap_up": {
        "label": "热力图上半组",
        "description": "rank_mean 中位数以上样本",
        "flag_prefix": "is_median_",
        "filter_value": 2,
    },
    "fm_heatmap_down": {
        "label": "热力图下半组",
        "description": "rank_mean 中位数以下样本",
        "flag_prefix": "is_median_",
        "filter_value": -2,
    },
    "fm_heatmap_top33": {
        "label": "热力图前三分组",
        "description": "rank_mean 前 1/3 样本",
        "flag_prefix": "is_tercile_",
        "filter_value": 3,
    },
    "fm_heatmap_mid33": {
        "label": "热力图中三分组",
        "description": "rank_mean 中间 1/3 样本",
        "flag_prefix": "is_tercile_",
        "filter_value": 2,
    },
    "fm_heatmap_bottom33": {
        "label": "热力图后三分组",
        "description": "rank_mean 后 1/3 样本",
        "flag_prefix": "is_tercile_",
        "filter_value": 1,
    },
}


def make_heatmap_factor(m: int, n: int, pairwise: int) -> str:
    """按热力图窗口规格生成 FAC_rank_vol 因子列名。"""
    return f"FAC_rank_vol_m{m}_n{n}_pairwise{pairwise}"


def make_heatmap_rank_mean_suffix(m: int, n: int, pairwise: int) -> str:
    """生成 rank_mean 后缀，供 median/tercile 筛选列共用。"""
    return f"rank_mean_m{m}_n{n}_pairwise{pairwise}"


def make_heatmap_group_flag(
    flag_prefix: str, m: int, n: int, pairwise: int
) -> str:
    """按模型分组口径生成某个 factor 对应的样本筛选列。"""
    return f"{flag_prefix}{make_heatmap_rank_mean_suffix(m, n, pairwise)}"


def make_heatmap_factors() -> list[str]:
    """生成排除 n=1 后的 132 个热力图 FAC_rank_vol 因子。"""
    return [
        make_heatmap_factor(m, n, pairwise)
        for m, n, pairwise in HEATMAP_PAIRWISE1_SPECS
    ]


def make_heatmap_factor_group_suffixes() -> dict[str, str]:
    """生成热力图因子到输出短名称的映射。"""
    return {
        make_heatmap_factor(m, n, pairwise): f"consistency_m{m}_n{n}_pairwise{pairwise}"
        for m, n, pairwise in HEATMAP_PAIRWISE1_SPECS
    }


def make_heatmap_factor_sample_filters(
    flag_prefix: str, filter_value: int
) -> dict[str, dict[str, int]]:
    """为每个热力图 factor 生成自己的分组筛选条件。"""
    return {
        make_heatmap_factor(m, n, pairwise): {
            make_heatmap_group_flag(flag_prefix, m, n, pairwise): filter_value
        }
        for m, n, pairwise in HEATMAP_PAIRWISE1_SPECS
    }


def make_heatmap_sample_flag_columns(flag_prefix: str) -> list[str]:
    """列出热力图模型需要保留的基础样本标记和分组标记。"""
    return [
        "is_insample_future_ret_6m",
        *[
            make_heatmap_group_flag(flag_prefix, m, n, pairwise)
            for m, n, pairwise in HEATMAP_PAIRWISE1_SPECS
        ],
    ]


def make_heatmap_config(model_key: str) -> dict[str, object]:
    """从 baseline 派生一个热力图回归配置。

    Full sample 不使用 rank_mean 分组；其余模型中，每个 factor 都使用同一
    (m,n) 下自己的 rank_mean 分组列，避免把其他窗口的分组误套过来。
    """
    if model_key not in HEATMAP_GROUP_MODELS:
        raise ValueError(f"不支持的热力图模型：{model_key}")

    group_config = HEATMAP_GROUP_MODELS[model_key]
    raw_flag_prefix = group_config["flag_prefix"]
    is_full_sample = raw_flag_prefix is None
    flag_prefix = "" if is_full_sample else str(raw_flag_prefix)
    filter_value = None if is_full_sample else int(group_config["filter_value"])
    factors = make_heatmap_factors()
    preprocess_dir = f"B_factors/output/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"

    config = deepcopy(REGISTRY["fm_baseline"])
    config.update(
        {
            "description": (
                "Fama-MacBeth 热力图模型"
                f"（{group_config['label']}）：一致性主效应 + baseline 控制变量，"
                f"{group_config['description']}；m=1..12，n=2..12，pairwise=1"
            ),
            "window_policy": "热力图专用：m=单期收益期限（月），n=排名期数，pairwise=1",
            "window_specs": make_window_spec_metadata(HEATMAP_PAIRWISE1_SPECS),
            "preprocess_input_path": HEATMAP_PANEL_INPUT_PATH,
            "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
            "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
            "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
            "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
            "correlation_output_dir": (
                f"{preprocess_dir}/variable_correlation_check"
            ),
            "factors": factors,
            "sample_flag_columns": ["is_insample_future_ret_6m"]
            if is_full_sample
            else make_heatmap_sample_flag_columns(flag_prefix),
            "factor_sample_filters": {}
            if is_full_sample
            else make_heatmap_factor_sample_filters(flag_prefix, int(filter_value)),
            "output_dir": regression_dir,
            "factor_group_suffixes": make_heatmap_factor_group_suffixes(),
        }
    )

    # 热力图模型沿用 baseline 的 y 和 controls，但 winsorize 需要覆盖 132 个
    # 新 FAC 因子；控制变量列仍从 baseline 配置中原样保留。
    baseline_factor_set = set(REGISTRY["fm_baseline"]["factors"])
    config["winsorize"]["columns"] = [
        column
        for column in config["winsorize"]["columns"]
        if column not in baseline_factor_set
    ]
    config["winsorize"]["columns"][1:1] = factors

    for step in config["pipeline"]:
        step_name = str(step["name"])
        if step_name == "preprocess":
            step["outputs"] = [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ]
        elif step_name == "correlation_check":
            step["outputs"] = [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ]
        elif step_name == "regression":
            step["outputs"] = [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ]
        elif step_name == "portfolio_sorting":
            step["outputs"] = [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ]

    return config


for _heatmap_model_key in HEATMAP_GROUP_MODELS:
    REGISTRY[_heatmap_model_key] = make_heatmap_config(_heatmap_model_key)


def make_heatmap_y_horizon_config(
    model_key: str,
    source_model_key: str,
    y_col: str,
) -> dict[str, object]:
    """从热力图模型派生一个指定未来收益期限的专用配置。

    portfolio sorting 会读取 registry 中的 ``regression_input_path``。现有
    ``fm_heatmap_top33`` 的 B_factors 输出只保留 ``future_ret_6m``，因此要检验
    12 个月收益时，需要先用同一份 A_data 热力图 panel 重新清洗出一个独立的
    B_factors 面板。这里用派生配置集中替换 y、输出目录和 winsorize 的收益列，
    避免覆盖已经跑好的 6 个月主结果。
    """

    config = deepcopy(REGISTRY[source_model_key])
    preprocess_dir = f"B_factors/output/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    base_y_col = str(config["y"])

    config.update(
        {
            "description": (
                str(config["description"])
                + f"；portfolio sorting 专用未来收益期限：{y_col}"
            ),
            "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
            "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
            "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
            "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
            "correlation_output_dir": (
                f"{preprocess_dir}/variable_correlation_check"
            ),
            "output_dir": regression_dir,
            "y": y_col,
        }
    )

    # 清洗脚本只保留 registry["y"] 对应的一列未来收益；如果 y 换成 12m，
    # winsorize 清单也必须同步替换，否则输出面板不会按当前 y 做收益缩尾。
    config["winsorize"]["columns"] = [
        y_col if column == base_y_col else column
        for column in config["winsorize"]["columns"]
    ]

    # 每一步产物都放到新模型目录下，既方便审计，也避免误覆盖 6m 热力图结果。
    for step in config["pipeline"]:
        step_name = str(step["name"])
        if step_name == "preprocess":
            step["outputs"] = [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ]
        elif step_name == "correlation_check":
            step["outputs"] = [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ]
        elif step_name == "regression":
            step["outputs"] = [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ]
        elif step_name == "portfolio_sorting":
            step["outputs"] = [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ]

    return config


# m6_n12 的 12 个月 portfolio sorting 需要单独的 B_factors 面板来保留
# future_ret_12m。6 个月结果仍直接使用原有 fm_heatmap_top33。
REGISTRY["fm_heatmap_top33_y12m"] = make_heatmap_y_horizon_config(
    model_key="fm_heatmap_top33_y12m",
    source_model_key="fm_heatmap_top33",
    y_col="future_ret_12m",
)


# 三种非重叠 winrate 模型共享窗口、控制变量和估计设置。Top 33 与 Bottom 33
# 替代旧 Top 30/Bottom 30 设计；Top 50 保留为较宽松的门槛敏感度口径。
WINRATE_NONOVERLAP_METRICS = {
    "top50": "排名前50%",
    "top33": "排名前33%",
    "bottom33": "排名后33%",
}


def make_nonoverlap_winrate_config(metric: str) -> dict[str, object]:
    """基于现有 winrate 模型生成一个指定口径的非重叠模型配置。"""
    if metric not in WINRATE_NONOVERLAP_METRICS:
        raise ValueError(f"不支持的非重叠 winrate 口径：{metric}")

    model_key = f"fm_winrates_{metric}_nonoverlap"
    config = deepcopy(REGISTRY["fm_winrates_top50"])
    config.update(
        {
            "description": (
                "Fama-MacBeth 两层方向一致性模型（"
                f"{WINRATE_NONOVERLAP_METRICS[metric]}非重叠期间占比）："
                "hitrate 线性主效应 + 累积 hit 边际效应 + 控制变量"
            ),
            "window_policy": (
                "pairwise=m，收益窗口完全不重叠；"
                "m=单期收益期限（月），n=排名期数；m,n 均遍历 1..6"
            ),
            "window_specs": make_window_spec_metadata(WINRATE_NONOVERLAP_SPECS),
            "model_layers": {
                "primary": "hitrate=hitcount/n",
                "secondary": "Dk=1(hitcount>=k), k=1..n",
            },
            "factors": make_nonoverlap_winrate_factors(
                metric, WINRATE_NONOVERLAP_SPECS
            ),
            "factor_group_suffixes": make_nonoverlap_winrate_group_suffixes(
                metric, WINRATE_NONOVERLAP_SPECS
            ),
            "portfolio_sorting_factors": [
                make_winrate_hitrate_factor(metric, m, n, pairwise)
                for m, n, pairwise in WINRATE_NONOVERLAP_SPECS
            ],
            # 新网格依赖 heatmap 大面板中新增的非重叠排名列；B_factors 仍会为
            # 每个模型写出独立清洗面板，不会让三个模型共享可变中间结果。
            "preprocess_input_path": HEATMAP_PANEL_INPUT_PATH,
        }
    )

    # 这些字段都属于单个模型的产物，必须使用独立目录；共享的 heatmap 源面板
    # 已在上面显式指定，不参与路径替换。
    for path_key in (
        "preprocess_output_path",
        "preprocess_preview_path",
        "preprocess_summary_path",
        "regression_input_path",
        "correlation_output_dir",
        "output_dir",
    ):
        config[path_key] = str(config[path_key]).replace(
            "fm_winrates_top50", model_key
        )

    for step in config["pipeline"]:
        step["outputs"] = [
            str(output_path).replace("fm_winrates_top50", model_key)
            for output_path in step.get("outputs", [])
        ]

    return config


for _metric in WINRATE_NONOVERLAP_METRICS:
    _model_key = f"fm_winrates_{_metric}_nonoverlap"
    REGISTRY[_model_key] = make_nonoverlap_winrate_config(_metric)


# =============================================================================
# 市态一致性模型（2026-07 新课题）：4 个市态维度，每个维度 8 个模型 key。
#
# 数据前提：A_data/output/panel_base.parquet 已由
# 3_panel_base_mkt_condition.py / 3_panel_base_mkt_condition_factors.py /
# 3_panel_base_mkt_condition_future_returns.py 写入市态列、市态条件因子和
# 状态匹配未来收益。
#
# 模型清单（{dim} 取 hs300/style/size/indvol）：
# - fm_baseline_{dim}：市态 FAC 主效应 + 6 控制变量（对照 fm_baseline M1）
# - fm_baseline_interaction_noctrlLTM_{dim}：市态 FAC_c + 市态 rank_mean_c +
#   交互_c + 5 控制变量（对照 M3'）
# - fm_marginal_interaction_noctrlLTM_{dim}：在上一行基础上再加同期限普通
#   FAC_c、普通 rank_mean_c 及普通交互_c（FAC_PLAIN/RANK_MEAN_PLAIN 占位符
#   由回归与相关性脚本按当前市态 factor 剥离 regime 片段解析）
# - fm_winrates_top50_{dim}：市态 top50 累计 hit dummy 组 + 6 控制变量
# - fm_ymatch_{dim}_{regime}（每维度 2 个）：状态匹配检验，市态 FAC 对
#   同 regime 的状态匹配未来收益
# - fm_ymatch_cross_{dim}_{regime}（每维度 2 个）：反证检验，市态 FAC 对
#   对面 regime 的状态匹配未来收益
# =============================================================================

MKT_STATE_DIMENSIONS = {
    "hs300": ("hs300up", "hs300down"),
    "style": ("growth", "value"),
    "size": ("large", "small"),
    "indvol": ("highvol", "lowvol"),
}
MKT_STATE_WINDOW_SPECS = ((3, 6), (6, 3), (6, 6), (6, 12), (12, 6))
MKT_STATE_PAIRWISE = 1
MKT_STATE_WINRATE_SPECS = WINRATE_TOP50_PAIRWISE1_SPECS

MKT_STATE_CONTROLS_FULL = [
    "CtrlRetSTR",
    "CtrlRetLTM",
    "CtrlVol",
    "as_偏股混合型基金",
    "Ctrl_log_fund_size",
    "Ctrl_fund_age",
]
MKT_STATE_CONTROLS_NO_LTM = [
    column for column in MKT_STATE_CONTROLS_FULL if column != "CtrlRetLTM"
]
# 哑变量 as_偏股混合型基金 不参与 winsorize。
MKT_STATE_CONTROLS_FULL_WINSOR = [
    column for column in MKT_STATE_CONTROLS_FULL if column != "as_偏股混合型基金"
]
MKT_STATE_CONTROLS_NO_LTM_WINSOR = [
    column
    for column in MKT_STATE_CONTROLS_NO_LTM
    if column != "as_偏股混合型基金"
]


def make_state_fac_column(regime: str, m: int, n: int) -> str:
    """返回市态 FAC 因子列名。"""
    return f"FAC_rank_vol_{regime}_m{m}_n{n}_pairwise{MKT_STATE_PAIRWISE}"


def make_state_rank_mean_column(regime: str, m: int, n: int) -> str:
    """返回市态排名均值列名。"""
    return f"rank_mean_{regime}_m{m}_n{n}_pairwise{MKT_STATE_PAIRWISE}"


def make_state_fac_columns(regimes: tuple[str, ...]) -> list[str]:
    """按 regime 顺序展开全部市态 FAC 列。"""
    return [
        make_state_fac_column(regime, m, n)
        for regime in regimes
        for m, n in MKT_STATE_WINDOW_SPECS
    ]


def make_state_fac_group_suffixes(
    regimes: tuple[str, ...],
) -> dict[str, str]:
    """市态 FAC 到输出短名称的映射。"""
    return {
        make_state_fac_column(regime, m, n): (
            f"consistency_{regime}_m{m}_n{n}_pairwise{MKT_STATE_PAIRWISE}"
        )
        for regime in regimes
        for m, n in MKT_STATE_WINDOW_SPECS
    }


def _make_mkt_state_pipeline(model_key: str) -> list[dict[str, object]]:
    """生成市态模型统一的四步 pipeline 配置。"""
    preprocess_dir = f"B_factors/output/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    return [
        {
            "name": "preprocess",
            "script": "B_factors/scripts/run_factor_pipeline.py",
            "args": ["--registry-key", "{model}"],
            "outputs": [
                f"{preprocess_dir}/panel_base.parquet",
                f"{preprocess_dir}/panel_base_summary.json",
            ],
        },
        {
            "name": "correlation_check",
            "script": "B_factors/scripts/2_factor_correlation.py",
            "args": ["--model", "{model}"],
            "outputs": [
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_correlation_summary_long.csv",
                f"{preprocess_dir}/variable_correlation_check/"
                "fama_macbeth_time_series_vif_summary.csv",
            ],
        },
        {
            "name": "regression",
            "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
            "args": ["--model", "{model}"],
            "outputs": [
                f"{regression_dir}/fama_macbeth_results.csv",
                f"{regression_dir}/run_metadata.json",
            ],
        },
        {
            "name": "portfolio_sorting",
            "script": "D_analysis/scripts/portfolio_sorting.py",
            "args": ["--model", "{model}"],
            "outputs": [
                f"{regression_dir}/portfolio_sorting/"
                "portfolio_sorting_registry.json"
            ],
        },
    ]


def _make_mkt_state_config(
    model_key: str,
    description: str,
    y_column: str,
    insample_flag: str,
    factors: list[object],
    factor_group_suffixes: dict[object, str],
    controls: list[str],
    winsorize_factor_columns: list[str],
    control_winsor_columns: list[str],
    extra_columns: list[str] | None = None,
) -> dict[str, object]:
    """构造市态模型共享的完整 registry 配置。"""
    preprocess_dir = f"B_factors/output/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"
    return {
        "description": description,
        "date_col": "month_date",
        "id_columns": [
            "ifind_code",
            "month_date",
            "investment_type",
        ],
        "sample_filters": {insample_flag: 1},
        "sample_flag_columns": [insample_flag],
        "pipeline": _make_mkt_state_pipeline(model_key),
        "script": "D_analysis/scripts/consistency_fama_mac_regression.py",
        "preprocess_script": "B_factors/scripts/1_fund_consistency_factors_clear.py",
        "correlation_script": "B_factors/scripts/2_factor_correlation.py",
        "preprocess_input_path": "A_data/output/panel_base.parquet",
        "preprocess_output_path": f"{preprocess_dir}/panel_base.parquet",
        "preprocess_preview_path": f"{preprocess_dir}/panel_base_preview.xlsx",
        "preprocess_summary_path": f"{preprocess_dir}/panel_base_summary.json",
        "regression_input_path": f"{preprocess_dir}/panel_base.parquet",
        "correlation_output_dir": f"{preprocess_dir}/variable_correlation_check",
        "y": y_column,
        "factors": list(factors),
        "factor_sample_filters": {},
        "controls": list(controls),
        "extra_columns": list(extra_columns or []),
        "interactions": [],
        "output_dir": regression_dir,
        "min_cross_section_n": 50,
        "newey_west_lag": 5,
        "winsorize": {
            "group_column": "month_date",
            "lower_quantile": 0.01,
            "upper_quantile": 0.99,
            "columns": [
                y_column,
                *winsorize_factor_columns,
                *control_winsor_columns,
            ],
        },
        "factor_group_suffixes": dict(factor_group_suffixes),
    }


def make_mkt_state_models() -> dict[str, dict[str, object]]:
    """生成全部市态模型配置。"""
    models: dict[str, dict[str, object]] = {}

    for dim, regimes in MKT_STATE_DIMENSIONS.items():
        state_facs = make_state_fac_columns(regimes)
        state_rank_means = [
            make_state_rank_mean_column(regime, m, n)
            for regime in regimes
            for m, n in MKT_STATE_WINDOW_SPECS
        ]
        plain_facs = [
            f"FAC_rank_vol_m{m}_n{n}_pairwise{MKT_STATE_PAIRWISE}"
            for m, n in MKT_STATE_WINDOW_SPECS
        ]
        plain_rank_means = [
            f"rank_mean_m{m}_n{n}_pairwise{MKT_STATE_PAIRWISE}"
            for m, n in MKT_STATE_WINDOW_SPECS
        ]
        fac_suffixes = make_state_fac_group_suffixes(regimes)

        # 1. M1 对照：市态 FAC 主效应 + 6 控制变量。
        key = f"fm_baseline_{dim}"
        models[key] = _make_mkt_state_config(
            model_key=key,
            description=(
                f"Fama-MacBeth 市态基础模型（{dim}）：市态 FAC 主效应 + "
                "六个控制变量，对照 fm_baseline"
            ),
            y_column="future_ret_6m",
            insample_flag="is_insample_future_ret_6m",
            factors=list(state_facs),
            factor_group_suffixes=fac_suffixes,
            controls=MKT_STATE_CONTROLS_FULL,
            winsorize_factor_columns=state_facs,
            control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
        )

        # 2. M3' 对照：市态 FAC_c + 市态 rank_mean_c + 交互_c + 5 控制变量。
        key = f"fm_baseline_interaction_noctrlLTM_{dim}"
        config = _make_mkt_state_config(
            model_key=key,
            description=(
                f"Fama-MacBeth 市态交互模型（{dim}）：月度去均值后的市态 FAC、"
                "市态 rank_mean 及其交互项 + 五个控制变量（不含 CtrlRetLTM），"
                "对照 fm_baseline_interaction_noctrlLTM"
            ),
            y_column="future_ret_6m",
            insample_flag="is_insample_future_ret_6m",
            factors=list(state_facs),
            factor_group_suffixes=fac_suffixes,
            controls=MKT_STATE_CONTROLS_NO_LTM,
            winsorize_factor_columns=state_facs,
            control_winsor_columns=MKT_STATE_CONTROLS_NO_LTM_WINSOR,
            extra_columns=state_rank_means,
        )
        config["interaction_main_effects"] = ["RANK_MEAN"]
        config["interactions"] = ["{FAC,RANK_MEAN}"]
        config["interaction_centering"] = "cross_section_mean"
        config["portfolio_sorting_factors"] = ["{FAC,RANK_MEAN}"]
        models[key] = config

        # 3. marginal：市态与普通两套主效应及交互项同场竞争。
        key = f"fm_marginal_interaction_noctrlLTM_{dim}"
        config = _make_mkt_state_config(
            model_key=key,
            description=(
                f"Fama-MacBeth 市态边际贡献模型（{dim}）：市态 FAC_c + 市态 "
                "rank_mean_c + 市态交互_c + 同期限普通 FAC_c + 普通 rank_mean_c "
                "+ 普通交互_c + 五个控制变量（不含 CtrlRetLTM）。预期存在共线性，"
                "结论以 correlation_check 的 VIF 诊断为前提"
            ),
            y_column="future_ret_6m",
            insample_flag="is_insample_future_ret_6m",
            factors=list(state_facs),
            factor_group_suffixes=fac_suffixes,
            controls=MKT_STATE_CONTROLS_NO_LTM,
            winsorize_factor_columns=[*state_facs, *plain_facs],
            control_winsor_columns=MKT_STATE_CONTROLS_NO_LTM_WINSOR,
            extra_columns=[
                *state_rank_means,
                *plain_facs,
                *plain_rank_means,
            ],
        )
        config["interaction_main_effects"] = [
            "RANK_MEAN",
            "FAC_PLAIN",
            "RANK_MEAN_PLAIN",
        ]
        config["interactions"] = [
            "{FAC,RANK_MEAN}",
            "{FAC_PLAIN,RANK_MEAN_PLAIN}",
        ]
        config["interaction_centering"] = "cross_section_mean"
        models[key] = config

        # 4. 市态 winrates：top50 累计 hit dummy 组，对照 fm_winrates_top50。
        key = f"fm_winrates_top50_{dim}"
        winrate_factors: list[object] = []
        winrate_suffixes: dict[tuple[str, ...], str] = {}
        for regime in regimes:
            metric = f"top50_{regime}"
            winrate_factors.extend(
                make_winrate_factor_groups(metric, MKT_STATE_WINRATE_SPECS)
            )
            winrate_suffixes.update(
                {
                    group: f"winrate_{regime}_m{m}_n{n}_pairwise{pairwise}"
                    for (m, n, pairwise), group in zip(
                        MKT_STATE_WINRATE_SPECS,
                        make_winrate_factor_groups(
                            metric, MKT_STATE_WINRATE_SPECS
                        ),
                    )
                }
            )
        config = _make_mkt_state_config(
            model_key=key,
            description=(
                f"Fama-MacBeth 市态方向一致性模型（{dim}）：市态月份内排名前50%"
                "累计命中 dummy 组 + 六个控制变量，对照 fm_winrates_top50"
            ),
            y_column="future_ret_6m",
            insample_flag="is_insample_future_ret_6m",
            factors=winrate_factors,
            factor_group_suffixes=winrate_suffixes,
            controls=MKT_STATE_CONTROLS_FULL,
            winsorize_factor_columns=[],
            control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
        )
        config["window_policy"] = (
            "市态月份滚动选取：n 为市态月份数，m 为单期收益期限；"
            "最大回看 48 个月"
        )
        config["window_specs"] = make_window_spec_metadata(
            MKT_STATE_WINRATE_SPECS
        )
        models[key] = config

        # 5/6. 状态匹配与反证：FAC^{regime} 对同/异 regime 的状态匹配 Y。
        for regime_index, regime in enumerate(regimes):
            other_regime = regimes[1 - regime_index]
            regime_facs = [
                make_state_fac_column(regime, m, n)
                for m, n in MKT_STATE_WINDOW_SPECS
            ]
            regime_suffixes = {
                fac: f"consistency_{regime}_m{m}_n{n}_pairwise1"
                for fac, (m, n) in zip(regime_facs, MKT_STATE_WINDOW_SPECS)
            }

            key = f"fm_ymatch_{dim}_{regime}"
            ymatch_config = _make_mkt_state_config(
                model_key=key,
                description=(
                    f"Fama-MacBeth 状态匹配模型（{dim}/{regime}）：{regime} 市态 "
                    f"FAC 对未来最近 6 个 {regime} 市态月的累积收益 + 六个控制变量"
                ),
                y_column=f"future_ret_6m_{regime}",
                insample_flag=f"is_insample_future_ret_6m_{regime}",
                factors=list(regime_facs),
                factor_group_suffixes=regime_suffixes,
                controls=MKT_STATE_CONTROLS_FULL,
                winsorize_factor_columns=regime_facs,
                control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
            )
            # 状态匹配 Y 的日历持有期逐月不同，固定期组合排序不适用，
            # 因此 ymatch 系列不运行 portfolio_sorting 步骤。
            ymatch_config["pipeline"] = [
                step
                for step in ymatch_config["pipeline"]
                if step["name"] != "portfolio_sorting"
            ]
            models[key] = ymatch_config

            key = f"fm_ymatch_cross_{dim}_{regime}"
            ymatch_cross_config = _make_mkt_state_config(
                model_key=key,
                description=(
                    f"Fama-MacBeth 状态错配反证模型（{dim}/{regime}）：{regime} "
                    f"市态 FAC 对未来最近 6 个 {other_regime} 市态月的累积收益 "
                    "+ 六个控制变量，作为状态匹配模型的对照"
                ),
                y_column=f"future_ret_6m_{other_regime}",
                insample_flag=f"is_insample_future_ret_6m_{other_regime}",
                factors=list(regime_facs),
                factor_group_suffixes=regime_suffixes,
                controls=MKT_STATE_CONTROLS_FULL,
                winsorize_factor_columns=regime_facs,
                control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
            )
            ymatch_cross_config["pipeline"] = [
                step
                for step in ymatch_cross_config["pipeline"]
                if step["name"] != "portfolio_sorting"
            ]
            models[key] = ymatch_cross_config

    return models


for _mkt_state_key, _mkt_state_config in make_mkt_state_models().items():
    if _mkt_state_key in REGISTRY:
        raise ValueError(f"市态模型 key 与现有模型重名：{_mkt_state_key}")
    REGISTRY[_mkt_state_key] = _mkt_state_config


# ---------------------------------------------------------------------------
# 基准超额收益版一致性模型（投资目标分类课题，方案乙）。
# 因子由 A_data/scripts/3_panel_base_benchmark_excess_factors.py 写入面板：
# 排名输入从原始 m 月收益换成「基金收益 - 自身基准指数(.BI)同期收益」，
# 排名截面保持「月份 x 投资类型」不变。
# ---------------------------------------------------------------------------

BENCHMARK_EXCESS_WINDOW_SPECS = ((3, 6), (6, 3), (6, 6), (6, 12), (12, 6))
BENCHMARK_EXCESS_PAIRWISE = 1
# 稳健性模型 fm_bmk_objctrl 用投资目标分类 dummy 替换投资类型 dummy。
# as_绝对收益类 = 1(objective_class==1)；代码 2 已并入代码 3 作为基准组。
OBJECTIVE_ABS_DUMMY = "as_绝对收益类"
BENCHMARK_EXCESS_CONTROLS_OBJCTRL = [
    OBJECTIVE_ABS_DUMMY if column == "as_偏股混合型基金" else column
    for column in MKT_STATE_CONTROLS_FULL
]


def make_bmk_fac_column(m: int, n: int) -> str:
    """返回基准超额 FAC 因子列名。"""
    return f"FAC_rank_vol_bmk_m{m}_n{n}_pairwise{BENCHMARK_EXCESS_PAIRWISE}"


def make_bmk_fac_columns() -> list[str]:
    """按窗口顺序展开全部基准超额 FAC 列。"""
    return [make_bmk_fac_column(m, n) for m, n in BENCHMARK_EXCESS_WINDOW_SPECS]


def make_bmk_fac_group_suffixes() -> dict[str, str]:
    """基准超额 FAC 到输出短名称的映射。"""
    return {
        make_bmk_fac_column(m, n): (
            f"consistency_bmk_m{m}_n{n}_pairwise{BENCHMARK_EXCESS_PAIRWISE}"
        )
        for m, n in BENCHMARK_EXCESS_WINDOW_SPECS
    }


def make_benchmark_excess_models() -> dict[str, dict[str, object]]:
    """生成基准超额收益版模型配置。

    - fm_bmk：主模型。除因子换成 FAC_rank_vol_bmk_* 外，控制变量、样本
      口径、winsorize 等全部与 fm_baseline 逐项一致，保证溢价差异可以
      干净地归因于因子口径变化。
    - fm_bmk_objctrl：稳健性模型。唯一差别是把控制变量中的投资类型
      dummy（as_偏股混合型基金）换成投资目标分类 dummy（as_绝对收益类），
      检验结论对该控制变量选择的敏感性。不设交互项。
    """
    bmk_facs = make_bmk_fac_columns()
    bmk_suffixes = make_bmk_fac_group_suffixes()

    models: dict[str, dict[str, object]] = {}
    models["fm_bmk"] = _make_mkt_state_config(
        model_key="fm_bmk",
        description=(
            "Fama-MacBeth 基准超额一致性基础模型：FAC_rank_vol_bmk 主效应 + "
            "六个控制变量（与 fm_baseline 完全一致），对照 fm_baseline"
        ),
        y_column="future_ret_6m",
        insample_flag="is_insample_future_ret_6m",
        factors=list(bmk_facs),
        factor_group_suffixes=bmk_suffixes,
        controls=MKT_STATE_CONTROLS_FULL,
        winsorize_factor_columns=bmk_facs,
        control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
    )
    models["fm_bmk_objctrl"] = _make_mkt_state_config(
        model_key="fm_bmk_objctrl",
        description=(
            "Fama-MacBeth 基准超额一致性稳健性模型：控制变量中投资类型 "
            "dummy 换成投资目标分类 dummy（as_绝对收益类），其余与 fm_bmk "
            "完全一致"
        ),
        y_column="future_ret_6m",
        insample_flag="is_insample_future_ret_6m",
        factors=list(bmk_facs),
        factor_group_suffixes=bmk_suffixes,
        controls=BENCHMARK_EXCESS_CONTROLS_OBJCTRL,
        winsorize_factor_columns=bmk_facs,
        # dummy（as_绝对收益类）与其他哑变量一样不参与 winsorize。
        control_winsor_columns=[
            column
            for column in BENCHMARK_EXCESS_CONTROLS_OBJCTRL
            if column != OBJECTIVE_ABS_DUMMY
        ],
    )

    # 3. top50 胜率版：累计 hit dummy 组，对照 fm_winrates_top50。
    # 面板列名 dummy_top50_bmk_* 恰好符合 metric="top50_bmk" 的生成规则。
    winrate_specs = tuple(
        (m, n, BENCHMARK_EXCESS_PAIRWISE)
        for m, n in BENCHMARK_EXCESS_WINDOW_SPECS
    )
    winrate_factors = make_winrate_factor_groups("top50_bmk", winrate_specs)
    winrate_suffixes = {
        group: f"winrate_bmk_m{m}_n{n}_pairwise{pairwise}"
        for (m, n, pairwise), group in zip(winrate_specs, winrate_factors)
    }
    models["fm_winrates_top50_bmk"] = _make_mkt_state_config(
        model_key="fm_winrates_top50_bmk",
        description=(
            "Fama-MacBeth 基准超额方向一致性模型：超额排名前50%累计命中 "
            "dummy 组 + 六个控制变量，对照 fm_winrates_top50"
        ),
        y_column="future_ret_6m",
        insample_flag="is_insample_future_ret_6m",
        factors=winrate_factors,
        factor_group_suffixes=winrate_suffixes,
        controls=MKT_STATE_CONTROLS_FULL,
        # dummy 因子不参与 winsorize，与 fm_winrates_top50 一致。
        winsorize_factor_columns=[],
        control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
    )

    # 4. 上半组子样本：对照 fm_baseline_up，用超额排名均值的中位数二分标记
    # （is_median_rank_mean_bmk_* == 2）逐因子筛选上半组。未配置 descriptive
    # 步骤（fm_baseline_up 的 descriptive 属于描述性统计附加产出，不影响回归）。
    up_config = _make_mkt_state_config(
        model_key="fm_bmk_up",
        description=(
            "Fama-MacBeth 基准超额一致性模型（上半组）：FAC_rank_vol_bmk 主"
            "效应 + 六个控制变量，超额排名均值中位数以上子样本，对照 "
            "fm_baseline_up"
        ),
        y_column="future_ret_6m",
        insample_flag="is_insample_future_ret_6m",
        factors=list(bmk_facs),
        factor_group_suffixes=bmk_suffixes,
        controls=MKT_STATE_CONTROLS_FULL,
        winsorize_factor_columns=bmk_facs,
        control_winsor_columns=MKT_STATE_CONTROLS_FULL_WINSOR,
    )
    up_median_flags = {
        make_bmk_fac_column(m, n): (
            f"is_median_rank_mean_bmk_m{m}_n{n}_"
            f"pairwise{BENCHMARK_EXCESS_PAIRWISE}"
        )
        for m, n in BENCHMARK_EXCESS_WINDOW_SPECS
    }
    up_config["factor_sample_filters"] = {
        fac: {flag: 2} for fac, flag in up_median_flags.items()
    }
    up_config["sample_flag_columns"] = [
        "is_insample_future_ret_6m",
        *up_median_flags.values(),
    ]
    models["fm_bmk_up"] = up_config

    return models


for _bmk_key, _bmk_config in make_benchmark_excess_models().items():
    if _bmk_key in REGISTRY:
        raise ValueError(f"基准超额模型 key 与现有模型重名：{_bmk_key}")
    REGISTRY[_bmk_key] = _bmk_config


# 统一给所有包含 correlation_check 的模型登记相关性可视化步骤。
# 集中在 REGISTRY 组装完成后追加，而不是逐个模型手写，避免派生模型漏登记
# 或输出路径替换出错。绘图脚本只读 correlation_check 的 CSV，不重算相关性。
CORRELATION_PLOTS_SCRIPT = "B_factors/scripts/2b_correlation_vif_plots.py"

for _plots_model_key, _plots_config in REGISTRY.items():
    _plots_pipeline = _plots_config.get("pipeline")
    if not isinstance(_plots_pipeline, list):
        continue
    _check_indexes = [
        index
        for index, _plots_step in enumerate(_plots_pipeline)
        if _plots_step.get("name") == "correlation_check"
    ]
    if not _check_indexes:
        continue
    if any(
        _plots_step.get("name") == "correlation_plots"
        for _plots_step in _plots_pipeline
    ):
        continue
    _plots_correlation_dir = _plots_config.get("correlation_output_dir")
    if _plots_correlation_dir is None:
        raise ValueError(
            f"模型 {_plots_model_key} 有 correlation_check 步骤，"
            "但缺少 correlation_output_dir，无法登记 correlation_plots。"
        )
    _plots_pipeline.insert(
        _check_indexes[0] + 1,
        {
            "name": "correlation_plots",
            "script": CORRELATION_PLOTS_SCRIPT,
            "args": ["--model", "{model}"],
            "outputs": [
                f"{_plots_correlation_dir}/figures/plots_manifest.json",
            ],
        },
    )


DEFAULT_REGRESSION_KEY = "fm_baseline"

# 旧命令行 key 仅作为向后兼容入口；REGISTRY 和所有新输出路径统一使用
# bottom33。这样旧自动化不会突然报错，但新一轮结果不会再写入 bm33 目录。
LEGACY_REGRESSION_KEY_ALIASES: dict[str, str] = {
    canonical_key.replace("bottom33", "bm33"): canonical_key
    for canonical_key in REGISTRY
    if "bottom33" in canonical_key
}

# 普通固定期限未来收益的列名规则。市态匹配收益（例如
# future_ret_6m_hs300up）有自己逐月校验目标月份的逻辑，因此不会匹配这里。
PLAIN_FUTURE_RETURN_PATTERN = re.compile(r"^future_ret_(\d+)m$")
PLAIN_FUTURE_SAMPLE_FLAG_PATTERN = re.compile(
    r"^(?:is_insample|match_is_sample)_future_ret_\d+m$"
)


def normalize_plain_future_return_filters(
    config: dict[str, object],
) -> dict[str, object]:
    """让普通未来收益模型使用与 Y 同期限的两层样本筛选。

    ``is_insample`` 负责保证未来收益不跨过研究样本截止日；
    ``match_is_sample`` 负责保证从预测月到收益终点的每个月都属于可用样本。
    后者会排除未来持有期内发生基金经理团队变更、因而进入新 regime 的观察。

    这里在读取 registry 时集中规范化，避免 1/3/6/12 月派生模型各自维护列名，
    也能防止未来再次出现“Y 已换成 12m，但仍沿用 6m 样本标记”的错位。
    """

    y_column = str(config.get("y", ""))
    match = PLAIN_FUTURE_RETURN_PATTERN.fullmatch(y_column)
    if match is None:
        return config

    horizon = int(match.group(1))
    insample_column = f"is_insample_future_ret_{horizon}m"
    match_column = f"match_is_sample_future_ret_{horizon}m"

    # 保留分组等其他基础筛选，只替换普通未来收益对应的旧期限标记。
    sample_filters = {
        str(column): value
        for column, value in dict(config.get("sample_filters", {})).items()
        if PLAIN_FUTURE_SAMPLE_FLAG_PATTERN.fullmatch(str(column)) is None
    }
    sample_filters[insample_column] = 1
    sample_filters[match_column] = 1
    config["sample_filters"] = sample_filters

    # 清洗面板需要保留筛选列，供回归和组合排序再次核对同一口径。
    sample_flag_columns = [
        str(column)
        for column in list(config.get("sample_flag_columns", []))
        if PLAIN_FUTURE_SAMPLE_FLAG_PATTERN.fullmatch(str(column)) is None
    ]
    config["sample_flag_columns"] = list(
        dict.fromkeys([insample_column, match_column, *sample_flag_columns])
    )
    return config


def list_regression_keys() -> list[str]:
    """列出当前已经登记的回归模型版本。"""

    return sorted(REGISTRY)


def get_regression_config(key: str = DEFAULT_REGRESSION_KEY) -> dict[str, object]:
    """返回指定实验的配置副本，避免调用方误改全局 REGISTRY。"""

    key = LEGACY_REGRESSION_KEY_ALIASES.get(key, key)
    if key not in REGISTRY:
        available = ", ".join(list_regression_keys())
        raise KeyError(f"未知回归版本：{key}；可用版本：{available}")
    config = deepcopy(REGISTRY[key])
    return normalize_plain_future_return_filters(config)
