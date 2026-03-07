#!/usr/bin/env python3
"""
Life Index - Search Journals Tool
分层级检索日志（L1索引→L2元数据→L3内容）

Usage:
    python search_journals.py --query "关键词"
    python search_journals.py --topic work --project LobsterAI
    python search_journals.py --date-from 2026-01-01 --date-to 2026-03-04
    python search_journals.py --level 3 --query "深度学习"
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import fnmatch

# 导入共享配置
sys.path.insert(0, str(Path(__file__).parent))
from lib.config import JOURNALS_DIR, BY_TOPIC_DIR, USER_DATA_DIR, PROJECT_ROOT


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """解析 YAML frontmatter，返回 (metadata, body)"""
    if not content.startswith('---'):
        return {}, content

    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content

    fm_text = parts[1].strip()
    body = parts[2].strip()

    metadata = {}
    for line in fm_text.split('\n'):
        line = line.strip()
        if ':' in line and not line.startswith('#'):
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # 处理列表格式 [item1, item2]
            if value.startswith('[') and value.endswith(']'):
                value = [v.strip().strip('"\'') for v in value[1:-1].split(',') if v.strip()]

            metadata[key] = value

    return metadata, body


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
            content = index_file.read_text(encoding='utf-8')
            # 解析索引条目: - [YYYY-MM-DD 标题](路径)
            pattern = r'- \[(\d{4}-\d{2}-\d{2})\s+([^\]]+)\]\(([^)]+)\)'
            matches = re.findall(pattern, content)

            for date_str, title, path in matches:
                full_path = str(USER_DATA_DIR / path)
                if full_path not in seen_paths:
                    seen_paths.add(full_path)
                    results.append({
                        "date": date_str,
                        "title": title,
                        "path": full_path,
                        "rel_path": path,
                        "source": "index:all"
                    })
        except Exception:
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

    if query_type == 'topic':
        index_file = BY_TOPIC_DIR / f"主题_{query_value}.md"
    elif query_type == 'project':
        index_file = BY_TOPIC_DIR / f"项目_{query_value}.md"
    elif query_type == 'tag':
        index_file = BY_TOPIC_DIR / f"标签_{query_value}.md"
    else:
        return results

    if not index_file.exists():
        return results

    content = index_file.read_text(encoding='utf-8')

    # 解析索引条目: - [YYYY-MM-DD] [标题](路径)
    pattern = r'- \[(\d{4}-\d{2}-\d{2})\] \[(.*?)\]\((.*?)\)'
    matches = re.findall(pattern, content)

    for date_str, title, path in matches:
        full_path = PROJECT_ROOT / path
        results.append({
            "date": date_str,
            "title": title,
            "path": str(full_path),
            "rel_path": path,
            "source": f"index:{query_type}={query_value}"
        })

    return results


def search_l2_metadata(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    L2: 元数据层搜索 - 扫描所有日志的 frontmatter

    Args:
        query: 当指定 query 时，额外过滤 title/abstract/tags 包含该关键词的日志
    """
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
                    content = journal_file.read_text(encoding='utf-8')
                    metadata, body = parse_frontmatter(content)

                    if not metadata:
                        continue

                    # 日期过滤
                    file_date = metadata.get('date', '')[:10]
                    if date_from and file_date < date_from:
                        continue
                    if date_to and file_date > date_to:
                        continue

                    # 地点过滤
                    if location and location.lower() not in metadata.get('location', '').lower():
                        continue

                    # 天气过滤
                    if weather and weather.lower() not in metadata.get('weather', '').lower():
                        continue

                    # Topic过滤（支持数组或字符串）
                    if topic:
                        file_topics = metadata.get('topic', [])
                        if isinstance(file_topics, str):
                            file_topics = [file_topics]
                        if topic not in file_topics:
                            continue

                    # Project过滤（支持数组或字符串）
                    if project:
                        file_projects = metadata.get('project', [])
                        if isinstance(file_projects, str):
                            file_projects = [file_projects]
                        if project not in file_projects:
                            continue

                    # Tags过滤
                    if tags:
                        file_tags = metadata.get('tags', [])
                        if not isinstance(file_tags, list):
                            file_tags = [file_tags]
                        if not any(tag in file_tags for tag in tags):
                            continue

                    # Query 过滤：当指定 query 时，要求元数据包含该关键词
                    if query:
                        query_lower = query.lower()
                        title = metadata.get('title', '').lower()
                        abstract = metadata.get('abstract', '').lower() if isinstance(metadata.get('abstract'), str) else ''
                        file_tags = metadata.get('tags', [])
                        tags_str = ' '.join(file_tags).lower() if isinstance(file_tags, list) else str(file_tags).lower()

                        # 检查 title/abstract/tags 是否包含 query
                        if query_lower not in title and query_lower not in abstract and query_lower not in tags_str:
                            continue  # 元数据不匹配，跳过

                    # 匹配成功
                    try:
                        rel_path = os.path.relpath(journal_file, USER_DATA_DIR).replace("\\", "/")
                    except ValueError:
                        rel_path = str(journal_file).replace("\\", "/")

                    results.append({
                        "date": file_date,
                        "title": metadata.get('title', '无标题'),
                        "path": str(journal_file),
                        "rel_path": rel_path,
                        "metadata": metadata,
                        "source": "metadata_scan"
                    })

                except Exception as e:
                    continue

    return results


