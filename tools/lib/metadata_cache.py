#!/usr/bin/env python3
"""
Life Index - Metadata Cache Module
L2搜索元数据缓存管理

特性:
- 增量更新：仅处理新增/修改的日志
- 自动初始化：首次使用时自动创建缓存表
- 文件变更检测：使用mtime+size检测文件变更
- 内存缓存：支持内存级缓存加速热点查询
"""

import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import sys

# 导入配置
sys.path.insert(0, str(Path(__file__).parent))
from config import JOURNALS_DIR, USER_DATA_DIR  # type: ignore
from frontmatter import parse_journal_file  # type: ignore

# 缓存存储目录
CACHE_DIR = USER_DATA_DIR / ".cache"
METADATA_DB_PATH = CACHE_DIR / "metadata_cache.db"

# 内存缓存（进程生命周期）
_memory_cache: Dict[str, Any] = {}
_memory_cache_timestamp: float = 0
_memory_cache_ttl: int = 60  # 内存缓存TTL（秒）


def init_metadata_cache() -> sqlite3.Connection:
    """初始化元数据缓存数据库"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(METADATA_DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")  # 启用 WAL 模式提升并发性能
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 创建元数据缓存表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata_cache (
            file_path TEXT PRIMARY KEY,
            date TEXT,
            title TEXT,
            location TEXT,
            weather TEXT,
            topic TEXT,  -- JSON数组
            project TEXT,
            tags TEXT,   -- JSON数组
            mood TEXT,   -- JSON数组
            people TEXT, -- JSON数组
            abstract TEXT,
            file_mtime REAL,
            file_size INTEGER,
            cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 创建索引加速查询
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_metadata_date 
        ON metadata_cache(date)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_metadata_topic 
        ON metadata_cache(topic)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_metadata_project 
        ON metadata_cache(project)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_metadata_location 
        ON metadata_cache(location)
    """)

    # 创建缓存状态表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    return conn


def get_file_signature(file_path: Path) -> Tuple[float, int]:
    """获取文件签名（mtime, size）用于检测变更"""
    try:
        stat = file_path.stat()
        return (stat.st_mtime, stat.st_size)
    except (OSError, IOError):
        return (0, 0)


def is_cache_valid(file_path: Path, cached_mtime: float, cached_size: int) -> bool:
    """检查缓存是否有效（文件未变更）"""
    current_mtime, current_size = get_file_signature(file_path)
    return current_mtime == cached_mtime and current_size == cached_size


def parse_and_cache_journal(
    conn: sqlite3.Connection, file_path: Path
) -> Optional[Dict[str, Any]]:
    """解析日志并更新缓存"""
    try:
        # 解析日志文件
        metadata = parse_journal_file(file_path)
        if not metadata:
            return None

        # 获取文件签名
        mtime, size = get_file_signature(file_path)

        # 提取可过滤字段
        file_path_str = str(file_path)
        date = metadata.get("date", "")[:10] if metadata.get("date") else ""
        title = metadata.get("title", "")
        location = metadata.get("location", "")
        weather = metadata.get("weather", "")
        abstract = metadata.get("abstract", "")

        # 数组字段转为JSON
        topic = json.dumps(metadata.get("topic", []), ensure_ascii=False)
        project = metadata.get("project", "")
        tags = json.dumps(metadata.get("tags", []), ensure_ascii=False)
        mood = json.dumps(metadata.get("mood", []), ensure_ascii=False)
        people = json.dumps(metadata.get("people", []), ensure_ascii=False)

        # 更新缓存
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO metadata_cache 
            (file_path, date, title, location, weather, topic, project, tags, mood, people, abstract, file_mtime, file_size)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                file_path_str,
                date,
                title,
                location,
                weather,
                topic,
                project,
                tags,
                mood,
                people,
                abstract,
                mtime,
                size,
            ),
        )

        conn.commit()

        return {
            "file_path": file_path_str,
            "date": date,
            "title": title,
            "location": location,
            "weather": weather,
            "topic": json.loads(topic),
            "project": project,
            "tags": json.loads(tags),
            "mood": json.loads(mood),
            "people": json.loads(people),
            "abstract": abstract,
            "metadata": metadata,
        }

    except (IOError, OSError, ValueError) as e:
        return None


