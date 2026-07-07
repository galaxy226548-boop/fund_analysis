# fm_comparison 指标可行性比较页面 实作计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `I_Visualization/fm_comparison/` 下实现一个 Streamlit 页面：解析回归系数显著性总表，按四维规则给每个 (模型目录 × m,n) 候选打分，以"擂台式"左右对照比较新指标族与现役基准，并导出可行性排名 xlsx。

**Architecture:** 四个模块——`config.py`（集中配置）、`data_loader.py`（xlsx → 整洁表）、`scoring.py`（纯函数打分引擎）、`export.py`（导出）——加一个 `app.py`（三 Tab UI）。打分引擎与 UI 完全解耦，全部通过 cfg 字典取参数，便于单元测试与侧栏实时调参。

**Tech Stack:** Python（项目 `.venv`）、pandas 3.0.3、openpyxl 3.1.5、Streamlit 1.58、pytest 9.1.1（unittest 风格测试类）。

**Spec:** `docs/superpowers/specs/2026-07-07-fm-comparison-design.md`（所有阈值、公式以 spec 第 4 节为准，本计划已逐条落实）。

## Global Constraints

- Python 注释一律**简体中文**：每个函数有 docstring，函数内每个逻辑步骤有行级注释（用户拿注释当学习材料）。
- **绝对不用中文引号（弯引号）**，全部英文直引号——中文引号导致 SyntaxError 且肉眼难辨。
- 路径、权重、阈值全部放 `config.py`，不许硬编码在逻辑代码里。
- 测试用 unittest 风格（`unittest.TestCase`），与 `tests/` 现有文件一致；测试通过 `sys.path.insert` 指向 `I_Visualization/fm_comparison/` 后按普通模块导入。
- 所有命令用项目虚拟环境：`.venv/bin/python`、`.venv/bin/streamlit`。
- `I_Visualization/fm_comparison/output/` 下的导出结果**不提交 git**。
- 核心变量判断用前缀 `FAC`（当前唯一核心变量为 `FAC_rank_vol`）。
- 邻格显著性 p<0.1 用 |t| >= 1.645 近似（FM 系数表只有 t 值，无 p 值）。

---

### Task 1: 脚手架与 config.py

**Files:**
- Create: `I_Visualization/fm_comparison/config.py`
- Create: `I_Visualization/fm_comparison/output/.gitkeep`（空文件占位）
- Modify: `.gitignore`（追加导出结果忽略规则）
- Test: `tests/test_fm_comparison_scoring.py`（先只放 config 完整性测试）

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: `config.SUMMARY_XLSX: Path`、`config.OUTPUT_DIR: Path`、`config.CORE_VARIABLE_PREFIX: str = "FAC"`、`config.DEFAULT_CONFIG: dict`（键见下方代码，后续所有打分函数只认这些键名）、`config.BASELINES: dict[str, dict]`（键 `"bottom33"`/`"up"`，值含 `"model"`、`"param_key"`）。

- [ ] **Step 1: 写失败测试**

```python
"""fm_comparison 打分引擎与配置的单元测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 把 fm_comparison 目录加入搜索路径，按普通模块导入（目录名带大写前缀，不适合做包名）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = PROJECT_ROOT / "I_Visualization" / "fm_comparison"
sys.path.insert(0, str(PKG_DIR))

import config  # noqa: E402


class TestConfig(unittest.TestCase):
    """校验配置文件的键完整性，防止后续函数取不到参数。"""

    def test_default_config_keys(self):
        # 打分引擎依赖的全部键必须存在
        required = {
            "fm_full", "fm_t_bands",
            "neighbor_full", "neighbor_t_min",
            "ps_full", "ps_p_bands", "ps_direction_conflict_mult",
            "ps_econ_threshold", "ps_econ_mult",
            "r2_individual_full", "r2_family_full",
            "months_penalties", "obs_penalties",
            "corr_pair_penalty", "corr_pair_core_penalty", "corr_cap",
            "vif_penalty", "vif_core_penalty", "vif_cap",
            "replace_margin", "tie_band",
        }
        self.assertTrue(required.issubset(config.DEFAULT_CONFIG.keys()))

    def test_baselines(self):
        # 两条基准：bottom33 与 up（top50 对应 fm_baseline_up）
        self.assertEqual(config.BASELINES["bottom33"]["model"], "fm_baseline_bottom33")
        self.assertEqual(config.BASELINES["bottom33"]["param_key"], "m3_n6")
        self.assertEqual(config.BASELINES["up"]["model"], "fm_baseline_up")
        self.assertEqual(config.BASELINES["up"]["param_key"], "m6_n12")

    def test_paths(self):
        # 总表路径应指向 D_analysis 下的固定位置
        self.assertTrue(str(config.SUMMARY_XLSX).endswith("回归系数显著性_总表.xlsx"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'config'`）

- [ ] **Step 3: 写 config.py**

```python
"""fm_comparison 页面的集中配置：路径、打分权重、基准与配对规则。

所有可调参数集中在此，页面侧栏基于 DEFAULT_CONFIG 生成副本后覆盖，
打分引擎（scoring.py）只通过 cfg 字典读取，不直接 import 本模块的具体数值。
"""

from pathlib import Path

# ---- 路径 ----
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUMMARY_XLSX = (
    PROJECT_ROOT
    / "D_analysis" / "output" / "fama_macbeth_results_reading"
    / "回归系数显著性" / "回归系数显著性_总表.xlsx"
)
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# ---- 核心变量前缀：共线性风险对/VIF 变量是否"含核心变量"按此前缀判断 ----
CORE_VARIABLE_PREFIX = "FAC"

# ---- 默认打分配置（spec 第 4 节；侧栏可实时覆盖）----
DEFAULT_CONFIG = {
    # FM 显著性：|t| 分档 (阈值, 满分占比)，从高到低匹配，乘 fm_full
    "fm_full": 40.0,
    "fm_t_bands": [(2.58, 1.0), (1.96, 0.8), (1.65, 0.6)],
    # 邻格稳健性：邻格中"同号且 |t|>=neighbor_t_min"的比例 × neighbor_full
    "neighbor_full": 10.0,
    "neighbor_t_min": 1.645,  # p<0.1 的 |t| 近似阈值（FM 表只有 t 值）
    # 多空显著性：p 分档 (阈值, 满分占比)，乘 ps_full，再乘折扣系数
    "ps_full": 30.0,
    "ps_p_bands": [(0.01, 1.0), (0.05, 0.8), (0.10, 0.6), (0.15, 1 / 3)],
    "ps_direction_conflict_mult": 0.5,  # FM 系数方向与多空收益方向冲突
    "ps_econ_threshold": 0.003,         # 月均多空 |收益| < 0.3%/月 触发经济显著性折扣
    "ps_econ_mult": 0.8,
    # 回归质量：个体 R² 分位数 × 12 + 族平均 R² 分位数 × 8
    "r2_individual_full": 12.0,
    "r2_family_full": 8.0,
    # 样本量扣分：(阈值, 扣分) 升序排列，命中最严档，不叠加
    "months_penalties": [(48, -10.0), (60, -5.0)],
    "obs_penalties": [(3000, -8.0), (6000, -3.0)],
    # 共线性扣分：每组唯一风险对基础扣分 × 持续性系数，族内合计有上限
    "corr_pair_penalty": -2.0,
    "corr_pair_core_penalty": -5.0,  # 风险对含核心 FAC 变量时的加重档
    "corr_cap": -8.0,
    "vif_penalty": -4.0,
    "vif_core_penalty": -8.0,        # 核心 FAC 变量自身 VIF 超标时的加重档
    "vif_cap": -12.0,
    # 擂台判定
    "replace_margin": 10.0,  # 领先基准 >= 此分差 → "优先关注"
    "tie_band": 5.0,         # 与守擂现役格分差绝对值 <= 此值 → 色点标"平"
}

# ---- 基准（守擂者）：按样本层配对；top50 对应模型目录 fm_baseline_up ----
BASELINES = {
    "bottom33": {"model": "fm_baseline_bottom33", "param_key": "m3_n6"},
    "up": {"model": "fm_baseline_up", "param_key": "m6_n12"},
}
```

同时创建空文件 `I_Visualization/fm_comparison/output/.gitkeep`，并在 `.gitignore` 末尾追加：

```
# fm_comparison 导出结果不提交
I_Visualization/fm_comparison/output/*
!I_Visualization/fm_comparison/output/.gitkeep
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: PASS（3 个测试）

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/config.py I_Visualization/fm_comparison/output/.gitkeep .gitignore tests/test_fm_comparison_scoring.py
git commit -m "feat(fm_comparison): 脚手架与打分配置 config.py"
```

---

### Task 2: data_loader 基础解析函数

**Files:**
- Create: `I_Visualization/fm_comparison/data_loader.py`
- Test: `tests/test_fm_comparison_data_loader.py`

