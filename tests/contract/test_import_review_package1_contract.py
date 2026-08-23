#!/usr/bin/env python3
"""Package-1 contract tests: recoverable review queue + date/dedup/state authority.

These are the **focused synthetic behavioral tests** for M7 package 1. They assert
public CLI envelopes / persisted state (not only helpers), use synthetic source
directories + a tmp ``LIFE_INDEX_DATA_DIR``, and touch no real data, network, AI,
or runtime/cloud.

Package 1 scope: the recoverable review queue substrate — date authority (no
1970 sentinel, explicit ``date_resolution``), scan dedup authority (committed +
confirmed/batching/imported SHAs), state authority (merge / no-downgrade /
reconciliation), and child-batch identity substrate (monotonic ids + exact
``proposal_ids``). Attachment transaction streaming / canonical journal
publication mechanics belong to package 2 and are not exercised for new behavior
here.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

ENVELOPE_SCHEMA_VERSION = "import_job.v1"


# ---------------------------------------------------------------------------
# CLI invocation helpers
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
# Synthetic JPEG helpers
# ---------------------------------------------------------------------------


def _make_jpeg(
    path: Path,
    *,
    color: tuple[int, int, int] = (10, 20, 30),
    date_original: str | None = "2024:06:15 10:30:00",
    make: str = "TestCam",
    model: str = "X100",
) -> Path:
    """Write a small synthetic JPEG with a naive DateTimeOriginal in the main IFD."""
    from PIL import Image

    img = Image.new("RGB", (8, 8), color)
    exif = Image.Exif()
    if date_original is not None:
        exif[36867] = date_original  # DateTimeOriginal (written at IFD0)
    if make:
        exif[271] = make
    if model:
        exif[272] = model
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        path,
        format="JPEG",
        exif=exif.tobytes() if (date_original or make or model) else None,
    )
    return path


def _ascii_bytes(s: str) -> bytes:
    return s.encode("ascii", "replace") + b"\x00"


def _build_exif_app1(
    *,
    make: str = "",
    model: str = "",
    dt_original: str = "",
    dt_digitized: str = "",
    offset_original: str = "",
    offset_digitized: str = "",
) -> bytes:
    """Build a little-endian EXIF APP1 payload (Exif\\0\\0 + TIFF).

    IFD0 carries Make/Model/ExifTag; the ExifIFD carries DateTimeOriginal /
    DateTimeDigitized / OffsetTimeOriginal / OffsetTimeDigitized. Only non-empty
    tags are written, so the adapter's ExifIFD branch reads exactly what we
    intend (offset / conflict authority) rather than the main-IFD fallback.
    """

    def _entries(specs: list[tuple[int, int, bytes]]) -> list[tuple[int, int, int, bytes]]:
        return [(tag, typ, len(b), b) for tag, typ, b in specs]

    ifd0_entries: list[tuple[int, int, bytes]] = []
    if make:
        ifd0_entries.append((271, 2, _ascii_bytes(make)))
    if model:
        ifd0_entries.append((272, 2, _ascii_bytes(model)))

    exif_items: list[tuple[int, str]] = []
    if dt_original:
        exif_items.append((36867, dt_original))
    if dt_digitized:
        exif_items.append((36868, dt_digitized))
    if offset_original:
        exif_items.append((0x9011, offset_original))
    if offset_digitized:
        exif_items.append((0x9012, offset_digitized))
    have_exif = bool(exif_items)

    # TIFF header (8 bytes), IFD0 at offset 8.
    tiff_header = b"II" + struct.pack("<H", 0x002A) + struct.pack("<I", 8)

    ifd0_specs = [(t, 2, _ascii_bytes(s)) for (t, s) in []]  # placeholder, replaced below
    ifd0_main = ifd0_entries  # (tag, type, bytes)
    ifd0_count = len(ifd0_main) + (1 if have_exif else 0)
    ifd0_size = 2 + ifd0_count * 12 + 4
    after_ifd0 = 8 + ifd0_size

    ifd0_data = b""
    ifd0_offsets: dict[int, int] = {}
    for tag, typ, b in ifd0_main:
        if len(b) > 4:
            ifd0_offsets[tag] = after_ifd0 + len(ifd0_data)
            ifd0_data += b
            if len(ifd0_data) % 2:
                ifd0_data += b"\x00"

    exif_ifd_offset = after_ifd0 + len(ifd0_data)
    exif_entries = [(tag, 2, _ascii_bytes(s)) for tag, s in exif_items]
    exif_count = len(exif_entries)
    exif_ifd_size = 2 + exif_count * 12 + 4
    exif_data = b""
    exif_offsets: dict[int, int] = {}
    for tag, typ, b in exif_entries:
        if len(b) > 4:
            exif_offsets[tag] = exif_ifd_offset + exif_ifd_size + len(exif_data)
            exif_data += b
            if len(exif_data) % 2:
                exif_data += b"\x00"

    def _serialize(specs: list[tuple[int, int, bytes]], long_specs: list[tuple[int, int]],
                   offsets: dict[int, int]) -> bytes:
        all_entries: list[tuple[int, int, int, bytes]] = [
            (tag, typ, len(b), b) for tag, typ, b in specs
        ]
        for tag, val in long_specs:
            all_entries.append((tag, 4, 1, struct.pack("<I", val)))
        all_entries.sort(key=lambda e: e[0])
        out = struct.pack("<H", len(all_entries))
        for tag, typ, cnt, b in all_entries:
            if typ == 4:
                out += struct.pack("<HHI", tag, typ, cnt) + b
            else:
                if len(b) <= 4:
                    out += struct.pack("<HHI", tag, typ, cnt) + b.ljust(4, b"\x00")
                else:
                    out += struct.pack("<HHI", tag, typ, cnt) + struct.pack("<I", offsets[tag])
        out += struct.pack("<I", 0)
        return out

    long_specs: list[tuple[int, int]] = []
    if have_exif:
        long_specs.append((0x8769, exif_ifd_offset))
    ifd0_blob = _serialize(ifd0_main, long_specs, ifd0_offsets)
    exif_blob = _serialize([(t, ty, b) for (t, ty, b) in exif_entries], [], exif_offsets)

    tiff = tiff_header + ifd0_blob + ifd0_data + exif_blob + exif_data
    return b"Exif\x00\x00" + tiff


def _make_jpeg_rich(
    path: Path,
    *,
    color: tuple[int, int, int] = (10, 20, 30),
    make: str = "TestCam",
    model: str = "X100",
    dt_original: str = "",
    dt_digitized: str = "",
    offset_original: str = "",
    offset_digitized: str = "",
) -> Path:
    """Write a synthetic JPEG whose ExifIFD carries the requested date/offset tags."""
    from PIL import Image

    img = Image.new("RGB", (8, 8), color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG")
    app1 = _build_exif_app1(
        make=make, model=model, dt_original=dt_original,
        dt_digitized=dt_digitized, offset_original=offset_original,
        offset_digitized=offset_digitized,
    )
    length = len(app1) + 2
    segment = b"\xff\xe1" + struct.pack(">H", length) + app1
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8"
    path.write_bytes(data[:2] + segment + data[2:])
    return path


def _photo_plan(data_dir: Path, input_dir: Path, *extra: str) -> dict[str, Any]:
    res = _run_import(
        data_dir, "plan", "--source", "media.photo_timeline", "--input", str(input_dir), "--json", *extra
    )
    return _ok(res)


def _plan_file(tmp_path: Path, plan_data: dict[str, Any], name: str = "plan.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(plan_data), encoding="utf-8")
    return p


def _confirm(
    data_dir: Path, plan_data: dict[str, Any], source_root: Path | None = None,
    import_id: str | None = None,
) -> dict[str, Any]:
    plan_file = _plan_file(
        Path(data_dir).parent, plan_data, name=f"review_{plan_data['import_id']}.json"
    )
    args = ["confirm", "--plan", str(plan_file), "--json"]
    if source_root is not None:
        args += ["--source-root", str(source_root)]
    if import_id is not None:
        args += ["--import-id", import_id]
    return _ok(_run_import(data_dir, *args))


def _status(data_dir: Path, import_id: str) -> dict[str, Any]:
    return _ok(_run_import(data_dir, "status", "--import-id", import_id, "--json"))


def _ledger(data_dir: Path) -> dict[str, Any]:
    return json.loads(
        (data_dir / ".life-index" / "import-jobs" / "ledger.json").read_text("utf-8")
    )


def _write_ledger(data_dir: Path, ledger: dict[str, Any]) -> None:
    (data_dir / ".life-index" / "import-jobs" / "ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )


_CAPTURE_CONFLICT_CODES = {"PHOTO_CAPTURE_TIME_MISSING", "PHOTO_CAPTURE_TIME_AMBIGUOUS"}


# ===================================================================
# Scale + recursive safety
# ===================================================================


def test_plan_handles_100_plus_photos(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # 120 distinct photos across 4 calendar days (30 each).
    dates = ["2024:01:0%d 09:00:00" % d for d in range(1, 5)]
    for i in range(120):
        day = dates[i % 4]
        _make_jpeg(src / f"p{i:03d}.jpg", color=(i % 256, (i * 7) % 256, (i * 13) % 256), date_original=day)

    plan = _photo_plan(data_dir, src)
    assert plan["data"]["source"]["record_count"] == 120
    props = plan["data"]["proposals"]
    assert len(props) == 4  # aggregated per day
    total_atts = sum(len(p["attachments"]) for p in props)
    assert total_atts == 120
    # every proposal is resolved+runnable at plan time
    assert all(p["state"] == "pending" for p in props)


def test_recursive_scan_skips_symlink_escape_and_cycle(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "real.jpg", color=(1, 2, 3))
    _make_jpeg(src / "sub" / "nested.jpg", color=(4, 5, 6))
    os.symlink(src / "real.jpg", src / "link.jpg")  # symlink -> skip
    outside = tmp_path / "outside.jpg"
    _make_jpeg(outside, color=(9, 9, 9))
    os.symlink(outside, src / "escape.jpg")  # root escape -> skip
    os.symlink(src, src / "sub" / "cycle")  # dir cycle -> skip

    plan = _photo_plan(data_dir, src)
    rel_paths = sorted(
        att["source_rel_path"]
        for prop in plan["data"]["proposals"]
        for att in prop["attachments"]
    )
    assert rel_paths == ["real.jpg", "sub/nested.jpg"]


def test_exact_duplicate_vs_same_name_different_content(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(1, 2, 3))  # identical bytes -> duplicate
    (src / "day1").mkdir()
    _make_jpeg(src / "day1" / "IMG.jpg", color=(5, 6, 7))
    (src / "day2").mkdir()
    _make_jpeg(src / "day2" / "IMG.jpg", color=(8, 9, 0))  # same name, diff content -> kept

    plan = _photo_plan(data_dir, src)
    assert plan["data"]["source"]["record_count"] == 3  # a, day1/IMG, day2/IMG
    codes = [w.get("code") for w in plan["data"]["warnings"]]
    assert "PHOTO_DUPLICATE_SKIPPED" in codes


# ===================================================================
# Date authority — offset / naive / missing / conflicting
# ===================================================================


def test_date_offset_exif_uses_local_calendar_no_utc(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # +05:30 offset, 2024-06-15 10:30 local -> must stay 2024-06-15 (no UTC shift).
    _make_jpeg_rich(
        src / "off.jpg", color=(1, 2, 3),
        dt_original="2024:06:15 10:30:00", offset_original="+05:30",
    )
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert prop["journal"]["date"] == "2024-06-15"
    assert prop["source_facts"][0]["capture_time"]["timezone_authority"] == "exif_offset"
    assert not any(c.get("code") in _CAPTURE_CONFLICT_CODES for c in prop["conflicts"])


def test_date_naive_exif_is_camera_local(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg_rich(src / "naive.jpg", color=(4, 5, 6), dt_original="2024:07:20 09:00:00")
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert prop["journal"]["date"] == "2024-07-20"
    assert prop["source_facts"][0]["capture_time"]["timezone_authority"] == "exif_naive"
    assert not any(c.get("code") in _CAPTURE_CONFLICT_CODES for c in prop["conflicts"])


def test_date_malformed_offset_falls_back_to_naive(tmp_path: Path) -> None:
    """An out-of-world / malformed offset is not trusted; date stays camera-local."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # +14:30 is invalid (14 only valid with :00); date must remain 2024-06-15.
    _make_jpeg_rich(
        src / "bad.jpg", color=(1, 2, 3),
        dt_original="2024:06:15 10:30:00", offset_original="+14:30",
    )
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert prop["journal"]["date"] == "2024-06-15"
    assert prop["source_facts"][0]["capture_time"]["timezone_authority"] == "exif_naive"
    assert not any(c.get("code") in _CAPTURE_CONFLICT_CODES for c in prop["conflicts"])


