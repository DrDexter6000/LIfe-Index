#!/usr/bin/env python3
"""Contract test: M16 top-level schema_version presence on public CLI commands.

Verifies that the seven public CLI commands (search, smart-search,
aggregate/analyze, entity, timeline, health, generate-index) emit a
top-level ``schema_version`` string field on success JSON payloads.

generate-index emits a JSON **array**, not a dict; wrapping it in a dict
would be a breaking shape change.  That command is therefore BLOCKED and
tested separately to confirm the array shape is unchanged.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _write_journal(
    data_dir: Path,
    date_str: str,
    title: str = "Test Entry",
    body: str = "Body text.",
    topic: str = "",
    abstract: str = "",
) -> Path:
    """Write a minimal journal under data_dir/Journals/YYYY/MM/."""
    parts = date_str.split("-")
    year, month = parts[0], parts[1]
    month_dir = data_dir / "Journals" / year / month
    month_dir.mkdir(parents=True, exist_ok=True)
    path = month_dir / f"life-index_{date_str}_001.md"
    extra = f"\ntopic: {topic}" if topic else ""
    extra += f'\nabstract: "{abstract}"' if abstract else ""
    content = f'---\ntitle: "{title}"\ndate: {date_str}{extra}\n---\n\n' f"# {title}\n\n{body}\n"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture
def sandbox(tmp_path: Path):
    """Create sandbox data dir with journals, return (data_dir, env)."""
    data_dir = tmp_path / "Life-Index"
    journals_dir = data_dir / "Journals" / "2026" / "03"
    journals_dir.mkdir(parents=True)

    for day in (14, 15, 16):
        path = journals_dir / f"life-index_2026-03-{day:02d}_001.md"
        content = f"---\ndate: 2026-03-{day:02d}\n---\n\n" f"# Test {day}\n\nEntry for day {day}.\n"
        path.write_text(content, encoding="utf-8")

    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return data_dir, env


class TestSearchSchemaVersion:
    """search emits top-level schema_version on success."""

    def test_search_success_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "search",
                "--query",
                "Test",
                "--no-semantic",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "search success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"] == "v1.1.1"


class TestSmartSearchSchemaVersion:
    """smart-search emits top-level schema_version on success."""

    def test_smart_search_success_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "smart-search",
                "--query",
                "Test",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "smart-search success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"].startswith("m16.")


class TestAggregateSchemaVersion:
    """aggregate emits top-level schema_version on success."""

    def test_aggregate_success_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "aggregate",
                "--range",
                "2026-03-14..2026-03-16",
                "--unit",
                "day",
                "--predicate",
                "journal_count",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "aggregate success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"].startswith("m16.")

    def test_analyze_alias_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "analyze",
                "--range",
                "2026-03-14..2026-03-16",
                "--unit",
                "day",
                "--predicate",
                "journal_count",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "analyze alias success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"].startswith("m16.")

    def test_aggregate_error_has_schema_version(self, sandbox):
        """aggregate error payload also carries schema_version."""
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "aggregate",
                "--range",
                "2026-03-14..2026-03-16",
                "--unit",
                "day",
                "--predicate",
                "bogus_predicate",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode != 0
        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert (
            "schema_version" in payload
        ), "aggregate error payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)


class TestEntitySchemaVersion:
    """entity emits top-level schema_version on success."""

    def test_entity_stats_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "entity",
                "--stats",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "entity --stats success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"] == "v1.1.1"

    def test_entity_audit_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "entity",
                "--audit",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "entity --audit success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)


class TestTimelineSchemaVersion:
    """timeline emits top-level schema_version on success."""

    def test_timeline_success_has_schema_version(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "timeline",
                "--range",
                "2026-03",
                "2026-03",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "timeline success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"].startswith("m16.")

    def test_timeline_error_has_schema_version(self, tmp_path: Path):
        """timeline error payload also carries schema_version."""
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "timeline",
                "--range",
                "invalid",
                "invalid",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        # Error payloads should still carry schema_version for consistency
        assert (
            "schema_version" in payload
        ), "timeline error payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)


class TestHealthSchemaVersion:
    """health emits top-level schema_version on success."""

    def test_health_success_has_schema_version(self, tmp_path: Path):
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "health",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "health success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)
        assert payload["schema_version"].startswith("m16.")

    def test_health_data_audit_has_schema_version(self, tmp_path: Path):
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "health",
                "--data-audit",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert (
            "schema_version" in payload
        ), "health --data-audit success payload missing top-level schema_version"
        assert isinstance(payload["schema_version"], str)


class TestGenerateIndexSchemaVersionBlocked:
    """generate-index emits a JSON array; adding top-level schema_version
    requires wrapping which is a breaking shape change.

    This class confirms the array shape is preserved (BLOCKED finding).
    """

    def test_generate_index_outputs_json_array(self, sandbox):
        """generate-index --json outputs a JSON array, not a dict."""
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "generate-index",
                "--month",
                "2026-03",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        assert isinstance(payload, list), (
            "generate-index --json output is not a JSON array. "
            "If this has changed to a dict, the BLOCKED finding should "
            "be revisited."
        )