**Interfaces:**
- Consumes: `config.CORE_VARIABLE_PREFIX`。
- Produces（后续任务与测试按这些签名调用）:
  - `split_header_blocks(raw: pd.DataFrame, marker: str = "来源批次") -> list[pd.DataFrame]`
  - `parse_coef_cell(cell) -> tuple[float, float, int] | None`（返回 coef、t、星数）
  - `parse_param(text: str) -> tuple[int, int, str] | None`（返回 m、n、param_key 如 `"m3_n6"`）
  - `batch_run_no(batch: str) -> int`（批次尾号，无法解析返回 -1）
  - `keep_latest_batch(df: pd.DataFrame) -> pd.DataFrame`（要求含 `batch`、`model` 列）

- [ ] **Step 1: 写失败测试**

```python
"""data_loader 的单元测试：块切分、单元格解析、批次去重。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = PROJECT_ROOT / "I_Visualization" / "fm_comparison"
sys.path.insert(0, str(PKG_DIR))

import data_loader  # noqa: E402


class TestBasicParsers(unittest.TestCase):
    """基础解析函数：不接触真实 Excel，全部用合成数据。"""

    def test_split_header_blocks(self):
        # 模拟一个 sheet 里两个批次块、表头行重复出现的结构
        raw = pd.DataFrame([
            ["来源批次", "模型目录", "月份数"],
            ["b_001", "m_a", 60],
            ["b_001", "m_b", 55],
            ["来源批次", "模型目录", "月份数"],
            ["b_002", "m_c", 48],
        ])
        blocks = data_loader.split_header_blocks(raw)
        self.assertEqual(len(blocks), 2)
        self.assertEqual(list(blocks[0].columns), ["来源批次", "模型目录", "月份数"])
        self.assertEqual(len(blocks[0]), 2)
        self.assertEqual(blocks[1].iloc[0]["模型目录"], "m_c")

    def test_parse_coef_cell(self):
        # 标准格式：系数 + 星号 + 换行 + t 值
        self.assertEqual(data_loader.parse_coef_cell("-0.07*\n(t=-1.73)"), (-0.07, -1.73, 1))
        self.assertEqual(data_loader.parse_coef_cell("0.08***\n(t=2.74)"), (0.08, 2.74, 3))
        self.assertEqual(data_loader.parse_coef_cell("0.04\n(t=1.31)"), (0.04, 1.31, 0))
        # 异常输入返回 None
        self.assertIsNone(data_loader.parse_coef_cell(float("nan")))
        self.assertIsNone(data_loader.parse_coef_cell(None))
        self.assertIsNone(data_loader.parse_coef_cell("不适用"))

    def test_parse_param(self):
        self.assertEqual(data_loader.parse_param("m3_n6_pairwise1"), (3, 6, "m3_n6"))
        self.assertEqual(data_loader.parse_param("m12_n6_pairwise1"), (12, 6, "m12_n6"))
        self.assertIsNone(data_loader.parse_param("模型参数"))

    def test_batch_run_no(self):
        self.assertEqual(data_loader.batch_run_no("6_市态条件一致性_回归系数显著性_004"), 4)
        self.assertEqual(data_loader.batch_run_no("无尾号批次"), -1)

    def test_keep_latest_batch(self):
        # 同一模型出现在 001 与 004 两个批次时，只保留 004 的行
        df = pd.DataFrame({
            "batch": ["x_001", "x_001", "x_004", "y_002"],
            "model": ["m_a", "m_b", "m_a", "m_c"],
            "val": [1, 2, 3, 4],
        })
        kept = data_loader.keep_latest_batch(df)
        self.assertEqual(kept[kept["model"] == "m_a"]["val"].tolist(), [3])
        # 其余模型不受影响
        self.assertEqual(sorted(kept["model"].tolist()), ["m_a", "m_b", "m_c"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_data_loader.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'data_loader'`）

- [ ] **Step 3: 写实现**

```python
"""解析 回归系数显著性_总表.xlsx 的五个 sheet 为整洁 DataFrame。

总表的共同格式：同一 sheet 内多个批次块首尾相接，表头行（首列为"来源批次"）
重复出现。本模块先按表头行切块，再逐 sheet 解析成 tidy 结构。
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

import config

# 表头行的识别标记：首列单元格文本
HEADER_MARKER = "来源批次"

# FM 系数单元格格式，如 "-0.07*\n(t=-1.73)"；\s 可匹配中间的换行
_COEF_CELL_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)\s*(\*{0,3})\s*\(t=(-?\d+(?:\.\d+)?)\)\s*$"
)
# 模型参数格式，如 "m3_n6_pairwise1"
_PARAM_RE = re.compile(r"m(\d+)_n(\d+)")


def split_header_blocks(raw: pd.DataFrame, marker: str = HEADER_MARKER) -> list[pd.DataFrame]:
    """按重复出现的表头行把 sheet 切成多个块，并把表头提升为列名。"""
    # 找到所有表头行的位置（首列文本等于标记）
    header_idx = [i for i in range(len(raw)) if str(raw.iloc[i, 0]).strip() == marker]
    blocks: list[pd.DataFrame] = []
    for k, start in enumerate(header_idx):
        # 每个块的范围：当前表头行之后，到下一个表头行（或表尾）为止
        end = header_idx[k + 1] if k + 1 < len(header_idx) else len(raw)
        header = raw.iloc[start]
        body = raw.iloc[start + 1 : end].copy()
        # 表头单元格可能是 NaN（如 FM 系数表的空列），统一转成字符串列名
        body.columns = ["" if pd.isna(c) else str(c).strip() for c in header]
        # 丢掉首列为空的行（块间空行）
        body = body[body.iloc[:, 0].notna()].reset_index(drop=True)
        blocks.append(body)
    return blocks


def parse_coef_cell(cell) -> tuple[float, float, int] | None:
    """把 "-0.07*\\n(t=-1.73)" 解析成 (coef, t, 星数)；解析失败返回 None。"""
    # 非字符串（NaN/None/数值）一律视为缺失
    if not isinstance(cell, str):
        if cell is None or (isinstance(cell, float) and math.isnan(cell)):
            return None
        cell = str(cell)
    match = _COEF_CELL_RE.match(cell)
    if match is None:
        return None
    coef, stars, t_stat = match.groups()
    return float(coef), float(t_stat), len(stars)


def parse_param(text: str) -> tuple[int, int, str] | None:
    """把 "m3_n6_pairwise1" 解析成 (3, 6, "m3_n6")；解析失败返回 None。"""
    if not isinstance(text, str):
        return None
    match = _PARAM_RE.search(text)
    if match is None:
        return None
    m_val, n_val = int(match.group(1)), int(match.group(2))
    return m_val, n_val, f"m{m_val}_n{n_val}"


def batch_run_no(batch: str) -> int:
    """取批次名的尾号（如 ..._004 -> 4），无法解析返回 -1。"""
    if not isinstance(batch, str):
        return -1
    tail = batch.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def keep_latest_batch(df: pd.DataFrame) -> pd.DataFrame:
    """同一模型目录跨批次重复出现时，只保留批次尾号最大（最新）的那一批。"""
    if df.empty:
        return df
    # 按 (尾号, 批次名) 排序后取每个模型的最后一个批次名作为"最新批次"
    tmp = df.assign(_run=df["batch"].map(batch_run_no))
    latest = (
        tmp.sort_values(["_run", "batch"])
        .groupby("model")["batch"]
        .last()
    )
    # 只保留每个模型属于其最新批次的行
    mask = df.apply(lambda row: row["batch"] == latest[row["model"]], axis=1)
    return df[mask].drop(columns=[c for c in ["_run"] if c in df.columns]).reset_index(drop=True)
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_data_loader.py -v`
Expected: PASS（5 个测试）

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/data_loader.py tests/test_fm_comparison_data_loader.py
git commit -m "feat(fm_comparison): data_loader 基础解析（块切分/系数单元格/参数/批次去重）"
```

---

### Task 3: data_loader 四张表加载与 load_all

**Files:**
- Modify: `I_Visualization/fm_comparison/data_loader.py`（追加函数）
- Test: `tests/test_fm_comparison_data_loader.py`（追加测试类）

**Interfaces:**
- Consumes: Task 2 的全部函数；`config.SUMMARY_XLSX`、`config.CORE_VARIABLE_PREFIX`。
- Produces（scoring 与 app 依赖的四张 tidy 表结构）:
  - `load_coverage(xlsx: Path) -> pd.DataFrame`：列 `batch, model, param, param_key, m, n, n_months, avg_funds, n_obs, avg_r2, avg_adj_r2`
  - `load_fm_coef(xlsx: Path) -> pd.DataFrame`：列 `batch, model, variable, param, param_key, m, n, coef, t_stat, stars`
  - `load_ps(xlsx: Path) -> pd.DataFrame`：列 `batch, model, variable, param, param_key, m, n, long_short, t_stat, p_value`
  - `load_corr_diag(xlsx: Path) -> pd.DataFrame`：列 `batch, model, kind`（`"corr"`/`"vif"`）`, var_1, var_2, n_flagged, involves_core`
  - `load_all(xlsx: Path) -> dict[str, pd.DataFrame]`：键 `"coverage"/"fm"/"ps"/"diag"`，各表已做最新批次去重
  - 块内解析辅助（测试直接调用）：`parse_corr_cell(text) -> list[tuple[str, str]]`、`parse_vif_cell(text) -> list[str]`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_fm_comparison_data_loader.py` 末尾（`if __name__` 之前）追加：

