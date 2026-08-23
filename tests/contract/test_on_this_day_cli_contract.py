#!/usr/bin/env python3
"""Contract test: life-index on-this-day CLI subprocess interface.

Verifies:
- `python -m tools on-this-day --date YYYY-MM-DD --years-back N --json`
  returns prior-year same-month/day matches via timeline subprocess.
- Excludes the target year.
- Returns relative slash-only paths.
- No matches is still success (total 0, matches []).
- Invalid --date exits nonzero with structured error E2401.
- Invalid --years-back/--limit exits nonzero with structured error E2402.
- Omitting --date defaults to today.
- Does not write data directory.
- docs/API.md contains M24 contract block.
- README.md contains on-this-day command reference.
- CHANGELOG.md [Unreleased] mentions on-this-day.
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
    title: str,
    body: str,
    abstract: str = "",
) -> Path:
    """Write a journal file under data_dir/Journals/YYYY/MM/."""
    parts = date_str.split("-")
    year, month = parts[0], parts[1]
    month_dir = data_dir / "Journals" / year / month
    month_dir.mkdir(parents=True, exist_ok=True)
    path = month_dir / f"life-index_{date_str}_001.md"
    frontmatter = f"""---
title: "{title}"
date: {date_str}
abstract: "{abstract}"
---

# {title}

