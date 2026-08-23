#!/usr/bin/env python3
"""Fault-injection tests for the confirm plan/ledger crash protocol (gap 1).

The confirm flow persists a durable ``pending_review_update`` intent on the
parent job *before* replacing the review plan, then finalizes the parent
projection from that intent and clears it. Reconciliation (used by
confirm/status/run/rollback) converges across the crash windows:

- crash after intent, before plan  → abort intent, retain prior projection
  (remove an empty first-confirm shell);
- crash after plan, before finalize → finalize idempotently from the intent;
- no intent but persisted plan fingerprint disagrees with the ledger
  → fail closed with ``recovery_required`` + ``authority_status``.

These tests drive the public ``confirm_review`` / ``query_review_status`` entry
points in-process so a crash can be injected at an exact durable step, then
assert the public status outcome and persisted convergence.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import tools.ingest.review as review
from tests.contract.test_import_review_package1_contract import _make_jpeg_rich


class _CrashError(RuntimeError):
    """Raised to simulate a process crash at an injected durable step."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg(path: Path, *, color: tuple[int, int, int] = (1, 2, 3)) -> Path:
    """A JPEG with a valid EXIF capture date so it resolves to ``confirmed``."""
    return _make_jpeg_rich(
        path,
        color=color,
        make="TestCam",
        model="X100",
        dt_original="2024:05:06 07:08:09",
        offset_original="+05:30",
    )


def _plan_via_cli(data_dir: Path, src: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    res = subprocess.run(
        [sys.executable, "-m", "tools", "import", "plan",
         "--source", "media.photo_timeline", "--input", str(src), "--json"],
        capture_output=True, text=True, env=env, timeout=120,
        encoding="utf-8",
    )
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)["data"]


def _write_plan(tmp_path: Path, plan_data: dict[str, Any], name: str) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(plan_data), encoding="utf-8")
    return p


def _ledger(data_dir: Path) -> dict[str, Any]:
    return json.loads(
        (data_dir / ".life-index" / "import-jobs" / "ledger.json").read_text("utf-8")
    )


def _review_plan(data_dir: Path, parent_id: str) -> dict[str, Any]:
    return json.loads(
        (data_dir / ".life-index" / "import-jobs" / parent_id / "review-plan.json")
        .read_text("utf-8")
    )


def _confirm_inproc(plan_path: Path, data_dir: Path, src: Path) -> dict[str, Any]:
    return review.confirm_review(
        plan_path=str(plan_path), data_dir=data_dir, source_root=str(src)
    )


# ---------------------------------------------------------------------------
# Crash after intent, before plan replace
# ---------------------------------------------------------------------------


