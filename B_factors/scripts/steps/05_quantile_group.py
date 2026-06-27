"""历史 Step 05：q5/q10 分组标签生成逻辑已归档。"""

from __future__ import annotations

import argparse
from pathlib import Path


def parse_args() -> argparse.Namespace:
    """读取输入和输出路径。"""

    parser = argparse.ArgumentParser(description="历史 Step 05：q5/q10 标签生成逻辑已归档。")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """提示用户使用归档文件查看旧逻辑。"""

    args = parse_args()
    raise RuntimeError(
        "q5/q10 分组步骤已从当前 B_factors pipeline 移除。"
        "历史实现已归档到 B_factors/bin/archived_quantile_group_logic.py。"
        f"本次传入的输入为 {args.input}，输出为 {args.output}。"
    )


if __name__ == "__main__":
    main()
