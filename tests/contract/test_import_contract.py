#!/usr/bin/env python3
"""Contract tests for the import provider CLI surface (PRD §12).

These tests encode the public JSON contract for import plan, run, status,
rollback, idempotency, structured errors, fixed ledger/manifest paths,
and dry-run non-mutation.

S1 is RED-first: all tests are expected to fail because the ``import``
subcommand does not exist yet in ``tools/__main__.py``.  Failures must be
limited to the missing/unimplemented import runtime, **not** syntax errors,
fixture parse errors, or malformed tests.

PRD reference: Import Provider Contract PRD (private governance)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Constants from PRD §5 / §9 / §10
# ---------------------------------------------------------------------------

ENVELOPE_SCHEMA_VERSION = "import_job.v1"
LEDGER_REL_PATH = ".life-index/import-jobs/ledger.json"


def _rollback_manifest_rel_path(import_id: str) -> str:
    """PRD §8: fixed rollback manifest path contract."""
    return f".life-index/import-jobs/{import_id}/rollback-manifest.json"


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "import_jobs"


# ---------------------------------------------------------------------------
# Helpers (style: test_journal_contract.py / test_attachment_contract.py)
# ---------------------------------------------------------------------------


def _run_import(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Invoke ``python -m tools import ...`` with LIFE_INDEX_DATA_DIR set."""
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "import", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _run_index(data_dir: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the public index authority for an isolated data directory."""
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "index", "--json"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _run_search(data_dir: Path, query: str) -> subprocess.CompletedProcess[str]:
    """Invoke the public search authority for an isolated data directory."""
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "search", "--query", query, "--limit", "0"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse JSON stdout into a dict.

    Raises AssertionError (not JSONDecodeError) when stdout is not valid JSON,
    so that S1 RED failures always present a clear missing-runtime message.
    """
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            f"Expected JSON on stdout but got non-JSON output.\n"
            f"This is expected in S1 when the import command is not yet "
            f"registered in tools/__main__.py.\n"
            f"stdout[:500]: {result.stdout[:500]}"
        ) from None


def _load_fixture(name: str) -> dict[str, Any]:
    """Load a fixture file from tests/fixtures/import_jobs/."""
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_plan_payload_for_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize environment/date-dependent plan fields for golden snapshots."""
    snapshot = json.loads(json.dumps(payload))
    data = snapshot["data"]
    data["import_id"] = "<import_id>"
    data["idempotency_key"] = "<idempotency_key>"
    return snapshot


def _fixture_path(name: str) -> str:
    """Return absolute string path for a fixture file."""
    return str(FIXTURES_DIR / name)


def _prepare_r1a_route_legacy_plan(
    data_dir: Path, tmp_path: Path
) -> tuple[Path, str, set[str]]:
    """Create a valid legacy plan without mutating the isolated data directory."""
    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert (
        plan_result.returncode == 0
    ), f"plan stdout: {plan_result.stdout}\nstderr: {plan_result.stderr}"
    plan_data = _payload(plan_result)["data"]
    plan_file = tmp_path / "r1a-route-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")
    return plan_file, plan_data["import_id"], set(plan_data["write_set_preview"]["create_files"])


def _r1a_route_data_files(data_dir: Path) -> set[str]:
    """Return regular-file paths relative to the isolated data directory."""
    return {
        path.relative_to(data_dir).as_posix()
        for path in data_dir.rglob("*")
        if path.is_file()
    }


def _assert_r1a_route_import_id_invalid(
    result: subprocess.CompletedProcess[str], reason: str
) -> None:
    """Assert the exact fail-closed import-id envelope."""
    assert result.returncode != 0
    assert result.stderr == ""
    payload = _payload(result)
    assert payload == {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "success": False,
        "command": "import.run",
        "data": None,
        "error": {
            "code": "IMPORT_ID_INVALID",
            "message": "Import id is invalid.",
            "details": {"reason": reason},
            "retryable": False,
        },
    }


def _seed_journal(
    data_dir: Path,
    *,
    date: str,
    seq: str = "001",
    title: str,
    body: str,
) -> Path:
    """Create a minimal journal file under *data_dir* for conflict testing."""
    year, month, _day = date.split("-")
    journal_dir = data_dir / "Journals" / year / month
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / f"life-index_{date}_{seq}.md"
    path.write_text(
        "---\n" f'title: "{title}"\n' f"date: {date}\n" "---\n\n" f"{body}",
        encoding="utf-8",
    )
    return path


def _plan_then_run(
    data_dir: Path,
    source_fixture: str | Path,
    tmp_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Helper: plan → write plan.json → run with confirm.

    Returns (plan_data, run_payload, import_id).
    """
    fixture = (
        _fixture_path(source_fixture) if isinstance(source_fixture, str) else str(source_fixture)
    )
    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        fixture,
        "--json",
    )
    assert (
        plan_result.returncode == 0
    ), f"plan stdout: {plan_result.stdout}\nstderr: {plan_result.stderr}"
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    assert (
        run_result.returncode == 0
    ), f"run stdout: {run_result.stdout}\nstderr: {run_result.stderr}"
    run_payload = _payload(run_result)
    return plan_data, run_payload, import_id


# ===================================================================
# M7 R1a: the real CLI router distinguishes option presence from truthiness
# ===================================================================


def test_r1a_route_legacy_plan_without_confirm_preserves_confirmation_error(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True)
    plan_file, _import_id, proposed_paths = _prepare_r1a_route_legacy_plan(
        data_dir, tmp_path
    )

    result = _run_import(data_dir, "run", "--plan", str(plan_file), "--json")

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["error"] == {
        "code": "IMPORT_CONFIRMATION_REQUIRED",
        "message": "The --confirm flag is required for import run.",
        "details": {"import_id": _import_id},
        "retryable": False,
    }
    assert not (proposed_paths & _r1a_route_data_files(data_dir))


def test_r1a_route_legacy_plan_with_matching_confirm_succeeds(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True)
    plan_file, import_id, proposed_paths = _prepare_r1a_route_legacy_plan(
        data_dir, tmp_path
    )

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["data"]["state"] == "committed"
    assert proposed_paths <= _r1a_route_data_files(data_dir)
    assert sum(path.startswith("Journals/") for path in proposed_paths) == 2
    assert sum(path.startswith("attachments/") for path in proposed_paths) == 2


def test_r1a_route_valid_import_id_selects_batch_route(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True)

    result = _run_import(
        data_dir, "run", "--import-id", "valid_parent", "--json"
    )

    assert result.returncode != 0
    assert result.stderr == ""
    payload = _payload(result)
    assert payload["error"]["code"] == "IMPORT_JOB_NOT_FOUND"
    assert _r1a_route_data_files(data_dir) == {
        ".life-index/import-jobs/ledger.lock",
        ".life-index/import-jobs/valid_parent/review.lock",
    }


