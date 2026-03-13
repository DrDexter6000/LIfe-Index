#!/usr/bin/env python3
"""
Life Index - Write Journal Tool - Frontmatter
YAML frontmatter 格式化模块
"""

import json
from pathlib import Path
from typing import Any, Dict


def format_frontmatter(data: Dict[str, Any]) -> str:
    """格式化 YAML frontmatter - 统一使用 JSON 数组格式，保持字段顺序与历史日志一致"""
    lines = ["---"]

    # 标题（始终带引号）
    title = data.get("title", "")
    if title:
        lines.append(f'title: "{title}"')

    # 日期时间（ISO格式，始终带时间，不带引号保持与历史格式一致）
    date_str = data.get("date", "")
    if date_str:
        if len(date_str) == 10:  # YYYY-MM-DD
            from datetime import datetime

            time_str = datetime.now().strftime("%H:%M:%S")
            lines.append(f"date: {date_str}T{time_str}")
        else:
            lines.append(f"date: {date_str}")

    # 地点（始终带引号）
    location = data.get("location", "")
    lines.append(f'location: "{location}"')

    # 天气（始终带引号，即使为空）
    weather = data.get("weather", "")
    lines.append(f'weather: "{weather}"')

    # 心情（统一使用 JSON 数组格式，即使为空）
    mood = data.get("mood", [])
    if not isinstance(mood, list):
        mood = [mood] if mood else []
    lines.append(f"mood: {json.dumps(mood, ensure_ascii=False)}")

    # 人物（统一使用 JSON 数组格式，即使为空）
    people = data.get("people", [])
    if not isinstance(people, list):
        people = [people] if people else []
    lines.append(f"people: {json.dumps(people, ensure_ascii=False)}")

    # 标签（统一使用 JSON 数组格式，即使为空）
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = [tags] if tags else []
    lines.append(f"tags: {json.dumps(tags, ensure_ascii=False)}")

    # 项目（始终带引号，即使为空）- 注意顺序：在 topic 之前
    project = data.get("project", "")
    lines.append(f'project: "{project}"')

    # 主题（统一使用 JSON 数组格式，即使为空）- 注意顺序：在 project 之后
    topic = data.get("topic", [])
    if not isinstance(topic, list):
        topic = [topic] if topic else []
    lines.append(f"topic: {json.dumps(topic, ensure_ascii=False)}")

    # 摘要（始终带引号，即使为空）
    abstract = data.get("abstract", "")
    lines.append(f'abstract: "{abstract}"')

    # 链接（统一使用 JSON 数组格式，即使为空）- 与历史日志格式保持一致
    links = data.get("links", [])
    if not isinstance(links, list):
        links = [links] if links else []
    lines.append(f"links: {json.dumps(links, ensure_ascii=False)}")

    # 附件（统一使用 JSON 数组格式，即使为空）
    attachments = data.get("attachments", [])
    att_list = []
    for att in attachments:
        if isinstance(att, dict):
            path = att.get("rel_path", "") or att.get("filename", "")
            if path and not path.startswith("["):
                att_list.append(path)
        elif isinstance(att, str):
            att_list.append(att)
    lines.append(f"attachments: {json.dumps(att_list, ensure_ascii=False)}")

    lines.append("---")
    return "\n".join(lines)


def format_content(data: Dict[str, Any]) -> str:
    """格式化日志内容"""
    lines = []

    # 标题
    title = data.get("title", "")
    if title:
        lines.append(f"# {title}")
        lines.append("")

    # 正文
    content = data.get("content", "")
    if content:
        lines.append(content)
        lines.append("")

    # 附件引用
    attachments = data.get("attachments", [])
    if attachments:
        lines.append("## Attachments")
        for att in attachments:
            filename = att.get("filename", "")
            rel_path = att.get("rel_path", "")
            description = att.get("description", "")
            # 优先使用 rel_path，回退到基于 filename 构建的路径
            path = rel_path or f"../../../Attachments/{filename}"
            lines.append(f"- [{filename}]({path}) - {description}")
        lines.append("")

    return "\n".join(lines)