def test_date_mismatched_offset_tag_not_borrowed(tmp_path: Path) -> None:
    """OffsetTimeDigitized must not be borrowed for DateTimeOriginal."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # DateTimeOriginal present, but only OffsetTimeDigitized (paired with
    # CreateDate) is carried — the adapter must not borrow it.
    _make_jpeg_rich(
        src / "mismatch.jpg", color=(1, 2, 3),
        dt_original="2024:06:15 10:30:00", offset_digitized="+05:30",
    )
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert prop["journal"]["date"] == "2024-06-15"
    assert prop["source_facts"][0]["capture_time"]["timezone_authority"] == "exif_naive"
    assert not any(c.get("code") in _CAPTURE_CONFLICT_CODES for c in prop["conflicts"])


def test_date_missing_yields_empty_date_pending(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg_rich(src / "missing.jpg", color=(11, 12, 13))  # no date tags at all
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    # NO 1970-01-01 sentinel: empty date + empty target, conflict recorded.
    assert prop["journal"]["date"] == ""
    assert prop["journal"]["target_rel_path"] == ""
    assert prop["state"] == "pending"
    assert any(c.get("code") == "PHOTO_CAPTURE_TIME_MISSING" for c in prop["conflicts"])
    # filesystem mtime never supplies a date
    assert prop.get("date_resolution", {}).get("status") == "unresolved"


def test_date_conflict_yields_empty_date_pending(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg_rich(
        src / "conflict.jpg", color=(7, 8, 9),
        dt_original="2024:06:15 10:30:00", dt_digitized="2025:01:01 00:00:00",
    )
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert prop["journal"]["date"] == ""
    assert prop["journal"]["target_rel_path"] == ""
    assert prop["state"] == "pending"
    assert any(c.get("code") == "PHOTO_CAPTURE_TIME_AMBIGUOUS" for c in prop["conflicts"])


def test_mtime_never_supplies_capture_date(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    f = src / "noexif.jpg"
    _make_jpeg_rich(f, color=(1, 1, 1))  # no EXIF date
    # Backdate the mtime to a very specific value; the plan must not adopt it.
    import os as _os

    long_ago = 1_000_000_000
    _os.utime(f, (long_ago, long_ago))
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert prop["journal"]["date"] == ""
    assert any(c.get("code") == "PHOTO_CAPTURE_TIME_MISSING" for c in prop["conflicts"])


# ===================================================================
# Explicit date resolution + invalid/no resolution
# ===================================================================


def _proposal_with_code(plan: dict[str, Any], code: str) -> tuple[int, dict[str, Any]]:
    for i, prop in enumerate(plan["data"]["proposals"]):
        if any(c.get("code") == code for c in prop["conflicts"]):
            return i, prop
    raise AssertionError(f"no proposal with conflict {code}")


def test_unresolved_confirm_without_resolution_stays_pending(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg_rich(src / "missing.jpg", color=(11, 12, 13))
    plan = _photo_plan(data_dir, src)

    # Confirm as-is: no date_resolution supplied -> stays pending.
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res["queue_counts"]["pending"] == 1
    assert res["queue_counts"]["confirmed"] == 0
    pid = plan["data"]["proposals"][0]["proposal_id"]
    assert res["proposal_states"][pid] == "pending"


def test_unresolved_confirm_with_invalid_resolution_stays_pending(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg_rich(src / "missing.jpg", color=(11, 12, 13))
    plan = _photo_plan(data_dir, src)
    # Garbage date under user_confirmed -> still unresolved/pending.
    plan["data"]["proposals"][0]["date_resolution"] = {
        "status": "user_confirmed", "date": "not-a-date"
    }
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    pid = plan["data"]["proposals"][0]["proposal_id"]
    assert res["proposal_states"][pid] == "pending"
    assert res["queue_counts"]["confirmed"] == 0


def test_unresolved_confirm_with_valid_resolution_becomes_confirmed(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg_rich(src / "missing.jpg", color=(11, 12, 13))
    plan = _photo_plan(data_dir, src)
    plan["data"]["proposals"][0]["date_resolution"] = {
        "status": "user_confirmed", "date": "2024-05-01"
    }
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    pid = plan["data"]["proposals"][0]["proposal_id"]
    assert res["proposal_states"][pid] == "confirmed"
    assert res["queue_counts"]["confirmed"] == 1
    # persisted review plan now carries the derived canonical target + date
    review_plan_path = (
        data_dir / ".life-index" / "import-jobs" / res["parent_id"] / "review-plan.json"
    )
    persisted = json.loads(review_plan_path.read_text("utf-8"))
    p = persisted["proposals"][0]
    assert p["journal"]["date"] == "2024-05-01"
    assert p["journal"]["target_rel_path"].startswith("Journals/2024/05/")
    assert p["journal"]["target_rel_path"] != ""
    assert p["attachments"][0]["target_rel_path"].startswith("attachments/2024/05/")
    assert p["date_resolution"]["status"] == "user_confirmed"


def test_resolved_photo_confirms_without_explicit_resolution(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))  # naive but resolved
    plan = _photo_plan(data_dir, src)
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res["queue_counts"]["confirmed"] == 1
    assert res["queue_counts"]["pending"] == 0


# ===================================================================
# Immutable attachment provenance — confirm rejects tampered binding
# ===================================================================


def _one_photo_plan_and_prop(tmp_path: Path) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    return data_dir, src, plan["data"], prop


def _confirm_err(data_dir: Path, plan_data: dict[str, Any], src: Path) -> dict[str, Any]:
    return _err(_run_import(
        data_dir, "confirm", "--plan",
        str(_plan_file(Path(data_dir).parent, plan_data, name="prov.json")),
        "--source-root", str(src), "--json",
    ))


def test_confirm_rejects_tampered_source_rel_path(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["attachments"][0]["source_rel_path"] = "tampered/elsewhere.jpg"
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_rejects_tampered_source_ref(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["attachments"][0]["source_ref"] = "source://media.photo_timeline/deadbeef"
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_rejects_tampered_media_type(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["attachments"][0]["media_type"] = "image/png"
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_rejects_tampered_size_bytes(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["attachments"][0]["size_bytes"] = prop["attachments"][0]["size_bytes"] + 999
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_rejects_tampered_attachment_id(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["attachments"][0]["attachment_id"] = "att_deadbeefdead"
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_rejects_attachment_target_escape(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["attachments"][0]["target_rel_path"] = "../evil.jpg"
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_rejects_journal_target_escape(tmp_path: Path) -> None:
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    prop["journal"]["target_rel_path"] = "../escape.md"
    res = _confirm_err(data_dir, plan_data, src)
    assert res["error"]["code"] == "IMPORT_PLAN_INVALID"


def test_confirm_canonical_attachment_target_derived_not_trusted(tmp_path: Path) -> None:
    """A GUI-injected (confined) attachment target is overwritten by the canonical one."""
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    sha = prop["attachments"][0]["source_sha256"]
    prefix = sha.removeprefix("sha256:")[:12]
    # inject a confined-but-wrong target (wrong prefix); confirm must re-derive it.
    prop["attachments"][0]["target_rel_path"] = f"attachments/2024/06/import_deadbeef.jpg"
    res = _confirm(data_dir, plan_data, source_root=src)["data"]
    assert res["queue_counts"]["confirmed"] == 1
    persisted = json.loads(
        (data_dir / ".life-index" / "import-jobs" / res["parent_id"] / "review-plan.json")
        .read_text("utf-8")
    )
    att = persisted["proposals"][0]["attachments"][0]
    # canonical target derived from effective date + content, never the injected value
    assert att["target_rel_path"] == f"attachments/2024/06/import_{prefix}.jpg"
    assert "deadbeef" not in att["target_rel_path"]


def test_confirm_canonical_journal_target_within_date_path(tmp_path: Path) -> None:
    """Journal target is re-derived to the canonical date path/sequence, not trusted."""
    data_dir, src, plan_data, prop = _one_photo_plan_and_prop(tmp_path)
    # inject a confined-but-noncanonical journal target
    prop["journal"]["target_rel_path"] = "Journals/2024/06/life-index_2024-06-15_042.md"
    res = _confirm(data_dir, plan_data, source_root=src)["data"]
    persisted = json.loads(
        (data_dir / ".life-index" / "import-jobs" / res["parent_id"] / "review-plan.json")
        .read_text("utf-8")
    )
    target = persisted["proposals"][0]["journal"]["target_rel_path"]
    assert target.startswith("Journals/2024/06/life-index_2024-06-15_")
    assert target != "Journals/2024/06/life-index_2024-06-15_042.md"


def test_confirm_partial_selection_provenance_preserved(tmp_path: Path) -> None:
    """Dropping one attachment from a multi-photo proposal keeps the remainder bound."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6))
    plan = _photo_plan(data_dir, src)
    prop = plan["data"]["proposals"][0]
    assert len(prop["attachments"]) == 2
    prop["attachments"] = prop["attachments"][:1]  # partial selection
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res["queue_counts"]["confirmed"] == 1
    assert res["queue_counts"]["skipped"] == 0


