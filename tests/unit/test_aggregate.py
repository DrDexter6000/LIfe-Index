#!/usr/bin/env python3
"""Unit tests for tools.aggregate.core — TDD RED phase.

Required RED cases:
1. date-only journals + entry_time_after=22:00 → partial, count=0, unknown_entries
2. explicit datetime metadata counts late entries deterministically
3. two late entries same day → unit=day counts once, unit=entry counts twice
4. journal_count grouped by unit=month returns deterministic buckets
5. term_presence=晚睡 returns matched paths with exactness=approximate + limitations
"""

import os
from pathlib import Path

import pytest

from tools.aggregate import core as aggregate_core
from tools.aggregate.core import run_aggregate


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch):
    """Create a temp data dir with Journals/ structure, set LIFE_INDEX_DATA_DIR."""
    data_dir = tmp_path / "Life-Index"
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    return data_dir


def _write_journal(
    journals_dir: Path,
    date: str,
    content: str = "test content",
    *,
    filename_suffix: str = "001",
    extra_frontmatter: str = "",
) -> Path:
    """Helper: write a minimal journal file under Journals/YYYY/MM/."""
    year, month, _ = date.split("-")
    d = journals_dir / year / month
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"life-index_{date}_{filename_suffix}.md"
    fm = f"---\ndate: {date}\n{extra_frontmatter}---\n\n# Test\n\n{content}\n"
    path.write_text(fm, encoding="utf-8")
    return path


def _write_journal_with_time(
    journals_dir: Path,
    date: str,
    time_str: str,
    content: str = "test content",
    *,
    filename_suffix: str = "001",
) -> Path:
    """Write journal with ISO datetime in frontmatter."""
    year, month, _ = date.split("-")
    d = journals_dir / year / month
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"life-index_{date}_{filename_suffix}.md"
    fm = f"---\ndate: {date}T{time_str}\n---\n\n# Test\n\n{content}\n"
    path.write_text(fm, encoding="utf-8")
    return path


def _write_journal_with_separate_time(
    journals_dir: Path,
    date: str,
    time_str: str,
    content: str = "test content",
    *,
    filename_suffix: str = "001",
) -> Path:
    """Write journal with separate frontmatter time: field (not embedded in date)."""
    year, month, _ = date.split("-")
    d = journals_dir / year / month
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"life-index_{date}_{filename_suffix}.md"
    fm = f"---\ndate: {date}\ntime: {time_str}\n---\n" f"\n# Test\n\n{content}\n"
    path.write_text(fm, encoding="utf-8")
    return path


