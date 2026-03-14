#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - L2 Metadata
二级元数据搜索模块（frontmatter扫描）

性能优化：使用SQLite元数据缓存避免重复解析
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# 导入配置 (relative imports from tools/lib)
from ..lib.config import JOURNALS_DIR, USER_DATA_DIR
from ..lib.metadata_cache import (
    get_or_update_metadata,
    get_all_cached_metadata,
    init_metadata_cache,
    update_cache_for_all_journals,
    get_cache_stats,
)


# 是否启用缓存（可通过环境变量控制）
ENABLE_CACHE = os.environ.get("LIFE_INDEX_L2_CACHE", "1") == "1"


def _matches_filters(
    metadata: Dict[str, Any],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mood: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    query: Optional[str] = None,
) -> bool:
    """检查元数据是否匹配过滤条件"""
    # 日期过滤
    file_date = metadata.get("date", "")
    if date_from and file_date < date_from:
        return False
    if date_to and file_date > date_to:
        return False

    # 地点过滤
    if location and location.lower() not in metadata.get("location", "").lower():
        return False

    # 天气过滤
    if weather and weather.lower() not in metadata.get("weather", "").lower():
        return False

    # Topic过滤（支持数组或字符串）
    if topic:
        file_topics = metadata.get("topic", [])
        if isinstance(file_topics, str):
            file_topics = [file_topics]
        if topic not in file_topics:
            return False

    # Project过滤（支持数组或字符串）
    if project:
        file_projects = metadata.get("project", [])
        if isinstance(file_projects, str):
            file_projects = [file_projects]
        if project not in file_projects:
            return False

    # Tags过滤
    if tags:
        file_tags = metadata.get("tags", [])
        if not isinstance(file_tags, list):
            file_tags = [file_tags]
        if not any(tag in file_tags for tag in tags):
            return False

    # Mood过滤
    if mood:
        file_moods = metadata.get("mood", [])
        if isinstance(file_moods, str):
            file_moods = [file_moods]
        if not isinstance(file_moods, list):
            file_moods = []
        if not any(m in file_moods for m in mood):
            return False

    # People过滤
    if people:
        file_people = metadata.get("people", [])
        if isinstance(file_people, str):
            file_people = [file_people]
        if not isinstance(file_people, list):
            file_people = []
        if not any(p in file_people for p in people):
            return False

    # Query 过滤：当指定 query 时，要求元数据包含该关键词
    if query:
        query_lower = query.lower()
        title = metadata.get("title", "").lower()
        abstract = (
            metadata.get("abstract", "").lower()
            if isinstance(metadata.get("abstract"), str)
            else ""
        )
        file_tags = metadata.get("tags", [])
        tags_str = (
            " ".join(file_tags).lower()
            if isinstance(file_tags, list)
            else str(file_tags).lower()
        )

        # 检查 title/abstract/tags 是否包含 query
        if (
            query_lower not in title
            and query_lower not in abstract
            and query_lower not in tags_str
        ):
            return False

    return True