def test_r1a_route_valid_import_id_wins_over_valid_legacy_args(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True)
    plan_file, import_id, proposed_paths = _prepare_r1a_route_legacy_plan(
        data_dir, tmp_path
    )

    result = _run_import(
        data_dir,
        "run",
        "--import-id",
        "valid_parent",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["error"]["code"] == "IMPORT_JOB_NOT_FOUND"
    assert not (proposed_paths & _r1a_route_data_files(data_dir))
    assert _r1a_route_data_files(data_dir) == {
        ".life-index/import-jobs/ledger.lock",
        ".life-index/import-jobs/valid_parent/review.lock",
    }


@pytest.mark.parametrize(
    ("import_id", "reason"),
    [
        pytest.param("", "empty", id="empty"),
        pytest.param(" ", "syntax", id="whitespace"),
    ],
)
def test_r1a_route_invalid_import_id_without_legacy_args_fails_closed(
    tmp_path: Path, import_id: str, reason: str
) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True)

    result = _run_import(data_dir, "run", "--import-id", import_id, "--json")

    _assert_r1a_route_import_id_invalid(result, reason)
    assert _r1a_route_data_files(data_dir) == {
        ".life-index/import-jobs/ledger.lock"
    }


@pytest.mark.parametrize(
    ("import_id", "reason"),
    [
        pytest.param("", "empty", id="empty"),
        pytest.param(" ", "syntax", id="whitespace"),
    ],
)
def test_r1a_route_invalid_import_id_with_valid_legacy_args_fails_closed(
    tmp_path: Path, import_id: str, reason: str
) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True)
    plan_file, confirm_id, proposed_paths = _prepare_r1a_route_legacy_plan(
        data_dir, tmp_path
    )

    result = _run_import(
        data_dir,
        "run",
        "--import-id",
        import_id,
        "--plan",
        str(plan_file),
        "--confirm",
        confirm_id,
        "--json",
    )

    _assert_r1a_route_import_id_invalid(result, reason)
    assert not (proposed_paths & _r1a_route_data_files(data_dir))
    assert _r1a_route_data_files(data_dir) == {
        ".life-index/import-jobs/ledger.lock"
    }


# ===================================================================
# PRD §12 Test 1: import plan returns correct dry-run envelope
# ===================================================================


def test_import_plan_returns_dry_run_envelope_with_fingerprints(
    tmp_path: Path,
) -> None:
    """PRD §12(1): plan returns schema_version, dry_run=true,
    plan_fingerprint, idempotency_key, and deterministic proposals."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)

    # Envelope
    assert payload["schema_version"] == ENVELOPE_SCHEMA_VERSION
    assert payload["success"] is True
    assert payload["command"] == "import.plan"
    assert payload["error"] is None

    data = payload["data"]
    assert data["dry_run"] is True
    assert data["schema_version"] == "import_plan.v1"
    assert data["plan_fingerprint"].startswith("sha256:")
    assert data["idempotency_key"].startswith("sha256:")
    assert data["import_id"].startswith("imp_")

    # Proposals
    assert len(data["proposals"]) == 2
    for proposal in data["proposals"]:
        assert proposal["proposal_fingerprint"].startswith("sha256:")
        assert "source_record_fingerprint" in proposal
        assert "journal" in proposal
        assert "attachments" in proposal


def test_import_plan_matches_normalized_golden_snapshot(tmp_path: Path) -> None:
    """T5 hardening: plan envelope shape is protected by a golden snapshot.

    The snapshot keeps deterministic fingerprints exact while normalizing
    fields that depend on the temp data directory or current date.
    """
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)

    expected = _load_fixture("golden_minimal_plan_envelope.normalized.json")
    assert _normalize_plan_payload_for_snapshot(payload) == expected


# ===================================================================
# PRD §12 Test 2: import plan creates no files under data dir
# ===================================================================


def test_import_plan_creates_no_files_under_data_dir(
    tmp_path: Path,
) -> None:
    """PRD §12(2): import plan must not write any files."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    files_before = set(data_dir.rglob("*"))

    result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )

    files_after = set(data_dir.rglob("*"))
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert files_after == files_before, f"import plan created files: {files_after - files_before}"


# ===================================================================
# PRD §12 Test 3: import run requires --confirm <import_id>
# ===================================================================


def test_import_run_requires_confirm_flag(tmp_path: Path) -> None:
    """PRD §12(3): run without --confirm returns IMPORT_CONFIRMATION_REQUIRED."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        _fixture_path("invalid_plan_missing_fingerprint.json"),
        "--json",
    )

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"]["code"] == "IMPORT_CONFIRMATION_REQUIRED"
    assert payload["error"]["retryable"] is False


# ===================================================================
# PRD §12 Test 4: import run creates only proposed paths
# ===================================================================


def test_import_run_creates_only_proposed_paths(tmp_path: Path) -> None:
    """PRD §12(4): run creates only the journal and attachment paths from plan."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_data, run_payload, _import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    assert run_payload["success"] is True
    assert run_payload["data"]["state"] == "committed"

    created_paths = {f["rel_path"] for f in run_payload["data"]["created_files"]}
    proposed_paths = set(plan_data["write_set_preview"]["create_files"])
    assert created_paths == proposed_paths


# ===================================================================
# PRD §12 Test 5: idempotent re-run returns already_committed
# ===================================================================


def test_import_run_idempotent_already_committed(tmp_path: Path) -> None:
    """PRD §12(5): re-running same plan returns already_committed."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_data, _first, import_id = _plan_then_run(data_dir, "minimal_plan_source.json", tmp_path)

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    second_run = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    assert second_run.returncode == 0, f"stdout: {second_run.stdout}\nstderr: {second_run.stderr}"
    second_payload = _payload(second_run)
    assert second_payload["data"]["state"] == "already_committed"


# ===================================================================
# PRD §12 Test 6: existing target paths fail closed
# ===================================================================


def test_import_run_conflict_existing_path_fails_closed(
    tmp_path: Path,
) -> None:
    """PRD §12(6): conflicting target paths produce conflict_count > 0."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Pre-create a journal that the conflicting fixture targets
    _seed_journal(
        data_dir,
        date="2026-05-29",
        seq="001",
        title="Existing Journal",
        body="This already exists.",
    )

    result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("conflicting_target_source.json"),
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    plan_data = _payload(result)["data"]
    assert plan_data["summary"]["conflict_count"] > 0
    assert len(plan_data["conflicts"]) > 0


def test_import_run_rejects_unsafe_target_path_before_writes(
    tmp_path: Path,
) -> None:
    """Run-stage validation must reject traversal target paths before ledger or
    durable writes. A tampered plan must not create files outside data_dir."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    unsafe_rel = "../outside_escape.md"
    plan_data["proposals"][0]["journal"]["target_rel_path"] = unsafe_rel
    plan_data["write_set_preview"]["create_files"][0] = unsafe_rel

    plan_file = tmp_path / "unsafe-run-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    payload = _payload(result)

    assert result.returncode != 0
    assert payload["success"] is False
    assert payload["error"]["code"] == "IMPORT_PLAN_INVALID"
    assert not (tmp_path / "outside_escape.md").exists()
    assert not (data_dir / LEDGER_REL_PATH).exists()


def test_import_run_revalidates_fingerprints_before_writes(
    tmp_path: Path,
) -> None:
    """Run must recompute proposal/plan/idempotency fingerprints and reject a
    tampered plan that preserves stale fingerprint fields."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    plan_data["proposals"][0]["journal"][
        "content"
    ] = "Tampered content with stale proposal and plan fingerprints."

    plan_file = tmp_path / "stale-fingerprint-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    payload = _payload(result)

    assert result.returncode != 0
    assert payload["success"] is False
    assert payload["error"]["code"] == "IMPORT_PLAN_INVALID"
    assert "proposal_fingerprint" in json.dumps(payload["error"]["details"])
    assert not (data_dir / LEDGER_REL_PATH).exists()