```python
class TestSheetLoaders(unittest.TestCase):
    """sheet 级加载：合成 DataFrame 走块解析路径 + 真实总表集成测试。"""

    def test_parse_corr_cell(self):
        # 诊断单元格里内嵌 markdown 表格，同一对可重复出现（多个 m,n 组合各标记一次）
        text = (
            "按 `abs(mean_corr) >= 0.50` 口径，本次发现 3 组相关性风险变量对：\n"
            "| variable_1 | variable_2 | mean_corr | abs_mean_corr | stars | n_months | risk_level |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| Ctrl_fund_age | as_基金A | 0.501 | 0.501 | *** | 63 | 重点关注 |\n"
            "| Ctrl_fund_age | as_基金A | 0.558 | 0.558 | *** | 56 | 重点关注 |\n"
            "| FAC_rank_vol | Ctrl_size | 0.60 | 0.60 | *** | 56 | 重点关注 |"
        )
        pairs = data_loader.parse_corr_cell(text)
        # 返回原始行（含重复），由上层聚合成唯一对 + 标记次数
        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[0], ("Ctrl_fund_age", "as_基金A"))
        self.assertEqual(pairs[2], ("FAC_rank_vol", "Ctrl_size"))
        # "未发现"文本返回空列表
        self.assertEqual(data_loader.parse_corr_cell("按口径，本次未发现相关性风险变量对。"), [])
        self.assertEqual(data_loader.parse_corr_cell(float("nan")), [])

    def test_corr_diag_aggregation(self):
        # 用合成 raw sheet 验证：去重 + 标记次数 + 核心变量识别
        raw = pd.DataFrame([
            ["来源批次", "模型目录", "报告路径", "相关性风险变量对", "VIF风险变量", "风险解读"],
            [
                "b_001", "m_a", "/tmp/r.md",
                "发现 2 组：\n| variable_1 | variable_2 | x |\n| --- | --- | --- |\n"
                "| Ctrl_a | as_b | 0.5 |\n| Ctrl_a | as_b | 0.6 |",
                "按口径，本次未发现稳定偏高的 VIF 风险变量。",
                "解读",
            ],
        ])
        diag = data_loader._corr_diag_from_blocks(data_loader.split_header_blocks(raw))
        self.assertEqual(len(diag), 1)
        row = diag.iloc[0]
        self.assertEqual(row["kind"], "corr")
        self.assertEqual((row["var_1"], row["var_2"]), ("Ctrl_a", "as_b"))
        self.assertEqual(row["n_flagged"], 2)   # 同一对标记两次 -> 去重后 n_flagged=2
        self.assertFalse(row["involves_core"])  # 不含 FAC 前缀变量

    def test_load_all_real_file(self):
        # 真实总表存在时做集成校验（不存在则跳过，保证 CI 环境可运行）
        if not data_loader.config.SUMMARY_XLSX.exists():
            self.skipTest("真实总表不存在，跳过集成测试")
        tables = data_loader.load_all(data_loader.config.SUMMARY_XLSX)
        self.assertEqual(set(tables.keys()), {"coverage", "fm", "ps", "diag"})
        cov, fm = tables["coverage"], tables["fm"]
        # 基准模型与现役参数组合必须在表里
        self.assertIn("fm_baseline_bottom33", set(cov["model"]))
        self.assertIn("m3_n6", set(cov[cov["model"] == "fm_baseline_bottom33"]["param_key"]))
        self.assertIn("fm_baseline_up", set(cov["model"]))
        # FM 系数已解析为数值
        self.assertTrue(fm["t_stat"].notna().all())
        self.assertTrue(fm["coef"].dtype.kind == "f")
        # 覆盖表数值列可用
        self.assertTrue((cov["n_months"] > 0).all())
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_data_loader.py -v`
Expected: 新增测试 FAIL（`AttributeError: module 'data_loader' has no attribute 'parse_corr_cell'`），Task 2 的测试仍 PASS

- [ ] **Step 3: 写实现**

在 `data_loader.py` 末尾追加：

```python
# 覆盖表列名 -> 英文标准名（列名与总表完全一致，注意"平均 R²"中间有空格）
_COVERAGE_RENAME = {
    "来源批次": "batch",
    "模型目录": "model",
    "模型参数": "param",
    "月份数": "n_months",
    "月均基金数": "avg_funds",
    "月份数×月均基金数": "n_obs",
    "平均 R²": "avg_r2",
    "平均调整 R²": "avg_adj_r2",
}

_PS_RENAME = {
    "来源批次": "batch",
    "模型目录": "model",
    "解释变量": "variable",
    "模型参数": "param",
    "long-short": "long_short",
    "t-stat": "t_stat",
    "p-value": "p_value",
}


def _add_param_cols(df: pd.DataFrame) -> pd.DataFrame:
    """按 param 列补 m、n、param_key 三列，无法解析的行丢弃。"""
    parsed = df["param"].map(parse_param)
    df = df[parsed.notna()].copy()
    parsed = parsed[parsed.notna()]
    df["m"] = [p[0] for p in parsed]
    df["n"] = [p[1] for p in parsed]
    df["param_key"] = [p[2] for p in parsed]
    return df


def load_coverage(xlsx: Path) -> pd.DataFrame:
    """加载"模型比较样本覆盖"sheet：每行一个 (模型目录, m,n) 的覆盖与 R² 指标。"""
    raw = pd.read_excel(xlsx, sheet_name="模型比较样本覆盖", header=None)
    blocks = split_header_blocks(raw)
    df = pd.concat(blocks, ignore_index=True)
    # 只保留识别的列并改英文名，便于下游统一引用
    df = df[[c for c in _COVERAGE_RENAME if c in df.columns]].rename(columns=_COVERAGE_RENAME)
    df = _add_param_cols(df)
    # 数值列统一转型，脏值转 NaN
    for col in ["n_months", "avg_funds", "n_obs", "avg_r2", "avg_adj_r2"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def load_fm_coef(xlsx: Path) -> pd.DataFrame:
    """加载"FM系数整理"sheet：宽表（每列一个模型）转长表，并解析系数单元格。"""
    raw = pd.read_excel(xlsx, sheet_name="FM系数整理", header=None)
    records: list[dict] = []
    for block in split_header_blocks(raw):
        # 模型列的表头格式为 "fm_baseline_top33\n变量：FAC_rank_vol"
        model_cols = [c for c in block.columns if "\n变量：" in str(c)]
        for _, row in block.iterrows():
            for col in model_cols:
                parsed = parse_coef_cell(row[col])
                if parsed is None:
                    continue  # 空格/NaN：该模型在此参数组合下无结果
                model, variable = str(col).split("\n变量：", 1)
                coef, t_stat, stars = parsed
                records.append({
                    "batch": row["来源批次"],
                    "model": model.strip(),
                    "variable": variable.strip(),
                    "param": row["模型参数"],
                    "coef": coef,
                    "t_stat": t_stat,
                    "stars": stars,
                })
    df = pd.DataFrame(records)
    return _add_param_cols(df).reset_index(drop=True)


def load_ps(xlsx: Path) -> pd.DataFrame:
    """加载"PS_long_short_pvalue"sheet：多空收益、t 与 p 值。"""
    raw = pd.read_excel(xlsx, sheet_name="PS_long_short_pvalue", header=None)
    blocks = split_header_blocks(raw)
    df = pd.concat(blocks, ignore_index=True)
    df = df[[c for c in _PS_RENAME if c in df.columns]].rename(columns=_PS_RENAME)
    df = _add_param_cols(df)
    for col in ["long_short", "t_stat", "p_value"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.reset_index(drop=True)


def _md_table_rows(text) -> list[list[str]]:
    """从单元格内嵌的 markdown 表格提取数据行（跳过表头与分隔行）。"""
    if not isinstance(text, str) or "未发现" in text:
        return []
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # 跳过表头行（含 variable 字样）与分隔行（全为 --- ）
        if not cells or cells[0].startswith("variable") or set(cells[0]) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def parse_corr_cell(text) -> list[tuple[str, str]]:
    """解析相关性风险单元格，返回原始 (var_1, var_2) 行列表（含重复标记）。"""
    return [(r[0], r[1]) for r in _md_table_rows(text) if len(r) >= 2]


def parse_vif_cell(text) -> list[str]:
    """解析 VIF 风险单元格，返回风险变量名列表（含重复标记）。"""
    return [r[0] for r in _md_table_rows(text)]


def _corr_diag_from_blocks(blocks: list[pd.DataFrame]) -> pd.DataFrame:
    """把诊断 sheet 的块聚合成整洁表：按变量对去重，统计标记次数与核心变量涉险。"""
    records: list[dict] = []
    core = config.CORE_VARIABLE_PREFIX
    for block in blocks:
        for _, row in block.iterrows():
            batch, model = row["来源批次"], row["模型目录"]
            # 相关性风险：按 (var_1, var_2) 排序后去重，重复次数即持续性的分子
            pair_counts: dict[tuple[str, str], int] = {}
            for pair in parse_corr_cell(row.get("相关性风险变量对")):
                key = tuple(sorted(pair))
                pair_counts[key] = pair_counts.get(key, 0) + 1
            for (v1, v2), cnt in pair_counts.items():
                records.append({
                    "batch": batch, "model": model, "kind": "corr",
                    "var_1": v1, "var_2": v2, "n_flagged": cnt,
                    "involves_core": v1.startswith(core) or v2.startswith(core),
                })
            # VIF 风险：按变量名去重
            vif_counts: dict[str, int] = {}
            for var in parse_vif_cell(row.get("VIF风险变量")):
                vif_counts[var] = vif_counts.get(var, 0) + 1
            for var, cnt in vif_counts.items():
                records.append({
                    "batch": batch, "model": model, "kind": "vif",
                    "var_1": var, "var_2": None, "n_flagged": cnt,
                    "involves_core": var.startswith(core),
                })
    columns = ["batch", "model", "kind", "var_1", "var_2", "n_flagged", "involves_core"]
    return pd.DataFrame(records, columns=columns)


def load_corr_diag(xlsx: Path) -> pd.DataFrame:
    """加载"变量相关性诊断"sheet 为整洁风险表。"""
    raw = pd.read_excel(xlsx, sheet_name="变量相关性诊断", header=None)
    return _corr_diag_from_blocks(split_header_blocks(raw))


def load_all(xlsx: Path) -> dict[str, pd.DataFrame]:
    """一次加载四张表并做最新批次去重，返回 {"coverage","fm","ps","diag"}。"""
    return {
        "coverage": keep_latest_batch(load_coverage(xlsx)),
        "fm": keep_latest_batch(load_fm_coef(xlsx)),
        "ps": keep_latest_batch(load_ps(xlsx)),
        "diag": keep_latest_batch(load_corr_diag(xlsx)),
    }
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_data_loader.py -v`
Expected: PASS（8 个测试；真实总表存在时集成测试也应通过）

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/data_loader.py tests/test_fm_comparison_data_loader.py
git commit -m "feat(fm_comparison): 四张 tidy 表加载与共线性诊断解析"
```

---

### Task 4: scoring 基础——样本层、邻格、FM 显著性、样本量扣分

**Files:**
- Create: `I_Visualization/fm_comparison/scoring.py`
- Test: `tests/test_fm_comparison_scoring.py`（追加测试类）

**Interfaces:**
- Consumes: `config.DEFAULT_CONFIG`（测试直接用它做 cfg）。
- Produces:
  - `sample_layer(model: str) -> str`（`"up"` / `"bottom33"` / `"other"`）
  - `build_axes(pairs: Iterable[tuple[int, int]]) -> tuple[list[int], list[int]]`（排序去重的 m 轴、n 轴）
  - `neighbor_cells(m: int, n: int, m_axis: list[int], n_axis: list[int]) -> list[tuple[int, int]]`
  - `fm_significance_score(t_stat: float | None, cfg: dict) -> tuple[float, dict]`
  - `sample_penalty(n_months: float, n_obs: float, cfg: dict) -> tuple[float, dict]`
  - 明细字典统一结构：`{"名称": str, "公式": str, "代入": str, "得分": float}`（页面"分数计算明细"直接渲染此结构，后续所有打分函数遵守）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_fm_comparison_scoring.py` 末尾（`if __name__` 之前）追加：

