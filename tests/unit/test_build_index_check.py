"""Tests for index --check CLI command (Round 12 Phase 0 Task 0.2)."""

import json
import pickle
import sqlite3
import subprocess
import sys
import pytest
from pathlib import Path


@pytest.fixture
def fresh_data_dir(tmp_path: Path) -> Path:
    """Create a minimal data directory structure for testing."""
    data_dir = tmp_path / "Life-Index"
    journals_dir = data_dir / "Journals" / "2026" / "03"
    journals_dir.mkdir(parents=True)
    index_dir = data_dir / ".index"
    index_dir.mkdir()
    return data_dir


def _create_journal(journals_dir: Path, name: str, title: str = "Test") -> Path:
    """Create a minimal journal file."""
    month_dir = journals_dir / "2026" / "03"
    month_dir.mkdir(parents=True, exist_ok=True)
    p = month_dir / name
    p.write_text(
        f'---\ntitle: "{title}"\ndate: 2026-03-01\ntopic: [life]\n---\n# {title}\nBody',
        encoding="utf-8",
    )
    return p


def _create_fts_db(index_dir: Path, paths: list[str]) -> Path:
    """Create a minimal FTS database with given paths."""
    db_path = index_dir / "journals_fts.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS journals (
            path TEXT PRIMARY KEY, title TEXT, content TEXT,
            date TEXT, location TEXT, weather TEXT, topic TEXT,
            project TEXT, tags TEXT, mood TEXT, people TEXT,
            file_hash TEXT, modified_time TEXT, title_segmented TEXT
        )
    """)
    # Create FTS virtual table so get_fts_count() can query it
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS journals_fts
        USING fts5(title, content, tags, mood, people, topic,
                   tokenize='unicode61')
    """)
    for p in paths:
        conn.execute(
            "INSERT OR REPLACE INTO journals (path, title, date, file_hash) VALUES (?, ?, ?, ?)",
            (p, "Test", "2026-03-01", "abc123"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO journals_fts (title) VALUES (?)",
            ("Test",),
        )
    conn.commit()
    conn.close()
    return db_path


def _create_vector_pickle(index_dir: Path, paths: list[str]) -> Path:
    """Create a minimal vector pickle with given paths."""
    pkl_path = index_dir / "vectors_simple.pkl"
    vectors = {}
    for p in paths:
        vectors[p] = {
            "embedding": [float(i) / 10 for i in range(10)],
            "date": "2026-03-01",
            "hash": "abc123",
        }
    with open(pkl_path, "wb") as f:
        pickle.dump(vectors, f)
    return pkl_path


class TestCheckIndexFunction:
    """Test the check_index() function that backs the CLI command."""

    def test_healthy_consistent_indexes(self, fresh_data_dir: Path):
        """When FTS, manifest, and freshness agree, healthy=True."""
        from tools.build_index import check_index
        from tools.lib.index_manifest import IndexManifest, write_manifest

        journals_dir = fresh_data_dir / "Journals"
        index_dir = fresh_data_dir / ".index"
        paths = ["Journals/2026/03/life-index_2026-03-01_001.md"]
        _create_journal(journals_dir, "life-index_2026-03-01_001.md")
        _create_fts_db(index_dir, paths)
        _create_vector_pickle(index_dir, paths)

        # Round 12 Phase 3: healthy now requires manifest + freshness
        write_manifest(
            IndexManifest(
                fts_count=1,
                vector_count=1,
                file_count=1,
                fts_checksum="a",
                vector_checksum="b",
                build_timestamp="2026-04-18T12:00:00",
                build_version="1.0.0",
            ),
            index_dir,
        )

        from unittest.mock import patch

        with (
            patch("tools.lib.index_freshness.get_fts_count", return_value=1),
            patch("tools.lib.index_freshness.get_vector_count", return_value=1),
        ):
            result = check_index(data_dir=fresh_data_dir)

        assert result["healthy"] is True
        assert result["fts_count"] == 1
        assert result["vector_count"] == 0
        assert result["file_count"] == 1
        assert result["issues"] == []

    def test_unhealthy_fts_missing(self, fresh_data_dir: Path):
        """When FTS is missing entries, healthy=False."""
        from tools.build_index import check_index

        journals_dir = fresh_data_dir / "Journals"
        index_dir = fresh_data_dir / ".index"
        _create_journal(journals_dir, "life-index_2026-03-01_001.md")
        _create_journal(journals_dir, "life-index_2026-03-01_002.md")
        _create_fts_db(index_dir, ["Journals/2026/03/life-index_2026-03-01_001.md"])
        _create_vector_pickle(index_dir, ["Journals/2026/03/life-index_2026-03-01_001.md"])

        result = check_index(data_dir=fresh_data_dir)
        assert result["healthy"] is False
        assert len(result["issues"]) > 0

    def test_empty_directory_is_not_healthy(self, fresh_data_dir: Path):
        """Empty data directory with no indexes + no manifest is not healthy."""
        from tools.build_index import check_index

        result = check_index(data_dir=fresh_data_dir)
        # Round 12 Phase 3: no manifest means not healthy, suggests rebuild
        assert result["healthy"] is False
        assert result["fts_count"] == 0
        assert result["vector_count"] == 0
        assert result["file_count"] == 0
        assert result["manifest"]["exists"] is False
        assert any("rebuild" in str(i).lower() for i in result.get("issues", []))

    def test_output_is_json_serializable(self, fresh_data_dir: Path):
        """Result must be JSON-serializable for CLI output."""
        from tools.build_index import check_index

        result = check_index(data_dir=fresh_data_dir)
        serialized = json.dumps(result, ensure_ascii=False)
        assert isinstance(serialized, str)
        parsed = json.loads(serialized)
        assert "healthy" in parsed
        assert "fts_count" in parsed


class TestCheckIndexCLI:
    """Test index --check via subprocess (integration-level)."""

    def test_check_via_subprocess(self, fresh_data_dir: Path):
        """life-index index --check runs without error."""
        from tools.lib.index_manifest import IndexManifest, write_manifest

        journals_dir = fresh_data_dir / "Journals"
        index_dir = fresh_data_dir / ".index"
        paths = ["Journals/2026/03/life-index_2026-03-01_001.md"]
        _create_journal(journals_dir, "life-index_2026-03-01_001.md")
        _create_fts_db(index_dir, paths)
        _create_vector_pickle(index_dir, paths)

        # Round 12 Phase 3: manifest required for healthy check
        write_manifest(
            IndexManifest(
                fts_count=1,
                vector_count=1,
                file_count=1,
                fts_checksum="a",
                vector_checksum="b",
                build_timestamp="2026-04-18T12:00:00",
                build_version="1.0.0",
            ),
            index_dir,
        )

        result = subprocess.run(
            [sys.executable, "-m", "tools.build_index", "--check"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent.parent.parent,
            env={**__import__("os").environ, "LIFE_INDEX_DATA_DIR": str(fresh_data_dir)},
            timeout=15,
            encoding="utf-8",
        )
        # CLI should succeed (exit 0 for healthy)
        assert result.returncode == 0
        output = json.loads(result.stdout)
        assert output["healthy"] is True
