#!/usr/bin/env python3
"""
Life Index - Simple Vector Index (Fallback)
纯 Python 向量索引（当 sqlite-vec 不可用时作为降级方案）

特性:
- 使用 numpy 进行向量运算
- 使用 pickle 持久化存储
- 与 semantic_search.py 接口兼容
"""

import json
import pickle
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import sys
import os

# 导入配置
sys.path.insert(0, str(Path(__file__).parent))
from config import JOURNALS_DIR, USER_DATA_DIR

# 索引存储目录
INDEX_DIR = USER_DATA_DIR / ".index"
VEC_INDEX_PATH = INDEX_DIR / "vectors_simple.pkl"
META_PATH = INDEX_DIR / "vectors_simple_meta.json"
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


class SimpleVectorIndex:
    """
    简单向量索引实现

    数据结构:
    {
        "path1": {"embedding": [0.1, 0.2, ...], "date": "2026-03-05", "hash": "abc123"},
        "path2": {...}
    }
    """

    def __init__(self):
        self.vectors: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self):
        """从磁盘加载索引"""
        if VEC_INDEX_PATH.exists():
            try:
                with open(VEC_INDEX_PATH, 'rb') as f:
                    self.vectors = pickle.load(f)
            except Exception as e:
                print(f"Warning: Failed to load vector index: {e}")
                self.vectors = {}

    def _save(self):
        """保存索引到磁盘"""
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(VEC_INDEX_PATH, 'wb') as f:
                pickle.dump(self.vectors, f)

            # 保存元数据
            meta = {
                "total_vectors": len(self.vectors),
                "last_updated": datetime.now().isoformat(),
                "version": "1.0"
            }
            with open(META_PATH, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2)

        except Exception as e:
            print(f"Warning: Failed to save vector index: {e}")

    def add(self, path: str, embedding: List[float], date: str, file_hash: str):
        """添加或更新向量"""
        self.vectors[path] = {
            "embedding": embedding,
            "date": date,
            "hash": file_hash,
            "added_at": datetime.now().isoformat()
        }

    def remove(self, path: str):
        """删除向量"""
        if path in self.vectors:
            del self.vectors[path]

    def get(self, path: str) -> Optional[Dict[str, Any]]:
        """获取指定路径的向量"""
        return self.vectors.get(path)

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 20,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None
    ) -> List[Tuple[str, float]]:
        """
        搜索最相似的向量（余弦相似度）

        Returns:
            [(path, score), ...] 按相似度降序排列
        """
        try:
            import numpy as np
        except ImportError:
            print("Warning: numpy not installed. Cannot perform vector search.")
            return []

        if not self.vectors:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)
        query_vec = query_vec / (np.linalg.norm(query_vec) + 1e-8)  # 归一化

        results = []

        for path, data in self.vectors.items():
            # 日期过滤
            doc_date = data.get("date", "")
            if date_from and doc_date and doc_date < date_from:
                continue
            if date_to and doc_date and doc_date > date_to:
                continue

            # 计算余弦相似度
            doc_vec = np.array(data["embedding"], dtype=np.float32)
            doc_vec = doc_vec / (np.linalg.norm(doc_vec) + 1e-8)  # 归一化

            similarity = float(np.dot(query_vec, doc_vec))

            results.append((path, similarity))

        # 按相似度降序排列
        results.sort(key=lambda x: x[1], reverse=True)

        return results[:top_k]

    def commit(self):
        """提交更改到磁盘"""
        self._save()

    def clear(self):
        """清空所有向量"""
        self.vectors.clear()

    def stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "exists": VEC_INDEX_PATH.exists(),
            "total_vectors": len(self.vectors),
            "index_size_mb": round(VEC_INDEX_PATH.stat().st_size / (1024 * 1024), 2) if VEC_INDEX_PATH.exists() else 0,
            "backend": "simple_numpy"
        }


# 全局索引实例
_index_instance: Optional[SimpleVectorIndex] = None


def get_index() -> SimpleVectorIndex:
    """获取全局索引实例"""
    global _index_instance
    if _index_instance is None:
        _index_instance = SimpleVectorIndex()
    return _index_instance


