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
    # nonzero-offset final page — must list unread_page. The window here is bounded
    # by the OFFSET, not the limit (limit 2 >= the 1 remaining candidate), so no
    # result_limit may be recorded: an offset-only final page is not a limit cap.
    assert "unread_page" in coverage["partial_reasons"], (
        "a window that does not carry the whole admitted set must list unread_page, "
        "even when next_offset is null"
    )
    assert not any(
        str(limit).startswith("result_limit:") for limit in coverage["limits_applied"]
    ), (
        "an offset-only final page must not record result_limit; the offset, not the "
        "limit, bounded this window"
    )


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


# ── Phase 1 corrective helpers ──────────────────────────────────────────────


def _fresh_index_patches() -> tuple[Any, Any]:
    """Patch the freshness guard so no real index build runs during a test."""
    from tools.lib.index_freshness import FreshnessReport

    fresh = FreshnessReport(fts_fresh=True, vector_fresh=True, overall_fresh=True, issues=[])
    return (
        patch("tools.lib.pending_writes.has_pending", return_value=False),
        patch("tools.lib.index_freshness.check_full_freshness", return_value=fresh),
    )


# ── (k) structured rebuild failure must not claim a self-healed index ─────────


def test_k_structured_rebuild_failure_keeps_auto_updated_false(
    isolated_data_dir: Path,
) -> None:
    """A structured success=false rebuild (LockTimeout-style) must stay unfresh.

    ``_build_all`` can return a structured failure instead of raising — e.g. the
    LockTimeout error envelope ``{"success": false, "error": {"code": "E0005"}}``.
    Treating that as a successful auto-update (``auto_updated=true``) erases the
    index_not_fresh signal and lets a stale-index retrieval claim ``complete``.
    The failure must keep ``auto_updated=false`` and record a stable warning.
    """
    from tools.lib.errors import ErrorCode, create_error_response
    from tools.lib.index_freshness import FreshnessReport
    from tools.search_journals.core import hierarchical_search

    token = "rebuildtoken"
    _write_two_line_body_journal(isolated_data_dir, date_str="2026-01-05", token=token, seq=1)

    stale_report = FreshnessReport(
        fts_fresh=False,
        vector_fresh=True,
        overall_fresh=False,
        issues=["fts_index_older_than_corpus"],
    )
    lock_timeout_result = create_error_response(
        ErrorCode.LOCK_TIMEOUT,
        "无法获取索引锁，请稍后重试",
        {"lock_path": "C:/tmp/index.lock", "timeout": 30},
    )
    with (
        patch("tools.lib.pending_writes.has_pending", return_value=False),
        patch("tools.lib.index_freshness.check_full_freshness", return_value=stale_report),
        patch("tools.build_index.build_all", return_value=lock_timeout_result),
    ):
        result = hierarchical_search(query=token, use_index=False)

    assert (
        result["index_status"]["auto_updated"] is False
    ), "a structured success=false rebuild result must not set auto_updated=true"
    assert (
        "index_update_failed: E0005" in result["warnings"]
    ), "a failed rebuild must record a stable warning keyed by the structured error code"
    coverage = find_coverage(result)
    assert coverage is not None
    assert (
        coverage["status"] == "partial"
    ), "a retrieval over an index whose rebuild failed must not claim complete"
    assert "index_not_fresh" in coverage["partial_reasons"]


def test_k_structured_rebuild_failure_without_error_code_is_still_unfresh(
    isolated_data_dir: Path,
) -> None:
    """A structured failure without an ``error`` envelope must also stay unfresh.

    ``_build_all`` may report failure through a nested ``fts.error`` instead of a
    top-level error envelope; the honest treatment is identical: no
    ``auto_updated=true`` and a stable warning.
    """
    from tools.lib.index_freshness import FreshnessReport
    from tools.search_journals.core import hierarchical_search

    token = "rebuildfts token"
    _write_two_line_body_journal(isolated_data_dir, date_str="2026-01-06", token=token, seq=1)

    stale_report = FreshnessReport(
        fts_fresh=False,
        vector_fresh=True,
        overall_fresh=False,
        issues=["no_manifest: No index manifest found, run 'life-index index'"],
    )
    with (
        patch("tools.lib.pending_writes.has_pending", return_value=False),
        patch("tools.lib.index_freshness.check_full_freshness", return_value=stale_report),
        patch(
            "tools.build_index.build_all",
            return_value={"success": False, "fts": {"success": False, "error": "disk full"}},
        ),
    ):
        result = hierarchical_search(query=token, use_index=False)

    assert result["index_status"]["auto_updated"] is False
    assert any(
        str(w).startswith("index_update_failed:") for w in result["warnings"]
    ), "the failed rebuild must still record an index_update_failed warning"
    coverage = find_coverage(result)
    assert coverage is not None
    assert "index_not_fresh" in coverage["partial_reasons"]