def test_crash_after_intent_before_plan_removes_first_confirm_shell(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _plan_via_cli(data_dir, src)
    parent_id = plan["import_id"]

    # First confirm: inject a crash right after the intent is persisted, before
    # the review plan is replaced. There is no prior plan on disk.
    monkeypatch.setattr(review, "_write_review_plan_atomic",
                        lambda *a, **k: (_ for _ in ()).throw(_CrashError()))

    with pytest.raises(_CrashError):
        _confirm_inproc(_write_plan(tmp_path, plan, "p.json"), data_dir, src)

    # Reconciliation must abort the intent and remove the empty first-confirm
    # shell: no pending intent, no parent review job left behind.
    status_res = review.query_review_status(parent_id, data_dir)
    status_data = status_res.get("data") or {}
    # The parent review job is gone (shell removed) → no review authority.
    assert status_data.get("kind") != "review"
    jobs = _ledger(data_dir).get("jobs", {})
    assert parent_id not in jobs
    # a fresh confirm now succeeds cleanly (convergence).
    monkeypatch.undo()
    res = _confirm_inproc(_write_plan(tmp_path, plan, "p2.json"), data_dir, src)
    assert res["success"]
    assert res["data"]["queue_counts"]["confirmed"] == 1


def test_crash_after_intent_before_plan_retains_prior_projection(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _plan_via_cli(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]

    # Establish a prior confirmed projection.
    first = _confirm_inproc(_write_plan(tmp_path, plan, "p.json"), data_dir, src)
    assert first["data"]["proposal_states"][pid] == "confirmed"
    prior_fp = _ledger(data_dir)["jobs"][parent_id]["plan_fingerprint"]

    # Re-confirm an EDITED plan (different content → different plan_fingerprint),
    # crashing after the intent is persisted but before the plan is replaced.
    edited = json.loads(json.dumps(plan))
    edited["proposals"][0]["journal"]["title"] = "Edited title for re-confirm"
    monkeypatch.setattr(review, "_write_review_plan_atomic",
                        lambda *a, **k: (_ for _ in ()).throw(_CrashError()))
    with pytest.raises(_CrashError):
        _confirm_inproc(_write_plan(tmp_path, edited, "e.json"), data_dir, src)

    # The persisted plan on disk is still the OLD one; reconciliation must abort
    # the intent and RETAIN the prior projection (plan_fingerprint unchanged,
    # no pending intent, recovery_required cleared).
    status = review.query_review_status(parent_id, data_dir)["data"]
    assert status["proposal_states"][pid] == "confirmed"
    assert status["recovery_required"] is False
    job = _ledger(data_dir)["jobs"][parent_id]
    assert job.get("pending_review_update") is None
    assert job["plan_fingerprint"] == prior_fp
    assert status["plan_fingerprint"] == prior_fp


# ---------------------------------------------------------------------------
# Crash after plan replace, before finalize
# ---------------------------------------------------------------------------


def test_crash_after_plan_before_finalize_converges(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _plan_via_cli(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]

    first = _confirm_inproc(_write_plan(tmp_path, plan, "p.json"), data_dir, src)
    assert first["success"]

    # Re-confirm an edited plan; the new plan IS replaced on disk, but the
    # finalize step crashes. The intent + new plan are both durable now.
    edited = json.loads(json.dumps(plan))
    edited["proposals"][0]["journal"]["title"] = "Edited title for finalize crash"
    new_fp_expected = None

    def crashing_finalize(data_dir_, ledger_, parent_id_, intent_):  # type: ignore[no-untyped-def]
        nonlocal new_fp_expected
        new_fp_expected = intent_["expected_plan_fingerprint"]
        # delegate to the real impl so the window is "after plan, at finalize"
        raise _CrashError()

    monkeypatch.setattr(review, "_finalize_review_update", crashing_finalize)
    with pytest.raises(_CrashError):
        _confirm_inproc(_write_plan(tmp_path, edited, "e.json"), data_dir, src)
    monkeypatch.undo()

    # The new plan is on disk (matches the intent); reconciliation finalizes
    # idempotently from the intent → projection reflects the new plan, no
    # pending intent, recovery_required cleared.
    assert _review_plan(data_dir, parent_id)["plan_fingerprint"] == new_fp_expected
    status = review.query_review_status(parent_id, data_dir)["data"]
    assert status["proposal_states"][pid] == "confirmed"
    assert status["recovery_required"] is False
    job = _ledger(data_dir)["jobs"][parent_id]
    assert job.get("pending_review_update") is None
    assert job["plan_fingerprint"] == new_fp_expected

    # repeated status converges (idempotent, no further mutation)
    status2 = review.query_review_status(parent_id, data_dir)["data"]
    assert status2["proposal_states"] == status["proposal_states"]
    assert status2["plan_fingerprint"] == new_fp_expected


# ---------------------------------------------------------------------------
# Unexplained plan/ledger mismatch (no intent) → fail closed
# ---------------------------------------------------------------------------


def test_unexplained_plan_ledger_mismatch_fails_closed(
    isolated_data_dir: Path, tmp_path: Path
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _plan_via_cli(data_dir, src)
    parent_id = plan["import_id"]

    first = _confirm_inproc(_write_plan(tmp_path, plan, "p.json"), data_dir, src)
    assert first["success"]

    # Simulate unexplained corruption: rewrite the persisted review plan with a
    # DIFFERENT plan_fingerprint while the ledger keeps its authority. No intent.
    persisted = _review_plan(data_dir, parent_id)
    persisted["plan_fingerprint"] = "sha256:deadbeef" + "0" * 54
    (data_dir / ".life-index" / "import-jobs" / parent_id / "review-plan.json").write_text(
        json.dumps(persisted), encoding="utf-8"
    )

    # status must NOT silently pick one: surface recovery_required + authority_status.
    status = review.query_review_status(parent_id, data_dir)["data"]
    assert status["recovery_required"] is True
    assert status["authority_status"] == "plan_ledger_mismatch"

    # run must fail closed rather than act on the disagreeing plan.
    run_res = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert not run_res["success"]
    assert run_res["error"]["code"] == "IMPORT_RECOVERY_REQUIRED"