def search_l3_content(query: str, paths: Optional[List[str]] = None) -> List[Dict[str, Any]]:
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
            content = journal_file.read_text(encoding='utf-8')
            metadata, body = parse_frontmatter(content)


            # 在标题中搜索
            title_match = False
            title = metadata.get('title', '')
            if query_lower in title.lower():
                title_match = True

            # 在正文中搜索
            body_matches = []
            lines = body.split('\n')
            for i, line in enumerate(lines, 1):
                if query_lower in line.lower():
                    # 提取上下文
                    start = max(0, i - 2)
                    end = min(len(lines), i + 1)
                    context = '\n'.join(lines[start:end])
                    body_matches.append({
                        "line": i,
                        "context": context.strip()
                    })

            if title_match or body_matches:
                # 计算相对路径（基于 USER_DATA_DIR，避免跨驱动器问题）
                try:
                    rel_path = os.path.relpath(journal_file, USER_DATA_DIR).replace("\\", "/")
                except ValueError:
                    # 如果无法计算相对路径，使用绝对路径
                    rel_path = str(journal_file).replace("\\", "/")

                results.append({
                    "date": metadata.get('date', '')[:10],
                    "title": title or '无标题',
                    "path": str(journal_file),
                    "rel_path": rel_path,
                    "title_match": title_match,
                    "body_matches": body_matches,
                    "match_count": len(body_matches) + (1 if title_match else 0),
                    "source": "content_search"
                })

        except Exception as e:
            continue

    # 按匹配度排序
    results.sort(key=lambda x: x["match_count"], reverse=True)

    return results


