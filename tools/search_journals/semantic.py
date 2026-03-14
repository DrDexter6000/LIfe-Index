#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - Semantic
语义搜索模块
"""

from pathlib import Path
from typing import Any, Dict, List

# 导入配置 (relative imports from tools/lib)
from ..lib.config import USER_DATA_DIR

from .utils import parse_frontmatter


def search_semantic(
    query: str, date_from: str = "", date_to: str = ""
) -> List[Dict[str, Any]]:
    """
    执行语义搜索

    Args:
        query: 查询词
        date_from: 起始日期
        date_to: 结束日期

    Returns:
        语义搜索结果列表
    """
    results = []

    try:
        # 尝试使用简单向量索引（Windows 兼容）
        from ..lib.vector_index_simple import get_model, get_index

        model = get_model()
        if model.load():
            query_embeddings = model.encode([query])
            if query_embeddings:
                index = get_index()
                semantic_raw = index.search(
                    query_embeddings[0], top_k=50, date_from=date_from, date_to=date_to
                )
                # 转换格式
                for path, score in semantic_raw:
                    vec_data = index.get(path)
                    date_str = vec_data.get("date", "") if vec_data else ""
                    results.append(
                        {
                            "path": str(USER_DATA_DIR / path),
                            "rel_path": path,
                            "date": date_str,
                            "similarity": round(score, 4),
                            "source": "semantic",
                        }
                    )
    except (OSError, IOError, ImportError):
        # 语义搜索失败时返回空列表（可能是模型未安装或文件读取失败）
        pass

    return results


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
            content = file_path.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(content)

            # 补充标题
            if not result.get("title") and metadata.get("title"):
                result["title"] = metadata["title"]

            # 生成摘要片段（前 200 字符）
            if not result.get("snippet") and body:
                snippet = body[:200].replace("\n", " ").strip()
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
    except (OSError, IOError):
        pass  # 读取失败时保持原样

    return result
