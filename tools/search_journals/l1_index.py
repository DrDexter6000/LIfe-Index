#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - L1 Index
一级索引搜索模块（by-topic索引）
"""

import re
from pathlib import Path
from typing import Any, Dict, List

# 导入配置 (relative imports from tools/lib)
from ..lib.config import BY_TOPIC_DIR, USER_DATA_DIR, PROJECT_ROOT


def scan_all_indices() -> List[Dict[str, Any]]:
    """
    扫描所有索引文件（L1 层全索引浏览）

    Returns:
        所有索引条目合并后的列表
    """
    results = []
    seen_paths = set()

    if not BY_TOPIC_DIR.exists():
        return results

    # 扫描所有索引文件
    for index_file in BY_TOPIC_DIR.glob("*.md"):
        try:
            content = index_file.read_text(encoding="utf-8")
            # 解析索引条目: - [YYYY-MM-DD 标题](路径)
            pattern = r"- \[(\d{4}-\d{2}-\d{2})\s+([^\]]+)\]\(([^)]+)\)"
            matches = re.findall(pattern, content)

            for date_str, title, path in matches:
                full_path = str(USER_DATA_DIR / path)
                if full_path not in seen_paths:
                    seen_paths.add(full_path)
                    results.append(
                        {
                            "date": date_str,
                            "title": title,
                            "path": full_path,
                            "rel_path": path,
                            "source": "index:all",
                        }
                    )
        except (OSError, IOError):
            continue

    return results


def search_l1_index(query_type: str, query_value: str) -> List[Dict[str, Any]]:
    """
    L1: 索引层搜索 - 快速定位可能包含目标的日志

    Args:
        query_type: 'topic', 'project', 'tag'
        query_value: 查询值
    """
    results = []

    if query_type == "topic":
        index_file = BY_TOPIC_DIR / f"主题_{query_value}.md"
    elif query_type == "project":
        index_file = BY_TOPIC_DIR / f"项目_{query_value}.md"
    elif query_type == "tag":
        index_file = BY_TOPIC_DIR / f"标签_{query_value}.md"
    else:
        return results

    if not index_file.exists():
        return results

    content = index_file.read_text(encoding="utf-8")

    # 解析索引条目: - [YYYY-MM-DD] [标题](路径)
    pattern = r"- \[(\d{4}-\d{2}-\d{2})\] \[(.*?)\]\((.*?)\)"
    matches = re.findall(pattern, content)

    for date_str, title, path in matches:
        full_path = PROJECT_ROOT / path
        results.append(
            {
                "date": date_str,
                "title": title,
                "path": str(full_path),
                "rel_path": path,
                "source": f"index:{query_type}={query_value}",
            }
        )

    return results
