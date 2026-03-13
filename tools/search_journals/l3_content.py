#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - L3 Content
三级内容搜索模块（全文搜索）
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# 导入配置
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from lib.config import JOURNALS_DIR, USER_DATA_DIR

from .utils import parse_frontmatter


def search_l3_content(
    query: str, paths: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    L3: 内容层搜索 - 全文检索

    Args:
        query: 搜索关键词
        paths: 限定搜索范围（如果为None则搜索全部）
    """
    results = []
    query_lower = query.lower()

    if paths:
        files_to_search = [Path(p) for p in paths if Path(p).exists()]
    else:
        files_to_search = []
        if JOURNALS_DIR.exists():
            for year_dir in JOURNALS_DIR.iterdir():
                if year_dir.is_dir() and year_dir.name.isdigit():
                    for month_dir in year_dir.iterdir():
                        if month_dir.is_dir():
                            files_to_search.extend(month_dir.glob("*.md"))

    for journal_file in files_to_search:
        try:
            content = journal_file.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(content)

            # 在标题中搜索
            title_match = False
            title = metadata.get("title", "")
            if query_lower in title.lower():
                title_match = True

            # 在正文中搜索
            body_matches = []
            lines = body.split("\n")
            for i, line in enumerate(lines, 1):
                if query_lower in line.lower():
                    # 提取上下文
                    start = max(0, i - 2)
                    end = min(len(lines), i + 1)
                    context = "\n".join(lines[start:end])
                    body_matches.append({"line": i, "context": context.strip()})

            if title_match or body_matches:
                # 计算相对路径（基于 USER_DATA_DIR，避免跨驱动器问题）
                try:
                    rel_path = os.path.relpath(journal_file, USER_DATA_DIR).replace(
                        "\\", "/"
                    )
                except ValueError:
                    # 如果无法计算相对路径，使用绝对路径
                    rel_path = str(journal_file).replace("\\", "/")

                results.append(
                    {
                        "date": metadata.get("date", "")[:10],
                        "title": title or "无标题",
                        "path": str(journal_file),
                        "rel_path": rel_path,
                        "title_match": title_match,
                        "body_matches": body_matches,
                        "match_count": len(body_matches) + (1 if title_match else 0),
                        "source": "content_search",
                    }
                )

        except (OSError, IOError):
            continue

    # 按匹配度排序
    results.sort(key=lambda x: x["match_count"], reverse=True)

    return results
