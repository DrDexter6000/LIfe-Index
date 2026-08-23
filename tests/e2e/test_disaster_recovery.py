"""Synthetic backup -> empty restore -> rebuild disaster-recovery proof."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime as RealDatetime
from pathlib import Path
from typing import Any

import pytest

from tools.backup import create_backup, restore_backup
from tools.build_index import build_all
from tools.generate_index import rebuild_index_tree
from tools.lib.entity_graph import save_entity_graph
from tools.lib.paths import get_default_user_data_dir, is_default_user_data_dir
from tools.search_journals import hierarchical_search
from tools.verify.core import run_verify

RECOVERY_MANIFEST_NAME = ".life-index-recovery-manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_hashes(root: Path) -> dict[str, str]:
    source_paths = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.name == "entity_graph.yaml"
            or "attachments" in path.relative_to(root).parts
            or (
                "Journals" in path.relative_to(root).parts
                and not path.name.startswith(("index_", "monthly_", "yearly_"))
            )
        )
    ]
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(source_paths, key=lambda item: item.relative_to(root).as_posix())
    }


def _assert_sandbox(root: Path, tmp_path: Path) -> None:
    assert root.is_relative_to(tmp_path)
    assert root.resolve() != get_default_user_data_dir().resolve()
    assert not is_default_user_data_dir(root)


def _activate_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    process_temp = tmp_path / f"{name}-process-temp"
    process_temp.mkdir()
    _assert_sandbox(root, tmp_path)
    monkeypatch.setenv("LIFE_INDEX_VALIDATION_MODE", "1")
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(root))
    monkeypatch.setenv("TEMP", str(process_temp))
    monkeypatch.setenv("TMP", str(process_temp))
    return root


def _write_synthetic_dataset(root: Path) -> dict[str, str]:
    journal_specs = [
        (
            "2025",
            "12",
            "life-index_2025-12-31_001.md",
            "Recovery Alpha",
            "recoveryquartzalpha",
            "",
        ),
        (
            "2026",
            "01",
            "life-index_2026-01-02_001.md",
            "Recovery Beta",
            "recoveryquartzbeta",
            "![evidence](attachments/2026/01/recovery-evidence.bin)",
        ),
    ]
    for year, month, filename, title, token, attachment_ref in journal_specs:
        target = root / "Journals" / year / month / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "\n".join(
                [
                    "---",
                    f'title: "{title}"',
                    f"date: {year}-{month}-02" if month == "01" else f"date: {year}-{month}-31",
                    'topic: ["life"]',
                    f'abstract: "Synthetic recovery token {token}"',
                    "---",
                    "",
                    f"# {title}",
                    "",
                    f"Known synthetic token: {token}.",
                    attachment_ref,
                    "",
                ]
            ),
            encoding="utf-8",
        )

    attachment = root / "attachments" / "2026" / "01" / "recovery-evidence.bin"
    attachment.parent.mkdir(parents=True)
    attachment.write_bytes(b"synthetic-attachment-evidence\x00\x01")

    save_entity_graph(
        [
            {
                "id": "actor-recovery-guide",
                "type": "actor",
                "primary_name": "Recovery Guide",
                "aliases": ["RecoveryGuideAlias"],
                "attributes": {"kind": "human"},
                "relationships": [],
            }
        ],
        root / "entity_graph.yaml",
    )

    derived = root / ".index" / "derived-sentinel.bin"
    derived.parent.mkdir(parents=True)
    derived.write_bytes(b"rebuildable-only")
    return _source_hashes(root)


def _load_recovery_manifest(result: dict[str, object]) -> tuple[Path, dict[str, Any]]:
    manifest_path = Path(str(result["recovery_manifest_path"]))
    assert manifest_path.name == RECOVERY_MANIFEST_NAME
    return manifest_path, json.loads(manifest_path.read_text(encoding="utf-8"))


def _save_recovery_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _make_directory_link(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name == "nt":
            completed = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if completed.returncode == 0:
                return
            pytest.skip(
                "Windows link/reparse probe unavailable: "
                f"symlink={symlink_error}; junction={completed.stderr or completed.stdout}"
            )
        pytest.skip(f"directory symlink probe unavailable: {symlink_error}")


def _supports_case_distinct_names(directory: Path) -> bool:
    lower = directory / "life-index-case-probe"
    upper = directory / "LIFE-INDEX-CASE-PROBE"
    try:
        lower.write_text("lower", encoding="utf-8")
        if upper.exists():
            return False
        upper.write_text("upper", encoding="utf-8")
        return (
            lower.read_text(encoding="utf-8") == "lower"
            and upper.read_text(encoding="utf-8") == "upper"
        )
    finally:
        upper.unlink(missing_ok=True)
        lower.unlink(missing_ok=True)


def test_backup_manifest_covers_all_required_source_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source")
    expected_source_hashes = _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()

    first = create_backup(str(backup_root), full=True)

    assert first["success"] is True
    manifest_path, manifest = _load_recovery_manifest(first)
    artifacts = manifest["artifacts"]
    canonical = {
        item["path"]: item["sha256"]
        for item in artifacts
        if item["classification"] == "canonical_source"
    }
    derived = {
        item["path"]: item for item in artifacts if item["classification"] == "rebuildable_derived"
    }

    assert manifest["schema_version"] == "life-index.backup-manifest.v1"
    assert manifest["hash_algorithm"] == "sha256"
    assert manifest["complete"] is True
    assert canonical == expected_source_hashes
    assert derived[".index/derived-sentinel.bin"]["included"] is False
    assert not (manifest_path.parent / ".index" / "derived-sentinel.bin").exists()
    assert list(canonical) == sorted(canonical)

    second = create_backup(str(backup_root), full=True)
    _, second_manifest = _load_recovery_manifest(second)
    assert second_manifest == manifest


def test_backup_empty_restore_rebuild_search_verify_roundtrip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source")
    source_hashes = _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True

    restored = tmp_path / "restored"
    restored.mkdir()
    _assert_sandbox(restored, tmp_path)
    assert list(restored.iterdir()) == []

    restore_result = restore_backup(str(backup_result["backup_path"]), dest_path=str(restored))
    assert restore_result["success"] is True
    assert _source_hashes(restored) == source_hashes
    assert not (restored / ".index" / "derived-sentinel.bin").exists()

    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(restored))
    fts_result = build_all(incremental=False)
    legacy_result = rebuild_index_tree()
    assert fts_result["success"] is True
    assert legacy_result["errors"] == []
    assert legacy_result["monthly_indexes_rebuilt"] == 2
    assert legacy_result["yearly_indexes_rebuilt"] == 2
    assert legacy_result["root_index_rebuilt"] is True

    expected_search_paths = {
        "recoveryquartzalpha": "Journals/2025/12/life-index_2025-12-31_001.md",
        "recoveryquartzbeta": "Journals/2026/01/life-index_2026-01-02_001.md",
    }
    for token, expected_path in expected_search_paths.items():
        search_result = hierarchical_search(query=token, level=3)
        assert search_result["success"] is True
        assert any(
            item.get("rel_path", item.get("path")) == expected_path
            for item in search_result["merged_results"]
        )

    verify_result = run_verify()
    assert verify_result["success"] is True
    assert verify_result["issues_count"] == 0
    assert _source_hashes(restored) == source_hashes


def test_backup_copy_failure_names_artifact_and_does_not_publish_complete_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    failed_name = "life-index_2026-01-02_001.md"

    from tools import backup as backup_module

    real_copy2 = backup_module.shutil.copy2

    def fail_selected_copy(source_path: Path, destination_path: Path) -> object:
        if Path(source_path).name == failed_name:
            raise OSError("injected backup copy failure")
        return real_copy2(source_path, destination_path)

    monkeypatch.setattr(backup_module.shutil, "copy2", fail_selected_copy)
    result = create_backup(str(backup_root), full=True)

    assert result["success"] is False
    assert any(failed_name in error for error in result["errors"])
    assert result.get("recovery_manifest_path", "") == ""
    assert not (Path(result["backup_path"]) / RECOVERY_MANIFEST_NAME).exists()
    catalog = backup_root / ".life-index-backup-manifest.json"
    if catalog.exists():
        records = json.loads(catalog.read_text(encoding="utf-8")).get("backups", [])
        assert all(record.get("path") != result["backup_path"] for record in records)


def test_restore_refuses_nonempty_destination_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True

    destination = tmp_path / "nonempty-destination"
    destination.mkdir()
    sentinel = destination / "owner-sentinel.txt"
    sentinel.write_text("must remain unchanged", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in destination.iterdir()}

    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(destination))

    assert result["success"] is False
    assert any("nonempty" in error.lower() for error in result["errors"])
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == before


def test_rebuild_failure_is_visible_and_preserves_source_hashes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True
    restored = tmp_path / "restored"
    restored.mkdir()
    assert restore_backup(str(backup_result["backup_path"]), dest_path=str(restored))["success"]
    before = _source_hashes(restored)
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(restored))

    monkeypatch.setattr(
        "tools.build_index.update_fts_index",
        lambda **_kwargs: {"success": False, "error": "injected rebuild failure"},
    )
    result = build_all(incremental=False)

    assert result["success"] is False
    assert result["fts"]["error"] == "injected rebuild failure"
    assert _source_hashes(restored) == before


@pytest.mark.parametrize(
    "tamper_case",
    ["index_as_canonical", "duplicate_path", "non_normalized_path", "extra_field"],
)
def test_restore_rejects_untrusted_manifest_artifact_schema_and_mapping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tamper_case: str
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, f"source-{tamper_case}")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / f"backups-{tamper_case}"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True
    manifest_path, manifest = _load_recovery_manifest(backup_result)
    artifacts = manifest["artifacts"]

    if tamper_case == "index_as_canonical":
        poison = next(item for item in artifacts if item["path"].startswith(".index/"))
        poison["classification"] = "canonical_source"
        poison["included"] = True
        copied_poison = manifest_path.parent / poison["path"]
        copied_poison.parent.mkdir(parents=True)
        copied_poison.write_bytes((source / poison["path"]).read_bytes())
    elif tamper_case == "duplicate_path":
        artifacts.append(dict(artifacts[0]))
    elif tamper_case == "non_normalized_path":
        journal = next(item for item in artifacts if item["path"].startswith("Journals/"))
        parts = Path(journal["path"]).parts
        journal["path"] = (Path(*parts[:-1]) / ".." / parts[-2] / parts[-1]).as_posix()
    else:
        artifacts[0]["unexpected_authority"] = True

    _save_recovery_manifest(manifest_path, manifest)
    destination = tmp_path / f"restore-{tamper_case}"
    destination.mkdir()
    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(destination))

    assert result["success"] is False
    assert result["files_restored"] == 0
    assert list(destination.iterdir()) == []


def test_restore_rejects_artifact_directory_reparse_escape_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-artifact-link")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-artifact-link"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True

    backup_path = Path(backup_result["backup_path"])
    outside_journals = tmp_path / "outside-journals"
    (backup_path / "Journals").rename(outside_journals)
    _make_directory_link(backup_path / "Journals", outside_journals)
    destination = tmp_path / "restore-artifact-link"
    destination.mkdir()

    result = restore_backup(str(backup_path), dest_path=str(destination))

    assert result["success"] is False
    assert result["files_restored"] == 0
    assert list(destination.iterdir()) == []


def test_restore_rejects_reparse_destination_root_and_preserves_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-destination-link")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-destination-link"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True

    outside_destination = tmp_path / "outside-destination"
    outside_destination.mkdir()
    linked_destination = tmp_path / "linked-destination"
    _make_directory_link(linked_destination, outside_destination)

    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(linked_destination))

    assert result["success"] is False
    assert result["files_restored"] == 0
    assert list(outside_destination.iterdir()) == []


def test_restore_rejects_nonexistent_destination_below_reparse_ancestor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-destination-ancestor-link")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-destination-ancestor-link"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True

    outside_parent = tmp_path / "outside-parent"
    outside_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    _make_directory_link(linked_parent, outside_parent)
    requested_destination = linked_parent / "new-destination"

    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(requested_destination))

    assert result["success"] is False
    assert result["files_restored"] == 0
    assert list(outside_parent.iterdir()) == []


def test_full_backup_refuses_caller_exclusion_of_canonical_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-exclusion")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-exclusion"
    backup_root.mkdir()
    excluded_name = "life-index_2026-01-02_001.md"

    result = create_backup(str(backup_root), full=True, exclude_patterns=[excluded_name])

    assert result["success"] is False
    assert any(
        excluded_name in error and "canonical" in error.lower() for error in result["errors"]
    )
    assert result["recovery_manifest_path"] == ""
    assert not (Path(result["backup_path"]) / RECOVERY_MANIFEST_NAME).exists()
    catalog = backup_root / ".life-index-backup-manifest.json"
    if catalog.exists():
        records = json.loads(catalog.read_text(encoding="utf-8")).get("backups", [])
        assert all(record.get("path") != result["backup_path"] for record in records)


def test_restore_second_copy_failure_compensates_to_retryable_empty_destination(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-restore-copy-failure")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-restore-copy-failure"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True
    destination = tmp_path / "restore-copy-failure"
    destination.mkdir()

    from tools import backup as backup_module

    real_copy2 = backup_module.shutil.copy2
    call_count = 0

    def fail_second_copy(source_path: Path, destination_path: Path) -> object:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise OSError("injected second restore copy failure")
        return real_copy2(source_path, destination_path)

    monkeypatch.setattr(backup_module.shutil, "copy2", fail_second_copy)
    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(destination))

    assert result["success"] is False
    assert any("injected second restore copy failure" in error for error in result["errors"])
    assert result["files_restored"] == 0
    assert list(destination.iterdir()) == []


def test_restore_reports_verified_and_legacy_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-restore-modes")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-restore-modes"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True
    verified_destination = tmp_path / "verified-destination"
    verified_destination.mkdir()

    verified = restore_backup(
        str(backup_result["backup_path"]), dest_path=str(verified_destination)
    )

    assert verified["success"] is True
    assert verified["restore_mode"] == "manifest_verified"
    assert verified["recovery_manifest_verified"] is True
    assert verified["warnings"] == []

    legacy_backup = tmp_path / "legacy-backup"
    legacy_journal = legacy_backup / "Journals" / "2026" / "02" / "legacy.md"
    legacy_journal.parent.mkdir(parents=True)
    legacy_journal.write_text("legacy", encoding="utf-8")
    legacy_destination = tmp_path / "legacy-destination"
    legacy_destination.mkdir()

    legacy = restore_backup(str(legacy_backup), dest_path=str(legacy_destination))

    assert legacy["success"] is True
    assert legacy["restore_mode"] == "legacy_unverified"
    assert legacy["recovery_manifest_verified"] is False
    assert any(
        "legacy" in warning.lower() and "unverified" in warning.lower()
        for warning in legacy["warnings"]
    )


def test_full_backups_with_same_timestamp_create_distinct_recovery_points(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-collision")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-collision"
    backup_root.mkdir()

    from tools import backup as backup_module

    class FixedDatetime:
        @classmethod
        def now(cls) -> RealDatetime:
            return RealDatetime(2026, 7, 13, 20, 0, 0)

    monkeypatch.setattr(backup_module, "datetime", FixedDatetime)
    first = create_backup(str(backup_root), full=True)
    second = create_backup(str(backup_root), full=True)

    assert first["success"] is True
    assert second["success"] is True
    assert first["backup_path"] != second["backup_path"]
    for result in (first, second):
        assert Path(result["backup_path"]).is_dir()
        assert Path(result["recovery_manifest_path"]).is_file()
    records = json.loads(
        (backup_root / ".life-index-backup-manifest.json").read_text(encoding="utf-8")
    )["backups"]
    assert [record["path"] for record in records] == [
        first["backup_path"],
        second["backup_path"],
    ]


def test_case_distinct_artifacts_roundtrip_on_case_sensitive_filesystem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-case-sensitive")
    if not _supports_case_distinct_names(source):
        pytest.skip("real case-sensitive filesystem semantics are unavailable")
    _write_synthetic_dataset(source)
    upper = source / "attachments" / "Case.bin"
    lower = source / "attachments" / "case.bin"
    upper.write_bytes(b"upper")
    lower.write_bytes(b"lower")
    backup_root = tmp_path / "backups-case-sensitive"
    backup_root.mkdir()

    backup_result = create_backup(str(backup_root), full=True)

    assert backup_result["success"] is True
    _, manifest = _load_recovery_manifest(backup_result)
    paths = {artifact["path"] for artifact in manifest["artifacts"]}
    assert {"attachments/Case.bin", "attachments/case.bin"} <= paths
    destination = tmp_path / "restore-case-sensitive"
    destination.mkdir()
    restore_result = restore_backup(str(backup_result["backup_path"]), dest_path=str(destination))
    assert restore_result["success"] is True
    assert (destination / "attachments" / "Case.bin").read_bytes() == b"upper"
    assert (destination / "attachments" / "case.bin").read_bytes() == b"lower"


def test_case_colliding_artifacts_rejected_for_insensitive_destination_before_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-case-collision")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-case-collision"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True
    manifest_path, manifest = _load_recovery_manifest(backup_result)
    attachment = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["path"] == "attachments/2026/01/recovery-evidence.bin"
    )
    collision = dict(attachment)
    collision["path"] = "attachments/2026/01/RECOVERY-EVIDENCE.BIN"
    manifest["artifacts"].append(collision)
    _save_recovery_manifest(manifest_path, manifest)
    destination = tmp_path / "restore-case-collision"
    destination.mkdir()

    from tools import backup as backup_module

    monkeypatch.setattr(
        backup_module,
        "_destination_filesystem_case_sensitive",
        lambda _path: False,
        raising=False,
    )
    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(destination))

    assert result["success"] is False
    assert result["files_restored"] == 0
    assert list(destination.iterdir()) == []


def test_case_distinct_excluded_index_records_do_not_block_insensitive_restore(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-excluded-case-collision")
    source_hashes = _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-excluded-case-collision"
    backup_root.mkdir()
    backup_result = create_backup(str(backup_root), full=True)
    assert backup_result["success"] is True
    manifest_path, manifest = _load_recovery_manifest(backup_result)
    excluded_index = next(
        artifact
        for artifact in manifest["artifacts"]
        if artifact["path"] == ".index/derived-sentinel.bin"
    )
    case_distinct_excluded = dict(excluded_index)
    case_distinct_excluded["path"] = ".index/DERIVED-SENTINEL.BIN"
    manifest["artifacts"].append(case_distinct_excluded)
    _save_recovery_manifest(manifest_path, manifest)
    destination = tmp_path / "restore-excluded-case-collision"
    destination.mkdir()

    from tools import backup as backup_module

    monkeypatch.setattr(
        backup_module,
        "_destination_filesystem_case_sensitive",
        lambda _path: False,
    )
    result = restore_backup(str(backup_result["backup_path"]), dest_path=str(destination))

    assert result["success"] is True
    assert result["recovery_manifest_verified"] is True
    assert _source_hashes(destination) == source_hashes
    assert not (destination / ".index").exists()


def test_creation_case_collision_returns_failure_envelope_without_publication(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-create-case-collision")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-create-case-collision"
    backup_root.mkdir()

    from tools import backup as backup_module

    real_artifact_record = backup_module._artifact_record
    journal_2025_locator = "Journals/2025/12/life-index_2025-12-31_001.md"
    journal_2026_locator = "Journals/2026/01/life-index_2026-01-02_001.md"

    def inject_case_collision(*, path: str, file_path: Path) -> dict[str, Any]:
        record = real_artifact_record(path=path, file_path=file_path)
        if record["path"] == journal_2026_locator:
            parent, filename = journal_2025_locator.rsplit("/", 1)
            record["path"] = f"{parent}/{filename.upper()}"
        return record

    monkeypatch.setattr(backup_module, "_artifact_record", inject_case_collision)
    monkeypatch.setattr(
        backup_module,
        "_destination_filesystem_case_sensitive",
        lambda _path: False,
    )

    result = create_backup(str(backup_root), full=True)

    assert result["success"] is False
    assert result["recovery_manifest_path"] == ""
    assert any("case-colliding" in error for error in result["errors"])
    assert not (Path(result["backup_path"]) / RECOVERY_MANIFEST_NAME).exists()
    catalog_path = backup_root / ".life-index-backup-manifest.json"
    if catalog_path.exists():
        assert json.loads(catalog_path.read_text(encoding="utf-8"))["backups"] == []


def test_concurrent_backup_catalog_publication_preserves_both_recovery_points(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-catalog-concurrency")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-catalog-concurrency"
    backup_root.mkdir()

    from tools import backup as backup_module

    class FixedDatetime:
        @classmethod
        def now(cls) -> RealDatetime:
            return RealDatetime(2026, 7, 13, 21, 0, 0)

    real_load = backup_module.load_backup_manifest
    initial_reads = threading.Barrier(2)
    call_guard = threading.Lock()
    call_count = 0

    def synchronized_load(backup_dir: Path) -> dict[str, Any]:
        nonlocal call_count
        with call_guard:
            call_count += 1
            current_call = call_count
        snapshot = real_load(backup_dir)
        if current_call <= 2:
            initial_reads.wait(timeout=10)
        return snapshot

    monkeypatch.setattr(backup_module, "datetime", FixedDatetime)
    monkeypatch.setattr(backup_module, "load_backup_manifest", synchronized_load)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _index: create_backup(str(backup_root), full=True), range(2))
        )

    assert all(result["success"] is True for result in results)
    assert len({result["backup_path"] for result in results}) == 2
    catalog = real_load(backup_root)
    assert {record["path"] for record in catalog["backups"]} == {
        result["backup_path"] for result in results
    }


def test_catalog_publish_failure_preserves_history_and_releases_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _activate_sandbox(monkeypatch, tmp_path, "source-catalog-interruption")
    _write_synthetic_dataset(source)
    backup_root = tmp_path / "backups-catalog-interruption"
    backup_root.mkdir()
    first = create_backup(str(backup_root), full=True)
    assert first["success"] is True
    catalog_path = backup_root / ".life-index-backup-manifest.json"
    prior_bytes = catalog_path.read_bytes()

    from tools import backup as backup_module
    from tools.lib.file_lock import FileLock

    real_replace = backup_module.Path.replace

    def interrupt_catalog_replace(source_path: Path, target_path: Path) -> Path:
        if Path(target_path) == catalog_path:
            raise OSError("injected catalog publication interruption")
        return real_replace(source_path, target_path)

    monkeypatch.setattr(backup_module.Path, "replace", interrupt_catalog_replace)
    interrupted = create_backup(str(backup_root), full=True)

    assert interrupted["success"] is False
    assert any("manifest" in error.lower() or "清单" in error for error in interrupted["errors"])
    assert catalog_path.read_bytes() == prior_bytes
    records = json.loads(prior_bytes)["backups"]
    assert [record["path"] for record in records] == [first["backup_path"]]
    assert list(backup_root.glob(".life-index-backup-manifest.json*.tmp")) == []
    with FileLock(
        backup_root / backup_module.BACKUP_CATALOG_LOCK_NAME,
        timeout=1.0,
    ):
        pass
