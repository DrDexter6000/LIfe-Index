#!/usr/bin/env python3
"""
Life Index - Index Rebuild Tool
索引重建工具

功能：
1. 清理索引文件中的死链
2. 根据日志元数据重建主题/项目/标签索引
3. 确保所有日志被正确索引

Usage:
    python -m tools.dev.rebuild_indices              # 重建所有索引
    python -m tools.dev.rebuild_indices --dry-run    # 预览变更
    python -m tools.dev.rebuild_indices --clean-only # 仅清理死链，不重建
"""

import argparse
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Set, Tuple, Any, Optional

# 导入配置 (relative imports from tools/lib)
from ...lib.config import JOURNALS_DIR, BY_TOPIC_DIR
from ...lib.frontmatter import parse_journal_file


class IndexRebuilder:
    """索引重建器"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.journals: List[Path] = []
        self.journal_metadata: Dict[str, dict] = {}  # rel_path -> metadata
        self.dead_links_found = 0
        self.indices_updated = 0

    def run(self) -> None:
        """执行重建"""
        print("=" * 60)
        print("Life Index 索引重建工具")
        print("=" * 60)
        print(f"模式: {'预览' if self.dry_run else '执行'}")
        print()

        # 收集所有日志
        self._collect_journals()
        print(f"📁 发现 {len(self.journals)} 个日志文件")

        # 解析元数据
        self._parse_all_metadata()
        print(f"📊 成功解析 {len(self.journal_metadata)} 个日志的元数据")
        print()

        # 清理死链
        self._clean_dead_links()
        print(f"🧹 清理了 {self.dead_links_found} 个死链")

        # 重建索引
        self._rebuild_topic_indices()
        self._rebuild_project_indices()
        self._rebuild_tag_indices()

        print()
        print("=" * 60)
        print(f"✅ 完成！更新了 {self.indices_updated} 个索引文件")
        print("=" * 60)

    def _collect_journals(self) -> None:
        """收集所有日志文件"""
        if JOURNALS_DIR.exists():
            self.journals = list(JOURNALS_DIR.rglob("life-index_*.md"))
            # 排除摘要文件
            self.journals = [
                f
                for f in self.journals
                if not f.name.startswith("monthly_")
                and not f.name.startswith("yearly_")
            ]
            self.journals.sort()

    def _parse_frontmatter(self, file_path: Path) -> dict:
        """解析 YAML frontmatter（使用 lib.frontmatter）"""
        try:
            return parse_journal_file(file_path)
        except Exception as e:
            print(f"⚠️ 无法解析 {file_path}: {e}")
            return {}

    # _simple_yaml_parse 和 _parse_yaml_value 已移至 lib.frontmatter 模块

    def _parse_all_metadata(self) -> None:
        """解析所有日志的元数据"""
        for journal in self.journals:
            rel_path = journal.relative_to(JOURNALS_DIR.parent)
            metadata = self._parse_frontmatter(journal)
            if metadata:
                self.journal_metadata[str(rel_path)] = metadata

    def _clean_dead_links(self) -> None:
        """清理索引文件中的死链"""
        if not BY_TOPIC_DIR.exists():
            return

        index_files = list(BY_TOPIC_DIR.glob("*.md"))

        for index_file in index_files:
            content = index_file.read_text(encoding="utf-8")
            original_content = content

            # 查找所有 Markdown 链接
            link_pattern = r"- \[.*?\]\([^)]+\).*?(?=\n- |\n\n|$)"
            entries = re.findall(link_pattern, content, re.DOTALL)

            new_entries = []
            for entry in entries:
                # 提取链接路径
                path_match = re.search(r"\]\(([^)]+)\)", entry)
                if path_match:
                    link_path = path_match.group(1)
                    resolved = self._resolve_link(index_file, link_path)

                    if resolved and not resolved.exists():
                        # 死链，跳过
                        self.dead_links_found += 1
                        if self.dry_run:
                            print(
                                f"🔍 [预览] 将删除死链: {link_path} in {index_file.name}"
                            )
                        continue

                new_entries.append(entry)

            # 重建内容
            if len(new_entries) != len(entries):
                # 保留文件头部（到第一个 ## 之前的部分）
                header_match = re.match(r"^(# .+?\n)(## .+)$", content, re.DOTALL)
                if header_match:
                    header = header_match.group(1)
                    rest = header_match.group(2)

                    # 重新组织内容
                    new_content = header + "\n"

                    # 按月份分组
                    months: Dict[str, List[str]] = {}
                    for entry in new_entries:
                        # 提取日期
                        date_match = re.search(r"(\d{4}-\d{2})", entry)
                        if date_match:
                            month_key = date_match.group(1)
                        else:
                            month_key = "其他"

                        if month_key not in months:
                            months[month_key] = []
                        months[month_key].append(entry)

                    # 按月份输出
                    for month in sorted(months.keys(), reverse=True):
                        new_content += f"### {month}\n\n"
                        for entry in months[month]:
                            new_content += entry + "\n"
                        new_content += "\n"

                    if not self.dry_run:
                        index_file.write_text(new_content, encoding="utf-8")
                        self.indices_updated += 1
                        print(f"✅ 已清理: {index_file.name}")

    def _resolve_link(self, from_file: Path, link: str) -> Optional[Path]:
        """解析相对链接"""
        if link.startswith("http://") or link.startswith("https://"):
            return None

        if link.startswith("/"):
            return JOURNALS_DIR.parent / link.lstrip("/")

        return (from_file.parent / link).resolve()

    def _rebuild_topic_indices(self) -> None:
        """重建主题索引"""
        topics: Dict[str, List[Tuple[str, dict]]] = {}

        for rel_path, metadata in self.journal_metadata.items():
            topic_list = metadata.get("topic", [])
            if isinstance(topic_list, str):
                topic_list = [topic_list]

            for topic in topic_list:
                if topic:
                    if topic not in topics:
                        topics[topic] = []
                    topics[topic].append((rel_path, metadata))

        for topic, entries in topics.items():
            self._write_index(f"主题_{topic}.md", f"主题: {topic}", entries)

    def _rebuild_project_indices(self) -> None:
        """重建项目索引"""
        projects: Dict[str, List[Tuple[str, dict]]] = {}

        for rel_path, metadata in self.journal_metadata.items():
            project = metadata.get("project", "")
            if project:
                if project not in projects:
                    projects[project] = []
                projects[project].append((rel_path, metadata))

        for project, entries in projects.items():
            self._write_index(f"项目_{project}.md", f"项目: {project}", entries)

    def _rebuild_tag_indices(self) -> None:
        """重建标签索引"""
        tags: Dict[str, List[Tuple[str, dict]]] = {}

        for rel_path, metadata in self.journal_metadata.items():
            tag_list = metadata.get("tags", [])
            if isinstance(tag_list, str):
                tag_list = [tag_list]

            for tag in tag_list:
                if tag:
                    if tag not in tags:
                        tags[tag] = []
                    tags[tag].append((rel_path, metadata))

        for tag, entries in tags.items():
            self._write_index(f"标签_{tag}.md", f"标签: {tag}", entries)

    def _write_index(
        self, filename: str, title: str, entries: List[Tuple[str, dict]]
    ) -> None:
        """写入索引文件"""
        index_file = BY_TOPIC_DIR / filename

        # 按日期排序（倒序）
        entries.sort(key=lambda x: x[1].get("date", ""), reverse=True)

        content = f"# {title}\n\n## 日志列表\n\n"

        # 按月份分组
        months: Dict[str, List[str]] = {}
        for rel_path, metadata in entries:
            date_str = metadata.get("date", "")
            if isinstance(date_str, str) and len(date_str) >= 7:
                month_key = date_str[:7]  # YYYY-MM
            else:
                month_key = "其他"

            if month_key not in months:
                months[month_key] = []

            # 构建相对路径
            rel_path_obj = Path(rel_path)
            depth = len(index_file.parent.parts) - len(JOURNALS_DIR.parent.parts)
            prefix = "../" * depth
            link_path = f"{prefix}{rel_path}"

            # 提取信息
            title_text = metadata.get("_title", rel_path_obj.stem)
            abstract = metadata.get("_abstract", "")
            tags = metadata.get("tags", [])
            project = metadata.get("project", "")

            if isinstance(tags, list):
                tags_str = ", ".join(tags)
            else:
                tags_str = str(tags)

            # 格式化日期
            date_display = date_str[:10] if isinstance(date_str, str) else "未知日期"

            entry_text = f"- [{date_display} {title_text}]({link_path})\n"
            if abstract:
                entry_text += f"  - 摘要: {abstract}\n"
            if tags_str:
                entry_text += f"  - 标签: {tags_str}\n"
            if project:
                entry_text += f"  - 项目: {project}\n"

            months[month_key].append(entry_text)

        # 按月份输出（倒序）
        for month in sorted(months.keys(), reverse=True):
            content += f"### {month}\n\n"
            for entry in months[month]:
                content += entry + "\n"

        if self.dry_run:
            print(f"🔍 [预览] 将更新: {filename} ({len(entries)} 条记录)")
        else:
            index_file.write_text(content, encoding="utf-8")
            self.indices_updated += 1
            print(f"✅ 已更新: {filename} ({len(entries)} 条记录)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Life Index 索引重建工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
python -m tools.dev.rebuild_indices              # 重建所有索引
        python -m tools.dev.rebuild_indices --dry-run    # 预览变更
        """,
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="预览模式：显示将要做的变更但不实际执行"
    )

    args = parser.parse_args()

    rebuilder = IndexRebuilder(dry_run=args.dry_run)
    rebuilder.run()


if __name__ == "__main__":
    main()