def hierarchical_search(
    query: Optional[str] = None,
    topic: Optional[str] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    level: int = 3,
    use_index: bool = False,
    semantic: bool = False,
    semantic_weight: float = 0.4,
    fts_weight: float = 0.6
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
    result = {
        "success": True,
        "query_params": {
            "query": query,
            "topic": topic,
            "project": project,
            "tags": tags,
            "date_from": date_from,
            "date_to": date_to,
            "level": level,
            "semantic": semantic
        },
        "l1_results": [],
        "l2_results": [],
        "l3_results": [],
        "semantic_results": [],
        "total_found": 0,
        "performance": {}
    }

    import time
    start_time = time.time()

    # L1: 索引层
    l1_start = time.time()

    if topic:
        result["l1_results"].extend(search_l1_index('topic', topic))
    if project:
        result["l1_results"].extend(search_l1_index('project', project))
    if tags:
        for tag in tags:
            result["l1_results"].extend(search_l1_index('tag', tag))

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
        result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
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
        query=query  # 传递 query，L2 层也会过滤元数据
    )

    result["performance"]["l2_time_ms"] = round((time.time() - l2_start) * 1000, 2)

    if level == 2:
        result["total_found"] = len(result["l2_results"])
        result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
        return result

    # L3: 内容层
    l3_start = time.time()
    l3_results = []  # 本地变量存储结果

    if query:
        # 处理多关键词：将空格分隔转换为 FTS5 OR 语法
        # "思考 反思" -> "思考 OR 反思"
        if query and ' ' in query and 'OR' not in query.upper() and 'AND' not in query.upper():
            keywords = [k.strip() for k in query.split() if k.strip()]
            if len(keywords) > 1:
                fts_query = ' OR '.join(keywords)
            else:
                fts_query = query
        else:
            fts_query = query

        # 尝试使用 FTS 索引（如果可用且启用）
        if use_index:
            try:
                from lib.search_index import search_fts
                fts_results = search_fts(fts_query, date_from, date_to, limit=100)
                if fts_results:
                    # 转换格式以兼容现有结果
                    l3_results = [{
                        "path": str(USER_DATA_DIR / r["path"]),
                        "rel_path": r["path"],
                        "date": r["date"],
                        "title": r["title"],
                        "snippet": r.get("snippet", ""),
                        "match_count": 1,
                        "source": "fts_index",
                        "relevance": r.get("relevance", 50)  # 传递 BM25 相关性分数
                    } for r in fts_results]
                    print(f"Debug: FTS found {len(l3_results)} results", file=sys.stderr)
            except Exception as e:
                print(f"Debug: FTS error: {e}", file=sys.stderr)
                # FTS 失败时回退到文件系统扫描
                pass

        # 如果没有 FTS 结果，使用传统文件系统扫描
        if not l3_results:
            candidate_paths = [r["path"] for r in result["l1_results"] + result["l2_results"]]
            l3_results = search_l3_content(query, candidate_paths if candidate_paths else None)
            print(f"Debug: File scan found {len(l3_results)} results", file=sys.stderr)

    result["l3_results"] = l3_results

    result["performance"]["l3_time_ms"] = round((time.time() - l3_start) * 1000, 2)

    # 语义搜索层（当启用时）
    semantic_results = []
    if semantic and query:
        semantic_start = time.time()
        try:
            # 尝试使用简单向量索引（Windows 兼容）
            from lib.vector_index_simple import get_model, get_index
            model = get_model()
            if model.load():
                query_embeddings = model.encode([query])
                if query_embeddings:
                    index = get_index()
                    semantic_raw = index.search(query_embeddings[0], top_k=50, date_from=date_from, date_to=date_to)
                    # 转换格式
                    semantic_results = []
                    for path, score in semantic_raw:
                        vec_data = index.get(path)
                        date_str = vec_data.get("date", "") if vec_data else ""
                        semantic_results.append({
                            "path": str(USER_DATA_DIR / path),
                            "rel_path": path,
                            "date": date_str,
                            "similarity": round(score, 4),
                            "source": "semantic"
                        })
                    print(f"Debug: Semantic found {len(semantic_results)} results", file=sys.stderr)
        except Exception as e:
            print(f"Debug: Semantic search error: {e}", file=sys.stderr)
            pass
        result["performance"]["semantic_time_ms"] = round((time.time() - semantic_start) * 1000, 2)

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
            semantic_weight=semantic_weight
        )
    else:
        # 使用传统排序
        result["merged_results"] = merge_and_rank_results(
            result["l1_results"],
            result["l2_results"],
            result["l3_results"],
            query
        )
    result["total_found"] = len(result["merged_results"])
    result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)

    return result


def enrich_semantic_result(semantic_result: Dict) -> Dict:
    """
    为语义搜索结果补充文件元数据（title, snippet 等）

    Args:
        semantic_result: 语义搜索结果（包含 path, date, similarity）

    Returns:
        补充后的结果字典
    """
    path = semantic_result.get("path", "")
    result = semantic_result.copy()

    try:
        file_path = Path(path)
        if file_path.exists():
            content = file_path.read_text(encoding='utf-8')
            metadata, body = parse_frontmatter(content)

            # 补充标题
            if not result.get("title") and metadata.get("title"):
                result["title"] = metadata["title"]

            # 生成摘要片段（前 200 字符）
            if not result.get("snippet") and body:
                snippet = body[:200].replace('\n', ' ').strip()
                if len(body) > 200:
                    snippet += "..."
                result["snippet"] = snippet

            # 补充其他元数据
            if metadata.get("abstract"):
                result["abstract"] = metadata["abstract"]
            if metadata.get("tags"):
                result["tags"] = metadata["tags"]
            if metadata.get("topic"):
                result["topic"] = metadata["topic"]
            if metadata.get("project"):
                result["project"] = metadata["project"]
    except Exception:
        pass  # 读取失败时保持原样

    return result