```python
import scoring  # noqa: E402


class TestScoringBasics(unittest.TestCase):
    """样本层识别、邻格构造、FM 分档、样本量扣分。"""

    def setUp(self):
        self.cfg = dict(config.DEFAULT_CONFIG)

    def test_sample_layer(self):
        # 按下划线分词识别：含 up -> up；含 bottom33 -> bottom33；其余 other
        self.assertEqual(scoring.sample_layer("fm_baseline_up"), "up")
        self.assertEqual(scoring.sample_layer("fm_baseline_hs300_up"), "up")
        self.assertEqual(scoring.sample_layer("fm_baseline_up_indvol"), "up")
        self.assertEqual(scoring.sample_layer("fm_baseline_indvol_bottom33"), "bottom33")
        self.assertEqual(scoring.sample_layer("fm_baseline_bottom33"), "bottom33")
        self.assertEqual(scoring.sample_layer("fm_baseline_down_hs300"), "other")
        self.assertEqual(scoring.sample_layer("fm_baseline_mid33"), "other")

    def test_neighbor_cells(self):
        # 轴 m/n 均为 {3,6,12}：邻格 = 恰好沿一条轴走一步（曼哈顿距离 1）
        m_axis, n_axis = [3, 6, 12], [3, 6, 12]
        # m3_n3 与 m3_n6 是邻格；对角 m6_n6 不是
        self.assertIn((3, 6), scoring.neighbor_cells(3, 3, m_axis, n_axis))
        self.assertNotIn((6, 6), scoring.neighbor_cells(3, 3, m_axis, n_axis))
        # 角点 m3_n3 只有 2 个邻格
        self.assertEqual(len(scoring.neighbor_cells(3, 3, m_axis, n_axis)), 2)
        # 中心点 m6_n6 有 4 个邻格
        self.assertEqual(
            sorted(scoring.neighbor_cells(6, 6, m_axis, n_axis)),
            [(3, 6), (6, 3), (6, 12), (12, 6)],
        )
        # 轴随新参数扩展：m 轴加入 24 后 m12 多一个右邻
        self.assertIn((24, 6), scoring.neighbor_cells(12, 6, [3, 6, 12, 24], n_axis))

    def test_build_axes(self):
        m_axis, n_axis = scoring.build_axes([(6, 12), (3, 6), (6, 3), (6, 6)])
        self.assertEqual(m_axis, [3, 6])
        self.assertEqual(n_axis, [3, 6, 12])

    def test_fm_significance_bands(self):
        # 分档边界：>=2.58 满分 40；>=1.96 得 32；恰好 1.96 命中 32 档
        self.assertEqual(scoring.fm_significance_score(-3.60, self.cfg)[0], 40.0)
        self.assertEqual(scoring.fm_significance_score(1.96, self.cfg)[0], 32.0)
        self.assertEqual(scoring.fm_significance_score(-1.73, self.cfg)[0], 24.0)
        self.assertEqual(scoring.fm_significance_score(1.31, self.cfg)[0], 0.0)
        # 缺失 t 值得 0 分，明细里说明原因
        score, detail = scoring.fm_significance_score(None, self.cfg)
        self.assertEqual(score, 0.0)
        self.assertIn("名称", detail)

    def test_sample_penalty_tiers(self):
        # 月份数：<48 -> -10；<60 -> -5；>=60 不扣。样本数：<3000 -> -8；<6000 -> -3
        self.assertEqual(scoring.sample_penalty(47, 7000, self.cfg)[0], -10.0)
        self.assertEqual(scoring.sample_penalty(48, 7000, self.cfg)[0], -5.0)   # 恰好 48 落 <60 档
        self.assertEqual(scoring.sample_penalty(60, 7000, self.cfg)[0], 0.0)    # 恰好 60 不扣
        self.assertEqual(scoring.sample_penalty(67, 4832, self.cfg)[0], -3.0)   # top33 m6_n12 场景
        self.assertEqual(scoring.sample_penalty(67, 2999, self.cfg)[0], -8.0)
        self.assertEqual(scoring.sample_penalty(56, 4832, self.cfg)[0], -8.0)   # 两类扣分叠加 -5 + -3
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: 新增测试 FAIL（`ModuleNotFoundError: No module named 'scoring'`），Task 1 的测试仍 PASS

- [ ] **Step 3: 写实现**

```python
"""打分引擎：四维打分 + 扣分项 + 擂台徽章。

全部为纯函数：输入 tidy DataFrame / 标量与 cfg 字典，输出 (得分, 明细字典)。
明细字典统一结构 {"名称", "公式", "代入", "得分"}，页面的"分数计算明细"直接渲染，
让每个分数都能被人工复算。
"""

from __future__ import annotations

import math
from typing import Iterable

import pandas as pd


def _is_missing(value) -> bool:
    """判断标量缺失（None 或 NaN）。"""
    return value is None or (isinstance(value, float) and math.isnan(value))


def sample_layer(model: str) -> str:
    """按模型目录名的下划线分词识别样本层：up / bottom33 / other。"""
    tokens = str(model).split("_")
    if "bottom33" in tokens:
        return "bottom33"
    if "up" in tokens:
        return "up"
    return "other"


def build_axes(pairs: Iterable[tuple[int, int]]) -> tuple[list[int], list[int]]:
    """从 (m, n) 集合构造排序去重的 m 轴与 n 轴。"""
    pairs = list(pairs)
    return sorted({p[0] for p in pairs}), sorted({p[1] for p in pairs})


def neighbor_cells(m: int, n: int, m_axis: list[int], n_axis: list[int]) -> list[tuple[int, int]]:
    """邻格 = 参数网格上恰好沿一条轴走一步的组合（曼哈顿距离 1，对角不算）。"""
    neighbors: list[tuple[int, int]] = []
    mi, ni = m_axis.index(m), n_axis.index(n)
    # 沿 m 轴走一步（n 不动）
    for step in (-1, 1):
        if 0 <= mi + step < len(m_axis):
            neighbors.append((m_axis[mi + step], n))
    # 沿 n 轴走一步（m 不动）
    for step in (-1, 1):
        if 0 <= ni + step < len(n_axis):
            neighbors.append((m, n_axis[ni + step]))
    return neighbors