# ── (l) result_limit records only a limit that truly bound the window ─────────


def test_l_result_limit_only_recorded_when_limit_binds(isolated_data_dir: Path) -> None:
    """An offset-only final page is not a limit cap; a binding limit still is.

    * population 5, offset 3, limit 10 → the window returns 2 because only 2
      remain after the offset; the limit never bound it → NO ``result_limit``.
    * population 5, offset 0, limit 2 → the limit genuinely cut the window
      short of the admitted set → ``result_limit:2`` must be recorded.
    """
    from tools.search_journals.__main__ import run_search

    token = "limitbindtoken"
    base = date(2026, 5, 1)
    for i in range(5):
        _write_two_line_body_journal(
            isolated_data_dir,
            date_str=(base + timedelta(days=i)).isoformat(),
            token=token,
            seq=i + 1,
        )

    final_page = run_search(query=token, use_index=False, limit=10, offset=3, include_events=False)
    cov = find_coverage(final_page)
    assert cov is not None
    assert cov["observed_total"] == 5
    assert cov["returned"] == 2
    assert cov["next_offset"] is None
    assert cov["status"] == "partial"
    assert "unread_page" in cov["partial_reasons"]
    assert not any(
        str(entry).startswith("result_limit:") for entry in cov["limits_applied"]
    ), "an offset-only final page must not record result_limit"

    first_page = run_search(query=token, use_index=False, limit=2, offset=0, include_events=False)
    cov1 = find_coverage(first_page)
    assert cov1 is not None
    assert cov1["returned"] == 2
    assert cov1["next_offset"] == 2
    assert "result_limit:2" in [
        str(entry) for entry in cov1["limits_applied"]
    ], "a limit that actually excluded admitted candidates must be recorded"


# ── (m) empty / high-offset windows never report a non-advancing next_offset ──


def test_m_empty_or_high_offset_window_never_reports_non_advancing_next_offset() -> None:
    """An empty window must never emit next_offset 0 or a cursor equal to offset.

    A ``next_offset`` that does not advance past the current offset (0 on an
    empty first window, or the same offset on an empty mid-corpus window) traps
    a paging Host Agent in a loop. Such windows stay honestly ``partial`` with
    ``unread_page`` but carry no mechanical cursor.
    """
    from tools.search_journals.coverage import build_retrieval_coverage

    empty_first = build_retrieval_coverage(observed_total=3, returned=0, offset=0)
    assert empty_first["next_offset"] is None, "an empty first window must not emit next_offset=0"
    assert empty_first["status"] == "partial"
    assert "unread_page" in empty_first["partial_reasons"]

    empty_mid = build_retrieval_coverage(observed_total=5, returned=0, offset=2)
    assert (
        empty_mid["next_offset"] is None
    ), "an empty window must not emit a next_offset equal to the current offset"

    high_offset = build_retrieval_coverage(observed_total=5, returned=0, offset=7)
    assert high_offset["next_offset"] is None


# ── (n) level 1 / level 2 paginate their own result arrays with real coverage ──


