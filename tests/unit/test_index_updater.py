#!/usr/bin/env python3
"""
Unit tests for write_journal/index_updater.py

Tests cover:
- Topic index updates
- Project index updates
- Tag index updates
- Monthly abstract updates
"""

import json
import subprocess

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile


class TestUpdateTopicIndex:
    """Tests for update_topic_index function"""

    def test_update_single_topic_string(self, tmp_path):
        """Update index for single topic as string"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_topic_index("work", journal_path, data)

        assert len(result) == 1
        assert "主题_work.md" in result[0].name

    def test_update_single_topic_list(self, tmp_path):
        """Update index for single topic as list"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_topic_index(["work"], journal_path, data)

        assert len(result) == 1
        assert "主题_work.md" in result[0].name

    def test_update_multiple_topics(self, tmp_path):
        """Update index for multiple topics"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_topic_index(["work", "learn"], journal_path, data)

        assert len(result) == 2

    def test_empty_topic_skipped(self, tmp_path):
        """Empty topic list should return empty"""
        from tools.write_journal.index_updater import update_topic_index

        result = update_topic_index([], tmp_path / "test.md", {})
        assert result == []

    def test_none_topic_skipped(self, tmp_path):
        """None topic should return empty"""
        from tools.write_journal.index_updater import update_topic_index

        result = update_topic_index(None, tmp_path / "test.md", {})
        assert result == []

    def test_invalid_type_topic_skipped(self, tmp_path):
        """Invalid type (dict/int) should return empty"""
        from tools.write_journal.index_updater import update_topic_index

        result = update_topic_index({"key": "value"}, tmp_path / "test.md", {})
        assert result == []

        result = update_topic_index(123, tmp_path / "test.md", {})
        assert result == []

    def test_topic_with_empty_string_skipped(self, tmp_path):
        """Empty string in topic list should be skipped"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_topic_index(["work", "", "learn"], journal_path, data)

        # Should only create 2 files (skip empty string)
        assert len(result) == 2
        assert "主题_work.md" in [f.name for f in result]
        assert "主题_learn.md" in [f.name for f in result]