def _band_score(value: float, bands: list[tuple[float, float]], full: float, higher_is_better: bool) -> float:
    """分档打分：bands 为 (阈值, 满分占比) 列表；FM 用 |t| 越大越好，PS 用 p 越小越好。"""
    for threshold, fraction in bands:
        hit = value >= threshold if higher_is_better else value < threshold
        if hit:
            return fraction * full
    return 0.0


def fm_significance_score(t_stat, cfg: dict) -> tuple[float, dict]:
    """FM 显著性：按 |t| 分档乘满分；t 缺失得 0。"""
    full, bands = cfg["fm_full"], cfg["fm_t_bands"]
    formula = "; ".join(f"|t|>={thr}→{frac * full:g}分" for thr, frac in bands) + "; 其他→0"
    if _is_missing(t_stat):
        return 0.0, {"名称": "FM显著性", "公式": formula, "代入": "t 值缺失", "得分": 0.0}
    score = _band_score(abs(float(t_stat)), bands, full, higher_is_better=True)
    detail = {"名称": "FM显著性", "公式": formula, "代入": f"|t|={abs(float(t_stat)):.2f}", "得分": score}
    return score, detail


def _tier_penalty(value: float, tiers: list[tuple[float, float]]) -> float:
    """阶梯扣分：tiers 按阈值升序，命中第一个 value < 阈值 的档（最严档），否则 0。"""
    for threshold, penalty in tiers:
        if value < threshold:
            return penalty
    return 0.0


def sample_penalty(n_months, n_obs, cfg: dict) -> tuple[float, dict]:
    """样本量扣分：月份数与（月份数×月均基金数）分别按阶梯取最严档后相加。"""
    months_pen = 0.0 if _is_missing(n_months) else _tier_penalty(float(n_months), cfg["months_penalties"])
    obs_pen = 0.0 if _is_missing(n_obs) else _tier_penalty(float(n_obs), cfg["obs_penalties"])
    total = months_pen + obs_pen
    formula = (
        "月份数: " + "; ".join(f"<{t}→{p:g}" for t, p in cfg["months_penalties"])
        + " | 样本数: " + "; ".join(f"<{t}→{p:g}" for t, p in cfg["obs_penalties"])
    )
    detail = {
        "名称": "样本量扣分", "公式": formula,
        "代入": f"月份数={n_months}, 样本数={n_obs} → {months_pen:g} + {obs_pen:g}",
        "得分": total,
    }
    return total, detail
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: PASS（Task 1 的 3 个 + 新增 6 个）

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/scoring.py tests/test_fm_comparison_scoring.py
git commit -m "feat(fm_comparison): scoring 基础（样本层/邻格/FM分档/样本量扣分）"
```

---

### Task 5: scoring 进阶——邻格稳健性、PS 折扣、R² 分位、共线性扣分

**Files:**
- Modify: `I_Visualization/fm_comparison/scoring.py`（追加函数）
- Test: `tests/test_fm_comparison_scoring.py`（追加测试类）

**Interfaces:**
- Consumes: Task 4 的 `neighbor_cells`、`build_axes`、`_band_score`、`_is_missing`。
- Produces:
  - `neighbor_robustness_score(m: int, n: int, coef: float, family_fm: pd.DataFrame, cfg: dict) -> tuple[float, dict]`（`family_fm` 为同一模型+变量的 FM 表子集，需含 `m, n, coef, t_stat` 列）
  - `ps_score(p_value, long_short, fm_coef, cfg: dict) -> tuple[float, dict]`
  - `r2_quality_score(r2: float, pool: pd.Series, family_r2: float, family_pool: pd.Series, cfg: dict) -> tuple[float, dict]`
  - `percentile_of(value: float, pool: pd.Series) -> float`（0~1，含并列值取中点）
  - `collinearity_penalty(diag_family: pd.DataFrame, n_params: int, cfg: dict) -> tuple[float, dict]`（`diag_family` 为该模型的诊断子集，含 `kind, var_1, var_2, n_flagged, involves_core` 列）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_fm_comparison_scoring.py` 末尾追加：

```python
import pandas as pd  # noqa: E402


class TestScoringAdvanced(unittest.TestCase):
    """邻格稳健性、PS 折扣叠乘、R² 分位、共线性扣分。"""

    def setUp(self):
        self.cfg = dict(config.DEFAULT_CONFIG)

    def _family(self):
        # 构造一个族的 FM 表：m6_n6 为本格（coef 为负），四个邻格中两个"同号且 |t|>=1.645"
        return pd.DataFrame({
            "m":      [6,     3,     6,     6,     12],
            "n":      [6,     6,     3,     12,    6],
            "coef":   [-0.05, -0.07, -0.04, 0.03,  -0.06],
            "t_stat": [-2.0,  -1.73, -0.9,  2.1,   -1.8],
        })

    def test_neighbor_robustness(self):
        # 4 个邻格里：m3_n6(-1.73 同号显著) 和 m12_n6(-1.8 同号显著) 命中，m6_n3 不显著，m6_n12 异号
        score, detail = scoring.neighbor_robustness_score(6, 6, -0.05, self._family(), self.cfg)
        self.assertAlmostEqual(score, 10.0 * 2 / 4)
        self.assertIn("2/4", detail["代入"])

    def test_neighbor_no_data(self):
        # 族里只有本格自己 -> 无邻格数据，得 0 并在明细里说明
        alone = pd.DataFrame({"m": [6], "n": [6], "coef": [-0.05], "t_stat": [-2.0]})
        score, detail = scoring.neighbor_robustness_score(6, 6, -0.05, alone, self.cfg)
        self.assertEqual(score, 0.0)
        self.assertIn("无邻格", detail["代入"])

    def test_ps_score_bands_and_discounts(self):
        # p=0.006, 收益 -2.5%/月, FM 系数同为负 -> 满分 30 无折扣
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.025, -0.06, self.cfg)[0], 30.0)
        # 方向冲突：FM 系数为正、多空收益为负 -> ×0.5
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.025, 0.08, self.cfg)[0], 15.0)
        # 经济显著性：|收益| 0.2%/月 < 0.3% -> ×0.8
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.002, -0.06, self.cfg)[0], 24.0)
        # 两个折扣叠乘 ×0.4
        self.assertAlmostEqual(scoring.ps_score(0.0065, -0.002, 0.08, self.cfg)[0], 12.0)
        # 分档边界：恰好 p=0.05 落入 <0.10 档（24 -> 18）
        self.assertAlmostEqual(scoring.ps_score(0.05, -0.025, -0.06, self.cfg)[0], 18.0)
        # 无 PS 记录得 0
        score, detail = scoring.ps_score(None, None, -0.06, self.cfg)
        self.assertEqual(score, 0.0)
        self.assertIn("无PS记录", detail["代入"])

    def test_r2_quality(self):
        pool = pd.Series([0.20, 0.24, 0.28, 0.32])
        fam_pool = pd.Series([0.22, 0.26, 0.30])
        # r2=0.28 在 pool 中分位 (2 + 0.5)/4 = 0.625；族 0.26 在 fam_pool 中分位 0.5
        score, detail = scoring.r2_quality_score(0.28, pool, 0.26, fam_pool, self.cfg)
        self.assertAlmostEqual(score, 0.625 * 12 + 0.5 * 8)
        self.assertEqual(detail["得分"], score)

    def test_collinearity_penalty(self):
        # 1 组非核心风险对、5 个参数组合中标记 3 次 -> -2 × 0.6 = -1.2
        diag = pd.DataFrame([
            {"kind": "corr", "var_1": "Ctrl_a", "var_2": "as_b", "n_flagged": 3, "involves_core": False},
        ])
        score, _ = scoring.collinearity_penalty(diag, 5, self.cfg)
        self.assertAlmostEqual(score, -1.2)
        # 含核心变量的对 -5；持续性超过 1 封顶；corr 合计不低于 -8
        diag2 = pd.DataFrame([
            {"kind": "corr", "var_1": "FAC_rank_vol", "var_2": "Ctrl_a", "n_flagged": 9, "involves_core": True},
            {"kind": "corr", "var_1": "Ctrl_a", "var_2": "as_b", "n_flagged": 5, "involves_core": False},
            {"kind": "corr", "var_1": "Ctrl_c", "var_2": "as_d", "n_flagged": 5, "involves_core": False},
        ])
        score2, _ = scoring.collinearity_penalty(diag2, 5, self.cfg)
        self.assertAlmostEqual(score2, -8.0)  # -5 + -2 + -2 = -9 -> 封顶 -8
        # VIF：核心变量自身超标 -8，非核心 -4，合计封顶 -12
        diag3 = pd.DataFrame([
            {"kind": "vif", "var_1": "FAC_rank_vol", "var_2": None, "n_flagged": 5, "involves_core": True},
            {"kind": "vif", "var_1": "Ctrl_a", "var_2": None, "n_flagged": 5, "involves_core": False},
            {"kind": "vif", "var_1": "Ctrl_b", "var_2": None, "n_flagged": 5, "involves_core": False},
        ])
        score3, _ = scoring.collinearity_penalty(diag3, 5, self.cfg)
        self.assertAlmostEqual(score3, -12.0)  # -8 + -4 + -4 = -16 -> 封顶 -12
        # 无风险 -> 0
        empty = pd.DataFrame(columns=["kind", "var_1", "var_2", "n_flagged", "involves_core"])
        self.assertEqual(scoring.collinearity_penalty(empty, 5, self.cfg)[0], 0.0)
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: 新增测试 FAIL（`AttributeError: ... 'neighbor_robustness_score'`）

- [ ] **Step 3: 写实现**

在 `scoring.py` 末尾追加：

```python
def _sign(x: float) -> int:
    """符号函数：正 1、负 -1、零 0。"""
    return (x > 0) - (x < 0)