# ===================================================================
# Selection states — full / partial / all-deselected
# ===================================================================


def test_selection_full_and_partial_confirmed(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # Two photos same day -> one multi-attachment proposal (full selection).
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6))
    plan = _photo_plan(data_dir, src)
    assert len(plan["data"]["proposals"]) == 1
    assert len(plan["data"]["proposals"][0]["attachments"]) == 2

    # full selection -> confirmed
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res["queue_counts"]["confirmed"] == 1

    # partial selection: edit the SAME confirmed proposal (proposal_id kept
    # stable), drop one attachment -> still confirmed with the remainder. A
    # fresh rescan would dedup the queued photos, so selection edits go through
    # the existing plan rather than a new scan.
    prop = plan["data"]["proposals"][0]
    prop["attachments"] = prop["attachments"][:1]
    res2 = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res2["queue_counts"]["confirmed"] == 1
    assert res2["queue_counts"]["skipped"] == 0


def test_selection_all_deselected_is_skipped(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "keep.jpg", color=(1, 2, 3))
    _make_jpeg(src / "drop.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    for prop in plan["data"]["proposals"]:
        prop["attachments"] = []  # deselect everything
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res["queue_counts"]["confirmed"] == 0
    assert res["queue_counts"]["skipped"] == len(plan["data"]["proposals"])
    # nothing runnable
    assert res["queue_counts"]["imported"] == 0


# ===================================================================
# Dedup authority — committed AND current confirmed/batching/imported
# ===================================================================


def test_currently_confirmed_review_proposal_sha_not_reproposed(tmp_path: Path) -> None:
    """A photo in a confirmed (queued) review proposal is deduped on rescan."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "only.jpg", color=(1, 2, 3))

    plan = _photo_plan(data_dir, src)
    assert plan["data"]["source"]["record_count"] == 1
    _confirm(data_dir, plan["data"], source_root=src)  # -> confirmed (queued, not yet imported)

    # Rescan: the confirmed proposal's content SHA must be excluded.
    plan2 = _photo_plan(data_dir, src)
    assert plan2["data"]["source"]["record_count"] == 0
    codes = [w.get("code") for w in plan2["data"]["warnings"]]
    assert "PHOTO_DUPLICATE_SKIPPED" in codes


def test_rolled_back_to_confirmed_remains_excluded_from_rescan(tmp_path: Path) -> None:
    """After import + child rollback, the proposal returns to confirmed and stays excluded."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "only.jpg", color=(1, 2, 3))

    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    _confirm(data_dir, plan["data"], source_root=src)
    run = _ok(_run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    ))["data"]
    child_id = run["import_id"]
    # rollback the child -> proposal returns to confirmed
    _ok(_run_import(data_dir, "rollback", "--import-id", child_id, "--json"))
    assert _status(data_dir, parent_id)["data"]["queue_counts"]["confirmed"] == 1

    # rescan must STILL exclude it (confirmed is in the dedup set)
    plan2 = _photo_plan(data_dir, src)
    assert plan2["data"]["source"]["record_count"] == 0


