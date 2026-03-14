#!/usr/bin/env python3
"""
Unit tests for tools/lib/search_index.py

Tests cover:
- FTS5 index creation and management
- Journal parsing
- Index update operations
- FTS search functionality
- File hash computation
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import sqlite3
import tempfile


class TestGetFileHash:
    """Tests for get_file_hash function"""

    def test_hash_computation(self, tmp_path):
        """Hash is computed correctly"""
        from tools.lib.search_index import get_file_hash

        test_file = tmp_path / "test.md"
        test_file.write_text("test content", encoding="utf-8")

        result = get_file_hash(test_file)

        assert result != ""
        assert len(result) == 16  # MD5 first 16 chars

    def test_hash_consistency(self, tmp_path):
        """Same content produces same hash"""
        from tools.lib.search_index import get_file_hash

        test_file = tmp_path / "test.md"
        test_file.write_text("same content", encoding="utf-8")

        hash1 = get_file_hash(test_file)
        hash2 = get_file_hash(test_file)

        assert hash1 == hash2

    def test_hash_different_content(self, tmp_path):
        """Different content produces different hash"""
        from tools.lib.search_index import get_file_hash

        file1 = tmp_path / "test1.md"
        file1.write_text("content 1", encoding="utf-8")

        file2 = tmp_path / "test2.md"
        file2.write_text("content 2", encoding="utf-8")

        hash1 = get_file_hash(file1)
        hash2 = get_file_hash(file2)

        assert hash1 != hash2

    def test_hash_nonexistent_file(self, tmp_path):
        """Nonexistent file returns empty string"""
        from tools.lib.search_index import get_file_hash

        nonexistent = tmp_path / "nonexistent.md"
        result = get_file_hash(nonexistent)

        assert result == ""


class TestInitFtsDb:
    """Tests for init_fts_db function"""

    def test_creates_database(self, tmp_path):
        """Database is created successfully"""
        from tools.lib import search_index

        with patch.object(search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()

        assert conn is not None
        conn.close()

    def test_creates_tables(self, tmp_path):
        """FTS5 table is created"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()

        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='journals'"
        )
        result = cursor.fetchone()

        assert result is not None
        conn.close()

    def test_enables_wal_mode(self, tmp_path):
        """WAL mode is enabled"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()

        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        result = cursor.fetchone()

        assert result[0].lower() == "wal"
        conn.close()


class TestParseJournal:
    """Tests for parse_journal function"""

    def test_parse_valid_journal(self, tmp_path):
        """Valid journal is parsed correctly"""
        from tools.lib import search_index

        journal = tmp_path / "test.md"
        journal.write_text(
            """---
title: Test Journal
date: 2026-03-14
location: Beijing
---

# Test Content

This is the body.
""",
            encoding="utf-8",
        )

        # Mock USER_DATA_DIR to allow relative_to to work
        with patch.object(search_index, "USER_DATA_DIR", tmp_path):
            result = search_index.parse_journal(journal)

        assert result is not None
        assert result.get("title") == "Test Journal"
        assert result.get("date") == "2026-03-14"

    def test_parse_no_frontmatter(self, tmp_path):
        """File without frontmatter returns None"""
        from tools.lib.search_index import parse_journal

        journal = tmp_path / "test.md"
        journal.write_text("# No Frontmatter\n\nJust content.", encoding="utf-8")

        result = parse_journal(journal)

        assert result is None

    def test_parse_incomplete_frontmatter(self, tmp_path):
        """File with incomplete frontmatter returns None"""
        from tools.lib.search_index import parse_journal

        journal = tmp_path / "test.md"
        journal.write_text(
            """---
title: Test

# Content""",
            encoding="utf-8",
        )

        result = parse_journal(journal)

        assert result is None

    def test_parse_nonexistent_file(self, tmp_path):
        """Nonexistent file returns None"""
        from tools.lib.search_index import parse_journal

        nonexistent = tmp_path / "nonexistent.md"
        result = parse_journal(nonexistent)

        assert result is None

    def test_parse_extracts_body(self, tmp_path):
        """Body content is extracted"""
        from tools.lib import search_index

        journal = tmp_path / "test.md"
        journal.write_text(
            """---
title: Test
date: 2026-03-14
---

# Heading

Body paragraph.
""",
            encoding="utf-8",
        )

        # Mock USER_DATA_DIR to allow relative_to to work
        with patch.object(search_index, "USER_DATA_DIR", tmp_path):
            result = search_index.parse_journal(journal)

        assert result is not None
        assert "Body paragraph" in result.get("content", "")

    def test_parse_list_fields(self, tmp_path):
        """List fields in frontmatter are parsed correctly"""
        from tools.lib import search_index

        journal = tmp_path / "test.md"
        journal.write_text(
            """---
title: Test
date: 2026-03-14
topic: [work, learn]
tags: [python, test]
mood: ["happy", "excited"]
---

Content.
""",
            encoding="utf-8",
        )

        with patch.object(search_index, "USER_DATA_DIR", tmp_path):
            result = search_index.parse_journal(journal)

            assert result is not None
            assert "work" in result.get("topic", "")
            assert "learn" in result.get("topic", "")
            assert "python" in result.get("tags", "")


