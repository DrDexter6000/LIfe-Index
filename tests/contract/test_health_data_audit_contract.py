#!/usr/bin/env python3
"""Contract test: life-index health --data-audit summary interface.

`health --data-audit` is a compatibility summary over the Data Doctor SSOT:
`life-index maintenance audit --json`. It must stay read-only and point agents
to the full maintenance audit/plan flow instead of running a second detector
stack.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Create sandbox data dir with standard journals, return (data_dir, env)."""
    data_dir = tmp_path / "Life-Index"
    journals_dir = data_dir / "Journals" / "2026" / "03"
    journals_dir.mkdir(parents=True)

    for day in (14, 15, 16):
        p = journals_dir / f"life-index_2026-03-{day:02d}_001.md"
        p.write_text(
            f"---\ndate: 2026-03-{day:02d}\ntopic: testing\n---\n\n# Test {day}\n\nEntry.\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return data_dir, env


def _run_data_audit(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tools", "health", "--data-audit"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


class TestHealthDataAuditContract:
    def test_data_audit_exits_0_and_returns_data_doctor_summary(
        self, sandbox: tuple[Path, dict[str, str]]
    ) -> None:
        _data_dir, env = sandbox
        result = _run_data_audit(env)

        assert result.returncode == 0, f"stderr: {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert payload["schema_version"] == "m16.health.v0"

        data = payload["data"]
        assert data["source"] == "maintenance audit"
        assert data["status"] in {"ok", "issues_found"}
        assert isinstance(data["issue_count"], int)
        assert isinstance(data["summary"], dict)
        assert data["issue_count"] == data["summary"]["total_issues"]
        assert data["next_command"] == "life-index maintenance audit --json"
        assert data["plan_command_template"] == (
            "life-index maintenance plan --issue-id <issue-id> --json"
        )
        assert "detectors" in data
        assert "issues_preview" in data

    def test_data_audit_uses_data_doctor_issue_types(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "Life-Index"
        month_dir = data_dir / "Journals" / "2026" / "03"
        month_dir.mkdir(parents=True)

        (month_dir / "life-index_2026-03-14_001.md").write_text(
            "---\ndate: 2026-03-14\ntopic: testing\n---\n",
            encoding="utf-8",
        )
        (month_dir / "life-index_2026-03-14_001_20260418_120000_000000.md").write_text(
            "---\ndate: 2026-03-14\ntopic: testing\n---\n",
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

        result = _run_data_audit(env)
        assert result.returncode == 0
        payload = json.loads(result.stdout)
        preview_types = {issue["type"] for issue in payload["data"]["issues_preview"]}
        assert "loose_timestamped_journal_copy" in preview_types

    def test_data_audit_does_not_emit_legacy_detector_fields(
        self, sandbox: tuple[Path, dict[str, str]]
    ) -> None:
        _data_dir, env = sandbox
        result = _run_data_audit(env)

        assert result.returncode == 0
        payload = json.loads(result.stdout)
        data = payload["data"]
        assert "file_count" not in data
        assert "anomalies" not in data
        assert "distribution" not in data

    def test_data_audit_is_read_only(self, sandbox: tuple[Path, dict[str, str]]) -> None:
        data_dir, env = sandbox
        before = {
            path.relative_to(data_dir).as_posix(): path.read_bytes()
            for path in data_dir.rglob("*")
            if path.is_file()
        }

        result = _run_data_audit(env)
        assert result.returncode == 0

        after = {
            path.relative_to(data_dir).as_posix(): path.read_bytes()
            for path in data_dir.rglob("*")
            if path.is_file()
        }
        assert after == before, "health --data-audit modified files"