def _search_with_cache(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mood: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """使用缓存的元数据进行搜索（高性能路径）"""
    results = []

    # 获取所有缓存的元数据
    cached_entries = get_all_cached_metadata()

    for entry in cached_entries:
        # 使用通用过滤函数
        if not _matches_filters(
            entry,
            date_from=date_from,
            date_to=date_to,
            location=location,
            weather=weather,
            topic=topic,
            project=project,
            tags=tags,
            mood=mood,
            people=people,
            query=query,
        ):
            continue

        # 匹配成功
        file_path = Path(entry["file_path"])
        try:
            rel_path = os.path.relpath(file_path, USER_DATA_DIR).replace("\\", "/")
        except ValueError:
            rel_path = str(file_path).replace("\\", "/")

        results.append(
            {
                "date": entry["date"],
                "title": entry.get("title", "无标题"),
                "path": str(file_path),
                "rel_path": rel_path,
                "metadata": entry["metadata"],
                "source": "metadata_cache",
            }
        )

    return results


def _search_filesystem(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mood: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """使用文件系统扫描搜索（Fallback路径）"""
    results = []

    if not JOURNALS_DIR.exists():
        return results

    # 遍历所有日志文件
    for year_dir in JOURNALS_DIR.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue

        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue

            for journal_file in month_dir.glob("*.md"):
                try:
                    # 获取元数据（使用缓存）
                    entry = get_or_update_metadata(journal_file)
                    if not entry:
                        continue

                    # 使用通用过滤函数
                    if not _matches_filters(
                        entry,
                        date_from=date_from,
                        date_to=date_to,
                        location=location,
                        weather=weather,
                        topic=topic,
                        project=project,
                        tags=tags,
                        mood=mood,
                        people=people,
                        query=query,
                    ):
                        continue

                    # 匹配成功
                    try:
                        rel_path = os.path.relpath(journal_file, USER_DATA_DIR).replace(
                            "\\", "/"
                        )
                    except ValueError:
                        rel_path = str(journal_file).replace("\\", "/")

                    results.append(
                        {
                            "date": entry["date"],
                            "title": entry.get("title", "无标题"),
                            "path": str(journal_file),
                            "rel_path": rel_path,
                            "metadata": entry["metadata"],
                            "source": "filesystem_scan",
                        }
                    )

                except (IOError, OSError, ValueError) as e:
                    continue

    return results


def search_l2_metadata(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mood: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    query: Optional[str] = None,
    use_cache: bool = True,
) -> List[Dict[str, Any]]:
    """
    L2: 元数据层搜索

    性能优化：使用SQLite元数据缓存避免重复解析
    缓存策略：
    1. 优先使用缓存表中的数据
    2. 缓存未命中时解析文件并更新缓存
    3. 文件变更检测：通过mtime+size判断缓存是否有效

    Args:
        query: 当指定 query 时，额外过滤 title/abstract/tags 包含该关键词的日志
        use_cache: 是否使用缓存（默认True）
    """
    # 如果不使用缓存，直接扫描文件系统
    if not use_cache or not ENABLE_CACHE:
        return _search_filesystem(
            date_from=date_from,
            date_to=date_to,
            location=location,
            weather=weather,
            topic=topic,
            project=project,
            tags=tags,
            mood=mood,
            people=people,
            query=query,
        )

    # 尝试使用缓存搜索
    try:
        # 检查缓存是否存在且有数据
        stats = get_cache_stats()
        if stats["total_entries"] > 0:
            # 使用缓存搜索
            return _search_with_cache(
                date_from=date_from,
                date_to=date_to,
                location=location,
                weather=weather,
                topic=topic,
                project=project,
                tags=tags,
                mood=mood,
                people=people,
                query=query,
            )
    except (IOError, OSError):
        pass

    # 缓存不可用或为空，回退到文件系统扫描
    return _search_filesystem(
        date_from=date_from,
        date_to=date_to,
        location=location,
        weather=weather,
        topic=topic,
        project=project,
        tags=tags,
        mood=mood,
        people=people,
        query=query,
    )


def warm_cache(progress_callback: Optional[callable] = None) -> Dict[str, int]:
    """
    预热缓存：扫描所有日志文件并更新缓存

    建议在以下场景调用：
    - 首次启用缓存
    - 定期维护（如每周）
    - 批量导入日志后

    Returns:
        {"updated": 更新数, "skipped": 跳过数, "errors": 错误数}
    """
    return update_cache_for_all_journals(progress_callback)


def get_l2_cache_stats() -> Dict[str, Any]:
    """获取L2缓存统计信息"""
    return get_cache_stats()


def invalidate_l2_cache() -> None:
    """使L2缓存失效（下次搜索将重新构建缓存）"""
    from lib.metadata_cache import invalidate_cache

    invalidate_cache()
