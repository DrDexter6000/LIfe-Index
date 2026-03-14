#!/usr/bin/env python3
"""
Unit tests for tools/edit_journal/__init__.py

Tests cover:
- Journal parsing
- Frontmatter updates
- Index operations
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestParseJournal:
    """Tests for parse_journal function"""

    def test_parse_valid_journal(self, tmp_path):
        """Parse a valid journal file"""
        from tools.edit_journal import parse_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            """---
title: Test Journal
date: 2026-03-14
location: Beijing
---

# Test Content
""",
            encoding="utf-8",
        )

        metadata, body = parse_journal(journal)

        assert metadata.get("title") == "Test Journal"
        assert "Test Content" in body

    def test_parse_nonexistent_file(self, tmp_path):
        """Parse nonexistent file"""
        from tools.edit_journal import parse_journal

        nonexistent = tmp_path / "nonexistent.md"
        metadata, body = parse_journal(nonexistent)

        assert "_error" in metadata or metadata.get("title") is None


class TestRemoveFromIndex:
    """Tests for remove_from_index function"""

    def test_remove_existing_entry(self, tmp_path):
        """Remove existing entry from index"""
        from tools.edit_journal import remove_from_index

        index_file = tmp_path / "index.md"
        index_file.write_text(
            """# 主题: work

- [2026-03-14] [Test](../../Journals/2026/03/test_001.md)
- [2026-03-15] [Other](../../Journals/2026/03/other_001.md)
""",
            encoding="utf-8",
        )

        result = remove_from_index(index_file, "test_001.md")

        assert result is True
        content = index_file.read_text(encoding="utf-8")
        assert "test_001.md" not in content
        assert "other_001.md" in content

    def test_remove_nonexistent_entry(self, tmp_path):
        """Remove nonexistent entry returns False"""
        from tools.edit_journal import remove_from_index

        index_file = tmp_path / "index.md"
        index_file.write_text(
            """# 主题: work

