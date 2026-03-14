#!/usr/bin/env python3
"""
Life Index - Search Index Module
SQLite FTS5 全文索引管理

特性:
- 增量更新：仅处理新增/修改的日志
- 自动初始化：首次使用时自动创建索引
- 降级路径：索引损坏时自动重建
"""

import sqlite3
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from .config import JOURNALS_DIR, USER_DATA_DIR

# 索引存储目录
INDEX_DIR = USER_DATA_DIR / ".index"
FTS_DB_PATH = INDEX_DIR / "journals_fts.db"


def get_file_hash(file_path: Path) -> str:
    """计算文件内容哈希，用于检测变更"""
    try:
        content = file_path.read_bytes()
        return hashlib.md5(content).hexdigest()[:16]
    except (OSError, IOError):
        return ""


def init_fts_db() -> sqlite3.Connection:
    """初始化 FTS5 数据库"""
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(FTS_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提升并发性能
    cursor = conn.cursor()

    # 创建 FTS5 虚拟表（如果不存在）
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS journals USING fts5(
            path,
            title,
            content,
            date,
            location,
            weather,
            topic,
            project,
            tags,
            file_hash UNINDEXED,
            modified_time UNINDEXED
        )
    """)

    # 创建元数据表（记录索引状态）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS index_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    return conn


def parse_journal(file_path: Path) -> Optional[Dict[str, Any]]:
    """解析日志文件，提取可索引内容"""
    try:
        content = file_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        fm_text = parts[1].strip()
        body = parts[2].strip()

        # 解析 frontmatter
        metadata = {}
        for line in fm_text.split("\n"):
            line = line.strip()
            if ":" in line and not line.startswith("#"):
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip()

                # 处理列表格式
                if value.startswith("[") and value.endswith("]"):
                    value = [
                        v.strip().strip("\"'")
                        for v in value[1:-1].split(",")
                        if v.strip()
                    ]  # type: ignore

                metadata[key] = value

        # 构建可索引文档
        doc = {
            "path": str(file_path.relative_to(USER_DATA_DIR)).replace("\\", "/"),
            "title": metadata.get("title", ""),
            "content": body,
            "date": metadata.get("date", "")[:10],
            "location": metadata.get("location", ""),
            "weather": metadata.get("weather", ""),
            "topic": _normalize_to_str(metadata.get("topic")),
            "project": metadata.get("project", ""),
            "tags": _normalize_to_str(metadata.get("tags")),
            "file_hash": get_file_hash(file_path),
            "modified_time": datetime.fromtimestamp(
                file_path.stat().st_mtime
            ).isoformat(),
        }

        return doc

    except (OSError, IOError, ValueError) as e:
        print(f"Warning: Failed to parse {file_path}: {e}")
        return None


def _normalize_to_str(value: Any) -> str:
    """将值规范化为字符串"""
    if not value:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def get_indexed_files(conn: sqlite3.Connection) -> Dict[str, Tuple[str, str]]:
    """获取已索引的文件列表（路径 -> (hash, modified_time)）"""
    cursor = conn.cursor()
    cursor.execute("SELECT path, file_hash, modified_time FROM journals")

    result = {}
    for row in cursor.fetchall():
        result[row[0]] = (row[1], row[2])

    return result


def update_index(incremental: bool = True) -> Dict[str, Any]:
    """
    更新搜索索引

    Args:
        incremental: True=仅更新变更，False=全量重建

    Returns:
        {
            "success": bool,
            "added": int,
            "updated": int,
            "removed": int,
            "total": int,
            "error": str (optional)
        }
    """
    result: Dict[str, Any] = {
        "success": False,
        "added": 0,
        "updated": 0,
        "removed": 0,
        "total": 0,
        "error": None,
    }

    try:
        conn = init_fts_db()
        cursor = conn.cursor()

        # 获取当前已索引的文件
        indexed_files = get_indexed_files(conn)

        # 扫描所有日志文件
        current_files = set()
        files_to_update = []

        if JOURNALS_DIR.exists():
            for year_dir in JOURNALS_DIR.iterdir():
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue

                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir():
                        continue

                    for journal_file in month_dir.glob("life-index_*.md"):
                        rel_path = str(journal_file.relative_to(USER_DATA_DIR)).replace(
                            "\\", "/"
                        )
                        current_files.add(rel_path)

                        # 检查是否需要更新
                        file_hash = get_file_hash(journal_file)

                        if rel_path not in indexed_files:
                            # 新文件
                            files_to_update.append(("add", journal_file, rel_path))
                        elif indexed_files[rel_path][0] != file_hash:
                            # 文件已修改
                            files_to_update.append(("update", journal_file, rel_path))

        # 找出需要删除的索引（文件已不存在）
        files_to_remove = set(indexed_files.keys()) - current_files

        # 如果不是增量模式，清空所有索引
        if not incremental:
            cursor.execute("DELETE FROM journals")
            files_to_remove = set()
            # p is already relative to USER_DATA_DIR, need to reconstruct full path correctly
            files_to_update = [("add", USER_DATA_DIR / p, p) for p in current_files]
            result["removed"] = len(indexed_files)

        # 执行删除
        for rel_path in files_to_remove:
            cursor.execute("DELETE FROM journals WHERE path = ?", (rel_path,))
            result["removed"] = (result["removed"] or 0) + 1

        # 执行添加/更新
        for action, file_path, rel_path in files_to_update:
            doc = parse_journal(file_path)
            if doc:
                # 如果是更新，先删除旧记录
                if action == "update":
                    cursor.execute("DELETE FROM journals WHERE path = ?", (rel_path,))
                    result["updated"] = (result["updated"] or 0) + 1
                else:
                    result["added"] = (result["added"] or 0) + 1

                # 插入新记录
                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, date, location, weather,
                                        topic, project, tags, file_hash, modified_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        doc["path"],
                        doc["title"],
                        doc["content"],
                        doc["date"],
                        doc["location"],
                        doc["weather"],
                        doc["topic"],
                        doc["project"],
                        doc["tags"],
                        doc["file_hash"],
                        doc["modified_time"],
                    ),
                )

        conn.commit()
        conn.close()

        # 更新总数
        result["total"] = len(current_files)
        result["success"] = True

    except (OSError, IOError, sqlite3.Error) as e:
        result["error"] = str(e)

    return result


def search_fts(
    query: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    使用 FTS5 搜索日志（带 BM25 相关性排序）

    Args:
        query: 搜索关键词（支持 FTS5 语法：AND, OR, NOT, * 通配符）
        date_from: 起始日期 YYYY-MM-DD
        date_to: 结束日期 YYYY-MM-DD
        limit: 最大返回结果数

    Returns:
        搜索结果列表（按 BM25 相关性排序，分数越高越相关）
    """
    results: List[Dict[str, Any]] = []

    try:
        if not FTS_DB_PATH.exists():
            # 索引不存在，返回空结果（调用方应回退到文件系统扫描）
            return results

        conn = sqlite3.connect(str(FTS_DB_PATH))
        cursor = conn.cursor()

        # 构建查询 - 使用 BM25 排序（分数越低越相关，所以用 ASC）
        # bm25(journals, 1, 1, 1, 0.5) - 调整权重：title/content 权重更高
        sql = """
            SELECT path, title, date,
                   snippet(journals, 2, '<mark>', '</mark>', '...', 32) as snippet,
                   bm25(journals, 1.0, 1.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5) as rank
            FROM journals
            WHERE journals MATCH ?
        """
        params = [query]

        # 添加日期过滤
        if date_from:
            sql += " AND date >= ?"
            params.append(date_from)
        if date_to:
            sql += " AND date <= ?"
            params.append(date_to)

        # 按 BM25 分数排序（分数越低表示越相关）
        sql += " ORDER BY rank ASC"
        sql += f" LIMIT {limit}"

        cursor.execute(sql, params)

        for row in cursor.fetchall():
            # BM25 分数转换为匹配度百分比（分数越低越相关）
            # 典型 BM25 分数范围：-10 到 10，负数表示高度相关
            bm25_score = row[4] if row[4] is not None else 0
            # 转换公式：将 BM25 分数映射到 0-100 的匹配度
            # 分数 <= -5: 95-100% (高度相关)
            # 分数 0: 70% (中等相关)
            # 分数 >= 5: 30% (弱相关)
            relevance = max(0, min(100, int(70 - bm25_score * 5)))

            results.append(
                {
                    "path": row[0],
                    "title": row[1],
                    "date": row[2],
                    "snippet": row[3],
                    "bm25_score": bm25_score,
                    "relevance": relevance,
                    "source": "fts",
                }
            )

        conn.close()

    except (sqlite3.Error, OSError) as e:
        print(f"FTS search error: {e}")

    return results


def get_stats() -> Dict[str, Any]:
    """获取索引统计信息"""
    stats = {
        "exists": FTS_DB_PATH.exists(),
        "total_documents": 0,
        "db_size_mb": 0,
        "last_updated": None,
    }

    try:
        if FTS_DB_PATH.exists():
            stats["db_size_mb"] = round(FTS_DB_PATH.stat().st_size / (1024 * 1024), 2)

            conn = sqlite3.connect(str(FTS_DB_PATH))
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM journals")
            stats["total_documents"] = cursor.fetchone()[0]

            cursor.execute("SELECT MAX(modified_time) FROM journals")
            last = cursor.fetchone()[0]
            if last:
                stats["last_updated"] = last

            conn.close()

    except (OSError, IOError, sqlite3.Error):
        pass

    return stats


if __name__ == "__main__":
    # 测试代码
    print("Initializing FTS index...")
    result = update_index(incremental=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\nIndex stats:")
    print(json.dumps(get_stats(), indent=2, ensure_ascii=False))

    print("\nTesting search:")
    results = search_fts("重构")
    for r in results[:3]:
        print(f"  [{r['date']}] {r['title']}")