def test_n_level1_paginates_l1_results_with_required_coverage(
    isolated_data_dir: Path,
) -> None:
    """Level 1 must paginate ``l1_results`` and carry a truthful coverage object.

    The API declares ``retrieval_coverage`` as always present. A level-1 response
    must therefore build coverage from the actual complete ``l1_results`` array
    (not from the empty ``merged_results``), slice ``l1_results`` for a page
    window, and keep the legacy totals as projections of that coverage.
    """
    from tools.search_journals.__main__ import run_search

    l1_items = [
        {"path": f"Journals/2026/01/note{seq}.md", "date": "2026-01-05"} for seq in range(5)
    ]
    fresh_pending, fresh_report = _fresh_index_patches()
    with (
        fresh_pending,
        fresh_report,
        patch("tools.search_journals.core.scan_all_indices", return_value=l1_items),
    ):
        page1 = run_search(level=1, limit=2, offset=0, include_events=False)
        page2 = run_search(level=1, limit=2, offset=2, include_events=False)
        final_page = run_search(level=1, limit=2, offset=4, include_events=False)
        full = run_search(level=1, limit=0, offset=0, include_events=False)

    assert len(page1["l1_results"]) == 2, "level 1 must paginate l1_results, not merged_results"
    cov1 = find_coverage(page1)
    assert cov1 is not None, "level 1 must carry the API-required retrieval_coverage object"
    assert cov1["schema_version"] == _COVERAGE_SCHEMA_VERSION
    assert cov1["observed_total"] == 5
    assert cov1["returned"] == 2
    assert cov1["next_offset"] == 2
    assert page1["total_matches"] == cov1["observed_total"]
    assert page1["total_available"] == cov1["observed_total"]
    assert page1["total_found"] == cov1["returned"]
    assert page1["has_more"] is True

    assert len(page2["l1_results"]) == 2
    assert find_coverage(page2)["next_offset"] == 4

    assert len(final_page["l1_results"]) == 1
    covf = find_coverage(final_page)
    assert covf["status"] == "partial"
    assert covf["next_offset"] is None
    assert "unread_page" in covf["partial_reasons"]
    assert not any(
        str(entry).startswith("result_limit:") for entry in covf["limits_applied"]
    ), "the offset-only final page of level 1 must not record result_limit"

    cov_full = find_coverage(full)
    assert cov_full is not None
    assert cov_full["status"] == "complete"
    assert len(full["l1_results"]) == 5


def test_n_level2_paginates_l2_results_with_required_coverage(
    isolated_data_dir: Path,
) -> None:
    """Level 2 must paginate ``l2_results`` with coverage as the totals authority."""
    from tools.search_journals.__main__ import run_search

    l2_items = [
        {"path": f"Journals/2026/02/note{seq}.md", "date": "2026-02-05"} for seq in range(3)
    ]
    fresh_pending, fresh_report = _fresh_index_patches()
    with (
        fresh_pending,
        fresh_report,
        patch(
            "tools.search_journals.core.search_l2_metadata",
            return_value={"results": l2_items, "truncated": False, "total_available": 3},
        ),
    ):
        page1 = run_search(level=2, limit=2, offset=0, include_events=False)
        final_page = run_search(level=2, limit=2, offset=2, include_events=False)

    assert len(page1["l2_results"]) == 2, "level 2 must paginate l2_results, not merged_results"
    cov1 = find_coverage(page1)
    assert cov1 is not None, "level 2 must carry the API-required retrieval_coverage object"
    assert cov1["observed_total"] == 3
    assert cov1["returned"] == 2
    assert cov1["next_offset"] == 2
    assert page1["total_matches"] == cov1["observed_total"]
    assert page1["total_found"] == cov1["returned"]
    assert page1["has_more"] is True

    assert len(final_page["l2_results"]) == 1
    covf = find_coverage(final_page)
    assert covf["status"] == "partial"
    assert covf["observed_total"] == 3
    assert covf["returned"] == 1
    assert covf["next_offset"] is None
    assert "unread_page" in covf["partial_reasons"]
    assert final_page["total_found"] == 1
    assert final_page["total_matches"] == covf["observed_total"]


# ── (o) FTS min-hits exclusion is an honest partial; recovery is not ───────────


def _min_hits_fts_items() -> list[dict[str, Any]]:
    """Two FTS hits for the segmented query ``苹果香蕉`` (required hits = 2).

    The first hits both non-stopword tokens; the second hits only ``苹果`` and is
    the candidate the min-hits post-filter drops.
    """
    return [
        {
            "path": "Journals/2026/03/both.md",
            "date": "2026-03-01",
            "title": "苹果 香蕉 沙拉",
            "snippet": "同时包含 苹果 和 香蕉",
            "relevance": 60,
        },
        {
            "path": "Journals/2026/03/one.md",
            "date": "2026-03-02",
            "title": "苹果派记录",
            "snippet": "只提到 苹果",
            "relevance": 40,
        },
    ]


