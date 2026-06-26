"""按 input_update_record.json 自动重跑受输入更新时间影响的脚本。

运行方式：

    .venv/bin/python A_data/scripts/0_engine.py

脚本会读取 A_data/reference/input_update_record.json。该 JSON 的结构为：

    {
      "脚本名.py": {
        "输入文件路径": "YYYY-MM-DD HH:MM:SS"
      }
    }

当某个输入文件当前更新时间与 JSON 记录不一致时，engine 会运行对应脚本。
脚本运行成功后，engine 会把该脚本涉及的输入文件更新时间更新回 JSON，
然后重新从头检查，直到所有记录都与当前文件状态一致。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
A_DATA_ROOT = PROJECT_ROOT / "A_data"
SCRIPTS_DIR = A_DATA_ROOT / "scripts"
DEFAULT_RECORD_PATH = A_DATA_ROOT / "reference" / "input_update_record.json"
DEFAULT_MAX_ROUNDS = 50

# 部分脚本需要额外命令行参数才能在 engine 级联中正确运行。
# 例如 2_fund_filter.py 默认会自动串联调用 3_generate_panel_base.py，
# 但 engine 已经把 3_generate_panel_base.py 作为独立步骤管理，
# 如果不加 --skip-panel 就会导致面板脚本被重复执行。
SCRIPT_EXTRA_ARGS: dict[str, list[str]] = {
    "2_fund_filter.py": ["--skip-panel"],
}


def parse_args() -> argparse.Namespace:
    """读取命令行参数。"""
    parser = argparse.ArgumentParser(
        description="检测输入文件更新时间，并自动重跑受影响脚本。"
    )
    parser.add_argument(
        "--record",
        type=Path,
        default=DEFAULT_RECORD_PATH,
        help="输入更新时间记录 JSON，默认使用 A_data/reference/input_update_record.json。",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=DEFAULT_MAX_ROUNDS,
        help="最多允许重跑脚本的次数，用于防止循环依赖导致无限运行。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印会重跑哪些脚本，不实际执行，也不更新 JSON。",
    )
    return parser.parse_args()


def load_record(record_path: Path) -> OrderedDict[str, OrderedDict[str, str]]:
    """按 JSON 原始顺序读取脚本输入更新时间记录。"""
    if not record_path.exists():
        raise FileNotFoundError(f"未找到更新时间记录：{record_path}")

    with record_path.open("r", encoding="utf-8") as file:
        data = json.load(file, object_pairs_hook=OrderedDict)

    if not isinstance(data, dict):
        raise ValueError(f"{record_path} 顶层必须是对象。")

    for script_name, inputs in data.items():
        if not isinstance(inputs, dict):
            raise ValueError(f"{record_path} 中 {script_name} 的值必须是对象。")
    return data


def save_record(
    record_path: Path, record: OrderedDict[str, OrderedDict[str, str]]
) -> None:
    """保存更新时间记录，保留中文路径可读性。"""
    with record_path.open("w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")


def resolve_project_path(path_text: str) -> Path:
    """把 JSON 中的相对路径解析为项目绝对路径。"""
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def format_mtime(path: Path) -> str | None:
    """返回文件更新时间字符串；文件不存在时返回 None。"""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def find_first_mismatch(
    record: OrderedDict[str, OrderedDict[str, str]]
) -> tuple[str, list[tuple[str, str | None, str]]] | None:
    """按记录顺序找出第一个存在输入更新时间不一致的脚本。"""
    for script_name, inputs in record.items():
        mismatches = []
        for input_path_text, recorded_mtime in inputs.items():
            current_mtime = format_mtime(resolve_project_path(input_path_text))
            if current_mtime != recorded_mtime:
                mismatches.append((input_path_text, current_mtime, recorded_mtime))
        if mismatches:
            return script_name, mismatches
    return None


def choose_python() -> Path:
    """优先使用项目虚拟环境中的 Python。"""
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def resolve_script_path(script_name: str) -> Path:
    """把 JSON key 解析为脚本绝对路径。

    如果 key 包含目录分隔符（如 ``B_factors/scripts/xxx.py``），
    视为项目根目录下的相对路径；否则在 ``A_data/scripts/`` 下查找。
    """
    if "/" in script_name or "\\" in script_name:
        return PROJECT_ROOT / script_name
    return SCRIPTS_DIR / script_name


def run_script(script_name: str, python_executable: Path) -> None:
    """运行受影响的脚本。"""
    script_path = resolve_script_path(script_name)
    if not script_path.exists():
        raise FileNotFoundError(f"记录中对应脚本不存在：{script_path}")

    extra_args = SCRIPT_EXTRA_ARGS.get(script_name, [])
    command = [str(python_executable), str(script_path), *extra_args]
    print("\n" + "=" * 80)
    print(f"开始运行：{script_name}")
    print(f"命令：{' '.join(command)}")
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    print(f"运行完成：{script_name}")


def refresh_script_record(
    record: OrderedDict[str, OrderedDict[str, str]], script_name: str
) -> None:
    """脚本运行成功后，更新该脚本全部输入文件的当前更新时间。"""
    missing_paths = []
    for input_path_text in record[script_name]:
        current_mtime = format_mtime(resolve_project_path(input_path_text))
        if current_mtime is None:
            missing_paths.append(input_path_text)
            continue
        record[script_name][input_path_text] = current_mtime

    if missing_paths:
        missing_list = "\n".join(f"- {path}" for path in missing_paths)
        raise FileNotFoundError(
            f"{script_name} 运行后仍有输入文件不存在，无法更新记录：\n{missing_list}"
        )


def print_mismatches(
    script_name: str, mismatches: list[tuple[str, str | None, str]]
) -> None:
    """打印当前触发重跑的输入文件。"""
    print("\n" + "=" * 80)
    print(f"检测到 {script_name} 的输入文件更新时间不一致：")
    for path_text, current_mtime, recorded_mtime in mismatches:
        current_label = current_mtime if current_mtime is not None else "文件不存在"
        print(f"- {path_text}")
        print(f"  JSON 记录：{recorded_mtime}")
        print(f"  当前文件：{current_label}")


def main() -> None:
    """程序入口。"""
    args = parse_args()
    if args.max_rounds < 1:
        raise ValueError("--max-rounds 必须大于等于 1。")

    record_path = args.record if args.record.is_absolute() else PROJECT_ROOT / args.record
    record = load_record(record_path)
    python_executable = choose_python()

    print(f"项目根目录：{PROJECT_ROOT}")
    print(f"更新时间记录：{record_path}")
    print(f"Python：{python_executable}")

    run_count = 0
    while True:
        mismatch = find_first_mismatch(record)
        if mismatch is None:
            print("\n所有记录的输入文件更新时间均已一致。")
            print(f"本次共重跑脚本：{run_count} 次")
            return

        script_name, mismatches = mismatch
        print_mismatches(script_name, mismatches)

        if args.dry_run:
            print("\n--dry-run 模式：未运行脚本，未更新 JSON。")
            return

        if run_count >= args.max_rounds:
            raise RuntimeError(
                f"已达到最大重跑次数 {args.max_rounds}，仍未收敛；"
                "请检查是否存在脚本互相更新彼此输入的循环依赖。"
            )

        run_script(script_name, python_executable)
        refresh_script_record(record, script_name)
        save_record(record_path, record)
        run_count += 1
        print(f"已更新 {script_name} 在 {record_path} 中的输入更新时间记录。")


if __name__ == "__main__":
    main()