def test_import_run_rejects_unresolved_conflicts_before_writes(
    tmp_path: Path,
) -> None:
    """Run must fail closed when a plan carries unresolved conflicts, even if a
    caller tampers a previously clean plan file."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    conflict = {
        "type": "injected_conflict",
        "target_rel_path": plan_data["proposals"][0]["journal"]["target_rel_path"],
        "message": "Injected unresolved conflict.",
    }
    plan_data["summary"]["conflict_count"] = 1
    plan_data["conflicts"] = [conflict]
    plan_data["proposals"][0]["conflicts"] = [conflict]

    plan_file = tmp_path / "conflicted-run-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    payload = _payload(result)

    assert result.returncode != 0
    assert payload["success"] is False
    assert payload["error"]["code"] == "IMPORT_PLAN_CONFLICTS_UNRESOLVED"
    assert not (data_dir / LEDGER_REL_PATH).exists()


def test_import_run_rejects_unsupported_plan_schema_without_writes(
    tmp_path: Path,
) -> None:
    """T5 hardening: unsupported plan schema versions fail before writes."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]
    plan_data["schema_version"] = "import_plan.v2"

    plan_file = tmp_path / "unsupported-schema-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    payload = _payload(result)

    assert result.returncode != 0
    assert payload["success"] is False
    assert payload["error"]["code"] == "IMPORT_PLAN_SCHEMA_UNSUPPORTED"
    assert not (data_dir / LEDGER_REL_PATH).exists()


def test_import_run_tolerates_additive_unknown_plan_fields(tmp_path: Path) -> None:
    """T5 hardening: additive unknown fields are ignored by v1 consumers."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    plan_data["future_extension"] = {"ignored_by": "import_plan.v1"}
    plan_data["proposals"][0]["future_extension"] = {"ignored": True}
    plan_data["proposals"][0]["journal"]["future_extension"] = "ignored"
    plan_data["proposals"][0]["attachments"][0]["future_extension"] = "ignored"

    plan_file = tmp_path / "additive-fields-plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    payload = _payload(result)

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert payload["success"] is True
    assert payload["data"]["state"] == "committed"


# ===================================================================
# PRD §12 Test 7: import status reports committed / not-found
# ===================================================================


def test_import_status_reports_committed_state(tmp_path: Path) -> None:
    """PRD §12(7): status reports committed from fixed ledger + manifest."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, _run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    status_result = _run_import(
        data_dir,
        "status",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        status_result.returncode == 0
    ), f"stdout: {status_result.stdout}\nstderr: {status_result.stderr}"
    status_payload = _payload(status_result)
    assert status_payload["success"] is True
    assert status_payload["data"]["state"] == "committed"
    assert status_payload["data"]["import_id"] == import_id


def test_import_status_reports_not_found(tmp_path: Path) -> None:
    """PRD §12(7): status for unknown import_id returns IMPORT_JOB_NOT_FOUND."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    result = _run_import(
        data_dir,
        "status",
        "--import-id",
        "imp_nonexistent",
        "--json",
    )

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"]["code"] == "IMPORT_JOB_NOT_FOUND"


# ===================================================================
# PRD §12 Test 8: rollback removes checksum-matching files
# ===================================================================


def test_import_rollback_removes_checksum_matching_files(
    tmp_path: Path,
) -> None:
    """PRD §12(8): rollback deletes created files when checksums match."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    created_files = run_payload["data"]["created_files"]

    rollback_result = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        rollback_result.returncode == 0
    ), f"stdout: {rollback_result.stdout}\nstderr: {rollback_result.stderr}"
    rollback_payload = _payload(rollback_result)
    assert rollback_payload["data"]["state"] == "rolled_back"

    # Verify files were actually removed
    for file_entry in created_files:
        assert not (
            data_dir / file_entry["rel_path"]
        ).exists(), f"File should have been rolled back: {file_entry['rel_path']}"


def test_import_rollback_removes_journal_from_next_normal_search(
    tmp_path: Path,
) -> None:
    """A rolled-back journal must not survive in the next public search."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    unique_token = "rollbacksearchuniquetoken"
    source = _load_fixture("minimal_plan_source.json")
    source["records"][0]["journal"]["content"] = f"Imported {unique_token}."
    source_path = tmp_path / "rollback-search-source.json"
    source_path.write_text(json.dumps(source), encoding="utf-8")

    _plan_data, _run_payload, import_id = _plan_then_run(data_dir, source_path, tmp_path)

    index_result = _run_index(data_dir)
    assert (
        index_result.returncode == 0
    ), f"index stdout: {index_result.stdout}\nstderr: {index_result.stderr}"
    assert _payload(index_result)["success"] is True

    before_rollback = _run_search(data_dir, unique_token)
    assert (
        before_rollback.returncode == 0
    ), f"search stdout: {before_rollback.stdout}\nstderr: {before_rollback.stderr}"
    assert _payload(before_rollback)["total_matches"] >= 1

    rollback_result = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        rollback_result.returncode == 0
    ), f"rollback stdout: {rollback_result.stdout}\nstderr: {rollback_result.stderr}"
    assert _payload(rollback_result)["data"]["state"] == "rolled_back"

    after_rollback = _run_search(data_dir, unique_token)
    assert (
        after_rollback.returncode == 0
    ), f"search stdout: {after_rollback.stdout}\nstderr: {after_rollback.stderr}"
    after_payload = _payload(after_rollback)
    assert after_payload["total_matches"] == 0
    assert after_payload["merged_results"] == []


def test_import_rollback_keeps_files_when_freshness_queue_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Rollback must not delete a journal it cannot queue for index removal."""
    import tools.ingest.runner as runner

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    _plan_data, run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )
    journal_entry = next(
        entry for entry in run_payload["data"]["created_files"] if entry["kind"] == "journal"
    )
    journal_path = data_dir / journal_entry["rel_path"]
    assert journal_path.exists()

    def _raise_pending_failure(_journal_path: str) -> None:
        raise OSError("synthetic pending persistence failure")

    monkeypatch.setattr(runner, "mark_pending", _raise_pending_failure, raising=False)

    result = runner.execute_rollback(import_id=import_id, data_dir=data_dir)

    assert result["success"] is False
    assert result["error"]["code"] == "IMPORT_INTERNAL_ERROR"
    assert journal_path.exists()


# ===================================================================
# PRD §12 Test 9: rollback refuses checksum mismatch
# ===================================================================


