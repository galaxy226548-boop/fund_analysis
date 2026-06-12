很好的习惯！来做一个完整的交接文档。

**关于是否需要带文件：是的，建议带上。** 新窗口的 Claude 没有记忆，光靠文字描述很难精确修改代码，带上文件才能直接操作。

---

## 交接存档

**项目：Parquet 清洗覆盖审计工具**

### 文件结构
```
MAIN_STYLE_ROTATION/
└── I_Visualization/
    ├── clean_auditor_app.py      # 主应用
    └── src/
        └── mapping_loader.py     # mapping 逻辑模块
```

启动命令：
```bash
cd ~/Projects/MAIN_STYLE_ROTATION
streamlit run I_Visualization/clean_auditor_app.py
```

---

### 已实现功能

**覆盖审计**
- 扫描 raw_dir / cleaned_dir 下所有 `.parquet` 和 `.xlsx` 文件
- 覆盖表字段：`file_name`、`raw_exists`、`cleaned_exists`、`status`、`match_method`、`mapped_raw_files`、`mapping_status`
- 状态三态：✅ 已清洗 / ⏳ 未清洗 / 👻 孤儿清洗文件
- 顶部统计指标：raw 数、cleaned 数、未清洗数、孤儿数
- 按状态筛选

**Mapping JSON 支持**
- 侧边栏可填 mapping JSON 路径，优先用 JSON 匹配，失败自动回退同名匹配
- JSON 结构：`sheets -> records`，每条记录含 `clean_data`（cleaned 文件名）和 `file_name`（raw 文件名）
- `clean_data` 为 `"none"` / `"nan"` 等占位符的记录自动跳过
- 新增覆盖表字段 `match_method`（`json_mapping` / `same_name`）和 `mapping_status`

**默认路径常量**（在 app 顶部）
```python
DEFAULT_RAW_DIR    = r"/Users/chloezh/Projects/MAIN_STYLE_ROTATION/A_data/data"
DEFAULT_CLEAN_DIR  = r"/Users/chloezh/Projects/MAIN_STYLE_ROTATION/A_data/prepared_data"
DEFAULT_MAPPING_JSON = r"/Users/chloezh/Projects/MAIN_STYLE_ROTATION/A_data/reference/data_inventory_A.json"
```

**文件预览 & Profile**
- ① Radio 先选侧（Clean Data / Raw Data），② 文件列表随之切换
- Raw 侧：列表显示实际存在的 raw 文件名，选中后 Cleaned 预览自动过滤只显示列名匹配的列
- Clean 侧：列表显示 cleaned 文件，正常预览
- 每个预览 Tab 显示前 50 行 + 分割线 + 后 50 行
- Profile Tab：行数、列数、每列缺失率（进度条）、字段类型、数值列 min/max/mean
- Profile 对比 Tab：raw vs cleaned 并排逐字段对比，含行数/列数 delta

**稳定性**
- 所有文件读取包裹 try/except，失败显示红色提示不崩溃
- mapping JSON 读取失败显示 warning 并回退同名匹配
- 用 `st.session_state` 保持扫描状态，selectbox 切换不会白屏

---

### 开新窗口时的操作步骤

1. 上传 `clean_auditor_app.py` 和 `src/mapping_loader.py` 两个文件
2. 把上面这段存档复制粘贴进去
3. 说明你的新需求

新窗口的 Claude 看到文件 + 存档就能无缝接手。