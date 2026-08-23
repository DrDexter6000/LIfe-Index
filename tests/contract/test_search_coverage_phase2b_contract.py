#!/usr/bin/env python3
"""Phase 2B RED→GREEN contract: unified coverage vocabulary on aggregate + index-tree.

The aggregate T3 slice below is copied MECHANICALLY from the read-only evidence
commit ``36fd6a16e941f0826983c9e0f1f9c5dc043914cd`` ::
``tests/contract/test_search_coverage_phase0_contract.py`` — T3 slice at source
lines 254-290 (``test_t3_aggregate_evidence_must_surface_complete_coverage``)
plus its dependency helpers at source lines 24-102 (``_COVERAGE_SCHEMA_VERSION``,
``_is_int``, ``_is_coverage_object``, ``find_coverage``,
``_require_complete_coverage``). Assertions are unchanged from the evidence
source; no skip/xfail is applied. They RED on the unchanged base because
aggregate does not yet surface a ``retrieval_coverage.v1`` object, then walk
RED→GREEN as Phase 2B projects the unified coverage vocabulary onto aggregate
and index-tree.

The index-tree slices extend the same vocabulary to ``index-tree discover`` /
``navigate``: a present ``retrieval_coverage.v1`` object and an ``exhaustive``
flag derived from collection facts instead of hardcoded ``True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

_COVERAGE_SCHEMA_VERSION = "retrieval_coverage.v1"


# ── retrieval-coverage discovery (contract: retrieval_coverage.v1) ──────────


def _is_int(value: Any) -> bool:
    """An actual int, excluding the bool subtype."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_coverage_object(obj: Any) -> bool:
    """Match the strongly-typed ``retrieval_coverage.v1`` field set.

    The object may live under any envelope path (the nesting key is not
    pre-fixed). Only the approved schema below is accepted::

        schema_version: "retrieval_coverage.v1"
        status: "complete" | "partial"
        observed_total: int
        returned: int
        next_offset: int | None
        partial_reasons: list
        limits_applied: list
    """
    if not isinstance(obj, dict):
        return False
    if obj.get("schema_version") != _COVERAGE_SCHEMA_VERSION:
        return False
    return (
        obj.get("status") in {"complete", "partial"}
        and _is_int(obj.get("observed_total"))
        and _is_int(obj.get("returned"))
        and (obj.get("next_offset") is None or _is_int(obj.get("next_offset")))
        and isinstance(obj.get("partial_reasons"), list)
        and isinstance(obj.get("limits_applied"), list)
    )


def find_coverage(envelope: Any) -> dict[str, Any] | None:
    """Recursively locate the retrieval-coverage object, if present."""
    if isinstance(envelope, dict):
        if _is_coverage_object(envelope):
            return envelope
        for value in envelope.values():
            found = find_coverage(value)
            if found is not None:
                return found
    elif isinstance(envelope, list):
        for value in envelope:
            found = find_coverage(value)
            if found is not None:
                return found
    return None


def _require_complete_coverage(envelope: Any) -> None:
    """A complete retrieval must prove it via ``retrieval_coverage.v1``.

    ``complete`` means the retrieval truthfully observed and returned the same
    set with no remainder: ``observed_total == returned``, ``next_offset`` is
    null, and both ``partial_reasons`` and ``limits_applied`` are empty.
    """
    coverage = find_coverage(envelope)
    assert coverage is not None, "retrieval coverage (retrieval_coverage.v1) is missing"
    assert coverage["status"] == "complete"
    assert coverage["observed_total"] == coverage["returned"]
    assert coverage["next_offset"] is None
    assert coverage["partial_reasons"] == []
    assert coverage["limits_applied"] == []


# ── T3: aggregate evidence must surface a complete coverage ─────────────────


def test_t3_aggregate_evidence_must_surface_complete_coverage(
    isolated_data_dir: Path,
) -> None:
    """A real aggregate scan with no remainder must prove complete coverage."""
    from tools.aggregate.core import run_aggregate

    journals_dir = isolated_data_dir / "Journals" / "2026" / "03"
    journals_dir.mkdir(parents=True, exist_ok=True)
    for day in (1, 2, 3):
        (journals_dir / f"life-index_2026-03-{day:02d}_001.md").write_text(
            "---\n"
            f"date: 2026-03-{day:02d}\n"
            "topic: [work]\n"
            "---\n\n"
            "# note\n\n"
            "Late session notes.\n",
            encoding="utf-8",
        )

    result = run_aggregate(
        range_str="2026-03-01..2026-03-31",
        unit="day",
        predicate="journal_count",
        query="how many work days in march",
    )

    # Real current behavior: aggregate scans the full range with no remainder
    # (asserted directly on the value, not via a default).
    assert result["evidence_pack"]["page_info"]["has_more"] is False

    _require_complete_coverage(result)