{body}
"""
    path.write_text(frontmatter, encoding="utf-8")
    return path


@pytest.fixture
def sandbox(tmp_path: Path):
    """Create sandbox data dir with journals, return (data_dir, env).

    Fixture entries (target 2026-05-19, years_back=3 → since_year=2023):
    - 2025-05-19 "Past C"       — same-day, within range         → MATCH
    - 2024-05-19 "Past B"       — same-day, within range         → MATCH
    - 2023-05-19 "Past A"       — same-day, within range         → MATCH
    - 2019-05-19 "Old Entry"    — same-day, OLDER than range     → EXCLUDED
    - 2024-05-20 "Different Day" — different day                  → EXCLUDED
    - 2026-05-19 "Current Year"  — target year                    → EXCLUDED
    """
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir()

    # Same-day entries within lookback range (years_back=3 → since_year=2023)
    _write_journal(data_dir, "2023-05-19", "Past A", "Body A", "Abstract A")
    _write_journal(data_dir, "2024-05-19", "Past B", "Body B", "Abstract B")
    _write_journal(data_dir, "2025-05-19", "Past C", "Body C2", "Abstract C2")
    # Same-day entry OLDER than lookback range (2019 < 2023)
    _write_journal(data_dir, "2019-05-19", "Old Entry", "Body E", "Abstract E")
    # Different day - should NOT match
    _write_journal(data_dir, "2024-05-20", "Different Day", "Body C", "Abstract C")
    # Current/target year - should be excluded
    _write_journal(data_dir, "2026-05-19", "Current Year", "Body D", "Abstract D")

    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return data_dir, env


class TestOnThisDayCliContract:
    def test_on_this_day_returns_prior_year_same_day_matches(self, sandbox):
        data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--date",
                "2026-05-19",
                "--years-back",
                "3",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["command"] == "on-this-day"
        assert payload["schema_version"] == "m24.on_this_day.v0"

        # Three matches: 2025, 2024, and 2023 only (newest first).
        matches = payload["matches"]
        assert len(matches) == 3, f"Expected 3 matches, got {len(matches)}: {matches}"

        # Newest first
        assert [m["date"] for m in matches] == [
            "2025-05-19",
            "2024-05-19",
            "2023-05-19",
        ]

        # Verify excluded entries are NOT in matches
        assert "2019-05-19" not in [m["date"] for m in matches]
        assert "2024-05-20" not in [m["date"] for m in matches]
        assert "2026-05-19" not in [m["date"] for m in matches]

        # Verify match fields (including year and mood)
        for m in matches:
            assert "date" in m
            assert "year" in m
            assert "years_ago" in m
            assert "title" in m
            assert "abstract" in m
            assert "mood" in m
            assert "path" in m
            assert "source_command" in m

        # Years ago calculation
        assert [m["years_ago"] for m in matches] == [1, 2, 3]

        # source_contracts references timeline
        sc = payload["source_contracts"]
        assert len(sc) >= 1
        assert sc[0]["command"] == "timeline"
        assert "M16" in sc[0]["contract"]

        # Query payload reflects parsed parameters and defaulted bounds.
        assert payload["query"] == {
            "date": "2026-05-19",
            "month_day": "05-19",
            "years_back": 3,
            "since_year": 2023,
            "until_year": 2025,
        }

        # Relative slash paths (no backslashes, no absolute)
        for m in matches:
            assert "\\" not in m["path"], f"Backslash in path: {m['path']}"
            assert not os.path.isabs(m["path"]), f"Absolute path: {m['path']}"

        for p in payload.get("evidence_paths", []):
            assert "\\" not in p, f"Backslash in evidence_path: {p}"
            assert not os.path.isabs(p), f"Absolute evidence_path: {p}"

    def test_on_this_day_no_matches_is_success(self, tmp_path: Path):
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        # No journals at all
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--date",
                "2026-05-19",
                "--years-back",
                "3",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["total"] == 0
        assert payload["matches"] == []

    def test_on_this_day_invalid_date_exits_nonzero_with_structured_error(self, tmp_path: Path):
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--date",
                "not-a-date",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        assert result.returncode != 0, (
            f"Expected nonzero exit, got {result.returncode}\n" f"stdout: {result.stdout}"
        )

        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["code"] == "E2401"

    def test_on_this_day_does_not_write_data_dir(self, sandbox):
        data_dir, env = sandbox
        journals_dir = data_dir / "Journals"

        files_before = set(journals_dir.rglob("*"))

        subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--date",
                "2026-05-19",
                "--years-back",
                "3",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        files_after = set(journals_dir.rglob("*"))
        assert files_before == files_after, "on-this-day wrote files to data dir"

    def test_on_this_day_docs_and_changelog_are_updated(self):
        # docs/API.md must have M24 contract block
        api_md = Path(__file__).resolve().parent.parent.parent / "docs" / "API.md"
        api_content = api_md.read_text(encoding="utf-8")
        assert "## on-this-day" in api_content, "docs/API.md missing '## on-this-day' section"
        assert (
            "<!-- M24-CONTRACT: on-this-day -->" in api_content
        ), "docs/API.md missing M24 contract marker"
        contract_block = api_content.split("<!-- M24-CONTRACT: on-this-day -->", 1)[1].split(
            "<!-- /M24-CONTRACT -->", 1
        )[0]
        assert "`query`" in contract_block, "docs/API.md missing M24 query object"
        assert "`query.date`" in contract_block, "docs/API.md missing M24 query.date field"
        assert (
            "`query.month_day`" in contract_block
        ), "docs/API.md missing M24 query.month_day field"
        assert (
            "`query.years_back`" in contract_block
        ), "docs/API.md missing M24 query.years_back field"
        assert (
            "`target_date`" not in contract_block
        ), "docs/API.md still documents stale top-level target_date"
        m24_section = api_content.split("## on-this-day", 1)[1].split("## entity", 1)[0]
        return_example = m24_section.split("### 返回值", 1)[1].split("### 行为约束", 1)[0]
        assert '"query": {' in return_example, "docs/API.md M24 example missing query object"
        assert (
            '"target_date"' not in return_example
        ), "docs/API.md M24 example still shows stale target_date"

        # README.md must have on-this-day command
        readme = Path(__file__).resolve().parent.parent.parent / "README.md"
        readme_content = readme.read_text(encoding="utf-8")
        assert (
            "life-index on-this-day" in readme_content
        ), "README.md missing 'life-index on-this-day'"

        # CHANGELOG.md must include on-this-day in the current release history
        changelog = Path(__file__).resolve().parent.parent.parent / "CHANGELOG.md"
        changelog_content = changelog.read_text(encoding="utf-8")
        assert (
            "## [1.0.1] - 2026-05-20" in changelog_content
        ), "CHANGELOG.md missing 1.0.1 release entry"
        release_section = changelog_content.split("## [1.0.1] - 2026-05-20", 1)[1].split(
            "## [1.0.0]",
            1,
        )[0]
        assert (
            "on-this-day" in release_section.lower()
        ), "CHANGELOG.md 1.0.1 does not mention on-this-day"

    def test_on_this_day_omit_date_uses_today_with_defaults(self, tmp_path: Path):
        """Omitting --date defaults to today; empty sandbox returns 0 with
        years_back == 10 and matches == []."""
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["query"]["years_back"] == 10
        assert payload["query"]["month_day"] == payload["query"]["date"][5:]
        assert payload["matches"] == []

    def test_on_this_day_years_back_zero_returns_e2402(self, tmp_path: Path):
        """--years-back 0 is invalid and must return E2402."""
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--date",
                "2026-05-19",
                "--years-back",
                "0",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        assert result.returncode != 0, (
            f"Expected nonzero exit, got {result.returncode}\n" f"stdout: {result.stdout}"
        )

        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["code"] == "E2402"

    def test_on_this_day_limit_zero_returns_e2402(self, tmp_path: Path):
        """--limit 0 is invalid and must return E2402."""
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools",
                "on-this-day",
                "--date",
                "2026-05-19",
                "--limit",
                "0",
                "--json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
            encoding="utf-8",
        )

        assert result.returncode != 0, (
            f"Expected nonzero exit, got {result.returncode}\n" f"stdout: {result.stdout}"
        )

        payload = json.loads(result.stdout)
        assert payload["success"] is False
        assert payload["error"]["code"] == "E2402"
