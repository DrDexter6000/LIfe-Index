#!/usr/bin/env python3
"""Contract tests for raw attachment media export variants."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image


def _run_attachment_text(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "attachment", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _run_attachment_bytes(data_dir: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "attachment", *args],
        capture_output=True,
        text=False,
        env=env,
        timeout=30,
    )


def _seed_image(data_dir: Path, rel_path: str, size: tuple[int, int] = (2400, 1200)) -> Path:
    path = data_dir / "attachments" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color=(30, 120, 200))
    image.save(path, format="PNG")
    return path


def _seed_bytes(data_dir: Path, rel_path: str, content: bytes) -> Path:
    path = data_dir / "attachments" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_media_preview_file_export_returns_headers_for_non_ascii_filename(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_image(data_dir, "2026/04/中文 文件.png")
    output = tmp_path / "preview.png"

    result = _run_attachment_text(
        data_dir,
        "media",
        "attachments/2026/04/中文 文件.png",
        "--variant",
        "preview",
        "--max-px",
        "1400",
        "--output",
        str(output),
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["schema_version"] == "m17.attachment-media.v1"
    data = payload["data"]
    assert output.read_bytes()
    assert data["variant"] == "preview"
    assert data["max_px"] == 1400
    assert data["headers"]["Content-Type"] == "image/png"
    assert int(data["headers"]["Content-Length"]) == output.stat().st_size
    assert 'filename="' in data["headers"]["Content-Disposition"]
    assert (
        "filename*=UTF-8''%E4%B8%AD%E6%96%87%20%E6%96%87%E4%BB%B6.png"
        in data["headers"]["Content-Disposition"]
    )

    with Image.open(output) as preview:
        assert max(preview.size) <= 1400


def test_media_thumbnail_cache_hits_and_invalidates_when_source_changes(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    source = _seed_image(data_dir, "2026/04/cache.png", size=(800, 600))
    first_output = tmp_path / "thumb-1.png"
    second_output = tmp_path / "thumb-2.png"
    third_output = tmp_path / "thumb-3.png"

    first = _run_attachment_text(
        data_dir,
        "media",
        "2026/04/cache.png",
        "--variant",
        "thumbnail",
        "--output",
        str(first_output),
    )
    second = _run_attachment_text(
        data_dir,
        "media",
        "2026/04/cache.png",
        "--variant",
        "thumbnail",
        "--output",
        str(second_output),
    )
    assert first.returncode == 0
    assert second.returncode == 0
    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first_payload["data"]["cache"]["hit"] is False
    assert second_payload["data"]["cache"]["hit"] is True
    assert first_payload["data"]["cache"]["key"] == second_payload["data"]["cache"]["key"]

    Image.new("RGB", (800, 600), color=(200, 40, 40)).save(source, format="PNG")
    third = _run_attachment_text(
        data_dir,
        "media",
        "2026/04/cache.png",
        "--variant",
        "thumbnail",
        "--output",
        str(third_output),
    )
    assert third.returncode == 0
    third_payload = json.loads(third.stdout)
    assert third_payload["data"]["cache"]["hit"] is False
    assert third_payload["data"]["cache"]["key"] != first_payload["data"]["cache"]["key"]


def test_media_original_range_streams_raw_bytes_and_metadata_sidecar(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    content = b"0123456789abcdef"
    _seed_bytes(data_dir, "2026/04/movie.mp4", content)
    metadata = tmp_path / "metadata.json"

    result = _run_attachment_bytes(
        data_dir,
        "media",
        "attachments/2026/04/movie.mp4",
        "--variant",
        "original",
        "--range",
        "bytes=2-5",
        "--metadata-output",
        str(metadata),
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert result.stdout == b"2345"
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    assert payload["data"]["stream"]["status_code"] == 206
    assert payload["data"]["headers"]["Content-Range"] == "bytes 2-5/16"
    assert payload["data"]["headers"]["Accept-Ranges"] == "bytes"
    assert payload["data"]["headers"]["Content-Length"] == "4"


def test_media_reports_not_found_as_structured_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"

    result = _run_attachment_text(
        data_dir,
        "media",
        "attachments/2026/04/missing.png",
        "--variant",
        "preview",
        "--output",
        str(tmp_path / "missing.png"),
    )

    assert result.returncode != 0
    payload = json.loads(result.stderr)
    assert payload["success"] is False
    assert payload["schema_version"] == "m17.attachment-media.v1"
    assert payload["error"]["code"] == "ATTACHMENT_NOT_FOUND"


def test_media_reports_unsupported_media_and_decode_failures(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_bytes(data_dir, "2026/04/readme.txt", b"not an image")
    _seed_bytes(data_dir, "2026/04/broken.png", b"not actually a png")

    unsupported = _run_attachment_text(
        data_dir,
        "media",
        "2026/04/readme.txt",
        "--variant",
        "preview",
        "--output",
        str(tmp_path / "readme-preview"),
    )
    decode_failed = _run_attachment_text(
        data_dir,
        "media",
        "2026/04/broken.png",
        "--variant",
        "preview",
        "--output",
        str(tmp_path / "broken-preview"),
    )

    assert unsupported.returncode != 0
    assert json.loads(unsupported.stderr)["error"]["code"] == "ATTACHMENT_UNSUPPORTED_MEDIA"
    assert decode_failed.returncode != 0
    assert json.loads(decode_failed.stderr)["error"]["code"] == "ATTACHMENT_DECODE_FAILED"


def test_media_rejects_invalid_range_without_writing_output(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_bytes(data_dir, "2026/04/movie.mp4", b"0123")
    output = tmp_path / "bad-range.bin"

    result = _run_attachment_text(
        data_dir,
        "media",
        "2026/04/movie.mp4",
        "--variant",
        "original",
        "--range",
        "bytes=99-100",
        "--output",
        str(output),
    )

    assert result.returncode != 0
    assert not output.exists()
    assert json.loads(result.stderr)["error"]["code"] == "ATTACHMENT_RANGE_INVALID"