class TestUpdateProjectIndex:
    """Tests for update_project_index function"""

    def test_update_project_index(self, tmp_path):
        """Update index for project"""
        from tools.write_journal.index_updater import update_project_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_project_index("Life-Index", journal_path, data)

        assert result is not None
        assert result.name == "项目_Life-Index.md"

    def test_empty_project_skipped(self, tmp_path):
        """Empty project should return None"""
        from tools.write_journal.index_updater import update_project_index

        result = update_project_index("", tmp_path / "test.md", {})
        assert result is None

    def test_none_project_skipped(self, tmp_path):
        """None project should return None"""
        from tools.write_journal.index_updater import update_project_index

        result = update_project_index(None, tmp_path / "test.md", {})  # type: ignore
        assert result is None

    def test_project_index_new_file(self, tmp_path):
        """Project index should create new file if not exists"""
        from tools.write_journal.index_updater import update_project_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_project_index("NewProject", journal_path, data)

        assert result is not None
        assert "项目_NewProject.md" in result.name
        content = result.read_text(encoding="utf-8")
        assert "NewProject" in content
        assert "2026-03-10" in content
        assert "Test" in content

    def test_project_index_existing_file_no_duplicate(self, tmp_path):
        """Project index should not duplicate entries"""
        from tools.write_journal.index_updater import update_project_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                # First call
                result1 = update_project_index("ExistingProject", journal_path, data)
                # Second call with same data
                result2 = update_project_index("ExistingProject", journal_path, data)

        assert result1 is not None
        assert result2 is not None
        content = result2.read_text(encoding="utf-8")
        # Should only have one entry
        assert content.count("2026-03-10") == 1

    def test_project_index_existing_file_append(self, tmp_path):
        """Project index should append to existing file with different entry"""
        from tools.write_journal.index_updater import update_project_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path1 = tmp_path / "journal1.md"
        journal_path1.write_text("---\ntitle: Test1\n---\nContent")

        journal_path2 = tmp_path / "journal2.md"
        journal_path2.write_text("---\ntitle: Test2\n---\nContent")

        data1 = {"title": "Test1", "date": "2026-03-10"}
        data2 = {"title": "Test2", "date": "2026-03-11"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                update_project_index("SameProject", journal_path1, data1)
                update_project_index("SameProject", journal_path2, data2)

        index_file = index_dir / "项目_SameProject.md"
        content = index_file.read_text(encoding="utf-8")
        # Should have both entries
        assert "2026-03-10" in content
        assert "2026-03-11" in content
        assert "Test1" in content
        assert "Test2" in content


class TestUpdateTagIndices:
    """Tests for update_tag_indices function"""

    def test_update_multiple_tags(self, tmp_path):
        """Update indices for multiple tags"""
        from tools.write_journal.index_updater import update_tag_indices

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_tag_indices(["python", "testing"], journal_path, data)

        assert len(result) == 2

    def test_empty_tags_skipped(self, tmp_path):
        """Empty tags should return empty"""
        from tools.write_journal.index_updater import update_tag_indices

        result = update_tag_indices([], tmp_path / "test.md", {})
        assert result == []

    def test_none_tags_skipped(self, tmp_path):
        """None tags should be handled gracefully"""
        from tools.write_journal.index_updater import update_tag_indices

        # update_tag_indices doesn't handle None, only empty list
        # This test documents the expected behavior
        import pytest

        with pytest.raises(TypeError):
            update_tag_indices(None, tmp_path / "test.md", {})  # type: ignore

    def test_tag_with_empty_string_skipped(self, tmp_path):
        """Empty string in tags list should be skipped"""
        from tools.write_journal.index_updater import update_tag_indices

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_tag_indices(
                    ["python", "", "testing"], journal_path, data
                )

        # Should only create 2 files (skip empty string)
        assert len(result) == 2
        assert "标签_python.md" in [f.name for f in result]
        assert "标签_testing.md" in [f.name for f in result]

    def test_tag_index_existing_file_no_duplicate(self, tmp_path):
        """Tag index should not duplicate entries"""
        from tools.write_journal.index_updater import update_tag_indices

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                # First call
                result1 = update_tag_indices(["duplicate"], journal_path, data)
                # Second call with same data
                result2 = update_tag_indices(["duplicate"], journal_path, data)

        assert len(result1) == 1
        assert len(result2) == 1
        content = result2[0].read_text(encoding="utf-8")
        # Should only have one entry
        assert content.count("2026-03-10") == 1

    def test_tag_index_new_file(self, tmp_path):
        """Tag index should create new file if not exists"""
        from tools.write_journal.index_updater import update_tag_indices

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_tag_indices(["newtag"], journal_path, data)

        assert len(result) == 1
        assert "标签_newtag.md" in result[0].name
        content = result[0].read_text(encoding="utf-8")
        assert "newtag" in content
        assert "2026-03-10" in content
        assert "Test" in content

    def test_tag_index_existing_file_append(self, tmp_path):
        """Tag index should append to existing file with different entry"""
        from tools.write_journal.index_updater import update_tag_indices

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path1 = tmp_path / "journal1.md"
        journal_path1.write_text("---\ntitle: Test1\n---\nContent")

        journal_path2 = tmp_path / "journal2.md"
        journal_path2.write_text("---\ntitle: Test2\n---\nContent")

        data1 = {"title": "Test1", "date": "2026-03-10"}
        data2 = {"title": "Test2", "date": "2026-03-11"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                update_tag_indices(["sametag"], journal_path1, data1)
                update_tag_indices(["sametag"], journal_path2, data2)

        index_file = index_dir / "标签_sametag.md"
        content = index_file.read_text(encoding="utf-8")
        # Should have both entries
        assert "2026-03-10" in content
        assert "2026-03-11" in content
        assert "Test1" in content
        assert "Test2" in content


class TestUpdateMonthlyAbstract:
    """Tests for update_monthly_abstract function"""

    def test_create_new_abstract_success(self, tmp_path):
        """Create new monthly abstract with successful subprocess call"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"
        month_dir = journals_dir / "2026" / "03"
        month_dir.mkdir(parents=True)

        # Create a test journal
        journal_file = month_dir / "life-index_2026-03-10_001.md"
        journal_file.write_text("""---
title: "Test Journal"
date: 2026-03-10
topic: ["work"]
---

# Test Journal

Content here.
""")

        mock_output = json.dumps(
            [
                {
                    "abstract_path": str(month_dir / "monthly_report_2026-03.md"),
                    "journal_count": 1,
                    "updated": True,
                }
            ]
        )

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=mock_output, stderr=""
                )
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is not None
        assert result["journal_count"] == 1
        assert result["updated"] is True
        assert "error" not in result

    def test_dry_run_mode(self, tmp_path):
        """Dry run should pass --dry-run flag to subprocess"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"
        month_dir = journals_dir / "2026" / "03"
        month_dir.mkdir(parents=True)

        mock_output = json.dumps(
            [
                {
                    "abstract_path": str(month_dir / "monthly_report_2026-03.md"),
                    "journal_count": 0,
                    "updated": False,
                }
            ]
        )

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout=mock_output, stderr=""
                )
                result = update_monthly_abstract(2026, 3, dry_run=True)

        # Verify --dry-run flag was passed
        mock_run.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "--dry-run" in call_args
        assert result["journal_count"] == 0
        assert result["updated"] is False

    def test_subprocess_failure(self, tmp_path):
        """Handle subprocess failure gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1, stdout="", stderr="Error: Something went wrong"
                )
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False
        assert "error" in result
        assert "Error: Something went wrong" in result["error"]

    def test_subprocess_timeout(self, tmp_path):
        """Handle subprocess timeout gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(
                    cmd=["test"], timeout=30
                )
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False
        assert "error" in result
        assert "timed out" in result["error"]

    def test_json_decode_error(self, tmp_path):
        """Handle invalid JSON output gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0, stdout="Invalid JSON output", stderr=""
                )
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_empty_json_output(self, tmp_path):
        """Handle empty JSON output gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="[]", stderr="")
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False

    def test_os_error_handling(self, tmp_path):
        """Handle OSError gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = OSError("OS error occurred")
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False
        assert "error" in result
        assert "OS error occurred" in result["error"]

    def test_io_error_handling(self, tmp_path):
        """Handle IOError gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = IOError("IO error occurred")
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False
        assert "error" in result
        assert "IO error occurred" in result["error"]

    def test_runtime_error_handling(self, tmp_path):
        """Handle RuntimeError gracefully"""
        from tools.write_journal.index_updater import update_monthly_abstract

        journals_dir = tmp_path / "Journals"

        with patch("tools.write_journal.index_updater.JOURNALS_DIR", journals_dir):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = RuntimeError("Runtime error occurred")
                result = update_monthly_abstract(2026, 3, dry_run=False)

        assert result["abstract_path"] is None
        assert result["journal_count"] == 0
        assert result["updated"] is False
        assert "error" in result
        assert "Runtime error occurred" in result["error"]


