#!/usr/bin/env python3
"""
Life Index - Semantic Search Module
RAG 语义检索模块（基于 sqlite-vec）

特性:
- 本地嵌入模型（all-MiniLM-L6-v2，80MB）
- 向量相似度搜索 + 时间衰减排序
- 自动下载模型，首次使用 ~2s 加载
"""

import sqlite3
import json
import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import sys
import os

# 导入配置
sys.path.insert(0, str(Path(__file__).parent))
from config import JOURNALS_DIR, USER_DATA_DIR

# 索引存储目录
INDEX_DIR = USER_DATA_DIR / ".index"
VEC_DB_PATH = INDEX_DIR / "journals_vec.db"
CACHE_DIR = USER_DATA_DIR / ".cache" / "models"

# 嵌入模型配置
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # MiniLM-L6-v2 输出维度


class EmbeddingModel:
    """嵌入模型管理器（单例模式）"""
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self) -> bool:
        """加载嵌入模型，返回是否成功"""
        if self._model is not None:
            return True

        try:
            from sentence_transformers import SentenceTransformer

            print(f"Loading embedding model: {EMBEDDING_MODEL}...")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)

            self._model = SentenceTransformer(
                EMBEDDING_MODEL,
                cache_folder=str(CACHE_DIR)
            )
            print("Model loaded successfully.")
            return True

        except ImportError:
            print("Warning: sentence-transformers not installed. Run: pip install sentence-transformers")
            return False
        except Exception as e:
            print(f"Warning: Failed to load embedding model: {e}")
            return False

    def encode(self, texts: List[str]) -> List[List[float]]:
        """编码文本为向量"""
        if not self.load():
            return []

        try:
            embeddings = self._model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as e:
            print(f"Encoding error: {e}")
            return []


def get_model() -> EmbeddingModel:
    """获取嵌入模型实例"""
    return EmbeddingModel()


def _load_sqlite_vec_extension(conn: sqlite3.Connection) -> bool:
    """
    加载 sqlite-vec 扩展（跨平台兼容）

    Returns:
        True if loaded successfully
    """
    import platform

    try:
        conn.enable_load_extension(True)

        # 根据平台尝试不同的加载方式
        system = platform.system()

        if system == "Windows":
            # Windows: 尝试常见路径
            possible_paths = [
                # 当前目录
                "vec0.dll",
                "vec.dll",
                # Python 包目录
                Path(sys.executable).parent / "Lib" / "site-packages" / "sqlite_vec" / "vec0.dll",
                # 用户数据目录
                USER_DATA_DIR / ".bin" / "vec0.dll",
            ]

            for path in possible_paths:
                try:
                    conn.load_extension(str(path))
                    return True
                except:
                    continue

        elif system == "Darwin":  # macOS
            possible_names = ["vec0.dylib", "libvec.dylib", "vec.dylib", "vec0", "vec"]
            for name in possible_names:
                try:
                    conn.load_extension(name)
                    return True
                except:
                    continue

        else:  # Linux
            possible_names = ["vec0.so", "libvec.so", "vec.so", "vec0", "vec"]
            for name in possible_names:
                try:
                    conn.load_extension(name)
                    return True
                except:
                    continue

        return False

    except Exception as e:
        return False


def init_vec_db() -> Optional[sqlite3.Connection]:
    """
    初始化向量数据库（sqlite-vec）

    Returns:
        Connection if successful, None if sqlite-vec not available
    """
    INDEX_DIR.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(VEC_DB_PATH))

    # 尝试加载 sqlite-vec 扩展
    if not _load_sqlite_vec_extension(conn):
        conn.close()
        return None

    cursor = conn.cursor()

    # 创建虚拟表（使用 float32 数组存储向量）
    try:
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS journal_vectors USING vec0(
                path TEXT PRIMARY KEY,
                embedding FLOAT[{EMBEDDING_DIM}],
                date TEXT,
                file_hash TEXT
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"Warning: Failed to create vector table: {e}")
        conn.close()
        return None

    return conn