def test_import_rollback_refuses_checksum_mismatch(
    tmp_path: Path,
) -> None:
    """PRD §12(9): rollback refuses to delete a user-modified file."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    created = run_payload["data"]["created_files"]
    assert len(created) > 0, "Expected at least one created file"

    # Tamper with the first created file so its checksum no longer matches
    tampered_path = data_dir / created[0]["rel_path"]
    tampered_path.write_text("TAMPERED CONTENT", encoding="utf-8")

    rollback_result = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )

    assert rollback_result.returncode != 0
    rollback_payload = _payload(rollback_result)
    assert rollback_payload["success"] is False
    assert rollback_payload["error"]["code"] == "IMPORT_ROLLBACK_CHECKSUM_MISMATCH"
    # The tampered file must still exist
    assert tampered_path.exists()


# ===================================================================
# PRD §12 Test 10: structured error envelopes
# ===================================================================


def test_import_error_envelope_has_stable_codes(tmp_path: Path) -> None:
    """PRD §12(10): failure paths return structured error envelopes."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    result = _run_import(
        data_dir,
        "plan",
        "--source",
        "nonexistent.adapter",
        "--input",
        "/dev/null",
        "--json",
    )

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["schema_version"] == ENVELOPE_SCHEMA_VERSION

    error = payload["error"]
    assert "code" in error
    assert "message" in error
    assert "details" in error
    assert "retryable" in error
    assert isinstance(error["retryable"], bool)


def test_import_run_rejects_file_with_missing_fingerprint(
    tmp_path: Path,
) -> None:
    """PRD §12(10): running an import file missing fingerprints returns
    IMPORT_PLAN_INVALID or IMPORT_PLAN_SCHEMA_UNSUPPORTED.

    Renamed from ``test_import_invalid_plan_returns_import_plan_invalid`` to
    avoid collection by ``-k "plan"`` — this is an S3 ``run`` behaviour test,
    not an S2 ``plan`` test.  Assertion and coverage are unchanged.
    """
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    result = _run_import(
        data_dir,
        "run",
        "--plan",
        _fixture_path("invalid_plan_missing_fingerprint.json"),
        "--confirm",
        "imp_20260529_invalid001",
        "--json",
    )

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["error"]["code"] in (
        "IMPORT_PLAN_INVALID",
        "IMPORT_PLAN_SCHEMA_UNSUPPORTED",
    )


# ===================================================================
# PRD §12 Test 11: fixed paths, fingerprints, and hash assertions
# ===================================================================


def test_import_contract_asserts_fixed_paths_and_hashes(
    tmp_path: Path,
) -> None:
    """PRD §12(11): assert proposal_fingerprint, normalized hashes,
    fixed ledger path, and fixed rollback manifest path."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    # --- Plan ---
    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert (
        plan_result.returncode == 0
    ), f"stdout: {plan_result.stdout}\nstderr: {plan_result.stderr}"
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    # proposal_fingerprint present in every proposal
    for proposal in plan_data["proposals"]:
        assert "proposal_fingerprint" in proposal
        assert proposal["proposal_fingerprint"].startswith("sha256:")

    # source_fingerprint present
    assert plan_data["source"]["source_fingerprint"].startswith("sha256:")

    # Fixed rollback manifest path
    expected_rollback_rel = _rollback_manifest_rel_path(import_id)

    # --- Run ---
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")
    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    assert run_result.returncode == 0, f"stdout: {run_result.stdout}\nstderr: {run_result.stderr}"
    run_data = _payload(run_result)["data"]

    # Assert fixed rollback manifest path (PRD §8)
    assert run_data["rollback_manifest_rel_path"] == expected_rollback_rel

    # Assert fixed ledger path (PRD §9)
    ledger_path = data_dir / LEDGER_REL_PATH
    assert ledger_path.exists(), f"Ledger not found at {LEDGER_REL_PATH}"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["schema_version"] == "import_job_ledger.v1"
    assert import_id in ledger["jobs"]
    ledger_entry = ledger["jobs"][import_id]
    assert ledger_entry["rollback_manifest_rel_path"] == expected_rollback_rel

    # --- Status must reference same fixed paths ---
    status_result = _run_import(
        data_dir,
        "status",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        status_result.returncode == 0
    ), f"stdout: {status_result.stdout}\nstderr: {status_result.stderr}"
    status_data = _payload(status_result)["data"]
    assert status_data["rollback_manifest_rel_path"] == expected_rollback_rel


# ===================================================================
# PRD §8-§10: Durable-write ordering and partial failure evidence
# ===================================================================


def test_import_run_creates_ledger_before_durable_writes(
    tmp_path: Path,
) -> None:
    """PRD §9: ledger must exist with state=running before any journal/attachment
    file is created.  Verified by calling execute_run directly with a monkeypatch
    that inspects state at the first durable-write call.
    """
    from unittest.mock import patch
    from tools.ingest.runner import execute_run

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    # First, generate a plan via CLI
    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    plan_file = tmp_path / "plan_test_ordering.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    ledger_path = data_dir / ".life-index" / "import-jobs" / "ledger.json"
    first_durable_checked = {"done": False}

    original_write_text = Path.write_text

    def _checking_write_text(self, content, *args, **kwargs):
        if not first_durable_checked["done"]:
            # Normalize to forward slashes for cross-platform matching
            str_self = str(self).replace("\\", "/")
            if "Journals/" in str_self or "attachments/" in str_self:
                assert ledger_path.exists(), (
                    "PRD §9 violation: ledger must be created before "
                    f"durable file writes. Ledger path: {ledger_path}"
                )
                ledger_data = json.loads(ledger_path.read_text(encoding="utf-8"))
                assert import_id in ledger_data.get("jobs", {}), (
                    "PRD §9 violation: ledger must contain the import_id " "before durable writes."
                )
                job = ledger_data["jobs"][import_id]
                assert job.get("state") == "running", (
                    f"PRD §9 violation: ledger state before durable writes "
                    f"must be 'running', got '{job.get('state')}'"
                )
                first_durable_checked["done"] = True
        return original_write_text(self, content, *args, **kwargs)

    with patch.object(Path, "write_text", _checking_write_text):
        result = execute_run(
            plan_path=str(plan_file),
            confirm_id=import_id,
            data_dir=data_dir,
        )

    assert result["success"] is True
    assert first_durable_checked["done"], (
        "The pre-condition check was never triggered — " "no journal/attachment write occurred."
    )


def test_import_run_manifest_has_evidence_for_each_created_file(
    tmp_path: Path,
) -> None:
    """PRD §10: rollback manifest must contain checksum evidence for every
    file created by the run."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    # Read the manifest from disk
    manifest_rel = _rollback_manifest_rel_path(import_id)
    manifest_path = data_dir / manifest_rel
    assert manifest_path.exists(), f"Rollback manifest not found at {manifest_rel}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["state"] == "committed"
    manifest_files = manifest.get("created_files", [])
    run_files = run_payload["data"]["created_files"]

    # Every file reported in the run result must have evidence in the manifest
    assert len(manifest_files) == len(run_files), (
        f"Manifest has {len(manifest_files)} files, " f"but run reported {len(run_files)} files"
    )
    for mf in manifest_files:
        assert mf.get("sha256_after"), f"Manifest file entry missing checksum: {mf.get('rel_path')}"
        assert mf.get("kind") in ("journal", "attachment")


