#!/usr/bin/env python3
"""Gap 2 tests: parent lock on child rollback projection.

``execute_review_rollback`` must identify the child's parent, acquire the
per-parent lock, then perform the checksum-guarded child rollback and the exact
``child.proposal_ids`` projection while holding that lock — the same lock
``run`` takes, so parent↔child lock order stays consistent.

The first test is a **lock-spy**: it proves behaviourally that the parent
projection ledger write happens while the parent review lock is held (it does
not merely assert a helper was called). The second proves the projection is
driven by the child's exact ``proposal_ids`` membership, never by the parent's
last selection.
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
import tools.ingest.runner as runner
from tests.contract.test_import_review_package1_contract import _make_jpeg_rich


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg(path: Path, *, color: tuple[int, int, int]) -> Path:
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


def _save_ledger(data_dir: Path, ledger: dict[str, Any]) -> None:
    (data_dir / ".life-index" / "import-jobs" / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _confirmed_run_child(
    data_dir: Path, src: Path, tmp_path: Path
) -> tuple[str, str, str]:
    """Plan + confirm one photo + run a batch; return (parent_id, child_id, pid)."""
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _plan_via_cli(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    review.confirm_review(
        plan_path=str(_write_plan(tmp_path, plan, "p.json")),
        data_dir=data_dir, source_root=str(src),
    )
    run = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert run["success"], run
    child_id = run["data"]["import_id"]
    return parent_id, child_id, pid


# ---------------------------------------------------------------------------
# Lock-spy: parent projection is guarded by the parent review lock
# ---------------------------------------------------------------------------


def test_rollback_projects_parent_under_parent_lock(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    parent_id, child_id, pid = _confirmed_run_child(data_dir, src, tmp_path)
    # sanity: the proposal is imported before rollback
    assert _ledger(data_dir)["jobs"][parent_id]["proposal_states"][pid] == "imported"

    # --- Spy on the parent review lock: track whether it is held ---
    held = {"parent": False}
    real_lock = review.FileLock

    class SpyLock:
        def __init__(self, path: Any, timeout: float = 30.0) -> None:
            self._path = str(path)
            self._inner = real_lock(path, timeout=timeout)

        def __enter__(self) -> "SpyLock":
            self._inner.__enter__()
            if "review.lock" in self._path:
                held["parent"] = True
            return self

        def __exit__(self, *exc: Any) -> None:
            if "review.lock" in self._path:
                held["parent"] = False
            return self._inner.__exit__(*exc)

    monkeypatch.setattr(review, "FileLock", SpyLock)

    # --- Spy on ledger writes: capture held-state of any projection write ---
    # A projection write is one that restores the rolled-back child's proposal
    # to ``confirmed`` on the parent. review._write_ledger delegates to
    # runner._write_ledger at call time, and execute_rollback calls it directly,
    # so patching runner._write_ledger intercepts every write during rollback.
    projection_held: list[bool] = []
    real_wl = runner._write_ledger

    def spy_wl(dd: Path, ledger: dict[str, Any]) -> None:
        parent = (ledger.get("jobs", {}) or {}).get(parent_id)
        if isinstance(parent, dict):
            states = parent.get("proposal_states", {}) or {}
            if states.get(pid) == "confirmed":
                projection_held.append(held["parent"])
        return real_wl(dd, ledger)

    monkeypatch.setattr(runner, "_write_ledger", spy_wl)

    result = review.execute_review_rollback(child_id, data_dir)

    # rollback succeeded and restored the proposal to confirmed
    assert result["success"], result
    assert result["data"]["state"] == "rolled_back"
    assert _ledger(data_dir)["jobs"][parent_id]["proposal_states"][pid] == "confirmed"

    # Behavioural guarantee: the projection write happened, and EVERY such write
    # occurred while the parent review lock was held (guarded, not racing).
    assert projection_held, "no projection write was captured"
    assert all(projection_held), (
        f"parent projection write happened outside the parent lock: {projection_held}"
    )


# ---------------------------------------------------------------------------
# Exact membership: projection uses child.proposal_ids, not parent's selection
# ---------------------------------------------------------------------------


def test_rollback_projection_uses_exact_child_membership(
    isolated_data_dir: Path, tmp_path: Path
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    parent_id, child_id, pid_a = _confirmed_run_child(data_dir, src, tmp_path)

    # Seed the parent so its "last selection" (selected_proposal_ids) is a
    # SUPERSET of what this child actually touched, and two phantom proposals
    # B, C are also "imported". A correct projection restores ONLY the child's
    # own proposal_ids (A); a projection that trusted the parent's last
    # selection would wrongly restore B, C too.
    ledger = _ledger(data_dir)
    parent = ledger["jobs"][parent_id]
    parent["proposal_states"] = {pid_a: "imported", "prop_B": "imported", "prop_C": "imported"}
    parent["selected_proposal_ids"] = [pid_a, "prop_B", "prop_C"]
    _save_ledger(data_dir, ledger)
    # child.proposal_ids stays [pid_a] (what THIS batch touched)

    result = review.execute_review_rollback(child_id, data_dir)
    assert result["success"], result

    states = _ledger(data_dir)["jobs"][parent_id]["proposal_states"]
    # Only the child's exact membership is restored to confirmed.
    assert states[pid_a] == "confirmed"
    assert states["prop_B"] == "imported"
    assert states["prop_C"] == "imported"