class TestNormalizeToStr:
    """Tests for _normalize_to_str function"""

    def test_string_passthrough(self):
        """String passes through unchanged"""
        from tools.lib.search_index import _normalize_to_str

        assert _normalize_to_str("test") == "test"

    def test_list_to_string(self):
        """List is converted to string"""
        from tools.lib.search_index import _normalize_to_str

        result = _normalize_to_str(["a", "b", "c"])
        assert "a" in result

    def test_none_to_empty(self):
        """None becomes empty string"""
        from tools.lib.search_index import _normalize_to_str

        assert _normalize_to_str(None) == ""

    def test_number_to_string(self):
        """Number is converted to string"""
        from tools.lib.search_index import _normalize_to_str

        assert _normalize_to_str(123) == "123"


class TestGetIndexedFiles:
    """Tests for get_indexed_files function (lines 140-147)"""

    def test_empty_index(self, tmp_path):
        """Empty index returns empty dict"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                result = search_index.get_indexed_files(conn)
                conn.close()

                assert result == {}

    def test_with_indexed_files(self, tmp_path):
        """Returns dict of path -> (hash, modified_time)"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                # Insert test files
                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, file_hash, modified_time)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        "Journals/2026/03/test1.md",
                        "Test 1",
                        "Content 1",
                        "abc123",
                        "2026-03-14T10:00:00",
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, file_hash, modified_time)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        "Journals/2026/03/test2.md",
                        "Test 2",
                        "Content 2",
                        "def456",
                        "2026-03-14T11:00:00",
                    ),
                )
                conn.commit()

                result = search_index.get_indexed_files(conn)
                conn.close()

                assert len(result) == 2
                assert "Journals/2026/03/test1.md" in result
                assert result["Journals/2026/03/test1.md"] == (
                    "abc123",
                    "2026-03-14T10:00:00",
                )
                assert result["Journals/2026/03/test2.md"] == (
                    "def456",
                    "2026-03-14T11:00:00",
                )


