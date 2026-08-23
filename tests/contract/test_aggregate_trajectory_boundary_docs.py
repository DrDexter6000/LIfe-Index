"""Contract tests for the aggregate/trajectory jurisdiction boundary."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_MD = REPO_ROOT / "docs" / "API.md"
SKILL_MD = REPO_ROOT / "SKILL.md"


def _run_tools(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools", *args],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )


def test_public_api_documents_aggregate_trajectory_ssot() -> None:
    api = API_MD.read_text(encoding="utf-8")

    assert "`aggregate` owns deterministic counts, buckets, and claim" in api
    assert "It does **not** own typed" in api
    assert "`trajectory` owns deterministic typed observation series" in api
    assert "It does **not** own counts, buckets, denominators" in api


def test_skill_routes_counts_and_observation_series_to_separate_tools() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    assert "计数 vs 观测序列选择" in skill
    assert "`aggregate` owns counts, buckets, and claim envelopes" in skill
    assert "`trajectory` owns typed\nobservation series" in skill
    assert "Do not use `trajectory` as a hidden counter" in skill


def test_top_level_help_describes_aggregate_boundary() -> None:
    result = _run_tools("--help")

    assert result.returncode == 0
    assert "aggregate  Deterministic counts, buckets, and claim envelopes" in result.stdout
    assert "aggregate/trend computation" not in result.stdout


def test_aggregate_help_describes_claim_boundary() -> None:
    result = _run_tools("aggregate", "--help")

    assert result.returncode == 0
    assert "Deterministic counts, buckets, and claim envelopes" in result.stdout
    assert "aggregate/trend" not in result.stdout
