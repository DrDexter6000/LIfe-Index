#!/usr/bin/env python3
"""Contract test: cache version sidecar, index --cache-dry-run, health --cache-audit.

Verifies:
- First index run creates .life-index/cache/_version.json with correct shape
- index --cache-dry-run reports invalidation without creating or modifying files
- health --cache-audit --json returns read-only version status
- All tests use isolated temp data dirs; no production data writes
"""

import json
import os
import subprocess
import sys
from pathlib import Path

CACHE_VERSION_RELPATH = ".life-index/cache/_version.json"


# ============================================================
# Direct function tests (sidecar read/write logic)
# ============================================================


class TestCacheVersionSidecar:
    """Test that cache version sidecar is written and read correctly."""

    def test_get_cache_version_path_returns_expected(self, isolated_data_dir):
        from tools.lib.metadata_cache import get_cache_version_path

        p = get_cache_version_path()
        assert p.parts[-3:] == (".life-index", "cache", "_version.json")

    def test_write_and_read_cache_version_roundtrip(self, isolated_data_dir):
        from tools.lib.metadata_cache import write_cache_version, read_cache_version

        data = write_cache_version(source_hash="sha256:abc123")
        assert data["schema_version"] == "v1.1.2"
        assert data["source_hash"] == "sha256:abc123"
        assert "tool_version" in data
        assert "created_at" in data
        assert isinstance(data["created_at"], str)
        assert "invalidation_history" in data
        assert isinstance(data["invalidation_history"], list)

        version_path = isolated_data_dir / CACHE_VERSION_RELPATH
        assert version_path.exists()
        raw = json.loads(version_path.read_text(encoding="utf-8"))
        assert raw == data

        readback = read_cache_version()
        assert readback == data

    def test_read_cache_version_missing_returns_none(self, isolated_data_dir):
        from tools.lib.metadata_cache import read_cache_version

        version_path = isolated_data_dir / CACHE_VERSION_RELPATH
        assert not version_path.exists()
        assert read_cache_version() is None

    def test_write_cache_version_creates_parent_dirs(self, isolated_data_dir):
        from tools.lib.metadata_cache import write_cache_version

        version_dir = isolated_data_dir / ".life-index" / "cache"
        # Remove dirs if they exist from fixture setup
        if version_dir.exists():
            import shutil

            shutil.rmtree(version_dir)
        assert not version_dir.exists()

        write_cache_version(source_hash="test")
        assert version_dir.exists()
        assert (version_dir / "_version.json").exists()

    def test_sidecar_invalidation_history_appended(self, isolated_data_dir):
        from tools.lib.metadata_cache import write_cache_version, read_cache_version

        write_cache_version(source_hash="v1")
        assert len(read_cache_version()["invalidation_history"]) == 0

        write_cache_version(
            source_hash="v2",
            invalidation_reason="schema_bump",
            from_version="v1.1.0",
        )
        history = read_cache_version()["invalidation_history"]
        assert len(history) == 1
        assert history[0]["reason"] == "schema_bump"
        assert history[0]["from_version"] == "v1.1.0"
        assert "at" in history[0]

    def test_cache_version_not_written_to_cache_dir(self, isolated_data_dir):
        """Sidecar lives under .life-index/cache/, not .cache/."""
        from tools.lib.metadata_cache import write_cache_version

        write_cache_version(source_hash="test")

        cache_dir = isolated_data_dir / ".cache"
        assert not (cache_dir / "_version.json").exists()
        if cache_dir.exists():
            assert "_version.json" not in [f.name for f in cache_dir.iterdir()]

    def test_cache_content_files_not_modified(self, isolated_data_dir):
        """Test that cache version operations do not modify existing cache files."""
        from tools.lib.metadata_cache import write_cache_version, read_cache_version
        from tools.lib.metadata_cache import init_metadata_cache

        # Create some metadata cache first
        conn = init_metadata_cache()
        conn.close()
        cache_db = isolated_data_dir / ".cache" / "metadata_cache.db"
        assert cache_db.exists()
        mtime_before = cache_db.stat().st_mtime
        size_before = cache_db.stat().st_size

        write_cache_version(source_hash="test")
        read_cache_version()

        assert cache_db.stat().st_mtime == mtime_before
        assert cache_db.stat().st_size == size_before


# ============================================================
# CLI subprocess tests (index --cache-dry-run, health --cache-audit)
# ============================================================