class TestUpdateIndex:
    """Tests for update_index function (lines 167-270)"""

    def test_full_rebuild_empty_dirs(self, tmp_path):
        """Full rebuild with no journals"""
        from tools.lib import search_index

        journals_dir = tmp_path / "Journals"
        journals_dir.mkdir(parents=True)

        with patch.object(search_index, "JOURNALS_DIR", journals_dir):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        result = search_index.update_index(incremental=False)

                        assert result["success"] is True
                        assert result["added"] == 0
                        assert result["total"] == 0

    def test_incremental_add_new_file(self, tmp_path):
        """Incremental update adds new files"""
        from tools.lib import search_index

        # Setup directory structure
        journals_dir = tmp_path / "Journals" / "2026" / "03"
        journals_dir.mkdir(parents=True)

        # Create a test journal file
        journal_file = journals_dir / "life-index_2026-03-14_001.md"
        journal_file.write_text(
            """---
title: New Journal
date: 2026-03-14
topic: work
---

# Content

This is new content.
""",
            encoding="utf-8",
        )

        with patch.object(search_index, "JOURNALS_DIR", tmp_path / "Journals"):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        result = search_index.update_index(incremental=True)

                        assert result["success"] is True
                        assert result["added"] == 1
                        assert result["total"] == 1

    def test_incremental_update_modified_file(self, tmp_path):
        """Incremental update detects modified files"""
        from tools.lib import search_index

        # Setup directory structure
        journals_dir = tmp_path / "Journals" / "2026" / "03"
        journals_dir.mkdir(parents=True)

        # Create initial journal
        journal_file = journals_dir / "life-index_2026-03-14_001.md"
        journal_file.write_text(
            """---
title: Original
date: 2026-03-14
---

Original content.
""",
            encoding="utf-8",
        )

        with patch.object(search_index, "JOURNALS_DIR", tmp_path / "Journals"):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        # First update - add file
                        result1 = search_index.update_index(incremental=True)
                        assert result1["success"] is True
                        assert result1["added"] == 1

                        # Modify file
                        journal_file.write_text(
                            """---
title: Modified
date: 2026-03-14
---

Modified content.
""",
                            encoding="utf-8",
                        )

                        # Second update - should detect modification
                        result2 = search_index.update_index(incremental=True)
                        assert result2["success"] is True
                        assert result2["updated"] == 1

    def test_incremental_remove_deleted_file(self, tmp_path):
        """Incremental update removes deleted files from index"""
        from tools.lib import search_index

        # Setup directory structure
        journals_dir = tmp_path / "Journals" / "2026" / "03"
        journals_dir.mkdir(parents=True)

        # Create journal
        journal_file = journals_dir / "life-index_2026-03-14_001.md"
        journal_file.write_text(
            """---
title: To Delete
date: 2026-03-14
---

Content to delete.
""",
            encoding="utf-8",
        )

        with patch.object(search_index, "JOURNALS_DIR", tmp_path / "Journals"):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        # Add file
                        result1 = search_index.update_index(incremental=True)
                        assert result1["added"] == 1

                        # Delete file
                        journal_file.unlink()

                        # Update - should remove from index
                        result2 = search_index.update_index(incremental=True)
                        assert result2["success"] is True
                        assert result2["removed"] == 1

    def test_full_rebuild_with_files(self, tmp_path):
        """Full rebuild clears and reindexes all files"""
        from tools.lib import search_index

        journals_dir = tmp_path / "Journals" / "2026" / "03"
        journals_dir.mkdir(parents=True)

        # Create two journals
        for i in range(2):
            journal_file = journals_dir / f"life-index_2026-03-1{i + 1}_00{i + 1}.md"
            journal_file.write_text(
                f"""---
title: Journal {i + 1}
date: 2026-03-1{i + 1}
---

Content {i + 1}.
""",
                encoding="utf-8",
            )

        with patch.object(search_index, "JOURNALS_DIR", tmp_path / "Journals"):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        # Incremental add
                        result1 = search_index.update_index(incremental=True)
                        assert result1["added"] == 2

                        # Full rebuild
                        result2 = search_index.update_index(incremental=False)
                        assert result2["success"] is True
                        assert result2["total"] == 2

    def test_invalid_journal_skipped(self, tmp_path):
        """Invalid journal files are skipped"""
        from tools.lib import search_index

        # Setup: tmp_path/Journals/2026/03/
        journals_dir = tmp_path / "Journals"
        year_dir = journals_dir / "2026"
        year_dir.mkdir(parents=True)
        month_dir = year_dir / "03"
        month_dir.mkdir()

        # Create valid journal
        valid = month_dir / "life-index_2026-03-14_001.md"
        valid.write_text(
            """---
title: Valid
date: 2026-03-14
---

Valid content.
""",
            encoding="utf-8",
        )

        # Create invalid journal (no frontmatter)
        invalid = month_dir / "life-index_2026-03-14_002.md"
        invalid.write_text("# No Frontmatter\n\nJust content.", encoding="utf-8")

        with patch.object(search_index, "JOURNALS_DIR", journals_dir):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        result = search_index.update_index(incremental=True)

                        assert result["success"] is True
                        assert result["added"] == 1  # Only valid file indexed

    def test_non_year_directories_skipped(self, tmp_path):
        """Non-year directories are skipped during scan"""
        from tools.lib import search_index

        journals_dir = tmp_path / "Journals"
        journals_dir.mkdir(parents=True)

        # Create invalid year dir
        invalid_year = journals_dir / "not_a_year"
        invalid_year.mkdir()
        (invalid_year / "test.md").write_text("content")

        # Create valid year dir
        valid_year = journals_dir / "2026"
        valid_year.mkdir()
        month_dir = valid_year / "03"
        month_dir.mkdir()
        journal = month_dir / "life-index_2026-03-14_001.md"
        journal.write_text(
            """---
title: Valid
date: 2026-03-14
---

Content.
""",
            encoding="utf-8",
        )

        with patch.object(search_index, "JOURNALS_DIR", journals_dir):
            with patch.object(search_index, "USER_DATA_DIR", tmp_path):
                with patch.object(
                    search_index, "FTS_DB_PATH", tmp_path / "test_fts.db"
                ):
                    with patch.object(search_index, "INDEX_DIR", tmp_path / ".index"):
                        result = search_index.update_index(incremental=False)

                        assert result["success"] is True
                        assert result["total"] == 1