def neighbor_robustness_score(m, n, coef, family_fm: pd.DataFrame, cfg: dict) -> tuple[float, dict]:
    """邻格稳健性：邻格中"与本格同号且 |t|>=阈值"的比例 × 满分。

    family_fm 为同一模型+变量的 FM 子表（含 m, n, coef, t_stat）；
    邻格按族内出现过的 m/n 取值构造轴，缺数据的邻格不进分母。
    """
    full, t_min = cfg["neighbor_full"], cfg["neighbor_t_min"]
    formula = f"邻格中(同号且|t|>={t_min})的比例 × {full:g}分；邻格=沿一条轴走一步"
    # 轴由族内全部 (m, n) 组合决定，新参数进来后自动扩展
    m_axis, n_axis = build_axes(zip(family_fm["m"], family_fm["n"]))
    wanted = set(neighbor_cells(m, n, m_axis, n_axis))
    # 只统计族里真实存在数据的邻格
    available = family_fm[[(mm, nn) in wanted for mm, nn in zip(family_fm["m"], family_fm["n"])]]
    if available.empty:
        return 0.0, {"名称": "邻格稳健性", "公式": formula, "代入": "无邻格数据", "得分": 0.0}
    # 命中条件：邻格系数与本格同号，且 |t| 达到显著阈值
    hits = available[
        (available["coef"].map(_sign) == _sign(float(coef)))
        & (available["t_stat"].abs() >= t_min)
    ]
    score = full * len(hits) / len(available)
    cells = ", ".join(f"m{r.m}_n{r.n}(t={r.t_stat:.2f})" for r in available.itertuples())
    detail = {
        "名称": "邻格稳健性", "公式": formula,
        "代入": f"{len(hits)}/{len(available)} 命中；邻格: {cells}",
        "得分": score,
    }
    return score, detail


def ps_score(p_value, long_short, fm_coef, cfg: dict) -> tuple[float, dict]:
    """多空显著性：p 分档基础分 × 方向冲突折扣 × 经济显著性折扣（可叠乘）。"""
    full, bands = cfg["ps_full"], cfg["ps_p_bands"]
    formula = (
        "; ".join(f"p<{thr}→{frac * full:g}分" for thr, frac in bands)
        + f"; 方向冲突×{cfg['ps_direction_conflict_mult']}"
        + f"; |月均多空|<{cfg['ps_econ_threshold']:.1%}×{cfg['ps_econ_mult']}"
    )
    if _is_missing(p_value):
        return 0.0, {"名称": "多空显著性", "公式": formula, "代入": "无PS记录", "得分": 0.0}
    base = _band_score(float(p_value), bands, full, higher_is_better=False)
    mult, notes = 1.0, [f"p={float(p_value):.4f}→基础{base:g}分"]
    # 方向冲突：FM 系数与多空收益符号相反（都非零才判断）
    if not _is_missing(long_short) and not _is_missing(fm_coef) and float(long_short) * float(fm_coef) < 0:
        mult *= cfg["ps_direction_conflict_mult"]
        notes.append(f"方向冲突×{cfg['ps_direction_conflict_mult']}")
    # 经济显著性：月均多空收益太小，即使显著也缺乏选基价值
    if not _is_missing(long_short) and abs(float(long_short)) < cfg["ps_econ_threshold"]:
        mult *= cfg["ps_econ_mult"]
        notes.append(f"|多空|={abs(float(long_short)):.2%}<{cfg['ps_econ_threshold']:.1%}×{cfg['ps_econ_mult']}")
    score = base * mult
    return score, {"名称": "多空显著性", "公式": formula, "代入": "; ".join(notes), "得分": score}


def percentile_of(value: float, pool: pd.Series) -> float:
    """value 在 pool 中的分位（0~1）：小于者计 1、并列计 0.5，除以总数。"""
    pool = pool.dropna()
    if pool.empty or _is_missing(value):
        return 0.0
    return float(((pool < value).sum() + 0.5 * (pool == value).sum()) / len(pool))


def r2_quality_score(r2, pool: pd.Series, family_r2, family_pool: pd.Series, cfg: dict) -> tuple[float, dict]:
    """回归质量：个体 R² 全体分位 × 12 + 族平均 R² 跨族分位 × 8（梯度化，无跳分）。"""
    ind_full, fam_full = cfg["r2_individual_full"], cfg["r2_family_full"]
    ind_pct = percentile_of(r2, pool)
    fam_pct = percentile_of(family_r2, family_pool)
    score = ind_pct * ind_full + fam_pct * fam_full
    detail = {
        "名称": "回归质量",
        "公式": f"个体R²分位×{ind_full:g} + 族均R²分位×{fam_full:g}",
        "代入": f"个体R²={r2}(分位{ind_pct:.2f}), 族均R²={family_r2}(分位{fam_pct:.2f})",
        "得分": score,
    }
    return score, detail


