#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - Core
核心协调模块
"""

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# 导入子模块
from .l1_index import scan_all_indices, search_l1_index
from .l2_metadata import search_l2_metadata
from .l3_content import search_l3_content
from .semantic import search_semantic
from .ranking import merge_and_rank_results, merge_and_rank_results_hybrid

# 导入 logger
try:
    from ..lib.logger import get_logger

    logger = get_logger("search_journals")
except ImportError:
    import logging

    logger = logging.getLogger("search_journals")


def hierarchical_search(
    query: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mood: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    level: int = 3,
    use_index: bool = False,
    semantic: bool = False,
    semantic_weight: float = 0.4,
    fts_weight: float = 0.6,
) -> Dict[str, Any]:
    """
    执行分层级搜索

    Args:
        level: 1=仅索引, 2=索引+元数据, 3=完整三层
        use_index: 是否使用 FTS 索引加速 L3 搜索
        semantic: 是否启用语义搜索（混合 BM25 + 向量相似度）
        semantic_weight: 语义搜索得分权重（默认 0.4）
        fts_weight: FTS 搜索得分权重（默认 0.6）
    """
    result: Dict[str, Any] = {
        "success": True,
        "query_params": {
            "query": query,
            "topic": topic,
            "project": project,
            "tags": tags,
            "mood": mood,
            "people": people,
            "date_from": date_from,
            "date_to": date_to,
            "level": level,
            "semantic": semantic,
        },
        "l1_results": [],
        "l2_results": [],
        "l3_results": [],
        "semantic_results": [],
        "total_found": 0,
        "performance": {},
    }

    start_time = time.time()

    # L1: 索引层
    l1_start = time.time()

    if topic:
        result["l1_results"].extend(search_l1_index("topic", topic))
    if project:
        result["l1_results"].extend(search_l1_index("project", project))
    if tags:
        for tag in tags:
            result["l1_results"].extend(search_l1_index("tag", tag))

    # 当无过滤条件但指定 level=1 时，扫描所有索引文件
    if level == 1 and not topic and not project and not tags:
        result["l1_results"].extend(scan_all_indices())

    # 去重
    seen_paths = set()
    unique_l1 = []
    for r in result["l1_results"]:
        if r["path"] not in seen_paths:
            seen_paths.add(r["path"])
            unique_l1.append(r)
    result["l1_results"] = unique_l1

    result["performance"]["l1_time_ms"] = round((time.time() - l1_start) * 1000, 2)

    if level == 1:
        result["total_found"] = len(result["l1_results"])
        result["performance"]["total_time_ms"] = round(
            (time.time() - start_time) * 1000, 2
        )
        return result

    # L2: 元数据层
    l2_start = time.time()

    result["l2_results"] = search_l2_metadata(
        date_from=date_from,
        date_to=date_to,
        location=location,
        weather=weather,
        topic=topic,
        project=project,
        tags=tags,
        mood=mood,
        people=people,
        query=query,  # 传递 query，L2 层也会过滤元数据
    )

    result["performance"]["l2_time_ms"] = round((time.time() - l2_start) * 1000, 2)

    if level == 2:
        result["total_found"] = len(result["l2_results"])
        result["performance"]["total_time_ms"] = round(
            (time.time() - start_time) * 1000, 2
        )
        return result

    # L3: 内容层
    l3_start = time.time()
    l3_results = []  # 本地变量存储结果

    if query:
        # 处理多关键词：将空格分隔转换为 FTS5 OR 语法
        # "思考 反思" -> "思考 OR 反思"
        if (
            query
            and " " in query
            and "OR" not in query.upper()
            and "AND" not in query.upper()
        ):
            keywords = [k.strip() for k in query.split() if k.strip()]
            if len(keywords) > 1:
                fts_query = " OR ".join(keywords)
            else:
                fts_query = query
        else:
            fts_query = query

        # 尝试使用 FTS 索引（如果可用且启用）
        if use_index:
            try:
                from lib.config import USER_DATA_DIR
                from lib.search_index import search_fts

                fts_results = search_fts(fts_query, date_from, date_to, limit=100)
                if fts_results:
                    # 转换格式以兼容现有结果
                    l3_results = [
                        {
                            "path": str(USER_DATA_DIR / r["path"]),
                            "rel_path": r["path"],
                            "date": r["date"],
                            "title": r["title"],
                            "snippet": r.get("snippet", ""),
                            "match_count": 1,
                            "source": "fts_index",
                            "relevance": r.get("relevance", 50),  # 传递 BM25 相关性分数
                        }
                        for r in fts_results
                    ]
                    logger.debug(f"FTS found {len(l3_results)} results")
            except (ImportError, OSError) as e:
                logger.debug(f"FTS error: {e}")
                # FTS 失败时回退到文件系统扫描
                pass

        # 如果没有 FTS 结果，使用传统文件系统扫描
        if not l3_results:
            candidate_paths = [
                r["path"] for r in result["l1_results"] + result["l2_results"]
            ]
            l3_results = search_l3_content(
                query, candidate_paths if candidate_paths else None
            )
            logger.debug(f"File scan found {len(l3_results)} results")

    result["l3_results"] = l3_results

    result["performance"]["l3_time_ms"] = round((time.time() - l3_start) * 1000, 2)

    # 语义搜索层（当启用时）
    semantic_results = []
    if semantic and query:
        semantic_start = time.time()
        semantic_results = search_semantic(query, date_from or "", date_to or "")
        if semantic_results:
            logger.debug(f"Semantic found {len(semantic_results)} results")
        result["performance"]["semantic_time_ms"] = round(
            (time.time() - semantic_start) * 1000, 2
        )

    result["semantic_results"] = semantic_results

    # 合并结果（按相关性排序）
    if semantic and semantic_results:
        # 使用混合排序（BM25 + 语义）
        result["merged_results"] = merge_and_rank_results_hybrid(
            result["l1_results"],
            result["l2_results"],
            result["l3_results"],
            semantic_results,
            query,
            fts_weight=fts_weight,
            semantic_weight=semantic_weight,
        )
    else:
        # 使用传统排序
        result["merged_results"] = merge_and_rank_results(
            result["l1_results"], result["l2_results"], result["l3_results"], query
        )
    result["total_found"] = len(result["merged_results"])
    result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)

    return result