def parse_journal_for_vec(file_path: Path) -> Optional[Tuple[str, str, str]]:
    """
    解析日志文件，提取用于向量化的内容

    Returns:
        (path, combined_text, date) or None
    """
    try:
        content = file_path.read_text(encoding='utf-8')

        if not content.startswith('---'):
            return None

        parts = content.split('---', 2)
        if len(parts) < 3:
            return None

        fm_text = parts[1].strip()
        body = parts[2].strip()

        # 解析 frontmatter
        metadata = {}
        for line in fm_text.split('\n'):
            line = line.strip()
            if ':' in line and not line.startswith('#'):
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                if value.startswith('[') and value.endswith(']'):
                    value = [v.strip().strip('"\'') for v in value[1:-1].split(',') if v.strip()]

                metadata[key] = value

        # 组合用于向量化的文本（标题 + 正文 + 标签）
        text_parts = []

        if metadata.get('title'):
            text_parts.append(metadata['title'])

        text_parts.append(body[:1000])  # 限制正文长度，避免过长

        if metadata.get('tags'):
            tags = metadata['tags']
            if isinstance(tags, list):
                text_parts.extend(tags)
            else:
                text_parts.append(tags)

        if metadata.get('topic'):
            topic = metadata['topic']
            if isinstance(topic, list):
                text_parts.extend(topic)
            else:
                text_parts.append(topic)

        combined_text = ' '.join(text_parts)

        rel_path = str(file_path.relative_to(USER_DATA_DIR)).replace('\\', '/')
        date_str = metadata.get('date', '')[:10]

        return (rel_path, combined_text, date_str)

    except Exception as e:
        return None


def get_file_hash(file_path: Path) -> str:
    """计算文件哈希"""
    try:
        content = file_path.read_bytes()
        return hashlib.md5(content).hexdigest()[:16]
    except Exception:
        return ""