def merge_and_rank_results(
    l1_results: List[Dict],
    l2_results: List[Dict],
    l3_results: List[Dict],
    query: Optional[str] = None
) -> List[Dict]:
    """
    合并三层搜索结果并按相关性排序

    排序策略：
    1. L3 内容匹配（最高优先级）：使用 BM25 分数
    2. L2 元数据匹配：title/abstract 匹配加分
    3. L1 索引匹配：基础存在分
    """
    scored = {}  # path -> {data, score, tier}

    # L3: 内容匹配（最高优先级，BM25 分数已计算）
    for r in l3_results:
        path = r["path"]
        # BM25 分数转换：relevance 已经是 0-100 的匹配度
        base_score = r.get("relevance", 50)
        # 标题匹配额外加分
        if r.get("title_match"):
            base_score += 10
        scored[path] = {
            "data": r,
            "score": base_score,
            "tier": 3
        }

    # L2: 元数据匹配（仅当不在 L3 中时添加）
    for r in l2_results:
        path = r["path"]
        if path in scored:
            continue  # L3 已覆盖，跳过

        # L2 基础分必须低于 L3 最低分（L3 最低约 30-40）
        # 确保即使 L2 title 完全匹配，也不超过 L3 的 BM25 分数
        score = 20  # L2 基础分（显著低于 L3 的最低分）

        if query:
            query_lower = query.lower()
            title = r.get("title", "").lower()
            metadata = r.get("metadata", {})
            abstract = metadata.get("abstract", "").lower() if isinstance(metadata.get("abstract"), str) else ""
            tags = metadata.get("tags", [])
            tags_str = " ".join(tags).lower() if isinstance(tags, list) else str(tags).lower()

            # title 匹配 +8 分（限制上限，确保不超过 L3 内容匹配）
            if query_lower in title:
                score += 8
            # abstract 匹配 +5 分
            if query_lower in abstract:
                score += 5
            # tags 匹配 +2 分
            if query_lower in tags_str:
                score += 2

        scored[path] = {
            "data": r,
            "score": score,
            "tier": 2
        }

    # L1: 索引匹配（最低优先级）
    for r in l1_results:
        path = r["path"]
        if path in scored:
            continue
        scored[path] = {
            "data": r,
            "score": 10,  # L1 基础分
            "tier": 1
        }

    # 按分数降序排序，分数相同按 tier 排序（高 tier 优先）
    sorted_results = sorted(
        scored.values(),
        key=lambda x: (x["score"], x["tier"]),
        reverse=True
    )

    # 提取数据并添加排名信息
    merged = []
    for rank, item in enumerate(sorted_results, 1):
        data = item["data"].copy()
        data["search_rank"] = rank
        data["relevance_score"] = item["score"]
        merged.append(data)

    return merged


def merge_and_rank_results_hybrid(
    l1_results: List[Dict],
    l2_results: List[Dict],
    l3_results: List[Dict],
    semantic_results: List[Dict],
    query: Optional[str] = None,
    fts_weight: float = 0.6,
    semantic_weight: float = 0.4
) -> List[Dict]:
    """
    混合排序：结合 FTS (BM25) 和语义搜索结果

    Args:
        l1_results: L1 索引层结果
        l2_results: L2 元数据层结果
        l3_results: L3 内容层结果（FTS）
        semantic_results: 语义搜索结果
        query: 查询词
        fts_weight: FTS 得分权重
        semantic_weight: 语义得分权重
    """
    scored = {}  # path -> {data, fts_score, semantic_score, final_score}

    # 处理 L3/FTS 结果
    max_fts_score = 0
    for r in l3_results:
        path = r["path"]
        # 使用 BM25 relevance 分数（0-100）
        fts_score = r.get("relevance", 50)
        if r.get("title_match"):
            fts_score += 10
        max_fts_score = max(max_fts_score, fts_score)

        scored[path] = {
            "data": r,
            "fts_score": fts_score / 100.0,  # 归一化到 0-1
            "semantic_score": 0,
            "tier": 3
        }

    # 处理语义结果
    max_semantic_score = max([r.get("similarity", 0) for r in semantic_results]) if semantic_results else 1.0
    if max_semantic_score == 0:
        max_semantic_score = 1.0

    for r in semantic_results:
        path = r["path"]
        semantic_score = r.get("similarity", 0) / max_semantic_score  # 归一化

        if path in scored:
            # 已存在，合并语义分数
            scored[path]["semantic_score"] = semantic_score
        else:
            # 新结果 - 需要补充读取文件元数据
            enriched_data = enrich_semantic_result(r)
            scored[path] = {
                "data": enriched_data,
                "fts_score": 0,
                "semantic_score": semantic_score,
                "tier": 4  # 语义层
            }

    # 计算最终得分
    for path, item in scored.items():
        item["final_score"] = (
            item["fts_score"] * fts_weight +
            item["semantic_score"] * semantic_weight
        ) * 100  # 转换回 0-100 范围

    # 处理 L2 结果（仅当不在 L3/语义中时）
    for r in l2_results:
        path = r["path"]
        if path in scored:
            continue

        score = 20  # L2 基础分
        if query:
            query_lower = query.lower()
            title = r.get("title", "").lower()
            metadata = r.get("metadata", {})
            abstract = metadata.get("abstract", "").lower() if isinstance(metadata.get("abstract"), str) else ""
            tags = metadata.get("tags", [])
            tags_str = " ".join(tags).lower() if isinstance(tags, list) else str(tags).lower()

            if query_lower in title:
                score += 8
            if query_lower in abstract:
                score += 5
            if query_lower in tags_str:
                score += 2

        scored[path] = {
            "data": r,
            "fts_score": 0,
            "semantic_score": 0,
            "final_score": score,
            "tier": 2
        }

    # 处理 L1 结果
    for r in l1_results:
        path = r["path"]
        if path in scored:
            continue
        scored[path] = {
            "data": r,
            "fts_score": 0,
            "semantic_score": 0,
            "final_score": 10,
            "tier": 1
        }

    # 按最终得分排序
    sorted_results = sorted(
        scored.values(),
        key=lambda x: (x["final_score"], x["tier"]),
        reverse=True
    )

    # 提取数据并添加排名
    merged = []
    for rank, item in enumerate(sorted_results, 1):
        data = item["data"].copy()
        data["search_rank"] = rank
        data["relevance_score"] = round(item["final_score"], 2)
        data["fts_score"] = round(item["fts_score"] * 100, 2)
        data["semantic_score"] = round(item["semantic_score"] * 100, 2)
        merged.append(data)

    return merged