class TestSearchFtsEdgeCases:
    """Extended tests for search_fts (lines 314-318, 350-351)"""

    def test_search_with_date_filters(self, tmp_path):
        """Search respects date_from and date_to filters"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                # Insert journals with different dates
                for i in range(3):
                    cursor.execute(
                        """
                        INSERT INTO journals (path, title, content, date)
                        VALUES (?, ?, ?, ?)
                    """,
                        (
                            f"test{i}.md",
                            f"Test {i}",
                            "Python programming",
                            f"2026-03-{10 + i}",
                        ),
                    )
                conn.commit()
                conn.close()

                # Search with date filter
                results = search_index.search_fts(
                    "Python", date_from="2026-03-11", date_to="2026-03-12"
                )

                assert len(results) == 2
                for r in results:
                    assert "2026-03-11" <= r["date"] <= "2026-03-12"

    def test_search_special_characters(self, tmp_path):
        """Search handles special characters in query"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, date)
                    VALUES (?, ?, ?, ?)
                """,
                    ("test.md", "Test", "C++ programming & Python", "2026-03-14"),
                )
                conn.commit()
                conn.close()

                # Search with special chars - should not crash
                results = search_index.search_fts("C++")
                assert isinstance(results, list)

    def test_search_unicode_content(self, tmp_path):
        """Search handles Unicode content"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, date)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        "test.md",
                        "中文测试",
                        "今天天气很好，适合编程",
                        "2026-03-14",
                    ),
                )
                conn.commit()
                conn.close()

                # FTS5 supports Unicode, search for 编程 (programming)
                results = search_index.search_fts("编程")
                # Note: FTS5 may or may not tokenize Chinese characters properly
                # depending on build, so we just verify it doesn't crash
                assert isinstance(results, list)

    def test_search_very_long_query(self, tmp_path):
        """Search handles very long queries"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                long_content = " ".join(["word"] * 1000)
                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, date)
                    VALUES (?, ?, ?, ?)
                """,
                    ("test.md", "Long Content", long_content, "2026-03-14"),
                )
                conn.commit()
                conn.close()

                long_query = " ".join(["word"] * 100)
                results = search_index.search_fts(long_query)
                assert isinstance(results, list)

    def test_search_limit(self, tmp_path):
        """Search respects limit parameter"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                # Insert 10 journals
                for i in range(10):
                    cursor.execute(
                        """
                        INSERT INTO journals (path, title, content, date)
                        VALUES (?, ?, ?, ?)
                    """,
                        (f"test{i}.md", f"Test {i}", "Python", f"2026-03-{10 + i}"),
                    )
                conn.commit()
                conn.close()

                results = search_index.search_fts("Python", limit=5)
                assert len(results) <= 5

    def test_search_bm25_ranking(self, tmp_path):
        """Search results are ranked by BM25"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                # Insert journals with varying relevance
                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, date)
                    VALUES (?, ?, ?, ?)
                """,
                    ("test1.md", "Python Guide", "Python Python Python", "2026-03-10"),
                )
                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, date)
                    VALUES (?, ?, ?, ?)
                """,
                    ("test2.md", "Other", "Mention of python once", "2026-03-11"),
                )
                conn.commit()
                conn.close()

                results = search_index.search_fts("Python")

                # Check results have BM25 scores
                assert len(results) >= 1
                for r in results:
                    assert "bm25_score" in r
                    assert "relevance" in r
                    assert 0 <= r["relevance"] <= 100

    def test_search_sqlite_error(self, tmp_path):
        """Search handles SQLite errors gracefully"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                conn.close()

                # Corrupt the database
                db_path.write_bytes(b"corrupted data")

                # Should not raise, returns empty list
                results = search_index.search_fts("test")
                assert results == []


class TestGetStatsEdgeCases:
    """Extended tests for get_stats (lines 378-383)"""

    def test_stats_corrupted_database(self, tmp_path):
        """Stats handles corrupted database"""
        from tools.lib import search_index

        db_path = tmp_path / "corrupted.db"
        db_path.write_bytes(b"not a sqlite database")

        with patch.object(search_index, "FTS_DB_PATH", db_path):
            stats = search_index.get_stats()

            assert stats.get("exists") is True
            assert stats.get("total_documents") == 0

    def test_stats_empty_database(self, tmp_path):
        """Stats with empty database"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                conn.close()

                stats = search_index.get_stats()

                assert stats.get("exists") is True
                assert stats.get("total_documents") == 0
                assert stats.get("db_size_mb", 0) >= 0

    def test_stats_with_last_updated(self, tmp_path):
        """Stats includes last updated time"""
        from tools.lib import search_index

        db_path = tmp_path / "test_fts.db"
        with patch.object(search_index, "FTS_DB_PATH", db_path):
            with patch.object(search_index, "INDEX_DIR", tmp_path):
                conn = search_index.init_fts_db()
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT INTO journals (path, title, content, modified_time)
                    VALUES (?, ?, ?, ?)
                """,
                    ("test.md", "Test", "Content", "2026-03-14T10:00:00"),
                )
                conn.commit()
                conn.close()

                stats = search_index.get_stats()

                assert stats.get("last_updated") == "2026-03-14T10:00:00"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
