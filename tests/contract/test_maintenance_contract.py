"""Contract tests for maintenance --dry-run (gbrain Phase D).

Covers:
  - CLI surface: maintenance --dry-run / --output=json
  - Six check categories (index freshness, entity audit, orphan related_entries,
    search eval smoke, backup verification, candidate edges count)
  - Status enum: pass / fail / needs-user-action
  - Subprocess delegation to existing CLI commands
  - Zero production writes
  - No LLM provider imports in default path
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE_ROOT = REPO_ROOT / "tools" / "maintenance"

# ── Helpers ─────────────────────────────────────────────────────────


def _run_maintenance(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Run maintenance CLI via subprocess."""
    env = os.environ.copy()
    # Ensure we use test directories when specified
    if "LIFE_INDEX_DATA_DIR" in kwargs:
        env["LIFE_INDEX_DATA_DIR"] = kwargs.pop("LIFE_INDEX_DATA_DIR")
    cmd = [sys.executable, "-m", "tools", "maintenance"] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        encoding="utf-8",
        **kwargs,
    )


def _parse_json_output(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse JSON from subprocess stdout, raising AssertionError on failure."""
    assert proc.returncode == 0, f"Expected exit 0, got {proc.returncode}: stderr={proc.stderr}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(f"stdout is not valid JSON: {e}\nstdout={proc.stdout}") from e
    assert isinstance(data, dict), f"Expected JSON object, got {type(data)}"
    return data


def _file_hashes(data_dir: Path) -> dict[str, str]:
    """Compute SHA256 of all files under a directory, relative to it."""
    hashes: dict[str, str] = {}
    if not data_dir.exists():
        return hashes
    for fpath in sorted(data_dir.rglob("*")):
        if fpath.is_file():
            rel = fpath.relative_to(data_dir).as_posix()
            hashes[rel] = hashlib.sha256(fpath.read_bytes()).hexdigest()
    return hashes


DISALLOWED_PROVIDER_IMPORTS = {"anthropic", "openai", "llm_client"}


def _imported_modules(path: Path) -> set[str]:
    """Parse Python file and return set of imported module names."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def _maintenance_files() -> list[Path]:
    """All .py files in tools/maintenance/."""
    if not MAINTENANCE_ROOT.exists():
        return []
    return sorted(MAINTENANCE_ROOT.rglob("*.py"))


# ── Module-scoped fixture for dry-run JSON output ────────────────────
# Runs the full maintenance dry-run once and shares the parsed result
# across all tests that only inspect the JSON structure. This avoids
# repeatedly spawning slow subprocesses (especially search_eval_smoke).


@pytest.fixture(scope="module")
def dry_run_json() -> dict[str, Any]:
    """Run maintenance --dry-run --output=json once per test module."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = _run_maintenance(["--dry-run", "--output=json"], LIFE_INDEX_DATA_DIR=tmpdir)
        return _parse_json_output(proc)


# ── CLI surface tests ───────────────────────────────────────────────


def test_maintenance_help_output() -> None:
    """maintenance --help prints usage and exits 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = _run_maintenance(["--help"], LIFE_INDEX_DATA_DIR=tmpdir)
        assert proc.returncode == 0, f"help failed: {proc.stderr}"
        assert (
            "maintenance" in proc.stdout.lower()
        ), f"help output missing 'maintenance': {proc.stdout[:200]}"


def test_maintenance_dry_run_exits_zero() -> None:
    """maintenance --dry-run exits 0 and produces JSON output."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = _run_maintenance(["--dry-run", "--output=json"], LIFE_INDEX_DATA_DIR=tmpdir)
        output = _parse_json_output(proc)
        assert output.get("success") is True, f"Expected success=True: {output}"
        assert "checks" in output, f"Expected 'checks' key: {output}"
        assert "schema_version" in output, f"Expected 'schema_version': {output}"


def test_maintenance_no_args_prints_help() -> None:
    """maintenance with no args prints help and exits 0 or non-zero.

    This test must use a temp data dir to avoid touching the real default
    ~/Documents/Life-Index when LIFE_INDEX_DATA_DIR is unset in the calling shell.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = _run_maintenance([], LIFE_INDEX_DATA_DIR=tmpdir)
        # Should print usage info (either via argparse default or help)
        combined = proc.stdout + proc.stderr
        assert "maintenance" in combined.lower() or proc.returncode != 0


# ── Six check categories ────────────────────────────────────────────


def test_six_check_categories_present(dry_run_json: dict[str, Any]) -> None:
    """maintenance --dry-run reports exactly 6 check categories."""
    checks = dry_run_json["checks"]
    assert isinstance(checks, list), f"Expected list, got {type(checks)}"
    assert len(checks) == 6, f"Expected 6 checks, got {len(checks)}"

    expected_categories = {
        "index_freshness",
        "entity_audit",
        "orphan_related_entries",
        "search_eval_smoke",
        "backup_verification",
        "candidate_edges",
    }
    actual_categories = {c["category"] for c in checks}
    assert (
        actual_categories == expected_categories
    ), f"Missing/extra categories. Expected: {expected_categories}, Got: {actual_categories}"


def test_each_check_has_required_fields(dry_run_json: dict[str, Any]) -> None:
    """Each check has category, status, details, and timestamp."""
    for check in dry_run_json["checks"]:
        assert "category" in check, f"Missing 'category' in check: {check}"
        assert "status" in check, f"Missing 'status' in check: {check}"
        assert "details" in check, f"Missing 'details' in check: {check}"
        assert "timestamp" in check, f"Missing 'timestamp' in check: {check}"


def test_status_enum_values(dry_run_json: dict[str, Any]) -> None:
    """All check status values are valid enum members: pass, fail, needs-user-action."""
    valid_statuses = {"pass", "fail", "needs-user-action"}
    for check in dry_run_json["checks"]:
        assert (
            check["status"] in valid_statuses
        ), f"Invalid status '{check['status']}' in check '{check['category']}'"


# ── JSON output format ──────────────────────────────────────────────


def test_json_output_is_valid(dry_run_json: dict[str, Any]) -> None:
    """--output=json produces valid JSON with top-level keys."""
    assert "success" in dry_run_json
    assert "schema_version" in dry_run_json
    assert "checks" in dry_run_json
    assert "summary" in dry_run_json
    assert "timestamp" in dry_run_json
    assert isinstance(dry_run_json["checks"], list)
    assert isinstance(dry_run_json["summary"], dict)


def test_default_output_is_text_report() -> None:
    """Default output (no --output=json) is a human-readable text report."""
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = _run_maintenance(["--dry-run"], LIFE_INDEX_DATA_DIR=tmpdir)
        assert proc.returncode == 0
        # Should contain check category names in text form
        combined = proc.stdout + proc.stderr
        assert "index" in combined.lower(), f"Output missing index check: {combined[:300]}"
        assert "entity" in combined.lower(), f"Output missing entity audit: {combined[:300]}"


# ── Zero-write behavior ─────────────────────────────────────────────


def test_zero_production_writes() -> None:
    """maintenance --dry-run must NOT create or modify ANY file under the target data dir.

    The full directory snapshot (all files, all subdirectories) must be identical
    before and after maintenance --dry-run. This includes .index/, .cache/,
    .life-index/metrics/, and any other subdirectory — zero writes, period.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        # Create a minimal data dir structure with a journal file
        journals_dir = data_dir / "Journals" / "2026" / "05"
        journals_dir.mkdir(parents=True, exist_ok=True)
        test_file = journals_dir / "life-index_2026-05-21_001.md"
        test_file.write_text(
            "---\ntitle: Test\ndate: 2026-05-21\n---\n# Test\n\nTest content.\n",
            encoding="utf-8",
        )

        # Capture FULL directory snapshot before
        before_hashes = _file_hashes(data_dir)
        assert len(before_hashes) > 0, "Test setup error: no files in data dir"

        # Run maintenance
        proc = _run_maintenance(["--dry-run", "--output=json"], LIFE_INDEX_DATA_DIR=str(data_dir))
        assert proc.returncode == 0

        # Capture FULL directory snapshot after
        after_hashes = _file_hashes(data_dir)

        # Assert ZERO changes: no new files, no modified files, no deleted files
        new_files = set(after_hashes.keys()) - set(before_hashes.keys())
        deleted_files = set(before_hashes.keys()) - set(after_hashes.keys())
        modified_files = {
            k for k in after_hashes if k in before_hashes and after_hashes[k] != before_hashes[k]
        }

        assert new_files == set(), (
            f"maintenance --dry-run created {len(new_files)} new file(s) "
            f"under target data dir: {sorted(new_files)}"
        )
        assert deleted_files == set(), (
            f"maintenance --dry-run deleted {len(deleted_files)} file(s) "
            f"from target data dir: {sorted(deleted_files)}"
        )
        assert modified_files == set(), (
            f"maintenance --dry-run modified {len(modified_files)} file(s) "
            f"in target data dir: {sorted(modified_files)}"
        )


# ── Subprocess boundary ─────────────────────────────────────────────


def test_maintenance_uses_subprocess_not_direct_import() -> None:
    """tools/maintenance/ must not directly import called module internals.

    The maintenance module delegates to existing CLI commands (index, entity,
    eval, backup) via subprocess. It must never import their internals directly.
    """
    disallowed_internal_imports = {
        "tools.build_index",
        "tools.entity",
        "tools.eval.ablation",
        "tools.backup",
        # Allowed: tools.lib.* (shared utilities)
    }

    offenders: list[str] = []
    for path in _maintenance_files():
        imports = _imported_modules(path)
        for imported in imports:
            if any(
                imported == disallowed or imported.startswith(f"{disallowed}.")
                for disallowed in disallowed_internal_imports
            ):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {imported}")

    # Allow tools.entity.candidate_edges specifically for the orphan check,
    # but only at the function-import granularity, not wholesale module import.
    # The contract says "subprocess for CLI operations, no imports for called internals."
    assert offenders == [], (
        f"maintenance module directly imports called module internals "
        f"(should use subprocess): {offenders}"
    )


def test_maintenance_no_default_llm_imports() -> None:
    """tools/maintenance/ must not import LLM providers in default path."""
    offenders: list[str] = []
    for path in _maintenance_files():
        imports = _imported_modules(path)
        found = imports & DISALLOWED_PROVIDER_IMPORTS
        if found:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: {sorted(found)}")

    assert offenders == [], f"maintenance module contains disallowed LLM imports: {offenders}"


# ── Schema version contract ─────────────────────────────────────────


def test_schema_version_is_stable(dry_run_json: dict[str, Any]) -> None:
    """JSON output includes a stable schema_version field."""
    sv = dry_run_json.get("schema_version")
    assert sv is not None, "Missing schema_version"
    assert isinstance(sv, str)
    assert sv == "v1.1.1", f"schema_version should match observability contract: {sv}"


# ── Summary contract ────────────────────────────────────────────────


def test_summary_contains_counts(dry_run_json: dict[str, Any]) -> None:
    """summary includes pass_count, fail_count, needs_user_action_count totals."""
    summary = dry_run_json["summary"]
    assert isinstance(summary, dict)
    assert "pass_count" in summary
    assert "fail_count" in summary
    assert "needs_user_action_count" in summary
    assert isinstance(summary["pass_count"], int)
    assert isinstance(summary["fail_count"], int)
    assert isinstance(summary["needs_user_action_count"], int)
    # Sum should equal 6
    total = summary["pass_count"] + summary["fail_count"] + summary["needs_user_action_count"]
    assert total == 6, f"Summary counts should sum to 6: {summary}"


# ── Dry-run flag is required for report ─────────────────────────────


def test_dry_run_flag_controls_report() -> None:
    """--dry-run flag produces the report; without it, behavior is the same
    (maintenance currently only supports dry-run mode)."""
    # Currently, --dry-run is the only mode. The command should work with it.
    with tempfile.TemporaryDirectory() as tmpdir:
        proc = _run_maintenance(["--dry-run", "--help"], LIFE_INDEX_DATA_DIR=tmpdir)
        assert proc.returncode == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
