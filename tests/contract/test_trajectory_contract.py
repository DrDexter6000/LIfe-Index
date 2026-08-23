"""Contract test: life-index trajectory CLI.

Verifies:
- trajectory --field={weight|sleep|mood|location|project} --range=YYYY-MM..YYYY-MM
  returns typed observation JSON with {type, value, time, evidence_paths[]}.
- Each field has at least 1 happy-path test.
- Zero L1 schema write (fixture file hashes unchanged before/after).
- evidence_paths are fully traceable to source journal files.
- Default path has no LLM calls.
- Does not write to real data directory (uses LIFE_INDEX_DATA_DIR).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_JOURNALS_DIR = REPO_ROOT / "tests" / "fixtures" / "trajectory" / "sample_journals"

SCHEMA_VERSION = "v1.1.1"

FIELDS = ("weight", "sleep", "mood", "location", "project")


def _file_hashes(directory: Path) -> dict[str, str]:
    """Return relative-path -> sha256 hex for all .md files under directory."""
    hashes: dict[str, str] = {}
    for path in sorted(directory.rglob("*.md")):
        rel = path.relative_to(directory).as_posix()
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _run_trajectory(field: str, range_str: str, data_dir: Path) -> dict:
    """Invoke trajectory CLI via subprocess and return parsed JSON."""
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "trajectory",
            "--field",
            field,
            "--range",
            range_str,
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        encoding="utf-8",
    )
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError(
            f"trajectory output not valid JSON (exit={proc.returncode}): {exc}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    if not isinstance(payload, dict):
        raise AssertionError("trajectory output JSON was not an object")
    return payload


@pytest.fixture
def sandbox(tmp_path: Path):
    """Copy fixture journals into a temp data dir and return (data_dir, before_hashes)."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir()
    # Copy the entire fixture tree (including .index) so that L2 search
    # subprocesses find a warm index and do not trigger incremental builds
    # that leave stale locks on Windows.
    if FIXTURE_JOURNALS_DIR.exists():
        import shutil

        shutil.copytree(FIXTURE_JOURNALS_DIR, data_dir, dirs_exist_ok=True)
    journals_dst = data_dir / "Journals"
    before_hashes = _file_hashes(journals_dst)
    return data_dir, before_hashes