# ── Phase 2B index-tree: unified coverage vocabulary on discover/navigate ────


def _write_index_tree_fixture_journal(data_dir: Path, *, date_str: str, seq: int) -> str:
    """Write one minimal journal under ``Journals/YYYY/MM/`` and return its rel_path."""
    year, month, _day = date_str.split("-")
    journal_dir = data_dir / "Journals" / year / month
    journal_dir.mkdir(parents=True, exist_ok=True)
    filename = f"life-index_{date_str}_{seq:03d}.md"
    (journal_dir / filename).write_text(
        "---\n"
        f"date: {date_str}\n"
        "topic: [work]\n"
        "---\n\n"
        "# note\n\n"
        f"Index-tree fixture note {seq}.\n",
        encoding="utf-8",
    )
    return f"Journals/{year}/{month}/{filename}"


def test_index_tree_discover_surfaces_unified_coverage_and_derived_exhaustive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """discover must carry retrieval_coverage.v1 and derive ``exhaustive`` from facts."""
    from tools.index_tree.core import build_discover_payload

    data_dir = tmp_path / "Life-Index"
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    expected_paths = {
        _write_index_tree_fixture_journal(data_dir, date_str="2026-03-02", seq=1),
        _write_index_tree_fixture_journal(data_dir, date_str="2026-03-05", seq=2),
    }

    payload = build_discover_payload(date_from="2026-03", date_to="2026-03")

    assert payload["success"] is True
    data = payload["data"]
    # exhaustive must be DERIVED from collection facts (True on a clean scan).
    assert data["exhaustive"] is True

    # The unified-vocabulary completeness authority must be present.
    coverage = find_coverage(data)
    assert coverage is not None, "index-tree.discover lacks a retrieval_coverage.v1 object"
    assert coverage["schema_version"] == _COVERAGE_SCHEMA_VERSION
    assert coverage["status"] == "complete"
    assert coverage["observed_total"] == len(expected_paths)
    assert coverage["returned"] == len(expected_paths)
    assert coverage["next_offset"] is None
    assert coverage["partial_reasons"] == []
    assert coverage["limits_applied"] == []


def test_index_tree_navigate_surfaces_unified_coverage_and_derived_exhaustive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """navigate must carry retrieval_coverage.v1 and derive ``exhaustive`` from facts."""
    from tools.index_tree.core import build_navigate_payload

    data_dir = tmp_path / "Life-Index"
    monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
    expected_paths = {
        _write_index_tree_fixture_journal(data_dir, date_str="2026-04-01", seq=1),
        _write_index_tree_fixture_journal(data_dir, date_str="2026-04-08", seq=2),
    }

    payload = build_navigate_payload(date_from="2026-04", date_to="2026-04")

    assert payload["success"] is True
    data = payload["data"]
    # exhaustive must be DERIVED from collection facts (True on a clean scan).
    assert data["exhaustive"] is True
    assert data["count"] == len(expected_paths)

    # The unified-vocabulary completeness authority must be present and describe
    # this response's own enumeration facts.
    coverage = find_coverage(data)
    assert coverage is not None, "index-tree.navigate lacks a retrieval_coverage.v1 object"
    assert coverage["schema_version"] == _COVERAGE_SCHEMA_VERSION
    assert coverage["status"] == "complete"
    assert coverage["observed_total"] == len(expected_paths)
    assert coverage["returned"] == len(expected_paths)
    assert coverage["next_offset"] is None
    assert coverage["partial_reasons"] == []
    assert coverage["limits_applied"] == []


# ── Phase 2B numerical invariance: coverage projection must not move counts ───