def get_cached_metadata(
    conn: sqlite3.Connection, file_path: Path
) -> Optional[Dict[str, Any]]:
    """从缓存获取元数据（如果有效）"""
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM metadata_cache WHERE file_path = ?", (str(file_path),)
    )

    row = cursor.fetchone()
    if row is None:
        return None

    # 检查缓存是否有效
    if not is_cache_valid(file_path, row["file_mtime"], row["file_size"]):
        return None

    # 转换为字典
    return {
        "file_path": row["file_path"],
        "date": row["date"],
        "title": row["title"],
        "location": row["location"],
        "weather": row["weather"],
        "topic": json.loads(row["topic"]) if row["topic"] else [],
        "project": row["project"],
        "tags": json.loads(row["tags"]) if row["tags"] else [],
        "mood": json.loads(row["mood"]) if row["mood"] else [],
        "people": json.loads(row["people"]) if row["people"] else [],
        "abstract": row["abstract"],
        "metadata": {
            "date": row["date"],
            "title": row["title"],
            "location": row["location"],
            "weather": row["weather"],
            "topic": json.loads(row["topic"]) if row["topic"] else [],
            "project": row["project"],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "mood": json.loads(row["mood"]) if row["mood"] else [],
            "people": json.loads(row["people"]) if row["people"] else [],
            "abstract": row["abstract"],
        },
    }


def get_or_update_metadata(
    file_path: Path, conn: Optional[sqlite3.Connection] = None
) -> Optional[Dict[str, Any]]:
    """获取元数据（优先从缓存，缓存未命中则解析并缓存）"""
    close_conn = False
    if conn is None:
        conn = init_metadata_cache()
        close_conn = True

    try:
        # 尝试从缓存获取
        cached = get_cached_metadata(conn, file_path)
        if cached:
            return cached

        # 缓存未命中，解析并缓存
        return parse_and_cache_journal(conn, file_path)

    finally:
        if close_conn:
            conn.close()


def get_all_cached_metadata(
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """获取所有缓存的元数据（用于L2搜索）"""
    close_conn = False
    if conn is None:
        conn = init_metadata_cache()
        close_conn = True

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM metadata_cache")

        results = []
        for row in cursor.fetchall():
            results.append(
                {
                    "file_path": row["file_path"],
                    "date": row["date"],
                    "title": row["title"],
                    "location": row["location"],
                    "weather": row["weather"],
                    "topic": json.loads(row["topic"]) if row["topic"] else [],
                    "project": row["project"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                    "mood": json.loads(row["mood"]) if row["mood"] else [],
                    "people": json.loads(row["people"]) if row["people"] else [],
                    "abstract": row["abstract"],
                    "metadata": {
                        "date": row["date"],
                        "title": row["title"],
                        "location": row["location"],
                        "weather": row["weather"],
                        "topic": json.loads(row["topic"]) if row["topic"] else [],
                        "project": row["project"],
                        "tags": json.loads(row["tags"]) if row["tags"] else [],
                        "mood": json.loads(row["mood"]) if row["mood"] else [],
                        "people": json.loads(row["people"]) if row["people"] else [],
                        "abstract": row["abstract"],
                    },
                }
            )

        return results

    finally:
        if close_conn:
            conn.close()


def invalidate_cache(file_path: Optional[Path] = None) -> None:
    """使缓存失效"""
    conn = init_metadata_cache()
    try:
        cursor = conn.cursor()
        if file_path:
            cursor.execute(
                "DELETE FROM metadata_cache WHERE file_path = ?", (str(file_path),)
            )
        else:
            cursor.execute("DELETE FROM metadata_cache")
        conn.commit()
    finally:
        conn.close()


def get_cache_stats() -> Dict[str, Any]:
    """获取缓存统计信息"""
    conn = init_metadata_cache()
    try:
        cursor = conn.cursor()

        # 总条目数
        cursor.execute("SELECT COUNT(*) FROM metadata_cache")
        total_entries = cursor.fetchone()[0]

        # 缓存大小
        db_size = METADATA_DB_PATH.stat().st_size if METADATA_DB_PATH.exists() else 0

        # 最后更新时间
        cursor.execute("SELECT MAX(cached_at) FROM metadata_cache")
        last_update = cursor.fetchone()[0]

        return {
            "total_entries": total_entries,
            "db_size_mb": round(db_size / (1024 * 1024), 2),
            "last_update": last_update,
            "cache_path": str(METADATA_DB_PATH),
        }
    finally:
        conn.close()


def update_cache_for_all_journals(
    progress_callback: Optional[callable] = None,
) -> Dict[str, int]:
    """更新所有日志的缓存（用于重建缓存）"""
    conn = init_metadata_cache()
    try:
        updated = 0
        skipped = 0
        errors = 0

        # 遍历所有日志文件
        if JOURNALS_DIR.exists():
            for year_dir in JOURNALS_DIR.iterdir():
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue

                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir():
                        continue

                    for journal_file in month_dir.glob("*.md"):
                        try:
                            # 检查缓存是否有效
                            cached = get_cached_metadata(conn, journal_file)
                            if cached:
                                skipped += 1
                                continue

                            # 更新缓存
                            result = parse_and_cache_journal(conn, journal_file)
                            if result:
                                updated += 1
                            else:
                                errors += 1

                            if progress_callback:
                                progress_callback(updated, skipped, errors)

                        except (IOError, OSError, ValueError):
                            errors += 1

        return {
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
    finally:
        conn.close()
