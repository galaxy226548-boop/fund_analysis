# B_factors 分步脚本临时运行说明

当前阶段先手工串联 6 个 CLI，不做配置驱动总 runner。

```bash
mkdir -p B_factors/output/debug_steps

.venv/bin/python B_factors/scripts/steps/01_select_columns.py \
  --input B_factors/input/panel_base.parquet \
  --output B_factors/output/debug_steps/01_selected_columns.parquet

.venv/bin/python B_factors/scripts/steps/02_sample_filter.py \
  --input B_factors/output/debug_steps/01_selected_columns.parquet \
  --output B_factors/output/debug_steps/02_sample_filtered.parquet

.venv/bin/python B_factors/scripts/steps/03_coerce_numeric.py \
  --input B_factors/output/debug_steps/02_sample_filtered.parquet \
  --output B_factors/output/debug_steps/03_numeric_coerced.parquet

.venv/bin/python B_factors/scripts/steps/04_winsorize.py \
  --input B_factors/output/debug_steps/03_numeric_coerced.parquet \
  --output B_factors/output/debug_steps/04_winsorized.parquet

.venv/bin/python B_factors/scripts/steps/05_quantile_group.py \
  --input B_factors/output/debug_steps/04_winsorized.parquet \
  --output B_factors/output/debug_steps/05_grouped.parquet

.venv/bin/python B_factors/scripts/steps/06_export_summary_preview.py \
  --input B_factors/output/debug_steps/05_grouped.parquet \
  --output B_factors/output/debug_steps/panel_base.parquet \
  --preview B_factors/output/debug_steps/panel_base_preview.xlsx \
  --summary B_factors/output/debug_steps/panel_base_summary.json
```