def test_aggregate_counts_and_buckets_invariant_under_coverage_projection(
    isolated_data_dir: Path,
) -> None:
    """Hand-computed aggregate values must be byte-identical before/after 2B.

    Every expected number below is computed BY HAND from the fixture (four
    journals in March 2026), not read back from the implementation, so any
    drift in counts, buckets, matched/excluded sets, or denominators caused by
    the coverage projection fails this test.
    """
    from tools.aggregate.core import run_aggregate

    journals_dir = isolated_data_dir / "Journals" / "2026" / "03"
    journals_dir.mkdir(parents=True, exist_ok=True)
    # Days 1-2 carry the "Fixture note" body substring; days 3-4 deliberately
    # do not, so term_presence can discriminate matched from excluded entries.
    fixture = {
        1: ("topic: [work]", "Fixture note"),
        2: ("topic: [work]", "Fixture note"),
        3: ("topic: [life]", "Different note"),
        4: ("", "Different note"),
    }
    for day, (topic_line, body_phrase) in fixture.items():
        (journals_dir / f"life-index_2026-03-{day:02d}_001.md").write_text(
            "---\n"
            f"date: 2026-03-{day:02d}\n"
            f"{topic_line}\n"
            "---\n\n"
            "# note\n\n"
            f"{body_phrase} {day}.\n",
            encoding="utf-8",
        )

    path_1 = "Journals/2026/03/life-index_2026-03-01_001.md"
    path_2 = "Journals/2026/03/life-index_2026-03-02_001.md"
    path_3 = "Journals/2026/03/life-index_2026-03-03_001.md"
    path_4 = "Journals/2026/03/life-index_2026-03-04_001.md"

    # journal_count, unit=day: one bucket per journaled day, each count 1/1.
    day_result = run_aggregate(
        range_str="2026-03-01..2026-03-31",
        unit="day",
        predicate="journal_count",
    )
    assert day_result["result"]["count"] == 4
    assert day_result["result"]["denominator"] == 31
    assert day_result["matched_entries"] == [path_1, path_2, path_3, path_4]
    assert day_result["excluded_entries"] == []
    assert day_result["buckets"] == [
        {
            "key": "2026-03-01",
            "count": 1,
            "total": 1,
            "evidence_paths": [path_1],
        },
        {
            "key": "2026-03-02",
            "count": 1,
            "total": 1,
            "evidence_paths": [path_2],
        },
        {
            "key": "2026-03-03",
            "count": 1,
            "total": 1,
            "evidence_paths": [path_3],
        },
        {
            "key": "2026-03-04",
            "count": 1,
            "total": 1,
            "evidence_paths": [path_4],
        },
    ]
    assert [item["path"] for item in day_result["evidence_pack"]["items"]] == [
        path_1,
        path_2,
        path_3,
        path_4,
    ]

    # journal_count, unit=month: exactly one non-empty bucket of 4 entries.
    month_result = run_aggregate(
        range_str="2026-03-01..2026-03-31",
        unit="month",
        predicate="journal_count",
    )
    assert month_result["result"]["count"] == 1
    assert month_result["result"]["denominator"] == 1
    assert month_result["buckets"] == [
        {
            "key": "2026-03",
            "count": 4,
            "total": 4,
            "evidence_paths": [path_1, path_2, path_3, path_4],
        }
    ]

    # term_presence=work: substring match hits days 1-2 only.
    term_result = run_aggregate(
        range_str="2026-03-01..2026-03-31",
        unit="day",
        predicate="term_presence=Fixture note",
    )
    assert term_result["result"]["count"] == 2
    assert term_result["matched_entries"] == [path_1, path_2]
    assert term_result["excluded_entries"] == [path_3, path_4]

    # field_equals=topic:work: exact frontmatter match on days 1-2; the
    # non-matching value and the missing field both land in excluded.
    field_result = run_aggregate(
        range_str="2026-03-01..2026-03-31",
        unit="entry",
        predicate="field_equals=topic:work",
    )
    assert field_result["result"]["count"] == 2
    assert field_result["matched_entries"] == [path_1, path_2]
    assert field_result["excluded_entries"] == [path_3, path_4]

    # The coverage projection itself: observed == returned == 4 on this clean
    # fixture, no pagination, no partial reasons, no limits.
    coverage = day_result["evidence_pack"]["retrieval_coverage"]
    assert coverage["schema_version"] == _COVERAGE_SCHEMA_VERSION
    assert coverage["status"] == "complete"
    assert coverage["observed_total"] == 4
    assert coverage["returned"] == 4
    assert coverage["next_offset"] is None
    assert coverage["partial_reasons"] == []
    assert coverage["limits_applied"] == []
