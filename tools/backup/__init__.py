#!/usr/bin/env python3
"""
Life Index - Backup Tool
数据备份工具（支持增量备份）

Usage:
    python -m tools.backup --dest /path/to/backup
    python -m tools.backup --dest /path/to/backup --full
    python -m tools.backup --dest /path/to/backup --dry-run

Public API:
    from tools.backup import create_backup
    result = create_backup(dest_path="/path/to/backup")
"""

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from ..lib.config import (
    JOURNALS_DIR,
    BY_TOPIC_DIR,
    ATTACHMENTS_DIR,
    USER_DATA_DIR,
    ensure_dirs,
)
from ..lib.logger import get_logger

logger = get_logger(__name__)


def calculate_file_hash(file_path: Path) -> str:
    """计算文件的 MD5 哈希值"""
    hash_md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except (IOError, OSError) as e:
        logger.error(f"计算哈希失败 {file_path}: {e}")
        return ""


def load_backup_manifest(backup_dir: Path) -> Dict[str, Any]:
    """加载备份清单文件"""
    manifest_path = backup_dir / ".life-index-backup-manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"无法加载备份清单: {e}")
    return {"backups": [], "files": {}}


def save_backup_manifest(backup_dir: Path, manifest: Dict[str, Any]) -> None:
    """保存备份清单文件"""
    manifest_path = backup_dir / ".life-index-backup-manifest.json"
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error(f"无法保存备份清单: {e}")


def create_backup(
    dest_path: str,
    full: bool = False,
    dry_run: bool = False,
    exclude_patterns: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    创建 Life Index 数据备份

    Args:
        dest_path: 备份目标路径
        full: 是否执行全量备份（默认增量）
        dry_run: 模拟运行，不实际复制文件
        exclude_patterns: 排除的文件模式列表

    Returns:
        {
            "success": bool,
            "backup_path": str,
            "files_backed_up": int,
            "files_skipped": int,
            "errors": List[str],
            "manifest_path": str,
        }
    """
    result = {
        "success": False,
        "backup_path": "",
        "files_backed_up": 0,
        "files_skipped": 0,
        "errors": [],
        "manifest_path": "",
    }

    try:
        dest = Path(dest_path)
        if not dry_run:
            dest.mkdir(parents=True, exist_ok=True)

        # 创建带时间戳的子目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_subdir = dest / f"life-index-backup-{timestamp}"
        if not dry_run:
            backup_subdir.mkdir(parents=True, exist_ok=True)

        result["backup_path"] = str(backup_subdir)

        # 加载之前的备份清单（用于增量备份）
        manifest = load_backup_manifest(dest) if not full else {"files": {}}

        # 默认排除模式
        exclude_patterns = exclude_patterns or []
        exclude_patterns.extend(
            [
                ".life-index-backup-manifest.json",
                "*.tmp",
                ".cache",
            ]
        )

        def should_exclude(file_path: Path) -> bool:
            """检查文件是否应该被排除"""
            for pattern in exclude_patterns:
                if pattern in str(file_path):
                    return True
            return False

        def backup_directory(src_dir: Path, dest_subdir: str) -> None:
            """备份单个目录"""
            if not src_dir.exists():
                logger.warning(f"源目录不存在: {src_dir}")
                return

            backup_dest = backup_subdir / dest_subdir
            if not dry_run:
                backup_dest.mkdir(parents=True, exist_ok=True)

            for file_path in src_dir.rglob("*"):
                if file_path.is_file() and not should_exclude(file_path):
                    try:
                        # 计算相对路径
                        rel_path = file_path.relative_to(src_dir)
                        dest_file = backup_dest / rel_path

                        # 增量备份：检查文件是否已更改
                        file_hash = calculate_file_hash(file_path)
                        file_key = f"{dest_subdir}/{rel_path}"

                        if not full and file_key in manifest.get("files", {}):
                            old_hash = manifest["files"][file_key].get("hash", "")
                            if old_hash == file_hash:
                                result["files_skipped"] += 1
                                continue

                        if not dry_run:
                            dest_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(file_path, dest_file)

                        result["files_backed_up"] += 1

                        # 更新清单
                        manifest["files"][file_key] = {
                            "hash": file_hash,
                            "mtime": file_path.stat().st_mtime,
                            "size": file_path.stat().st_size,
                        }

                    except (IOError, OSError) as e:
                        error_msg = f"备份失败 {file_path}: {e}"
                        logger.error(error_msg)
                        result["errors"].append(error_msg)

        # 备份各个目录
        logger.info("备份日志文件...")
        backup_directory(JOURNALS_DIR, "Journals")

        logger.info("备份索引文件...")
        backup_directory(BY_TOPIC_DIR, "by-topic")

        logger.info("备份附件文件...")
        backup_directory(ATTACHMENTS_DIR, "attachments")

        # 保存备份清单
        if not dry_run:
            backup_record = {
                "timestamp": timestamp,
                "type": "full" if full else "incremental",
                "path": str(backup_subdir),
                "files_backed_up": result["files_backed_up"],
                "files_skipped": result["files_skipped"],
            }
            manifest["backups"].append(backup_record)
            save_backup_manifest(dest, manifest)
            result["manifest_path"] = str(dest / ".life-index-backup-manifest.json")

        result["success"] = len(result["errors"]) == 0

        logger.info(
            f"备份完成: {result['files_backed_up']} 个文件已备份, "
            f"{result['files_skipped']} 个文件已跳过"
        )

    except (OSError, IOError, RuntimeError) as e:
        error_msg = f"备份过程出错: {e}"
        logger.error(error_msg)
        result["errors"].append(error_msg)

    return result


def list_backups(backup_dir: Path) -> List[Dict[str, Any]]:
    """列出所有备份记录"""
    manifest = load_backup_manifest(backup_dir)
    return manifest.get("backups", [])


def restore_backup(
    backup_path: str,
    dest_path: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    从备份恢复数据

    Args:
        backup_path: 备份目录路径
        dest_path: 恢复目标路径（默认 USER_DATA_DIR）
        dry_run: 模拟运行

    Returns:
        恢复结果
    """
    result = {
        "success": False,
        "files_restored": 0,
        "errors": [],
    }

    try:
        backup = Path(backup_path)
        dest = Path(dest_path) if dest_path else USER_DATA_DIR

        if not backup.exists():
            result["errors"].append(f"备份目录不存在: {backup}")
            return result

        # 恢复各个目录
        for subdir in ["Journals", "by-topic", "attachments"]:
            src = backup / subdir
            if src.exists():
                dst = dest / subdir
                if not dry_run:
                    dst.mkdir(parents=True, exist_ok=True)

                for file_path in src.rglob("*"):
                    if file_path.is_file():
                        try:
                            rel_path = file_path.relative_to(src)
                            dest_file = dst / rel_path

                            if not dry_run:
                                dest_file.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(file_path, dest_file)

                            result["files_restored"] += 1
                        except (IOError, OSError) as e:
                            error_msg = f"恢复失败 {file_path}: {e}"
                            logger.error(error_msg)
                            result["errors"].append(error_msg)

        result["success"] = len(result["errors"]) == 0
        logger.info(f"恢复完成: {result['files_restored']} 个文件已恢复")

    except (OSError, IOError, RuntimeError) as e:
        error_msg = f"恢复过程出错: {e}"
        logger.error(error_msg)
        result["errors"].append(error_msg)

    return result


__all__ = ["create_backup", "restore_backup", "list_backups"]