def _run_index_dry_run(env):
    return subprocess.run(
        [sys.executable, "-m", "tools", "index", "--cache-dry-run"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        encoding="utf-8",
    )


def _run_health_cache_audit(env):
    return subprocess.run(
        [sys.executable, "-m", "tools", "health", "--cache-audit"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _make_empty_sandbox(tmp_path: Path):
    """Create sandbox data dir with minimal structure, return (data_dir, env)."""
    data_dir = tmp_path / "Life-Index"
    journals_dir = data_dir / "Journals" / "2026" / "05"
    journals_dir.mkdir(parents=True)
    (data_dir / ".index").mkdir(parents=True, exist_ok=True)
    (data_dir / ".cache").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return data_dir, env


class TestIndexCacheDryRun:
    """Test index --cache-dry-run behavior."""

    def test_dry_run_exits_0_on_clean_sandbox(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_index_dry_run(env)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_dry_run_output_is_valid_json(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_index_dry_run(env)
        payload = json.loads(result.stdout)
        assert "success" in payload
        assert payload["success"] is True
        assert "dry_run" in payload
        assert payload["dry_run"] is True
        assert "cache_version" in payload

    def test_dry_run_does_not_create_cache_version_file(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        version_path = data_dir / CACHE_VERSION_RELPATH
        assert not version_path.exists()

        _run_index_dry_run(env)
        assert not version_path.exists(), "cache-dry-run must not create _version.json"

    def test_dry_run_does_not_modify_existing_files(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        # Create a file to monitor
        test_file = data_dir / "Journals" / "2026" / "05" / "test.md"
        test_file.write_text("---\ndate: 2026-05-22\n---\n\nTest.\n", encoding="utf-8")
        mtime_before = test_file.stat().st_mtime

        _run_index_dry_run(env)
        assert test_file.stat().st_mtime == mtime_before

    def test_dry_run_reports_no_existing_version(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_index_dry_run(env)
        payload = json.loads(result.stdout)
        cv = payload["cache_version"]
        assert cv["exists"] is False
        assert cv["would_rebuild"] is True

    def test_dry_run_with_existing_version_reports_stable(self, tmp_path):
        import hashlib

        data_dir, env = _make_empty_sandbox(tmp_path)
        actual_hash = f"sha256:{hashlib.sha256(b'').hexdigest()}"

        version_dir = data_dir / ".life-index" / "cache"
        version_dir.mkdir(parents=True)
        sidecar = {
            "schema_version": "v1.1.2",
            "tool_version": "1.1.1",
            "created_at": "2026-05-22T00:00:00Z",
            "source_hash": actual_hash,
            "invalidation_history": [],
        }
        (version_dir / "_version.json").write_text(json.dumps(sidecar), encoding="utf-8")

        result = _run_index_dry_run(env)
        payload = json.loads(result.stdout)
        cv = payload["cache_version"]
        assert cv["exists"] is True
        assert cv["would_rebuild"] is False


class TestHealthCacheAudit:
    """Test health --cache-audit --json behavior."""

    def test_cache_audit_exits_0(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_health_cache_audit(env)
        assert result.returncode == 0, f"stderr: {result.stderr}"

    def test_cache_audit_output_is_valid_json(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_health_cache_audit(env)
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert "cache_audit" in payload

    def test_cache_audit_reports_missing_version(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_health_cache_audit(env)
        payload = json.loads(result.stdout)
        assert payload["cache_audit"]["version_exists"] is False
        assert payload["cache_audit"]["status"] == "missing"

    def test_cache_audit_reports_version_present(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        version_dir = data_dir / ".life-index" / "cache"
        version_dir.mkdir(parents=True)
        sidecar = {
            "schema_version": "v1.1.2",
            "tool_version": "1.1.1",
            "created_at": "2026-05-22T00:00:00Z",
            "source_hash": "abc",
            "invalidation_history": [],
        }
        (version_dir / "_version.json").write_text(json.dumps(sidecar), encoding="utf-8")

        result = _run_health_cache_audit(env)
        payload = json.loads(result.stdout)
        assert payload["cache_audit"]["version_exists"] is True
        assert payload["cache_audit"]["status"] in ("valid", "stale")

    def test_cache_audit_does_not_create_or_modify_files(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        version_path = data_dir / CACHE_VERSION_RELPATH
        assert not version_path.exists()

        # Create a journal file to monitor
        journal = data_dir / "Journals" / "2026" / "05" / "test.md"
        journal.write_text("---\ndate: 2026-05-22\n---\n\nTest.\n", encoding="utf-8")
        mtime_before = journal.stat().st_mtime

        _run_health_cache_audit(env)
        assert not version_path.exists(), "health --cache-audit must be read-only"
        assert journal.stat().st_mtime == mtime_before

    def test_cache_audit_returns_json_flag(self, tmp_path):
        data_dir, env = _make_empty_sandbox(tmp_path)
        result = _run_health_cache_audit(env)
        payload = json.loads(result.stdout)
        assert payload["cache_audit"]["json"] is True


# ============================================================
# Read-only isolation guard
# ============================================================


def test_no_files_written_outside_life_index_cache_dir(isolated_data_dir):
    """All cache version operations only touch .life-index/cache/ subtree."""
    from tools.lib.metadata_cache import write_cache_version, read_cache_version

    data_dir = isolated_data_dir

    # Snapshot files before
    def all_files(d):
        if not d.exists():
            return set()
        return {str(p.relative_to(d)) for p in d.rglob("*") if p.is_file()}

    before = all_files(data_dir)

    write_cache_version(source_hash="test")
    read_cache_version()

    after = all_files(data_dir)
    new_files = after - before
    for f in new_files:
        assert f.startswith(".life-index\\cache\\") or f.startswith(
            ".life-index/cache/"
        ), f"Unexpected new file: {f}"