def collinearity_penalty(diag_family: pd.DataFrame, n_params: int, cfg: dict) -> tuple[float, dict]:
    """共线性扣分（族层面）：唯一风险对/变量的基础扣分 × 持续性系数，分类封顶。

    持续性系数 = 被标记次数 / 该族参数组合数，上限 1（同一对在多个 m,n 里反复
    出现说明风险稳定，扣满；只出现一两次则按比例减轻）。
    """
    notes: list[str] = []
    corr_sum, vif_sum = 0.0, 0.0
    for row in diag_family.itertuples():
        # 防御除零；持续性封顶 1
        persistence = min(1.0, row.n_flagged / n_params) if n_params > 0 else 1.0
        if row.kind == "corr":
            base = cfg["corr_pair_core_penalty"] if row.involves_core else cfg["corr_pair_penalty"]
            corr_sum += base * persistence
            notes.append(f"corr {row.var_1}×{row.var_2}: {base:g}×{persistence:.2f}")
        elif row.kind == "vif":
            base = cfg["vif_core_penalty"] if row.involves_core else cfg["vif_penalty"]
            vif_sum += base * persistence
            notes.append(f"vif {row.var_1}: {base:g}×{persistence:.2f}")
    # 分类封顶：扣分为负数，用 max 取"不低于上限"
    corr_total = max(corr_sum, cfg["corr_cap"])
    vif_total = max(vif_sum, cfg["vif_cap"])
    total = corr_total + vif_total
    formula = (
        f"corr: 每唯一对{cfg['corr_pair_penalty']:g}(含核心{cfg['corr_pair_core_penalty']:g})×持续性, "
        f"上限{cfg['corr_cap']:g} | vif: 每变量{cfg['vif_penalty']:g}(核心{cfg['vif_core_penalty']:g})×持续性, "
        f"上限{cfg['vif_cap']:g}"
    )
    detail = {
        "名称": "共线性扣分", "公式": formula,
        "代入": "; ".join(notes) if notes else "无风险记录",
        "得分": total,
    }
    return total, detail
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: PASS（累计 15 个测试）

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/scoring.py tests/test_fm_comparison_scoring.py
git commit -m "feat(fm_comparison): scoring 进阶（邻格/PS折扣/R²分位/共线性扣分）"
```

---

### Task 6: score_all 汇总与擂台徽章

**Files:**
- Modify: `I_Visualization/fm_comparison/scoring.py`（追加函数）
- Test: `tests/test_fm_comparison_scoring.py`（追加测试类）

**Interfaces:**
- Consumes: Task 4/5 的全部打分函数；`data_loader.load_all` 的四表结构。
- Produces:
  - `score_all(tables: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame`：每行一个候选，列
    `batch, model, layer, variable, param_key, m, n, coef, t_stat, stars, long_short, p_value, n_months, avg_funds, n_obs, avg_r2, fm_score, neighbor_score, ps_sig_score, r2_score, sample_pen, collin_pen, total, 明细`（`明细` 为 list[dict]，元素是统一明细结构）
  - `attach_badges(scores: pd.DataFrame, baselines: dict, cfg: dict) -> pd.DataFrame`：追加列
    `is_baseline: bool, baseline_total: float, vs_baseline: float, badge: str`（badge 取值 `""` / `"可能可替代基准"` / `"优先关注"`）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_fm_comparison_scoring.py` 末尾追加：

```python
def _toy_tables():
    """构造两个族（挑战者/守擂者）各两个参数组合的完整四表，用于汇总测试。"""
    coverage = pd.DataFrame({
        "batch": ["b_001"] * 4,
        "model": ["fm_baseline_bottom33", "fm_baseline_bottom33",
                  "fm_baseline_indvol_bottom33", "fm_baseline_indvol_bottom33"],
        "param": ["m3_n6_pairwise1", "m6_n6_pairwise1"] * 2,
        "param_key": ["m3_n6", "m6_n6"] * 2,
        "m": [3, 6] * 2, "n": [6, 6] * 2,
        "n_months": [65, 63, 62, 61],
        "avg_funds": [108.0, 101.0, 90.0, 88.0],
        "n_obs": [7038.0, 6390.0, 5580.0, 5368.0],
        "avg_r2": [0.27, 0.24, 0.30, 0.29],
        "avg_adj_r2": [0.21, 0.18, 0.24, 0.23],
    })
    fm = coverage[["batch", "model", "param", "param_key", "m", "n"]].copy()
    fm["variable"] = "FAC_rank_vol"
    fm["coef"] = [-0.09, -0.01, -0.12, -0.10]
    fm["t_stat"] = [-3.60, -0.16, -3.80, -2.20]
    fm["stars"] = [3, 0, 3, 2]
    ps = fm[["batch", "model", "variable", "param", "param_key", "m", "n"]].copy()
    ps["long_short"] = [-0.016, -0.005, -0.020, -0.015]
    ps["t_stat"] = [-2.03, -0.68, -2.60, -1.90]
    ps["p_value"] = [0.050, 0.504, 0.012, 0.065]
    diag = pd.DataFrame(columns=["batch", "model", "kind", "var_1", "var_2", "n_flagged", "involves_core"])
    return {"coverage": coverage, "fm": fm, "ps": ps, "diag": diag}


class TestScoreAll(unittest.TestCase):
    """汇总打分与擂台徽章。"""

    def setUp(self):
        self.cfg = dict(config.DEFAULT_CONFIG)
        self.tables = _toy_tables()

    def test_score_all_shape_and_total(self):
        scores = scoring.score_all(self.tables, self.cfg)
        # 4 个候选各一行，总分 = 四维得分 + 两类扣分之和
        self.assertEqual(len(scores), 4)
        row = scores[(scores["model"] == "fm_baseline_bottom33") & (scores["param_key"] == "m3_n6")].iloc[0]
        expected = (
            row["fm_score"] + row["neighbor_score"] + row["ps_sig_score"]
            + row["r2_score"] + row["sample_pen"] + row["collin_pen"]
        )
        self.assertAlmostEqual(row["total"], expected)
        # 明细列表覆盖全部六个组成部分
        self.assertEqual(len(row["明细"]), 6)
        # 样本层识别正确
        self.assertTrue((scores["layer"] == "bottom33").all())

    def test_attach_badges(self):
        scores = scoring.score_all(self.tables, self.cfg)
        badged = scoring.attach_badges(scores, config.BASELINES, self.cfg)
        # 基准行被标出且自己不参与打徽章
        base_row = badged[(badged["model"] == "fm_baseline_bottom33") & (badged["param_key"] == "m3_n6")].iloc[0]
        self.assertTrue(base_row["is_baseline"])
        self.assertEqual(base_row["badge"], "")
        # 挑战者 m3_n6：FM 更显著、PS 更显著、R² 更高 -> 总分应高于基准，拿到徽章
        ch = badged[(badged["model"] == "fm_baseline_indvol_bottom33") & (badged["param_key"] == "m3_n6")].iloc[0]
        self.assertGreater(ch["total"], base_row["total"])
        self.assertIn(ch["badge"], ("可能可替代基准", "优先关注"))
        self.assertAlmostEqual(ch["vs_baseline"], ch["total"] - base_row["total"])
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: 新增测试 FAIL（`AttributeError: ... 'score_all'`）

- [ ] **Step 3: 写实现**

在 `scoring.py` 末尾追加：

```python
def score_all(tables: dict[str, pd.DataFrame], cfg: dict) -> pd.DataFrame:
    """给全部候选 (模型目录 × m,n) 打分，返回带六项明细的汇总表。"""
    coverage, fm, ps, diag = tables["coverage"], tables["fm"], tables["ps"], tables["diag"]
    # 候选 = FM 系数表与覆盖表能对上的 (model, param_key)；PS 允许缺失
    base = fm.merge(
        coverage[["model", "param_key", "n_months", "avg_funds", "n_obs", "avg_r2"]],
        on=["model", "param_key"], how="inner",
    ).merge(
        ps[["model", "param_key", "long_short", "p_value"]],
        on=["model", "param_key"], how="left",
    )
    # R² 分位的两个池：全体候选池 + 各族平均池
    pool_r2 = base["avg_r2"]
    family_avg = base.groupby("model")["avg_r2"].mean()
    family_pool = pd.Series(family_avg.values)

    records: list[dict] = []
    for row in base.itertuples():
        # 族内 FM 子表（邻格用），族参数组合数（持续性分母用）
        family_fm = fm[(fm["model"] == row.model) & (fm["variable"] == row.variable)]
        n_params = coverage[coverage["model"] == row.model]["param_key"].nunique()
        diag_family = diag[diag["model"] == row.model]
        # 六个组成部分逐项计算，明细全部保留
        fm_s, d1 = fm_significance_score(row.t_stat, cfg)
        nb_s, d2 = neighbor_robustness_score(row.m, row.n, row.coef, family_fm, cfg)
        ps_s, d3 = ps_score(row.p_value, row.long_short, row.coef, cfg)
        r2_s, d4 = r2_quality_score(row.avg_r2, pool_r2, family_avg[row.model], family_pool, cfg)
        sp, d5 = sample_penalty(row.n_months, row.n_obs, cfg)
        cp, d6 = collinearity_penalty(diag_family, n_params, cfg)
        records.append({
            "batch": row.batch, "model": row.model, "layer": sample_layer(row.model),
            "variable": row.variable, "param_key": row.param_key, "m": row.m, "n": row.n,
            "coef": row.coef, "t_stat": row.t_stat, "stars": row.stars,
            "long_short": row.long_short, "p_value": row.p_value,
            "n_months": row.n_months, "avg_funds": row.avg_funds,
            "n_obs": row.n_obs, "avg_r2": row.avg_r2,
            "fm_score": fm_s, "neighbor_score": nb_s, "ps_sig_score": ps_s,
            "r2_score": r2_s, "sample_pen": sp, "collin_pen": cp,
            "total": fm_s + nb_s + ps_s + r2_s + sp + cp,
            "明细": [d1, d2, d3, d4, d5, d6],
        })
    return pd.DataFrame(records)


def attach_badges(scores: pd.DataFrame, baselines: dict, cfg: dict) -> pd.DataFrame:
    """按样本层配对基准，给胜过基准的候选打徽章。

    规则（spec 第 4 节）：总分 > 基准 -> "可能可替代基准"；
    领先 >= replace_margin -> "优先关注"；other 层无基准，不打徽章。
    """
    scores = scores.copy()
    # 每层基准的总分：基准候选缺失时该层不打徽章
    layer_base_total: dict[str, float] = {}
    is_baseline = pd.Series(False, index=scores.index)
    for layer, spec in baselines.items():
        mask = (scores["model"] == spec["model"]) & (scores["param_key"] == spec["param_key"])
        is_baseline |= mask
        if mask.any():
            layer_base_total[layer] = float(scores.loc[mask, "total"].iloc[0])
    scores["is_baseline"] = is_baseline
    scores["baseline_total"] = scores["layer"].map(layer_base_total)
    scores["vs_baseline"] = scores["total"] - scores["baseline_total"]

    def _badge(row) -> str:
        # 基准自己、无基准层、分数未超过基准 -> 无徽章
        if row["is_baseline"] or pd.isna(row["baseline_total"]) or row["total"] <= row["baseline_total"]:
            return ""
        if row["vs_baseline"] >= cfg["replace_margin"]:
            return "优先关注"
        return "可能可替代基准"

    scores["badge"] = scores.apply(_badge, axis=1)
    return scores
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_scoring.py -v`
Expected: PASS（累计 17 个测试）

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/scoring.py tests/test_fm_comparison_scoring.py
git commit -m "feat(fm_comparison): score_all 汇总打分与擂台徽章"
```

---

### Task 7: export.py 导出可行性排名

**Files:**
- Create: `I_Visualization/fm_comparison/export.py`
- Test: `tests/test_fm_comparison_export.py`

**Interfaces:**
- Consumes: `attach_badges` 输出的 scores 表（含 `明细` 与 badge 列）。
- Produces: `export_ranking(scores: pd.DataFrame, cfg: dict, out_dir: Path) -> Path`（返回写出的 xlsx 路径；三个 sheet：`排名总表`、`打分明细`、`权重快照`）。

- [ ] **Step 1: 写失败测试**

```python
"""export 导出功能的单元测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = PROJECT_ROOT / "I_Visualization" / "fm_comparison"
sys.path.insert(0, str(PKG_DIR))

import config  # noqa: E402
import export  # noqa: E402


class TestExport(unittest.TestCase):
    """校验导出文件的 sheet 结构与内容。"""

    def test_export_ranking(self):
        # 最小 scores 表：两行候选 + 明细列表
        scores = pd.DataFrame({
            "model": ["m_a", "m_b"], "param_key": ["m3_n6", "m6_n6"],
            "layer": ["bottom33", "bottom33"], "total": [68.0, 40.0],
            "badge": ["优先关注", ""], "is_baseline": [False, True],
            "明细": [
                [{"名称": "FM显著性", "公式": "f", "代入": "x", "得分": 40.0}],
                [{"名称": "FM显著性", "公式": "f", "代入": "y", "得分": 24.0}],
            ],
        })
        with tempfile.TemporaryDirectory() as tmp:
            path = export.export_ranking(scores, dict(config.DEFAULT_CONFIG), Path(tmp))
            self.assertTrue(path.exists())
            self.assertTrue(path.name.startswith("fm_ps_指标可行性排名_"))
            # 三个 sheet 齐全
            sheets = pd.ExcelFile(path).sheet_names
            self.assertEqual(sheets, ["排名总表", "打分明细", "权重快照"])
            # 排名总表按 total 降序且不含明细对象列
            rank = pd.read_excel(path, sheet_name="排名总表")
            self.assertEqual(rank.iloc[0]["model"], "m_a")
            self.assertNotIn("明细", rank.columns)
            # 打分明细逐行展开
            detail = pd.read_excel(path, sheet_name="打分明细")
            self.assertEqual(len(detail), 2)
            self.assertIn("公式", detail.columns)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_export.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'export'`）

- [ ] **Step 3: 写实现**

```python
"""把打分结果导出为 xlsx：排名总表 + 打分明细 + 权重快照。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd


def export_ranking(scores: pd.DataFrame, cfg: dict, out_dir: Path) -> Path:
    """写出三 sheet 的可行性排名文件，返回文件路径。

    文件名带时间戳，避免覆盖历史导出；权重快照记录导出时刻生效的全部配置，
    保证排名可复现。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"fm_ps_指标可行性排名_{datetime.now():%Y%m%d_%H%M}.xlsx"
    # 排名总表：按总分降序，去掉对象列（Excel 无法存 list[dict]）
    rank = scores.sort_values("total", ascending=False).drop(columns=["明细"])
    # 打分明细：每个候选的六项组成逐行展开
    detail_rows: list[dict] = []
    for row in scores.itertuples():
        for item in row.明细:
            detail_rows.append({
                "model": row.model, "param_key": row.param_key,
                "名称": item["名称"], "公式": item["公式"],
                "代入": item["代入"], "得分": item["得分"],
            })
    detail = pd.DataFrame(detail_rows)
    # 权重快照：配置项转成两列文本
    snapshot = pd.DataFrame(
        [(k, str(v)) for k, v in cfg.items()], columns=["参数", "取值"]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        rank.to_excel(writer, sheet_name="排名总表", index=False)
        detail.to_excel(writer, sheet_name="打分明细", index=False)
        snapshot.to_excel(writer, sheet_name="权重快照", index=False)
    return path
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_export.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/export.py tests/test_fm_comparison_export.py
git commit -m "feat(fm_comparison): 可行性排名 xlsx 导出"
```

---

### Task 8: app.py 三 Tab 页面与端到端验证

**Files:**
- Create: `I_Visualization/fm_comparison/app.py`

**Interfaces:**
- Consumes: `config`（默认配置、基准、路径）、`data_loader.load_all`、`scoring.score_all` / `attach_badges` / `sample_layer`、`export.export_ranking`。
- Produces: 可用 `.venv/bin/streamlit run I_Visualization/fm_comparison/app.py` 启动的页面（Tab1 擂台对比 / Tab2 可行性排行榜 / Tab3 打分说明）。

- [ ] **Step 1: 写 app.py**

```python
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


def render_side(title: str, side_scores: pd.DataFrame, tables: dict, champion_key: str | None, defender_total: float | None, cfg: dict):
    """渲染擂台一侧的四个块：FM 网格 / 覆盖与 R² / 多空 / 共线性诊断。"""
    model = side_scores["model"].iloc[0]
    fam_r2 = side_scores["avg_r2"].mean()
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
        left, right = st.columns(2)
        with left:
            challenger = st.selectbox("挑战者（新指标族）", models, index=0)
        # 守擂者按挑战者的样本层自动带出，可手动改
        layer = scoring.sample_layer(challenger)
        default_base = config.BASELINES.get(layer)
        with right:
            defender_model = st.selectbox(
                "守擂者（基准族）", models,
                index=models.index(default_base["model"]) if default_base and default_base["model"] in models else 0,
            )
            defender_params = sorted(scores[scores["model"] == defender_model]["param_key"].unique())
            default_param = default_base["param_key"] if default_base else defender_params[0]
            champion_key = st.selectbox(
                "现役参数组合", defender_params,
                index=defender_params.index(default_param) if default_param in defender_params else 0,
            )
        ch_scores = scores[scores["model"] == challenger]
        df_scores = scores[scores["model"] == defender_model]
        champ_rows = df_scores[df_scores["param_key"] == champion_key]
        defender_total = float(champ_rows["total"].iloc[0]) if not champ_rows.empty else None
        col_l, col_r = st.columns(2)
        with col_l:
            render_side(f"挑战者：{challenger}", ch_scores, tables, None, defender_total, cfg)
        with col_r:
            render_side(f"守擂者：{defender_model}", df_scores, tables, champion_key, None, cfg)
        with st.expander("分数计算明细（点开逐项复算）"):
            render_breakdown(scores, [challenger, defender_model])

    # ---- Tab2 可行性排行榜 ----
    with tab2:
        f1, f2, f3 = st.columns(3)
        batches = f1.multiselect("批次", sorted(scores["batch"].unique()))
        layers = f2.multiselect("样本层", sorted(scores["layer"].unique()))
        params = f3.multiselect("参数组合", sorted(scores["param_key"].unique()))
        view = scores.copy()
        if batches:
            view = view[view["batch"].isin(batches)]
        if layers:
            view = view[view["layer"].isin(layers)]
        if params:
            view = view[view["param_key"].isin(params)]
        view = view.sort_values("total", ascending=False)
        show_cols = ["model", "param_key", "layer", "total", "fm_score", "neighbor_score",
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
```

- [ ] **Step 2: 语法与导入检查**

Run: `.venv/bin/python -m py_compile I_Visualization/fm_comparison/app.py && echo OK`
Expected: 输出 `OK`

- [ ] **Step 3: 无头启动冒烟测试**

```bash
.venv/bin/streamlit run I_Visualization/fm_comparison/app.py --server.headless true --server.port 8599 &
SL_PID=$!
sleep 10
curl -s http://localhost:8599 | grep -o "<title>[^<]*" && echo SMOKE_OK
kill $SL_PID
```

Expected: 输出含 `<title>` 行与 `SMOKE_OK`；若页面报错，在浏览器打开 `http://localhost:8599` 看具体 traceback 修复后重试

- [ ] **Step 4: 跑全部 fm_comparison 测试 + 真实数据人工核对**

Run: `.venv/bin/python -m pytest tests/test_fm_comparison_data_loader.py tests/test_fm_comparison_scoring.py tests/test_fm_comparison_export.py -v`
Expected: 全部 PASS

再用真实总表做一次快速合理性核对（脚本内联运行）：

```bash
.venv/bin/python - <<'EOF'
import sys
from pathlib import Path
sys.path.insert(0, str(Path("I_Visualization/fm_comparison")))
import config, data_loader, scoring

tables = data_loader.load_all(config.SUMMARY_XLSX)
scores = scoring.attach_badges(scoring.score_all(tables, dict(config.DEFAULT_CONFIG)), config.BASELINES, dict(config.DEFAULT_CONFIG))
# 基准两行必须存在且有总分
for layer, spec in config.BASELINES.items():
    row = scores[(scores["model"] == spec["model"]) & (scores["param_key"] == spec["param_key"])]
    print(layer, spec["model"], spec["param_key"], "total=", round(float(row["total"].iloc[0]), 2))
# 排名前 10 概览
cols = ["model", "param_key", "total", "badge"]
print(scores.sort_values("total", ascending=False)[cols].head(10).to_string(index=False))
EOF
```

Expected: 两条基准都打印出总分；前 10 排名无 NaN 总分。人工核对：`fm_baseline_bottom33 × m3_n6` 的 FM 分应为 40（t=-3.60 命中 >=2.58 档）、PS 基础分应为 18（p≈0.0500 未过 <0.05 档、落 <0.10 档）；若与总表 sheet 数字对不上，逐项查该行 `明细` 定位是哪一步的公式或代入值出了偏差

- [ ] **Step 5: Commit**

```bash
git add I_Visualization/fm_comparison/app.py
git commit -m "feat(fm_comparison): 擂台式三 Tab Streamlit 页面"
```

---

## 完成定义

- `tests/test_fm_comparison_*.py` 全部通过；
- `.venv/bin/streamlit run I_Visualization/fm_comparison/app.py` 可启动，三个 Tab 均能渲染真实总表数据；
- Tab1 左右对照可选任意族，守擂侧现役格带 ★ 标记，挑战者格有优/平/劣色点与分数脚注，底部明细可逐项复算；
- Tab2 排行榜可筛选、基准行高亮、可导出三 sheet xlsx 到 `I_Visualization/fm_comparison/output/`（不提交 git）；
- 侧栏调整权重后排名与徽章实时变化。