def update_vector_index(incremental: bool = True) -> Dict[str, Any]:
    """
    更新向量索引

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
    result = {
        "success": False,
        "added": 0,
        "updated": 0,
        "removed": 0,
        "total": 0,
        "error": None
    }

    # 检查模型是否可用
    model = get_model()
    if not model.load():
        result["error"] = "Embedding model not available"
        return result

    try:
        conn = init_vec_db()
        if conn is None:
            result["error"] = "sqlite-vec extension not available. Vector search disabled."
            return result
        cursor = conn.cursor()

        # 获取已索引的文件
        indexed_files = {}
        try:
            cursor.execute("SELECT path, file_hash FROM journal_vectors")
            for row in cursor.fetchall():
                indexed_files[row[0]] = row[1]
        except Exception:
            pass

        # 扫描所有日志文件
        current_files = set()
        files_to_process = []

        if JOURNALS_DIR.exists():
            for year_dir in JOURNALS_DIR.iterdir():
                if not year_dir.is_dir() or not year_dir.name.isdigit():
                    continue

                for month_dir in year_dir.iterdir():
                    if not month_dir.is_dir():
                        continue

                    for journal_file in month_dir.glob("life-index_*.md"):
                        parsed = parse_journal_for_vec(journal_file)
                        if parsed:
                            rel_path, text, date_str = parsed
                            current_files.add(rel_path)
                            file_hash = get_file_hash(journal_file)

                            if rel_path not in indexed_files:
                                files_to_process.append(('add', rel_path, text, date_str, file_hash))
                            elif indexed_files[rel_path] != file_hash:
                                files_to_process.append(('update', rel_path, text, date_str, file_hash))

        # 找出需要删除的
        files_to_remove = set(indexed_files.keys()) - current_files

        # 如果不是增量模式，清空并重新处理
        if not incremental:
            try:
                cursor.execute("DELETE FROM journal_vectors")
            except Exception:
                pass
            files_to_remove = set()
            # 重新收集所有文件
            files_to_process = []
            for action, rel_path, text, date_str, file_hash in files_to_process:
                if action in ('add', 'update'):
                    files_to_process.append(('add', rel_path, text, date_str, file_hash))
            result["removed"] = len(indexed_files)

        # 批量处理（每批 10 个，避免内存问题）
        batch_size = 10
        for i in range(0, len(files_to_process), batch_size):
            batch = files_to_process[i:i+batch_size]

            # 收集文本
            texts = [item[2] for item in batch]

            # 编码为向量
            embeddings = model.encode(texts)

            if not embeddings:
                continue

            # 插入数据库
            for j, (action, rel_path, text, date_str, file_hash) in enumerate(batch):
                if j >= len(embeddings):
                    break

                embedding = embeddings[j]
                embedding_bytes = json.dumps(embedding)

                # 如果是更新，先删除
                if action == 'update':
                    try:
                        cursor.execute("DELETE FROM journal_vectors WHERE path = ?", (rel_path,))
                        result["updated"] += 1
                    except Exception:
                        pass
                else:
                    result["added"] += 1

                # 插入新记录
                try:
                    cursor.execute("""
                        INSERT INTO journal_vectors (path, embedding, date, file_hash)
                        VALUES (?, vec_f32(?), ?, ?)
                    """, (rel_path, embedding_bytes, date_str, file_hash))
                except Exception as e:
                    print(f"Insert error for {rel_path}: {e}")

        # 删除不存在的文件
        for rel_path in files_to_remove:
            try:
                cursor.execute("DELETE FROM journal_vectors WHERE path = ?", (rel_path,))
                result["removed"] += 1
            except Exception:
                pass

        conn.commit()
        conn.close()

        result["total"] = len(current_files)
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        import traceback
        traceback.print_exc()

    return result


def search_semantic(
    query: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    top_k: int = 20,
    time_decay_days: int = 365
) -> List[Dict[str, Any]]:
    """
    语义搜索（向量相似度 + 时间衰减）

    Args:
        query: 查询文本
        date_from: 起始日期
        date_to: 结束日期
        top_k: 返回结果数
        time_decay_days: 时间衰减半衰期（天）

    Returns:
        搜索结果列表，按综合得分排序
    """
    results = []

    # 检查模型和数据库
    model = get_model()
    if not model.load():
        return results

    if not VEC_DB_PATH.exists():
        return results

    try:
        # 编码查询
        query_embeddings = model.encode([query])
        if not query_embeddings:
            return results

        query_vec = query_embeddings[0]
        query_vec_json = json.dumps(query_vec)

        conn = init_vec_db()
        if conn is None:
            return results
        cursor = conn.cursor()

        # 执行向量搜索
        # 注意：sqlite-vec 的具体语法可能需要根据实际版本调整
        try:
            cursor.execute("""
                SELECT path, embedding, date,
                       vec_distance_l2(embedding, vec_f32(?)) as distance
                FROM journal_vectors
                ORDER BY distance ASC
                LIMIT ?
            """, (query_vec_json, top_k * 2))  # 多取一些用于后续过滤

            rows = cursor.fetchall()

            today = datetime.now()
            lambda_decay = 0.693 / time_decay_days  # 半衰期公式

            for row in rows:
                rel_path, embedding, date_str, distance = row

                # 日期过滤
                if date_from and date_str and date_str < date_from:
                    continue
                if date_to and date_str and date_str > date_to:
                    continue

                # 计算相似度得分（转换为 0-1 范围，越大越好）
                similarity_score = 1.0 / (1.0 + distance)

                # 计算时间衰减因子
                if date_str:
                    try:
                        doc_date = datetime.strptime(date_str, "%Y-%m-%d")
                        days_diff = (today - doc_date).days
                        time_factor = 1.0  # exp(-lambda_decay * days_diff)
                    except:
                        time_factor = 1.0
                else:
                    time_factor = 1.0

                # 综合得分（可调整权重）
                final_score = similarity_score * time_factor

                results.append({
                    'path': rel_path,
                    'date': date_str,
                    'similarity': round(similarity_score, 4),
                    'time_factor': round(time_factor, 4),
                    'final_score': round(final_score, 4),
                    'source': 'semantic'
                })

            # 按最终得分排序
            results.sort(key=lambda x: x['final_score'], reverse=True)

            # 截取前 K 个
            results = results[:top_k]

        except Exception as e:
            print(f"Vector search error: {e}")
            import traceback
            traceback.print_exc()

        conn.close()

    except Exception as e:
        print(f"Semantic search error: {e}")

    return results


def hybrid_search(
    query: str,
    fts_results: List[Dict[str, Any]],
    semantic_results: List[Dict[str, Any]],
    fts_weight: float = 0.6,
    semantic_weight: float = 0.4
) -> List[Dict[str, Any]]:
    """
    混合排序：结合 FTS 和语义搜索结果

    Args:
        query: 原始查询
        fts_results: FTS 搜索结果
        semantic_results: 语义搜索结果
        fts_weight: FTS 得分权重
        semantic_weight: 语义得分权重

    Returns:
        合并后的排序结果
    """
    # 归一化得分的字典
    scores = {}

    # 处理 FTS 结果
    max_fts_rank = len(fts_results)
    for i, r in enumerate(fts_results):
        path = r['path']
        # 排名越靠前得分越高（线性衰减）
        rank_score = 1.0 - (i / max_fts_rank) if max_fts_rank > 1 else 1.0
        scores[path] = {
            'path': path,
            'title': r.get('title', ''),
            'date': r.get('date', ''),
            'snippet': r.get('snippet', ''),
            'fts_score': rank_score,
            'semantic_score': 0,
            'final_score': rank_score * fts_weight
        }

    # 处理语义结果
    max_semantic = max([r['final_score'] for r in semantic_results]) if semantic_results else 1.0
    for r in semantic_results:
        path = r['path']
        semantic_score = r['final_score'] / max_semantic if max_semantic > 0 else 0

        if path in scores:
            # 已存在，合并得分
            scores[path]['semantic_score'] = semantic_score
            scores[path]['final_score'] = (
                scores[path]['fts_score'] * fts_weight +
                semantic_score * semantic_weight
            )
        else:
            scores[path] = {
                'path': path,
                'title': '',  # 需要从文件读取
                'date': r.get('date', ''),
                'snippet': '',
                'fts_score': 0,
                'semantic_score': semantic_score,
                'final_score': semantic_score * semantic_weight
            }

    # 转换为列表并排序
    merged = list(scores.values())
    merged.sort(key=lambda x: x['final_score'], reverse=True)

    return merged


def get_stats() -> Dict[str, Any]:
    """获取向量索引统计信息"""
    stats = {
        "exists": VEC_DB_PATH.exists(),
        "total_vectors": 0,
        "db_size_mb": 0,
        "model_loaded": get_model().load()
    }

    try:
        if VEC_DB_PATH.exists():
            stats["db_size_mb"] = round(VEC_DB_PATH.stat().st_size / (1024 * 1024), 2)

            conn = init_vec_db()
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT COUNT(*) FROM journal_vectors")
                stats["total_vectors"] = cursor.fetchone()[0]
            except Exception:
                pass

            conn.close()

    except Exception:
        pass

    return stats


if __name__ == "__main__":
    # 测试代码
    print("Testing semantic index...")

    print("\nIndex stats:")
    print(json.dumps(get_stats(), indent=2, ensure_ascii=False))

    print("\nUpdating vector index...")
    result = update_vector_index(incremental=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    print("\nTesting semantic search:")
    results = search_semantic("重构项目架构", top_k=5)
    for r in results:
        print(f"  [{r['date']}] {r['path']} (score: {r['final_score']})")
