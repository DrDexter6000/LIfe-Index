#!/usr/bin/env python3
"""Package-2 contract tests: streaming attachment transaction + crash reconciliation.

These are the **focused synthetic behavioral tests** for M7 package 2: the
bounded streaming + create-only publication of canonical journals and
attachments, manifest-guarded compensation, crash-window reconciliation, and
exact rollback — exercised through the public CLI surface (subprocess) and, for
fault-injection windows, the public in-process entry points under a per-test
``LIFE_INDEX_DATA_DIR``.

Package 2 scope:
- TOCTOU-safe copy (confirm-time precheck + copy-time streaming verification);
- create-only atomic publication (never overwrites), staging removed on every path;
- canonical journal transaction (current schema/version/topic + stored attachment
  authority; no source SHA/provenance in journal frontmatter; only selected
  attachments publish; fully-deselected proposal creates nothing);
- transaction/compensation (manifest-guarded; full -> retryable failure with no
  half-product; failed -> retain evidence + recovery_required; never mutates source);
- restart/crash reconciliation under per-parent lock (no-child, running-evidence,
  manifest-committed-before-ledger, committed-ledger-with-invalid/missing manifest,
  repeated status/run/rollback convergence);
- batch semantics (stale excluded while unaffected confirmed import; two
  independent batches from one parent independently + exactly rollbackable).

No real user data, network, AI/OCR/face/video/RAW, runtime/cloud, or new durable
authority. Synthetic source directories only.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import tools.ingest.review as review
from tests.contract.test_import_review_package1_contract import _make_jpeg_rich


# ---------------------------------------------------------------------------
# CLI invocation helpers (subprocess)
# ---------------------------------------------------------------------------


def _run_import(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "tools", "import", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        encoding="utf-8",
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise AssertionError(
            f"Expected JSON on stdout.\nstdout[:500]: {result.stdout[:500]}\n"
            f"stderr[:500]: {result.stderr[:500]}"
        ) from None


def _ok(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    return _payload(result)


def _err(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode != 0, f"expected non-zero exit, stdout: {result.stdout}"
    return _payload(result)


# ---------------------------------------------------------------------------
# Synthetic photo + plan helpers
# ---------------------------------------------------------------------------


def _make_jpeg(
    path: Path,
    *,
    color: tuple[int, int, int] = (10, 20, 30),
    date_original: str | None = "2024:06:15 10:30:00",
) -> Path:
    """A small synthetic JPEG with a naive EXIF capture date (resolves to confirmed)."""
    from PIL import Image

    img = Image.new("RGB", (8, 8), color)
    exif = Image.Exif()
    if date_original is not None:
        exif[36867] = date_original
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", exif=exif.tobytes() if date_original else None)
    return path


def _photo_plan(data_dir: Path, input_dir: Path) -> dict[str, Any]:
    return _ok(
        _run_import(
            data_dir, "plan", "--source", "media.photo_timeline",
            "--input", str(input_dir), "--json",
        )
    )["data"]


def _plan_file(tmp_path: Path, plan_data: dict[str, Any], name: str = "plan.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(plan_data), encoding="utf-8")
    return p


def _confirm(data_dir: Path, plan_data: dict[str, Any], src: Path, tmp_path: Path) -> dict[str, Any]:
    return _ok(_run_import(
        data_dir, "confirm", "--plan",
        str(_plan_file(tmp_path, plan_data, name=f"review_{plan_data['import_id']}.json")),
        "--source-root", str(src), "--json",
    ))["data"]


def _status(data_dir: Path, import_id: str) -> dict[str, Any]:
    return _ok(_run_import(data_dir, "status", "--import-id", import_id, "--json"))["data"]


def _run_batch(data_dir: Path, parent_id: str, src: Path) -> subprocess.CompletedProcess[str]:
    return _run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    )


def _run_batch_crashing_after_publish(
    data_dir: Path, parent_id: str, src: Path, artifact_kind: str
) -> subprocess.CompletedProcess[str]:
    """Run the public CLI and hard-crash immediately after one final hard link."""
    script = r"""
import os
import sys
import tools.ingest.review as review

kind = sys.argv[1]
parent_id = sys.argv[2]
source_root = sys.argv[3]
real_publish = review._publish_create_only

def crash_after_publish(staging_abs, target_abs):
    real_publish(staging_abs, target_abs)
    actual_kind = "journal" if target_abs.suffix.lower() == ".md" else "attachment"
    if actual_kind == kind:
        os._exit(91)