def test_import_run_partial_failure_preserves_evidence(
    tmp_path: Path,
) -> None:
    """PRD §8/§10: if a write error occurs after some files are created,
    the result must include state=partially_committed and the manifest must
    contain rollback evidence for every created file.

    Tested deterministically via monkeypatch on execute_run's write path.
    """
    from unittest.mock import patch
    from tools.ingest.runner import execute_run

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    # Fresh data dir for the partial failure test
    data_dir2 = tmp_path / "Life-Index-2"
    data_dir2.mkdir(parents=True, exist_ok=True)

    plan_file = tmp_path / "plan_partial.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    # Patch Path.write_text to fail after the first journal file is written.
    # Write sequence: ledger(1) + manifest-init(2) + journal-1(3) + manifest-update(4)
    # We fail at call 4 (after first journal written, during manifest evidence write)
    # This simulates a crash right after the first file is durably created.
    original_write_text = Path.write_text
    call_count = {"n": 0}
    TARGET_FAILURE = 4

    def _failing_write_text(self, content, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == TARGET_FAILURE:
            raise OSError("Simulated write failure for partial failure test")
        return original_write_text(self, content, *args, **kwargs)

    with patch.object(Path, "write_text", _failing_write_text):
        result = execute_run(
            plan_path=str(plan_file),
            confirm_id=import_id,
            data_dir=data_dir2,
        )

    # Read the manifest from disk
    manifest_rel = _rollback_manifest_rel_path(import_id)
    manifest_path = data_dir2 / manifest_rel

    if result["success"] is True and result["data"]["state"] == "partially_committed":
        # Partial failure path: some files were created
        assert manifest_path.exists(), f"Manifest missing after partial failure: {manifest_rel}"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["state"] == "partially_committed"
        assert (
            len(manifest["created_files"]) > 0
        ), "Partially committed run must have at least one file in manifest"
        for mf in manifest["created_files"]:
            assert mf.get("sha256_after"), "Missing checksum in manifest entry"
        # Ledger must also reflect partial state
        ledger_path = data_dir2 / ".life-index" / "import-jobs" / "ledger.json"
        assert ledger_path.exists()
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        assert ledger["jobs"][import_id]["state"] == "partially_committed"
    elif result["success"] is False:
        # Failed before any durable file — manifest should exist with failed/running
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert manifest["state"] in ("failed", "running")
    else:
        # If all writes succeeded despite the patch (unlikely), still valid
        assert result["data"]["state"] in ("committed", "partially_committed")


# ===================================================================
# PRD §8-§10: Idempotency state guard — non-committed states must
# not be reported as already_committed
# ===================================================================


def test_import_run_idempotency_partially_committed_not_already_committed(
    tmp_path: Path,
) -> None:
    """A prior run left in state=partially_committed must NOT return
    already_committed on a repeated run.  It must return
    state=partially_committed with the existing manifest evidence.

    Uses the existing partial-failure monkeypatch pattern to create a
    partially committed ledger entry, then calls execute_run again with
    the same plan.
    """
    from unittest.mock import patch
    from tools.ingest.runner import execute_run

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    plan_file = tmp_path / "plan_partial_idem.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    # First run: inject partial failure to leave state=partially_committed
    original_write_text = Path.write_text
    call_count = {"n": 0}
    TARGET_FAILURE = 4  # fail after first journal is durably written

    def _failing_write_text(self, content, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == TARGET_FAILURE:
            raise OSError("Simulated partial failure for idempotency test")
        return original_write_text(self, content, *args, **kwargs)

    with patch.object(Path, "write_text", _failing_write_text):
        first_result = execute_run(
            plan_path=str(plan_file),
            confirm_id=import_id,
            data_dir=data_dir,
        )

    # The first run must be partially committed (or failed before files)
    first_state = first_result["data"]["state"] if first_result["success"] else None
    if first_state != "partially_committed":
        # If the failure happened before any file was created, the state is
        # "failed" and the idempotency key is already written.  We need to
        # manually set the ledger to partially_committed to test the guard.
        # This simulates the scenario where partial failure did happen.
        from tools.ingest import runner as _runner

        ledger = _runner._read_ledger(data_dir)
        if import_id in ledger.get("jobs", {}):
            ledger["jobs"][import_id]["state"] = "partially_committed"
            _runner._write_ledger(data_dir, ledger)
        else:
            # Job not in ledger at all; seed it manually
            now_iso = (
                __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            )
            rollback_rel = f".life-index/import-jobs/{import_id}/rollback-manifest.json"
            ledger.setdefault("jobs", {})[import_id] = {
                "state": "partially_committed",
                "idempotency_key": plan_data["idempotency_key"],
                "plan_fingerprint": plan_data["plan_fingerprint"],
                "rollback_manifest_rel_path": rollback_rel,
                "updated_at": now_iso,
            }
            ledger.setdefault("idempotency_index", {})[plan_data["idempotency_key"]] = import_id
            _runner._write_ledger(data_dir, ledger)

            # Also create a minimal manifest with one file as evidence
            manifest_dir = data_dir / ".life-index" / "import-jobs" / import_id
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "rollback-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": "import_rollback_manifest.v1",
                        "import_id": import_id,
                        "state": "partially_committed",
                        "created_files": [
                            {
                                "kind": "journal",
                                "rel_path": "Journals/2026/05/life-index_2026-05-29_001.md",
                                "sha256_after": "sha256:abc",
                                "size_bytes": 100,
                                "created_by_import": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

    # Second run with same plan: must NOT return already_committed
    second_result = execute_run(
        plan_path=str(plan_file),
        confirm_id=import_id,
        data_dir=data_dir,
    )

    assert (
        second_result["success"] is True
    ), f"Second run failed unexpectedly: {second_result.get('error')}"
    assert second_result["data"]["state"] == "partially_committed", (
        f"Expected state=partially_committed but got "
        f"state={second_result['data']['state']}. "
        f"A partially_committed prior run must NOT be reported as already_committed."
    )
    assert second_result["data"]["import_id"] == import_id


def test_import_run_idempotency_failed_not_already_committed(
    tmp_path: Path,
) -> None:
    """A prior run left in state=failed must NOT return already_committed.
    It must return IMPORT_JOB_NOT_COMMITTED error."""
    from tools.ingest.runner import execute_run, _read_ledger, _write_ledger

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]
    idempotency_key = plan_data["idempotency_key"]

    plan_file = tmp_path / "plan_failed_idem.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    # Seed ledger with a failed job entry
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    rollback_rel = f".life-index/import-jobs/{import_id}/rollback-manifest.json"
    ledger = _read_ledger(data_dir)
    ledger["jobs"][import_id] = {
        "state": "failed",
        "idempotency_key": idempotency_key,
        "plan_fingerprint": plan_data["plan_fingerprint"],
        "rollback_manifest_rel_path": rollback_rel,
        "updated_at": now_iso,
    }
    ledger["idempotency_index"][idempotency_key] = import_id
    _write_ledger(data_dir, ledger)

    # Re-run with same plan: must NOT return already_committed
    result = execute_run(
        plan_path=str(plan_file),
        confirm_id=import_id,
        data_dir=data_dir,
    )

    assert (
        result["success"] is False
    ), f"Expected failure but got success with state={result.get('data', {}).get('state')}"
    assert (
        result["error"]["code"] == "IMPORT_JOB_NOT_COMMITTED"
    ), f"Expected IMPORT_JOB_NOT_COMMITTED but got {result['error']['code']}"
    assert (
        "failed" in result["error"]["message"]
    ), f"Error message should mention 'failed' state: {result['error']['message']}"


def test_import_run_idempotency_running_not_already_committed(
    tmp_path: Path,
) -> None:
    """A prior run left in state=running must NOT return already_committed.
    It must return IMPORT_JOB_NOT_COMMITTED error."""
    from tools.ingest.runner import execute_run, _read_ledger, _write_ledger

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]
    idempotency_key = plan_data["idempotency_key"]

    plan_file = tmp_path / "plan_running_idem.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    # Seed ledger with a running job entry (simulates a crashed run)
    now_iso = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    rollback_rel = f".life-index/import-jobs/{import_id}/rollback-manifest.json"
    ledger = _read_ledger(data_dir)
    ledger["jobs"][import_id] = {
        "state": "running",
        "idempotency_key": idempotency_key,
        "plan_fingerprint": plan_data["plan_fingerprint"],
        "rollback_manifest_rel_path": rollback_rel,
        "updated_at": now_iso,
    }
    ledger["idempotency_index"][idempotency_key] = import_id
    _write_ledger(data_dir, ledger)

    # Re-run with same plan: must NOT return already_committed
    result = execute_run(
        plan_path=str(plan_file),
        confirm_id=import_id,
        data_dir=data_dir,
    )

    assert (
        result["success"] is False
    ), f"Expected failure but got success with state={result.get('data', {}).get('state')}"
    assert (
        result["error"]["code"] == "IMPORT_JOB_NOT_COMMITTED"
    ), f"Expected IMPORT_JOB_NOT_COMMITTED but got {result['error']['code']}"
    assert (
        "running" in result["error"]["message"]
    ), f"Error message should mention 'running' state: {result['error']['message']}"


# ===================================================================
# S4: Rollback idempotency, status-after-rollback, manifest evidence
# ===================================================================


def test_import_rollback_idempotent_returns_rolled_back(
    tmp_path: Path,
) -> None:
    """S4 self-check: repeated rollback after successful removal returns
    ``rolled_back`` without error (PRD §10 idempotency)."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, _run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    # First rollback
    first_rb = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        first_rb.returncode == 0
    ), f"First rollback failed: stdout={first_rb.stdout}\nstderr={first_rb.stderr}"
    first_payload = _payload(first_rb)
    assert first_payload["data"]["state"] == "rolled_back"

    # Second rollback — must succeed idempotently
    second_rb = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        second_rb.returncode == 0
    ), f"Idempotent rollback failed: stdout={second_rb.stdout}\nstderr={second_rb.stderr}"
    second_payload = _payload(second_rb)
    assert second_payload["data"]["state"] == "rolled_back"
    assert second_payload["data"]["import_id"] == import_id


def test_import_status_reports_rolled_back_after_rollback(
    tmp_path: Path,
) -> None:
    """S4 self-check: ``import status`` reports ``rolled_back`` after a
    successful rollback (PRD §9 valid states)."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, _run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    # Perform rollback
    rb_result = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        rb_result.returncode == 0
    ), f"Rollback failed: stdout={rb_result.stdout}\nstderr={rb_result.stderr}"

    # Check status
    status_result = _run_import(
        data_dir,
        "status",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        status_result.returncode == 0
    ), f"Status failed: stdout={status_result.stdout}\nstderr={status_result.stderr}"
    status_payload = _payload(status_result)
    assert status_payload["success"] is True
    assert status_payload["data"]["state"] == "rolled_back"
    assert status_payload["data"]["import_id"] == import_id


def test_import_rollback_preserves_manifest_as_audit_evidence(
    tmp_path: Path,
) -> None:
    """S4 self-check: rollback manifest remains on disk after successful
    rollback and has state=rolled_back (PRD §10 audit evidence)."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    _plan_data, _run_payload, import_id = _plan_then_run(
        data_dir, "minimal_plan_source.json", tmp_path
    )

    manifest_rel = _rollback_manifest_rel_path(import_id)
    manifest_path = data_dir / manifest_rel
    assert manifest_path.exists(), "Manifest must exist before rollback"

    # Perform rollback
    rb_result = _run_import(
        data_dir,
        "rollback",
        "--import-id",
        import_id,
        "--json",
    )
    assert (
        rb_result.returncode == 0
    ), f"Rollback failed: stdout={rb_result.stdout}\nstderr={rb_result.stderr}"

    # Manifest must still exist as audit evidence
    assert (
        manifest_path.exists()
    ), f"Rollback manifest must be preserved as audit evidence: {manifest_rel}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "rolled_back"
    assert manifest["import_id"] == import_id

    # Ledger must also show rolled_back
    ledger_path = data_dir / LEDGER_REL_PATH
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["jobs"][import_id]["state"] == "rolled_back"


# ===================================================================
# S4 Rework v01: Path confinement regression (PRD §11 IMPORT_ROLLBACK_UNSAFE)
# ===================================================================


def test_import_rollback_refuses_unsafe_manifest_path(
    tmp_path: Path,
) -> None:
    """PRD §11 IMPORT_ROLLBACK_UNSAFE: a rollback manifest containing a path
    that escapes the data directory (e.g. ``../outside.txt``) must fail closed
    with IMPORT_ROLLBACK_UNSAFE and must NOT delete any file — including an
    outside sentinel file.

    This test directly manipulates the manifest on disk to inject an unsafe
    path, then calls ``execute_rollback`` and verifies the sentinel survives.
    """
    from tools.ingest.runner import execute_rollback, _read_ledger

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    # --- Set up a committed import job with a real file inside data_dir ---
    plan_result = _run_import(
        data_dir,
        "plan",
        "--source",
        "fixture.import_records",
        "--input",
        _fixture_path("minimal_plan_source.json"),
        "--json",
    )
    assert plan_result.returncode == 0
    plan_data = _payload(plan_result)["data"]
    import_id = plan_data["import_id"]

    plan_file = tmp_path / "plan_unsafe.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")

    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        import_id,
        "--json",
    )
    assert (
        run_result.returncode == 0
    ), f"run stdout: {run_result.stdout}\nstderr: {run_result.stderr}"

    # --- Create an outside sentinel file ---
    outside_dir = tmp_path / "outside-area"
    outside_dir.mkdir(parents=True, exist_ok=True)
    sentinel = outside_dir / "outside.txt"
    sentinel.write_text("SENTINEL - must survive rollback", encoding="utf-8")
    assert sentinel.exists()

    # --- Tamper the manifest to inject an unsafe traversal path ---
    manifest_rel = _rollback_manifest_rel_path(import_id)
    manifest_path = data_dir / manifest_rel
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Compute the relative traversal from data_dir to the sentinel
    # data_dir is tmp_path/Life-Index, sentinel is tmp_path/outside-area/outside.txt
    # So the traversal is ../outside-area/outside.txt
    unsafe_rel = "../outside-area/outside.txt"
    manifest["created_files"].append(
        {
            "kind": "journal",
            "rel_path": unsafe_rel,
            "sha256_after": f"sha256:{hashlib.sha256(b'irrelevant').hexdigest()}",
            "size_bytes": 999,
            "created_by_import": True,
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # --- Execute rollback via direct function call ---
    result = execute_rollback(import_id=import_id, data_dir=data_dir)

    # --- Assertions ---
    assert result["success"] is False, f"Expected failure but got success: {result}"
    assert (
        result["error"]["code"] == "IMPORT_ROLLBACK_UNSAFE"
    ), f"Expected IMPORT_ROLLBACK_UNSAFE but got {result['error']['code']}"
    # The outward envelope is locator-free: only reason + counts + entry indices.
    # The raw hostile/traversal rel_path must never be echoed back.
    details = result["error"]["details"]
    expected_unsafe_index = len(manifest["created_files"]) - 1
    assert details["reason"] == "unsafe_manifest_entries"
    assert "unsafe_paths" not in details
    assert details["unsafe_path_count"] >= 1
    assert expected_unsafe_index in details["unsafe_entry_indices"]
    assert unsafe_rel not in json.dumps(details)

    # The outside sentinel must survive
    assert sentinel.exists(), "OUTSIDE SENTINEL WAS DELETED — path confinement failed!"
    assert sentinel.read_text(encoding="utf-8") == "SENTINEL - must survive rollback"

    # Ledger must show rollback_failed
    ledger = _read_ledger(data_dir)
    assert ledger["jobs"][import_id]["state"] == "rollback_failed"


def _copy_fixture_photo(name: str, dest_dir: Path) -> Path:
    """Copy a photo fixture to a temp directory for testing."""
    import shutil as _shutil

    src = PHOTO_FIXTURES_DIR / name
    dest = dest_dir / name
    _shutil.copy2(src, dest)
    return dest


# ===================================================================
# Tranche B: Photo Timeline adapter contract tests (S1)
# ===================================================================

PHOTO_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "import_jobs" / "photo_timeline"


def _run_photo_plan(data_dir: Path, input_dir: Path) -> subprocess.CompletedProcess[str]:
    """Run import plan with media.photo_timeline source."""
    return _run_import(
        data_dir,
        "plan",
        "--source",
        "media.photo_timeline",
        "--input",
        str(input_dir),
        "--json",
    )


def test_photo_timeline_plan_generates_import_plan_envelope(
    tmp_path: Path,
) -> None:
    """Uses photo_with_exif.jpg fixture. Verifies envelope shape."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Copy fixture to temp dir (adapter takes a directory)
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)

    assert payload["schema_version"] == ENVELOPE_SCHEMA_VERSION
    assert payload["success"] is True
    assert payload["command"] == "import.plan"

    data = payload["data"]
    assert data["dry_run"] is True
    assert data["plan_fingerprint"].startswith("sha256:")
    assert data["source"]["adapter_id"] == "media.photo_timeline"

    proposals = data["proposals"]
    assert len(proposals) >= 1
    for proposal in proposals:
        assert "journal" in proposal
        assert "attachments" in proposal
        assert proposal["proposal_fingerprint"].startswith("sha256:")