def test_o_min_hits_exclusion_marks_partial_with_stable_signal(
    isolated_data_dir: Path,
) -> None:
    """A candidate still excluded by the FTS min-hits filter must not be complete.

    The min-hits post-filter keeps its filtering semantics, but a candidate it
    dropped — and that no fallback recovered — must surface through a stable
    coverage signal instead of a silent ``complete``.
    """
    from tools.search_journals.core import hierarchical_search

    fresh_pending, fresh_report = _fresh_index_patches()
    with (
        fresh_pending,
        fresh_report,
        patch(
            "tools.search_journals.keyword_pipeline.search_l2_metadata",
            return_value={"results": [], "truncated": False, "total_available": 0},
        ),
        patch("tools.lib.search_index.search_fts", return_value=_min_hits_fts_items()),
        patch("tools.search_journals.keyword_pipeline.search_l3_content", return_value=[]),
    ):
        result = hierarchical_search(query="苹果香蕉", use_index=True, emit_metrics=False)

    coverage = find_coverage(result)
    assert coverage is not None
    assert coverage["status"] == "partial", (
        "a retrieval that dropped a candidate via the FTS min-hits filter must not "
        "claim complete"
    )
    assert "threshold_excluded" in coverage["partial_reasons"]
    assert any(
        str(entry).startswith("fts_min_hits:") for entry in coverage["limits_applied"]
    ), "the min-hits exclusion must carry a stable closed-set limit entry"
    assert len(result["merged_results"]) == 1, "the surviving both-token match is returned"


def test_o_min_hits_recovery_by_fallback_reports_no_gap(
    isolated_data_dir: Path,
) -> None:
    """A min-hits exclusion fully recovered by the fallback is not a gap.

    When the full-corpus fallback re-admits the excluded candidate, reporting a
    min-hits gap anyway would double-report a defect that no longer exists; the
    retrieval stays ``complete``.
    """
    from tools.search_journals.core import hierarchical_search

    recovered = [
        {
            "path": "Journals/2026/03/one.md",
            "journal_route_path": "2026/03/one.md",
            "date": "2026-03-02",
            "title": "苹果派记录",
            "snippet": "只提到 苹果",
            "match_count": 1,
            "source": "content_search",
            "relevance": 20,
        }
    ]
    fresh_pending, fresh_report = _fresh_index_patches()
    with (
        fresh_pending,
        fresh_report,
        patch(
            "tools.search_journals.keyword_pipeline.search_l2_metadata",
            return_value={"results": [], "truncated": False, "total_available": 0},
        ),
        patch("tools.lib.search_index.search_fts", return_value=_min_hits_fts_items()),
        patch("tools.search_journals.keyword_pipeline.search_l3_content", return_value=recovered),
    ):
        result = hierarchical_search(query="苹果香蕉", use_index=True, emit_metrics=False)

    coverage = find_coverage(result)
    assert coverage is not None
    assert (
        coverage["status"] == "complete"
    ), "a min-hits exclusion recovered by the fallback must not be reported as a gap"
    assert "threshold_excluded" not in coverage["partial_reasons"]
    assert not any(str(entry).startswith("fts_min_hits:") for entry in coverage["limits_applied"])
    assert len(result["merged_results"]) == 2


# ── (p) candidate_paths filtering must not erase the L2 source-cap fact ────────


def test_p_candidate_filter_does_not_hide_l2_source_cap(
    isolated_data_dir: Path,
) -> None:
    """The upstream L2 source-cap total must survive the candidate filter.

    When an L0 prefilter (candidate_paths) narrows the L2 result list, the
    upstream ``total_available`` / ``truncated`` facts are about the SOURCE, not
    about the filtered window; overwriting them hides a real retrieval cap.
    """
    import os

    from tools.search_journals.keyword_pipeline import run_keyword_pipeline

    kept = str((isolated_data_dir / "Journals" / "2026" / "03" / "a.md").resolve()).replace(
        "\\", "/"
    )
    dropped = str((isolated_data_dir / "Journals" / "2026" / "03" / "b.md").resolve()).replace(
        "\\", "/"
    )
    assert os.environ.get("LIFE_INDEX_DATA_DIR") == str(isolated_data_dir)

    with patch(
        "tools.search_journals.keyword_pipeline.search_l2_metadata",
        return_value={
            "results": [
                {"path": kept, "date": "2026-03-01"},
                {"path": dropped, "date": "2026-03-02"},
            ],
            "truncated": True,
            "total_available": 50,
        },
    ):
        _l1, l2_results, _l3, l2_truncated, l2_total_available, _perf = run_keyword_pipeline(
            query="capsrctoken2", candidate_paths={kept}, use_index=False
        )

    assert l2_truncated is True, "the upstream truncation flag must survive the filter"
    assert len(l2_results) == 1, "the candidate filter still narrows the returned window"
    assert (
        l2_total_available == 50
    ), "the upstream L2 source-cap total must not be overwritten with the filtered count"


