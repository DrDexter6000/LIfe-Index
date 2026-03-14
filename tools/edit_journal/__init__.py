#!/usr/bin/env python3
"""
Life Index - Edit Journal Tool
编辑已存在的日志文件，支持 frontmatter 字段修改和正文编辑

Usage:
    python -m tools.edit_journal --journal "Journals/2026/03/life-index_2026-03-05_001.md" \\
        --set-location "Beijing, China" --set-weather "多云"

Public API:
    from tools.edit_journal import edit_journal
    result = edit_journal(journal_path=path, frontmatter_updates={"weather": "晴天"})
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# 导入配置 (relative imports from parent tools package)
from ..lib.config import JOURNALS_DIR, BY_TOPIC_DIR, ensure_dirs
from ..lib.frontmatter import (
    parse_journal_file,
    format_frontmatter,
    update_frontmatter_fields,
)
from ..lib.file_lock import FileLock, LockTimeoutError, get_journals_lock_path
from ..lib.errors import ErrorCode, create_error_response
from ..lib.logger import get_logger

logger = get_logger(__name__)


def parse_journal(file_path: Path) -> Tuple[Dict[str, Any], str]:
    """
    解析日志文件，返回 (frontmatter_dict, content_body)
    使用 lib/frontmatter 模块实现
    """
    metadata = parse_journal_file(file_path)
    return metadata, metadata.get("_body", "")


# format_frontmatter 已移至 lib/frontmatter 模块


def remove_from_index(index_file: Path, journal_filename: str) -> bool:
    """从索引文件中移除指定日志条目"""
    if not index_file.exists():
        return False

    content = index_file.read_text(encoding="utf-8")
    lines = content.split("\n")

    new_lines = []
    removed = False
    for line in lines:
        if journal_filename in line and line.strip().startswith("- ["):
            removed = True
            logger.debug(f"从索引移除：{journal_filename}")
            continue
        new_lines.append(line)

    if removed:
        index_file.write_text("\n".join(new_lines), encoding="utf-8")
        logger.info(f"已更新索引文件：{index_file.name}")

    return removed


def add_to_index(index_file: Path, journal_path: Path, data: Dict[str, Any]) -> None:
    """添加日志条目到索引文件"""
    date_str = data.get("date", "")[:10] if data.get("date") else ""
    title = data.get("title", "无标题")
    rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

    entry = f"- [{date_str}] [{title}]({rel_path})"

    BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)

    if index_file.exists():
        content = index_file.read_text(encoding="utf-8")
        if entry not in content:
            with open(index_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
            logger.debug(f"添加条目到索引：{index_file.name}")
    else:
        # 确定索引类型和名称
        name = (
            index_file.stem.replace("主题_", "")
            .replace("项目_", "")
            .replace("标签_", "")
        )
        if index_file.stem.startswith("主题_"):
            header = f"# 主题：{name}\n\n"
        elif index_file.stem.startswith("项目_"):
            header = f"# 项目：{name}\n\n"
        elif index_file.stem.startswith("标签_"):
            header = f"# 标签：{name}\n\n"
        else:
            header = f"# {name}\n\n"

        with open(index_file, "w", encoding="utf-8") as f:
            f.write(header + entry + "\n")
        logger.info(f"创建索引文件：{index_file.name}")


def update_indices_for_change(
    journal_path: Path, old_data: Dict[str, Any], new_data: Dict[str, Any]
) -> List[str]:
    """
    根据数据变更更新索引
    返回更新的索引文件列表
    """
    updated_indices = []
    journal_filename = journal_path.name

    # 检查 topic 变更
    old_topics = _normalize_to_list(old_data.get("topic"))
    new_topics = _normalize_to_list(new_data.get("topic"))

    # 移除旧 topic 索引
    for topic in old_topics:
        if topic and topic not in new_topics:
            idx_file = BY_TOPIC_DIR / f"主题_{topic}.md"
            logger.info(f"检测到 topic 变更：{topic} -> 移除")
            if remove_from_index(idx_file, journal_filename):
                updated_indices.append(str(idx_file))

    # 添加到新 topic 索引
    for topic in new_topics:
        if topic:
            idx_file = BY_TOPIC_DIR / f"主题_{topic}.md"
            logger.info(f"检测到 topic 变更：添加 {topic}")
            add_to_index(idx_file, journal_path, new_data)
            if str(idx_file) not in updated_indices:
                updated_indices.append(str(idx_file))

    # 检查 project 变更
    old_project = old_data.get("project", "")
    new_project = new_data.get("project", "")

    if old_project != new_project:
        logger.info(f"检测到 project 变更：{old_project} -> {new_project}")
        # 移除旧 project 索引
        if old_project:
            idx_file = BY_TOPIC_DIR / f"项目_{old_project}.md"
            if remove_from_index(idx_file, journal_filename):
                if str(idx_file) not in updated_indices:
                    updated_indices.append(str(idx_file))

        # 添加到新 project 索引
        if new_project:
            idx_file = BY_TOPIC_DIR / f"项目_{new_project}.md"
            add_to_index(idx_file, journal_path, new_data)
            if str(idx_file) not in updated_indices:
                updated_indices.append(str(idx_file))

    # 检查 tags 变更
    old_tags = set(_normalize_to_list(old_data.get("tags")))
    new_tags = set(_normalize_to_list(new_data.get("tags")))

    # 移除旧 tag 索引
    for tag in old_tags - new_tags:
        if tag:
            idx_file = BY_TOPIC_DIR / f"标签_{tag}.md"
            logger.debug(f"检测到 tag 移除：{tag}")
            if remove_from_index(idx_file, journal_filename):
                if str(idx_file) not in updated_indices:
                    updated_indices.append(str(idx_file))

    # 添加新 tag 索引
    for tag in new_tags - old_tags:
        if tag:
            idx_file = BY_TOPIC_DIR / f"标签_{tag}.md"
            logger.debug(f"检测到 tag 添加：{tag}")
            add_to_index(idx_file, journal_path, new_data)
            if str(idx_file) not in updated_indices:
                updated_indices.append(str(idx_file))

    return updated_indices


def _normalize_to_list(value: Any) -> List[str]:
    """将值规范化为字符串列表"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if v]
    if isinstance(value, str):
        return [value]
    return []