# ===================================================================
# Safe re-confirm after an imported proposal
# ===================================================================


def test_safe_reconfirm_after_imported_proposal(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "imp.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    pid = plan["data"]["proposals"][0]["proposal_id"]
    _confirm(data_dir, plan["data"], source_root=src)
    _ok(_run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    ))
    assert _status(data_dir, parent_id)["data"]["proposal_states"][pid] == "imported"

    # Re-confirm the original plan: imported proposal must NOT downgrade, contents frozen.
    res = _confirm(data_dir, plan["data"], source_root=src)["data"]
    assert res["proposal_states"][pid] == "imported"
    assert res["queue_counts"]["imported"] == 1

    # persisted plan keeps the imported proposal's original (authoritative) contents
    persisted = json.loads(
        (data_dir / ".life-index" / "import-jobs" / parent_id / "review-plan.json").read_text("utf-8")
    )
    imp = next(p for p in persisted["proposals"] if p["proposal_id"] == pid)
    assert imp["state"] == "imported"
    assert imp["journal"]["date"] == "2024-06-15"


# ===================================================================
# Edit rejected during an active child
# ===================================================================


def test_edit_rejected_during_active_child(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    _confirm(data_dir, plan["data"], source_root=src)

    # Seed an unsettled (running) child to simulate a live batch in progress.
    ledger = _ledger(data_dir)
    child_id = f"{parent_id}#batch-900000001"
    ledger["jobs"][child_id] = {
        "kind": "batch", "parent_review_job_id": parent_id,
        "state": "running", "updated_at": "2026-01-01T00:00:00+00:00",
    }
    ledger["jobs"][parent_id]["active_child_id"] = child_id
    _write_ledger(data_dir, ledger)

    res = _err(_run_import(data_dir, "confirm", "--plan",
                           str(_plan_file(tmp_path, plan["data"], "edit.json")), "--json"))
    assert res["error"]["code"] == "IMPORT_BATCH_ALREADY_ACTIVE"


# ===================================================================
# Restart: status reconstructed only from persisted files
# ===================================================================


def test_restart_status_from_persisted_files_only(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    # one resolved, one missing-date (pending), one deselected (skipped)
    _make_jpeg(src / "ok.jpg", color=(1, 2, 3))
    _make_jpeg_rich(src / "miss.jpg", color=(4, 5, 6))  # missing date -> pending
    _make_jpeg(src / "drop.jpg", color=(7, 8, 9), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    for prop in plan["data"]["proposals"]:
        if prop["journal"]["date"] == "2024-07-01":
            prop["attachments"] = []
    parent_id = plan["data"]["import_id"]
    confirm_res = _confirm(data_dir, plan["data"], source_root=src)["data"]

    # A brand-new process (subprocess) reconstructs status purely from disk.
    status = _status(data_dir, parent_id)["data"]
    assert status["queue_counts"] == confirm_res["queue_counts"]
    assert status["active_child_id"] is None
    assert status["recovery_required"] is False
    # the persisted ledger is the sole authority
    job = _ledger(data_dir)["jobs"][parent_id]
    assert job["proposal_states"] == status["proposal_states"]


# ===================================================================
# Monotonic child ids + exact proposal_ids
# ===================================================================


def test_monotonic_two_child_ids_and_exact_proposal_ids(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "a.jpg", color=(1, 2, 3))
    _make_jpeg(src / "b.jpg", color=(4, 5, 6), date_original="2024:07:01 09:00:00")
    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    pids = sorted(p["proposal_id"] for p in plan["data"]["proposals"])
    _confirm(data_dir, plan["data"], source_root=src)

    run1 = _ok(_run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    ))["data"]
    child1 = run1["import_id"]
    assert child1.startswith(f"{parent_id}#batch-")
    seq1 = int(child1.rsplit("#batch-", 1)[1])

    ledger = _ledger(data_dir)
    assert ledger["jobs"][child1]["proposal_ids"] == pids  # exact membership
    assert ledger["jobs"][parent_id]["next_batch_sequence"] > seq1

    # rollback child1 -> proposals return to confirmed, then run a second child.
    _ok(_run_import(data_dir, "rollback", "--import-id", child1, "--json"))
    run2 = _ok(_run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    ))["data"]
    child2 = run2["import_id"]
    seq2 = int(child2.rsplit("#batch-", 1)[1])
    assert seq2 > seq1  # monotonic

    ledger = _ledger(data_dir)
    assert ledger["jobs"][child2]["proposal_ids"] == pids


# ===================================================================
# Plan-only / ledger-only projection reconciliation
# ===================================================================


def test_plan_only_rebuilds_projection_from_review_plan(tmp_path: Path) -> None:
    """Ledger lost, review-plan.json present -> status rebuilds the parent projection."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "ok.jpg", color=(1, 2, 3))
    _make_jpeg_rich(src / "miss.jpg", color=(4, 5, 6))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    confirm_res = _confirm(data_dir, plan["data"], source_root=src)["data"]

    # Simulate a ledger crash: delete ledger.json, keep review-plan.json.
    (data_dir / ".life-index" / "import-jobs" / "ledger.json").unlink()

    status = _status(data_dir, parent_id)["data"]
    # projection restored from the persisted review plan, never silently reset.
    assert status["queue_counts"] == confirm_res["queue_counts"]
    assert status["kind"] == "review"


def test_status_refuses_rebuild_when_batch_children_exist(tmp_path: Path) -> None:
    """F4: deleting the parent job AFTER a batch import must NOT rebuild the
    parent from the surviving review plan.

    A rebuild would reset imported proposals back to the plan's ``confirmed`` and
    ``next_batch_sequence`` back to 1 — a second authority that resurrects already
    imported history (re-import risk). When batch children of the parent exist in
    the ledger, the parent is NOT a clean first-confirm crash window: status fails
    closed instead of rebuilding. The no-children rebuild above stays green.
    """
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    _confirm(data_dir, plan["data"], source_root=src)
    # run -> a committed batch child; the parent proposal is now imported.
    _ok(_run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    ))
    ledger = _ledger(data_dir)
    assert any(
        job.get("parent_review_job_id") == parent_id for job in ledger["jobs"].values()
    )

    # Delete ONLY the parent job (keep the committed batch child + review plan).
    ledger = _ledger(data_dir)
    ledger["jobs"].pop(parent_id, None)
    (data_dir / ".life-index" / "import-jobs" / "ledger.json").write_text(
        json.dumps(ledger), encoding="utf-8"
    )

    # status must fail closed rather than rebuild (no resurrected history).
    raw = _run_import(data_dir, "status", "--import-id", parent_id, "--json")
    assert raw.returncode != 0, f"expected IMPORT_LEDGER_CORRUPT; stdout:\n{raw.stdout}"
    err = _payload(raw)
    assert err["error"]["code"] == "IMPORT_LEDGER_CORRUPT"
    assert err["error"]["details"]["reason"] == "parent_authority_unrecoverable"


def test_ledger_only_status_ok_run_reports_missing_plan(tmp_path: Path) -> None:
    """Plan lost, ledger present -> status from ledger; run reports explicit missing."""
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "ok.jpg", color=(1, 2, 3))
    plan = _photo_plan(data_dir, src)
    parent_id = plan["data"]["import_id"]
    _confirm(data_dir, plan["data"], source_root=src)

    # Delete the persisted review plan, keep the ledger.
    (data_dir / ".life-index" / "import-jobs" / parent_id / "review-plan.json").unlink()

    # status still works (proposal_states live in the ledger)
    status = _status(data_dir, parent_id)["data"]
    assert status["queue_counts"]["confirmed"] == 1

    # run cannot proceed without the plan -> explicit error, never silent reset
    res = _err(_run_import(
        data_dir, "run", "--import-id", parent_id, "--source-root", str(src), "--json"
    ))
    assert res["error"]["code"] == "IMPORT_REVIEW_PLAN_MISSING"


# ===================================================================
# HEIC explicit report + source immutability
# ===================================================================


def test_heic_explicitly_reported_unsupported(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    _make_jpeg(src / "shot.jpg", color=(1, 2, 3))
    (src / "img.heic").write_bytes(b"not really heic but extension matters")
    (src / "img2.heif").write_bytes(b"heif bytes")

    plan = _photo_plan(data_dir, src)
    assert plan["data"]["source"]["record_count"] == 1
    heic = [w for w in plan["data"]["warnings"] if w.get("code") == "PHOTO_UNSUPPORTED_FORMAT"]
    assert len(heic) == 2
    assert all(w.get("preview_available") is False for w in heic)


def test_scan_and_confirm_leave_source_hash_and_mtime_unchanged(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    src = tmp_path / "photos"
    f = src / "shot.jpg"
    _make_jpeg(f, color=(10, 20, 30))
    before_bytes = f.read_bytes()
    before_mtime = f.stat().st_mtime_ns

    plan = _photo_plan(data_dir, src)  # scan
    _confirm(data_dir, plan["data"], source_root=src)  # confirm

    assert f.read_bytes() == before_bytes
    assert f.stat().st_mtime_ns == before_mtime