# ── (q) docs state the min_relevance=0 recall-first intent; vocabulary narrowed ─


_MIN_RELEVANCE_DOC_MARKER = (
    "`min_relevance=0` is the intentional Phase 1 recall-first default: search "
    "passes an explicit zero token-match threshold and thereby bypasses the "
    "legacy high-frequency dynamic threshold; this is by design, not an omission."
)


def test_q_docs_state_min_relevance_zero_recall_first_intent() -> None:
    """Canonical and packaged docs must state the min_relevance=0 intent."""
    repo_root = Path(__file__).resolve().parents[2]
    for rel in (
        "docs/API.md",
        "SKILL.md",
        "references/GROUNDED_QUERY_PLAYBOOK.md",
        "tools/_skill_artifacts/SKILL.md",
        "tools/_skill_artifacts/references/GROUNDED_QUERY_PLAYBOOK.md",
    ):
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert _MIN_RELEVANCE_DOC_MARKER in text, (
            f"{rel} must state that min_relevance=0 is the intentional Phase 1 "
            "recall-first default, not an omission"
        )


def test_q_child_failed_is_not_an_emittable_partial_reason() -> None:
    """The unreachable ``child_failed`` reason is removed from the public contract.

    No code path can emit it in Phase 1, so it must not appear in the public
    partial-reason vocabulary (module constants or documented enum).
    """
    import tools.search_journals.coverage as coverage_module

    emitted_reasons = {
        value
        for name, value in vars(coverage_module).items()
        if name.startswith("REASON_") and isinstance(value, str)
    }
    assert "child_failed" not in emitted_reasons

    api_text = (Path(__file__).resolve().parents[2] / "docs" / "API.md").read_text(encoding="utf-8")
    assert "child_failed" not in api_text, (
        "the documented partial_reasons vocabulary must not advertise an " "unreachable reason"
    )


# ── (r) host-agent coverage consumption semantics in root + packaged docs ─────


_SKILL_GROUNDED_ANCHORS = (
    "<!-- GROUNDED_QUERY_SKILL_START -->",
    "<!-- GROUNDED_QUERY_SKILL_END -->",
)
_PLAYBOOK_CONSUMPTION_ANCHORS = (
    "## Search And Smart-Search Consumption",
    "## Aggregation And Heuristic Evidence",
)

_ROOT_AND_PACKAGED_DOCS = (
    ("root SKILL.md", "SKILL.md"),
    ("packaged SKILL.md", "tools/_skill_artifacts/SKILL.md"),
    ("root playbook", "references/GROUNDED_QUERY_PLAYBOOK.md"),
    (
        "packaged playbook",
        "tools/_skill_artifacts/references/GROUNDED_QUERY_PLAYBOOK.md",
    ),
)


def _doc_block(label: str, rel_path: str) -> str:
    """Read the coverage-consumption surface of one doc (root or packaged).

    SKILL.md is scoped to its Grounded Query Routing SSOT block; the playbook is
    scoped to its Search And Smart-Search Consumption section. The scoped block
    is where the host-agent consumption rules must live.
    """
    text = (Path(__file__).resolve().parents[2] / rel_path).read_text(encoding="utf-8")
    anchors = (
        _SKILL_GROUNDED_ANCHORS if rel_path.endswith("SKILL.md") else _PLAYBOOK_CONSUMPTION_ANCHORS
    )
    start_marker, end_marker = anchors
    start = text.find(start_marker)
    assert start != -1, f"{label} must contain the anchor {start_marker!r}"
    start += len(start_marker)
    end = text.find(end_marker, start)
    assert end != -1, f"{label} must contain the anchor {end_marker!r}"
    return text[start:end]


