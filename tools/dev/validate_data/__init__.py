#!/usr/bin/env python3
"""
Life Index - Data Integrity Validation Tool
数据完整性校验工具

Usage:
    python -m tools.dev.validate_data                    # 完整校验
    python -m tools.dev.validate_data --quick            # 快速校验（仅检查数量和基本结构）
    python -m tools.dev.validate_data --fix              # 自动修复可修复的问题
    python -m tools.dev.validate_data --json             # JSON格式输出
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field, asdict

# 导入配置 (relative imports from tools/lib)
from ...lib.config import JOURNALS_DIR, BY_TOPIC_DIR, ATTACHMENTS_DIR
from ...lib.frontmatter import (
    parse_journal_file,
    parse_frontmatter,
    validate_metadata,
    get_required_fields,
    get_recommended_fields,
)


@dataclass
class ValidationIssue:
    """校验问题记录"""

    level: str  # error, warning, info
    category: str  # orphan_index, metadata, link, sequence, attachment
    file: str
    message: str
    suggestion: str = ""
    auto_fixable: bool = False


@dataclass
class ValidationResult:
    """校验结果"""

    total_journals: int = 0
    total_indices: int = 0
    total_attachments: int = 0
    issues: List[ValidationIssue] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)

    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "error")

    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.level == "warning")

    def to_dict(self) -> dict:
        return {
            "summary": {
                "total_journals": self.total_journals,
                "total_indices": self.total_indices,
                "total_attachments": self.total_attachments,
                "errors": self.error_count(),
                "warnings": self.warning_count(),
            },
            "stats": self.stats,
            "issues": [asdict(i) for i in self.issues],
        }


class DataValidator:
    """数据完整性校验器"""

    # 必填字段（根据 HANDBOOK.md 规范）
    # 从 lib.frontmatter 获取字段定义
    @property
    def REQUIRED_FIELDS(self):
        return get_required_fields()

    @property
    def RECOMMENDED_FIELDS(self):
        return get_recommended_fields()

    OPTIONAL_FIELDS = ["tags", "project", "topic", "links", "attachments"]

    def __init__(self, fix_mode: bool = False):
        self.fix_mode = fix_mode
        self.result = ValidationResult()
        self.journal_files: List[Path] = []
        self.index_files: List[Path] = []
        self.attachment_files: List[Path] = []
        self.journal_entries: Dict[str, dict] = {}  # rel_path -> metadata

    def run(self) -> ValidationResult:
        """执行完整校验"""
        self._collect_files()
        self._validate_journals()
        self._validate_indices()
        self._validate_attachments()
        self._validate_cross_references()
        self._generate_stats()
        return self.result

    def _collect_files(self) -> None:
        """收集所有相关文件"""
        # 收集日志文件
        if JOURNALS_DIR.exists():
            self.journal_files = list(JOURNALS_DIR.rglob("life-index_*.md"))
            # 排除摘要文件
            self.journal_files = [
                f
                for f in self.journal_files
                if not f.name.startswith("monthly_")
                and not f.name.startswith("yearly_")
            ]

        # 收集索引文件
        if BY_TOPIC_DIR.exists():
            self.index_files = list(BY_TOPIC_DIR.glob("*.md"))

        # 收集附件文件
        if ATTACHMENTS_DIR.exists():
            self.attachment_files = list(ATTACHMENTS_DIR.rglob("*"))
            self.attachment_files = [f for f in self.attachment_files if f.is_file()]

        self.result.total_journals = len(self.journal_files)
        self.result.total_indices = len(self.index_files)
        self.result.total_attachments = len(self.attachment_files)

    def _parse_frontmatter(self, file_path: Path) -> Optional[dict]:
        """解析 YAML frontmatter（使用 lib.frontmatter）"""
        try:
            metadata = parse_journal_file(file_path)
            if "_error" in metadata:
                self.result.issues.append(
                    ValidationIssue(
                        level="error",
                        category="metadata",
                        file=str(file_path),
                        message=f"无法解析 frontmatter: {metadata['_error']}",
                        suggestion="检查文件编码和YAML格式",
                    )
                )
                return None
            return metadata
        except Exception as e:
            self.result.issues.append(
                ValidationIssue(
                    level="error",
                    category="metadata",
                    file=str(file_path),
                    message=f"无法解析 frontmatter: {e}",
                    suggestion="检查文件编码和YAML格式",
                )
            )
            return None

    # _simple_yaml_parse 和 _parse_yaml_value 已移至 lib.frontmatter 模块

    def _validate_journals(self) -> None:
        """校验日志文件"""
        sequences_by_date: Dict[str, List[Tuple[int, Path]]] = {}

        for journal_file in self.journal_files:
            rel_path = journal_file.relative_to(JOURNALS_DIR.parent)
            metadata = self._parse_frontmatter(journal_file)

            if metadata is None:
                continue

            self.journal_entries[str(rel_path)] = metadata

            # 检查必填字段
            for field in self.REQUIRED_FIELDS:
                if field not in metadata or not metadata[field]:
                    self.result.issues.append(
                        ValidationIssue(
                            level="error",
                            category="metadata",
                            file=str(journal_file),
                            message=f"缺少必填字段: {field}",
                            suggestion=f"在 frontmatter 中添加 {field} 字段",
                        )
                    )

            # 检查推荐字段
            for field in self.RECOMMENDED_FIELDS:
                if field not in metadata or not metadata[field]:
                    self.result.issues.append(
                        ValidationIssue(
                            level="warning",
                            category="metadata",
                            file=str(journal_file),
                            message=f"缺少推荐字段: {field}",
                            suggestion=f"考虑添加 {field} 以完善元数据",
                        )
                    )

            # 校验日期格式
            date_str = metadata.get("date", "")
            if date_str:
                try:
                    # 支持 ISO 8601 格式
                    date_str = str(date_str).replace("Z", "+00:00")
                    if "T" in date_str:
                        datetime.fromisoformat(date_str)
                    else:
                        datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    self.result.issues.append(
                        ValidationIssue(
                            level="error",
                            category="metadata",
                            file=str(journal_file),
                            message=f"日期格式错误: {date_str}",
                            suggestion="使用 ISO 8601 格式: YYYY-MM-DDTHH:MM:SS",
                        )
                    )

            # 检查序列号连续性
            match = re.search(
                r"life-index_(\d{4}-\d{2}-\d{2})_(\d{3})\.md$", journal_file.name
            )
            if match:
                date_part = match.group(1)
                seq = int(match.group(2))

                if date_part not in sequences_by_date:
                    sequences_by_date[date_part] = []
                sequences_by_date[date_part].append((seq, journal_file))

        # 检查每日序列号是否连续
        for date_part, seq_list in sequences_by_date.items():
            seqs = sorted([s[0] for s in seq_list])
            expected = list(range(1, len(seqs) + 1))

            if seqs != expected:
                missing = set(expected) - set(seqs)
                if missing:
                    self.result.issues.append(
                        ValidationIssue(
                            level="warning",
                            category="sequence",
                            file=str(seq_list[0][1]),
                            message=f"日期 {date_part} 的序列号不连续，缺失: {sorted(missing)}",
                            suggestion="检查是否有遗漏的日志文件或重命名现有文件",
                        )
                    )

    def _validate_indices(self) -> None:
        """校验索引文件"""
        for index_file in self.index_files:
            content = index_file.read_text(encoding="utf-8")

            # 提取所有链接
            link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
            links = re.findall(link_pattern, content)

            for text, link_path in links:
                # 解析相对路径
                resolved_path = self._resolve_link(index_file, link_path)

                if resolved_path and not resolved_path.exists():
                    self.result.issues.append(
                        ValidationIssue(
                            level="error",
                            category="link",
                            file=str(index_file),
                            message=f"死链: {link_path} (指向 {text})",
                            suggestion=f"删除或修复链接，目标文件不存在",
                            auto_fixable=True,
                        )
                    )

    def _validate_attachments(self) -> None:
        """校验附件引用"""
        for rel_path, metadata in self.journal_entries.items():
            attachments = metadata.get("attachments", [])
            journal_file = JOURNALS_DIR.parent / rel_path

            if isinstance(attachments, list):
                for att in attachments:
                    if isinstance(att, str):
                        # 解析相对路径 - 相对于日志文件位置
                        if att.startswith("../") or att.startswith("./"):
                            # 相对路径，基于日志文件位置解析
                            att_path = (journal_file.parent / att).resolve()
                        elif att.startswith("/"):
                            # 绝对路径（相对于用户数据目录根）
                            att_path = (JOURNALS_DIR.parent / att.lstrip("/")).resolve()
                        else:
                            # 只有文件名，根据日志日期推断路径
                            # 从日志文件名提取日期: life-index_YYYY-MM-DD_NNN.md
                            date_match = re.search(
                                r"(\d{4})-(\d{2})-\d{2}", journal_file.name
                            )
                            if date_match:
                                year, month = date_match.groups()
                                att_path = ATTACHMENTS_DIR / year / month / att
                            else:
                                att_path = ATTACHMENTS_DIR / att

                        if not att_path.exists():
                            self.result.issues.append(
                                ValidationIssue(
                                    level="error",
                                    category="attachment",
                                    file=str(journal_file),
                                    message=f"附件不存在: {att}",
                                    suggestion="检查附件路径或从 frontmatter 中移除该附件",
                                )
                            )

    def _validate_cross_references(self) -> None:
        """校验交叉引用一致性"""
        # 构建索引中的条目集合
        indexed_entries: Set[str] = set()

        for index_file in self.index_files:
            content = index_file.read_text(encoding="utf-8")
            link_pattern = r"\[([^\]]+)\]\(([^)]+)\)"
            links = re.findall(link_pattern, content)

            for text, link_path in links:
                resolved = self._resolve_link(index_file, link_path)
                if resolved:
                    try:
                        rel_path = resolved.relative_to(JOURNALS_DIR.parent)
                        indexed_entries.add(str(rel_path))
                    except ValueError:
                        pass

        # 检查每个日志是否被正确索引
        for rel_path_str, metadata in self.journal_entries.items():
            rel_path = Path(rel_path_str)
            # 获取主题、项目、标签
            topics = metadata.get("topic", [])
            project = metadata.get("project", "")
            tags = metadata.get("tags", [])

            if isinstance(topics, str):
                topics = [topics]
            if isinstance(tags, str):
                tags = [tags]

            # 检查主题索引
            for topic in topics:
                if topic:
                    index_file = BY_TOPIC_DIR / f"主题_{topic}.md"
                    if index_file.exists():
                        content = index_file.read_text(encoding="utf-8")
                        if (
                            rel_path.name not in content
                            and str(rel_path) not in content
                        ):
                            self.result.issues.append(
                                ValidationIssue(
                                    level="warning",
                                    category="orphan_index",
                                    file=str(index_file),
                                    message=f"日志 {rel_path} 有主题 '{topic}' 但未在对应索引中找到",
                                    suggestion=f"运行 write_journal 重新生成索引",
                                    auto_fixable=True,
                                )
                            )

    def _resolve_link(self, from_file: Path, link: str) -> Optional[Path]:
        """解析相对链接为绝对路径"""
        if link.startswith("http://") or link.startswith("https://"):
            return None  # 外部链接不检查

        # 相对于用户数据目录根
        if link.startswith("/"):
            return JOURNALS_DIR.parent / link.lstrip("/")

        # 相对路径
        resolved = (from_file.parent / link).resolve()
        return resolved

    def _generate_stats(self) -> None:
        """生成统计信息"""
        topic_counts: Dict[str, int] = {}
        project_counts: Dict[str, int] = {}
        tag_counts: Dict[str, int] = {}
        mood_counts: Dict[str, int] = {}
        monthly_counts: Dict[str, int] = {}

        for rel_path, metadata in self.journal_entries.items():
            # 主题统计
            topics = metadata.get("topic", [])
            if isinstance(topics, str):
                topics = [topics]
            for t in topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1

            # 项目统计
            project = metadata.get("project", "")
            if project:
                project_counts[project] = project_counts.get(project, 0) + 1

            # 标签统计
            tags = metadata.get("tags", [])
            if isinstance(tags, list):
                for tag in tags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

            # 心情统计
            moods = metadata.get("mood", [])
            if isinstance(moods, list):
                for m in moods:
                    mood_counts[m] = mood_counts.get(m, 0) + 1
            elif isinstance(moods, str):
                mood_counts[moods] = mood_counts.get(moods, 0) + 1

            # 月度统计
            date_str = metadata.get("date", "")
            if date_str:
                try:
                    date_str = str(date_str)[:7]  # YYYY-MM
                    monthly_counts[date_str] = monthly_counts.get(date_str, 0) + 1
                except:
                    pass

        self.result.stats = {
            "topics": topic_counts,
            "projects": project_counts,
            "tags": tag_counts,
            "moods": mood_counts,
            "monthly_distribution": monthly_counts,
        }


def print_report(result: ValidationResult, use_json: bool = False) -> None:
    """打印校验报告"""
    if use_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return

    print("=" * 60)
    print("Life Index 数据完整性校验报告")
    print("=" * 60)
    print()

    # 概览
    print(f"📊 数据概览:")
    print(f"   日志文件: {result.total_journals}")
    print(f"   索引文件: {result.total_indices}")
    print(f"   附件文件: {result.total_attachments}")
    print()

    # 问题汇总
    errors = result.error_count()
    warnings = result.warning_count()

    if errors == 0 and warnings == 0:
        print("✅ 所有检查通过，数据完整性良好！")
    else:
        status = "❌" if errors > 0 else "⚠️"
        print(f"{status} 发现问题: {errors} 个错误, {warnings} 个警告")
    print()

    # 详细问题
    if result.issues:
        print("📋 详细问题列表:")
        print("-" * 60)

        categories = {
            "metadata": "元数据",
            "link": "链接",
            "orphan_index": "孤立索引",
            "sequence": "序列号",
            "attachment": "附件",
        }

        for issue in result.issues:
            cat_name = categories.get(issue.category, issue.category)
            level_icon = {"error": "❌", "warning": "⚠️", "info": "ℹ️"}.get(
                issue.level, "•"
            )
            fixable = " [可自动修复]" if issue.auto_fixable else ""

            print(f"{level_icon} [{cat_name}] {issue.message}{fixable}")
            print(f"   文件: {issue.file}")
            if issue.suggestion:
                print(f"   建议: {issue.suggestion}")
            print()

    # 统计信息
    if result.stats:
        print("-" * 60)
        print("📈 数据统计:")

        if result.stats.get("topics"):
            print(
                f"   主题分布: {dict(sorted(result.stats['topics'].items(), key=lambda x: -x[1])[:5])}"
            )
        if result.stats.get("projects"):
            print(
                f"   项目分布: {dict(sorted(result.stats['projects'].items(), key=lambda x: -x[1])[:5])}"
            )
        if result.stats.get("monthly_distribution"):
            print(
                f"   月度分布: {dict(sorted(result.stats['monthly_distribution'].items()))}"
            )

    print()
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Life Index 数据完整性校验工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
python -m tools.dev.validate_data              # 完整校验并打印报告
        python -m tools.dev.validate_data --json       # JSON格式输出
        python -m tools.dev.validate_data --quick      # 快速模式（仅基本检查）
        """,
    )

    parser.add_argument(
        "--quick", action="store_true", help="快速模式：仅检查文件数量和基本结构"
    )

    parser.add_argument(
        "--fix", action="store_true", help="自动修复可修复的问题（谨慎使用）"
    )

    parser.add_argument("--json", action="store_true", help="JSON格式输出")

    args = parser.parse_args()

    # 执行校验
    validator = DataValidator(fix_mode=args.fix)
    result = validator.run()

    # 输出报告
    print_report(result, use_json=args.json)

    # 返回码
    sys.exit(0 if result.error_count() == 0 else 1)


if __name__ == "__main__":
    main()
