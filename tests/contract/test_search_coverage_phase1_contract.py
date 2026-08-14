#!/usr/bin/env python3
"""Phase 1 RED→GREEN contract: M4 retrieval coverage + deterministic ranking.

This file is the Phase 1 corrective lock for the Life Index search retrieval
contract. The T1 (>100) and T4 (small complete) target assertions are copied
mechanically from the Phase 0 read-only evidence commit
(``36fd6a16`` :: ``test_search_coverage_phase0_contract.py``); they RED on the
unchanged base because the target behavior is missing, then walk RED→GREEN as
the retrieval layer materializes full coverage.

The reviewer-driven tests (a–d) lock the additional Phase 1 corrections:
effective token-match threshold = 0, full materialization before pagination, a
deterministic path tie-breaker, and an honest ``retrieval_coverage.v1`` object.

No production code is changed by this file; it only locks the contract.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tools.lib.search_constants import FTS_LIMIT

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


def _result_identity(item: dict[str, Any]) -> str:
    """Stable comparable identity for a candidate (matches orchestrator dedup)."""
    for key in ("rel_path", "path", "title"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


# ── synthetic journal helper ────────────────────────────────────────────────


def _write_body_only_journal(data_dir: Path, *, date_str: str, token: str, seq: int) -> str:
    """Write a journal whose ``token`` appears ONLY in the body (pure L3 hit).

    Returns the comparable repo-relative path (``rel_path``) of the written
    journal so callers can build the expected identity set.
    """
    year, month, _day = date_str.split("-")
    journal_dir = data_dir / "Journals" / year / month
    journal_dir.mkdir(parents=True, exist_ok=True)
    filename = f"life-index_{date_str}_{seq:03d}.md"
    (journal_dir / filename).write_text(
        "---\n"
        f"date: {date_str}\n"
        "topic: []\n"
        "tags: []\n"
        "people: []\n"
        "---\n\n"
        "# neutral note\n\n"
        f"Neutral fixture {seq} contains {token} in body only.\n",
        encoding="utf-8",
    )
    return f"Journals/{year}/{month}/{filename}"


def _write_two_line_body_journal(data_dir: Path, *, date_str: str, token: str, seq: int) -> str:
    """Write a journal whose ``token`` appears on two SEPARATE body lines.

    The L3 file-scan fallback scores one body match per line, so a token on two
    lines yields ``relevance = 2 * L3_BODY_MATCH_PER_HIT = 20``: above the L3
    admit floor (``L3_MIN_FALLBACK_RELEVANCE = 15``) but below the legacy
    ranking floor (``FTS_MIN_RELEVANCE = 25``). Such a low-relevance token-match
    is the canonical probe for the effective-threshold=0 contract.
    """
    year, month, _day = date_str.split("-")
    journal_dir = data_dir / "Journals" / year / month
    journal_dir.mkdir(parents=True, exist_ok=True)
    filename = f"life-index_{date_str}_{seq:03d}.md"
    (journal_dir / filename).write_text(
        "---\n"
        f"date: {date_str}\n"
        "topic: []\n"
        "tags: []\n"
        "people: []\n"
        "---\n\n"
        "# neutral note\n\n"
        f"{token} appears here on line one.\n\n"
        f"{token} appears again here on line three.\n",
        encoding="utf-8",
    )
    return f"Journals/{year}/{month}/{filename}"


def _write_titled_journal(
    data_dir: Path,
    *,
    date_str: str,
    title: str,
    body: str,
    seq: int,
) -> str:
    """Write a journal with an explicit title and body. Returns rel_path."""
    year, month, _day = date_str.split("-")
    journal_dir = data_dir / "Journals" / year / month
    journal_dir.mkdir(parents=True, exist_ok=True)
    filename = f"life-index_{date_str}_{seq:03d}.md"
    (journal_dir / filename).write_text(
        "---\n"
        f"date: {date_str}\n"
        f"title: {title}\n"
        "topic: []\n"
        "tags: []\n"
        "people: []\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return f"Journals/{year}/{month}/{filename}"


# ── T1: silent FTS truncation must surface a truthful complete coverage ─────


def test_t1_silent_fts_truncation_must_surface_truthful_coverage(
    isolated_data_dir: Path,
) -> None:
    """A population larger than FTS_LIMIT must still be fully enumerable.

    Today FTS silently caps retrieval at FTS_LIMIT and reports that cap as if it
    were the complete set, so this REDs at "only FTS_LIMIT rather than
    population". The permanent contract demands the full population be
    enumerable and the retrieval prove itself complete.
    """
    from tools.search_journals.__main__ import run_search
    from tools.lib.search_index import update_index

    token = "trunctoken"
    population = FTS_LIMIT + 20  # 120 body-only matches; FTS silently caps at FTS_LIMIT
    base = date(2026, 1, 1)
    expected_paths: set[str] = set()
    for i in range(population):
        expected_paths.add(
            _write_body_only_journal(
                isolated_data_dir,
                date_str=(base + timedelta(days=i)).isoformat(),
                token=token,
                seq=i + 1,
            )
        )
    assert update_index(incremental=False)["success"] is True

    result = run_search(query=token, limit=0, include_events=False)

    returned_identities = {_result_identity(item) for item in result["merged_results"]}

    # Permanent contract: every admitted candidate is reachable, the reported
    # total covers the full population, and the returned set is exactly the
    # population — then the retrieval must prove itself complete.
    assert len(returned_identities) == population
    assert result["total_matches"] == population
    assert returned_identities == expected_paths
    _require_complete_coverage(result)


# ── T4: a small complete token-match retrieval must surface complete coverage ─


def test_t4_small_token_match_must_surface_complete_coverage(
    isolated_data_dir: Path,
) -> None:
    """A small, genuinely complete token-match retrieval must prove it."""
    from tools.search_journals.__main__ import run_search
    from tools.lib.search_index import update_index

    token = "completetoken"
    expected_paths: set[str] = set()
    for seq, day in enumerate((2, 5, 8), start=1):
        expected_paths.add(
            _write_body_only_journal(
                isolated_data_dir, date_str=f"2026-02-{day:02d}", token=token, seq=seq
            )
        )
    assert update_index(incremental=False)["success"] is True

    result = run_search(query=token, limit=0, include_events=False)
    returned_identities = {_result_identity(item) for item in result["merged_results"]}

    # Permanent contract: exactly the three matches, no more and no fewer, with
    # the returned identity set exactly equal to the expected paths — then the
    # retrieval must prove itself complete.
    assert result["total_matches"] == 3
    assert returned_identities == expected_paths
    _require_complete_coverage(result)


# ── (a) effective token-match threshold = 0 (FTS + ranking) ──────────────────


def test_a_low_relevance_token_match_reachable_in_default_ranking(
    isolated_data_dir: Path,
) -> None:
    """A low-relevance token-match must survive the default full ranking path.

    The token appears on two separate body lines, so the L3 file-scan fallback
    assigns ``relevance = 20`` — below the legacy ranking floor (25) but a
    genuine token-match. With the effective token-match threshold = 0, the
    default ranking path must NOT drop it. RED on the unchanged base because the
    ranking layer's threshold (25) filters it out before pagination.
    """
    from tools.search_journals.__main__ import run_search

    token = "lowreltoken"
    _write_two_line_body_journal(isolated_data_dir, date_str="2026-01-05", token=token, seq=1)

    result = run_search(query=token, use_index=False, limit=0, include_events=False)

    returned_identities = {_result_identity(item) for item in result["merged_results"]}
    assert len(returned_identities) >= 1, (
        "low-relevance token-match (relevance 20) must be reachable in the default "
        "full ranking path; the ranking layer must not drop it via a nonzero threshold"
    )


# ── (b) path-ascending final tie-breaker; pagination must not overlap/skip ────


def test_b_path_ascending_tiebreaker_stable_across_pages(
    isolated_data_dir: Path,
) -> None:
    """Candidates that tie on every existing sort key resolve by path-ascending.

    Five body-only journals share the same score/tier/title-position, so the
    path-ascending tie-breaker is the only remaining ordering signal. The full
    (limit=0) set must be path-ascending, and paginating it (limit=2) must yield
    the same sequence with no overlap and no gap. RED on the unchanged base
    because the threshold (25) drops all relevance-20 matches, so no set is
    returned to order or paginate.
    """
    from tools.search_journals.__main__ import run_search

    token = "tietoken"
    base = date(2026, 1, 1)
    for i in range(5):
        _write_two_line_body_journal(
            isolated_data_dir,
            date_str=(base + timedelta(days=i)).isoformat(),
            token=token,
            seq=i + 1,
        )

    full = run_search(query=token, use_index=False, limit=0, include_events=False)
    full_ids = [_result_identity(item) for item in full["merged_results"]]

    assert len(full_ids) == 5
    assert full_ids == sorted(
        full_ids
    ), "the full admitted set must be ordered path-ascending among score ties"

    page_ids: list[str] = []
    for page_offset in (0, 2, 4):
        page = run_search(
            query=token,
            use_index=False,
            limit=2,
            offset=page_offset,
            include_events=False,
        )
        page_ids.extend(_result_identity(item) for item in page["merged_results"])

    assert page_ids == full_ids, (
        "paginating the same deterministic query must reproduce the full order "
        "with no overlap and no gap"
    )


# ── (c) nonzero-offset final page is NOT complete (target #5) ─────────────────


def test_c_nonzero_offset_final_page_is_not_complete(
    isolated_data_dir: Path,
) -> None:
    """A nonzero-offset final page must not falsely report ``complete``.

    With a population of three and page size two, the final page sits at
    offset=2 and returns one item (``next_offset`` is null — no mechanical
    continuation). Yet ``observed_total`` (3) != ``returned`` (1), so the
    retrieval must honestly report ``partial``; ``has_more`` (next_offset) only
    signals whether the same deterministic query can mechanically continue.
    RED on the unchanged base because no ``retrieval_coverage.v1`` object exists.
    """
    from tools.search_journals.__main__ import run_search

    token = "pagetoken"
    base = date(2026, 1, 1)
    for i in range(3):
        _write_two_line_body_journal(
            isolated_data_dir,
            date_str=(base + timedelta(days=i)).isoformat(),
            token=token,
            seq=i + 1,
        )

    final_page = run_search(query=token, use_index=False, limit=2, offset=2, include_events=False)

    coverage = find_coverage(final_page)
    assert coverage is not None, "retrieval coverage (retrieval_coverage.v1) is missing"
    assert coverage["status"] == "partial", (
        "a nonzero-offset final page must not claim complete even though " "next_offset is null"
    )
    assert coverage["observed_total"] == 3
    assert coverage["returned"] == 1
    assert coverage["next_offset"] is None
    # Any response window that does not carry the whole admitted set — including a
    # nonzero-offset final page — must list unread_page, and a binding presentation
    # limit must be recorded as result_limit:<n>.
    assert "unread_page" in coverage["partial_reasons"], (
        "a window that does not carry the whole admitted set must list unread_page, "
        "even when next_offset is null"
    )
    assert any(
        str(limit).startswith("result_limit:") for limit in coverage["limits_applied"]
    ), "a binding presentation limit must be recorded as result_limit:<n>"


# ── (d) explicit threshold: partial only when it actually excludes ────────────


def test_d_explicit_threshold_partial_only_when_it_excludes(
    isolated_data_dir: Path,
) -> None:
    """An explicit nonzero threshold marks partial only when it excludes >= 1.

    * d1: threshold 30 but the only match sits above it (title relevance 40) →
      excludes 0 → must NOT be partial, no ``threshold_excluded``.
    * d2: threshold 30 and the only match sits below it (body relevance 20) →
      excludes 1 → must be ``partial`` with ``threshold_excluded`` and an
      ``fts_threshold:`` limit applied.

    RED on the unchanged base because no ``retrieval_coverage.v1`` object exists
    and the base never counts threshold exclusions.
    """
    from tools.search_journals.core import hierarchical_search

    # d1: token in the title only → L3 relevance 40 (>= threshold 30), excludes 0.
    _write_titled_journal(
        isolated_data_dir,
        date_str="2026-02-02",
        title="thresholdtoken titled note",
        body="Neutral body without the search token.",
        seq=1,
    )
    result_above = hierarchical_search(
        query="thresholdtoken", use_index=False, fts_min_relevance=30
    )
    coverage_above = find_coverage(result_above)
    assert coverage_above is not None
    assert (
        coverage_above["status"] == "complete"
    ), "a threshold that excludes 0 candidates must NOT mark the retrieval partial"
    assert "threshold_excluded" not in coverage_above["partial_reasons"]

    # d2: token on two body lines → L3 relevance 20 (< threshold 30), excludes 1.
    _write_two_line_body_journal(
        isolated_data_dir, date_str="2026-02-09", token="excludedtoken", seq=2
    )
    result_below = hierarchical_search(query="excludedtoken", use_index=False, fts_min_relevance=30)
    coverage_below = find_coverage(result_below)
    assert coverage_below is not None
    assert coverage_below["status"] == "partial", (
        "a threshold that excludes >= 1 otherwise-matching candidate must mark "
        "the retrieval partial"
    )
    assert "threshold_excluded" in coverage_below["partial_reasons"]
    assert any(
        str(limit).startswith("fts_threshold:") for limit in coverage_below["limits_applied"]
    )


# ── (e) high-cardinality safety bound fails CLOSED via the error envelope ────


def test_e_high_cardinality_guard_fails_closed_via_error_envelope(
    isolated_data_dir: Path,
) -> None:
    """Reaching the safety bound must fail CLOSED, not raise or truncate.

    The high-cardinality backstop must NOT raise a bare RuntimeError or return a
    truncated subset that could be mistaken for the complete set. It must surface
    a closed, machine-readable resource failure through the EXISTING search error
    envelope: success=false, error.code=E0301, and a stable
    details.reason=retrieval_resource_bound. No merged_results subset and no
    false-complete coverage object may appear. RED on the unchanged parent
    candidate, which raises a bare RuntimeError.
    """
    from tools.search_journals.__main__ import run_search

    token = "guardtoken"
    for i in range(3):
        _write_two_line_body_journal(
            isolated_data_dir,
            date_str=f"2026-01-{i + 1:02d}",
            token=token,
            seq=i + 1,
        )

    with patch("tools.search_journals.keyword_pipeline.FTS_MAX_RETRIEVAL_BOUND", 2):
        result = run_search(query=token, use_index=False, limit=0, include_events=False)

    assert result["success"] is False
    error = result["error"]
    assert error["code"] == "E0301"
    assert error["details"]["reason"] == "retrieval_resource_bound"
    assert error["details"]["bound"] == 2
    assert error["details"]["observed"] == 3
    # Fail-closed: no truncated subset may be returned.
    assert result["merged_results"] == []
    # No false-complete coverage object may appear.
    coverage = find_coverage(result)
    assert coverage is None or coverage["status"] != "complete"


def test_e_cli_exits_nonzero_on_fail_closed_result() -> None:
    """A fail-closed result (success=false) must make the CLI exit nonzero.

    The guard produces success=false; main() maps success to the exit code, so a
    closed resource failure exits nonzero (never 0) via the clean envelope path
    rather than crashing. This locks the CLI wiring that the guard relies on.
    """
    import sys

    import tools.search_journals.__main__ as cli

    fail_closed = {
        "success": False,
        "error": {
            "code": "E0301",
            "message": "retrieval refused",
            "details": {"reason": "retrieval_resource_bound"},
            "recovery_strategy": "ask_user",
        },
        "merged_results": [],
        "total_matches": 0,
    }
    with (
        patch.object(sys, "argv", ["search"]),
        patch.object(cli, "run_search", return_value=fail_closed),
        patch.object(cli, "_emit_json"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            cli.main()
    assert excinfo.value.code != 0


# ── (f) a normal set at/below the bound stays complete (no false guard) ───────


def test_f_normal_set_below_bound_is_complete(isolated_data_dir: Path) -> None:
    """A set at or below the bound must stay fully complete (no false guard).

    The safety bound is a strict ``>`` backstop: a set sized exactly at the bound
    must NOT trigger fail-closed and must surface complete coverage. This is the
    complement to (e) — the guard must not false-fire on ordinary large sets.
    """
    from tools.search_journals.__main__ import run_search

    token = "safeboundtoken"
    for i in range(5):
        _write_two_line_body_journal(
            isolated_data_dir, date_str=f"2026-03-{i + 1:02d}", token=token, seq=i + 1
        )

    with patch("tools.search_journals.keyword_pipeline.FTS_MAX_RETRIEVAL_BOUND", 5):
        result = run_search(query=token, use_index=False, limit=0, include_events=False)

    assert result["success"] is True
    assert result["total_matches"] == 5
    _require_complete_coverage(result)


# ── (g) stale / un-refreshed index => partial + index_not_fresh ───────────────


def test_g_stale_unrefreshed_index_is_partial_with_index_not_fresh(
    isolated_data_dir: Path,
) -> None:
    """An un-refreshed stale index must mark the retrieval partial.

    When the index is stale AND the auto-update fails (auto_updated is not True),
    the retrieval cannot prove completeness: partial_reasons must contain
    index_not_fresh. (A self-healed index with auto_updated=True stays complete.)
    """
    from tools.lib.index_freshness import FreshnessReport
    from tools.search_journals.core import hierarchical_search

    token = "staletoken"
    _write_two_line_body_journal(isolated_data_dir, date_str="2026-01-05", token=token, seq=1)

    stale_report = FreshnessReport(
        fts_fresh=False,
        vector_fresh=True,
        overall_fresh=False,
        issues=["fts_index_older_than_corpus"],
    )
    with (
        patch("tools.lib.pending_writes.has_pending", return_value=False),
        patch(
            "tools.lib.index_freshness.check_full_freshness",
            return_value=stale_report,
        ),
        patch("tools.build_index.build_all", side_effect=RuntimeError("update failed")),
    ):
        result = hierarchical_search(query=token, use_index=False)

    coverage = find_coverage(result)
    assert coverage is not None
    assert coverage["status"] == "partial"
    assert "index_not_fresh" in coverage["partial_reasons"]


# ── (h) corpus change between pages must not be reported complete ─────────────


def test_h_corpus_change_between_pages_is_not_false_complete(
    isolated_data_dir: Path,
) -> None:
    """A response must not claim complete when the corpus changed between pages.

    Pagination assumes a stable corpus; the tool holds no snapshot/cursor
    authority. If the corpus grew between page 1 and page 2, page 2's coverage is
    recomputed against the CURRENT observed_total and must honestly report
    partial — never complete.
    """
    from tools.search_journals.__main__ import run_search

    token = "muttoken"
    base = date(2026, 2, 1)
    for i in range(3):
        _write_two_line_body_journal(
            isolated_data_dir,
            date_str=(base + timedelta(days=i)).isoformat(),
            token=token,
            seq=i + 1,
        )

    page1 = run_search(query=token, use_index=False, limit=2, offset=0, include_events=False)
    cov1 = find_coverage(page1)
    assert cov1["status"] == "partial"
    assert cov1["observed_total"] == 3

    # Corpus grows between pages — no snapshot/cursor authority is added.
    _write_two_line_body_journal(isolated_data_dir, date_str="2026-02-20", token=token, seq=4)

    page2 = run_search(query=token, use_index=False, limit=2, offset=2, include_events=False)
    cov2 = find_coverage(page2)
    assert (
        cov2["status"] != "complete"
    ), "after the corpus changed between pages, the response must not claim complete"
    assert cov2["observed_total"] == 4


# ── (i) L2 source cap (l2_truncated) projects to partial + source_cap ─────────


def test_i_source_cap_projects_partial_with_source_cap(
    isolated_data_dir: Path,
) -> None:
    """An L2 source cap (l2_truncated=True) must project to partial + source_cap.

    When the L2 metadata source was capped, the retrieval may have missed
    L2-only candidates, so coverage must be partial with source_cap and a stable
    l2_source_cap:<n> limit string derived from the existing l2_total_available
    field. A configured cap that excluded nothing (l2_truncated=False) records
    nothing. RED on the unchanged parent candidate, which never projects
    source_cap.
    """
    from tools.search_journals.core import hierarchical_search

    token = "capsrctoken"
    _write_two_line_body_journal(isolated_data_dir, date_str="2026-01-05", token=token, seq=1)

    capped_l2 = {"results": [], "truncated": True, "total_available": 50}
    with patch(
        "tools.search_journals.keyword_pipeline.search_l2_metadata",
        return_value=capped_l2,
    ):
        result = hierarchical_search(query=token, use_index=False)

    coverage = find_coverage(result)
    assert coverage is not None
    assert coverage["status"] == "partial"
    assert "source_cap" in coverage["partial_reasons"]
    assert any(str(limit).startswith("l2_source_cap:") for limit in coverage["limits_applied"])


# ── (j) legacy total_*/has_more are projections of the coverage authority ─────


def test_j_legacy_totals_are_projections_of_coverage(isolated_data_dir: Path) -> None:
    """Legacy totals must equal the coverage projections (no independent drift).

    ``total_matches``/``total_available`` mirror ``observed_total``; ``total_found``
    mirrors ``returned``; ``has_more`` mirrors ``next_offset is not None``. This
    must hold for both the full set and a paginated window, locking the
    single-authority projection so the legacy fields cannot drift from
    ``retrieval_coverage.v1``.
    """
    from tools.search_journals.__main__ import run_search

    token = "projtoken"
    base = date(2026, 4, 1)
    for i in range(5):
        _write_two_line_body_journal(
            isolated_data_dir,
            date_str=(base + timedelta(days=i)).isoformat(),
            token=token,
            seq=i + 1,
        )

    full = run_search(query=token, use_index=False, limit=0, include_events=False)
    cov = find_coverage(full)
    assert cov is not None
    assert full["total_matches"] == cov["observed_total"]
    assert full["total_available"] == cov["observed_total"]
    assert full["total_found"] == cov["returned"]
    assert full["has_more"] == (cov["next_offset"] is not None)

    page = run_search(query=token, use_index=False, limit=2, offset=0, include_events=False)
    covp = find_coverage(page)
    assert covp is not None
    assert page["total_matches"] == covp["observed_total"]
    assert page["total_available"] == covp["observed_total"]
    assert page["total_found"] == covp["returned"]
    assert page["has_more"] == (covp["next_offset"] is not None)