def update_vector_index_simple(
    model_encode_func,
    incremental: bool = True
) -> Dict[str, Any]:
    """
    更新简单向量索引

    Args:
        model_encode_func: 编码函数，接收文本列表返回向量列表
        incremental: True=仅更新变更，False=全量重建

    Returns:
        更新结果统计
    """
    result = {
        "success": False,
        "added": 0,
        "updated": 0,
        "removed": 0,
        "total": 0,
        "error": None,
        "backend": "simple_numpy"
    }

    try:
        from lib.semantic_search import parse_journal_for_vec, get_file_hash
    except ImportError:
        # 如果无法导入，定义本地版本
        def parse_journal_for_vec(file_path: Path) -> Optional[Tuple[str, str, str]]:
            try:
                content = file_path.read_text(encoding='utf-8')
                if not content.startswith('---'):
                    return None
                parts = content.split('---', 2)
                if len(parts) < 3:
                    return None

                fm_text = parts[1].strip()
                body = parts[2].strip()

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

                text_parts = []
                if metadata.get('title'):
                    text_parts.append(metadata['title'])
                text_parts.append(body[:1000])
                if metadata.get('tags'):
                    tags = metadata['tags']
                    if isinstance(tags, list):
                        text_parts.extend(tags)
                    else:
                        text_parts.append(tags)

                combined_text = ' '.join(text_parts)
                rel_path = str(file_path.relative_to(USER_DATA_DIR)).replace('\\', '/')
                date_str = metadata.get('date', '')[:10]

                return (rel_path, combined_text, date_str)
            except Exception:
                return None

        def get_file_hash(file_path: Path) -> str:
            try:
                content = file_path.read_bytes()
                return hashlib.md5(content).hexdigest()[:16]
            except Exception:
                return ""

    try:
        index = get_index()

        # 如果不是增量模式，清空索引
        if not incremental:
            index.clear()
            result["removed"] = len(index.vectors)

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

                            existing = index.get(rel_path)
                            if existing is None:
                                files_to_process.append(('add', rel_path, text, date_str, file_hash))
                            elif existing.get("hash") != file_hash:
                                files_to_process.append(('update', rel_path, text, date_str, file_hash))

        # 找出需要删除的文件
        if incremental:
            files_to_remove = set(index.vectors.keys()) - current_files
            for path in files_to_remove:
                index.remove(path)
                result["removed"] += 1

        # 批量处理文件
        batch_size = 10
        for i in range(0, len(files_to_process), batch_size):
            batch = files_to_process[i:i+batch_size]
            texts = [item[2] for item in batch]

            embeddings = model_encode_func(texts)
            if not embeddings:
                continue

            for j, (action, rel_path, text, date_str, file_hash) in enumerate(batch):
                if j >= len(embeddings):
                    break

                index.add(rel_path, embeddings[j], date_str, file_hash)
                if action == 'add':
                    result["added"] += 1
                else:
                    result["updated"] += 1

        # 保存索引
        index.commit()

        result["total"] = len(index.vectors)
        result["success"] = True

    except Exception as e:
        result["error"] = str(e)
        import traceback
        traceback.print_exc()

    return result


def search_semantic_simple(
    query_embedding: List[float],
    top_k: int = 20,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    使用简单向量索引进行语义搜索

    Args:
        query_embedding: 查询向量
        top_k: 返回结果数
        date_from: 起始日期
        date_to: 结束日期

    Returns:
        搜索结果列表
    """
    index = get_index()
    results = []

    search_results = index.search(query_embedding, top_k, date_from, date_to)

    for path, score in search_results:
        data = index.get(path)
        if data:
            results.append({
                'path': path,
                'date': data.get('date', ''),
                'similarity': round(score, 4),
                'source': 'semantic_simple'
            })

    return results


if __name__ == "__main__":
    # 测试代码
    print("Testing simple vector index...")

    index = get_index()
    print(f"Stats: {index.stats()}")

    # 添加测试向量
    test_vec = [0.1] * EMBEDDING_DIM
    index.add("test/path1.md", test_vec, "2026-03-05", "abc123")
    index.add("test/path2.md", [0.2] * EMBEDDING_DIM, "2026-03-04", "def456")
    index.commit()

    # 搜索测试
    results = index.search(test_vec, top_k=5)
    print(f"Search results: {results}")

    print(f"Updated stats: {index.stats()}")
