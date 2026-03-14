#!/usr/bin/env python3
"""
Life Index - Build Index Tool
索引构建工具（FTS + 向量索引）

Usage:
    # 增量更新（默认）
    python -m tools.build_index

    # 全量重建
    python -m tools.build_index --rebuild

    # 仅更新 FTS 索引
    python -m tools.build_index --fts-only

    # 仅更新向量索引
    python -m tools.build_index --vec-only

    # 查看统计信息
    python -m tools.build_index --stats
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Any

# 导入配置 (relative imports from parent tools package)
from ..lib.config import USER_DATA_DIR
from ..lib.search_index import (
    update_index as update_fts_index,
    get_stats as get_fts_stats,
)
from ..lib.semantic_search import update_vector_index, get_stats as get_vec_stats
from ..lib.file_lock import FileLock, LockTimeoutError, get_index_lock_path
from ..lib.errors import ErrorCode, create_error_response
from ..lib.logger import get_logger

# 获取日志器
logger = get_logger("build_index")


def build_all(
    incremental: bool = True, fts_only: bool = False, vec_only: bool = False
) -> Dict[str, Any]:
    """
    构建所有索引

    Args:
        incremental: True=增量更新，False=全量重建
        fts_only: 仅更新 FTS 索引
        vec_only: 仅更新向量索引

    Returns:
        构建结果
    """
    result = {"success": True, "fts": None, "vector": None, "duration_seconds": 0}

    import time

    start_time = time.time()

    # ===== 文件锁保护 =====
    # 使用文件锁保护索引构建，防止并发冲突
    lock = FileLock(get_index_lock_path(), timeout=60.0)

    try:
        with lock:
            # 更新 FTS 索引
            if not vec_only:
                logger.info("Updating FTS index...")
                try:
                    fts_result = update_fts_index(incremental=incremental)
                    result["fts"] = fts_result
                    if fts_result.get("success"):
                        logger.info(
                            f"  ✓ FTS: +{fts_result.get('added', 0)} added, "
                            f"~{fts_result.get('updated', 0)} updated, "
                            f"-{fts_result.get('removed', 0)} removed"
                        )
                    else:
                        logger.warning(f"  ✗ FTS failed: {fts_result.get('error')}")
                        result["success"] = False
                except (RuntimeError, IOError, OSError) as e:
                    logger.error(f"  ✗ FTS error: {e}")
                    result["fts"] = {"success": False, "error": str(e)}
                    result["success"] = False

            # 更新向量索引
            if not fts_only:
                logger.info("Updating vector index...")
                vec_success = False

                # 首先尝试 sqlite-vec
                try:
                    from ..lib.semantic_search import update_vector_index, get_model

                    model = get_model()
                    if model.load():
                        vec_result = update_vector_index(incremental=incremental)
                        if vec_result.get("success"):
                            result["vector"] = vec_result
                            logger.info(
                                f"  ✓ Vector (sqlite-vec): +{vec_result.get('added', 0)} added, "
                                f"~{vec_result.get('updated', 0)} updated"
                            )
                            vec_success = True
                except (ImportError, RuntimeError):
                    pass  # 失败时尝试简单索引

                # 如果 sqlite-vec 失败，使用简单向量索引
                if not vec_success:
                    try:
                        from ..lib.vector_index_simple import (
                            update_vector_index_simple,
                            get_model as get_simple_model,
                        )

                        model = get_simple_model()
                        if model.load():
                            vec_result = update_vector_index_simple(
                                model.encode, incremental=incremental
                            )
                            result["vector"] = vec_result
                            if vec_result.get("success"):
                                logger.info(
                                    f"  ✓ Vector (simple): +{vec_result.get('added', 0)} added, "
                                    f"~{vec_result.get('updated', 0)} updated"
                                )
                            else:
                                logger.warning(
                                    f"  ⚠ Vector (simple): {vec_result.get('error', 'Unknown error')}"
                                )
                        else:
                            logger.info(
                                f"  ⚠ Embedding model not available. Install: pip install sentence-transformers"
                            )
                    except (RuntimeError, IOError, OSError) as e:
                        logger.error(f"  ✗ Vector error: {e}")
                        result["vector"] = {"success": False, "error": str(e)}

    except LockTimeoutError as e:
        # 锁超时，返回结构化错误
        return create_error_response(
            ErrorCode.LOCK_TIMEOUT,
            f"无法获取索引锁，请稍后重试: {e}",
            {"lock_path": str(get_index_lock_path()), "timeout": 60.0},
            "等待几秒后重试，或检查是否有其他进程正在构建索引",
        )

    result["duration_seconds"] = round(time.time() - start_time, 2)
    logger.info(f"Completed in {result['duration_seconds']}s")

    return result


def show_stats() -> None:
    """显示索引统计信息"""
    logger.info("=" * 50)
    logger.info("Life Index - Search Index Statistics")
    logger.info("=" * 50)

    logger.info("\n📚 FTS Index (Full-Text Search):")
    fts_stats = get_fts_stats()
    logger.info(f"  Exists: {'Yes' if fts_stats['exists'] else 'No'}")
    logger.info(f"  Documents: {fts_stats['total_documents']}")
    logger.info(f"  Size: {fts_stats['db_size_mb']} MB")
    if fts_stats["last_updated"]:
        logger.info(f"  Last Updated: {fts_stats['last_updated']}")

    logger.info("\n🧠 Vector Index (Semantic Search):")
    # 尝试获取 sqlite-vec 统计
    try:
        from ..lib.semantic_search import get_stats as get_vec_stats

        vec_stats = get_vec_stats()
        if vec_stats["exists"] and vec_stats["total_vectors"] > 0:
            logger.info(f"  Backend: sqlite-vec")
            logger.info(f"  Exists: Yes")
            logger.info(f"  Vectors: {vec_stats['total_vectors']}")
            logger.info(f"  Size: {vec_stats['db_size_mb']} MB")
            logger.info(
                f"  Model Loaded: {'Yes' if vec_stats['model_loaded'] else 'No'}"
            )
        else:
            # 尝试获取简单向量索引统计
            raise Exception("sqlite-vec not available")
    except (ImportError, RuntimeError):
        try:
            from ..lib.vector_index_simple import get_index

            simple_index = get_index()
            simple_stats = simple_index.stats()
            logger.info(f"  Backend: simple_numpy")
            logger.info(f"  Exists: {'Yes' if simple_stats['exists'] else 'No'}")
            logger.info(f"  Vectors: {simple_stats['total_vectors']}")
            logger.info(f"  Size: {simple_stats['index_size_mb']} MB")
        except (ImportError, RuntimeError) as e:
            logger.info(f"  Status: Not available")
            logger.info(f"  Note: Install sentence-transformers for semantic search")

    logger.info("\n💾 Cache Directory:")
    cache_dir = USER_DATA_DIR / ".cache" / "models"
    if cache_dir.exists():
        total_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file())
        logger.info(f"  Location: {cache_dir}")
        logger.info(f"  Size: {round(total_size / (1024 * 1024), 2)} MB")
    else:
        logger.info("  Not created yet")

    logger.info("=" * 50)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Life Index - Build Search Index",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Daily incremental update (default)
    python -m tools.build_index

    # Full rebuild (monthly maintenance)
    python -m tools.build_index --rebuild

    # Only FTS index
    python -m tools.build_index --fts-only

    # View statistics
    python -m tools.build_index --stats
        """,
    )

    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Full rebuild (delete and recreate all indexes)",
    )

    parser.add_argument("--fts-only", action="store_true", help="Only update FTS index")

    parser.add_argument(
        "--vec-only", action="store_true", help="Only update vector index"
    )

    parser.add_argument("--stats", action="store_true", help="Show index statistics")

    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    if args.stats:
        show_stats()
        return

    # 执行索引构建
    result = build_all(
        incremental=not args.rebuild, fts_only=args.fts_only, vec_only=args.vec_only
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif not result["success"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