# Each rule pairs the SKILL.md SSOT markers with the playbook markers. Every
# marker must appear verbatim in BOTH the root doc and the packaged mirror, so
# the packaged Skill cannot drift from the development SSOT.
_COVERAGE_CONSUMPTION_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "r1_bounded_scaffold_not_completeness_authority": {
        "SKILL.md": (
            "`smart-search` 的 `filtered_results` 只是有界发现 scaffold，不是完整性权威",
            "答案依赖“全部/计数/枚举”时，必须回到 `search` 的 `retrieval_coverage.v1`",
        ),
        "PLAYBOOK": (
            "`filtered_results` is a bounded discovery scaffold, not a completeness authority",
            "the completeness decision belongs to `search` and its `retrieval_coverage.v1` object",
        ),
    },
    "r2_full_set_mechanics": {
        "SKILL.md": (
            "优先用同一确定性 query/filter/level/min_relevance 调 `search --limit 0`",
            "每次只把 `offset` 改为当前返回的 `next_offset`，按稳定 journal `rel_path` 去重累计，"
            "直到 `next_offset` 为 null 才停止",
            "cursor 的存在或任何单独一页都不等于完整",
        ),
        "PLAYBOOK": (
            "same deterministic query/filter/level/min_relevance as `search --limit 0`",
            "change only `offset` to the returned `next_offset` on each call",
            "deduplicate the accumulated set by the stable journal `rel_path`",
            "stop only when `next_offset` is null",
            "A live cursor or any single page never proves completeness",
        ),
    },
    "r3_only_complete_proves_and_partial_disclosed": {
        "SKILL.md": (
            "只有 `status=complete` 才能声称该次响应携带完整 admitted set",
            "必须用自然语言向用户披露 `partial_reasons` 与 `limits_applied`，不得静默称“全部”",
        ),
        "PLAYBOOK": (
            'Only `status: "complete"` proves that one response carries the whole admitted set',
            "disclose `partial_reasons` and `limits_applied` to the user in natural language",
            'never silently claim "all"',
        ),
    },
    "r4_resource_bound_is_not_zero_results": {
        "SKILL.md": (
            "`success:false` + `E0301` + `reason=retrieval_resource_bound` 不是零结果",
            "先收窄 date/topic/person/project/entity/facet，或走 `index-tree ensure` → `discover` → `navigate`，再重试",
            "仍超界则如实报告 `observed`/`bound` 与未完成状态，不猜结论",
        ),
        "PLAYBOOK": (
            "`reason=retrieval_resource_bound` is not a zero-result answer",
            "Narrow the date/topic/person/project/entity/facet scope",
            "`index-tree ensure` -> `discover` -> `navigate`",
            "report the returned `observed`/`bound` and the unfinished state honestly",
        ),
    },
    "r5_legacy_totals_are_not_the_authority": {
        "SKILL.md": (
            "不得用 legacy `total_found` / `total_matches` / `total_available` / `has_more` "
            "取代 coverage authority",
        ),
        "PLAYBOOK": (
            "Never substitute the legacy `total_found` / `total_matches` / `total_available` / "
            "`has_more` projections for the coverage authority",
        ),
    },
    "r6_min_relevance_is_internal_fixed_not_a_host_flag": {
        "SKILL.md": (
            "`min_relevance=0` 是 `search` 内部固定的 recall-first 默认值，不是 Host 可传的 CLI flag",
            "Host 不得尝试 `--min-relevance`",
        ),
        "PLAYBOOK": (
            "`min_relevance=0` is fixed inside `search` itself; it is not a host-callable CLI flag",
            "must never attempt `--min-relevance`",
        ),
    },
    "r7_narrow_complete_proves_only_the_narrowed_set": {
        "SKILL.md": (
            "收窄 query/filter 后的 `complete` 只证明该次收窄的 admitted set 完整",
            "除非收窄方式构成对原始范围可证明穷尽且互不重叠的划分",
            "不得把多个窄 `complete` 合并宣称为原始宽问题的 complete",
            "必须向用户披露原问题仍为 partial/unfinished",
        ),
        "PLAYBOOK": (
            "A `complete` on a narrowed query/filter proves only that the narrowed "
            "admitted set is complete",
            "Unless the narrowing forms a provably exhaustive and non-overlapping "
            "partition of the original scope",
            "multiple narrow `complete` results must not be presented as the original "
            "wide question being complete",
            "disclose that the original question remains partial/unfinished",
        ),
    },
}