class TestTrajectoryContract:
    def _assert_observation_schema(self, obs: dict, expected_field: str) -> None:
        assert "type" in obs, f"Observation missing 'type': {obs}"
        assert obs["type"] == expected_field, f"Expected type={expected_field}, got {obs['type']}"
        assert "value" in obs, f"Observation missing 'value': {obs}"
        assert "time" in obs, f"Observation missing 'time': {obs}"
        assert "evidence_paths" in obs, f"Observation missing 'evidence_paths': {obs}"
        assert isinstance(obs["evidence_paths"], list), "evidence_paths must be a list"
        assert len(obs["evidence_paths"]) > 0, "evidence_paths must not be empty"
        for ep in obs["evidence_paths"]:
            assert isinstance(ep, str), "Each evidence_path must be a string"

    def _assert_zero_l1_write(self, data_dir: Path, before_hashes: dict) -> None:
        after_hashes = _file_hashes(data_dir / "Journals")
        assert after_hashes == before_hashes, (
            f"L1 write detected! Journals modified.\n"
            f"Before: {before_hashes}\nAfter: {after_hashes}"
        )

    def _assert_evidence_traceable(self, obs: dict, data_dir: Path) -> None:
        for ep in obs["evidence_paths"]:
            full = data_dir / ep
            assert (
                full.exists()
            ), f"evidence_path not traceable: {ep} does not exist under {data_dir}"

    # ------------------------------------------------------------------
    # Weight
    # ------------------------------------------------------------------
    def test_trajectory_weight_returns_observations(self, sandbox):
        data_dir, before_hashes = sandbox
        payload = _run_trajectory("weight", "2025-01..2025-12", data_dir)

        assert payload["success"] is True
        assert payload.get("schema_version") == SCHEMA_VERSION
        observations = payload["observations"]
        assert (
            len(observations) >= 1
        ), f"Expected at least 1 weight observation, got {len(observations)}"

        for obs in observations:
            self._assert_observation_schema(obs, "weight")
            self._assert_evidence_traceable(obs, data_dir)
            assert isinstance(obs["value"], (int, float)), "weight value must be numeric"

        # Specific known values from fixtures
        values = [obs["value"] for obs in observations]
        assert 72.5 in values, f"Expected 72.5 in weight values, got {values}"
        assert 70.5 in values, f"Expected 70.5 in weight values, got {values}"

        self._assert_zero_l1_write(data_dir, before_hashes)

    # ------------------------------------------------------------------
    # Sleep
    # ------------------------------------------------------------------
    def test_trajectory_sleep_returns_observations(self, sandbox):
        data_dir, before_hashes = sandbox
        payload = _run_trajectory("sleep", "2025-01..2025-12", data_dir)

        assert payload["success"] is True
        observations = payload["observations"]
        assert (
            len(observations) >= 1
        ), f"Expected at least 1 sleep observation, got {len(observations)}"

        for obs in observations:
            self._assert_observation_schema(obs, "sleep")
            self._assert_evidence_traceable(obs, data_dir)
            assert isinstance(obs["value"], (int, float)), "sleep value must be numeric"

        values = [obs["value"] for obs in observations]
        assert 7.5 in values, f"Expected 7.5 in sleep values, got {values}"
        assert 4.0 in values, f"Expected 4.0 in sleep values, got {values}"

        self._assert_zero_l1_write(data_dir, before_hashes)

    # ------------------------------------------------------------------
    # Mood
    # ------------------------------------------------------------------
    def test_trajectory_mood_returns_observations(self, sandbox):
        data_dir, before_hashes = sandbox
        payload = _run_trajectory("mood", "2025-01..2025-12", data_dir)

        assert payload["success"] is True
        observations = payload["observations"]
        assert (
            len(observations) >= 1
        ), f"Expected at least 1 mood observation, got {len(observations)}"

        for obs in observations:
            self._assert_observation_schema(obs, "mood")
            self._assert_evidence_traceable(obs, data_dir)
            assert isinstance(obs["value"], str), "mood value must be a string"

        values = [obs["value"] for obs in observations]
        assert "happy" in values, f"Expected 'happy' in mood values, got {values}"
        assert "stressed" in values, f"Expected 'stressed' in mood values, got {values}"

        self._assert_zero_l1_write(data_dir, before_hashes)

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------
    def test_trajectory_location_returns_observations(self, sandbox):
        data_dir, before_hashes = sandbox
        payload = _run_trajectory("location", "2025-01..2025-12", data_dir)

        assert payload["success"] is True
        observations = payload["observations"]
        assert (
            len(observations) >= 1
        ), f"Expected at least 1 location observation, got {len(observations)}"

        for obs in observations:
            self._assert_observation_schema(obs, "location")
            self._assert_evidence_traceable(obs, data_dir)
            assert isinstance(obs["value"], str), "location value must be a string"

        values = [obs["value"] for obs in observations]
        assert "Beijing" in values, f"Expected 'Beijing' in location values, got {values}"
        assert "Shanghai" in values, f"Expected 'Shanghai' in location values, got {values}"

        self._assert_zero_l1_write(data_dir, before_hashes)

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------
    def test_trajectory_project_returns_observations(self, sandbox):
        data_dir, before_hashes = sandbox
        payload = _run_trajectory("project", "2025-01..2025-12", data_dir)

        assert payload["success"] is True
        observations = payload["observations"]
        assert (
            len(observations) >= 1
        ), f"Expected at least 1 project observation, got {len(observations)}"

        for obs in observations:
            self._assert_observation_schema(obs, "project")
            self._assert_evidence_traceable(obs, data_dir)
            assert isinstance(obs["value"], str), "project value must be a string"

        values = [obs["value"] for obs in observations]
        assert "Life-Index" in values, f"Expected 'Life-Index' in project values, got {values}"
        assert "SideProject" in values, f"Expected 'SideProject' in project values, got {values}"

        self._assert_zero_l1_write(data_dir, before_hashes)

    # ------------------------------------------------------------------
    # Range filtering
    # ------------------------------------------------------------------
    def test_trajectory_range_filtering_excludes_out_of_range(self, sandbox):
        data_dir, before_hashes = sandbox
        # Only Jan-Mar
        payload = _run_trajectory("weight", "2025-01..2025-03", data_dir)
        assert payload["success"] is True
        observations = payload["observations"]
        for obs in observations:
            assert obs["time"] <= "2025-03-31", f"Observation {obs} outside range 2025-01..2025-03"

        self._assert_zero_l1_write(data_dir, before_hashes)

    # ------------------------------------------------------------------
    # Default / error cases
    # ------------------------------------------------------------------
    def test_trajectory_invalid_field_returns_error(self, sandbox):
        data_dir, before_hashes = sandbox
        payload = _run_trajectory("invalid_field", "2025-01..2025-03", data_dir)
        assert payload["success"] is False
        assert "error" in payload
        self._assert_zero_l1_write(data_dir, before_hashes)

    def test_trajectory_empty_range_returns_empty_observations(self, tmp_path: Path):
        data_dir = tmp_path / "Life-Index"
        data_dir.mkdir()
        (data_dir / "Journals").mkdir()
        payload = _run_trajectory("weight", "2024-01..2024-03", data_dir)
        assert payload["success"] is True
        assert payload["observations"] == []

    # ------------------------------------------------------------------
    # Layer boundary regression
    # ------------------------------------------------------------------
    def test_trajectory_no_default_llm_imports(self):
        """Static invariant: tools/trajectory/ must not import LLM providers."""
        import ast

        trajectory_dir = REPO_ROOT / "tools" / "trajectory"
        disallowed = {"anthropic", "openai"}
        offenders: list[str] = []
        for py_file in sorted(trajectory_dir.rglob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = {node.module.split(".")[0]}
                else:
                    continue
                found = names & disallowed
                if found:
                    rel = py_file.relative_to(REPO_ROOT).as_posix()
                    offenders.append(f"{rel}: {sorted(found)}")
        assert offenders == [], f"tools/trajectory/ contains disallowed LLM imports: {offenders}"

    def test_trajectory_has_no_direct_l1_access(self):
        """Fail if tools/trajectory imports or calls forbidden direct L1 patterns."""
        import ast

        trajectory_dir = REPO_ROOT / "tools" / "trajectory"
        forbidden_modules = {
            "tools.lib.paths",
            "tools.lib.frontmatter",
        }
        forbidden_calls = {
            "get_journals_dir",
            "get_user_data_dir",
            "parse_journal_file",
            "glob",
            "rglob",
            "iterdir",
            "read_text",
        }

        offenders: list[str] = []
        for py_file in sorted(trajectory_dir.rglob("*.py")):
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for forbidden in forbidden_modules:
                        if module == forbidden or module.startswith(forbidden + "."):
                            rel = py_file.relative_to(REPO_ROOT).as_posix()
                            offenders.append(f"{rel}: imports from {module}")
                            break
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr in forbidden_calls:
                            rel = py_file.relative_to(REPO_ROOT).as_posix()
                            offenders.append(f"{rel}: calls .{node.func.attr}()")
                    elif isinstance(node.func, ast.Name):
                        if node.func.id in forbidden_calls:
                            rel = py_file.relative_to(REPO_ROOT).as_posix()
                            offenders.append(f"{rel}: calls {node.func.id}()")

        assert offenders == [], f"Direct L1 access detected in trajectory: {offenders}"
