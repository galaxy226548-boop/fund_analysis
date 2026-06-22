# 项目环境提示

- 本项目已配置本地虚拟环境 `.venv`，数据分析相关依赖应优先使用 `.venv/bin/python` 执行。
- 读取或处理 Excel、Parquet、CSV 等数据文件时，优先使用项目环境中的 pandas；例如：`.venv/bin/python -c "import pandas as pd; ..."`。
- `requirements.txt` 中已包含 pandas、numpy、openpyxl、pyarrow、matplotlib 等常用分析依赖。

# 代码注释风格

- 本项目新增或修改脚本时，注释和说明性 docstring 应优先使用简体中文。
- 注释应适当多写一些，帮助只上过一学期 Python 课、成绩大约 B+ 的大学生也能读懂代码意图。
- 注释重点解释“为什么这样写”和“这一段在做什么”，不要只机械重复代码本身。
- 除了给函数写 docstring，函数内部的关键步骤也要加简体中文注释，尤其是排序、分组、缺失值处理、窗口计算、文件覆盖和校验逻辑。
