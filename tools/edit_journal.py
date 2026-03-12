#!/usr/bin/env python3
"""
Life Index - Edit Journal Tool
编辑已存在的日志文件，支持 frontmatter 字段修改和正文编辑

Usage:
    # 编辑 frontmatter 字段
    python edit_journal.py --journal "Journals/2026/03/life-index_2026-03-05_001.md" \
        --set-location "Beijing, China" \
        --set-weather "多云"

    # 追加正文内容
    python edit_journal.py --journal "..." --append-content "补充内容"

    # 替换正文内容（保留 frontmatter）
    python edit_journal.py --journal "..." --replace-content "新内容"

    # 修改 topic（触发索引重建）
    python edit_journal.py --journal "..." --set-topic "learn"
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# 导入配置
TOOLS_DIR = Path(__file__).parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from lib.config import JOURNALS_DIR, BY_TOPIC_DIR
    from lib.frontmatter import (
        parse_journal_file,
        format_frontmatter,
        update_frontmatter_fields,
    )
except ImportError:
    PROJECT_ROOT = Path(__file__).parent.parent
    JOURNALS_DIR = PROJECT_ROOT / "journals"
    BY_TOPIC_DIR = PROJECT_ROOT / "by-topic"


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
            continue
        new_lines.append(line)

    if removed:
        index_file.write_text("\n".join(new_lines), encoding="utf-8")

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
    else:
        # 确定索引类型和名称
        name = (
            index_file.stem.replace("主题_", "")
            .replace("项目_", "")
            .replace("标签_", "")
        )
        if index_file.stem.startswith("主题_"):
            header = f"# 主题: {name}\n\n"
        elif index_file.stem.startswith("项目_"):
            header = f"# 项目: {name}\n\n"
        elif index_file.stem.startswith("标签_"):
            header = f"# 标签: {name}\n\n"
        else:
            header = f"# {name}\n\n"

        with open(index_file, "w", encoding="utf-8") as f:
            f.write(header + entry + "\n")


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
            if remove_from_index(idx_file, journal_filename):
                updated_indices.append(str(idx_file))

    # 添加到新 topic 索引
    for topic in new_topics:
        if topic:
            idx_file = BY_TOPIC_DIR / f"主题_{topic}.md"
            add_to_index(idx_file, journal_path, new_data)
            if str(idx_file) not in updated_indices:
                updated_indices.append(str(idx_file))

    # 检查 project 变更
    old_project = old_data.get("project", "")
    new_project = new_data.get("project", "")

    if old_project != new_project:
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
            if remove_from_index(idx_file, journal_filename):
                if str(idx_file) not in updated_indices:
                    updated_indices.append(str(idx_file))

    # 添加新 tag 索引
    for tag in new_tags - old_tags:
        if tag:
            idx_file = BY_TOPIC_DIR / f"标签_{tag}.md"
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
        if not journal_path.exists():
            raise FileNotFoundError(f"日志文件不存在: {journal_path}")

        # 使用 lib/frontmatter 更新
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
            else:
                new_frontmatter[key] = value
                if old_value != value:
                    result["changes"][key] = {"old": old_value, "new": value}

        # 处理正文修改
        new_body = old_body
        if replace_content is not None:
            new_body = replace_content
            result["content_modified"] = True
        elif append_content is not None:
            if old_body:
                new_body = old_body + "\n\n" + append_content
            else:
                new_body = append_content
            result["content_modified"] = True

        if dry_run:
            result["success"] = True
            result["preview"] = {
                "frontmatter": format_frontmatter(new_frontmatter),
                "body_preview": new_body[:200] + "..."
                if len(new_body) > 200
                else new_body,
            }
            return result

        # 写入文件
        new_content = format_frontmatter(new_frontmatter) + "\n\n" + new_body
        journal_path.write_text(new_content, encoding="utf-8")

        # 更新索引（如果相关字段变更）
        if any(k in result["changes"] for k in ["topic", "project", "tags"]):
            updated = update_indices_for_change(
                journal_path, old_frontmatter, new_frontmatter
            )
            result["indices_updated"] = updated

        result["success"] = True

    except Exception as e:
        result["error"] = str(e)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Life Index - Edit Journal Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 设置地点和天气
    python edit_journal.py --journal "Journals/2026/03/life-index_2026-03-05_001.md" \\
        --set-location "Beijing, China" --set-weather "多云"

    # 追加正文内容
    python edit_journal.py --journal "..." --append-content "下午还讨论了部署方案。"

    # 修改 topic（会触发索引重建）
    python edit_journal.py --journal "..." --set-topic "learn"

    # 批量修改多个字段
    python edit_journal.py --journal "..." \\
        --set-location "Shanghai, China" \\
        --set-mood "开心,兴奋" \\
        --set-project "New-Project"
        """,
    )

    parser.add_argument(
        "--journal", required=True, help="日志文件路径（相对或绝对路径）"
    )

    # Frontmatter 字段设置
    parser.add_argument("--set-title", help="设置标题")
    parser.add_argument("--set-date", help="设置日期")
    parser.add_argument("--set-location", help="设置地点")
    parser.add_argument("--set-weather", help="设置天气")
    parser.add_argument("--set-mood", help="设置心情（逗号分隔多个）")
    parser.add_argument("--set-people", help="设置人物（逗号分隔多个）")
    parser.add_argument("--set-tags", help="设置标签（逗号分隔多个）")
    parser.add_argument("--set-project", help="设置项目")
    parser.add_argument("--set-topic", help="设置主题（逗号分隔多个）")
    parser.add_argument("--set-abstract", help="设置摘要")

    # 内容编辑
    content_group = parser.add_mutually_exclusive_group()
    content_group.add_argument("--append-content", help="追加内容到正文末尾")
    content_group.add_argument(
        "--replace-content", help="替换整个正文内容（保留 frontmatter）"
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="模拟运行，不实际写入文件"
    )

    parser.add_argument("--verbose", action="store_true", help="输出详细日志")

    args = parser.parse_args()

    # 解析日志路径
    journal_path = Path(args.journal)
    if not journal_path.is_absolute():
        # 尝试相对于用户数据目录解析
        try:
            from lib.config import USER_DATA_DIR

            base_dir = USER_DATA_DIR
        except ImportError:
            base_dir = Path.cwd()

        journal_path = base_dir / journal_path

    # 收集 frontmatter 更新
    frontmatter_updates = {}

    if args.set_title is not None:
        frontmatter_updates["title"] = args.set_title
    if args.set_date is not None:
        frontmatter_updates["date"] = args.set_date
    if args.set_location is not None:
        frontmatter_updates["location"] = args.set_location
    if args.set_weather is not None:
        frontmatter_updates["weather"] = args.set_weather
    if args.set_mood is not None:
        frontmatter_updates["mood"] = [
            m.strip() for m in args.set_mood.split(",") if m.strip()
        ]
    if args.set_people is not None:
        frontmatter_updates["people"] = [
            p.strip() for p in args.set_people.split(",") if p.strip()
        ]
    if args.set_tags is not None:
        frontmatter_updates["tags"] = [
            t.strip() for t in args.set_tags.split(",") if t.strip()
        ]
    if args.set_project is not None:
        frontmatter_updates["project"] = args.set_project
    if args.set_topic is not None:
        frontmatter_updates["topic"] = [
            t.strip() for t in args.set_topic.split(",") if t.strip()
        ]
    if args.set_abstract is not None:
        frontmatter_updates["abstract"] = args.set_abstract

    # 执行编辑
    result = edit_journal(
        journal_path=journal_path,
        frontmatter_updates=frontmatter_updates,
        append_content=args.append_content,
        replace_content=args.replace_content,
        dry_run=args.dry_run,
    )

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