class TestRed1DateOnlyPartial:
    """RED case 1: date-only journals with entry_time_after=22:00 → partial."""

    def test_date_only_returns_partial(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "some entry")
        _write_journal(journals_dir, "2026-03-15", "another entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="day",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 0
        assert len(result["unknown_entries"]) == 2
        for entry in result["unknown_entries"]:
            assert "reason" in entry
            assert "no_time" in entry["reason"] or "no_time_field" in entry["reason"]


class TestRed2ExplicitDatetimeDeterministic:
    """RED case 2: explicit datetime metadata counts late entries deterministically."""

    def test_late_entry_counted(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal_with_time(journals_dir, "2026-03-15", "10:00:00", "early entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "exact"
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) == 1
        assert "2026-03-14" in result["matched_entries"][0]


class TestRed2BSeparateTimeField:
    """Gate fix: separate frontmatter time: 23:30 must be counted as late."""

    def test_separate_time_field_counted(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_separate_time(journals_dir, "2026-03-14", "23:30", "late entry")
        _write_journal_with_separate_time(journals_dir, "2026-03-15", "10:00", "early entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "exact"
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) == 1
        assert "2026-03-14" in result["matched_entries"][0]
        assert len(result["unknown_entries"]) == 0

    def test_separate_time_hhmmss_format(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_separate_time(journals_dir, "2026-03-14", "23:30:00", "late entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1


class TestRed3DayVsEntryDeduplication:
    """RED case 3: two late entries same day → unit=day counts once, unit=entry counts twice."""

    def _setup_two_late_same_day(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(
            journals_dir, "2026-03-14", "22:30:00", "late1", filename_suffix="001"
        )
        _write_journal_with_time(
            journals_dir, "2026-03-14", "23:00:00", "late2", filename_suffix="002"
        )
        return journals_dir

    def test_unit_day_deduplicates(self, sandbox: Path):
        self._setup_two_late_same_day(sandbox)
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="entry_time_after=22:00",
        )
        assert result["success"] is True
        assert result["result"]["count"] == 1

    def test_unit_entry_counts_each(self, sandbox: Path):
        self._setup_two_late_same_day(sandbox)
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="entry_time_after=22:00",
        )
        assert result["success"] is True
        assert result["result"]["count"] == 2


class TestRed4JournalCountByMonth:
    """RED case 4: journal_count grouped by unit=month returns deterministic buckets."""

    def test_monthly_buckets(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-05", "jan entry 1")
        _write_journal(journals_dir, "2026-01-20", "jan entry 2")
        _write_journal(journals_dir, "2026-02-03", "feb entry")
        _write_journal(journals_dir, "2026-03-10", "mar entry 1")
        _write_journal(journals_dir, "2026-03-15", "mar entry 2")
        _write_journal(journals_dir, "2026-03-28", "mar entry 3")

        result = run_aggregate(
            range_str="2026-01-01..2026-03-31",
            unit="month",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "exact"
        assert "buckets" in result
        buckets_by_key = {b["key"]: b for b in result["buckets"]}
        assert buckets_by_key["2026-01"]["count"] == 2
        assert buckets_by_key["2026-02"]["count"] == 1
        assert buckets_by_key["2026-03"]["count"] == 3
        for b in result["buckets"]:
            assert "evidence_paths" in b
            for p in b["evidence_paths"]:
                assert not os.path.isabs(p)


class TestRed5TermPresenceApproximate:
    """RED case 5: term_presence=晚睡 returns matched paths with exactness=approximate."""

    def test_term_presence_approximate(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "今天又晚睡了，得早点休息")
        _write_journal(journals_dir, "2026-03-15", "今天按时睡觉了")
        _write_journal(journals_dir, "2026-03-16", "加班到很晚，又是晚睡")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-16",
            unit="day",
            predicate="term_presence=晚睡",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "approximate"
        assert result["result"]["count"] == 2
        assert len(result["matched_entries"]) == 2
        assert "limitations" in result
        assert any(
            "not behavior proof" in lim.lower() or "mention" in lim.lower()
            for lim in result["limitations"]
        )


class TestRedInvalidInputs:
    """Additional RED: invalid predicates/ranges return structured error JSON."""

    def test_invalid_predicate(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-01-01..2026-03-31",
            unit="day",
            predicate="nonexistent_predicate",
        )
        assert result["success"] is False

    def test_invalid_range_format(self, sandbox: Path):
        result = run_aggregate(
            range_str="invalid",
            unit="day",
            predicate="journal_count",
        )
        assert result["success"] is False

    def test_invalid_unit(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-01-01..2026-03-31",
            unit="decade",
            predicate="journal_count",
        )
        assert result["success"] is False


class TestOutputContract:
    """Verify JSON output contract fields per RFC-001 §8."""

    def test_output_has_all_required_fields(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "test")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        required_fields = [
            "success",
            "query",
            "command",
            "metric",
            "unit",
            "range",
            "predicate",
            "result",
            "buckets",
            "matched_entries",
            "excluded_entries",
            "unknown_entries",
            "evidence_paths",
            "limitations",
            "performance",
        ]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"

        assert result["command"] == "aggregate"
        assert result["unit"] == "day"
        assert "total_time_ms" in result["performance"]

    def test_no_absolute_paths_in_output(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "test")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        def _check_paths(
            obj,
            path_fields=(
                "evidence_paths",
                "matched_entries",
                "excluded_entries",
            ),
        ):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k in path_fields and isinstance(v, list):
                        for p in v:
                            if isinstance(p, str):
                                assert not os.path.isabs(p), f"Absolute path found: {p}"
                            elif isinstance(p, dict) and "path" in p:
                                assert not os.path.isabs(p["path"]), (
                                    f"Absolute path found: " f"{p['path']}"
                                )
                    elif isinstance(v, (dict, list)):
                        _check_paths(v, path_fields)
            elif isinstance(obj, list):
                for item in obj:
                    _check_paths(item, path_fields)

        _check_paths(result)

    def test_evidence_paths_use_forward_slashes(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "test")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        for path in result.get("evidence_paths", []):
            assert "\\" not in path, f"Backslash in path: {path}"


class TestMixedTimePartialCountLowerBound:
    """Contract fix: mixed time data returns partial with confirmed lower-bound count.

    When some entries have time and others don't, exactness is partial.
    count is the confirmed lower bound; matched_entries still list known-late
    entries as evidence.
    """

    def test_mixed_time_count_is_lower_bound_entry_unit(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal(journals_dir, "2026-03-15", "no time entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) >= 1
        assert "2026-03-14" in result["matched_entries"][0]
        assert len(result["unknown_entries"]) == 1
        assert "2026-03-15" in result["unknown_entries"][0]["path"]

    def test_mixed_time_count_is_lower_bound_day_unit(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal(journals_dir, "2026-03-15", "no time entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="day",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) >= 1
        assert len(result["unknown_entries"]) == 1


class TestTermPresenceCaseInsensitive:
    """Contract fix: term_presence uses case-insensitive substring matching."""

    def test_term_latin_case_insensitive(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "Late-Night coding session")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="term_presence=late-night",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) == 1


class TestEntityPresenceCaseInsensitive:
    """Contract fix: entity_presence matches aliases case-insensitively."""

    def test_entity_alias_case_insensitive(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "LATE-NIGHT gaming session")

        graph_yaml = (
            "entities:\n"
            "  - id: sleep_habit\n"
            "    type: concept\n"
            "    primary_name: Sleep Habit\n"
            "    aliases:\n"
            "      - late-night\n"
        )
        (sandbox / "entity_graph.yaml").write_text(graph_yaml, encoding="utf-8")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="entity_presence=sleep_habit",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) == 1


class TestClaimEnvelopeAndEvidencePack:
    """M02/A+: claim_envelope and evidence_pack additive output."""

    def test_journal_count_measurable_exact(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "test")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
            query="过去60天我写了几篇日志",
        )

        assert "claim_envelope" in result
        assert "evidence_pack" in result
        ce = result["claim_envelope"]
        assert ce["schema_version"] == "m02a.claim_envelope.v0"
        assert ce["claim_type"] == "measurable_exact"
        assert ce["source_command"] == "aggregate"
        assert ce["query"] == "过去60天我写了几篇日志"
        assert ce["metric"] == "journal_count"
        assert ce["value"] == result["result"]["count"]
        assert ce["denominator"] == result["result"]["denominator"]
        assert ce["exactness"] == result["result"]["exactness"]
        assert ce["confidence"] == result["result"]["confidence"]
        assert ce["evidence_pack_ref"] == "aggregate.evidence_pack"
        assert "time_range" in ce
        assert "predicate" in ce
        assert "limitations" in ce

        ep = result["evidence_pack"]
        assert ep["schema_version"] == "m02a.aggregate_evidence_pack.v0"
        assert ep["source_command"] == "aggregate"
        assert ep["query"] == "过去60天我写了几篇日志"
        assert "time_range" in ep
        assert "predicate" in ep
        assert "items" in ep
        assert len(ep["items"]) == 1
        item = ep["items"][0]
        assert item["role"] == "matched"
        assert item["path"] == "Journals/2026/03/life-index_2026-03-14_001.md"
        assert "\\" not in item["path"]
        assert not os.path.isabs(item["path"])
        assert "bucket" in item
        assert "index_node_ref" in item
        assert item["index_node_ref"]["type"] == "month"
        assert "page_info" in ep
        assert ep["page_info"]["has_more"] is False
        assert ep["page_info"]["cursor"] is None
        assert ep["page_info"]["cursor_hint"] is None

        # Phase 2B: aggregate must prove its own enumeration completeness via
        # the unified retrieval_coverage.v1 vocabulary (additive).
        cov = ep["retrieval_coverage"]
        assert cov["schema_version"] == "retrieval_coverage.v1"
        assert cov["status"] == "complete"
        assert cov["observed_total"] == cov["returned"] == len(ep["items"])
        assert cov["next_offset"] is None
        assert cov["partial_reasons"] == []
        assert cov["limits_applied"] == []

    def test_term_presence_measurable_approximate(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "今天又晚睡了")
        _write_journal(journals_dir, "2026-03-15", "今天按时睡觉了")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="day",
            predicate="term_presence=晚睡",
        )

        assert "claim_envelope" in result
        ce = result["claim_envelope"]
        assert ce["claim_type"] == "measurable_approximate"

        ep = result["evidence_pack"]
        items_by_path = {i["path"]: i for i in ep["items"]}
        assert len(items_by_path) == 2
        matched_item = items_by_path.get("Journals/2026/03/life-index_2026-03-14_001.md")
        assert matched_item is not None
        assert matched_item["role"] == "matched"
        excluded_item = items_by_path.get("Journals/2026/03/life-index_2026-03-15_001.md")
        assert excluded_item is not None
        assert excluded_item["role"] == "excluded"

    def test_entry_time_after_partial(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "some entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="entry_time_after=22:00",
        )

        assert "claim_envelope" in result
        ce = result["claim_envelope"]
        assert ce["claim_type"] == "measurable_partial"
        assert ce["value"] == 0

        ep = result["evidence_pack"]
        assert len(ep["items"]) == 1
        item = ep["items"][0]
        assert item["role"] == "unknown"
        assert item["reason"] == "no_time_field_available"

    def test_evidence_paths_no_backslashes_or_absolute(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "test")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        ep = result["evidence_pack"]
        for item in ep["items"]:
            assert "\\" not in item["path"], f"Backslash in path: {item['path']}"
            assert not os.path.isabs(item["path"]), f"Absolute path: {item['path']}"


class TestEntityPresenceClaimEvidenceShape:
    """M02/A+ hardening: entity_presence claim_envelope and evidence_pack shape."""

    def test_entity_presence_claim_envelope_shape(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "LATE-NIGHT gaming session")
        _write_journal(journals_dir, "2026-03-15", "normal day")

        graph_yaml = (
            "entities:\n"
            "  - id: sleep_habit\n"
            "    type: concept\n"
            "    primary_name: Sleep Habit\n"
            "    aliases:\n"
            "      - late-night\n"
        )
        (sandbox / "entity_graph.yaml").write_text(graph_yaml, encoding="utf-8")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entity_presence=sleep_habit",
        )

        assert result["success"] is True
        assert "claim_envelope" in result
        ce = result["claim_envelope"]
        assert ce["schema_version"] == "m02a.claim_envelope.v0"
        assert ce["claim_type"] == "measurable_approximate"
        assert ce["source_command"] == "aggregate"
        assert ce["metric"] == "entity_presence_count"
        assert ce["value"] == 1
        assert ce["exactness"] == "approximate"
        assert ce["confidence"] == "medium"
        assert ce["evidence_pack_ref"] == "aggregate.evidence_pack"
        assert "limitations" in ce
        assert any("recall-backed" in lim for lim in ce["limitations"])

    def test_entity_presence_evidence_pack_shape(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "LATE-NIGHT gaming session")
        _write_journal(journals_dir, "2026-03-15", "normal day")

        graph_yaml = (
            "entities:\n"
            "  - id: sleep_habit\n"
            "    type: concept\n"
            "    primary_name: Sleep Habit\n"
            "    aliases:\n"
            "      - late-night\n"
        )
        (sandbox / "entity_graph.yaml").write_text(graph_yaml, encoding="utf-8")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entity_presence=sleep_habit",
        )

        assert "evidence_pack" in result
        ep = result["evidence_pack"]
        assert ep["schema_version"] == "m02a.aggregate_evidence_pack.v0"
        assert len(ep["items"]) == 2
        matched_items = [i for i in ep["items"] if i["role"] == "matched"]
        excluded_items = [i for i in ep["items"] if i["role"] == "excluded"]
        assert len(matched_items) == 1
        assert len(excluded_items) == 1
        assert "2026-03-14" in matched_items[0]["path"]
        assert "2026-03-15" in excluded_items[0]["path"]
        for item in ep["items"]:
            assert "\\" not in item["path"]
            assert not os.path.isabs(item["path"])
            assert "index_node_ref" in item
            assert item["index_node_ref"]["type"] == "month"
        assert ep["page_info"]["has_more"] is False

        # Phase 2B: coverage authority present alongside page_info (additive).
        cov = ep["retrieval_coverage"]
        assert cov["schema_version"] == "retrieval_coverage.v1"
        assert cov["status"] == "complete"
        assert cov["observed_total"] == cov["returned"] == len(ep["items"])
        assert cov["next_offset"] is None
        assert cov["partial_reasons"] == []
        assert cov["limits_applied"] == []


class TestScanJournalsExcludesRevisions:
    """M03: _scan_journals must exclude files under .revisions directories."""

    def test_revisions_excluded_from_journal_count(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "current entry")

        rev_dir = journals_dir / "2026" / "03" / ".revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)
        rev_path = rev_dir / "life-index_2026-03-14_999_revision.md"
        rev_path.write_text(
            "---\ndate: 2026-03-14\n---\n\n# Revision\n\nold content\n",
            encoding="utf-8",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) == 1
        assert ".revisions" not in result["matched_entries"][0]

    def test_revisions_excluded_from_evidence_pack(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "current entry")

        rev_dir = journals_dir / "2026" / "03" / ".revisions"
        rev_dir.mkdir(parents=True, exist_ok=True)
        rev_path = rev_dir / "life-index_2026-03-14_999_revision.md"
        rev_path.write_text(
            "---\ndate: 2026-03-14\n---\n\n# Revision\n\nold content\n",
            encoding="utf-8",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="journal_count",
        )

        for p in result["evidence_paths"]:
            assert ".revisions" not in p, f"Revision path in evidence_paths: {p}"

        ep = result["evidence_pack"]
        for item in ep["items"]:
            assert ".revisions" not in item["path"], f"Revision in evidence_pack: {item['path']}"


class TestEmptyAggregateClaimEvidenceShape:
    """M02/A+ hardening: empty aggregate result claim_envelope and evidence_pack."""

    def test_empty_journal_count_claim_envelope(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 0
        assert result["result"]["exactness"] == "exact"
        assert result["matched_entries"] == []
        assert result["excluded_entries"] == []
        assert result["unknown_entries"] == []
        assert result["evidence_paths"] == []

        assert "claim_envelope" in result
        ce = result["claim_envelope"]
        assert ce["schema_version"] == "m02a.claim_envelope.v0"
        assert ce["claim_type"] == "measurable_exact"
        assert ce["value"] == 0
        assert ce["denominator"] == result["result"]["denominator"]
        assert ce["exactness"] == "exact"
        assert ce["evidence_pack_ref"] == "aggregate.evidence_pack"

    def test_empty_journal_count_evidence_pack(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        assert "evidence_pack" in result
        ep = result["evidence_pack"]
        assert ep["schema_version"] == "m02a.aggregate_evidence_pack.v0"
        assert ep["items"] == []
        assert ep["page_info"]["has_more"] is False
        assert ep["page_info"]["cursor"] is None

        # Phase 2B: an empty scan is a trivially complete enumeration.
        cov = ep["retrieval_coverage"]
        assert cov["schema_version"] == "retrieval_coverage.v1"
        assert cov["status"] == "complete"
        assert cov["observed_total"] == cov["returned"] == 0
        assert cov["next_offset"] is None
        assert cov["partial_reasons"] == []
        assert cov["limits_applied"] == []

    def test_empty_term_presence_claim_envelope(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="term_presence=晚睡",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 0

        assert "claim_envelope" in result
        ce = result["claim_envelope"]
        assert ce["claim_type"] == "measurable_approximate"
        assert ce["value"] == 0

        ep = result["evidence_pack"]
        assert ep["items"] == []


class TestFieldEqualsScalarMatch:
    """RED: field_equals=topic:work matches scalar frontmatter values."""

    def test_matches_scalar_topic_work(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(
            journals_dir,
            "2026-03-14",
            "work entry",
            extra_frontmatter="topic: work\n",
        )
        _write_journal(
            journals_dir,
            "2026-03-15",
            "life entry",
            extra_frontmatter="topic: life\n",
        )
        _write_journal(
            journals_dir,
            "2026-03-16",
            "another work",
            extra_frontmatter="topic: work\n",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-16",
            unit="entry",
            predicate="field_equals=topic:work",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "exact"
        assert result["result"]["confidence"] == "high"
        assert result["result"]["count"] == 2
        assert len(result["matched_entries"]) == 2
        assert len(result["excluded_entries"]) == 1
        assert result["metric"] == "field_equals_count"

    def test_predicate_contains_field_and_value(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(
            journals_dir,
            "2026-03-14",
            "entry",
            extra_frontmatter="topic: work\n",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=topic:work",
        )

        assert result["success"] is True
        assert result["predicate"]["field"] == "topic"
        assert result["predicate"]["value"] == "work"

    def test_case_insensitive_scalar_match(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(
            journals_dir,
            "2026-03-14",
            "entry",
            extra_frontmatter="topic: Work\n",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=topic:WORK",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1

    def test_no_match_returns_zero(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(
            journals_dir,
            "2026-03-14",
            "entry",
            extra_frontmatter="topic: life\n",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=topic:work",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 0
        assert len(result["excluded_entries"]) == 1

    def test_missing_field_excluded(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "no topic field")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=topic:work",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 0
        assert len(result["excluded_entries"]) == 1


class TestFieldEqualsListMatch:
    """RED: field_equals matches list frontmatter values if any item equals."""

    def test_matches_list_item(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        year, month, day = "2026", "03", "14"
        d = journals_dir / year / month
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"life-index_{year}-{month}-{day}_001.md"
        fm = (
            f"---\ndate: {year}-{month}-{day}\n"
            f"tags:\n  - python\n  - work\n  - ai\n---\n\n# Test\n\nentry\n"
        )
        path.write_text(fm, encoding="utf-8")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=tags:work",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1
        assert len(result["matched_entries"]) == 1

    def test_list_no_match(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        year, month, day = "2026", "03", "14"
        d = journals_dir / year / month
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"life-index_{year}-{month}-{day}_001.md"
        fm = (
            f"---\ndate: {year}-{month}-{day}\n"
            f"tags:\n  - python\n  - life\n---\n\n# Test\n\nentry\n"
        )
        path.write_text(fm, encoding="utf-8")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=tags:work",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 0

    def test_list_case_insensitive(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        year, month, day = "2026", "03", "14"
        d = journals_dir / year / month
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"life-index_{year}-{month}-{day}_001.md"
        fm = (
            f"---\ndate: {year}-{month}-{day}\n"
            f"tags:\n  - Python\n  - AI\n---\n\n# Test\n\nentry\n"
        )
        path.write_text(fm, encoding="utf-8")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=tags:python",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1


class TestFieldEqualsValidation:
    """RED: field_equals rejects invalid field names."""

    def test_invalid_field_name_rejected(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=invalid-field:value",
        )
        assert result["success"] is False

    def test_field_starts_with_digit_rejected(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=0field:value",
        )
        assert result["success"] is False

    def test_missing_value_rejected(self, sandbox: Path):
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=topic",
        )
        assert result["success"] is False


class TestFieldEqualsClaimEnvelopeShape:
    """field_equals claim_envelope and evidence_pack shape."""

    def test_claim_envelope_measurable_exact(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(
            journals_dir,
            "2026-03-14",
            "entry",
            extra_frontmatter="topic: work\n",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="field_equals=topic:work",
        )

        assert result["success"] is True
        ce = result["claim_envelope"]
        assert ce["claim_type"] == "measurable_exact"
        assert ce["value"] == 1
        assert ce["metric"] == "field_equals_count"

        ep = result["evidence_pack"]
        assert len(ep["items"]) == 1
        item = ep["items"][0]
        assert item["role"] == "matched"


class TestIndexNodeRefReusesNavigation:
    """T2 RED: index_node_ref_for_date must reuse navigation helper."""

    def test_ref_output_has_type_id_path_keys(self) -> None:
        from tools.aggregate.claim_envelope import index_node_ref_for_date

        ref = index_node_ref_for_date("2026-03-14")
        assert ref is not None
        assert ref["type"] == "month"
        assert ref["id"] == "Journals/2026/03"
        assert ref["path"] == "Journals/2026/03/index_2026-03.md"

    def test_ref_delegates_to_navigation_lookup(self) -> None:
        import tools.aggregate.claim_envelope as ce_mod

        assert ce_mod.index_node_ref_for_date("2026-03-14") == (
            ce_mod._nav_index_node_ref_for_date("2026-03-14")
        )

    def test_ref_preserves_existing_public_shape(self) -> None:
        from tools.aggregate.claim_envelope import index_node_ref_for_date

        ref = index_node_ref_for_date("2026-01-05")
        assert ref is not None
        assert ref["type"] == "month"
        assert "2026" in ref["id"]
        assert "01" in ref["id"]
        assert "index_2026-01" in ref["path"]
        assert "node_id" in ref
        assert ref["node_id"] == "month:2026-01"


class TestEvidencePackIndexScope:
    """RED step 5: cross-month/cross-year evidence_pack must have index_scope."""

    def test_cross_month_index_scope(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-15", "jan entry")
        _write_journal(journals_dir, "2026-02-10", "feb entry")
        _write_journal(journals_dir, "2026-03-05", "mar entry")

        result = run_aggregate(
            range_str="2026-01-01..2026-03-31",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert "evidence_pack" in result
        ep = result["evidence_pack"]
        assert "index_scope" in ep

        scope = ep["index_scope"]
        assert scope["type"] == "month_range"
        assert "refs" in scope
        assert isinstance(scope["refs"], list)

        ref_node_ids = [r["node_id"] for r in scope["refs"]]
        assert "month:2026-01" in ref_node_ids
        assert "month:2026-02" in ref_node_ids
        assert "month:2026-03" in ref_node_ids

        assert "note" in scope
        assert "navigation anchors" in scope["note"]

    def test_cross_year_index_scope(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2025-12-20", "dec entry")
        _write_journal(journals_dir, "2026-01-05", "jan entry")

        result = run_aggregate(
            range_str="2025-12-01..2026-01-31",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        ep = result["evidence_pack"]
        assert "index_scope" in ep

        scope = ep["index_scope"]
        ref_node_ids = [r["node_id"] for r in scope["refs"]]
        assert "month:2025-12" in ref_node_ids
        assert "month:2026-01" in ref_node_ids

    def test_index_scope_preserves_items_and_refs(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-15", "jan entry")
        _write_journal(journals_dir, "2026-02-10", "feb entry")

        result = run_aggregate(
            range_str="2026-01-01..2026-02-28",
            unit="entry",
            predicate="journal_count",
        )

        ep = result["evidence_pack"]
        assert len(ep["items"]) == 2
        for item in ep["items"]:
            assert "index_node_ref" in item
            assert "node_id" in item["index_node_ref"]

        scope = ep["index_scope"]
        assert len(scope["refs"]) == 2

    def test_index_scope_does_not_filter_evidence(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-15", "jan entry")
        _write_journal(journals_dir, "2026-03-05", "mar entry")

        result = run_aggregate(
            range_str="2026-01-01..2026-03-31",
            unit="entry",
            predicate="journal_count",
        )

        ep = result["evidence_pack"]
        assert len(ep["items"]) == 2
        evidence_paths = {item["path"] for item in ep["items"]}
        assert any("2026-01" in p for p in evidence_paths)
        assert any("2026-03" in p for p in evidence_paths)

    def test_single_month_index_scope(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "test")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        ep = result["evidence_pack"]
        assert "index_scope" in ep
        scope = ep["index_scope"]
        assert len(scope["refs"]) == 1
        assert scope["refs"][0]["node_id"] == "month:2026-03"

    def test_empty_result_index_scope(self, sandbox: Path) -> None:
        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="journal_count",
        )

        ep = result["evidence_pack"]
        assert "index_scope" in ep
        scope = ep["index_scope"]
        assert len(scope["refs"]) == 1
        assert scope["refs"][0]["node_id"] == "month:2026-03"


class TestMonthDirectoryCandidateIterator:
    """TDD 2 RED: _scan_journals must enumerate candidates from inclusive month directories.

    The month prefilter reduces candidate file traversal to inclusive month
    directories only, but still applies final per-entry date filtering.
    Entries outside the date range but within an overlapping month dir may be
    scanned but must be filtered out in the final result.
    """

    def test_only_inclusive_months_scanned(self, sandbox: Path, monkeypatch) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-15", "jan entry")
        _write_journal(journals_dir, "2026-02-10", "feb entry")
        _write_journal(journals_dir, "2026-03-05", "mar entry")
        _write_journal(journals_dir, "2026-04-01", "apr entry")
        parsed_paths: list[str] = []
        original_parse = aggregate_core._parse_journal_file

        def spy_parse(md_file, since, until, base_dir):
            parsed_paths.append(md_file.relative_to(base_dir).as_posix())
            return original_parse(md_file, since, until, base_dir)

        monkeypatch.setattr(aggregate_core, "_parse_journal_file", spy_parse)

        result = run_aggregate(
            range_str="2026-02-01..2026-03-31",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 2
        evidence = result["evidence_paths"]
        for p in evidence:
            assert "2026/01" not in p
            assert "2026/04" not in p
        assert parsed_paths == [
            "2026/02/life-index_2026-02-10_001.md",
            "2026/03/life-index_2026-03-05_001.md",
        ]

    def test_boundary_month_partial_overlap_included(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-02-01", "feb start")
        _write_journal(journals_dir, "2026-02-28", "feb end")
        _write_journal(journals_dir, "2026-03-01", "mar start")

        result = run_aggregate(
            range_str="2026-02-15..2026-03-01",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 2
        for p in result["matched_entries"]:
            assert "life-index_2026-02-01_001.md" not in p

    def test_cross_year_month_range(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2025-12-20", "dec entry")
        _write_journal(journals_dir, "2026-01-05", "jan entry")
        _write_journal(journals_dir, "2026-02-10", "feb entry")

        result = run_aggregate(
            range_str="2025-12-15..2026-01-31",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 2
        for p in result["evidence_paths"]:
            assert "2026/02" not in p

    def test_single_month_no_extra_dirs_scanned(self, sandbox: Path) -> None:
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "target")
        _write_journal(journals_dir, "2026-04-01", "next month")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1
        for p in result["evidence_paths"]:
            assert "2026/04" not in p


class TestMonthPrefilterSpy:
    """Review fix: directly prove out-of-range month files are never parsed."""

    def test_out_of_range_month_files_not_parsed(self, sandbox: Path, monkeypatch) -> None:
        import tools.aggregate.core as agg_core

        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-15", "jan entry")
        _write_journal(journals_dir, "2026-02-10", "feb target")
        _write_journal(journals_dir, "2026-03-05", "mar target")
        _write_journal(journals_dir, "2026-04-01", "apr entry")

        parsed_paths: list[str] = []
        original_parse = agg_core._parse_journal_file

        def _spy_parse(md_file, since, until, journals_dir_arg):
            parsed_paths.append(str(md_file).replace("\\", "/"))
            return original_parse(md_file, since, until, journals_dir_arg)

        monkeypatch.setattr(agg_core, "_parse_journal_file", _spy_parse)

        result = run_aggregate(
            range_str="2026-02-01..2026-03-31",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 2

        for path in parsed_paths:
            assert "2026/01" not in path, f"Out-of-range Jan file was parsed: {path}"
            assert "2026/04" not in path, f"Out-of-range Apr file was parsed: {path}"

    def test_cross_month_boundary_only_relevant_months_parsed(
        self, sandbox: Path, monkeypatch
    ) -> None:
        import tools.aggregate.core as agg_core

        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-01-20", "jan")
        _write_journal(journals_dir, "2026-02-28", "feb boundary")
        _write_journal(journals_dir, "2026-03-01", "mar boundary")
        _write_journal(journals_dir, "2026-04-15", "apr")

        parsed_paths: list[str] = []
        original_parse = agg_core._parse_journal_file

        def _spy_parse(md_file, since, until, journals_dir_arg):
            parsed_paths.append(str(md_file).replace("\\", "/"))
            return original_parse(md_file, since, until, journals_dir_arg)

        monkeypatch.setattr(agg_core, "_parse_journal_file", _spy_parse)

        result = run_aggregate(
            range_str="2026-02-28..2026-03-01",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 2

        for path in parsed_paths:
            assert "2026/01" not in path
            assert "2026/04" not in path
        assert any("2026/02" in p for p in parsed_paths)
        assert any("2026/03" in p for p in parsed_paths)

    def test_month_prefilter_uses_index_ref_path_when_id_is_absent(
        self, sandbox: Path, monkeypatch
    ) -> None:
        import tools.aggregate.core as agg_core

        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "target")

        monkeypatch.setattr(
            agg_core,
            "_nav_index_node_refs_for_range",
            lambda _since, _until: [
                {
                    "type": "month",
                    "node_id": "month:2026-03",
                    "path": "Journals/2026/03/index_2026-03.md",
                }
            ],
        )

        result = run_aggregate(
            range_str="2026-03-01..2026-03-31",
            unit="entry",
            predicate="journal_count",
        )

        assert result["success"] is True
        assert result["result"]["count"] == 1


class TestPartialUnknownSemantics:
    """RED 2: entry_time_after with mixed timed/untimed entries returns partial bounds.

    When some entries have time data and others don't, the aggregate must
    return a confirmed lower-bound count with auditable partial semantics
    instead of fabricating zero. exactness='partial', and additive bound
    fields must be present.
    """

    def test_mixed_time_entry_unit_partial_count(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal(journals_dir, "2026-03-15", "no time entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 1
        assert result["result"]["count_semantics"] == "partial_lower_bound"
        assert result["result"]["min_count"] == 1
        assert result["result"]["max_count"] == 2
        assert result["result"]["unknown_count"] == 1
        assert result["result"]["unknown_bucket_count"] == 1
        assert len(result["matched_entries"]) == 1
        assert len(result["unknown_entries"]) == 1

    def test_mixed_time_day_unit_partial_count(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal(journals_dir, "2026-03-15", "no time entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="day",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 1
        assert result["result"]["min_count"] == 1
        assert result["result"]["max_count"] == 2
        assert result["result"]["unknown_count"] == 1
        assert result["result"]["unknown_bucket_count"] == 1

    def test_unknown_same_day_as_matched_does_not_inflate_day_max(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        month_dir = journals_dir / "2026" / "03"
        unknown_path = month_dir / "life-index_2026-03-14_002.md"
        unknown_path.write_text(
            "---\n"
            "date: 2026-03-14\n"
            "title: Same Day No Time\n"
            "---\n\n"
            "# Same Day No Time\n\n"
            "same day no time entry\n",
            encoding="utf-8",
        )

        result = run_aggregate(
            range_str="2026-03-14..2026-03-14",
            unit="day",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 1
        assert result["result"]["min_count"] == 1
        assert result["result"]["max_count"] == 1
        assert result["result"]["unknown_count"] == 1
        assert result["result"]["unknown_bucket_count"] == 1

    def test_all_unknown_returns_partial(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal(journals_dir, "2026-03-14", "some entry")
        _write_journal(journals_dir, "2026-03-15", "another entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="day",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "partial"
        assert result["result"]["count"] == 0
        assert result["result"]["min_count"] == 0
        assert result["result"]["max_count"] == 2
        assert result["result"]["unknown_count"] == 2
        assert result["result"]["unknown_bucket_count"] == 2
        assert result["result"]["count_semantics"] == "partial_lower_bound"

    def test_partial_claim_envelope_type(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal(journals_dir, "2026-03-15", "no time entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        ce = result["claim_envelope"]
        assert ce["claim_type"] == "measurable_partial"
        assert ce["exactness"] == "partial"
        assert ce["value"] == 1
        assert "min_count" in ce
        assert "max_count" in ce
        assert ce["min_count"] == 1
        assert ce["max_count"] == 2

    def test_all_timed_stays_exact(self, sandbox: Path):
        journals_dir = sandbox / "Journals"
        _write_journal_with_time(journals_dir, "2026-03-14", "23:30:00", "late entry")
        _write_journal_with_time(journals_dir, "2026-03-15", "10:00:00", "early entry")

        result = run_aggregate(
            range_str="2026-03-14..2026-03-15",
            unit="entry",
            predicate="entry_time_after=22:00",
        )

        assert result["success"] is True
        assert result["result"]["exactness"] == "exact"
        assert result["result"]["count"] == 1
        assert "count_semantics" not in result["result"]
        assert "min_count" not in result["result"]
        assert "max_count" not in result["result"]