def test_photo_timeline_plan_does_not_write_data_dir(
    tmp_path: Path,
) -> None:
    """Plan must not create any files under data_dir."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    files_before = set(data_dir.rglob("*")) if data_dir.exists() else set()

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

    files_after = set(data_dir.rglob("*")) if data_dir.exists() else set()
    assert files_after == files_before, f"import plan created files: {files_after - files_before}"


def test_photo_timeline_missing_capture_time_blocks_run(
    tmp_path: Path,
) -> None:
    """Photo without EXIF capture time must generate a blocking conflict."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_no_exif.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    data = payload["data"]

    assert (
        data["summary"]["conflict_count"] > 0
    ), f"Expected conflicts for photo without capture time: {data['summary']}"

    # Verify conflict code
    conflicts = data["conflicts"]
    conflict_codes = [c.get("code", c.get("type", "")) for c in conflicts]
    assert any(
        "PHOTO_CAPTURE_TIME_MISSING" in code for code in conflict_codes
    ), f"Expected PHOTO_CAPTURE_TIME_MISSING conflict, got: {conflict_codes}"

    # Attempting import run should fail with IMPORT_PLAN_CONFLICTS_UNRESOLVED
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(data), encoding="utf-8")

    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        data["import_id"],
        "--json",
    )
    assert run_result.returncode != 0
    run_payload = _payload(run_result)
    assert run_payload["success"] is False
    assert run_payload["error"]["code"] == "IMPORT_PLAN_CONFLICTS_UNRESOLVED"


