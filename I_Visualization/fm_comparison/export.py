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
    # 创建输出目录
    out_dir.mkdir(parents=True, exist_ok=True)
    # 生成时间戳文件名
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

    # 写出三个 sheet 的 xlsx
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        rank.to_excel(writer, sheet_name="排名总表", index=False)
        detail.to_excel(writer, sheet_name="打分明细", index=False)
        snapshot.to_excel(writer, sheet_name="权重快照", index=False)

    return path
