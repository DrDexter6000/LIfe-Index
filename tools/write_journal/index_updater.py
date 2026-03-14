#!/usr/bin/env python3
"""
Life Index - Write Journal Tool - Index Updater
索引更新模块
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# 导入配置 - 使用绝对导入确保正确的 USER_DATA_DIR
import sys

TOOLS_LIB_DIR = Path(__file__).parent.parent / "lib"
if str(TOOLS_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_LIB_DIR))

from config import JOURNALS_DIR, BY_TOPIC_DIR, USER_DATA_DIR

# Define write_journal directory for subprocess calls
WRITE_JOURNAL_DIR = Path(__file__).parent


def update_topic_index(
    topic: Any, journal_path: Path, data: Dict[str, Any]
) -> List[Path]:
    """更新主题索引文件 - 支持单个主题或主题列表"""
    if not topic:
        return []

    # 统一处理为列表
    if isinstance(topic, str):
        topics = [topic]
    elif isinstance(topic, list):
        topics = topic
    else:
        return []

    date_str = data.get("date", "")[:10]
    title = data.get("title", "无标题")
    rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

    entry = f"- [{date_str}] [{title}]({rel_path})"

    updated = []
    for t in topics:
        if not t:
            continue
        BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)
        index_file = BY_TOPIC_DIR / f"主题_{t}.md"

        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            if entry not in content:
                with open(index_file, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
        else:
            with open(index_file, "w", encoding="utf-8") as f:
                f.write(f"# 主题: {t}\n\n")
                f.write(entry + "\n")

        updated.append(index_file)

    return updated


def update_project_index(
    project: str, journal_path: Path, data: Dict[str, Any]
) -> Optional[Path]:
    """更新项目索引文件"""
    if not project:
        return None

    BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)
    index_file = BY_TOPIC_DIR / f"项目_{project}.md"

    date_str = data.get("date", "")[:10]
    title = data.get("title", "无标题")
    rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

    entry = f"- [{date_str}] [{title}]({rel_path})"

    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        if entry not in content:
            with open(index_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
    else:
        with open(index_file, "w", encoding="utf-8") as f:
            f.write(f"# 项目: {project}\n\n")
            f.write(entry + "\n")

    return index_file


def update_tag_indices(
    tags: List[str], journal_path: Path, data: Dict[str, Any]
) -> List[Path]:
    """更新标签索引文件"""
    updated = []

    for tag in tags:
        if not tag:
            continue

        BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)
        index_file = BY_TOPIC_DIR / f"标签_{tag}.md"

        date_str = data.get("date", "")[:10]
        title = data.get("title", "无标题")
        rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

        entry = f"- [{date_str}] [{title}]({rel_path})"

        if index_file.exists():
            content = index_file.read_text(encoding="utf-8")
            if entry not in content:
                with open(index_file, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
        else:
            with open(index_file, "w", encoding="utf-8") as f:
                f.write(f"# 标签: {tag}\n\n")
                f.write(entry + "\n")

        updated.append(index_file)

    return updated


def update_monthly_abstract(
    year: int, month: int, dry_run: bool = False
) -> Dict[str, Any]:
    """
    更新月度摘要文件（调用 generate_abstract.py 工具）

    Args:
        year: 年份
        month: 月份
        dry_run: 是否为模拟运行

    Returns:
        {
            "abstract_path": str,
            "journal_count": int,
            "updated": bool
        }
    """
    result = {"abstract_path": None, "journal_count": 0, "updated": False}

    month_str = f"{year}-{month:02d}"
    abstract_path = (
        JOURNALS_DIR
        / str(year)
        / f"{month:02d}"
        / f"monthly_report_{year}-{month:02d}.md"
    )

    # 构建命令
    cmd = [
        sys.executable,
        str(WRITE_JOURNAL_DIR / "generate_abstract.py"),
        "--month",
        month_str,
        "--json",
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        # 调用 generate_abstract.py
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=30
        )

        if proc.returncode == 0:
            output = json.loads(proc.stdout)
            if output and len(output) > 0:
                data = output[0]
                result["abstract_path"] = data.get("abstract_path")
                result["journal_count"] = data.get("journal_count", 0)
                result["updated"] = data.get("updated", False)
        else:
            result["error"] = proc.stderr

    except (OSError, IOError, RuntimeError) as e:
        result["error"] = str(e)
        result["error"] = str(e)

    return result