- [2026-03-14] [Test](../../Journals/2026/03/test_001.md)
""",
            encoding="utf-8",
        )

        result = remove_from_index(index_file, "nonexistent.md")

        assert result is False

    def test_remove_from_nonexistent_index(self, tmp_path):
        """Remove from nonexistent index returns False"""
        from tools.edit_journal import remove_from_index

        nonexistent = tmp_path / "nonexistent.md"
        result = remove_from_index(nonexistent, "test.md")

        assert result is False


class TestNormalizeToList:
    """Tests for _normalize_to_list helper"""

    def test_string_to_list(self):
        """String becomes list"""
        from tools.edit_journal import _normalize_to_list

        assert _normalize_to_list("work") == ["work"]

    def test_list_unchanged(self):
        """List stays as list"""
        from tools.edit_journal import _normalize_to_list

        assert _normalize_to_list(["work", "learn"]) == ["work", "learn"]

    def test_empty_returns_empty(self):
        """Empty returns empty list"""
        from tools.edit_journal import _normalize_to_list

        assert _normalize_to_list(None) == []
        assert _normalize_to_list("") == []
        assert _normalize_to_list([]) == []


class TestAddToIndex:
    """Tests for add_to_index function"""

    def test_add_to_existing_index(self, tmp_path):
        """Add entry to existing index file"""
        from tools.edit_journal import add_to_index

        index_file = tmp_path / "主题_work.md"
        index_file.write_text(
            "# 主题：work\n\n- [2026-03-13] [Old](path/old.md)\n", encoding="utf-8"
        )

        journal_path = tmp_path / "Journals" / "2026" / "03" / "test_001.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        journal_path.write_text("# Test", encoding="utf-8")

        data = {"date": "2026-03-14T10:00:00", "title": "Test Entry"}
        add_to_index(index_file, journal_path, data)

        content = index_file.read_text(encoding="utf-8")
        assert "Test Entry" in content
        assert "2026-03-14" in content

    def test_create_new_topic_index(self, tmp_path):
        """Create new index file with topic prefix"""
        from tools.edit_journal import add_to_index

        index_file = tmp_path / "主题_learn.md"
        journal_path = tmp_path / "Journals" / "2026" / "03" / "test.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"date": "2026-03-14T10:00:00", "title": "Learning"}
        add_to_index(index_file, journal_path, data)

        content = index_file.read_text(encoding="utf-8")
        assert "# 主题：learn" in content
        assert "Learning" in content

    def test_create_new_project_index(self, tmp_path):
        """Create new index file with project prefix"""
        from tools.edit_journal import add_to_index

        index_file = tmp_path / "项目_MyProject.md"
        journal_path = tmp_path / "Journals" / "2026" / "03" / "test.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"date": "2026-03-14T10:00:00", "title": "Project Update"}
        add_to_index(index_file, journal_path, data)

        content = index_file.read_text(encoding="utf-8")
        assert "# 项目：MyProject" in content

    def test_create_new_tag_index(self, tmp_path):
        """Create new index file with tag prefix"""
        from tools.edit_journal import add_to_index

        index_file = tmp_path / "标签_重要.md"
        journal_path = tmp_path / "Journals" / "2026" / "03" / "test.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"date": "2026-03-14T10:00:00", "title": "Important Note"}
        add_to_index(index_file, journal_path, data)

        content = index_file.read_text(encoding="utf-8")
        assert "# 标签：重要" in content

    def test_prevent_duplicate_entries(self, tmp_path):
        """Prevent duplicate entries in index"""
        from tools.edit_journal import add_to_index

        index_file = tmp_path / "主题_work.md"
        journal_path = tmp_path / "Journals" / "2026" / "03" / "test.md"
        journal_path.parent.mkdir(parents=True, exist_ok=True)

        data = {"date": "2026-03-14T10:00:00", "title": "Test"}

        # Add twice
        add_to_index(index_file, journal_path, data)
        add_to_index(index_file, journal_path, data)

        content = index_file.read_text(encoding="utf-8")
        assert content.count("Test") == 1


class TestUpdateIndicesForChange:
    """Tests for update_indices_for_change function"""

    def test_topic_change(self, tmp_path):
        """Update indices when topic changes"""
        from tools.edit_journal import update_indices_for_change

        # Create old index
        old_index = tmp_path / "主题_work.md"
        old_index.write_text(
            "# 主题：work\n\n- [2026-03-14] [Test](path.md)\n", encoding="utf-8"
        )

        journal_path = tmp_path / "test.md"
        journal_path.write_text("# Test", encoding="utf-8")

        old_data = {"topic": ["work"]}
        new_data = {"topic": ["learn"], "date": "2026-03-14", "title": "Test"}

        with patch("tools.edit_journal.BY_TOPIC_DIR", tmp_path):
            updated = update_indices_for_change(journal_path, old_data, new_data)

        assert len(updated) >= 1

    def test_project_change(self, tmp_path):
        """Update indices when project changes"""
        from tools.edit_journal import update_indices_for_change

        old_index = tmp_path / "项目_OldProject.md"
        old_index.write_text(
            "# 项目：OldProject\n\n- [Test](path.md)\n", encoding="utf-8"
        )

        journal_path = tmp_path / "test.md"
        journal_path.write_text("# Test", encoding="utf-8")

        old_data = {"project": "OldProject"}
        new_data = {"project": "NewProject", "date": "2026-03-14", "title": "Test"}

        with patch("tools.edit_journal.BY_TOPIC_DIR", tmp_path):
            updated = update_indices_for_change(journal_path, old_data, new_data)

        assert len(updated) >= 1

    def test_tags_change(self, tmp_path):
        """Update indices when tags change"""
        from tools.edit_journal import update_indices_for_change

        old_index = tmp_path / "标签_old.md"
        old_index.write_text("# 标签：old\n\n- [Test](path.md)\n", encoding="utf-8")

        journal_path = tmp_path / "test.md"
        journal_path.write_text("# Test", encoding="utf-8")

        old_data = {"tags": ["old"]}
        new_data = {"tags": ["new"], "date": "2026-03-14", "title": "Test"}

        with patch("tools.edit_journal.BY_TOPIC_DIR", tmp_path):
            updated = update_indices_for_change(journal_path, old_data, new_data)

        assert len(updated) >= 1


class TestEditJournal:
    """Tests for edit_journal main function"""

    def test_edit_nonexistent_journal(self, tmp_path):
        """Edit nonexistent journal returns error"""
        from tools.edit_journal import edit_journal

        nonexistent = tmp_path / "nonexistent.md"
        result = edit_journal(nonexistent, {"weather": "Sunny"})

        assert result["success"] is False
        assert result["error"]["code"] == "E0500"

    def test_edit_no_changes_specified(self, tmp_path):
        """Edit with no changes returns error"""
        from tools.edit_journal import edit_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\n---\n\n# Content\n", encoding="utf-8"
        )

        result = edit_journal(journal, {})

        assert result["success"] is False
        assert result["error"]["code"] == "E0503"

    def test_edit_with_dry_run(self, tmp_path):
        """Edit with dry_run doesn't modify file"""
        from tools.edit_journal import edit_journal

        journal = tmp_path / "test.md"
        original = "---\ntitle: Test\ndate: 2026-03-14\n---\n\n# Content\n"
        journal.write_text(original, encoding="utf-8")

        result = edit_journal(journal, {"weather": "Sunny"}, dry_run=True)

        assert result["success"] is True
        assert "preview" in result
        assert journal.read_text(encoding="utf-8") == original

    def test_edit_update_weather(self, tmp_path):
        """Edit updates weather field"""
        from tools.edit_journal import edit_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\n---\n\n# Content\n", encoding="utf-8"
        )

        result = edit_journal(journal, {"weather": "Sunny"})

        assert result["success"] is True
        assert "weather" in result["changes"]

        content = journal.read_text(encoding="utf-8")
        assert "Sunny" in content

    def test_edit_append_content(self, tmp_path):
        """Edit appends content to body"""
        from tools.edit_journal import edit_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\n---\n\n# Content\n", encoding="utf-8"
        )

        result = edit_journal(journal, {}, append_content="New paragraph")

        assert result["success"] is True
        assert result["content_modified"] is True

        content = journal.read_text(encoding="utf-8")
        assert "New paragraph" in content

    def test_edit_replace_content(self, tmp_path):
        """Edit replaces body content"""
        from tools.edit_journal import edit_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\n---\n\n# Old Content\n",
            encoding="utf-8",
        )

        result = edit_journal(journal, {}, replace_content="# New Content\n\nReplaced.")

        assert result["success"] is True
        assert result["content_modified"] is True

        content = journal.read_text(encoding="utf-8")
        assert "Old Content" not in content
        assert "New Content" in content

    def test_edit_delete_field_with_empty_string(self, tmp_path):
        """Edit deletes field when value is empty string"""
        from tools.edit_journal import edit_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            "---\ntitle: Test\ndate: 2026-03-14\nweather: Sunny\n---\n\n# Content\n",
            encoding="utf-8",
        )

        result = edit_journal(journal, {"weather": ""})

        assert result["success"] is True
        assert result["changes"]["weather"]["new"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