def main():
    parser = argparse.ArgumentParser(
        description="Life Index - Search Journals Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python search_journals.py --query "深度学习"
    python search_journals.py --topic work --project LobsterAI
    python search_journals.py --date-from 2026-01-01 --date-to 2026-03-04
    python search_journals.py --tags AI,Python --level 2
    python search_journals.py --location Lagos
        """
    )

    parser.add_argument("--query", "--keywords", dest="query", help="内容搜索关键词（支持 --query 或 --keywords）")
    parser.add_argument("--topic", help="按主题过滤")
    parser.add_argument("--project", help="按项目过滤")
    parser.add_argument("--tags", help="按标签过滤（逗号分隔）")
    parser.add_argument("--date-from", help="起始日期 (YYYY-MM-DD)")
    parser.add_argument("--date-to", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--location", help="按地点过滤")
    parser.add_argument("--weather", help="按天气过滤")
    parser.add_argument("--level", type=int, choices=[1, 2, 3], default=3,
                        help="搜索层级: 1=索引, 2=元数据, 3=全文 (默认: 3)")
    parser.add_argument("--use-index", action="store_true",
                        help="使用 FTS 索引加速全文搜索（需要预先运行 build_index.py）")
    parser.add_argument("--semantic", action="store_true",
                        help="启用语义搜索（混合 BM25 + 向量相似度排序）")
    parser.add_argument("--semantic-weight", type=float, default=0.4,
                        help="语义搜索权重（0-1，默认 0.4，需配合 --semantic）")
    parser.add_argument("--fts-weight", type=float, default=0.6,
                        help="FTS 搜索权重（0-1，默认 0.6，需配合 --semantic）")
    parser.add_argument("--limit", type=int, default=50, help="返回结果数量限制")
    parser.add_argument("--verbose", action="store_true", help="输出详细日志")

    args = parser.parse_args()

    # 解析标签
    tags = args.tags.split(",") if args.tags else None

    # 执行搜索
    result = hierarchical_search(
        query=args.query,
        topic=args.topic,
        project=args.project,
        tags=tags,
        date_from=args.date_from,
        date_to=args.date_to,
        location=args.location,
        weather=args.weather,
        level=args.level,
        use_index=args.use_index,
        semantic=args.semantic,
        semantic_weight=args.semantic_weight,
        fts_weight=args.fts_weight
    )

    # 应用限制
    if "merged_results" in result:
        result["merged_results"] = result["merged_results"][:args.limit]
    elif result["l2_results"]:
        result["l2_results"] = result["l2_results"][:args.limit]
    elif result["l1_results"]:
        result["l1_results"] = result["l1_results"][:args.limit]

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
