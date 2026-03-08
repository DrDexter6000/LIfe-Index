#!/usr/bin/env python3
"""
Life Index - Write Journal Tool
写入日志并自动维护索引体系

Usage:
    python write_journal.py --data '{"title": "...", "content": "...", ...}'
    python write_journal.py --data @input.json
    python write_journal.py --dry-run --data '...'
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# 导入配置（优先使用用户数据目录）
import sys
TOOLS_DIR = Path(__file__).parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from lib.config import JOURNALS_DIR, BY_TOPIC_DIR, ATTACHMENTS_DIR
except ImportError:
    # 回退到项目目录（用于开发测试）
    PROJECT_ROOT = Path(__file__).parent.parent
    JOURNALS_DIR = PROJECT_ROOT / "journals"
    BY_TOPIC_DIR = PROJECT_ROOT / "by-topic"
    ATTACHMENTS_DIR = PROJECT_ROOT / "attachments"


def get_year_month(date_str: str) -> tuple:
    """从日期字符串提取年和月"""
    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    return dt.year, dt.month


def generate_filename(date_str: str, sequence: int = 1) -> str:
    """生成日志文件名: life-index_YYYY-MM-DD_XXX.md"""
    date_part = date_str[:10]  # YYYY-MM-DD
    return f"life-index_{date_part}_{sequence:03d}.md"


def get_next_sequence(date_str: str) -> int:
    """获取指定日期的下一个序列号"""
    year, month = get_year_month(date_str)
    month_dir = JOURNALS_DIR / str(year) / f"{month:02d}"

    if not month_dir.exists():
        return 1

    date_part = date_str[:10]
    pattern = f"life-index_{date_part}_*.md"
    existing = list(month_dir.glob(pattern))

    if not existing:
        return 1

    # 提取最大序列号
    max_seq = 0
    for f in existing:
        match = re.search(rf"life-index_{date_part}_(\d+)\.md$", f.name)
        if match:
            max_seq = max(max_seq, int(match.group(1)))

    return max_seq + 1


def format_frontmatter(data: Dict[str, Any]) -> str:
    """格式化 YAML frontmatter - 统一使用 JSON 数组格式，保持字段顺序一致"""
    lines = ["---"]

    # 标题（始终带引号）
    title = data.get("title", "")
    if title:
        lines.append(f'title: "{title}"')

    # 日期时间（ISO格式，始终带时间）
    date_str = data.get("date", "")
    if date_str:
        if len(date_str) == 10:  # YYYY-MM-DD
            from datetime import datetime
            time_str = datetime.now().strftime("%H:%M:%S")
            lines.append(f'date: "{date_str}T{time_str}"')
        else:
            lines.append(f'date: "{date_str}"')

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
    lines.append(f'mood: {json.dumps(mood, ensure_ascii=False)}')

    # 人物（统一使用 JSON 数组格式，即使为空）
    people = data.get("people", [])
    if not isinstance(people, list):
        people = [people] if people else []
    lines.append(f'people: {json.dumps(people, ensure_ascii=False)}')

    # 标签（统一使用 JSON 数组格式，即使为空）
    tags = data.get("tags", [])
    if not isinstance(tags, list):
        tags = [tags] if tags else []
    lines.append(f'tags: {json.dumps(tags, ensure_ascii=False)}')

    # 项目（始终带引号，即使为空）- 注意顺序：在 topic 之前
    project = data.get("project", "")
    lines.append(f'project: "{project}"')

    # 主题（统一使用 JSON 数组格式，即使为空）- 注意顺序：在 project 之后
    topic = data.get("topic", [])
    if not isinstance(topic, list):
        topic = [topic] if topic else []
    lines.append(f'topic: {json.dumps(topic, ensure_ascii=False)}')

    # 摘要（始终带引号，即使为空）
    abstract = data.get("abstract", "")
    lines.append(f'abstract: "{abstract}"')

    # 链接（统一使用 JSON 数组格式，即使为空）
    links = data.get("links", [])
    if not isinstance(links, list):
        links = [links] if links else []
    lines.append(f'links: {json.dumps(links, ensure_ascii=False)}')

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
    lines.append(f'attachments: {json.dumps(att_list, ensure_ascii=False)}')

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


def update_topic_index(topic, journal_path: Path, data: Dict[str, Any]) -> List[Path]:
    """更新主题索引文件 - 支持单个主题或主题列表"""
    if not topic:
        return []

    # 统一处理为列表
    if isinstance(topic, str):
        topics = [topic]
    elif isinstance(topic, list):
        topics = topic
    else:
        return []

    date_str = data.get("date", "")[:10]
    title = data.get("title", "无标题")
    rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

    entry = f"- [{date_str}] [{title}]({rel_path})"

    updated = []
    for t in topics:
        if not t:
            continue
        BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)
        index_file = BY_TOPIC_DIR / f"主题_{t}.md"

        if index_file.exists():
            content = index_file.read_text(encoding='utf-8')
            if entry not in content:
                with open(index_file, 'a', encoding='utf-8') as f:
                    f.write(entry + "\n")
        else:
            with open(index_file, 'w', encoding='utf-8') as f:
                f.write(f"# 主题: {t}\n\n")
                f.write(entry + "\n")

        updated.append(index_file)

    return updated


def update_project_index(project: str, journal_path: Path, data: Dict[str, Any]) -> Path:
    """更新项目索引文件"""
    if not project:
        return None

    BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)
    index_file = BY_TOPIC_DIR / f"项目_{project}.md"

    date_str = data.get("date", "")[:10]
    title = data.get("title", "无标题")
    rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

    entry = f"- [{date_str}] [{title}]({rel_path})"

    if index_file.exists():
        content = index_file.read_text(encoding='utf-8')
        if entry not in content:
            with open(index_file, 'a', encoding='utf-8') as f:
                f.write(entry + "\n")
    else:
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(f"# 项目: {project}\n\n")
            f.write(entry + "\n")

    return index_file


def update_tag_indices(tags: List[str], journal_path: Path, data: Dict[str, Any]) -> List[Path]:
    """更新标签索引文件"""
    updated = []

    for tag in tags:
        if not tag:
            continue

        BY_TOPIC_DIR.mkdir(parents=True, exist_ok=True)
        index_file = BY_TOPIC_DIR / f"标签_{tag}.md"

        date_str = data.get("date", "")[:10]
        title = data.get("title", "无标题")
        rel_path = os.path.relpath(journal_path, JOURNALS_DIR.parent).replace("\\", "/")

        entry = f"- [{date_str}] [{title}]({rel_path})"

        if index_file.exists():
            content = index_file.read_text(encoding='utf-8')
            if entry not in content:
                with open(index_file, 'a', encoding='utf-8') as f:
                    f.write(entry + "\n")
        else:
            with open(index_file, 'w', encoding='utf-8') as f:
                f.write(f"# 标签: {tag}\n\n")
                f.write(entry + "\n")

        updated.append(index_file)

    return updated


def process_attachments(attachments: List[Dict[str, str]], date_str: str, dry_run: bool = False) -> List[Dict[str, str]]:
    """
    处理附件复制

    Args:
        attachments: 附件列表，每项包含 source_path 和可选的 description
        date_str: 日期字符串，用于确定附件存储路径
        dry_run: 是否为模拟运行

    Returns:
        处理后的附件列表，包含 filename 和 description
    """
    if not attachments:
        return []

    processed = []
    year, month = get_year_month(date_str)
    att_dir = ATTACHMENTS_DIR / str(year) / f"{month:02d}"

    for idx, att in enumerate(attachments):
        source_path = att.get("source_path", "")
        description = att.get("description", "")

        if not source_path or not os.path.exists(source_path):
            processed.append({
                "filename": f"[未找到: {source_path}]",
                "description": description,
                "error": "源文件不存在"
            })
            continue

        # 生成目标文件名（处理重名）
        source_name = Path(source_path).name
        base_name = Path(source_name).stem
        ext = Path(source_name).suffix

        if dry_run:
            target_name = source_name
        else:
            # 检查是否已存在同名文件
            target_name = source_name
            counter = 1
            while (att_dir / target_name).exists():
                target_name = f"{base_name}_{counter:03d}{ext}"
                counter += 1

            # 复制文件
            att_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(source_path, att_dir / target_name)

        # 生成相对路径 (../../../Attachments/YYYY/MM/filename)
        rel_path = f"../../../Attachments/{year}/{month:02d}/{target_name}"

        processed.append({
            "filename": target_name,
            "rel_path": rel_path,
            "description": description,
            "original_name": source_name
        })

    return processed


def query_weather_for_location(location: str, date_str: str = "") -> str:
    """
    调用 query_weather.py 工具获取天气信息

    Args:
        location: 地点名称
        date_str: 日期字符串（可选，用于历史天气查询）

    Returns:
        天气描述字符串，失败返回空字符串
    """
    try:
        cmd = [
            sys.executable,
            str(TOOLS_DIR / "query_weather.py"),
            "--location", location
        ]
        if date_str:
            cmd.extend(["--date", date_str[:10]])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=15
        )

        if proc.returncode == 0:
            output = json.loads(proc.stdout)
            # 提取天气描述
            if isinstance(output, dict):
                if "weather" in output:
                    return output["weather"]
                elif "description" in output:
                    return output["description"]
        return ""
    except Exception:
        return ""


def normalize_location(location: str) -> str:
    """
    规范化地点名称，处理城市级别输入
    例如："重庆" -> "重庆，中国"
    """
    if not location:
        return "重庆，中国"

    location = location.strip()

    # 如果已经包含国家信息，直接返回
    if "，" in location or "," in location:
        return location

    # 常见城市默认国家映射
    city_to_country = {
        "重庆": "中国",
        "北京": "中国",
        "上海": "中国",
        "广州": "中国",
        "深圳": "中国",
        "成都": "中国",
        "杭州": "中国",
        "武汉": "中国",
        "西安": "中国",
        "南京": "中国",
        "lagos": "Nigeria",
        "lagos": "Nigeria",
        "beijing": "China",
        "shanghai": "China",
        "guangzhou": "China",
        "shenzhen": "China",
    }

    location_lower = location.lower()
    if location_lower in city_to_country:
        country = city_to_country[location_lower]
        return f"{location}，{country}"

    # 中文城市名（不带逗号）默认添加中国
    if all('\u4e00' <= char <= '\u9fff' for char in location):
        return f"{location}，中国"

    return location


def write_journal(data: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
    """
    写入日志的主函数
    自动处理默认值和天气查询

    Returns:
        {
            "success": bool,
            "journal_path": str,
            "updated_indices": [str],
            "attachments_processed": [dict],
            "location_used": str,
            "weather_used": str,
            "weather_auto_filled": bool,
            "needs_confirmation": bool,
            "confirmation_message": str,
            "error": str (optional)
        }
    """
    result = {
        "success": False,
        "journal_path": None,
        "updated_indices": [],
        "attachments_processed": [],
        "location_used": "",
        "weather_used": "",
        "weather_auto_filled": False,
        "needs_confirmation": False,
        "confirmation_message": "",
        "error": None
    }

    try:
        # 验证必需字段
        date_str = data.get("date")
        if not date_str:
            raise ValueError("缺少必需字段: date")

        # ===== 第一层：用户提及为准 =====
        # 如果用户提供了地点和天气，直接使用

        # ===== 第二层：自动填充 =====
        # 处理地点：如果未提供，使用默认值
        location = data.get("location", "").strip()
        if not location:
            location = "重庆，中国"
            result["location_used"] = location
        else:
            # 规范化地点（处理城市级别输入）
            location = normalize_location(location)
            result["location_used"] = location

        data["location"] = location

        # 处理天气：如果未提供，自动查询
        weather = data.get("weather", "").strip()
        if not weather:
            # 尝试获取天气
            queried_weather = query_weather_for_location(location, date_str)
            if queried_weather:
                weather = queried_weather
                result["weather_used"] = weather
                result["weather_auto_filled"] = True
            else:
                weather = ""
                result["weather_used"] = ""
        else:
            result["weather_used"] = weather

        data["weather"] = weather

        # 获取年月和序列号
        year, month = get_year_month(date_str)
        sequence = get_next_sequence(date_str)

        # 构建路径
        month_dir = JOURNALS_DIR / str(year) / f"{month:02d}"
        filename = generate_filename(date_str, sequence)
        journal_path = month_dir / filename

        # 处理附件
        attachments = data.get("attachments", [])
        processed_attachments = process_attachments(attachments, date_str, dry_run)
        result["attachments_processed"] = processed_attachments

        # 更新数据中的附件信息（用于生成内容）
        data["attachments"] = processed_attachments

        # 生成内容
        frontmatter = format_frontmatter(data)
        content = format_content(data)
        full_content = f"{frontmatter}\n\n{content}"

        if dry_run:
            result["journal_path"] = str(journal_path)
            result["content_preview"] = full_content[:500]
            result["success"] = True
            return result

        # 创建目录并写入文件
        month_dir.mkdir(parents=True, exist_ok=True)
        with open(journal_path, 'w', encoding='utf-8') as f:
            f.write(full_content)

        # 更新月度摘要（在写入文件后调用，确保包含当前日志）
        try:
            abstract_result = update_monthly_abstract(year, month, dry_run)
            result["monthly_abstract_updated"] = abstract_result
        except Exception as e:
            # 月度摘要更新失败不应影响主流程
            result["monthly_abstract_error"] = str(e)

        result["journal_path"] = str(journal_path)

        # 更新索引
        topic = data.get("topic")
        if topic:
            indices = update_topic_index(topic, journal_path, data)
            result["updated_indices"].extend([str(i) for i in indices])

        project = data.get("project")
        if project:
            idx = update_project_index(project, journal_path, data)
            if idx:
                result["updated_indices"].append(str(idx))

        tags = data.get("tags", [])
        if tags:
            indices = update_tag_indices(tags, journal_path, data)
            result["updated_indices"].extend([str(i) for i in indices])

        result["success"] = True

        # ===== 第三层：写入后确认 =====
        result["needs_confirmation"] = True
        result["confirmation_message"] = (
            f"日志已保存至：{journal_path}\n\n"
            f"当前记录信息：\n"
            f"- 地点：{location}\n"
            f"- 天气：{weather if weather else '（未获取）'}\n\n"
            f"请确认以上信息是否正确。如需修改，请告诉我新的地点或天气信息，"
            f"我将为您更新日志文件。"
        )

    except Exception as e:
        result["error"] = str(e)

    return result


def update_monthly_abstract(year: int, month: int, dry_run: bool = False) -> Dict[str, Any]:
    """
    更新月度摘要文件（调用 generate_abstract.py 工具）

    Args:
        year: 年份
        month: 月份
        dry_run: 是否为模拟运行

    Returns:
        {
            "abstract_path": str,
            "journal_count": int,
            "updated": bool
        }
    """
    result = {
        "abstract_path": None,
        "journal_count": 0,
        "updated": False
    }

    month_str = f"{year}-{month:02d}"
    abstract_path = JOURNALS_DIR / str(year) / f"{month:02d}" / "monthly_abstract.md"

    # 构建命令
    cmd = [
        sys.executable,
        str(TOOLS_DIR / "generate_abstract.py"),
        "--month", month_str,
        "--json"
    ]
    if dry_run:
        cmd.append("--dry-run")

    try:
        # 调用 generate_abstract.py
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=30
        )

        if proc.returncode == 0:
            output = json.loads(proc.stdout)
            if output and len(output) > 0:
                data = output[0]
                result["abstract_path"] = data.get("abstract_path")
                result["journal_count"] = data.get("journal_count", 0)
                result["updated"] = data.get("updated", False)
        else:
            result["error"] = proc.stderr

    except Exception as e:
        result["error"] = str(e)

    return result


def parse_frontmatter(file_path: Path) -> Optional[Dict]:
    """解析 YAML frontmatter（简化版，不依赖外部库）"""
    try:
        content = file_path.read_text(encoding='utf-8')

        if not content.startswith('---'):
            return {}

        parts = content.split('---', 2)
        if len(parts) < 3:
            return {}

        fm_content = parts[1].strip()

        # 简单解析关键字段
        result = {}
        for line in fm_content.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                # 去除引号
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]

                # 解析列表
                if value.startswith('[') and value.endswith(']'):
                    items = value[1:-1].split(',')
                    value = [item.strip().strip('"\'') for item in items if item.strip()]

                result[key] = value

        return result
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser(
        description="Life Index - Write Journal Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python write_journal.py --data '{"date":"2026-03-04","title":"测试","content":"内容"}'
    python write_journal.py --data @input.json --dry-run
    python write_journal.py --verbose --data '{...}'
        """
    )

    parser.add_argument(
        "--data",
        required=True,
        help='JSON数据，或 @文件路径 (如 @input.json)'
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="模拟运行，不实际写入文件"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="输出详细日志"
    )

    args = parser.parse_args()

    # 解析输入数据
    try:
        if args.data.startswith('@'):
            # 从文件读取
            file_path = args.data[1:]
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            # 直接解析JSON
            data = json.loads(args.data)
    except json.JSONDecodeError as e:
        print(json.dumps({
            "success": False,
            "error": f"JSON解析错误: {e}"
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    except FileNotFoundError:
        print(json.dumps({
            "success": False,
            "error": f"文件未找到: {args.data[1:]}"
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    if args.verbose:
        print(f"[INFO] 输入数据: {json.dumps(data, ensure_ascii=False)}", file=sys.stderr)

    # 执行写入
    result = write_journal(data, dry_run=args.dry_run)

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # 返回码
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
