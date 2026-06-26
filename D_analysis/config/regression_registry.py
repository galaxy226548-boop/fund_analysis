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
    "fm_baseline_interaction": {
        "description": "Fama-MacBeth 基础模型 + 交互项（Consistency x 对应 rank_mean），不标准化",
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
                    "D_analysis/output/fund_consistency/fm_baseline_interaction/fama_macbeth_results.csv",
                    "D_analysis/output/fund_consistency/fm_baseline_interaction/run_metadata.json",
                ],
            },
            {
                "name": "portfolio_sorting",
                "script": "D_analysis/scripts/portfolio_sorting.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "D_analysis/output/fund_consistency/fm_baseline_interaction/portfolio_sorting/portfolio_sorting_registry.json",
                ],
            },
        ],
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
        "factor_sample_filters": {
        },
        "portfolio_sorting_factors": ["{FAC,RANK_MEAN}"],
        "controls": [
            "CtrlRetSTR",
            "CtrlRetLTM",
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
        "interactions": ["{FAC,RANK_MEAN}"],
        "output_dir": "D_analysis/output/fund_consistency/fm_baseline_interaction",
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
    "fm_winrates_top50": {
        "description": "Fama-MacBeth 带方向一致性模型（排名前50%月份占比）：一致性主效应 + 控制变量",
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
                "script": "A_data/scripts/4_descriptive_dummy_analysis.py",
                "args": ["--model", "{model}"],
                "outputs": [
                    "A_data/output/descriptive_analysis/fm_winrates_top50/fm_winrates_top50_y_future_ret_6m_descriptive.xlsx",
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
        "factors": [
            ("dummy_top50_m3_n6_hit1_pairwise1", "dummy_top50_m3_n6_hit2_pairwise1", "dummy_top50_m3_n6_hit3_pairwise1", "dummy_top50_m3_n6_hit4_pairwise1", "dummy_top50_m3_n6_hit5_pairwise1", "dummy_top50_m3_n6_hit6_pairwise1"),
            ("dummy_top50_m6_n3_hit1_pairwise1", "dummy_top50_m6_n3_hit2_pairwise1", "dummy_top50_m6_n3_hit3_pairwise1"),
            ("dummy_top50_m6_n6_hit1_pairwise1", "dummy_top50_m6_n6_hit2_pairwise1", "dummy_top50_m6_n6_hit3_pairwise1", "dummy_top50_m6_n6_hit4_pairwise1", "dummy_top50_m6_n6_hit5_pairwise1", "dummy_top50_m6_n6_hit6_pairwise1"),
            ("dummy_top50_m6_n12_hit1_pairwise1", "dummy_top50_m6_n12_hit2_pairwise1", "dummy_top50_m6_n12_hit3_pairwise1", "dummy_top50_m6_n12_hit4_pairwise1", "dummy_top50_m6_n12_hit5_pairwise1", "dummy_top50_m6_n12_hit6_pairwise1", "dummy_top50_m6_n12_hit7_pairwise1", "dummy_top50_m6_n12_hit8_pairwise1", "dummy_top50_m6_n12_hit9_pairwise1", "dummy_top50_m6_n12_hit10_pairwise1", "dummy_top50_m6_n12_hit11_pairwise1", "dummy_top50_m6_n12_hit12_pairwise1"),
            ("dummy_top50_m12_n6_hit1_pairwise1", "dummy_top50_m12_n6_hit2_pairwise1", "dummy_top50_m12_n6_hit3_pairwise1", "dummy_top50_m12_n6_hit4_pairwise1", "dummy_top50_m12_n6_hit5_pairwise1", "dummy_top50_m12_n6_hit6_pairwise1")
        ],
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
        "factor_group_suffixes": {
            ("dummy_top50_m3_n6_hit1_pairwise1", "dummy_top50_m3_n6_hit2_pairwise1", "dummy_top50_m3_n6_hit3_pairwise1", "dummy_top50_m3_n6_hit4_pairwise1", "dummy_top50_m3_n6_hit5_pairwise1", "dummy_top50_m3_n6_hit6_pairwise1"): "winrate_m3_n6_pairwise1",
            ("dummy_top50_m6_n3_hit1_pairwise1", "dummy_top50_m6_n3_hit2_pairwise1", "dummy_top50_m6_n3_hit3_pairwise1"): "winrate_m6_n3_pairwise1",
            ("dummy_top50_m6_n6_hit1_pairwise1", "dummy_top50_m6_n6_hit2_pairwise1", "dummy_top50_m6_n6_hit3_pairwise1", "dummy_top50_m6_n6_hit4_pairwise1", "dummy_top50_m6_n6_hit5_pairwise1", "dummy_top50_m6_n6_hit6_pairwise1"): "winrate_m6_n6_pairwise1",
            ("dummy_top50_m6_n12_hit1_pairwise1", "dummy_top50_m6_n12_hit2_pairwise1", "dummy_top50_m6_n12_hit3_pairwise1", "dummy_top50_m6_n12_hit4_pairwise1", "dummy_top50_m6_n12_hit5_pairwise1", "dummy_top50_m6_n12_hit6_pairwise1", "dummy_top50_m6_n12_hit7_pairwise1", "dummy_top50_m6_n12_hit8_pairwise1", "dummy_top50_m6_n12_hit9_pairwise1", "dummy_top50_m6_n12_hit10_pairwise1", "dummy_top50_m6_n12_hit11_pairwise1", "dummy_top50_m6_n12_hit12_pairwise1"): "winrate_m6_n12_pairwise1",
            ("dummy_top50_m12_n6_hit1_pairwise1", "dummy_top50_m12_n6_hit2_pairwise1", "dummy_top50_m12_n6_hit3_pairwise1", "dummy_top50_m12_n6_hit4_pairwise1", "dummy_top50_m12_n6_hit5_pairwise1", "dummy_top50_m12_n6_hit6_pairwise1"): "winrate_m12_n6_pairwise1"
        },
    },
}

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
