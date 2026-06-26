"""
CSMAR 数据解压脚本 v2
功能：
1. 扫描 download 文件夹中所有 .rar / .zip 压缩包并逐个解压
2. 文件分类：xlsx -> data_csmar/xlsx/, txt -> data_csmar/txt/, pdf -> data_csmar/ignored_pdf/
3. 同名文件自动加 _1, _2... 后缀，不覆盖
4. 尝试将 txt 与 xlsx 配对（基于 [DES][xlsx] 命名规则，但容错）
5. 生成 manifest.json（追加式）、manifest.csv、process_log.txt

依赖：
  macOS 上需要安装 unar: brew install unar

使用：
  python3 extract_csmar.py /path/to/download /path/to/data_csmar
"""

import os
import sys
import json
import csv
import shutil
import subprocess
import tempfile
from datetime import datetime


# ---------------------------------------------------------------------------
# 1. 检查解压工具
# ---------------------------------------------------------------------------

def check_unar_available():
    if shutil.which("unar") is None:
        print("错误：未检测到 'unar' 命令。")
        print("请先安装：brew install unar")
        sys.exit(1)


# ---------------------------------------------------------------------------
# 2. 扫描 rar 文件
# ---------------------------------------------------------------------------

def scan_archive_files(download_dir):
    archives = []
    for f in sorted(os.listdir(download_dir)):
        if f.lower().endswith((".rar", ".zip")):
            archives.append(os.path.join(download_dir, f))
    return archives


# ---------------------------------------------------------------------------
# 3. 解压单个 rar 到临时目录，返回解压出的所有文件路径列表
# ---------------------------------------------------------------------------