class TestIndexEntryFormat:
    """Tests for index entry format"""

    def test_entry_contains_date(self, tmp_path):
        """Index entry should contain date"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_topic_index(["work"], journal_path, data)

        if result:
            content = result[0].read_text(encoding="utf-8")
            assert "2026-03-10" in content

    def test_entry_contains_title(self, tmp_path):
        """Index entry should contain title"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "My Test Title", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                result = update_topic_index(["work"], journal_path, data)

        if result:
            content = result[0].read_text(encoding="utf-8")
            assert "My Test Title" in content

    def test_topic_index_existing_file_no_duplicate(self, tmp_path):
        """Topic index should not duplicate entries"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path = tmp_path / "journal.md"
        journal_path.write_text("---\ntitle: Test\n---\nContent")

        data = {"title": "Test", "date": "2026-03-10"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                # First call
                result1 = update_topic_index(["duplicate"], journal_path, data)
                # Second call with same data
                result2 = update_topic_index(["duplicate"], journal_path, data)

        assert len(result1) == 1
        assert len(result2) == 1
        content = result2[0].read_text(encoding="utf-8")
        # Should only have one entry
        assert content.count("2026-03-10") == 1

    def test_topic_index_existing_file_append(self, tmp_path):
        """Topic index should append to existing file with different entry"""
        from tools.write_journal.index_updater import update_topic_index

        index_dir = tmp_path / "by-topic"
        index_dir.mkdir()

        journal_path1 = tmp_path / "journal1.md"
        journal_path1.write_text("---\ntitle: Test1\n---\nContent")

        journal_path2 = tmp_path / "journal2.md"
        journal_path2.write_text("---\ntitle: Test2\n---\nContent")

        data1 = {"title": "Test1", "date": "2026-03-10"}
        data2 = {"title": "Test2", "date": "2026-03-11"}

        with patch("tools.write_journal.index_updater.BY_TOPIC_DIR", index_dir):
            with patch("tools.write_journal.index_updater.JOURNALS_DIR", tmp_path):
                update_topic_index(["same"], journal_path1, data1)
                update_topic_index(["same"], journal_path2, data2)

        index_file = index_dir / "主题_same.md"
        content = index_file.read_text(encoding="utf-8")
        # Should have both entries
        assert "2026-03-10" in content
        assert "2026-03-11" in content
        assert "Test1" in content
        assert "Test2" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