@pytest.mark.parametrize("rule", list(_COVERAGE_CONSUMPTION_RULES))
def test_r_coverage_consumption_rule_is_published_root_and_packaged(rule: str) -> None:
    """(r) Each consumption rule must appear verbatim in root AND packaged docs.

    The retrieval_coverage.v1 consumption semantics are host-agent law: the
    Skill SSOT block and the grounded query playbook must teach them, and the
    packaged mirror under tools/_skill_artifacts must carry the same text so an
    installed Skill cannot drift from the development SSOT.
    """
    markers_by_doc = _COVERAGE_CONSUMPTION_RULES[rule]
    for label, rel_path in _ROOT_AND_PACKAGED_DOCS:
        block = _doc_block(label, rel_path)
        expected = markers_by_doc["SKILL.md" if rel_path.endswith("SKILL.md") else "PLAYBOOK"]
        for marker in expected:
            assert marker in block, (
                f"{label} must publish the {rule} consumption rule verbatim; "
                f"missing marker: {marker!r}"
            )


def test_r_consumption_rules_are_runtime_generic_and_cap_free() -> None:
    """(r) The consumption rules must stay runtime-generic and fixed-cap free.

    The rules live in the host-agent surface, so they must not branch on a
    specific agent runtime name (any compliant runtime executes them), and they
    must not bake in a fixed "at most N entries" ceiling: completeness is
    decided by retrieval_coverage.v1 mechanics, never by a hardcoded page cap.
    """
    import re

    forbidden_runtime_names = ("Codex", "Hermes", "Claude")
    forbidden_cap_patterns = (
        re.compile(r"--limit [1-9]"),
        re.compile(r"最多\s*[1-9]"),
        re.compile(r"(?:at most|up to)\s+[1-9][0-9]*\s+(?:results|entries|journals)"),
    )
    for label, rel_path in _ROOT_AND_PACKAGED_DOCS:
        block = _doc_block(label, rel_path)
        for name in forbidden_runtime_names:
            assert (
                name not in block
            ), f"{label} consumption rules must not branch on the runtime name {name!r}"
        for pattern in forbidden_cap_patterns:
            match = pattern.search(block)
            assert match is None, (
                f"{label} consumption rules must not fix a result cap; "
                f"forbidden cap pattern {pattern.pattern!r} matched {match.group(0)!r}"
            )


def test_r_consumption_rules_never_teach_executable_min_relevance_flag() -> None:
    """(r) Host consumption rules must never teach an executable ``--min-relevance``.

    ``min_relevance=0`` is fixed inside search; it is not a host-callable CLI
    flag. The scoped blocks may (and per r6 must) state that internal-default
    fact, but they must never carry an executable flag instruction: the dash
    form must not appear with a value, and every bare ``--min-relevance``
    mention must sit in a prohibition sentence. The lock targets only the
    dash-flag form, so it never forbids stating the internal default
    (``min_relevance=0``) itself.
    """
    import re

    value_form = re.compile(r"--min-relevance(?:=|\s)\S*")
    prohibition_tokens = ("不得", "不要", "禁止", "不存在", "never", "must not", "not a", "no such")
    for label, rel_path in _ROOT_AND_PACKAGED_DOCS:
        block = _doc_block(label, rel_path)
        assert "min_relevance=0" in block, (
            f"{label} must keep stating the internal min_relevance=0 default; the "
            "flag prohibition below must not ban that fact"
        )
        match = value_form.search(block)
        assert match is None, (
            f"{label} consumption rules must not teach an executable --min-relevance "
            f"flag; forbidden value form matched {match.group(0)!r}"
        )
        for line in block.splitlines():
            if "--min-relevance" in line:
                assert any(token in line for token in prohibition_tokens), (
                    f"{label} may mention --min-relevance only inside a prohibition "
                    f"sentence, never as an executable instruction; offending line: "
                    f"{line.strip()!r}"
                )