def extract_rar_to_temp(rar_path, tmp_dir):
    """成功返回 (True, [文件路径列表], None)，失败返回 (False, [], 错误信息)"""
    try:
        subprocess.run(
            ["unar", "-f", "-o", tmp_dir, rar_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode("utf-8", errors="ignore") if e.stderr else str(e)
        return False, [], err_msg

    extracted = []
    for dirpath, _, filenames in os.walk(tmp_dir):
        for fn in filenames:
            extracted.append(os.path.join(dirpath, fn))
    return True, extracted, None


# ---------------------------------------------------------------------------
# 4. 文件分类
# ---------------------------------------------------------------------------

def classify_files(file_paths):
    """按扩展名分类，返回 {'xlsx': [...], 'txt': [...], 'pdf': [...], 'other': [...]}"""
    groups = {"xlsx": [], "txt": [], "pdf": [], "other": []}
    for fpath in file_paths:
        ext = os.path.splitext(fpath)[1].lower()
        if ext == ".xlsx":
            groups["xlsx"].append(fpath)
        elif ext == ".txt":
            groups["txt"].append(fpath)
        elif ext == ".pdf":
            groups["pdf"].append(fpath)
        else:
            groups["other"].append(fpath)
    return groups


# ---------------------------------------------------------------------------
# 5. 防覆蓋的重命名：在目标目录中找一个不冲突的文件名
# ---------------------------------------------------------------------------

def get_unique_dest_name(filename, dest_dir, used_names_set):
    """
    若 dest_dir 中已存在该文件名，或本次运行已经用过该名字，
    则在文件名（不含扩展名）后加 _1, _2... 直到不冲突。
    返回 (最终文件名, 是否发生了重命名)
    """
    name, ext = os.path.splitext(filename)
    candidate = filename
    counter = 1
    renamed = False
    while candidate in used_names_set or os.path.exists(os.path.join(dest_dir, candidate)):
        candidate = f"{name}_{counter}{ext}"
        counter += 1
        renamed = True
    used_names_set.add(candidate)
    return candidate, renamed


# ---------------------------------------------------------------------------
# 6. 匹配 xlsx 与 txt
#    规则：txt 原始名通常是 "<xlsx文件名（不含扩展名）>[DES][xlsx].txt"
#    容错：若找不到严格匹配，尝试用 xlsx 基础名作为前缀匹配
# ---------------------------------------------------------------------------

def find_matching_txt(xlsx_original_name, txt_file_list):
    """
    xlsx_original_name: 原始 xlsx 文件名（含 .xlsx）
    txt_file_list: 本压缩包内所有 txt 文件的原始文件名列表
    返回匹配到的 txt 原始文件名，找不到则返回 None
    """
    xlsx_base = os.path.splitext(xlsx_original_name)[0]

    # 规则1：严格匹配 "<base>[DES][xlsx].txt"
    strict_candidate = f"{xlsx_base}[DES][xlsx].txt"
    for txt_name in txt_file_list:
        if txt_name == strict_candidate:
            return txt_name

    # 规则2：宽松匹配 —— txt 文件名以 xlsx 的 base 名开头
    for txt_name in txt_file_list:
        txt_base = os.path.splitext(txt_name)[0]
        if txt_base.startswith(xlsx_base):
            return txt_name

    return None


# ---------------------------------------------------------------------------
# 7. 写入 manifest.json（追加式）和 manifest.csv（每次重写，基于追加后的完整列表）
# ---------------------------------------------------------------------------

def load_existing_manifest(manifest_json_path):
    if os.path.exists(manifest_json_path):
        try:
            with open(manifest_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def write_manifest_json(manifest_json_path, all_entries):
    with open(manifest_json_path, "w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)


def write_manifest_csv(manifest_csv_path, all_entries):
    fieldnames = [
        "source_rar_path",
        "original_xlsx_name",
        "final_xlsx_name",
        "matched_txt_original_name",
        "matched_txt_final_name",
        "txt_exists",
        "renamed_due_to_conflict",
        "pdf_files_ignored",
        "other_files_ignored",
        "status",
        "error_message",
    ]
    with open(manifest_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in all_entries:
            row = dict(entry)
            row["pdf_files_ignored"] = "; ".join(entry.get("pdf_files_ignored", []) or [])
            row["other_files_ignored"] = "; ".join(entry.get("other_files_ignored", []) or [])
            writer.writerow(row)


# ---------------------------------------------------------------------------
# 8. 写日志
# ---------------------------------------------------------------------------

def write_log(log_path, lines):
    with open(log_path, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


# ---------------------------------------------------------------------------
# 主流程：处理单个 rar 文件，返回该 rar 产生的 manifest 条目列表 + 日志行列表
# ---------------------------------------------------------------------------

def process_one_rar(rar_path, output_dirs, used_names):
    """
    output_dirs: dict, keys = 'xlsx', 'txt', 'pdf'，值为对应输出目录路径
    used_names: dict, keys = 'xlsx', 'txt', 'pdf'，值为 set()，跟踪本次运行已用过的文件名
    返回 (entries, log_lines)
    """
    entries = []
    log_lines = []
    rar_name = os.path.basename(rar_path)
    log_lines.append(f"[{datetime.now().isoformat()}] 开始处理: {rar_name}")

    with tempfile.TemporaryDirectory() as tmpdir:
        ok, extracted_files, err = extract_rar_to_temp(rar_path, tmpdir)

        if not ok:
            log_lines.append(f"  解压失败: {err.strip() if err else '未知错误'}")
            entries.append({
                "source_rar_path": rar_path,
                "original_xlsx_name": None,
                "final_xlsx_name": None,
                "matched_txt_original_name": None,
                "matched_txt_final_name": None,
                "txt_exists": False,
                "renamed_due_to_conflict": False,
                "pdf_files_ignored": [],
                "other_files_ignored": [],
                "status": "extract_failed",
                "error_message": err.strip() if err else "unknown error",
            })
            return entries, log_lines

        groups = classify_files(extracted_files)

        # --- 处理 PDF：移动到 ignored_pdf/，并记录名字 ---
        pdf_ignored_names = []
        for pdf_path in groups["pdf"]:
            fname = os.path.basename(pdf_path)
            final_name, _ = get_unique_dest_name(fname, output_dirs["pdf"], used_names["pdf"])
            try:
                shutil.move(pdf_path, os.path.join(output_dirs["pdf"], final_name))
            except OSError as e:
                log_lines.append(f"  移动 PDF 失败 ({fname}): {e}")
            pdf_ignored_names.append(fname)

        if pdf_ignored_names:
            log_lines.append(f"  忽略 PDF: {', '.join(pdf_ignored_names)}")

        # --- 其他未识别类型文件 ---
        other_ignored_names = [os.path.basename(p) for p in groups["other"]]
        if other_ignored_names:
            log_lines.append(f"  其他未处理文件: {', '.join(other_ignored_names)}")

        # 本压缩包内 txt 原始文件名列表（用于匹配）
        txt_original_names = [os.path.basename(p) for p in groups["txt"]]
        txt_path_by_name = {os.path.basename(p): p for p in groups["txt"]}
        matched_txt_names = set()  # 记录已被匹配走的 txt（避免重复分配）

        # --- 处理每个 xlsx ---
        if groups["xlsx"]:
            for xlsx_path in groups["xlsx"]:
                original_xlsx_name = os.path.basename(xlsx_path)

                final_xlsx_name, renamed_xlsx = get_unique_dest_name(
                    original_xlsx_name, output_dirs["xlsx"], used_names["xlsx"]
                )
                try:
                    shutil.move(xlsx_path, os.path.join(output_dirs["xlsx"], final_xlsx_name))
                except OSError as e:
                    log_lines.append(f"  移动 xlsx 失败 ({original_xlsx_name}): {e}")
                    entries.append({
                        "source_rar_path": rar_path,
                        "original_xlsx_name": original_xlsx_name,
                        "final_xlsx_name": None,
                        "matched_txt_original_name": None,
                        "matched_txt_final_name": None,
                        "txt_exists": False,
                        "renamed_due_to_conflict": False,
                        "pdf_files_ignored": pdf_ignored_names,
                        "other_files_ignored": other_ignored_names,
                        "status": "xlsx_move_failed",
                        "error_message": str(e),
                    })
                    continue

                matched_txt_original = find_matching_txt(original_xlsx_name, txt_original_names)
                matched_txt_final = None
                txt_exists = False
                renamed_txt = False

                if matched_txt_original and matched_txt_original not in matched_txt_names:
                    txt_path = txt_path_by_name[matched_txt_original]
                    final_txt_name, renamed_txt = get_unique_dest_name(
                        matched_txt_original, output_dirs["txt"], used_names["txt"]
                    )
                    try:
                        shutil.move(txt_path, os.path.join(output_dirs["txt"], final_txt_name))
                        matched_txt_final = final_txt_name
                        txt_exists = True
                        matched_txt_names.add(matched_txt_original)
                    except OSError as e:
                        log_lines.append(f"  移动 txt 失败 ({matched_txt_original}): {e}")

                entries.append({
                    "source_rar_path": rar_path,
                    "original_xlsx_name": original_xlsx_name,
                    "final_xlsx_name": final_xlsx_name,
                    "matched_txt_original_name": matched_txt_original,
                    "matched_txt_final_name": matched_txt_final,
                    "txt_exists": txt_exists,
                    "renamed_due_to_conflict": renamed_xlsx or renamed_txt,
                    "pdf_files_ignored": pdf_ignored_names,
                    "other_files_ignored": other_ignored_names,
                    "status": "success",
                    "error_message": None,
                })
                log_lines.append(
                    f"  xlsx: {original_xlsx_name} -> {final_xlsx_name} | "
                    f"txt: {matched_txt_original} -> {matched_txt_final if matched_txt_final else '(未找到)'}"
                )

        # --- 处理未被任何 xlsx 匹配到的剩余 txt（仍然移动，但单独记一条） ---
        for txt_name, txt_path in txt_path_by_name.items():
            if txt_name in matched_txt_names:
                continue
            final_txt_name, renamed_txt = get_unique_dest_name(
                txt_name, output_dirs["txt"], used_names["txt"]
            )
            try:
                shutil.move(txt_path, os.path.join(output_dirs["txt"], final_txt_name))
            except OSError as e:
                log_lines.append(f"  移动 txt 失败 ({txt_name}): {e}")
                continue

            entries.append({
                "source_rar_path": rar_path,
                "original_xlsx_name": None,
                "final_xlsx_name": None,
                "matched_txt_original_name": txt_name,
                "matched_txt_final_name": final_txt_name,
                "txt_exists": True,
                "renamed_due_to_conflict": renamed_txt,
                "pdf_files_ignored": pdf_ignored_names if not groups["xlsx"] else [],
                "other_files_ignored": other_ignored_names if not groups["xlsx"] else [],
                "status": "txt_without_xlsx",
                "error_message": None,
            })
            log_lines.append(f"  未匹配 xlsx 的 txt: {txt_name} -> {final_txt_name}")

        # --- 若压缩包内没有 xlsx 也没有 txt，但有 pdf/other，记一条占位 ---
        if not groups["xlsx"] and not groups["txt"] and (pdf_ignored_names or other_ignored_names):
            entries.append({
                "source_rar_path": rar_path,
                "original_xlsx_name": None,
                "final_xlsx_name": None,
                "matched_txt_original_name": None,
                "matched_txt_final_name": None,
                "txt_exists": False,
                "renamed_due_to_conflict": False,
                "pdf_files_ignored": pdf_ignored_names,
                "other_files_ignored": other_ignored_names,
                "status": "no_xlsx_no_txt",
                "error_message": None,
            })

    log_lines.append(f"[{datetime.now().isoformat()}] 完成处理: {rar_name}")
    return entries, log_lines


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    # 脚本文件位于 A_data/scripts/，项目根目录为其上两级
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _project_root = os.path.dirname(os.path.dirname(_script_dir))

    if len(sys.argv) >= 3:
        download_dir = sys.argv[1]
        output_root = sys.argv[2]
    elif len(sys.argv) == 2:
        download_dir = sys.argv[1]
        output_root = os.path.join(download_dir, "data_csmar")
    else:
        download_dir = os.path.join(_project_root, "A_data", "data", "CSMAR_rar")
        output_root = os.path.join(_project_root, "A_data", "data", "data_csmar")

    download_dir = os.path.abspath(download_dir)
    output_root = os.path.abspath(output_root)

    check_unar_available()

    output_dirs = {
        "xlsx": os.path.join(output_root, "xlsx"),
        "txt": os.path.join(output_root, "txt"),
        "pdf": os.path.join(output_root, "ignored_pdf"),
    }
    for d in output_dirs.values():
        os.makedirs(d, exist_ok=True)

    manifest_json_path = os.path.join(output_root, "manifest.json")
    manifest_csv_path = os.path.join(output_root, "manifest.csv")
    log_path = os.path.join(output_root, "process_log.txt")

    archive_files = scan_archive_files(download_dir)
    if not archive_files:
        print(f"在 {download_dir} 中未找到 .rar / .zip 文件")
        sys.exit(0)

    # 追加式 manifest：先读取已有条目
    all_entries = load_existing_manifest(manifest_json_path)

    # used_names 基于输出目录中已存在的文件初始化，避免与历史运行冲突
    used_names = {"xlsx": set(), "txt": set(), "pdf": set()}
    for key, d in output_dirs.items():
        for f in os.listdir(d):
            used_names[key].add(f)

    write_log(log_path, [f"===== 运行开始: {datetime.now().isoformat()} ====="])

    for archive_path in archive_files:
        print(f"处理: {os.path.basename(archive_path)}")
        entries, log_lines = process_one_rar(archive_path, output_dirs, used_names)
        all_entries.extend(entries)
        write_log(log_path, log_lines)

    write_log(log_path, [f"===== 运行结束: {datetime.now().isoformat()} ====="])

    write_manifest_json(manifest_json_path, all_entries)
    write_manifest_csv(manifest_csv_path, all_entries)

    print(f"\n完成。共处理 {len(archive_files)} 个压缩文件。")
    print(f"manifest.json: {manifest_json_path}")
    print(f"manifest.csv:  {manifest_csv_path}")
    print(f"process_log.txt: {log_path}")


if __name__ == "__main__":
    main()
