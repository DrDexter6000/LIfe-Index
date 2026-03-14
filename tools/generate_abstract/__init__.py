#!/usr/bin/env python3
"""
Life Index - Abstract Generator
摘要生成工具（月度/年度）

Usage:
    # 生成月度摘要
    python -m tools.generate_abstract --month 2026-03
    python -m tools.generate_abstract --month 2026-03 --dry-run

    # 生成年度摘要
    python -m tools.generate_abstract --year 2026
    python -m tools.generate_abstract --year 2026 --dry-run

    # 批量生成全年月度摘要
    python -m tools.generate_abstract --year 2026 --all-months

    # 同时生成年度和月度摘要
    python -m tools.generate_abstract --year 2026 --month 2026-03
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

# 导入配置和日志 (relative imports from parent tools package)
from ..lib.config import JOURNALS_DIR
from ..lib.logger import get_logger

logger = get_logger(__name__)


def parse_frontmatter(file_path: Path) -> Optional[Dict]:
    """解析 YAML frontmatter（简化版）"""
    try:
        content = file_path.read_text(encoding="utf-8")

        if not content.startswith("---"):
            return {}

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}

        fm_content = parts[1].strip()
        body = parts[2].strip()

        result: Dict[str, Any] = {}
        current_key = None
        current_list: List[str] = []
        in_list = False

        for line in fm_content.split("\n"):
            stripped = line.strip()

            if not stripped or stripped.startswith("#"):
                continue

            if stripped.startswith("- "):
                value = stripped[2:].strip()
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                current_list.append(value)
                in_list = True
                continue

            if ":" in stripped:
                if in_list and current_key:
                    result[current_key] = current_list
                    current_list = []
                    in_list = False

                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip()

                if not value:
                    current_key = key
                    current_list = []
                    in_list = True
                    continue

                # 解析值
                parsed_value: Any
                if value.lower() in ("true", "yes"):
                    parsed_value = True
                elif value.lower() in ("false", "no"):
                    parsed_value = False
                elif value.lower() in ("null", "~", ""):
                    parsed_value = None
                elif value.startswith("[") and value.endswith("]"):
                    items = value[1:-1].split(",")
                    parsed_value = [
                        item.strip().strip("\"'") for item in items if item.strip()
                    ]
                elif (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    parsed_value = value[1:-1]
                else:
                    try:
                        if "." in value:
                            parsed_value = float(value)
                        else:
                            parsed_value = int(value)
                    except ValueError:
                        parsed_value = value

                result[key] = parsed_value
                current_key = None

        if in_list and current_key:
            result[current_key] = current_list

        result["_body"] = body
        return result
    except (ValueError, IndexError, IOError, OSError):
        return {}


def collect_month_journals(year: int, month: int) -> List[Dict]:
    """收集指定月份的所有日志"""
    journals: List[Dict] = []
    month_dir = JOURNALS_DIR / str(year) / f"{month:02d}"

    if not month_dir.exists():
        logger.debug(f"目录不存在：{month_dir}")
        return journals

    logger.debug(f"扫描目录：{month_dir}")
    for journal_file in sorted(month_dir.glob("life-index_*.md")):
        metadata = parse_frontmatter(journal_file)
        if metadata:
            journals.append(
                {
                    "file": journal_file.name,
                    "path": f"./{journal_file.name}",
                    "date": metadata.get("date", ""),
                    "title": metadata.get("title", journal_file.stem),
                    "tags": metadata.get("tags", []),
                    "project": metadata.get("project", ""),
                    "topic": metadata.get("topic", []),
                    "mood": metadata.get("mood", []),
                    "people": metadata.get("people", []),
                    "abstract": metadata.get("abstract", ""),
                }
            )

    return journals


def collect_year_journals(year: int) -> List[Dict]:
    """收集指定年份的所有日志"""
    journals: List[Dict] = []
    year_dir = JOURNALS_DIR / str(year)

    if not year_dir.exists():
        logger.debug(f"目录不存在：{year_dir}")
        return journals

    logger.debug(f"扫描目录：{year_dir}")
    # 遍历所有月份目录
    for month_dir in sorted(year_dir.iterdir()):
        if not month_dir.is_dir():
            continue

        # 收集该月的所有日志文件
        for journal_file in sorted(month_dir.glob("life-index_*.md")):
            metadata = parse_frontmatter(journal_file)
            if metadata:
                rel_path = f"./{month_dir.name}/{journal_file.name}"
                journals.append(
                    {
                        "file": journal_file.name,
                        "path": rel_path,
                        "month": month_dir.name,
                        "date": metadata.get("date", ""),
                        "title": metadata.get("title", journal_file.stem),
                        "tags": metadata.get("tags", []),
                        "project": metadata.get("project", ""),
                        "topic": metadata.get("topic", []),
                        "mood": metadata.get("mood", []),
                        "people": metadata.get("people", []),
                        "abstract": metadata.get("abstract", ""),
                    }
                )

    return journals


def generate_monthly_abstract_content(
    year: int, month: int, journals: List[Dict]
) -> str:
    """生成月度摘要内容（与 write_journal.py 格式兼容）"""
    month_name = f"{year}年{month:02d}月"
    now = datetime.now().isoformat()

    lines = [
        f"# {month_name} 日志摘要",
        "",
        f"> 生成时间: {now}",
        f"> 日志总数: {len(journals)}",
        "",
        "## 按日期索引",
        "",
    ]

    # 按日期分组
    by_date: Dict[str, List[Dict]] = {}
    for j in journals:
        date_str = j["date"]
        if isinstance(date_str, str) and len(date_str) >= 10:
            date_key = date_str[:10]
        else:
            date_key = "未知日期"

        if date_key not in by_date:
            by_date[date_key] = []
        by_date[date_key].append(j)

    # 输出每日日志
    for date_key in sorted(by_date.keys()):
        lines.append(f"### {date_key}")
        lines.append("")

        for j in by_date[date_key]:
            title = j["title"] or j["file"]
            lines.append(f"- [{title}]({j['path']})")
            if j["abstract"]:
                lines.append(f"  - {j['abstract'][:100]}...")
        lines.append("")

    # 统计信息
    all_tags = []
    all_projects = []
    all_topics = []

    for j in journals:
        tags = j["tags"]
        if isinstance(tags, list):
            all_tags.extend(tags)
        elif isinstance(tags, str):
            all_tags.append(tags)

        if j["project"]:
            all_projects.append(j["project"])

        topics = j["topic"]
        if isinstance(topics, list):
            all_topics.extend(topics)
        elif isinstance(topics, str):
            all_topics.append(topics)

    # 标签统计
    if all_tags:
        lines.append("## 标签统计")
        lines.append("")
        tag_counts = Counter(all_tags)
        for tag, count in tag_counts.most_common():
            lines.append(f"- {tag}: {count}篇")
        lines.append("")

    # 项目统计
    if all_projects:
        lines.append("## 项目统计")
        lines.append("")
        project_counts = Counter(all_projects)
        for proj, count in project_counts.most_common():
            lines.append(f"- {proj}: {count}篇")
        lines.append("")

    # 主题统计
    if all_topics:
        lines.append("## 主题统计")
        lines.append("")
        topic_counts = Counter(all_topics)
        for topic, count in topic_counts.most_common():
            lines.append(f"- {topic}: {count}篇")
        lines.append("")

    return "\n".join(lines)


def generate_yearly_abstract_content(year: int, journals: List[Dict]) -> str:
    """生成年度摘要内容（与 generate_yearly_abstract.py 格式兼容）"""
    now = datetime.now().isoformat()
    total_journals = len(journals)

    lines = [
        f"# {year}年 年度日志摘要",
        "",
        f"> 生成时间: {now}",
        f"> 日志总数: {total_journals}篇",
        "",
    ]

    # 按月份统计
    monthly_stats: Dict[str, int] = {}
    for j in journals:
        month = j.get("month", "未知")
        monthly_stats[month] = monthly_stats.get(month, 0) + 1

    lines.append("## 月度分布")
    lines.append("")
    for month in sorted(monthly_stats.keys()):
        count = monthly_stats[month]
        lines.append(f"- {year}年{month}月: {count}篇")
    lines.append("")

    # 全局统计
    all_tags = []
    all_projects = []
    all_topics = []
    all_moods = []
    all_people = []

    for j in journals:
        tags = j.get("tags", [])
        if isinstance(tags, list):
            all_tags.extend(tags)
        elif isinstance(tags, str):
            all_tags.append(tags)

        if j.get("project"):
            all_projects.append(j["project"])

        topics = j.get("topic", [])
        if isinstance(topics, list):
            all_topics.extend(topics)
        elif isinstance(topics, str):
            all_topics.append(topics)

        moods = j.get("mood", [])
        if isinstance(moods, list):
            all_moods.extend(moods)
        elif isinstance(moods, str):
            all_moods.append(moods)

        people = j.get("people", [])
        if isinstance(people, list):
            all_people.extend(people)
        elif isinstance(people, str):
            all_people.append(people)

    # 主题统计
    if all_topics:
        lines.append("## 主题分布")
        lines.append("")
        topic_counts = Counter(all_topics)
        for topic, count in topic_counts.most_common():
            lines.append(f"- {topic}: {count}篇")
        lines.append("")

    # 项目统计
    if all_projects:
        lines.append("## 项目分布")
        lines.append("")
        project_counts = Counter(all_projects)
        for proj, count in project_counts.most_common():
            lines.append(f"- {proj}: {count}篇")
        lines.append("")

    # 标签统计
    if all_tags:
        lines.append("## 热门标签")
        lines.append("")
        tag_counts = Counter(all_tags)
        for tag, count in tag_counts.most_common(20):  # Top 20
            lines.append(f"- {tag}: {count}篇")
        lines.append("")

    # 心情统计
    if all_moods:
        lines.append("## 心情分布")
        lines.append("")
        mood_counts = Counter(all_moods)
        for mood, count in mood_counts.most_common():
            lines.append(f"- {mood}: {count}次")
        lines.append("")

    # 人物统计
    if all_people:
        lines.append("## 相关人物")
        lines.append("")
        people_counts = Counter(all_people)
        for person, count in people_counts.most_common():
            lines.append(f"- {person}: {count}次")
        lines.append("")

    # 全年日志索引
    lines.append("## 全年日志索引")
    lines.append("")

    # 按月份分组
    by_month: Dict[str, List[Dict]] = {}
    for j in journals:
        month = j.get("month", "未知")
        if month not in by_month:
            by_month[month] = []
        by_month[month].append(j)

    for month in sorted(by_month.keys()):
        lines.append(f"### {year}年{month}月")
        lines.append("")
        for j in by_month[month]:
            date_str = j.get("date", "")
            if isinstance(date_str, str) and len(date_str) >= 10:
                day = date_str[8:10]
            else:
                day = "??"
            title = j.get("title") or j["file"]
            lines.append(f"- {day}日: [{title}]({j['path']})")
        lines.append("")

    return "\n".join(lines)


def generate_monthly_abstract(
    year: int, month: int, dry_run: bool = False
) -> Dict[str, Any]:
    """生成月度摘要文件"""
    result = {
        "type": "monthly",
        "year": year,
        "month": month,
        "abstract_path": None,
        "journal_count": 0,
        "updated": False,
    }

    month_dir = JOURNALS_DIR / str(year) / f"{month:02d}"
    abstract_path = month_dir / f"monthly_report_{year}-{month:02d}.md"

    # 收集该月所有日志
    journals = collect_month_journals(year, month)
    result["journal_count"] = len(journals)

    if not journals:
        logger.info(f"{year}年{month:02d}月没有日志记录")
        result["message"] = f"{year}年{month:02d}月没有日志记录"
        return result

    # 生成月度摘要内容
    content = generate_monthly_abstract_content(year, month, journals)
    result["abstract_path"] = str(abstract_path)

    if dry_run:
        logger.info(f"[预览] 将生成月度摘要：{abstract_path}")
        result["message"] = f"[预览] 将生成月度摘要：{abstract_path}"
        return result

    # 确保目录存在
    month_dir.mkdir(parents=True, exist_ok=True)

    # 写入摘要文件
    logger.debug(f"写入月度摘要：{abstract_path}")
    with open(abstract_path, "w", encoding="utf-8") as f:
        f.write(content)

    result["updated"] = True
    result["message"] = f"月度摘要已保存：{abstract_path}"
    logger.info(f"月度摘要已保存：{abstract_path}")

    return result

    # 生成月度摘要内容
    content = generate_monthly_abstract_content(year, month, journals)
    result["abstract_path"] = str(abstract_path)

    if dry_run:
        result["message"] = f"[预览] 将生成月度摘要: {abstract_path}"
        return result

    # 确保目录存在
    month_dir.mkdir(parents=True, exist_ok=True)

    # 写入摘要文件
    with open(abstract_path, "w", encoding="utf-8") as f:
        f.write(content)

    result["updated"] = True
    result["message"] = f"月度摘要已保存: {abstract_path}"

    return result


def generate_yearly_abstract(year: int, dry_run: bool = False) -> Dict[str, Any]:
    """生成年度摘要文件"""
    result = {
        "type": "yearly",
        "year": year,
        "abstract_path": None,
        "journal_count": 0,
        "updated": False,
    }

    abstract_path = JOURNALS_DIR / str(year) / f"yearly_report_{year}.md"

    # 收集该年所有日志
    journals = collect_year_journals(year)
    result["journal_count"] = len(journals)

    if not journals:
        logger.info(f"{year}年没有日志记录")
        result["message"] = f"{year}年没有日志记录"
        return result

    # 生成年度摘要内容
    content = generate_yearly_abstract_content(year, journals)
    result["abstract_path"] = str(abstract_path)

    if dry_run:
        logger.info(f"[预览] 将生成年度摘要：{abstract_path}")
        result["message"] = f"[预览] 将生成年度摘要：{abstract_path}"
        return result

    # 确保目录存在
    abstract_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入摘要文件
    logger.debug(f"写入年度摘要：{abstract_path}")
    with open(abstract_path, "w", encoding="utf-8") as f:
        f.write(content)

    result["updated"] = True
    result["message"] = f"年度摘要已保存：{abstract_path}"
    logger.info(f"年度摘要已保存：{abstract_path}")

    return result

    # 生成年度摘要内容
    content = generate_yearly_abstract_content(year, journals)
    result["abstract_path"] = str(abstract_path)

    if dry_run:
        result["message"] = f"[预览] 将生成年度摘要: {abstract_path}"
        return result

    # 确保目录存在
    abstract_path.parent.mkdir(parents=True, exist_ok=True)

    # 写入摘要文件
    with open(abstract_path, "w", encoding="utf-8") as f:
        f.write(content)

    result["updated"] = True
    result["message"] = f"年度摘要已保存: {abstract_path}"

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Life Index 摘要生成工具（月度/年度）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # 生成月度摘要
    python -m tools.generate_abstract --month 2026-03
    python -m tools.generate_abstract --month 2026-03 --dry-run

    # 生成年度摘要
    python -m tools.generate_abstract --year 2026
    python -m tools.generate_abstract --year 2026 --dry-run

    # 批量生成全年月度摘要
    python -m tools.generate_abstract --year 2026 --all-months

    # 同时生成年度和指定月度摘要
    python -m tools.generate_abstract --year 2026 --month 2026-03
        """,
    )

    parser.add_argument(
        "--month", type=str, help="生成月度摘要，格式: YYYY-MM (如 2026-03)"
    )

    parser.add_argument("--year", type=int, help="生成年度摘要，格式: YYYY (如 2026)")

    parser.add_argument(
        "--all-months",
        action="store_true",
        help="与 --year 一起使用，批量生成全年各月的月度摘要",
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="预览模式：显示生成的内容但不写入文件"
    )

    parser.add_argument("--json", action="store_true", help="输出结果为 JSON 格式")

    args = parser.parse_args()

    # 验证参数
    if not args.month and not args.year:
        parser.error("请指定 --month 或 --year 参数")

    results = []

    # 生成月度摘要
    if args.month:
        try:
            year, month = map(int, args.month.split("-"))
            logger.info(f"生成月度摘要：{year}年{month:02d}月")
            result = generate_monthly_abstract(year, month, args.dry_run)
            results.append(result)
        except ValueError:
            logger.error(f"--month 参数格式应为 YYYY-MM (如 2026-03)")
            sys.exit(1)

    # 生成年度摘要
    if args.year and not args.all_months:
        logger.info(f"生成年度摘要：{args.year}年")
        result = generate_yearly_abstract(args.year, args.dry_run)
        results.append(result)

    # 批量生成全年月度摘要
    if args.year and args.all_months:
        logger.info(f"批量生成{args.year}年全年月度摘要")
        year_dir = JOURNALS_DIR / str(args.year)
        if year_dir.exists():
            for month_dir in sorted(year_dir.iterdir()):
                if month_dir.is_dir() and month_dir.name.isdigit():
                    month = int(month_dir.name)
                    result = generate_monthly_abstract(args.year, month, args.dry_run)
                    results.append(result)
        else:
            logger.warning(f"{args.year}年目录不存在")
            results.append(
                {
                    "type": "monthly",
                    "year": args.year,
                    "message": f"{args.year}年目录不存在",
                }
            )

    # 输出结果
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(result.get("message", ""))
            if result.get("journal_count") is not None:
                print(f"  日志数量: {result['journal_count']}")

    # 返回非零退出码如果有错误
    if any(not r.get("updated") and r.get("journal_count", 0) > 0 for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
