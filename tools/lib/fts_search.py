#!/usr/bin/env python3
"""
Life Index - FTS Search Module
FTS5 全文搜索功能

从 search_index.py 提取的搜索逻辑。
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_FTS_MATCH_QUERY_CHARS = 1024
MAX_FTS_MATCH_QUERY_TOKENS = 32

from .search_constants import (
    FTS_LIMIT,
    FTS_MIN_RELEVANCE,
    FTS_SNIPPET_TOKENS,
    HIGH_FREQUENCY_MIN_RELEVANCE,
    HIGH_FREQUENCY_TERMS,
    BM25_RELEVANCE_BASE,
    BM25_RELEVANCE_MULTIPLIER,
)


def _effective_min_relevance(query: str, min_relevance: int) -> int:
    """Return the effective FTS threshold for a query.

    High-frequency project terms use a stricter default threshold, but explicit
    caller overrides still take precedence.

    B-5: Uses substring containment instead of exact match, so queries like
    "Life Index 2026" or "OpenClaw cron" also trigger the stricter threshold.
    """
    normalized_query = " ".join(str(query).lower().split())
    if min_relevance != FTS_MIN_RELEVANCE:
        return min_relevance
    if any(term in normalized_query for term in HIGH_FREQUENCY_TERMS):
        return HIGH_FREQUENCY_MIN_RELEVANCE
    return min_relevance


def _bounded_match_query(query: str) -> str:
    """Bound pathological FTS MATCH input before it reaches SQLite."""
    tokens = str(query).split()
    if len(tokens) > MAX_FTS_MATCH_QUERY_TOKENS:
        return " ".join(tokens[:MAX_FTS_MATCH_QUERY_TOKENS])
    if len(query) > MAX_FTS_MATCH_QUERY_CHARS:
        return query[:MAX_FTS_MATCH_QUERY_CHARS]
    return query


def _parse_json_field(value: Any) -> list[str]:
    """解析 JSON 字段（可能是 JSON 字符串或已经是列表）"""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def search_fts(
    fts_db_path: Path,
    query: str,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = FTS_LIMIT,
    min_relevance: int = FTS_MIN_RELEVANCE,
) -> list[dict[str, Any]]:
    """
    使用 FTS5 搜索日志（带 BM25 相关性排序）

    Args:
        fts_db_path: FTS 数据库路径
        query: 搜索关键词（支持 FTS5 语法：AND, OR, NOT, * 通配符）
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        limit: 最大返回结果数
        min_relevance: 最低相关性阈值（0-100）

    Returns:
        搜索结果列表（按 BM25 相关性排序，分数越高越相关）
    """
    results: list[dict[str, Any]] = []
    effective_min_relevance = _effective_min_relevance(query, min_relevance)
    match_query = _bounded_match_query(query)

    try:
        if not fts_db_path.exists():
            # 索引不存在，返回空结果（调用方应回退到文件系统扫描）
            return results

        conn = sqlite3.connect(str(fts_db_path))
        cursor = conn.cursor()

        # 尝试使用新版本的完整查询（包含 mood/people 列）
        # 如果旧索引缺少这些列，会抛出 sqlite3.OperationalError
        try:
            # Column layout (v2 schema): path(0), title(1/UNINDEXED),
            # title_segmented(2), content(3), date(4), location(5),
            # weather(6), topic(7), project(8), tags(9), mood(10), people(11)
            # BM25 weights: path=1.0, title_segmented=1.0, content=1.0,
            #   date=0.5, location=0.5, weather=0.5, topic=0.5,
            #   project=0.5, tags=0.5, mood=0.5, people=0.5
            # Note: UNINDEXED columns (title, file_hash, modified_time)
            #   are excluded from BM25 weight list.
            sql = """
                SELECT path, title, date, location, weather, topic, project, tags, mood, people,
                       snippet(journals, 3, '<mark>', '</mark>', '...', ?) as snippet,
                       bm25(journals, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5) as rank
                FROM journals
                WHERE journals MATCH ?
            """
            params = [FTS_SNIPPET_TOKENS, match_query]

            # 添加日期过滤
            if date_from:
                sql += " AND date >= ?"
                params.append(date_from)
            if date_to:
                sql += " AND date <= ?"
                params.append(date_to)

            # 按 BM25 分数排序（分数越低表示越相关）
            sql += " ORDER BY rank ASC"
            # limit <= 0 means "materialize the full admitted set" (Phase 1
            # CHARTER §1.11): no SQL LIMIT cap, so retrieval is not silently
            # truncated before pagination. A Python-level fail-closed bound
            # (FTS_MAX_RETRIEVAL_BOUND) in the keyword pipeline guards memory.
            if limit and limit > 0:
                sql += f" LIMIT {limit}"

            cursor.execute(sql, params)

            for row in cursor.fetchall():
                # BM25 分数转换为匹配度百分比（分数越低越相关）
                # 典型 BM25 分数范围：-10 到 10，负数表示高度相关
                bm25_score = row[11] if row[11] is not None else 0
                # 转换公式：将 BM25 分数映射到 0-100 的匹配度
                # 见 search_constants.py ADR-009
                relevance = max(
                    0,
                    min(
                        100,
                        int(BM25_RELEVANCE_BASE - bm25_score * BM25_RELEVANCE_MULTIPLIER),
                    ),
                )
                if relevance < effective_min_relevance:
                    continue

                results.append(
                    {
                        "path": row[0],
                        "title": row[1],
                        "date": row[2],
                        "location": row[3] or "",
                        "weather": row[4] or "",
                        "topic": _parse_json_field(row[5]) if row[5] else [],
                        "project": row[6] or "",
                        "tags": _parse_json_field(row[7]) if row[7] else [],
                        "mood": _parse_json_field(row[8]) if row[8] else [],
                        "people": _parse_json_field(row[9]) if row[9] else [],
                        "snippet": row[10],
                        "bm25_score": bm25_score,
                        "relevance": relevance,
                        "source": "fts",
                    }
                )

        except sqlite3.OperationalError as e:
            # 旧索引缺少 mood/people 列，使用简化查询
            logger.warning("FTS primary query failed (old schema?), falling back: %s", e)
            sql = """
                SELECT path, title, date, location, weather, topic, project, tags,
                       snippet(journals, 3, '<mark>', '</mark>', '...', ?) as snippet,
                       bm25(journals, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5) as rank
                FROM journals
                WHERE journals MATCH ?
            """
            params = [FTS_SNIPPET_TOKENS, match_query]

            if date_from:
                sql += " AND date >= ?"
                params.append(date_from)
            if date_to:
                sql += " AND date <= ?"
                params.append(date_to)

            sql += " ORDER BY rank ASC"
            if limit and limit > 0:
                sql += f" LIMIT {limit}"

            cursor.execute(sql, params)

            for row in cursor.fetchall():
                bm25_score = row[9] if row[9] is not None else 0
                relevance = max(
                    0,
                    min(
                        100,
                        int(BM25_RELEVANCE_BASE - bm25_score * BM25_RELEVANCE_MULTIPLIER),
                    ),
                )
                if relevance < effective_min_relevance:
                    continue

                results.append(
                    {
                        "path": row[0],
                        "title": row[1],
                        "date": row[2],
                        "location": row[3] or "",
                        "weather": row[4] or "",
                        "topic": _parse_json_field(row[5]) if row[5] else [],
                        "project": row[6] or "",
                        "tags": _parse_json_field(row[7]) if row[7] else [],
                        "mood": [],
                        "people": [],
                        "snippet": row[8],
                        "bm25_score": bm25_score,
                        "relevance": relevance,
                        "source": "fts",
                    }
                )

        conn.close()

    except (sqlite3.Error, OSError) as e:
        logger.error("FTS search error: %s", e)

    return results
