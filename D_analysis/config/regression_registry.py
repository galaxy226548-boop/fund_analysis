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
# 这里集中生成 12×12 的完整网格，避免在具体模型里手写 144 个变量名。
HEATMAP_PAIRWISE1_SPECS = tuple(
    (m, n, 1)
    for m in range(1, 13)
    for n in range(1, 13)
)
HEATMAP_PANEL_INPUT_PATH = "A_data/output/panel_base_heatmap_m1_12_n1_12.parquet"


def make_winrate_dummy_group(
    metric: str, m: int, n: int, pairwise: int
) -> tuple[str, ...]:
    """生成旧滚动模型使用的互斥 hit dummy 组。"""
    return tuple(
        f"dummy_{metric}_m{m}_n{n}_hit{hit_k}_pairwise{pairwise}"
        for hit_k in range(1, n + 1)
    )


def make_cumulative_winrate_dummy_group(
    metric: str, m: int, n: int, pairwise: int
) -> tuple[str, ...]:
    """生成新非重叠模型的 Dk=1(hitcount>=k) 累积 dummy 组。

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
    """兼容现有调用：生成 top50 口径的 dummy 组。"""
    return make_winrate_dummy_group("top50", m, n, pairwise)


def make_winrate_factor_groups(
    metric: str,
    specs: tuple[tuple[int, int, int], ...],
) -> list[tuple[str, ...]]:
    """把窗口规格转换成指定命中口径的 dummy tuple 列表。"""
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
        "preprocess_input_path": "A_data/output/panel_base.parquet",
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
    "bm33": {
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
# up/down 仍沿用 m6_n6 排名均值中位数分组，不改变现有分组口径。
CROSS_HORIZON_FACTOR = "rank_vol_across_horizons_1m_3m_6m_12m"
CROSS_HORIZON_RANK_MEAN = "rank_mean_across_horizons_1m_3m_6m_12m"
CROSS_HORIZON_MEDIAN_FLAG = "is_median_rank_mean_m6_n6_pairwise1"
CROSS_HORIZON_MODEL_SOURCES = {
    "fm_baseline_rank_vol_across_horizons": "fm_baseline",
    "fm_baseline_down_rank_vol_across_horizons": "fm_baseline_down",
    "fm_baseline_up_rank_vol_across_horizons": "fm_baseline_up",
    "fm_baseline_interaction_rank_vol_across_horizons": (
        "fm_baseline_interaction"
    ),
    "fm_baseline_interaction_alternative_rank_vol_across_horizons": (
        "fm_baseline_interaction_alternative"
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
    if is_up or is_down:
        # 原模型按每个 FAC 对应的 rank_mean 分组；替代模型只有一个指标，
        # 因此固定用 m6_n6 的排名均值中位数组，2 为上组、-2 为下组。
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
        # 跨期限模型使用原始主效应和原始乘积，避免替代指标的回归口径
        # 随标准 interaction 的中心化设置一起变化。
        config["interaction_centering"] = "none"
        config["portfolio_sorting_factors"] = [interaction]
        config["controls"] = [
            column for column in config["controls"] if column != "CtrlRetLTM"
        ]
        config["winsorize"]["columns"] = [
            column
            for column in config["winsorize"]["columns"]
            if column != "CtrlRetLTM"
        ]

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


HEATMAP_GROUP_MODELS = {
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
    "fm_heatmap_bm33": {
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
    """生成 144 个热力图 FAC_rank_vol 因子。"""
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
    """从 baseline 派生一个热力图分组回归配置。

    每个 factor 都使用同一 (m,n) 下自己的 rank_mean 分组列筛选样本，
    因而不会把 m1_n1 的 Top50 样本误套到 m12_n12 的 FAC 指标上。
    """
    if model_key not in HEATMAP_GROUP_MODELS:
        raise ValueError(f"不支持的热力图模型：{model_key}")

    group_config = HEATMAP_GROUP_MODELS[model_key]
    flag_prefix = str(group_config["flag_prefix"])
    filter_value = int(group_config["filter_value"])
    factors = make_heatmap_factors()
    preprocess_dir = f"B_factors/output/{model_key}"
    regression_dir = f"D_analysis/output/fund_consistency/{model_key}"

    config = deepcopy(REGISTRY["fm_baseline"])
    config.update(
        {
            "description": (
                "Fama-MacBeth 热力图模型"
                f"（{group_config['label']}）：一致性主效应 + baseline 控制变量，"
                f"{group_config['description']}；m=1..12，n=1..12，pairwise=1"
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
            "sample_flag_columns": make_heatmap_sample_flag_columns(flag_prefix),
            "factor_sample_filters": make_heatmap_factor_sample_filters(
                flag_prefix, filter_value
            ),
            "output_dir": regression_dir,
            "factor_group_suffixes": make_heatmap_factor_group_suffixes(),
        }
    )

    # 热力图模型沿用 baseline 的 y 和 controls，但 winsorize 需要覆盖 144 个
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


DEFAULT_REGRESSION_KEY = "fm_baseline"


def list_regression_keys() -> list[str]:
    """列出当前已经登记的回归模型版本。"""

    return sorted(REGISTRY)


def get_regression_config(key: str = DEFAULT_REGRESSION_KEY) -> dict[str, object]:
    """返回指定实验的配置副本，避免调用方误改全局 REGISTRY。"""

    if key not in REGISTRY:
        available = ", ".join(list_regression_keys())
        raise KeyError(f"未知回归版本：{key}；可用版本：{available}")
    return deepcopy(REGISTRY[key])