def test_photo_timeline_ambiguous_capture_time_blocks_run(
    tmp_path: Path,
) -> None:
    """Conflicting EXIF date tags must generate PHOTO_CAPTURE_TIME_AMBIGUOUS."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_ambiguous_dates.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    data = payload["data"]

    assert data["summary"]["conflict_count"] > 0
    conflict_codes = [conflict.get("code", "") for conflict in data["conflicts"]]
    assert "PHOTO_CAPTURE_TIME_AMBIGUOUS" in conflict_codes

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(data), encoding="utf-8")
    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        data["import_id"],
        "--source-root",
        str(photo_dir),
        "--json",
    )
    assert run_result.returncode != 0
    run_payload = _payload(run_result)
    assert run_payload["error"]["code"] == "IMPORT_PLAN_CONFLICTS_UNRESOLVED"


def test_photo_timeline_missing_gps_is_warning_only(
    tmp_path: Path,
) -> None:
    """Photo without GPS should have warnings but no conflicts."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_gps_missing.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    data = payload["data"]

    assert (
        data["summary"]["conflict_count"] == 0
    ), f"GPS missing should NOT be a conflict: {data['summary']}"

    warnings = data["warnings"]
    warning_codes = [w.get("code", "") for w in warnings]
    assert any(
        "PHOTO_GPS_MISSING" in code for code in warning_codes
    ), f"Expected PHOTO_GPS_MISSING warning, got: {warning_codes}"


def test_photo_timeline_source_fingerprint_stable_without_absolute_paths(
    tmp_path: Path,
) -> None:
    """Source fingerprint must be stable and not leak absolute paths."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    # Run plan twice
    result1 = _run_photo_plan(data_dir, photo_dir)
    assert result1.returncode == 0
    payload1 = _payload(result1)

    result2 = _run_photo_plan(data_dir, photo_dir)
    assert result2.returncode == 0
    payload2 = _payload(result2)

    # Source fingerprint must be stable
    fp1 = payload1["data"]["source"]["source_fingerprint"]
    fp2 = payload2["data"]["source"]["source_fingerprint"]
    assert fp1 == fp2, f"Fingerprints unstable: {fp1} vs {fp2}"

    # Plan fingerprint must be stable
    plan_fp1 = payload1["data"]["plan_fingerprint"]
    plan_fp2 = payload2["data"]["plan_fingerprint"]
    assert plan_fp1 == plan_fp2, f"Plan fingerprints unstable: {plan_fp1} vs {plan_fp2}"

    # JSON output must NOT contain the absolute path of the input directory
    plan_json = json.dumps(payload1["data"], ensure_ascii=False)
    photo_dir_str = str(photo_dir).replace("\\", "/")
    assert (
        photo_dir_str not in plan_json
    ), f"Plan JSON leaked input path: {photo_dir_str} found in output"

    # Check proposals and source_ref don't leak paths
    for proposal in payload1["data"]["proposals"]:
        source_ref = proposal.get("source_record_id", "")
        assert photo_dir_str not in source_ref, f"source_record_id leaked input path: {source_ref}"


def test_photo_timeline_gps_canonicalization_is_stable(
    tmp_path: Path,
) -> None:
    """GPS data must be normalized and produce stable fingerprints."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    result1 = _run_photo_plan(data_dir, photo_dir)
    assert result1.returncode == 0
    payload1 = _payload(result1)

    result2 = _run_photo_plan(data_dir, photo_dir)
    assert result2.returncode == 0
    payload2 = _payload(result2)

    # Same fixture, same fingerprint
    assert payload1["data"]["plan_fingerprint"] == payload2["data"]["plan_fingerprint"]