def edit_journal(
    journal_path: Path,
    frontmatter_updates: Dict[str, Any],
    append_content: Optional[str] = None,
    replace_content: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    编辑日志文件

    Args:
        journal_path: 日志文件路径
        frontmatter_updates: 要更新的 frontmatter 字段
        append_content: 追加到正文的内容
        replace_content: 替换正文的内容（优先级高于 append）
        dry_run: 模拟运行

    Returns:
        {
            "success": bool,
            "journal_path": str,
            "changes": {"field": {"old": val, "new": val}, ...},
            "content_modified": bool,
            "indices_updated": [str],
            "error": str (optional)
        }
    """
    result: Dict[str, Any] = {
        "success": False,
        "journal_path": str(journal_path),
        "changes": {},
        "content_modified": False,
        "indices_updated": [],
        "error": None,
    }

    try:
        logger.info(f"开始编辑日志：{journal_path.name}")

        if not journal_path.exists():
            logger.error(f"日志文件不存在：{journal_path}")
            return create_error_response(
                ErrorCode.JOURNAL_NOT_FOUND,
                f"日志文件不存在：{journal_path}",
                {"path": str(journal_path)},
                "请检查文件路径是否正确",
            )

        if not frontmatter_updates and not append_content and not replace_content:
            logger.warning("未指定任何修改")
            return create_error_response(
                ErrorCode.NO_CHANGES_SPECIFIED,
                "未指定任何修改内容",
                None,
                "请使用 --set-*, --append-content 或 --replace-content 指定修改",
            )

        # 使用 lib-frontmatter 更新
        # 构建完整数据用于格式化
        metadata = parse_journal_file(journal_path)
        old_frontmatter = {k: v for k, v in metadata.items() if not k.startswith("_")}
        old_body = metadata.get("_body", "")

        # 应用 frontmatter 更新
        new_frontmatter = dict(old_frontmatter)
        for key, value in frontmatter_updates.items():
            old_value = new_frontmatter.get(key)

            # 特殊处理：空字符串视为删除字段
            if value == "" or value is None:
                if key in new_frontmatter:
                    del new_frontmatter[key]
                    result["changes"][key] = {"old": old_value, "new": None}
                    logger.debug(f"删除字段：{key}")
            else:
                new_frontmatter[key] = value
                if old_value != value:
                    result["changes"][key] = {"old": old_value, "new": value}
                    logger.debug(f"更新字段：{key} = {value}")

        # 处理正文修改
        new_body = old_body
        if replace_content is not None:
            new_body = replace_content
            result["content_modified"] = True
            logger.info("替换正文内容")
        elif append_content is not None:
            if old_body:
                new_body = old_body + "\n\n" + append_content
            else:
                new_body = append_content
            result["content_modified"] = True
            logger.info("追加正文内容")

        if dry_run:
            logger.info("模拟运行模式（dry-run）")
            result["success"] = True
            result["preview"] = {
                "frontmatter": format_frontmatter(new_frontmatter),
                "body_preview": new_body[:200] + "..."
                if len(new_body) > 200
                else new_body,
            }
            return result

        # ===== 文件锁保护 =====
        # 使用文件锁保护写入操作，防止并发冲突
        lock = FileLock(get_journals_lock_path(), timeout=30.0)

        try:
            with lock:
                logger.debug("获取文件锁成功")
                # 写入文件
                new_content = format_frontmatter(new_frontmatter) + "\n\n" + new_body
                journal_path.write_text(new_content, encoding="utf-8")
                logger.info(f"已写入文件：{journal_path.name}")

                # 更新索引（如果相关字段变更）
                if any(k in result["changes"] for k in ["topic", "project", "tags"]):
                    logger.info("检测到索引相关字段变更，更新索引...")
                    updated = update_indices_for_change(
                        journal_path, old_frontmatter, new_frontmatter
                    )
                    result["indices_updated"] = updated
                    logger.info(f"已更新 {len(updated)} 个索引文件")

        except LockTimeoutError as e:
            # 锁超时，返回结构化错误
            logger.error(f"文件锁超时：{e}")
            return create_error_response(
                ErrorCode.LOCK_TIMEOUT,
                f"无法获取写入锁，请稍后重试：{e}",
                {"lock_path": str(get_journals_lock_path()), "timeout": 30.0},
                "等待几秒后重试，或检查是否有其他进程正在编辑",
            )

        result["success"] = True
        logger.info(f"编辑完成：{journal_path.name}")

    except (IOError, OSError) as e:
        logger.error(f"文件操作失败：{e}")
        return create_error_response(
            ErrorCode.WRITE_FAILED,
            f"文件操作失败：{e}",
            {"path": str(journal_path)},
            "请检查文件权限或磁盘空间",
        )

    return result


__all__ = ["edit_journal"]
