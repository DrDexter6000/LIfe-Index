"""Contract tests for Data Doctor maintenance commands.

These tests encode the m33 public maintenance envelope before runtime
implementation. All fixture data lives in temporary LIFE_INDEX_DATA_DIR roots.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

EXPECTED_AUDIT_DOMAINS = {
    "layout",
    "search_index",
    "frontmatter",
    "text_encoding",
    "links",
    "attachments",
    "revisions",
    "entity_nodes",
    "entity_relations",
    "import_jobs",
    "migration",
    "backup",
    "config",
    "path_portability",
    "privacy",
}


def _run_maintenance(args: list[str], data_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "maintenance", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        encoding="utf-8",
    )


def _parse_json(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert proc.returncode == 0, (
        f"expected exit 0, got {proc.returncode}\n" f"stdout={proc.stdout}\nstderr={proc.stderr}"
    )
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict)
    return payload


def _file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _write_minimal_fixture(data_dir: Path) -> None:
    journal_dir = data_dir / "Journals" / "2026" / "06"
    journal_dir.mkdir(parents=True)
    (journal_dir / "life-index_2026-06-01_001.md").write_text(
        "---\n"
        "title: Audit Fixture\n"
        "date: 2026-06-01\n"
        "topic: testing\n"
        "---\n"
        "# Audit Fixture\n\n"
        "This fixture intentionally omits generated indexes.\n",
        encoding="utf-8",
    )
    config_dir = data_dir / ".life-index"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "api_key: sk-test-secret-should-not-leak\n",
        encoding="utf-8",
    )


def _write_detector_fixture(data_dir: Path) -> None:
    _write_minimal_fixture(data_dir)

    bad_frontmatter_dir = data_dir / "Journals" / "2026" / "07"
    bad_frontmatter_dir.mkdir(parents=True)
    (bad_frontmatter_dir / "life-index_2026-07-01_001.md").write_text(
        "---\n"
        "title: Missing Date\n"
        "source_path: C:\\Users\\dexter\\Desktop\\legacy.md\n"
        "---\n"
        "# Missing Date\n\n"
        "This entry links to [missing](missing-target.md).\n"
        "It also references ![missing attachment](../../../attachments/missing.jpg).\n"
        "Potential token ghp_1234567890abcdefghijklmnopqrstuvwx should be redacted.\n",
        encoding="utf-8",
    )

    (bad_frontmatter_dir / "life-index_2026-07-02_001.md").write_bytes(
        b"---\ntitle: Bad Encoding\ndate: 2026-07-02\n---\nInvalid byte: \xff\n"
    )

    attachments_dir = data_dir / "attachments"
    attachments_dir.mkdir()
    (attachments_dir / "orphan.bin").write_bytes(b"orphan")

    revisions_dir = data_dir / ".revisions"
    revisions_dir.mkdir()
    (revisions_dir / "orphan-revision.md").write_text("orphan", encoding="utf-8")

    (data_dir / "entity_graph.yaml").write_text(
        "entities:\n"
        "  - id: person-a\n"
        "    type: person\n"
        "    primary_name: Alice\n"
        "    aliases: [SharedAlias]\n"
        "    relationships:\n"
        "      - target: missing-person\n"
        "        relation: spouse_of\n"
        "  - id: person-b\n"
        "    type: person\n"
        "    primary_name: Bob\n"
        "    aliases: [SharedAlias]\n"
        "    relationships: []\n",
        encoding="utf-8",
    )

    import_dir = data_dir / ".life-index" / "imports" / "job-001"
    import_dir.mkdir(parents=True)
    (import_dir / "ledger.json").write_text(
        '{"status": "running", "rollback_manifest_rel_path": "missing.json"}',
        encoding="utf-8",
    )

    (data_dir / ".life-index" / "migration_required.marker").write_text(
        "schema drift fixture\n",
        encoding="utf-8",
    )


def _write_repair_fixture(data_dir: Path) -> None:
    _write_minimal_fixture(data_dir)
    attachments_dir = data_dir / "attachments"
    attachments_dir.mkdir()
    (attachments_dir / "keep.bin").write_bytes(b"protected attachment")
    (data_dir / "entity_graph.yaml").write_text("entities: []\n", encoding="utf-8")
    import_dir = data_dir / ".life-index" / "imports" / "job-keep"
    import_dir.mkdir(parents=True)
    ledger_payload = {
        "status": "completed",
        "rollback_manifest_rel_path": ".life-index/imports/job-keep/rollback.json",
    }
    (import_dir / "ledger.json").write_text(json.dumps(ledger_payload), encoding="utf-8")
    (import_dir / "rollback.json").write_text("{}", encoding="utf-8")


def _write_timestamp_duplicate_fixture(data_dir: Path) -> tuple[Path, Path]:
    _write_repair_fixture(data_dir)
    month_dir = data_dir / "Journals" / "2026" / "06"
    canonical = month_dir / "life-index_2026-06-01_001.md"
    duplicate = month_dir / "life-index_2026-06-01_001_20260413_213643_663199.md"
    duplicate.write_text(
        "---\n"
        "title: Prior Audit Fixture\n"
        "date: 2026-06-01\n"
        "topic: testing\n"
        "---\n"
        "# Prior Audit Fixture\n\n"
        "This is a loose timestamped copy that should be archived, not counted.\n",
        encoding="utf-8",
    )
    return canonical, duplicate


def _write_entity_graph_backup_fixture(
    data_dir: Path, backup_name: str = "entity_graph.yaml.backup_20260621_120000"
) -> tuple[Path, Path]:
    _write_repair_fixture(data_dir)
    canonical = data_dir / "entity_graph.yaml"
    canonical.write_text(
        "entities:\n"
        "  - id: project-life-index\n"
        "    type: project\n"
        "    primary_name: Life Index\n"
        "    aliases: [life-index]\n"
        "    relationships: []\n",
        encoding="utf-8",
    )
    backup = data_dir / backup_name
    backup.write_text(
        "entities:\n"
        "  - id: old-project\n"
        "    type: project\n"
        "    primary_name: Old Project\n"
        "    aliases: []\n"
        "    relationships: []\n",
        encoding="utf-8",
    )
    return canonical, backup


def _write_proposal_fixture(data_dir: Path) -> str:
    _write_repair_fixture(data_dir)
    (data_dir / "entity_graph.yaml").write_text(
        "entities:\n"
        "  - id: person-a\n"
        "    type: person\n"
        "    primary_name: Alice\n"
        "    aliases: [Ali]\n"
        "    relationships: []\n"
        "  - id: person-b\n"
        "    type: person\n"
        "    primary_name: Bob\n"
        "    aliases: []\n"
        "    relationships: []\n",
        encoding="utf-8",
    )
    return "Journals/2026/06/life-index_2026-06-01_001.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_proposal(data_dir: Path, rel_path: str) -> dict[str, Any]:
    return {
        "schema_version": "m33.maintenance_proposal.v0",
        "proposal_id": "proposal-fixture-001",
        "requires_user_ack": True,
        "source": {
            "path": rel_path,
            "sha256": _sha256(data_dir / rel_path),
        },
        "evidence": [
            {
                "issue_id": f"frontmatter.missing_topic:{rel_path}",
                "path": rel_path,
            }
        ],
        "changes": [
            {
                "type": "frontmatter_update",
                "path": rel_path,
                "field": "topic",
                "value": "testing",
            }
        ],
    }


def _write_proposal_file(data_dir: Path, name: str, payload: dict[str, Any]) -> Path:
    path = data_dir / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


class TestMaintenanceAuditContract:
    def test_audit_json_envelope_reports_complete_issue_counts_and_detector_status(
        self, tmp_path: Path
    ) -> None:
        _write_minimal_fixture(tmp_path)

        proc = _run_maintenance(["audit", "--json"], tmp_path)
        payload = _parse_json(proc)

        assert payload["success"] is True
        assert payload["schema_version"] == "m33.maintenance_audit.v0"
        assert payload["command"] == "maintenance audit"
        assert payload["error"] is None

        issues = payload["issues"]
        assert isinstance(issues, list)
        assert issues, "fixture should produce at least one generated-index issue"

        summary = payload["summary"]
        assert summary["total_issues"] == len(issues)
        assert summary["total_issues"] == sum(summary["domain_counts"].values())
        assert set(summary["domain_counts"]) == EXPECTED_AUDIT_DOMAINS
        assert set(summary["detector_status"]) == EXPECTED_AUDIT_DOMAINS
        assert set(summary["detector_status"].values()) <= {"ok", "skipped", "error"}
        assert summary["truncated"] is False
        assert summary["limit"] is None
        assert summary["offset"] == 0
        assert summary["has_more"] is False

        detectors = payload["detectors"]
        assert {detector["domain"] for detector in detectors} == EXPECTED_AUDIT_DOMAINS
        for detector in detectors:
            assert detector["status"] in {"ok", "skipped", "error"}
            assert detector["issue_count"] == summary["domain_counts"][detector["domain"]]

        for issue in issues:
            assert issue["issue_id"]
            assert issue["domain"] in EXPECTED_AUDIT_DOMAINS
            assert issue["risk"] in {"low", "medium", "high"}
            for evidence in issue.get("evidence", []):
                path_value = evidence.get("path")
                if path_value:
                    assert not Path(path_value).is_absolute()

        serialized = json.dumps(payload, ensure_ascii=False)
        assert str(tmp_path) not in serialized
        assert "sk-test-secret-should-not-leak" not in serialized

    def test_audit_json_is_read_only(self, tmp_path: Path) -> None:
        _write_minimal_fixture(tmp_path)
        before = _file_hashes(tmp_path)

        proc = _run_maintenance(["audit", "--json"], tmp_path)
        _parse_json(proc)

        after = _file_hashes(tmp_path)
        assert after == before

    def test_audit_domain_filter_limits_detector_set(self, tmp_path: Path) -> None:
        _write_minimal_fixture(tmp_path)

        proc = _run_maintenance(["audit", "--domain", "layout,frontmatter", "--json"], tmp_path)
        payload = _parse_json(proc)

        expected_domains = {"layout", "frontmatter"}
        assert set(payload["summary"]["domain_counts"]) == expected_domains
        assert set(payload["summary"]["detector_status"]) == expected_domains
        assert {detector["domain"] for detector in payload["detectors"]} == expected_domains
        assert {issue["domain"] for issue in payload["issues"]} <= expected_domains


class TestMaintenanceDetectorAdapters:
    def test_audit_detectors_emit_representative_issue_for_each_domain(
        self, tmp_path: Path
    ) -> None:
        _write_detector_fixture(tmp_path)

        first = _parse_json(_run_maintenance(["audit", "--json"], tmp_path))
        second = _parse_json(_run_maintenance(["audit", "--json"], tmp_path))

        assert set(first["summary"]["domain_counts"]) == EXPECTED_AUDIT_DOMAINS
        assert all(
            first["summary"]["domain_counts"][domain] > 0 for domain in EXPECTED_AUDIT_DOMAINS
        )
        assert {issue["issue_id"] for issue in first["issues"]} == {
            issue["issue_id"] for issue in second["issues"]
        }

        for issue in first["issues"]:
            assert issue["domain"] in EXPECTED_AUDIT_DOMAINS
            assert issue["issue_id"].startswith(f"{issue['domain']}.")
            for evidence in issue.get("evidence", []):
                path_value = evidence.get("path")
                if path_value:
                    assert not Path(path_value).is_absolute()

        serialized = json.dumps(first, ensure_ascii=False)
        assert "sk-test-secret-should-not-leak" not in serialized
        assert "ghp_1234567890abcdefghijklmnopqrstuvwx" not in serialized
        assert str(tmp_path) not in serialized

    def test_detector_error_is_reported_without_truncating_other_domains(
        self, tmp_path: Path
    ) -> None:
        _write_minimal_fixture(tmp_path)
        (tmp_path / "entity_graph.yaml").write_text(
            "entities:\n  - id: [unterminated\n",
            encoding="utf-8",
        )

        payload = _parse_json(
            _run_maintenance(["audit", "--domain", "layout,entity_nodes", "--json"], tmp_path)
        )

        assert payload["summary"]["detector_status"]["entity_nodes"] == "error"
        assert payload["summary"]["detector_status"]["layout"] == "ok"
        assert payload["summary"]["domain_counts"]["layout"] > 0
        assert {detector["domain"] for detector in payload["detectors"]} == {
            "layout",
            "entity_nodes",
        }


class TestMaintenancePlanContract:
    def test_plan_returns_repairable_low_risk_generated_index_plan(self, tmp_path: Path) -> None:
        _write_detector_fixture(tmp_path)
        audit = _parse_json(_run_maintenance(["audit", "--json"], tmp_path))
        issue_id = next(
            issue["issue_id"]
            for issue in audit["issues"]
            if issue["domain"] == "layout" and issue["repairable"] is True
        )

        before = _file_hashes(tmp_path)
        plan = _parse_json(_run_maintenance(["plan", "--issue-id", issue_id, "--json"], tmp_path))
        after = _file_hashes(tmp_path)

        assert after == before
        assert plan["success"] is True
        assert plan["schema_version"] == "m33.maintenance_plan.v0"
        assert plan["command"] == "maintenance plan"
        assert plan["issue_id"] == issue_id
        assert plan["repairable"] is True
        assert plan["risk"] == "low"
        assert plan["requires_user_ack"] is True
        assert plan["touched_paths"]
        assert all(not Path(path).is_absolute() for path in plan["touched_paths"])
        assert plan["preconditions"]
        assert plan["post_check_command"]
        assert plan["rollback_story"]
        assert plan["error"] is None

    def test_plan_marks_human_judgment_issue_non_repairable(self, tmp_path: Path) -> None:
        _write_detector_fixture(tmp_path)
        audit = _parse_json(_run_maintenance(["audit", "--json"], tmp_path))
        issue_id = next(
            issue["issue_id"]
            for issue in audit["issues"]
            if issue["domain"] == "frontmatter" and issue["repairable"] is False
        )

        plan = _parse_json(_run_maintenance(["plan", "--issue-id", issue_id, "--json"], tmp_path))

        assert plan["success"] is True
        assert plan["issue_id"] == issue_id
        assert plan["repairable"] is False
        assert plan["requires_user_ack"] is True
        assert plan["touched_paths"]
        assert plan["plan_steps"] == []
        assert "proposal" in plan["non_repairable_reason"].lower()

    def test_plan_unknown_issue_id_returns_structured_error(self, tmp_path: Path) -> None:
        _write_minimal_fixture(tmp_path)

        proc = _run_maintenance(
            ["plan", "--issue-id", "layout.missing_generated_index:not-present.md", "--json"],
            tmp_path,
        )
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["success"] is False
        assert payload["schema_version"] == "m33.maintenance_plan.v0"
        assert payload["error"]["code"] == "MAINTENANCE_ISSUE_NOT_FOUND"


class TestMaintenanceRepairContract:
    def test_repair_dry_run_for_generated_index_changes_no_files(self, tmp_path: Path) -> None:
        _write_repair_fixture(tmp_path)
        issue_id = "layout.missing_generated_index:INDEX.md"
        before = _file_hashes(tmp_path)

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--dry-run", "--json"], tmp_path)
        )
        after = _file_hashes(tmp_path)

        assert after == before
        assert repair["success"] is True
        assert repair["schema_version"] == "m33.maintenance_repair.v0"
        assert repair["command"] == "maintenance repair"
        assert repair["dry_run"] is True
        assert repair["applied"] is False
        assert repair["planned_paths"] == ["INDEX.md"]
        assert repair["changed_paths"] == []
        assert repair["error"] is None

    def test_repair_apply_generated_index_touches_only_generated_markdown(
        self, tmp_path: Path
    ) -> None:
        _write_repair_fixture(tmp_path)
        issue_id = "layout.missing_generated_index:INDEX.md"
        protected_before = {
            path: digest
            for path, digest in _file_hashes(tmp_path).items()
            if not path.endswith("index_2026.md")
            and not path.endswith("index_2026-06.md")
            and path != "INDEX.md"
            and not path.startswith(".life-index/index-b/")
        }

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--apply", "--json"], tmp_path)
        )

        assert repair["success"] is True
        assert repair["schema_version"] == "m33.maintenance_repair.v0"
        assert repair["dry_run"] is False
        assert repair["applied"] is True
        assert set(repair["changed_paths"]) == {
            ".life-index/index-b/INDEX.md",
            ".life-index/index-b/Journals/2026/06/index.md",
            ".life-index/index-b/Journals/2026/index.md",
            ".life-index/index-b/manifest.json",
            "INDEX.md",
            "Journals/2026/index_2026.md",
            "Journals/2026/06/index_2026-06.md",
        }
        protected_after = {
            path: digest
            for path, digest in _file_hashes(tmp_path).items()
            if path in protected_before
        }
        assert protected_after == protected_before
        assert (tmp_path / "INDEX.md").exists()

    def test_repair_apply_search_index_touches_only_index_and_cache(self, tmp_path: Path) -> None:
        _write_repair_fixture(tmp_path)
        issue_id = "search_index.missing_rebuildable_index:.index"

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--apply", "--json"], tmp_path)
        )

        assert repair["success"] is True
        assert repair["applied"] is True
        assert repair["changed_paths"]
        assert all(
            path.startswith(".index/")
            or path.startswith(".cache/")
            or path.startswith(".life-index/cache/")
            for path in repair["changed_paths"]
        )
        assert (tmp_path / ".index").exists()

    def test_repair_apply_refuses_human_judgment_issue_without_writes(self, tmp_path: Path) -> None:
        _write_detector_fixture(tmp_path)
        audit = _parse_json(_run_maintenance(["audit", "--json"], tmp_path))
        issue_id = next(
            issue["issue_id"]
            for issue in audit["issues"]
            if issue["domain"] == "frontmatter" and issue["repairable"] is False
        )
        before = _file_hashes(tmp_path)

        proc = _run_maintenance(["repair", "--issue-id", issue_id, "--apply", "--json"], tmp_path)

        after = _file_hashes(tmp_path)
        assert after == before
        assert proc.returncode != 0
        payload = json.loads(proc.stdout)
        assert payload["success"] is False
        assert payload["schema_version"] == "m33.maintenance_repair.v0"
        assert payload["error"]["code"] == "MAINTENANCE_REPAIR_NOT_ALLOWED"

    def test_audit_reports_loose_timestamped_journal_copy_as_repairable(
        self, tmp_path: Path
    ) -> None:
        _write_timestamp_duplicate_fixture(tmp_path)

        audit = _parse_json(
            _run_maintenance(["audit", "--domain", "revisions", "--json"], tmp_path)
        )

        issues = [
            issue for issue in audit["issues"] if issue["type"] == "loose_timestamped_journal_copy"
        ]
        assert len(issues) == 1
        issue = issues[0]
        assert issue["repairable"] is True
        assert issue["repair_class"] == "archive"
        assert issue["risk"] == "low"
        assert issue["evidence"][0]["path"] == (
            "Journals/2026/06/life-index_2026-06-01_001_20260413_213643_663199.md"
        )
        assert issue["evidence"][1]["path"] == "Journals/2026/06/life-index_2026-06-01_001.md"

    def test_repair_dry_run_for_loose_timestamped_copy_changes_no_files(
        self, tmp_path: Path
    ) -> None:
        _write_timestamp_duplicate_fixture(tmp_path)
        issue_id = (
            "revisions.loose_timestamped_journal_copy:"
            "Journals/2026/06/life-index_2026-06-01_001_20260413_213643_663199.md"
        )
        before = _file_hashes(tmp_path)

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--dry-run", "--json"], tmp_path)
        )
        after = _file_hashes(tmp_path)

        assert after == before
        assert repair["success"] is True
        assert repair["dry_run"] is True
        assert repair["applied"] is False
        assert repair["planned_paths"] == [
            "Journals/2026/06/life-index_2026-06-01_001.md",
            "Journals/2026/06/life-index_2026-06-01_001_20260413_213643_663199.md",
        ]
        assert repair["changed_paths"] == []

    def test_repair_apply_archives_loose_timestamped_copy_and_preserves_canonical(
        self, tmp_path: Path
    ) -> None:
        canonical, duplicate = _write_timestamp_duplicate_fixture(tmp_path)
        canonical_before = _sha256(canonical)
        duplicate_text = duplicate.read_text(encoding="utf-8")
        issue_id = (
            "revisions.loose_timestamped_journal_copy:"
            "Journals/2026/06/life-index_2026-06-01_001_20260413_213643_663199.md"
        )

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--apply", "--json"], tmp_path)
        )

        archived = (
            tmp_path
            / ".trash"
            / "maintenance"
            / "timestamped-journal-copies"
            / "Journals"
            / "2026"
            / "06"
            / "life-index_2026-06-01_001_20260413_213643_663199.md"
        )
        assert repair["success"] is True
        assert repair["applied"] is True
        assert (
            "Journals/2026/06/life-index_2026-06-01_001_20260413_213643_663199.md"
            in repair["changed_paths"]
        )
        assert (
            ".trash/maintenance/timestamped-journal-copies/Journals/2026/06/"
            "life-index_2026-06-01_001_20260413_213643_663199.md"
        ) in repair["changed_paths"]
        assert canonical.exists()
        assert _sha256(canonical) == canonical_before
        assert not duplicate.exists()
        assert archived.read_text(encoding="utf-8") == duplicate_text

        post_audit = _parse_json(
            _run_maintenance(["audit", "--domain", "revisions", "--json"], tmp_path)
        )
        assert all(
            issue["type"] != "loose_timestamped_journal_copy" for issue in post_audit["issues"]
        )

    def test_audit_reports_entity_graph_backup_copy_as_repairable(self, tmp_path: Path) -> None:
        _write_entity_graph_backup_fixture(tmp_path)

        audit = _parse_json(
            _run_maintenance(["audit", "--domain", "revisions", "--json"], tmp_path)
        )

        issues = [issue for issue in audit["issues"] if issue["type"] == "entity_graph_backup_copy"]
        assert len(issues) == 1
        issue = issues[0]
        assert issue["repairable"] is True
        assert issue["repair_class"] == "archive"
        assert issue["risk"] == "low"
        assert issue["evidence"][0]["path"] == "entity_graph.yaml.backup_20260621_120000"
        assert issue["evidence"][1]["path"] == "entity_graph.yaml"

    def test_repair_dry_run_for_entity_graph_backup_changes_no_files(self, tmp_path: Path) -> None:
        _write_entity_graph_backup_fixture(tmp_path)
        issue_id = "revisions.entity_graph_backup_copy:entity_graph.yaml.backup_20260621_120000"
        before = _file_hashes(tmp_path)

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--dry-run", "--json"], tmp_path)
        )
        after = _file_hashes(tmp_path)

        assert after == before
        assert repair["success"] is True
        assert repair["dry_run"] is True
        assert repair["applied"] is False
        assert repair["planned_paths"] == [
            "entity_graph.yaml",
            "entity_graph.yaml.backup_20260621_120000",
        ]
        assert repair["changed_paths"] == []

    def test_repair_apply_archives_entity_graph_backup_and_preserves_canonical(
        self, tmp_path: Path
    ) -> None:
        canonical, backup = _write_entity_graph_backup_fixture(tmp_path)
        canonical_before = _sha256(canonical)
        backup_text = backup.read_text(encoding="utf-8")
        issue_id = "revisions.entity_graph_backup_copy:entity_graph.yaml.backup_20260621_120000"

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--apply", "--json"], tmp_path)
        )

        archived = (
            tmp_path
            / ".trash"
            / "maintenance"
            / "entity-graph-backups"
            / "entity_graph.yaml.backup_20260621_120000"
        )
        assert repair["success"] is True
        assert repair["applied"] is True
        assert "entity_graph.yaml.backup_20260621_120000" in repair["changed_paths"]
        assert (
            ".trash/maintenance/entity-graph-backups/entity_graph.yaml.backup_20260621_120000"
            in repair["changed_paths"]
        )
        assert canonical.exists()
        assert _sha256(canonical) == canonical_before
        assert not backup.exists()
        assert archived.read_text(encoding="utf-8") == backup_text

        post_audit = _parse_json(
            _run_maintenance(["audit", "--domain", "revisions", "--json"], tmp_path)
        )
        assert all(issue["type"] != "entity_graph_backup_copy" for issue in post_audit["issues"])

    def test_audit_detects_all_entity_graph_backup_name_variants(self, tmp_path: Path) -> None:
        _write_entity_graph_backup_fixture(
            tmp_path,
            backup_name="entity_graph.yaml.backup_20260506_125632",
        )
        (tmp_path / "entity_graph.yaml.backup.2026-05-05-D5").write_text(
            "entities: []\n",
            encoding="utf-8",
        )

        audit = _parse_json(
            _run_maintenance(["audit", "--domain", "revisions", "--json"], tmp_path)
        )

        issue_paths = {
            issue["evidence"][0]["path"]
            for issue in audit["issues"]
            if issue["type"] == "entity_graph_backup_copy"
        }
        assert issue_paths == {
            "entity_graph.yaml.backup_20260506_125632",
            "entity_graph.yaml.backup.2026-05-05-D5",
        }

    def test_repair_apply_archives_dot_date_entity_graph_backup_variant(
        self, tmp_path: Path
    ) -> None:
        canonical, backup = _write_entity_graph_backup_fixture(
            tmp_path,
            backup_name="entity_graph.yaml.backup.2026-05-05-D5",
        )
        canonical_before = _sha256(canonical)
        backup_text = backup.read_text(encoding="utf-8")
        issue_id = "revisions.entity_graph_backup_copy:entity_graph.yaml.backup.2026-05-05-D5"

        repair = _parse_json(
            _run_maintenance(["repair", "--issue-id", issue_id, "--apply", "--json"], tmp_path)
        )

        archived = (
            tmp_path
            / ".trash"
            / "maintenance"
            / "entity-graph-backups"
            / "entity_graph.yaml.backup.2026-05-05-D5"
        )
        assert repair["success"] is True
        assert repair["applied"] is True
        assert "entity_graph.yaml.backup.2026-05-05-D5" in repair["changed_paths"]
        assert (
            ".trash/maintenance/entity-graph-backups/entity_graph.yaml.backup.2026-05-05-D5"
            in repair["changed_paths"]
        )
        assert canonical.exists()
        assert _sha256(canonical) == canonical_before
        assert not backup.exists()
        assert archived.read_text(encoding="utf-8") == backup_text

        post_audit = _parse_json(
            _run_maintenance(["audit", "--domain", "revisions", "--json"], tmp_path)
        )
        assert all(issue["type"] != "entity_graph_backup_copy" for issue in post_audit["issues"])


class TestMaintenanceProposalValidation:
    def test_proposal_validate_accepts_metadata_entity_and_relation_fixtures(
        self, tmp_path: Path
    ) -> None:
        rel_path = _write_proposal_fixture(tmp_path)
        metadata = _base_proposal(tmp_path, rel_path)
        alias = _base_proposal(tmp_path, rel_path)
        alias["proposal_id"] = "proposal-alias"
        alias["changes"] = [{"type": "entity_alias_add", "entity_id": "person-b", "alias": "Bobby"}]
        relation = _base_proposal(tmp_path, rel_path)
        relation["proposal_id"] = "proposal-relation"
        relation["changes"] = [
            {
                "type": "entity_relation_add",
                "source_id": "person-a",
                "target_id": "person-b",
                "relation": "spouse_of",
            }
        ]

        for name, proposal in {
            "metadata.json": metadata,
            "alias.json": alias,
            "relation.json": relation,
        }.items():
            proposal_file = _write_proposal_file(tmp_path, name, proposal)
            before = _file_hashes(tmp_path)

            payload = _parse_json(
                _run_maintenance(
                    ["proposal", "validate", "--file", str(proposal_file), "--json"],
                    tmp_path,
                )
            )

            after = _file_hashes(tmp_path)
            assert after == before
            assert payload["success"] is True
            assert payload["schema_version"] == "m33.maintenance_proposal.v0"
            assert payload["command"] == "maintenance proposal validate"
            assert payload["valid"] is True
            assert payload["proposal_id"] == proposal["proposal_id"]
            assert payload["error"] is None
            assert payload["errors"] == []

    def test_proposal_validate_rejects_unsafe_proposals(self, tmp_path: Path) -> None:
        rel_path = _write_proposal_fixture(tmp_path)
        base = _base_proposal(tmp_path, rel_path)

        cases: dict[str, tuple[dict[str, Any], str]] = {}

        missing_evidence = dict(base)
        missing_evidence["evidence"] = []
        cases["missing_evidence.json"] = (
            missing_evidence,
            "MAINTENANCE_PROPOSAL_MISSING_EVIDENCE",
        )

        invalid_schema = dict(base)
        invalid_schema["schema_version"] = "m33.maintenance_proposal.v9"
        cases["invalid_schema.json"] = (
            invalid_schema,
            "MAINTENANCE_PROPOSAL_INVALID_SCHEMA",
        )

        path_escape = _base_proposal(tmp_path, rel_path)
        path_escape["source"] = {"path": "../escape.md", "sha256": "x"}
        path_escape["changes"] = [
            {
                "type": "frontmatter_update",
                "path": "../escape.md",
                "field": "topic",
                "value": "testing",
            }
        ]
        cases["path_escape.json"] = (
            path_escape,
            "MAINTENANCE_PROPOSAL_PATH_ESCAPE",
        )

        secret_exposure = _base_proposal(tmp_path, rel_path)
        secret_exposure["changes"][0]["value"] = "sk-test-secret-should-not-pass"
        cases["secret.json"] = (
            secret_exposure,
            "MAINTENANCE_PROPOSAL_SECRET_EXPOSURE",
        )

        unsupported_field = _base_proposal(tmp_path, rel_path)
        unsupported_field["changes"][0]["field"] = "content"
        cases["unsupported_field.json"] = (
            unsupported_field,
            "MAINTENANCE_PROPOSAL_UNSUPPORTED_FIELD",
        )

        alias_collision = _base_proposal(tmp_path, rel_path)
        alias_collision["changes"] = [
            {"type": "entity_alias_add", "entity_id": "person-b", "alias": "Alice"}
        ]
        cases["alias_collision.json"] = (
            alias_collision,
            "MAINTENANCE_PROPOSAL_ENTITY_ALIAS_COLLISION",
        )

        missing_ack = _base_proposal(tmp_path, rel_path)
        missing_ack["requires_user_ack"] = False
        cases["missing_ack.json"] = (
            missing_ack,
            "MAINTENANCE_PROPOSAL_MISSING_USER_ACK",
        )

        stale_hash = _base_proposal(tmp_path, rel_path)
        stale_hash["source"]["sha256"] = "0" * 64
        cases["stale_hash.json"] = (
            stale_hash,
            "MAINTENANCE_PROPOSAL_STALE_SOURCE_HASH",
        )

        for name, (proposal, expected_code) in cases.items():
            proposal_file = _write_proposal_file(tmp_path, name, proposal)
            before = _file_hashes(tmp_path)

            proc = _run_maintenance(
                ["proposal", "validate", "--file", str(proposal_file), "--json"],
                tmp_path,
            )

            after = _file_hashes(tmp_path)
            assert after == before
            assert proc.returncode != 0
            payload = json.loads(proc.stdout)
            assert payload["success"] is False
            assert payload["schema_version"] == "m33.maintenance_proposal.v0"
            assert payload["valid"] is False
            assert payload["error"]["code"] == expected_code
