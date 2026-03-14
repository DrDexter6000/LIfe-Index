#!/usr/bin/env python3
"""
Unit tests for tools/generate_abstract/__init__.py
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.generate_abstract import (
    parse_frontmatter,
    collect_month_journals,
    collect_year_journals,
    generate_monthly_abstract_content,
    generate_yearly_abstract_content,
    generate_monthly_abstract,
    generate_yearly_abstract,
)


class TestParseFrontmatter:
    """Tests for parse_frontmatter function"""

    def test_parse_valid_journal(self, tmp_path):
        """Parse valid journal returns metadata"""
        journal = tmp_path / "test.md"
        journal.write_text(
            """---
title: Test
date: 2026-03-14
---
# Content
""",
            encoding="utf-8",
        )

        result = parse_frontmatter(journal)

        assert result.get("title") == "Test"
        assert result.get("date") == "2026-03-14"

    def test_parse_invalid_journal(self, tmp_path):
        """Parse invalid journal returns dict with _error"""
        journal = tmp_path / "invalid.md"
        journal.write_text("# No frontmatter", encoding="utf-8")

        result = parse_frontmatter(journal)

        # Invalid frontmatter returns dict with _error key
        assert "_error" in result or result.get("title") is None


class TestCollectMonthJournals:
    """Tests for collect_month_journals function"""

    def test_collect_from_empty_directory(self, tmp_path):
        """Collect from non-existent directory returns empty list"""
        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = collect_month_journals(2026, 3)
            assert result == []

    def test_collect_from_directory_with_journals(self, tmp_path):
        """Collect journals from directory"""
        month_dir = tmp_path / "Journals" / "2026" / "03"
        month_dir.mkdir(parents=True)

        journal = month_dir / "life-index_2026-03-14_001.md"
        journal.write_text(
            """---
title: Test Journal
date: 2026-03-14T10:00:00
topic: ["work"]
---
# Content
""",
            encoding="utf-8",
        )

        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = collect_month_journals(2026, 3)

        assert len(result) == 1
        assert result[0]["title"] == "Test Journal"
        assert result[0]["file"] == "life-index_2026-03-14_001.md"


class TestCollectYearJournals:
    """Tests for collect_year_journals function"""

    def test_collect_from_empty_year(self, tmp_path):
        """Collect from non-existent year returns empty list"""
        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = collect_year_journals(2026)
            assert result == []

    def test_collect_from_year_with_multiple_months(self, tmp_path):
        """Collect journals from multiple months"""
        for month in ["01", "02"]:
            month_dir = tmp_path / "Journals" / "2026" / month
            month_dir.mkdir(parents=True)

            journal = month_dir / f"life-index_2026-{month}-15_001.md"
            journal.write_text(
                f"---\ntitle: Month {month}\ndate: 2026-{month}-15\n---\n# Content",
                encoding="utf-8",
            )

        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = collect_year_journals(2026)

        assert len(result) == 2


class TestGenerateMonthlyAbstractContent:
    """Tests for generate_monthly_abstract_content function"""

    def test_generate_with_journals(self):
        """Generate content with journals"""
        journals = [
            {
                "file": "test_001.md",
                "path": "./test_001.md",
                "date": "2026-03-14T10:00:00",
                "title": "Test Entry",
                "tags": ["test"],
                "project": "TestProject",
                "topic": ["work"],
                "mood": ["happy"],
                "people": ["Alice"],
                "abstract": "Test abstract",
            }
        ]

        content = generate_monthly_abstract_content(2026, 3, journals)

        assert "2026" in content
        assert "Test Entry" in content

    def test_generate_empty_journals(self):
        """Generate content with no journals"""
        content = generate_monthly_abstract_content(2026, 3, [])

        assert "0" in content


class TestGenerateYearlyAbstractContent:
    """Tests for generate_yearly_abstract_content function"""

    def test_generate_with_journals(self):
        """Generate yearly content"""
        journals = [
            {
                "file": "test_001.md",
                "path": "./03/test_001.md",
                "month": "03",
                "date": "2026-03-14",
                "title": "Test",
                "tags": ["test"],
                "project": "",
                "topic": ["work"],
                "mood": [],
                "people": [],
                "abstract": "",
            }
        ]

        content = generate_yearly_abstract_content(2026, journals)

        assert "2026" in content


class TestGenerateMonthlyAbstract:
    """Tests for generate_monthly_abstract function"""

    def test_generate_for_empty_month(self, tmp_path):
        """Generate for month with no journals"""
        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = generate_monthly_abstract(2026, 3)

        assert result["success"] is True
        assert result["journal_count"] == 0

    def test_generate_with_journals(self, tmp_path):
        """Generate abstract for month with journals"""
        month_dir = tmp_path / "Journals" / "2026" / "03"
        month_dir.mkdir(parents=True)

        journal = month_dir / "life-index_2026-03-14_001.md"
        journal.write_text(
            """---
title: Test
date: 2026-03-14T10:00:00
topic: ["work"]
---
# Content
""",
            encoding="utf-8",
        )

        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = generate_monthly_abstract(2026, 3)

        assert result["success"] is True
        assert result["journal_count"] == 1
        assert result["updated"] is True

    def test_dry_run(self, tmp_path):
        """Dry run doesn't write file"""
        month_dir = tmp_path / "Journals" / "2026" / "03"
        month_dir.mkdir(parents=True)

        journal = month_dir / "life-index_2026-03-14_001.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\n---\n# Content", encoding="utf-8"
        )

        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = generate_monthly_abstract(2026, 3, dry_run=True)

        assert result["success"] is True
        assert result["updated"] is False


class TestGenerateYearlyAbstract:
    """Tests for generate_yearly_abstract function"""

    def test_generate_for_empty_year(self, tmp_path):
        """Generate for year with no journals"""
        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = generate_yearly_abstract(2026)

        assert result["success"] is True
        assert result["journal_count"] == 0

    def test_generate_with_journals(self, tmp_path):
        """Generate abstract for year with journals"""
        month_dir = tmp_path / "Journals" / "2026" / "03"
        month_dir.mkdir(parents=True)

        journal = month_dir / "life-index_2026-03-14_001.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\n---\n# Content", encoding="utf-8"
        )

        with patch("tools.generate_abstract.JOURNALS_DIR", tmp_path / "Journals"):
            result = generate_yearly_abstract(2026)

        assert result["success"] is True
        assert result["journal_count"] == 1
        assert result["updated"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
