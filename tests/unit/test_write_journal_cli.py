#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, TypedDict

import pytest

from tools.write_journal.__main__ import main

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIFIED_CONFIRM = (sys.executable, "-m", "tools", "confirm")
NATIVE_CONFIRM = (sys.executable, "-m", "tools.write_journal", "confirm")


class TreeSnapshot(TypedDict):
    entries: list[tuple[str, str, str | None]]
    file_count: int
    tree_hash: str


def _isolated_cli_env(data_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return env


def _tree_snapshot(root: Path) -> TreeSnapshot:
    entries: list[tuple[str, str, str | None]] = []
    if root.exists():
        for path in sorted(root.rglob("*")):
            rel_path = path.relative_to(root).as_posix()
            if path.is_dir():
                entries.append(("dir", rel_path, None))
            else:
                entries.append(
                    (
                        "file",
                        rel_path,
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
    return {
        "entries": entries,
        "file_count": sum(1 for kind, _path, _digest in entries if kind == "file"),
        "tree_hash": hashlib.sha256(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def _write_valid_journal_at(journal: Path) -> Path:
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text(
        "---\n"
        'title: "Synthetic confirmation"\n'
        "date: 2026-07-19\n"
        'location: "Old City"\n'
        'weather: "Old Weather"\n'
        'topic: ["life"]\n'
        'abstract: "Synthetic entry"\n'
        "---\n\n"
        "Synthetic body.\n",
        encoding="utf-8",
    )
    return journal


def _write_valid_journal(data_dir: Path) -> Path:
    return _write_valid_journal_at(
        data_dir / "Journals" / "2026" / "07" / "life-index_2026-07-19_001.md"
    )


def _run_confirm(
    entrypoint: tuple[str, ...],
    *,
    journal_arg: str,
    data_dir: Path,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            *entrypoint,
            "--journal",
            journal_arg,
            "--location",
            "Corrected City",
            "--weather",
            "Corrected Weather",
        ],
        cwd=cwd,
        env=_isolated_cli_env(data_dir),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )


def test_write_journal_cli_confirm_subcommand_calls_apply_confirmation_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}
    data_dir = tmp_path / "data"
    journal_ref = "Journals/2026/03/life-index_2026-03-10_001.md"
    expected_journal_path = (data_dir / journal_ref).resolve()

    def fake_apply_confirmation_updates(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"success": True, "journal_path": str(kwargs["journal_path"])}

    monkeypatch.setattr(
        "tools.write_journal.__main__.apply_confirmation_updates",
        fake_apply_confirmation_updates,
        raising=False,
    )
    monkeypatch.setattr("tools.write_journal.__main__.ensure_dirs", lambda: None)
    monkeypatch.setattr("tools.write_journal.__main__._emit_json", lambda payload: None)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "write_journal",
            "confirm",
            "--journal",
            journal_ref,
            "--location",
            "New City",
            "--weather",
            "New Weather",
            "--approve-related",
            "Journals/2026/03/a.md",
            "--approve-related",
            "Journals/2026/03/b.md",
            "--approve-related-id",
            "1",
            "--reject-related",
            "Journals/2026/03/c.md",
            "--reject-related-id",
            "2",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert captured["journal_path"] == expected_journal_path
    assert captured["location"] == "New City"
    assert captured["weather"] == "New Weather"
    assert captured["approved_related_entries"] == [
        "Journals/2026/03/a.md",
        "Journals/2026/03/b.md",
    ]
    assert captured["approved_related_candidate_ids"] == [1]
    assert captured["rejected_related_entries"] == ["Journals/2026/03/c.md"]
    assert captured["rejected_related_candidate_ids"] == [2]


def test_unified_cli_routes_confirm_to_write_journal_with_nested_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.__main__ as tools_main

    class FakeModule:
        argv: list[str] | None = None

        @staticmethod
        def main() -> None:
            FakeModule.argv = list(sys.argv)

    monkeypatch.setattr(sys, "argv", ["life-index", "confirm", "--journal", "foo.md"])
    monkeypatch.setattr(tools_main, "__import__", lambda *args, **kwargs: FakeModule, raising=False)

    tools_main.main()

    assert FakeModule.argv == ["life-index confirm", "confirm", "--journal", "foo.md"]


def test_unified_cli_preserves_write_argument_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tools.__main__ as tools_main

    class FakeModule:
        argv: list[str] | None = None

        @staticmethod
        def main() -> None:
            FakeModule.argv = list(sys.argv)

    monkeypatch.setattr(sys, "argv", ["life-index", "write", "--data", "{}"])
    monkeypatch.setattr(tools_main, "__import__", lambda *args, **kwargs: FakeModule, raising=False)

    tools_main.main()

    assert FakeModule.argv == ["life-index write", "--data", "{}"]


def test_unified_confirm_updates_existing_journal_in_place(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    for rel_dir in ("by-topic", "attachments", ".life-index"):
        (data_dir / rel_dir).mkdir(parents=True, exist_ok=True)
    journal = _write_valid_journal(data_dir)
    before = _tree_snapshot(data_dir)
    before_journal_hash = hashlib.sha256(journal.read_bytes()).hexdigest()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "confirm",
            "--journal",
            str(journal),
            "--location",
            "Corrected City",
            "--weather",
            "Corrected Weather",
        ],
        cwd=REPO_ROOT,
        env=_isolated_cli_env(data_dir),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    after_invocation = _tree_snapshot(data_dir)
    assert (
        result.returncode == 0
    ), f"stderr={result.stderr!r}; before={before!r}; after={after_invocation!r}"
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["confirm_status"] == "complete"
    updated = journal.read_text(encoding="utf-8")
    assert 'location: "Corrected City"' in updated
    assert 'weather: "Corrected Weather"' in updated
    assert hashlib.sha256(journal.read_bytes()).hexdigest() != before_journal_hash
    canonical_journals = list((data_dir / "Journals").glob("*/*/life-index_*.md"))
    assert canonical_journals == [journal]

    after = after_invocation
    before_entries = {entry[1]: entry for entry in before["entries"]}
    after_entries = {entry[1]: entry for entry in after["entries"]}
    changed_paths = {
        path
        for path in before_entries.keys() | after_entries.keys()
        if before_entries.get(path) != after_entries.get(path)
    }
    revision_paths = {
        path for path in changed_paths if "/.revisions/" in f"/{path}/" and path.endswith(".md")
    }
    assert changed_paths == {
        journal.relative_to(data_dir).as_posix(),
        ".cache",
        ".cache/journals.lock",
        ".index",
        ".index/pending_writes.json",
        ".life-index/index-b",
        ".life-index/index-b/INDEX.md",
        ".life-index/index-b/manifest.json",
        ".life-index/index-b/Journals",
        ".life-index/index-b/Journals/2026",
        ".life-index/index-b/Journals/2026/index.md",
        ".life-index/index-b/Journals/2026/07",
        ".life-index/index-b/Journals/2026/07/index.md",
        "Journals/2026/07/.revisions",
        *revision_paths,
    }
    assert len(revision_paths) == 1


@pytest.mark.parametrize(
    "args",
    [
        ["confirm", "--location", "Nowhere"],
        ["confirm", "--journal", "unused.md", "--unknown-confirm-option"],
    ],
    ids=["missing-required-journal", "unknown-option"],
)
def test_unified_confirm_invalid_argv_is_zero_write(tmp_path: Path, args: list[str]) -> None:
    data_dir = tmp_path / "data"
    journal = _write_valid_journal(data_dir)
    before = _tree_snapshot(data_dir)
    before_bytes = journal.read_bytes()

    result = subprocess.run(
        [sys.executable, "-m", "tools", *args],
        cwd=REPO_ROOT,
        env=_isolated_cli_env(data_dir),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode != 0
    assert _tree_snapshot(data_dir) == before
    assert journal.read_bytes() == before_bytes


def test_unified_confirm_nonexistent_journal_is_zero_write(tmp_path: Path) -> None:
    data_dir = tmp_path / "absent-data"
    missing_journal = data_dir / "Journals" / "2026" / "07" / "life-index_2026-07-19_001.md"
    before = _tree_snapshot(data_dir)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools",
            "confirm",
            "--journal",
            str(missing_journal),
            "--location",
            "Nowhere",
            "--weather",
            "Unknown",
        ],
        cwd=REPO_ROOT,
        env=_isolated_cli_env(data_dir),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    after = _tree_snapshot(data_dir)
    assert result.returncode != 0
    assert after == before, f"before={before!r}; after={after!r}"


@pytest.mark.parametrize(
    ("entrypoint", "target_kind"),
    [
        (UNIFIED_CONFIRM, "outside"),
        (NATIVE_CONFIRM, "outside"),
        (UNIFIED_CONFIRM, "noncanonical"),
        (NATIVE_CONFIRM, "noncanonical"),
        (UNIFIED_CONFIRM, "revision"),
        (NATIVE_CONFIRM, "revision"),
        (UNIFIED_CONFIRM, "directory"),
        (NATIVE_CONFIRM, "directory"),
    ],
    ids=[
        "unified-outside",
        "native-outside",
        "unified-noncanonical",
        "native-noncanonical",
        "unified-revision",
        "native-revision",
        "unified-directory",
        "native-directory",
    ],
)
def test_confirm_rejects_paths_outside_canonical_journal_boundary(
    tmp_path: Path, entrypoint: tuple[str, ...], target_kind: str
) -> None:
    data_dir = tmp_path / "data"
    if target_kind == "outside":
        target = _write_valid_journal_at(
            tmp_path / "outside" / "2026" / "07" / "life-index_2026-07-19_001.md"
        )
    elif target_kind == "noncanonical":
        target = _write_valid_journal_at(data_dir / "Journals" / "2026" / "07" / "notes.md")
    elif target_kind == "revision":
        target = _write_valid_journal_at(
            data_dir
            / "Journals"
            / "2026"
            / "07"
            / ".revisions"
            / "life-index_2026-07-19_001_20260719_120000_000000.md"
        )
    else:
        target = data_dir / "Journals" / "2026" / "07" / "life-index_2026-07-19_001.md"
        target.mkdir(parents=True)

    before = _tree_snapshot(tmp_path)
    result = _run_confirm(
        entrypoint,
        journal_arg=str(target),
        data_dir=data_dir,
    )
    after = _tree_snapshot(tmp_path)

    assert result.returncode != 0, f"stdout={result.stdout!r}; before={before!r}; after={after!r}"
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["confirm_status"] == "failed"
    assert payload["error"]["code"] in {"E0103", "E0104"}
    assert after == before, f"before={before!r}; after={after!r}"


@pytest.mark.parametrize(
    "entrypoint",
    [UNIFIED_CONFIRM, NATIVE_CONFIRM],
    ids=["unified", "native"],
)
def test_confirm_rejects_relative_traversal_without_writes(
    tmp_path: Path, entrypoint: tuple[str, ...]
) -> None:
    data_dir = tmp_path / "data"
    cwd = tmp_path / "cwd"
    (cwd / "Journals" / "2026" / "07").mkdir(parents=True)
    outside = _write_valid_journal_at(cwd / "outside" / "life-index_2026-07-19_001.md")
    traversal_arg = "Journals/2026/07/../../../outside/" + outside.name
    before = _tree_snapshot(tmp_path)

    result = _run_confirm(
        entrypoint,
        journal_arg=traversal_arg,
        data_dir=data_dir,
        cwd=cwd,
    )
    after = _tree_snapshot(tmp_path)

    assert result.returncode != 0, f"stdout={result.stdout!r}; before={before!r}; after={after!r}"
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert payload["confirm_status"] == "failed"
    assert payload["error"]["code"] in {"E0103", "E0104"}
    assert after == before, f"before={before!r}; after={after!r}"


@pytest.mark.parametrize(
    "entrypoint",
    [UNIFIED_CONFIRM, NATIVE_CONFIRM],
    ids=["unified", "native"],
)
def test_confirm_accepts_relative_canonical_journal_ref(
    tmp_path: Path, entrypoint: tuple[str, ...]
) -> None:
    data_dir = tmp_path / "data"
    journal = _write_valid_journal(data_dir)

    result = _run_confirm(
        entrypoint,
        journal_arg="Journals/2026/07/life-index_2026-07-19_001.md",
        data_dir=data_dir,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["confirm_status"] == "complete"
    updated = journal.read_text(encoding="utf-8")
    assert 'location: "Corrected City"' in updated
    assert 'weather: "Corrected Weather"' in updated
    assert list((data_dir / "Journals").glob("*/*/life-index_*.md")) == [journal]


def test_enrich_cli_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_prepare_journal_metadata(data: dict[str, Any]) -> dict[str, Any]:
        captured["data"] = data
        return {"content": data["content"], "topic": ["life"]}

    monkeypatch.setattr(
        "tools.write_journal.__main__.prepare_journal_metadata",
        fake_prepare_journal_metadata,
    )
    monkeypatch.setattr("tools.write_journal.__main__._emit_json", lambda payload: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "write_journal",
            "enrich",
            "--data",
            '{"content":"test","topic":"life"}',
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert captured["data"]["content"] == "test"


def test_enrich_cli_use_llm_is_not_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "write_journal",
            "enrich",
            "--data",
            '{"content":"test","topic":"life"}',
            "--use-llm",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