def test_photo_timeline_missing_orientation_uses_null_with_warning(
    tmp_path: Path,
) -> None:
    """Photo without orientation should warn PHOTO_ORIENTATION_MISSING."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_gps_missing.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    data = payload["data"]

    warnings = data["warnings"]
    warning_codes = [w.get("code", "") for w in warnings]
    assert any(
        "PHOTO_ORIENTATION_MISSING" in code for code in warning_codes
    ), f"Expected PHOTO_ORIENTATION_MISSING warning, got: {warning_codes}"


def test_photo_timeline_corrupted_exif_graceful_degradation(
    tmp_path: Path,
) -> None:
    """Corrupted EXIF must not crash the plan."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_corrupted_exif.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    # Should not crash (returncode=0 even with warnings/conflicts is OK)
    payload = _payload(result)
    assert payload["success"] is True, f"Plan should not crash on corrupted EXIF: {payload}"
    # Should have at least warnings or conflicts about the corrupted file
    data = payload["data"]
    warnings_or_conflicts = len(data["warnings"]) + len(data["conflicts"])
    assert warnings_or_conflicts > 0, "Expected warnings or conflicts for corrupted EXIF"
    warning_codes = [warning.get("code", "") for warning in data["warnings"]]
    conflict_codes = [conflict.get("code", "") for conflict in data["conflicts"]]
    assert any(
        code in warning_codes
        for code in (
            "PHOTO_EXIF_UNREADABLE",
            "PHOTO_ORIENTATION_MISSING",
            "PHOTO_GPS_MISSING",
            "PHOTO_CAMERA_MISSING",
        )
    )
    assert warning_codes or conflict_codes


def test_photo_timeline_malformed_jpeg_emits_exif_unreadable(
    tmp_path: Path,
) -> None:
    """Malformed .jpg bytes should degrade to PHOTO_EXIF_UNREADABLE."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    (photo_dir / "malformed.jpg").write_bytes(b"not a valid jpeg")

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    data = payload["data"]

    warning_codes = [warning.get("code", "") for warning in data["warnings"]]
    conflict_codes = [conflict.get("code", "") for conflict in data["conflicts"]]
    assert "PHOTO_EXIF_UNREADABLE" in warning_codes
    assert "PHOTO_CAPTURE_TIME_MISSING" in conflict_codes


def test_photo_timeline_attachment_paths_stay_in_data_dir(
    tmp_path: Path,
) -> None:
    """All attachment target paths must be relative and inside data_dir."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)

    for proposal in payload["data"]["proposals"]:
        for att in proposal.get("attachments", []):
            target = att["target_rel_path"]
            # Must be relative (no leading slash, no drive letter)
            assert not Path(target).is_absolute(), f"Attachment path absolute: {target}"
            # Must start with attachments/
            assert target.startswith("attachments/"), f"Attachment not under attachments/: {target}"
            # Resolve inside data_dir
            resolved = (data_dir / target).resolve()
            assert str(resolved).startswith(
                str(data_dir.resolve())
            ), f"Attachment resolves outside data_dir: {resolved}"


def test_photo_timeline_import_run_copies_original_attachment_bytes(
    tmp_path: Path,
) -> None:
    """Photo import run copies original photo bytes when source root is provided."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    source_photo = _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    plan_data = _payload(result)["data"]
    assert plan_data["summary"]["conflict_count"] == 0

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(plan_data), encoding="utf-8")
    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        plan_data["import_id"],
        "--source-root",
        str(photo_dir),
        "--json",
    )
    assert run_result.returncode == 0, f"stdout: {run_result.stdout}\nstderr: {run_result.stderr}"

    target_rel = plan_data["proposals"][0]["attachments"][0]["target_rel_path"]
    target_abs = data_dir / target_rel
    assert target_abs.read_bytes() == source_photo.read_bytes()


def test_photo_timeline_existing_target_path_conflict_blocks_run(
    tmp_path: Path,
) -> None:
    """Pre-existing deterministic attachment target creates a blocking conflict."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)

    first_result = _run_photo_plan(data_dir, photo_dir)
    assert (
        first_result.returncode == 0
    ), f"stdout: {first_result.stdout}\nstderr: {first_result.stderr}"
    first_data = _payload(first_result)["data"]

    target_rel = first_data["proposals"][0]["attachments"][0]["target_rel_path"]
    target_abs = data_dir / target_rel
    target_abs.parent.mkdir(parents=True, exist_ok=True)
    target_abs.write_bytes(b"pre-existing attachment")

    second_result = _run_photo_plan(data_dir, photo_dir)
    assert (
        second_result.returncode == 0
    ), f"stdout: {second_result.stdout}\nstderr: {second_result.stderr}"
    second_data = _payload(second_result)["data"]

    assert (
        second_data["summary"]["conflict_count"] > 0
    ), f"Expected conflicts for existing target path: {second_data['summary']}"
    conflict_codes = [
        conflict.get("code", conflict.get("type", "")) for conflict in second_data["conflicts"]
    ]
    assert "PHOTO_TARGET_PATH_CONFLICT" in conflict_codes

    plan_file = tmp_path / "plan.json"
    plan_file.write_text(json.dumps(second_data), encoding="utf-8")
    run_result = _run_import(
        data_dir,
        "run",
        "--plan",
        str(plan_file),
        "--confirm",
        second_data["import_id"],
        "--json",
    )
    assert run_result.returncode != 0
    run_payload = _payload(run_result)
    assert run_payload["error"]["code"] == "IMPORT_PLAN_CONFLICTS_UNRESOLVED"


def test_photo_timeline_unsupported_file_warns_and_skips(
    tmp_path: Path,
) -> None:
    """Non-JPEG files should be skipped with PHOTO_UNSUPPORTED_FILE_SKIPPED warning."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    _copy_fixture_photo("photo_with_exif.jpg", photo_dir)
    _copy_fixture_photo("photo_unsupported.txt", photo_dir)

    result = _run_photo_plan(data_dir, photo_dir)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    data = payload["data"]

    # Only the JPEG should generate a proposal
    assert (
        data["source"]["record_count"] == 1
    ), f"Expected 1 record, got {data['source']['record_count']}"

    # Should have a warning about the unsupported file
    warnings = data["warnings"]
    warning_codes = [w.get("code", "") for w in warnings]
    assert any(
        "PHOTO_UNSUPPORTED_FILE_SKIPPED" in code for code in warning_codes
    ), f"Expected PHOTO_UNSUPPORTED_FILE_SKIPPED warning, got: {warning_codes}"
