#!/usr/bin/env python3
"""Contract tests for the public attachment read/export CLI surface."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _run_attachment(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
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


def _seed_attachment(data_dir: Path, rel_path: str, content: bytes) -> Path:
    path = data_dir / "attachments" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_export_returns_base64_content_for_attachment_ref(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    content = b"hello attachment\n"
    _seed_attachment(data_dir, "2026/05/photo.txt", content)

    result = _run_attachment(data_dir, "--export", "2026/05/photo.txt")

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["schema_version"] == "m16.attachment.v0"
    assert payload["error"] is None

    data = payload["data"]
    assert data["rel_path"] == "attachments/2026/05/photo.txt"
    assert data["filename"] == "photo.txt"
    assert data["content_type"] == "text/plain"
    assert data["size"] == len(content)
    assert data["sha256"] == hashlib.sha256(content).hexdigest()
    assert base64.b64decode(data["content_base64"]) == content


def test_info_accepts_stored_frontmatter_rel_path_without_content(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "Life-Index"
    content = b"%PDF-1.4"
    _seed_attachment(data_dir, "2026/05/report.pdf", content)

    result = _run_attachment(
        data_dir,
        "--info",
        "../../../attachments/2026/05/report.pdf",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["schema_version"] == "m16.attachment.v0"

    data = payload["data"]
    assert data["rel_path"] == "attachments/2026/05/report.pdf"
    assert data["filename"] == "report.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["size"] == len(content)
    assert "content_base64" not in data


def test_export_rejects_path_traversal_outside_attachments(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = data_dir / "secret.txt"
    secret.write_text("not an attachment", encoding="utf-8")

    result = _run_attachment(data_dir, "--export", "../secret.txt")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["schema_version"] == "m16.attachment.v0"
    assert payload["data"] is None
    assert payload["error"]["code"] == "ATTACHMENT_PATH_INVALID"


def test_export_reports_missing_attachment_as_json_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"

    result = _run_attachment(
        data_dir,
        "--export",
        "attachments/2026/05/missing.png",
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["schema_version"] == "m16.attachment.v0"
    assert payload["data"] is None
    assert payload["error"]["code"] == "ATTACHMENT_NOT_FOUND"