review._publish_create_only = crash_after_publish
sys.argv = [
    "life-index import",
    "run",
    "--import-id",
    parent_id,
    "--source-root",
    source_root,
    "--json",
]
from tools.ingest.__main__ import main
main()
"""
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", script, artifact_kind, parent_id, str(src)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        encoding="utf-8",
    )


def _ledger(data_dir: Path) -> dict[str, Any]:
    return json.loads(
        (data_dir / ".life-index" / "import-jobs" / "ledger.json").read_text("utf-8")
    )


def _save_ledger(data_dir: Path, ledger: dict[str, Any]) -> None:
    (data_dir / ".life-index" / "import-jobs" / "ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _manifest(data_dir: Path, child_id: str) -> dict[str, Any]:
    return json.loads(
        (data_dir / ".life-index" / "import-jobs" / child_id / "rollback-manifest.json")
        .read_text("utf-8")
    )


def _no_staging_leftovers(data_dir: Path) -> None:
    # The implementation publishes via ``_unique_staging``, which writes a
    # HIDDEN temp ``.{target}.staging-<rand>.tmp`` beside each target and
    # unlinks it on every path. Assert against that real hidden ``.staging-*.tmp``
    # naming (a loose ``*staging*`` glob is only a coincidental substring match
    # and could miss a leftover if the marker changed), plus a broad sweep so
    # nothing slips through on any base.
    real = sorted(data_dir.rglob(".*.staging-*.tmp"))
    broad = sorted(p for p in data_dir.rglob("*staging*"))
    leftover = sorted({*real, *broad})
    assert leftover == [], f"staging leftovers present: {[str(p) for p in leftover]}"


def _no_temp_replace_leftovers(data_dir: Path) -> None:
    # _atomic_write_json writes through a hidden ``.{target}.tmp-<rand>`` temp
    # beside each target and unlinks it on every path. os.walk lists hidden
    # files unconditionally (a leading-dot name is missed by ``*`` globs), so a
    # survivor temp proves a real half-write rather than a glob blind spot.
    leftovers: list[Path] = []
    for root, _dirs, files in os.walk(data_dir):
        for name in files:
            if name.startswith(".") and ".tmp-" in name:
                leftovers.append(Path(root) / name)
    assert leftovers == [], f"atomic-write temp leftovers: {[str(p) for p in leftovers]}"


# ===================================================================
# Selection: partial / all / deselected; unselected never published
# ===================================================================


def test_run_batch_partial_selection_publishes_only_selected(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # two photos same day -> one multi-attachment proposal
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6))
    plan = _photo_plan(data_dir, src)
    prop = plan["proposals"][0]
    assert len(prop["attachments"]) == 2
    kept = prop["attachments"][0]
    dropped = prop["attachments"][1]
    # partial selection: keep only the first attachment
    prop["attachments"] = [kept]
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    assert _run_batch(data_dir, parent_id, src).returncode == 0

    published_kept = data_dir / kept["target_rel_path"]
    dropped_target = data_dir / dropped["target_rel_path"]
    assert published_kept.exists()
    assert not dropped_target.exists()  # unselected attachment never published

    # the journal references exactly the one selected attachment
    from tools.lib.frontmatter import parse_frontmatter

    journal = data_dir / prop["journal"]["target_rel_path"]
    fm, _ = parse_frontmatter(journal.read_text("utf-8"))
    assert len(fm["attachments"]) == 1
    assert fm["attachments"][0]["filename"] == kept["target_rel_path"].split("/")[-1]
    _no_staging_leftovers(data_dir)


def test_run_batch_deselected_proposal_never_published(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "keep.jpg", color=(1, 2, 3))
    _make_jpeg(src / "drop.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    kept_prop = next(p for p in plan["proposals"] if p["journal"]["date"] == "2024-06-15")
    dropped_prop = next(p for p in plan["proposals"] if p["journal"]["date"] == "2024-07-01")
    # fully deselect the second-day proposal
    dropped_prop["attachments"] = []
    parent_id = plan["import_id"]
    res = _confirm(data_dir, plan, src, tmp_path)
    assert res["queue_counts"]["skipped"] == 1
    assert res["queue_counts"]["confirmed"] == 1

    assert _run_batch(data_dir, parent_id, src).returncode == 0

    # only the selected proposal produced a journal + attachment
    assert (data_dir / kept_prop["journal"]["target_rel_path"]).exists()
    assert (data_dir / kept_prop["attachments"][0]["target_rel_path"]).exists()
    # the deselected proposal created neither journal nor attachment
    assert not (data_dir / dropped_prop["journal"]["target_rel_path"]).exists()
    _no_staging_leftovers(data_dir)


# ===================================================================
# Stale detection: source deleted / changed after confirm (precheck gate)
# ===================================================================


def test_run_batch_stale_excluded_unaffected_confirmed_imports(tmp_path: Path) -> None:
    """A stale proposal is excluded while an unaffected confirmed proposal imports."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "ok.jpg", color=(1, 2, 3))
    _make_jpeg(src / "gone.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    ok_prop = next(p for p in plan["proposals"] if p["journal"]["date"] == "2024-06-15")
    stale_prop = next(p for p in plan["proposals"] if p["journal"]["date"] == "2024-07-01")
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # delete one source after confirm -> that proposal is stale at run time, but
    # the unaffected confirmed proposal is still runnable and imports.
    (src / "gone.jpg").unlink()

    run = _ok(_run_batch(data_dir, parent_id, src))["data"]
    assert run["state"] == "committed"
    parent = _ledger(data_dir)["jobs"][parent_id]
    assert parent["proposal_states"][stale_prop["proposal_id"]] == "stale"
    assert parent["proposal_states"][ok_prop["proposal_id"]] == "imported"
    # the unaffected proposal published its journal + attachment; the stale one did not
    assert (data_dir / ok_prop["journal"]["target_rel_path"]).exists()
    assert not (data_dir / stale_prop["journal"]["target_rel_path"]).exists()


def test_run_batch_source_changed_after_confirm_is_stale(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # mutate content after confirm -> stale (copy-time precheck rejects)
    (src / "shot.jpg").write_bytes(b"changed after confirm")

    res = _err(_run_batch(data_dir, parent_id, src))
    assert res["error"]["code"] == "IMPORT_NO_RUNNABLE_PROPOSALS"
    pid = plan["proposals"][0]["proposal_id"]
    assert _ledger(data_dir)["jobs"][parent_id]["proposal_states"][pid] == "stale"


# ===================================================================
# Copy-time gate: mutation during the streaming copy is rejected + compensated
# ===================================================================


class _MutatingReader:
    """Wraps an open source fp; appends extra bytes once so the streamed hash diverges."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._mutated = False

    def read(self, n: int) -> bytes:
        chunk = self._inner.read(n)
        if chunk and not self._mutated:
            chunk = chunk + b"\xcc\xdd\xee\xff"  # diverge hash + size from expected
            self._mutated = True
        return chunk


def test_run_batch_mutation_during_stream_copy_compensates(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    att = plan["proposals"][0]["attachments"][0]
    review.confirm_review(
        plan_path=str(_plan_file(tmp_path, plan, "p.json")),
        data_dir=data_dir, source_root=str(src),
    )

    source_file = src / "shot.jpg"
    before_bytes = source_file.read_bytes()
    before_mtime = source_file.stat().st_mtime_ns

    # Inject a mutation mid-stream: the streamed content diverges from the
    # confirmed hash -> the copy-time gate fires, nothing is published.
    real_drain = review._drain_source_to_staging

    def mutating_drain(src_fp: Any, dst_fp: Any, expected_sha: str, expected_size: int,
                       chunk_size: int = review._STREAM_CHUNK_SIZE) -> tuple[bool, str]:
        return real_drain(_MutatingReader(src_fp), dst_fp, expected_sha, expected_size, chunk_size)

    monkeypatch.setattr(review, "_drain_source_to_staging", mutating_drain)

    res = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert not res["success"]
    assert res["error"]["code"] == "IMPORT_WRITE_FAILURE"
    assert res["error"]["retryable"] is True  # fully compensated -> retryable

    # no final attachment, no journal, proposals restored to confirmed
    assert not (data_dir / att["target_rel_path"]).exists()
    assert not (data_dir / plan["proposals"][0]["journal"]["target_rel_path"]).exists()
    parent = _ledger(data_dir)["jobs"][parent_id]
    assert parent["proposal_states"][pid] == "confirmed"
    assert parent["active_child_id"] is None
    # source was never mutated by the import (the mutation was in the read stream only)
    assert source_file.read_bytes() == before_bytes
    assert source_file.stat().st_mtime_ns == before_mtime
    _no_staging_leftovers(data_dir)


# ===================================================================
# Create-only collision: existing target is never overwritten
# ===================================================================


def test_run_batch_create_only_collision_fails_and_compensates(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    att = plan["proposals"][0]["attachments"][0]
    _confirm(data_dir, plan, src, tmp_path)

    source_file = src / "shot.jpg"
    before_bytes = source_file.read_bytes()
    before_mtime = source_file.stat().st_mtime_ns

    # pre-create the canonical attachment target -> publish must collide (create-only)
    target = data_dir / att["target_rel_path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    collision_bytes = b"PRE-EXISTING COLLISION FILE"
    target.write_bytes(collision_bytes)

    res = _err(_run_batch(data_dir, parent_id, src))
    assert res["error"]["code"] == "IMPORT_WRITE_FAILURE"
    assert res["error"]["retryable"] is True

    # the existing target was never overwritten
    assert target.read_bytes() == collision_bytes
    # no journal was produced, proposals restored to confirmed
    assert not (data_dir / plan["proposals"][0]["journal"]["target_rel_path"]).exists()
    parent = _ledger(data_dir)["jobs"][parent_id]
    assert parent["proposal_states"][pid] == "confirmed"
    assert parent["active_child_id"] is None
    # source untouched
    assert source_file.read_bytes() == before_bytes
    assert source_file.stat().st_mtime_ns == before_mtime
    _no_staging_leftovers(data_dir)


# ===================================================================
# Mid-batch write failure: full compensation removes the half-product
# ===================================================================


def test_run_batch_mid_write_failure_fully_compensates(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pids = [p["proposal_id"] for p in plan["proposals"]]
    # proposal 0 publishes fully first; proposal 1 then fails mid-write.
    prop0 = plan["proposals"][0]
    prop0_att = prop0["attachments"][0]
    prop0_journal = prop0["journal"]["target_rel_path"]
    prop1_att_name = plan["proposals"][1]["attachments"][0]["target_rel_path"].split("/")[-1]
    review.confirm_review(
        plan_path=str(_plan_file(tmp_path, plan, "p.json")),
        data_dir=data_dir, source_root=str(src),
    )

    real_copy = review._stream_copy

    def failing_copy(source_abs: Path, target_abs: Path, expected_sha: str,
                     expected_size: int, chunk_size: int = review._STREAM_CHUNK_SIZE) -> tuple[bool, str]:
        if target_abs.name == prop1_att_name:
            return False, "simulated_write_failure"
        return real_copy(source_abs, target_abs, expected_sha, expected_size, chunk_size)

    monkeypatch.setattr(review, "_stream_copy", failing_copy)

    res = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert not res["success"]
    assert res["error"]["code"] == "IMPORT_WRITE_FAILURE"
    assert res["error"]["retryable"] is True  # full compensation succeeded

    # NO half-product: proposal 0's published attachment + journal were removed
    assert not (data_dir / prop0_att["target_rel_path"]).exists()
    assert not (data_dir / prop0_journal).exists()
    # both proposals restored to confirmed (re-runnable), no active child
    parent = _ledger(data_dir)["jobs"][parent_id]
    for pid in pids:
        assert parent["proposal_states"][pid] == "confirmed"
    assert parent["active_child_id"] is None
    assert parent["recovery_required"] is False
    # ONE durable recovery truth: the child job and its rollback manifest agree
    # on rolled_back (no diverged partially_committed child behind a rolled_back
    # manifest). The unfixed base leaves the child job diverged.
    child_id = next(
        jid for jid, j in _ledger(data_dir)["jobs"].items()
        if j.get("parent_review_job_id") == parent_id
    )
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "rolled_back"
    assert _manifest(data_dir, child_id)["state"] == "rolled_back"
    _no_staging_leftovers(data_dir)


def test_run_batch_mid_write_failure_child_and_manifest_converge_to_rolled_back(
    isolated_data_dir: Path, tmp_path: Path,
) -> None:
    """A fully compensated mid-write failure leaves ONE durable recovery truth.

    Forces a real mid-batch write failure WITHOUT monkeypatching the copy
    primitive (so it is behavioral on any base): proposal 0 publishes fully,
    then proposal 1's attachment collides create-only, so the batch fails with
    created evidence and reconciliation compensates it via ``execute_rollback``.

    After compensation the parent is cleanly retryable (confirmed, no active
    child, no recovery) AND the child job + rollback manifest agree on exactly
    one terminal state (``rolled_back``): no half-product and no diverged child
    job lingering behind a rolled_back manifest. Repeated status is a stable
    no-op. This is the focused contract for the stale-ledger overwrite.
    """
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pids = [p["proposal_id"] for p in plan["proposals"]]
    prop0 = plan["proposals"][0]
    prop1 = plan["proposals"][1]
    review.confirm_review(
        plan_path=str(_plan_file(tmp_path, plan, "p.json")),
        data_dir=data_dir, source_root=str(src),
    )

    # Pre-create proposal 1's attachment target so its create-only publish
    # collides AFTER proposal 0 has already published -> partially_committed
    # with proposal 0's files as durable created evidence.
    collision = data_dir / prop1["attachments"][0]["target_rel_path"]
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(b"PRE-EXISTING COLLISION")

    res = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert not res["success"]
    assert res["error"]["code"] == "IMPORT_WRITE_FAILURE"
    assert res["error"]["retryable"] is True  # fully compensated -> retryable

    # Parent is cleanly retryable.
    parent = _ledger(data_dir)["jobs"][parent_id]
    for pid in pids:
        assert parent["proposal_states"][pid] == "confirmed"
    assert parent["active_child_id"] is None
    assert parent["recovery_required"] is False

    # ONE durable recovery truth: the child job and its rollback manifest agree
    # on rolled_back. The unfixed base leaves the child job diverged
    # (partially_committed) behind a rolled_back manifest.
    child_id = next(
        jid for jid, j in _ledger(data_dir)["jobs"].items()
        if j.get("parent_review_job_id") == parent_id
    )
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "rolled_back"
    assert _manifest(data_dir, child_id)["state"] == "rolled_back"

    # No half-product survives: proposal 0's published attachment + journal were
    # compensated away, and the create-only collision file was never overwritten.
    assert not (data_dir / prop0["attachments"][0]["target_rel_path"]).exists()
    assert not (data_dir / prop0["journal"]["target_rel_path"]).exists()
    assert collision.read_bytes() == b"PRE-EXISTING COLLISION"
    _no_staging_leftovers(data_dir)

    # Repeated status/reconciliation is a stable no-op (convergence).
    snap1 = json.dumps(_ledger(data_dir)["jobs"], sort_keys=True)
    _status(data_dir, parent_id)
    snap2 = json.dumps(_ledger(data_dir)["jobs"], sort_keys=True)
    assert snap1 == snap2
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "rolled_back"


def test_run_batch_compensation_failure_requires_recovery(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    prop0_att_abs = data_dir / plan["proposals"][0]["attachments"][0]["target_rel_path"]
    prop1_att_name = plan["proposals"][1]["attachments"][0]["target_rel_path"].split("/")[-1]
    review.confirm_review(
        plan_path=str(_plan_file(tmp_path, plan, "p.json")),
        data_dir=data_dir, source_root=str(src),
    )

    real_copy = review._stream_copy
    corrupted = {"done": False}

    def corrupt_then_fail(source_abs: Path, target_abs: Path, expected_sha: str,
                          expected_size: int, chunk_size: int = review._STREAM_CHUNK_SIZE) -> tuple[bool, str]:
        # when proposal 1's attachment is about to publish, corrupt the already-
        # published proposal 0 attachment so the upcoming compensation cannot
        # match its recorded checksum -> compensation fails -> recovery_required.
        if target_abs.name == prop1_att_name and not corrupted["done"]:
            prop0_att_abs.write_bytes(b"CORRUPTED EVIDENCE")
            corrupted["done"] = True
            return False, "simulated_write_failure"
        return real_copy(source_abs, target_abs, expected_sha, expected_size, chunk_size)

    monkeypatch.setattr(review, "_stream_copy", corrupt_then_fail)

    res = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert not res["success"]
    assert res["error"]["code"] == "IMPORT_RECOVERY_REQUIRED"
    assert res["error"]["retryable"] is False  # fail closed

    # recovery_required surfaced, active child retained, evidence retained
    parent = _ledger(data_dir)["jobs"][parent_id]
    assert parent["recovery_required"] is True
    assert parent["active_child_id"] is not None
    assert prop0_att_abs.exists()  # corrupted artifact retained as evidence

    # convergence: a second status stays fail-closed (no further mutation)
    snap1 = json.dumps(_ledger(data_dir)["jobs"][parent_id], sort_keys=True)
    _status(data_dir, parent_id)
    snap2 = json.dumps(_ledger(data_dir)["jobs"][parent_id], sort_keys=True)
    assert snap1 == snap2
    assert _ledger(data_dir)["jobs"][parent_id]["recovery_required"] is True


# ===================================================================
# Windows transient manifest replace: first-run recovery, no half-products
# ===================================================================


def _transient_when_winerror_5_32(exc: BaseException) -> bool:
    """Behavioral stand-in for the production Windows-transient classifier.

    Confirms exactly an OSError carrying ``winerror`` 5/32 as the transient
    decision the production helper would make under ``os.name == "nt"``. Contract
    fault-injection tests patch this onto ``runner._is_windows_transient_replace_error``
    so they never depend on the host being Windows and run deterministically on
    Linux required CI; the real ``os.name`` + ``winerror`` semantics are proven by
    the unit direct classifier tests.
    """
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in (5, 32)


def test_review_run_windows_transient_manifest_replace_recovers_without_partial_outputs(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first Windows transient share/access lock on the child rollback-manifest
    ``os.replace`` is absorbed internally: the SAME first ``run_batch`` succeeds
    with complete Journal/Attachment outputs, readable manifest/ledger, no temp
    or staging half-file, and the source photo untouched.

    Fault injection (not a real file lock): the FIRST ``os.replace`` whose
    destination is the child ``rollback-manifest.json`` raises a Windows
    ``winerror=5`` OSError; every other replace (ledger, incremental manifest
    writes, the retry) delegates to the real ``os.replace``. The bounded retry
    inside ``runner._atomic_write_json`` absorbs exactly this one transient
    failure, so the run commits on the first attempt — no outer retry.

    The classifier is patched to treat only ``winerror`` 5/32 as transient, so
    the test does not depend on the host being Windows and runs deterministically
    on Linux required CI; the production ``os.name`` + ``winerror`` decision is
    proven by the unit direct classifier tests.
    """
    import tools.ingest.runner as runner

    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    source = _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    source_bytes = source.read_bytes()
    source_size = source.stat().st_size
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    source_mtime = source.stat().st_mtime_ns

    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal = plan["proposals"][0]
    journal_rel = proposal["journal"]["target_rel_path"]
    att_rel = proposal["attachments"][0]["target_rel_path"]
    review.confirm_review(
        plan_path=str(_plan_file(tmp_path, plan, "p.json")),
        data_dir=data_dir,
        source_root=str(src),
    )

    # Inject exactly one transient winerror=5 on the child rollback-manifest
    # target's first os.replace; everything else delegates to the real replace.
    real_replace = os.replace
    fault = {"fired": False}

    def transient_first_manifest_replace(src_path: Any, dst_path: Any) -> Any:
        if (
            os.path.basename(str(dst_path)) == "rollback-manifest.json"
            and "import-jobs" in str(dst_path)
            and not fault["fired"]
        ):
            fault["fired"] = True
            err = OSError("synthetic Windows transient sharing violation")
            err.winerror = 5
            raise err
        return real_replace(src_path, dst_path)

    monkeypatch.setattr(runner.os, "replace", transient_first_manifest_replace)
    # Treat only the injected winerror 5/32 as transient (host-agnostic: the
    # test no longer depends on os.name == "nt").
    monkeypatch.setattr(
        runner, "_is_windows_transient_replace_error", _transient_when_winerror_5_32
    )

    # The single first run_batch must succeed — the transient lock is absorbed
    # internally, NOT by an outer second run_batch.
    result = review.run_batch(parent_id, data_dir, source_root=str(src))

    assert result["success"], result
    assert result["data"]["state"] == "committed"
    child_id = result["data"]["import_id"]
    assert fault["fired"] is True  # the transient fault really fired exactly once

    # Journal + Attachment are fully present; the attachment carries source bytes.
    journal_abs = data_dir / journal_rel
    att_abs = data_dir / att_rel
    assert journal_abs.exists()
    assert att_abs.exists()
    assert att_abs.read_bytes() == source_bytes

    # Manifest + ledger are readable and agree on a clean committed state.
    manifest = _manifest(data_dir, child_id)
    assert manifest["state"] == "committed"
    ledger = _ledger(data_dir)
    assert ledger["jobs"][child_id]["state"] == "committed"
    assert ledger["jobs"][parent_id]["active_child_id"] is None

    # No temp / staging half-file anywhere under the data dir.
    _no_staging_leftovers(data_dir)
    _no_temp_replace_leftovers(data_dir)

    # Source photo is byte-for-byte untouched: bytes / hash / size / mtime_ns.
    assert source.read_bytes() == source_bytes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    assert source.stat().st_size == source_size
    assert source.stat().st_mtime_ns == source_mtime


def test_review_run_exhausted_windows_transient_manifest_replace_fully_compensates(
    isolated_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Windows transient share/access lock that does NOT clear within the bounded
    retry exhausts it cleanly: the SAME first ``run_batch`` returns the existing
    ``IMPORT_WRITE_FAILURE`` envelope (``retryable=True``), never a bare exception,
    and manifest-guarded compensation removes every half-product.

    The failure is injected at the child rollback-manifest write whose temp JSON
    already shows BOTH a published attachment and a published journal — that is the
    journal's ``_record_published_publication`` write, which happens AFTER both the
    attachment and the journal hard links already exist on disk. So compensation
    must remove two real published products, not bail before any product exists.
    Exactly three ``winerror=32`` faults are injected on that one ``os.replace``
    (the bounded retry's full attempt budget), after which the real ``os.replace``
    is restored so the compensation writes succeed. The classifier is patched to
    treat only ``winerror`` 5/32 as transient (host-agnostic; the production
    ``os.name`` decision is proven by the unit direct classifier tests).
    """
    import tools.ingest.runner as runner

    data_dir = isolated_data_dir
    src = tmp_path / "photos"
    source = _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    source_bytes = source.read_bytes()
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    source_size = source.stat().st_size
    source_mtime = source.stat().st_mtime_ns

    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal = plan["proposals"][0]
    pid = proposal["proposal_id"]
    journal_rel = proposal["journal"]["target_rel_path"]
    att_rel = proposal["attachments"][0]["target_rel_path"]
    review.confirm_review(
        plan_path=str(_plan_file(tmp_path, plan, "p.json")),
        data_dir=data_dir,
        source_root=str(src),
    )

    # Arm on the rollback-manifest write whose temp JSON already carries BOTH a
    # published attachment and a published journal (the journal's post-publish
    # manifest record). Once armed, inject exactly three winerror=32 faults on
    # that one replace (the full bounded-retry budget), then delegate every
    # later call (the compensation writes) to the real os.replace.
    real_replace = os.replace
    fault = {"armed": False, "attempts": 0}

    def exhausted_manifest_replace(src_path: Any, dst_path: Any) -> Any:
        if (
            os.path.basename(str(dst_path)) == "rollback-manifest.json"
            and not fault["armed"]
        ):
            try:
                payload = json.loads(Path(src_path).read_text("utf-8"))
            except (OSError, ValueError):
                payload = {}
            states: dict[str, Any] = {}
            for entry in payload.get("created_files") or []:
                if isinstance(entry, dict) and "kind" in entry:
                    states[entry["kind"]] = entry.get("publication_state")
            if states.get("attachment") == "published" and states.get("journal") == "published":
                fault["armed"] = True
        if fault["armed"] and fault["attempts"] < 3:
            fault["attempts"] += 1
            err = OSError("synthetic Windows transient sharing violation (exhausted)")
            err.winerror = 32
            raise err
        return real_replace(src_path, dst_path)

    monkeypatch.setattr(runner.os, "replace", exhausted_manifest_replace)
    monkeypatch.setattr(
        runner, "_is_windows_transient_replace_error", _transient_when_winerror_5_32
    )

    # The exhausted retry surfaces the existing failure envelope — NOT a bare
    # exception — with retryable=True (full compensation succeeded).
    result = review.run_batch(parent_id, data_dir, source_root=str(src))
    assert not result["success"], result
    assert result["error"]["code"] == "IMPORT_WRITE_FAILURE"
    assert result["error"]["retryable"] is True
    # exactly three transient fault attempts on the one manifest replace
    assert fault["armed"] is True
    assert fault["attempts"] == 3

    # No half-product: both the already-published attachment and journal were
    # compensated away to zero.
    assert not (data_dir / att_rel).exists()
    assert not (data_dir / journal_rel).exists()

    # Parent is cleanly retryable: proposal back to confirmed, no active child,
    # no recovery required.
    parent = _ledger(data_dir)["jobs"][parent_id]
    assert parent["proposal_states"][pid] == "confirmed"
    assert parent["active_child_id"] is None
    assert parent["recovery_required"] is False

    # ONE durable recovery truth: the child job and its rollback manifest agree
    # on rolled_back (no diverged partially_committed child behind a rolled_back
    # manifest).
    child_id = next(
        jid for jid, j in _ledger(data_dir)["jobs"].items()
        if j.get("parent_review_job_id") == parent_id
    )
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "rolled_back"
    assert _manifest(data_dir, child_id)["state"] == "rolled_back"

    # No atomic-write temp or staging half-file anywhere under the data dir.
    _no_staging_leftovers(data_dir)
    _no_temp_replace_leftovers(data_dir)

    # Source photo is byte-for-byte untouched: bytes / hash / size / mtime_ns.
    assert source.read_bytes() == source_bytes
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    assert source.stat().st_size == source_size
    assert source.stat().st_mtime_ns == source_mtime


@pytest.mark.parametrize("artifact_kind", ["attachment", "journal"])
def test_child_rollback_does_not_claim_success_for_post_publish_pre_manifest_crash(
    tmp_path: Path, artifact_kind: str
) -> None:
    """A hard crash after publish cannot leave an untracked owned survivor."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal = plan["proposals"][0]
    proposal_id = proposal["proposal_id"]
    attachment_abs = data_dir / proposal["attachments"][0]["target_rel_path"]
    journal_abs = data_dir / proposal["journal"]["target_rel_path"]
    _confirm(data_dir, plan, src, tmp_path)

    crashed = _run_batch_crashing_after_publish(
        data_dir, parent_id, src, artifact_kind
    )
    assert crashed.returncode == 91, (
        f"expected hard crash after {artifact_kind} publish; "
        f"stdout={crashed.stdout!r} stderr={crashed.stderr!r}"
    )
    assert attachment_abs.exists()
    if artifact_kind == "journal":
        assert journal_abs.exists()

    child_id = next(
        job_id
        for job_id, job in _ledger(data_dir)["jobs"].items()
        if job.get("parent_review_job_id") == parent_id
    )
    crash_manifest = _manifest(data_dir, child_id)
    crashed_entry = next(
        entry
        for entry in crash_manifest["created_files"]
        if entry["kind"] == artifact_kind
    )
    crashed_target = journal_abs if artifact_kind == "journal" else attachment_abs
    proof = crashed_entry["ownership_proof"]
    staging_abs = data_dir / proof["staging_rel_path"]
    assert crashed_entry["publication_state"] == "prepared"
    assert crashed_entry["sha256_after"].startswith("sha256:")
    assert crashed_entry["size_bytes"] == crashed_target.stat().st_size
    assert staging_abs.exists()
    assert os.path.samefile(staging_abs, crashed_target)

    status = _status(data_dir, parent_id)
    child = _ledger(data_dir)["jobs"][child_id]
    manifest = _manifest(data_dir, child_id)

    assert child["state"] == "rolled_back"
    assert manifest["state"] == "rolled_back"
    assert status["proposal_states"][proposal_id] == "confirmed"
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False
    assert not attachment_abs.exists()
    assert not journal_abs.exists()
    assert {
        entry["kind"] for entry in manifest["created_files"]
    } >= ({artifact_kind} if artifact_kind == "attachment" else {"attachment", "journal"})
    for entry in manifest["created_files"]:
        assert entry["ownership_proof"]["method"] == "hardlink_identity"
    _no_staging_leftovers(data_dir)


def test_child_rollback_preserves_racing_identical_non_owned_target(
    tmp_path: Path,
) -> None:
    """Checksum equality alone never authorizes deletion of a racing target."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    source = _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal = plan["proposals"][0]
    proposal_id = proposal["proposal_id"]
    target = data_dir / proposal["attachments"][0]["target_rel_path"]
    _confirm(data_dir, plan, src, tmp_path)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    identity_before = (target.stat().st_dev, target.stat().st_ino)
    result = _err(_run_batch(data_dir, parent_id, src))

    assert result["error"]["code"] == "IMPORT_WRITE_FAILURE"
    assert result["error"]["retryable"] is True
    assert target.exists()
    assert target.read_bytes() == source.read_bytes()
    assert (target.stat().st_dev, target.stat().st_ino) == identity_before
    status = _status(data_dir, parent_id)
    assert status["proposal_states"][proposal_id] == "confirmed"
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False
    child_id = next(
        job_id
        for job_id, job in _ledger(data_dir)["jobs"].items()
        if job.get("parent_review_job_id") == parent_id
    )
    manifest = _manifest(data_dir, child_id)
    assert manifest["state"] == "rolled_back"
    assert manifest["created_files"][0]["publication_state"] == "prepared"
    _no_staging_leftovers(data_dir)


def test_child_rollback_preserves_concurrent_journal_replacement_between_check_and_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A journal replaced after validation must survive with every sibling artifact."""
    import tools.ingest.runner as runner

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    manifest = _manifest(data_dir, child_id)
    journal_entry = next(
        entry for entry in manifest["created_files"] if entry["kind"] == "journal"
    )
    sibling_entry = next(
        entry for entry in manifest["created_files"] if entry["kind"] == "attachment"
    )
    journal_path = data_dir / journal_entry["rel_path"]
    sibling_path = data_dir / sibling_entry["rel_path"]
    replacement = b"concurrent editor replacement"
    real_mark_pending = runner.mark_pending
    replaced = False

    def replace_validated_journal(rel_path: str) -> None:
        nonlocal replaced
        if not replaced:
            replacement_path = journal_path.with_suffix(".replacement")
            replacement_path.write_bytes(replacement)
            os.replace(replacement_path, journal_path)
            replaced = True
        real_mark_pending(rel_path)

    monkeypatch.setattr(runner, "mark_pending", replace_validated_journal)

    result = review.execute_review_rollback(import_id=child_id, data_dir=data_dir)

    assert replaced is True
    assert result["success"] is False
    assert result["error"]["code"] == "IMPORT_ROLLBACK_CHECKSUM_MISMATCH"
    assert result["error"]["details"]["blocked_files"]
    assert journal_path.read_bytes() == replacement
    assert sibling_path.exists(), "final revalidation failure must precede every unlink"
    assert _ledger(data_dir)["jobs"][child_id]["state"] != "rolled_back"
    assert _status(data_dir, parent_id)["proposal_states"][proposal_id] != "confirmed"


def test_child_rollback_revalidates_prepared_staging_identity_before_any_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prepared staging replacement with identical bytes must fail closed."""
    import tools.ingest.runner as runner

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    crashed = _run_batch_crashing_after_publish(data_dir, parent_id, src, "journal")
    assert crashed.returncode == 91

    child_id = next(
        job_id
        for job_id, job in _ledger(data_dir)["jobs"].items()
        if job.get("parent_review_job_id") == parent_id
    )
    manifest = _manifest(data_dir, child_id)
    prepared = next(
        entry
        for entry in manifest["created_files"]
        if entry["kind"] == "journal" and entry["publication_state"] == "prepared"
    )
    staging_path = data_dir / prepared["ownership_proof"]["staging_rel_path"]
    target_paths = [
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    ]
    assert all(path.exists() for path in target_paths)
    original_staging_bytes = staging_path.read_bytes()
    real_mark_pending = runner.mark_pending
    replaced = False

    def replace_prepared_staging(rel_path: str) -> None:
        nonlocal replaced
        if not replaced:
            replacement_path = staging_path.with_suffix(".replacement")
            replacement_path.write_bytes(original_staging_bytes)
            os.replace(replacement_path, staging_path)
            replaced = True
        real_mark_pending(rel_path)

    monkeypatch.setattr(runner, "mark_pending", replace_prepared_staging)

    result = runner.execute_rollback(import_id=child_id, data_dir=data_dir)

    assert replaced is True
    assert result["success"] is False
    assert result["error"]["code"] == "IMPORT_ROLLBACK_CHECKSUM_MISMATCH"
    assert all(path.exists() for path in target_paths)
    assert staging_path.read_bytes() == original_staging_bytes
    assert _ledger(data_dir)["jobs"][child_id]["state"] != "rolled_back"


def test_child_rollback_journals_lock_timeout_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lock acquisition failure is retryable, path-safe, and mutation-free."""
    import tools.ingest.runner as runner
    from tools.lib.file_lock import LockTimeoutError, get_journals_lock_path

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]
    target_paths = [
        data_dir / entry["rel_path"]
        for entry in _manifest(data_dir, child_id)["created_files"]
        if entry.get("created_by_import") is True
    ]

    real_file_lock = runner.FileLock
    journals_lock_path = get_journals_lock_path()

    class TimedOutJournalsLock:
        def __init__(self, path: Path, timeout: float):
            self.path = Path(path)
            self.timeout = timeout
            self.delegate = real_file_lock(path, timeout=timeout)

        def acquire(self, blocking: bool = True) -> bool:
            if self.path != journals_lock_path:
                return self.delegate.acquire(blocking=blocking)
            assert blocking is True
            raise LockTimeoutError("C:\\private\\journals.lock", self.timeout)

        def release(self) -> None:
            self.delegate.release()

        def __enter__(self) -> "TimedOutJournalsLock":
            self.delegate.__enter__()
            return self

        def __exit__(self, *args: object) -> None:
            self.delegate.__exit__(*args)

    monkeypatch.setattr(runner, "FileLock", TimedOutJournalsLock)

    result = runner.execute_rollback(import_id=child_id, data_dir=data_dir)

    assert result["success"] is False
    assert result["error"]["code"] == "IMPORT_INTERNAL_ERROR"
    assert result["error"]["retryable"] is True
    assert result["error"]["details"] == {
        "import_id": child_id,
        "reason": "journals_lock_timeout",
    }
    assert "private" not in json.dumps(result)
    assert all(path.exists() for path in target_paths)
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "committed"


def test_child_rollback_interrupted_on_second_unlink_resumes_without_false_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial delete is durable recovery truth and the next rollback resumes."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    source = _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    source_before = source.read_bytes()
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]
    manifest = _manifest(data_dir, child_id)
    owned_targets = [
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    ]
    assert len(owned_targets) == 2
    assert all(path.exists() for path in owned_targets)

    real_unlink = Path.unlink
    attempted_targets: list[Path] = []

    def fail_second_owned_unlink(
        path: Path, missing_ok: bool = False
    ) -> None:
        if path in owned_targets:
            attempted_targets.append(path)
            if len(attempted_targets) == 2:
                raise OSError("synthetic second owned unlink interruption")
        real_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", fail_second_owned_unlink)
    caught: OSError | None = None
    interrupted: dict[str, Any] | None = None
    try:
        interrupted = review.execute_review_rollback(
            import_id=child_id, data_dir=data_dir
        )
    except OSError as exc:
        caught = exc
    monkeypatch.setattr(Path, "unlink", real_unlink)

    interrupted_ledger = _ledger(data_dir)
    interrupted_manifest = _manifest(data_dir, child_id)
    assert (
        caught,
        interrupted_ledger["jobs"][child_id]["state"],
        interrupted_manifest["state"],
    ) == (None, "rollback_in_progress", "rollback_in_progress")
    assert interrupted is not None
    assert interrupted["success"] is False
    assert interrupted["error"] == {
        "code": "IMPORT_ROLLBACK_INTERRUPTED",
        "message": "Rollback was interrupted while removing owned files.",
        "details": {
            "import_id": child_id,
            "reason": "filesystem_delete_failed",
            "deleted_count": 1,
        },
        "retryable": True,
    }
    assert not owned_targets[0].exists()
    assert owned_targets[1].exists()
    interrupted_status = _status(data_dir, parent_id)
    assert interrupted_status["proposal_states"][proposal_id] == "batching"
    assert interrupted_status["active_child_id"] == child_id
    assert interrupted_status["recovery_required"] is True
    interrupted_batch = next(
        item
        for item in interrupted_status["batches"]
        if item["import_id"] == child_id
    )
    assert interrupted_batch["state"] == "rollback_in_progress"
    assert interrupted_batch["rollback_available"] is True
    assert source.read_bytes() == source_before

    resumed = review.execute_review_rollback(import_id=child_id, data_dir=data_dir)

    assert resumed["success"] is True
    assert resumed["data"]["state"] == "rolled_back"
    assert not any(path.exists() for path in owned_targets)
    assert _manifest(data_dir, child_id)["state"] == "rolled_back"
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "rolled_back"
    final_status = _status(data_dir, parent_id)
    assert final_status["proposal_states"][proposal_id] == "confirmed"
    assert final_status["active_child_id"] is None
    assert final_status["recovery_required"] is False
    assert source.read_bytes() == source_before


@pytest.mark.parametrize(
    "rollback_state", ["rollback_in_progress", "rollback_failed"]
)
def test_status_recovers_orphaned_retryable_rollback_as_required_recovery(
    tmp_path: Path, rollback_state: str
) -> None:
    """Restart projects durable rollback intent instead of stale imported state."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    ledger = _ledger(data_dir)
    assert ledger["jobs"][parent_id]["active_child_id"] is None
    assert ledger["jobs"][parent_id]["proposal_states"][proposal_id] == "imported"
    ledger["jobs"][child_id]["state"] = rollback_state
    ledger["jobs"][child_id]["rollback_retryable"] = True
    _save_ledger(data_dir, ledger)
    manifest = _manifest(data_dir, child_id)
    manifest["state"] = rollback_state
    manifest["rollback_retryable"] = True
    _save_manifest(data_dir, child_id, manifest)

    status = _status(data_dir, parent_id)

    assert status["proposal_states"][proposal_id] == "batching"
    assert status["active_child_id"] == child_id
    assert status["recovery_required"] is True
    batch = next(item for item in status["batches"] if item["import_id"] == child_id)
    assert batch["state"] == rollback_state
    assert batch["rollback_available"] is True


def test_status_finishes_rolled_back_manifest_before_child_ledger_restart_window(
    tmp_path: Path,
) -> None:
    """A durable rolled-back manifest completes an interrupted ledger projection."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    manifest = _manifest(data_dir, child_id)
    owned_targets = [
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    ]
    for path in owned_targets:
        path.unlink()
    manifest["state"] = "rolled_back"
    manifest["rollback_retryable"] = False
    _save_manifest(data_dir, child_id, manifest)
    ledger = _ledger(data_dir)
    ledger["jobs"][child_id]["state"] = "rollback_in_progress"
    ledger["jobs"][child_id]["rollback_retryable"] = True
    _save_ledger(data_dir, ledger)

    status = _status(data_dir, parent_id)

    assert status["proposal_states"][proposal_id] == "confirmed"
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False
    durable_ledger = _ledger(data_dir)
    assert durable_ledger["jobs"][child_id]["state"] == "rolled_back"
    assert durable_ledger["jobs"][child_id]["rollback_retryable"] is False
    batch = next(item for item in status["batches"] if item["import_id"] == child_id)
    assert batch["state"] == "rolled_back"
    assert batch["rollback_available"] is False


def test_status_carries_manifest_rollback_intent_into_committed_child_ledger(
    tmp_path: Path,
) -> None:
    """Manifest-first intent remains executable if restart precedes ledger intent."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    ledger = _ledger(data_dir)
    assert ledger["jobs"][child_id]["state"] == "committed"
    manifest = _manifest(data_dir, child_id)
    manifest["state"] = "rollback_in_progress"
    manifest["rollback_retryable"] = True
    _save_manifest(data_dir, child_id, manifest)

    status = _status(data_dir, parent_id)

    assert status["proposal_states"][proposal_id] == "batching"
    assert status["active_child_id"] == child_id
    assert status["recovery_required"] is True
    durable_child = _ledger(data_dir)["jobs"][child_id]
    assert durable_child["state"] == "rollback_in_progress"
    assert durable_child["rollback_retryable"] is True
    batch = next(item for item in status["batches"] if item["import_id"] == child_id)
    assert batch["state"] == "rollback_in_progress"
    assert batch["rollback_available"] is True


def test_child_rollback_crash_after_child_finalization_converges_parent_on_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable parent marker closes the child-final/parent-stale crash window."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    committed_revision = _status(data_dir, parent_id)["queue_revision"]
    manifest = _manifest(data_dir, child_id)
    owned_targets = [
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    ]
    assert owned_targets
    assert all(path.exists() for path in owned_targets)

    def crash_before_parent_projection(
        _data_dir: Path,
        _parent_id: str,
        _proposal_ids: list[str],
    ) -> None:
        raise SystemExit("synthetic crash before final parent projection")

    monkeypatch.setattr(
        review,
        "_project_parent_after_child_rollback",
        crash_before_parent_projection,
    )

    with pytest.raises(
        SystemExit,
        match="synthetic crash before final parent projection",
    ):
        review.execute_review_rollback(import_id=child_id, data_dir=data_dir)

    crashed_ledger = _ledger(data_dir)
    crashed_parent = crashed_ledger["jobs"][parent_id]
    crashed_child = crashed_ledger["jobs"][child_id]
    assert crashed_child["state"] == "rolled_back"
    assert _manifest(data_dir, child_id)["state"] == "rolled_back"
    assert all(not path.exists() for path in owned_targets)
    assert crashed_parent["proposal_states"][proposal_id] == "batching"
    assert crashed_parent["active_child_id"] == child_id
    assert crashed_parent["recovery_required"] is True
    assert crashed_parent["rollback_started_from"] == "committed"
    assert crashed_parent["queue_revision"] == committed_revision + 1

    recovered = _status(data_dir, parent_id)
    assert recovered["proposal_states"][proposal_id] == "confirmed"
    assert recovered["active_child_id"] is None
    assert recovered["recovery_required"] is False
    assert recovered["queue_revision"] == committed_revision + 2
    assert "rollback_started_from" not in recovered
    assert "rollback_started_from" not in _ledger(data_dir)["jobs"][parent_id]
    batch = next(
        item for item in recovered["batches"] if item["import_id"] == child_id
    )
    assert batch["state"] == "rolled_back"
    assert batch["rollback_available"] is False

    stable = _status(data_dir, parent_id)
    assert stable == recovered
    assert stable["queue_revision"] == committed_revision + 2


def test_first_rollback_checksum_refusal_restores_imported_parent_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-delete refusal must not advertise partial rollback recovery."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    committed_revision = _status(data_dir, parent_id)["queue_revision"]
    child = _ledger(data_dir)["jobs"][child_id]
    manifest = _manifest(data_dir, child_id)
    owned_target = next(
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    )
    owned_target.write_bytes(owned_target.read_bytes() + b"-changed")

    refused = review.execute_review_rollback(
        import_id=child_id,
        data_dir=data_dir,
    )
    assert refused["success"] is False
    assert refused["error"]["code"] == "IMPORT_ROLLBACK_CHECKSUM_MISMATCH"

    refused_ledger = _ledger(data_dir)
    refused_parent = refused_ledger["jobs"][parent_id]
    refused_child = refused_ledger["jobs"][child_id]
    assert refused_child["state"] == "rollback_failed"
    assert refused_child["rollback_retryable"] is False
    assert owned_target.exists()
    assert refused_parent["proposal_states"] == {
        proposal_id_: "imported" for proposal_id_ in child["proposal_ids"]
    }
    assert refused_parent["active_child_id"] is None
    assert refused_parent["recovery_required"] is False
    assert "rollback_started_from" not in refused_parent
    assert refused_parent["queue_revision"] == committed_revision + 2

    stable = _status(data_dir, parent_id)
    assert stable["proposal_states"][proposal_id] == "imported"
    assert stable["active_child_id"] is None
    assert stable["recovery_required"] is False
    assert stable["queue_revision"] == committed_revision + 2


def test_first_rollback_refusal_crash_converges_imported_parent_on_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Restart distinguishes a no-delete refusal from partial rollback."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    committed_revision = _status(data_dir, parent_id)["queue_revision"]
    manifest = _manifest(data_dir, child_id)
    owned_targets = [
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    ]
    assert owned_targets
    assert all(path.exists() for path in owned_targets)
    owned_targets[0].write_bytes(owned_targets[0].read_bytes() + b"-changed")

    def crash_before_refusal_projection(
        _data_dir: Path,
        _parent_id: str,
        _child_id: str,
        _proposal_ids: list[str],
    ) -> None:
        raise SystemExit("synthetic crash before refusal parent projection")

    monkeypatch.setattr(
        review,
        "_restore_parent_after_predelete_rollback_refusal",
        crash_before_refusal_projection,
    )

    with pytest.raises(
        SystemExit,
        match="synthetic crash before refusal parent projection",
    ):
        review.execute_review_rollback(import_id=child_id, data_dir=data_dir)

    crashed_ledger = _ledger(data_dir)
    crashed_parent = crashed_ledger["jobs"][parent_id]
    crashed_child = crashed_ledger["jobs"][child_id]
    assert crashed_child["state"] == "rollback_failed"
    assert crashed_child["rollback_retryable"] is False
    assert _manifest(data_dir, child_id)["state"] == "rollback_failed"
    assert _manifest(data_dir, child_id)["rollback_retryable"] is False
    assert all(path.exists() for path in owned_targets)
    assert crashed_parent["proposal_states"][proposal_id] == "batching"
    assert crashed_parent["active_child_id"] == child_id
    assert crashed_parent["recovery_required"] is True
    assert crashed_parent["rollback_started_from"] == "committed"
    assert crashed_parent["queue_revision"] == committed_revision + 1

    recovered = _status(data_dir, parent_id)
    assert recovered["proposal_states"][proposal_id] == "imported"
    assert recovered["active_child_id"] is None
    assert recovered["recovery_required"] is False
    assert recovered["queue_revision"] == committed_revision + 2
    assert "rollback_started_from" not in recovered
    durable_parent = _ledger(data_dir)["jobs"][parent_id]
    assert "rollback_started_from" not in durable_parent
    batch = next(
        item for item in recovered["batches"] if item["import_id"] == child_id
    )
    assert batch["state"] == "rollback_failed"
    assert batch["rollback_available"] is False

    ledger_path = data_dir / ".life-index" / "import-jobs" / "ledger.json"
    settled_bytes = ledger_path.read_bytes()
    stable = _status(data_dir, parent_id)
    assert stable == recovered
    assert stable["queue_revision"] == committed_revision + 2
    assert ledger_path.read_bytes() == settled_bytes


def test_retry_checksum_refusal_keeps_parent_recovery_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refusal after durable rollback intent remains fail-closed."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    proposal_id = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]

    ledger = _ledger(data_dir)
    parent = ledger["jobs"][parent_id]
    child = ledger["jobs"][child_id]
    committed_revision = parent["queue_revision"]
    parent["proposal_states"][proposal_id] = "batching"
    parent["active_child_id"] = child_id
    parent["recovery_required"] = True
    parent["rollback_started_from"] = "committed"
    parent["queue_revision"] = committed_revision + 1
    child["state"] = "rollback_in_progress"
    child["rollback_retryable"] = True
    child["rollback_error"] = "synthetic interruption"
    _save_ledger(data_dir, ledger)

    manifest = _manifest(data_dir, child_id)
    manifest["state"] = "rollback_in_progress"
    manifest["rollback_retryable"] = True
    manifest["rollback_error"] = "synthetic interruption"
    _save_manifest(data_dir, child_id, manifest)
    owned_target = next(
        data_dir / entry["rel_path"]
        for entry in manifest["created_files"]
        if entry.get("created_by_import") is True
    )
    owned_target.write_bytes(owned_target.read_bytes() + b"-changed")

    refused = review.execute_review_rollback(
        import_id=child_id,
        data_dir=data_dir,
    )
    assert refused["success"] is False
    assert refused["error"]["code"] == "IMPORT_ROLLBACK_CHECKSUM_MISMATCH"

    refused_ledger = _ledger(data_dir)
    refused_parent = refused_ledger["jobs"][parent_id]
    refused_child = refused_ledger["jobs"][child_id]
    assert refused_child["state"] == "rollback_failed"
    assert refused_child["rollback_retryable"] is False
    assert refused_parent["proposal_states"][proposal_id] == "batching"
    assert refused_parent["active_child_id"] == child_id
    assert refused_parent["recovery_required"] is True
    assert refused_parent["rollback_started_from"] == "rollback_in_progress"
    assert refused_parent["queue_revision"] == committed_revision + 1


# ===================================================================
# Crash-window reconciliation (under the per-parent lock)
# ===================================================================


def test_crash_window_no_child_restores_confirmed(tmp_path: Path) -> None:
    """active_child_id set but child job + evidence absent -> restore confirmed + clear."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # seed the real crash window between the durable batching transition
    # (active_child_id + selected_proposal_ids set, proposals batching) and the
    # child batch job creation: the child job is missing, no manifest.
    ledger = _ledger(data_dir)
    ledger["jobs"][parent_id]["active_child_id"] = f"{parent_id}#batch-900000001"
    ledger["jobs"][parent_id]["selected_proposal_ids"] = [pid]
    ledger["jobs"][parent_id]["proposal_states"][pid] = "batching"
    _save_ledger(data_dir, ledger)

    status = _status(data_dir, parent_id)
    assert status["proposal_states"][pid] == "confirmed"
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False


def test_crash_window_running_with_evidence_compensates(tmp_path: Path) -> None:
    """A running child that left created evidence -> checksum-guarded compensation."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # seed a running child with a created-file manifest pointing at a real file
    child_id = f"{parent_id}#batch-900000001"
    att_rel = "attachments/2024/06/import_deadbeefdead.jpg"
    payload = b"published-then-crashed attachment"
    att_abs = data_dir / att_rel
    att_abs.parent.mkdir(parents=True, exist_ok=True)
    att_abs.write_bytes(payload)
    sha = "sha256:" + hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": "import_rollback_manifest.v1",
        "import_id": child_id,
        "parent_review_job_id": parent_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "state": "running",
        "created_files": [
            {"kind": "attachment", "rel_path": att_rel, "sha256_after": sha,
             "size_bytes": len(payload), "created_by_import": True}
        ],
        "preexisting_files": [],
        "errors": [],
    }
    mpath = data_dir / ".life-index" / "import-jobs" / child_id / "rollback-manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    ledger = _ledger(data_dir)
    ledger["jobs"][child_id] = {
        "kind": "batch", "parent_review_job_id": parent_id, "state": "running",
        "rollback_manifest_rel_path": f".life-index/import-jobs/{child_id}/rollback-manifest.json",
        "proposal_ids": [pid], "updated_at": "2026-01-01T00:00:00+00:00",
    }
    ledger["jobs"][parent_id]["active_child_id"] = child_id
    ledger["jobs"][parent_id]["proposal_states"][pid] = "batching"
    _save_ledger(data_dir, ledger)

    status = _status(data_dir, parent_id)
    # compensation removed the published artifact and restored confirmed
    assert not att_abs.exists()
    assert status["proposal_states"][pid] == "confirmed"
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False
    # ONE durable recovery truth via the status/reconcile path too: the child
    # job and its rollback manifest agree on rolled_back (the unfixed base
    # clobbers the child job back to the stale running/partial state).
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "rolled_back"
    assert _manifest(data_dir, child_id)["state"] == "rolled_back"


def test_crash_window_manifest_committed_before_ledger_projects_imported(tmp_path: Path) -> None:
    """A committed manifest whose ledger projection was interrupted -> project imported."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # run a real batch to a fully committed state (manifest + ledger + artifacts)
    run = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child_id = run["import_id"]
    assert _status(data_dir, parent_id)["proposal_states"][pid] == "imported"

    # rewind ONLY the ledger projection as if it crashed between manifest commit
    # and the child/parent ledger writes: manifest stays committed, child running,
    # parent still batching with the active child set.
    ledger = _ledger(data_dir)
    ledger["jobs"][child_id]["state"] = "running"
    ledger["jobs"][parent_id]["active_child_id"] = child_id
    ledger["jobs"][parent_id]["proposal_states"][pid] = "batching"
    ledger["jobs"][parent_id]["recovery_required"] = True
    ledger["jobs"][parent_id]["rollback_started_from"] = "committed"
    _save_ledger(data_dir, ledger)

    # reconcile trusts the durable committed manifest -> re-projects imported
    status = _status(data_dir, parent_id)
    assert status["proposal_states"][pid] == "imported"
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False
    assert _ledger(data_dir)["jobs"][child_id]["state"] == "committed"
    assert "rollback_started_from" not in _ledger(data_dir)["jobs"][parent_id]


def test_crash_window_committed_ledger_missing_manifest_fails_closed(tmp_path: Path) -> None:
    """child ledger committed + active, but manifest missing -> fail closed."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)

    child_id = f"{parent_id}#batch-900000001"
    ledger = _ledger(data_dir)
    ledger["jobs"][child_id] = {
        "kind": "batch", "parent_review_job_id": parent_id, "state": "committed",
        "rollback_manifest_rel_path": f".life-index/import-jobs/{child_id}/rollback-manifest.json",
        "proposal_ids": [pid], "updated_at": "2026-01-01T00:00:00+00:00",
    }
    ledger["jobs"][parent_id]["active_child_id"] = child_id
    ledger["jobs"][parent_id]["proposal_states"][pid] = "batching"
    ledger["jobs"][parent_id]["recovery_required"] = True
    ledger["jobs"][parent_id]["rollback_started_from"] = "committed"
    _save_ledger(data_dir, ledger)
    # NOTE: deliberately no manifest on disk for child_id.

    status = _status(data_dir, parent_id)
    assert status["recovery_required"] is True
    assert status["active_child_id"] == child_id  # retained, fail closed
    assert status["proposal_states"][pid] == "batching"  # NOT projected imported
    assert _ledger(data_dir)["jobs"][parent_id]["rollback_started_from"] == "committed"


def test_crash_window_committed_ledger_invalid_manifest_fails_closed(tmp_path: Path) -> None:
    """child ledger committed + manifest present but artifact hash mismatches -> fail closed."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # build a committed manifest whose recorded hash does NOT match the artifact
    child_id = f"{parent_id}#batch-900000001"
    att_rel = "attachments/2024/06/import_deadbeefdead.jpg"
    att_abs = data_dir / att_rel
    att_abs.parent.mkdir(parents=True, exist_ok=True)
    att_abs.write_bytes(b"actual content")
    manifest = {
        "schema_version": "import_rollback_manifest.v1",
        "import_id": child_id, "parent_review_job_id": parent_id,
        "created_at": "2026-01-01T00:00:00+00:00", "state": "committed",
        "created_files": [
            {"kind": "attachment", "rel_path": att_rel,
             "sha256_after": "sha256:" + "0" * 64,  # wrong hash
             "size_bytes": len(b"actual content"), "created_by_import": True}
        ],
        "preexisting_files": [], "errors": [],
    }
    mpath = data_dir / ".life-index" / "import-jobs" / child_id / "rollback-manifest.json"
    mpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.write_text(json.dumps(manifest), encoding="utf-8")

    ledger = _ledger(data_dir)
    ledger["jobs"][child_id] = {
        "kind": "batch", "parent_review_job_id": parent_id, "state": "committed",
        "rollback_manifest_rel_path": f".life-index/import-jobs/{child_id}/rollback-manifest.json",
        "proposal_ids": [pid], "updated_at": "2026-01-01T00:00:00+00:00",
    }
    ledger["jobs"][parent_id]["active_child_id"] = child_id
    ledger["jobs"][parent_id]["proposal_states"][pid] = "batching"
    _save_ledger(data_dir, ledger)

    status = _status(data_dir, parent_id)
    assert status["recovery_required"] is True
    assert status["proposal_states"][pid] == "batching"  # never projected imported


# ===================================================================
# Convergence: repeated status / run / rollback are no-ops once settled
# ===================================================================


def test_repeated_status_run_rollback_converges(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pid = plan["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan, src, tmp_path)

    run = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child_id = run["import_id"]

    # status is stable across repeated calls (convergence, no further mutation)
    s1 = _status(data_dir, parent_id)
    snap1 = json.dumps(_ledger(data_dir)["jobs"][parent_id], sort_keys=True)
    s2 = _status(data_dir, parent_id)
    snap2 = json.dumps(_ledger(data_dir)["jobs"][parent_id], sort_keys=True)
    assert s1 == s2
    assert snap1 == snap2
    assert s1["proposal_states"][pid] == "imported"

    # a re-run is a no-op (nothing confirmed left to run)
    rerun = _err(_run_batch(data_dir, parent_id, src))
    assert rerun["error"]["code"] == "IMPORT_NO_RUNNABLE_PROPOSALS"

    # rollback is idempotent: first rolls back, second is a no-op
    rb1 = _ok(_run_import(data_dir, "rollback", "--import-id", child_id, "--json"))["data"]
    assert rb1["state"] == "rolled_back"
    rb2 = _ok(_run_import(data_dir, "rollback", "--import-id", child_id, "--json"))["data"]
    assert rb2["state"] == "rolled_back"
    assert rb2["deleted_count"] == 0  # second rollback deleted nothing

    # proposal restored to confirmed exactly once
    assert _status(data_dir, parent_id)["proposal_states"][pid] == "confirmed"


# ===================================================================
# Two independent batches from one parent: independently + exactly rollbackable
# ===================================================================


def test_two_independent_batches_exact_rollback(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pids = sorted(p["proposal_id"] for p in plan["proposals"])
    _confirm(data_dir, plan, src, tmp_path)

    # child 1: import both proposals
    run1 = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child1 = run1["import_id"]
    assert sorted(_ledger(data_dir)["jobs"][child1]["proposal_ids"]) == pids

    # rollback child 1 -> both restored to confirmed, both artifacts removed
    rb1 = _ok(_run_import(data_dir, "rollback", "--import-id", child1, "--json"))["data"]
    assert rb1["deleted_count"] >= 2
    assert _manifest(data_dir, child1)["state"] == "rolled_back"
    child1_manifest_after_rollback = _manifest(data_dir, child1)
    for prop in plan["proposals"]:
        assert not (data_dir / prop["journal"]["target_rel_path"]).exists()
    states = _status(data_dir, parent_id)["proposal_states"]
    assert all(states[p] == "confirmed" for p in pids)

    # child 2: re-import both proposals (independent batch, monotonic id)
    run2 = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child2 = run2["import_id"]
    assert child2 != child1
    assert int(child2.rsplit("#batch-", 1)[1]) > int(child1.rsplit("#batch-", 1)[1])

    # rolling back child 2 restores exactly child 2's membership and does NOT
    # touch child 1's already-rolled-back manifest.
    _ok(_run_import(data_dir, "rollback", "--import-id", child2, "--json"))
    states = _status(data_dir, parent_id)["proposal_states"]
    assert all(states[p] == "confirmed" for p in pids)
    # child 1 manifest is untouched by child 2's rollback (byte-identical)
    assert _manifest(data_dir, child1) == child1_manifest_after_rollback
    for prop in plan["proposals"]:
        assert not (data_dir / prop["journal"]["target_rel_path"]).exists()


# ===================================================================
# Source immutability + canonical journal parsing + manifest evidence
# ===================================================================


def test_source_hash_and_mtime_unchanged_after_run_and_after_failure(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    snaps = {name: ((src / name).read_bytes(), (src / name).stat().st_mtime_ns)
             for name in ("a.jpg", "b.jpg")}

    # successful run: sources untouched
    assert _run_batch(data_dir, parent_id, src).returncode == 0
    for name, (b, m) in snaps.items():
        assert (src / name).read_bytes() == b
        assert (src / name).stat().st_mtime_ns == m

    # roll back, then force a create-only collision failure: sources still untouched
    child = _ledger(data_dir)["jobs"][parent_id]["active_child_id"]
    # (active_child is already None after a committed run; find the last child)
    last_child = [j for j, v in _ledger(data_dir)["jobs"].items()
                  if v.get("parent_review_job_id") == parent_id and v.get("state") == "committed"][0]
    _ok(_run_import(data_dir, "rollback", "--import-id", last_child, "--json"))

    # pre-create the first proposal's attachment target to force a collision
    collision = data_dir / plan["proposals"][0]["attachments"][0]["target_rel_path"]
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(b"COLLISION")
    _err(_run_batch(data_dir, parent_id, src))
    for name, (b, m) in snaps.items():
        assert (src / name).read_bytes() == b
        assert (src / name).stat().st_mtime_ns == m


def test_imported_journal_parses_canonical_frontmatter_multi_attachment(tmp_path: Path) -> None:
    import posixpath

    from tools.lib.frontmatter import parse_frontmatter

    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # multi-photo proposal: two photos same day -> one journal with 2 attachments
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6))
    plan = _photo_plan(data_dir, src)
    assert len(plan["proposals"]) == 1
    prop = plan["proposals"][0]
    assert len(prop["attachments"]) == 2
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    assert _run_batch(data_dir, parent_id, src).returncode == 0

    journal_path = data_dir / prop["journal"]["target_rel_path"]
    fm, body = parse_frontmatter(journal_path.read_text("utf-8"))
    assert fm["schema_version"] == 3
    assert fm["topic"] == ["life"]
    attachments = fm["attachments"]
    assert isinstance(attachments, list) and len(attachments) == 2
    journal_rel = prop["journal"]["target_rel_path"]
    published_bytes = {}
    for att_entry, att in zip(attachments, prop["attachments"]):
        # canonical 7-key stored attachment schema; no source SHA/provenance
        assert set(att_entry.keys()) == {
            "filename", "rel_path", "description", "original_name",
            "auto_detected", "content_type", "size",
        }
        assert att_entry["filename"] == posixpath.basename(att["target_rel_path"])
        expected_rel = posixpath.relpath(
            att["target_rel_path"], start=posixpath.dirname(journal_rel)
        )
        assert att_entry["rel_path"] == expected_rel
        assert att_entry["rel_path"].startswith("../../../attachments/")
        assert att_entry["original_name"] == posixpath.basename(att["source_rel_path"])
        assert att_entry["auto_detected"] is False
        assert att_entry["content_type"] == att["media_type"]
        assert att_entry["size"] == att["size_bytes"]
        # the attachment resolves through the journal-relative rel_path and opens
        resolved = (journal_path.parent / att_entry["rel_path"]).resolve()
        published = (data_dir / att["target_rel_path"]).resolve()
        assert resolved == published
        published_bytes[att["attachment_id"]] = resolved.read_bytes()
    # no source SHA anywhere in the journal frontmatter text
    assert "source_sha256" not in journal_path.read_text("utf-8")
    # both distinct attachments published with their real source bytes
    assert len(set(published_bytes.values())) == 2


def test_manifest_records_hashes_and_sizes(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    run = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child_id = run["import_id"]

    manifest = _manifest(data_dir, child_id)
    assert manifest["state"] == "committed"
    for entry in manifest["created_files"]:
        if not entry.get("created_by_import"):
            continue
        published = data_dir / entry["rel_path"]
        assert published.exists()
        assert entry["sha256_after"] == "sha256:" + hashlib.sha256(published.read_bytes()).hexdigest()
        assert entry["size_bytes"] == published.stat().st_size


def test_no_staging_leftovers_success_and_failure(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # success: no staging leftovers
    assert _run_batch(data_dir, parent_id, src).returncode == 0
    _no_staging_leftovers(data_dir)

    # roll back to make the proposal runnable again, then force a collision failure
    last_child = [j for j, v in _ledger(data_dir)["jobs"].items()
                  if v.get("parent_review_job_id") == parent_id and v.get("state") == "committed"][0]
    _ok(_run_import(data_dir, "rollback", "--import-id", last_child, "--json"))
    collision = data_dir / plan["proposals"][0]["attachments"][0]["target_rel_path"]
    collision.parent.mkdir(parents=True, exist_ok=True)
    collision.write_bytes(b"COLLISION")
    _err(_run_batch(data_dir, parent_id, src))
    _no_staging_leftovers(data_dir)


# ===================================================================
# Bounded streaming at scale: a larger synthetic file imports incrementally
# ===================================================================


def test_larger_synthetic_file_streams_and_publishes(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # A JPEG larger than the streaming chunk window (64 KiB) so the bounded copy
    # actually iterates, without relying on memory profiling.
    from PIL import Image

    big = src / "big.jpg"
    big.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (400, 400))
    # fill with varied content so JPEG compression stays well above 64 KiB
    img.putdata([(i % 256, (i * 3) % 256, (i * 7) % 256) for i in range(400 * 400)])
    exif = Image.Exif()
    exif[36867] = "2024:06:15 10:30:00"  # DateTimeOriginal -> resolves to confirmed
    img.save(big, format="JPEG", quality=95, exif=exif.tobytes())
    assert big.stat().st_size > review._STREAM_CHUNK_SIZE

    plan = _photo_plan(data_dir, src)
    assert plan["source"]["record_count"] == 1
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    assert _run_batch(data_dir, parent_id, src).returncode == 0

    att = plan["proposals"][0]["attachments"][0]
    published = data_dir / att["target_rel_path"]
    assert published.exists()
    assert published.stat().st_size == big.stat().st_size
    assert published.read_bytes() == big.read_bytes()
    _no_staging_leftovers(data_dir)


# ===================================================================
# Durable child-batch discovery on parent status (additive ``batches``)
#
# After a successful batch import and a GUI/backend restart (simulated by a
# fresh CLI subprocess), a parent review job's ``import status`` must expose
# its durable child batch ids derived from the existing import ledger — never
# cached by the GUI as a second truth. This is an additive parent-status
# projection: ledger-derived, restart-safe, locator-free, the only GUI source
# for rollback discovery.
# ===================================================================

# The only safe, locator-free keys a parent status may carry per child batch.
# ``rollback_manifest_rel_path`` / data-dir / source / journal paths / manifest
# contents must never be projected.
_ALLOWED_BATCH_KEYS = frozenset(
    {
        "import_id",
        "state",
        "proposal_ids",
        "proposal_count",
        "created_at",
        "updated_at",
        "rollback_available",
    }
)


def test_parent_status_exposes_durable_committed_batch_after_restart(
    tmp_path: Path,
) -> None:
    """A committed child batch is discoverable on parent status from a fresh CLI
    process; ``batches[0].import_id`` is the durable ``#batch-1`` child and
    ``rollback_available`` is true."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # commit a child batch (durable id carries the verbatim ``#``)
    run = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child_id = run["import_id"]
    assert child_id == f"{parent_id}#batch-1"

    # fresh CLI process (separate subprocess == restart): parent status exposes
    # the durable batch list derived from the ledger.
    status = _status(data_dir, parent_id)
    assert "batches" in status
    batches = status["batches"]
    assert len(batches) == 1
    b = batches[0]
    assert b["import_id"] == child_id  # verbatim ``#`` preserved
    assert b["state"] == "committed"
    assert b["rollback_available"] is True
    assert set(b.keys()) == _ALLOWED_BATCH_KEYS


def test_parent_status_batch_rolled_back_not_rollback_available(
    tmp_path: Path,
) -> None:
    """After rolling a child back, a fresh parent status still lists it with
    state ``rolled_back`` and ``rollback_available`` false."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    run = _ok(_run_batch(data_dir, parent_id, src))["data"]
    child_id = run["import_id"]
    assert _status(data_dir, parent_id)["batches"][0]["rollback_available"] is True

    # roll the child back, then a fresh parent status still lists it.
    _ok(_run_import(data_dir, "rollback", "--import-id", child_id, "--json"))
    status = _status(data_dir, parent_id)
    batches = status["batches"]
    assert len(batches) == 1
    assert batches[0]["import_id"] == child_id
    assert batches[0]["state"] == "rolled_back"
    assert batches[0]["rollback_available"] is False


def test_parent_status_batches_sort_numeric_and_preserve_membership(
    tmp_path: Path,
) -> None:
    """Two batches from one parent sort oldest/lowest numeric first and each
    preserves its exact proposal_ids membership."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    pids = [p["proposal_id"] for p in plan["proposals"]]
    _confirm(data_dir, plan, src, tmp_path)

    # batch 1 imports both proposals
    child1 = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]
    assert child1 == f"{parent_id}#batch-1"
    # rollback batch 1 -> both restored to confirmed (re-runnable)
    _ok(_run_import(data_dir, "rollback", "--import-id", child1, "--json"))
    # batch 2 re-imports both proposals (monotonic id)
    child2 = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]
    assert child2 == f"{parent_id}#batch-2"

    status = _status(data_dir, parent_id)
    batches = status["batches"]
    # deterministic ordering: oldest/lowest numeric sequence first
    assert [b["import_id"] for b in batches] == [child1, child2]
    # each batch preserves its exact proposal membership
    assert sorted(batches[0]["proposal_ids"]) == sorted(pids)
    assert sorted(batches[1]["proposal_ids"]) == sorted(pids)
    assert batches[0]["proposal_count"] == len(pids)
    assert batches[1]["proposal_count"] == len(pids)
    # batch1 rolled back -> not available; batch2 committed -> available
    assert batches[0]["state"] == "rolled_back"
    assert batches[0]["rollback_available"] is False
    assert batches[1]["state"] == "committed"
    assert batches[1]["rollback_available"] is True


def test_parent_status_batches_repeated_read_is_no_write(tmp_path: Path) -> None:
    """Repeated parent status reads after convergence are stable no-write: same
    batches projection, same queue_revision, byte-identical ledger."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    _ok(_run_batch(data_dir, parent_id, src))

    # first read ensures convergence is persisted; snapshot afterwards
    s1 = _status(data_dir, parent_id)
    q1 = s1["queue_revision"]
    batches1 = json.dumps(s1["batches"], sort_keys=True)
    ledger_after_first = _ledger(data_dir)

    # repeated read: deriving batches must not mutate / bump / rewrite
    s2 = _status(data_dir, parent_id)
    assert s2["queue_revision"] == q1
    assert json.dumps(s2["batches"], sort_keys=True) == batches1
    assert _ledger(data_dir) == ledger_after_first


def test_parent_status_batches_projection_is_locator_free(tmp_path: Path) -> None:
    """The batches projection carries only safe keys and never leaks a rollback
    manifest path, data-dir / source / journal path, or manifest contents."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    _ok(_run_batch(data_dir, parent_id, src))

    batches = _status(data_dir, parent_id)["batches"]
    blob = json.dumps(batches)
    forbidden = (
        "rollback_manifest_rel_path",
        "rollback-manifest",
        "created_files",
        "preexisting_files",
        "sha256_after",
        "source_rel_path",
        "target_rel_path",
        "Journals/",
        "attachments/",
        "import-jobs",
        str(data_dir),
        str(src),
    )
    for token in forbidden:
        assert token not in blob, f"forbidden locator/manifest token leaked: {token!r}"
    for b in batches:
        assert set(b.keys()) == _ALLOWED_BATCH_KEYS


def test_parent_status_batches_legacy_child_missing_created_at(tmp_path: Path) -> None:
    """A legacy child batch entry missing ``created_at`` remains readable; the
    projection falls back to ``updated_at`` (or null) without breaking status."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)

    # a newly created child batch carries created_at
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]
    assert "created_at" in _ledger(data_dir)["jobs"][child_id]

    # simulate a legacy entry predating the field by stripping created_at
    ledger = _ledger(data_dir)
    updated_at = ledger["jobs"][child_id]["updated_at"]
    ledger["jobs"][child_id].pop("created_at", None)
    _save_ledger(data_dir, ledger)

    status = _status(data_dir, parent_id)
    b = status["batches"][0]
    assert b["import_id"] == child_id
    # legacy child: created_at falls back to updated_at (a string), not null
    assert b["created_at"] == updated_at
    assert isinstance(b["created_at"], str)
    # the committed manifest is still authoritative -> still rollback_available
    assert b["rollback_available"] is True

    # a legacy child with NEITHER created_at nor updated_at falls back to null
    ledger = _ledger(data_dir)
    ledger["jobs"][child_id].pop("updated_at", None)
    _save_ledger(data_dir, ledger)
    status2 = _status(data_dir, parent_id)
    assert status2["batches"][0]["created_at"] is None


# ===================================================================
# Fail-closed rollback_available: a malformed / wrongly-linked committed
# rollback manifest must NOT be advertised as a safe rollback.
#
# ``batches[].rollback_available`` is the GUI's sole signal that a child
# batch can be safely rolled back. A committed child ledger plus a manifest
# whose ``state == "committed"`` is necessary but NOT sufficient: status
# must additionally fail closed when the manifest is malformed or wrongly
# linked (wrong/missing schema_version, wrong import_id, wrong
# parent_review_job_id, created_files not a list) so the GUI never falsely
# advertises rollback over a corrupted / mis-linked manifest. Status never
# re-hashes user artifacts for this — it is a lightweight structural + link
# check only. The child stays discoverable either way; only the rollback
# advertisement fails closed.
# ===================================================================


def _save_manifest(data_dir: Path, child_id: str, manifest: dict[str, Any]) -> None:
    (data_dir / ".life-index" / "import-jobs" / child_id / "rollback-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


def _committed_batch(tmp_path: Path) -> tuple[Path, str, str]:
    """Build a real committed, settled child batch from one synthetic photo.

    Returns ``(data_dir, parent_id, child_id)``. The child ledger is
    ``committed``, there is no active child, and its rollback manifest is a
    valid committed manifest (so the baseline ``rollback_available`` is True).
    """
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["import_id"]
    _confirm(data_dir, plan, src, tmp_path)
    child_id = _ok(_run_batch(data_dir, parent_id, src))["data"]["import_id"]
    assert child_id == f"{parent_id}#batch-1"
    return data_dir, parent_id, child_id


def _only_batch(status: dict[str, Any]) -> dict[str, Any]:
    batches = status["batches"]
    assert len(batches) == 1, f"expected exactly one batch, got {len(batches)}"
    return batches[0]


def test_parent_status_correct_committed_manifest_is_rollback_available(
    tmp_path: Path,
) -> None:
    """Baseline: a correctly linked committed manifest stays rollback_available."""
    data_dir, parent_id, child_id = _committed_batch(tmp_path)

    # untouched valid committed manifest -> still advertised as available
    b = _only_batch(_status(data_dir, parent_id))
    assert b["import_id"] == child_id
    assert b["state"] == "committed"
    assert b["rollback_available"] is True


@pytest.mark.parametrize(
    "mutate, label",
    [
        (lambda m: m.update(schema_version="import_rollback_manifest.v0"), "wrong_schema_version"),
        (lambda m: m.pop("schema_version", None), "missing_schema_version"),
        (lambda m: m.update(import_id="<wrong-import-id>"), "wrong_import_id"),
        (lambda m: m.update(parent_review_job_id="<wrong-parent-id>"), "wrong_parent_review_job_id"),
        (lambda m: m.update(created_files={"not": "a list"}), "created_files_not_a_list"),
    ],
)
def test_parent_status_malformed_manifest_fails_closed_rollback_available(
    tmp_path: Path, mutate: Any, label: str
) -> None:
    """A committed child with a malformed / wrongly-linked manifest stays
    discoverable but reports ``rollback_available=False`` (status fails closed).

    Starts from a real committed child and mutates ONLY the on-disk rollback
    manifest JSON to each invalid shape; the child ledger stays ``committed`` so
    the batch remains discoverable. ``parent_id`` is never inferred from the
    child id string — it is the real review job id.
    """
    data_dir, parent_id, child_id = _committed_batch(tmp_path)

    # baseline: the correct manifest is advertised as available
    assert _only_batch(_status(data_dir, parent_id))["rollback_available"] is True

    # mutate ONLY the on-disk rollback manifest to the invalid shape (the child
    # ledger is left committed so the batch stays discoverable).
    manifest = _manifest(data_dir, child_id)
    assert manifest["state"] == "committed"
    mutate(manifest)
    _save_manifest(data_dir, child_id, manifest)

    # fresh CLI process (separate subprocess == restart): the child is still
    # discoverable, but rollback is NOT advertised over the malformed manifest.
    b = _only_batch(_status(data_dir, parent_id))
    assert b["import_id"] == child_id
    assert b["state"] == "committed"  # ledger state unchanged -> discoverable
    assert b["rollback_available"] is False, f"expected fail-closed for {label}"
