"""Deterministic smart-search orchestrator unit tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from tools.search_journals.coverage import (
    REASON_THRESHOLD_EXCLUDED,
    build_retrieval_coverage,
)
from tools.search_journals.orchestrator import SmartSearchOrchestrator


def _search_result(count: int = 2) -> dict[str, Any]:
    items = [
        {
            "path": f"Journals/2026/03/life-index_2026-03-0{index}_001.md",
            "rel_path": f"Journals/2026/03/life-index_2026-03-0{index}_001.md",
            "title": f"Test Entry {index}",
            "date": f"2026-03-0{index}",
            "snippet": f"snippet {index}",
            "source": "fts",
            "relevance": 90 - index * 10,
            "fts_score": float(90 - index * 10),
            "semantic_score": 0.0,
            "rrf_score": float(90 - index * 10),
            "final_score": float(90 - index * 10),
            "search_rank": index,
            "confidence": "high" if index == 1 else "medium",
            "metadata": {
                "topic": "test",
                "location": "Beijing",
                "abstract": f"Abstract for entry {index}.",
            },
        }
        for index in range(1, count + 1)
    ]
    return {
        "success": True,
        "query_params": {"query": "test", "expanded_query": "test expanded"},
        "merged_results": items,
        "semantic_results": [],
        "total_available": count,
        "has_more": False,
        "no_confident_match": count == 0,
        "performance": {"total_time_ms": 42.0},
    }


def _domain_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "performance"}


def test_orchestrator_exposes_only_deterministic_pipeline_boundary() -> None:
    orch = SmartSearchOrchestrator()
    assert hasattr(orch, "rewrite_query")
    assert hasattr(orch, "execute_search")
    assert hasattr(orch, "search")
    assert not hasattr(orch, "post_filter_and_summarize")
    assert not hasattr(orch, "synthesize_answer")


def test_data_minimization_limit_is_preserved() -> None:
    from tools.lib.search_constants import ORCHESTRATOR_MAX_CANDIDATES

    assert ORCHESTRATOR_MAX_CANDIDATES == 15


def test_search_returns_agent_ready_deterministic_schema() -> None:
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: _search_result(1),
    ):
        result = SmartSearchOrchestrator().search("晴岚")

    assert result["agent_unavailable"] is True
    assert result["smart_search_mode"] == "deterministic_scaffold"
    assert result["summary"] == ""
    assert result["citations"] == []
    assert result["agent_decisions"] == []
    assert result["agent_instructions"]["role"] == "calling_agent"
    assert result["answer_scaffold"]["citation_policy"] == "cite_only_returned_results"


def test_search_bounds_candidates_without_changing_order() -> None:
    raw = _search_result(20)
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: raw,
    ):
        result = SmartSearchOrchestrator().search("test")

    assert len(result["filtered_results"]) == 15
    assert result["filtered_results"] == raw["merged_results"][:15]
    assert result["performance"]["total_available"] == 20


def test_execute_search_fuses_bounded_deterministic_subqueries() -> None:
    calls: list[str] = []

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        calls.append(query)
        result = _search_result(1)
        result["merged_results"][0]["path"] = f"Journals/{query}.md"
        result["merged_results"][0]["rel_path"] = f"Journals/{query}.md"
        return result

    rewritten: Any = {
        "rewritten_query": "family",
        "sub_queries": ["daughter", "birthday", "school", "ignored"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    assert calls == ["daughter", "birthday", "school"]
    assert result["strategy"] == "keyword_multi_pass"
    assert len(result["candidates"]) == 3


def test_multi_query_total_available_is_observed_unique_before_cap() -> None:
    all_items = _search_result(17)["merged_results"]

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        result = _search_result(0)
        result["merged_results"] = all_items[:10] if query == "first" else all_items[5:17]
        result["total_available"] = len(result["merged_results"])
        return result

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    assert [item["rel_path"] for item in result["candidates"]] == [
        item["rel_path"] for item in all_items[:15]
    ]
    assert result["total_available"] == 17
    assert result["raw_results"]["total_available"] == 17
    assert result["raw_results"]["total_found"] == 15
    assert result["raw_results"]["has_more"] is True


def test_multi_query_child_has_more_marks_observed_total_as_lower_bound() -> None:
    item = _search_result(1)["merged_results"][0]

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        result = _search_result(1)
        result["merged_results"] = [item]
        result["total_available"] = 50 if query == "partial" else 1
        result["has_more"] = query == "partial"
        return result

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["partial", "overlap"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    assert result["total_available"] == 1
    assert result["raw_results"]["total_available"] == 1
    # Revision 4: has_more only means a mechanical next page (next_offset is
    # not None). This partial has no executable continuation (observed unique
    # == delivered), so has_more is truthfully false; the incompleteness defect
    # lives in retrieval_coverage.partial_reasons instead.
    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "unread_page" in coverage["partial_reasons"]
    assert "child_failed" in coverage["partial_reasons"]
    assert coverage["next_offset"] is None
    assert result["raw_results"]["has_more"] is False


def test_multi_query_child_failure_preserves_partial_results_and_incompleteness() -> None:
    success = _search_result(1)
    failure = {
        "success": False,
        "error": {"code": "search_failed", "message": "synthetic failure"},
        "merged_results": [],
        "total_available": 0,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
    }

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return failure if query == "broken" else success

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["working", "broken"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    assert [item["rel_path"] for item in result["candidates"]] == [
        item["rel_path"] for item in success["merged_results"]
    ]
    assert result["total_available"] == 1
    # Revision 4: child_failed partial with no executable continuation has
    # next_offset=null and has_more=false; completeness is governed only by
    # retrieval_coverage.status / partial_reasons.
    assert result["raw_results"]["has_more"] is False
    assert result["retrieval_coverage"]["status"] == "partial"
    assert "child_failed" in result["retrieval_coverage"]["partial_reasons"]
    assert result["raw_results"]["multi_query_results"][1]["result"] == failure
    # Phase 2A safe-warning contract: the sub-query failure warning must not
    # embed the sub-query text (user query content) — it reports the failure
    # and the lower-bound semantics only.
    failure_warnings = [
        warning
        for warning in result["raw_results"]["warnings"]
        if warning.startswith("subquery_failed:")
    ]
    assert failure_warnings, "missing subquery_failed warning for failed child"
    assert all("broken" not in warning and "working" not in warning for warning in failure_warnings)


def test_multi_query_evidence_and_performance_share_observed_unique_lower_bound() -> None:
    all_items = _search_result(17)["merged_results"]

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        result = _search_result(0)
        result["merged_results"] = all_items[:10] if query == "first" else all_items[5:17]
        result["total_available"] = len(result["merged_results"])
        return result

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        result = SmartSearchOrchestrator().search("combined", include_evidence=True)

    assert len(result["filtered_results"]) == 15
    assert result["performance"]["total_available"] == 17
    assert result["evidence_pack"]["total_available"] == 17
    assert result["evidence_pack"]["has_more"] is True
    assert len(result["evidence_pack"]["items"]) == 15


@pytest.mark.parametrize("incomplete_kind", ["child_has_more", "child_failure"])
def test_multi_query_incomplete_evidence_never_claims_full_recall(
    incomplete_kind: str,
) -> None:
    success = _search_result(1)
    success["merged_results"][0]["confidence"] = "low"
    success["no_confident_match"] = False

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        if query == "first":
            return success
        if incomplete_kind == "child_has_more":
            partial = dict(success)
            partial["total_available"] = 10
            partial["has_more"] = True
            return partial
        return {
            "success": False,
            "error": {"code": "search_failed", "message": "synthetic failure"},
            "merged_results": [],
            "total_available": 0,
            "has_more": False,
            "performance": {"total_time_ms": 1.0},
        }

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        result = SmartSearchOrchestrator().search("combined", include_evidence=True)

    # Revision 4 boundary: evidence_pack total_*/has_more are projections of
    # retrieval_coverage (has_more == next_offset is not None). Here the fused
    # observed set fits one window, so has_more is false — the incompleteness
    # defect must surface through retrieval_coverage, never through a fake
    # has_more, and the response must not be presentable as complete.
    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert coverage["next_offset"] is None

    evidence = result["evidence_pack"]
    assert evidence["total_available"] == len(evidence["items"]) == 1
    assert evidence["has_more"] is False
    # The failure is not silently disguised: the safe warning rides the
    # evidence envelope via query_context.warnings.
    warnings = evidence["query_context"]["warnings"]
    assert any(
        warning.startswith(("subquery_failed:", "subquery_coverage_missing:"))
        for warning in warnings
    )
    diagnostics = evidence["diagnostics"]
    assert diagnostics["retrieval_outcome"] in (
        "ok",
        "weak_results",
        "no_confident_match",
        "zero_results",
    )


def test_multi_query_all_child_failures_report_incomplete_evidence() -> None:
    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return {
            "success": False,
            "error": {
                "code": "search_failed",
                "message": f"synthetic failure for {query}",
            },
            "merged_results": [],
            "total_available": 0,
            "has_more": False,
            "performance": {"total_time_ms": 1.0},
        }

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        result = SmartSearchOrchestrator().search("combined", include_evidence=True)

    # Revision 4: an uncontinuable child_failed partial has next_offset=null
    # and has_more=false. The honest incompleteness signal is the coverage
    # object plus the safe failure warning — never a fake has_more.
    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert coverage["next_offset"] is None

    evidence = result["evidence_pack"]
    assert evidence["items"] == []
    assert evidence["total_available"] == 0
    assert evidence["has_more"] is False
    warnings = evidence["query_context"]["warnings"]
    assert any(warning.startswith("subquery_failed:") for warning in warnings)


def test_execute_search_applies_deterministic_time_range() -> None:
    captured: list[dict[str, str]] = []

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs)
        return _search_result(0)

    rewritten: Any = {
        "rewritten_query": "family",
        "sub_queries": ["family"],
        "time_range": "2026-03",
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    assert captured == [{"date_from": "2026-03-01", "date_to": "2026-03-31"}]
    assert result["strategy"] == "keyword_temporal"


def test_default_search_has_no_evidence_pack_or_internal_raw_results() -> None:
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: _search_result(),
    ):
        result = SmartSearchOrchestrator().search("test")

    assert "evidence_pack" not in result
    assert "raw_results" not in result


def test_include_evidence_preserves_raw_candidate_evidence() -> None:
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: _search_result(5),
    ):
        result = SmartSearchOrchestrator().search("test", include_evidence=True)

    assert len(result["evidence_pack"]["items"]) == 5
    assert result["evidence_pack"]["total_available"] == 5
    assert result["performance"]["evidence_build_ms"] >= 0


def test_include_evidence_empty_results_produces_valid_empty_pack() -> None:
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: _search_result(0),
    ):
        result = SmartSearchOrchestrator().search("missing", include_evidence=True)

    assert result["evidence_pack"]["items"] == []
    assert result["evidence_pack"]["total_available"] == 0
    assert result["evidence_pack"]["no_confident_match"] is True


def test_evidence_build_failure_is_best_effort() -> None:
    with (
        patch(
            "tools.search_journals.orchestrator._get_search_fn",
            return_value=lambda **kwargs: _search_result(1),
        ),
        patch(
            "tools.evidence.adapter.extract_evidence_from_orchestrator",
            side_effect=RuntimeError("build failed"),
        ),
    ):
        result = SmartSearchOrchestrator().search("test", include_evidence=True)

    assert result["success"] is True
    assert "evidence_pack" not in result
    assert result["performance"]["evidence_error"] == "build failed"


def test_synthesize_compatibility_argument_is_exact_domain_noop() -> None:
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: _search_result(1),
    ):
        ordinary = SmartSearchOrchestrator().search("test")
        compatibility = SmartSearchOrchestrator().search("test", synthesize=True)

    assert _domain_payload(ordinary) == _domain_payload(compatibility)
    assert "answer" not in compatibility
    assert "synthesis_ms" not in compatibility["performance"]


def test_aggregate_delegation_preserves_public_scaffold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-13")
    aggregate = {
        "success": True,
        "command": "aggregate",
        "unit": "day",
        "predicate": {"type": "entry_time_after"},
        "result": {"count": 0},
    }
    with patch("tools.aggregate.core.run_aggregate", return_value=aggregate):
        result = SmartSearchOrchestrator().search("过去60天我有多少天晚睡")

    assert result["aggregate_result"] == aggregate
    assert result["smart_search_mode"] == "deterministic_aggregate"
    assert result["filtered_results"] == []
    assert result["agent_unavailable"] is True
    assert "answer" not in result


def test_aggregate_failure_falls_back_to_deterministic_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-13")
    with (
        patch("tools.aggregate.core.run_aggregate", side_effect=RuntimeError("boom")),
        patch(
            "tools.search_journals.orchestrator._get_search_fn",
            return_value=lambda **kwargs: _search_result(1),
        ),
    ):
        result = SmartSearchOrchestrator().search("过去60天我有多少天晚睡")

    assert "aggregate_result" not in result
    assert result["filtered_results"][0]["title"] == "Test Entry 1"


# ── Phase 2A: honest smart-search coverage and continuation ────────────────
#
# The T2 continuation assertions below are copied mechanically from the Phase 0
# read-only evidence commit (36fd6a16 :: test_search_coverage_phase0_contract.py)
# and keep walking RED -> GREEN as the smart-search surface materializes the
# coverage contract. The remaining tests lock the Phase 2A behavior slices:
# window honesty, child-coverage propagation, child-failure partiality,
# provenance across pages, and single-authority compat projections.


def _is_int(value: Any) -> bool:
    """An actual int, excluding the bool subtype."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_coverage_object(obj: Any) -> bool:
    """Match the strongly-typed ``retrieval_coverage.v1`` field set."""
    if not isinstance(obj, dict):
        return False
    if obj.get("schema_version") != "retrieval_coverage.v1":
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
    """A complete retrieval must prove it via ``retrieval_coverage.v1``."""
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


def _continuation_item(index: int) -> dict[str, Any]:
    path = f"Journals/2026/01/life-index_2026-01-{index + 1:02d}_001.md"
    return {
        "rel_path": path,
        "path": path,
        "title": f"continuation note {index}",
        "date": f"2026-01-{index + 1:02d}",
        "rrf_score": 1.0 - index * 0.01,
        "source": "fts",
        "confidence": "high",
    }


def test_t2_executable_continuation_via_public_smart_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pagination must continue through the public smart-search entry.

    The first page goes through ``SmartSearchOrchestrator.search``. If it
    delivers the whole population at once it must prove complete coverage; otherwise
    the page must carry a structured integer ``next_offset`` (a bare ``has_more``
    flag is not a continuation) and the second page must be fetched through the
    public ``search(..., offset=next_offset)`` entry, never by calling the fake
    directly.
    """
    import tools.search_journals.orchestrator as orchestrator

    population_size = 20
    page_size = 5  # below ORCHESTRATOR_MAX_CANDIDATES and below the population
    population = [_continuation_item(i) for i in range(population_size)]

    def fake_search(query=None, *, offset=None, **_kwargs):
        start = int(offset) if offset else 0
        page = [dict(item) for item in population[start : start + page_size]]
        return {
            "success": True,
            "query_params": {"query": query or ""},
            "merged_results": page,
            "semantic_results": [],
            "total_available": population_size,
            "total_found": len(page),
            "has_more": (start + len(page)) < population_size,
            "performance": {"total_time_ms": 0.0},
            "warnings": [],
        }

    # Offset-aware fake stays installed until teardown.
    monkeypatch.setattr(orchestrator, "_search_fn", fake_search)

    query = "continuationtoken"
    page_one = SmartSearchOrchestrator().search(query, include_evidence=True)
    first_count = len(page_one["filtered_results"])

    # A one-shot complete delivery must prove complete coverage (no bare return).
    if first_count >= population_size:
        _require_complete_coverage(page_one)
        return

    # Otherwise the page must carry a structured integer continuation offset
    # equal to the number already returned (a bare has_more flag is not enough).
    coverage = find_coverage(page_one)
    assert coverage is not None, "smart-search page lacks structured retrieval coverage"
    next_offset = coverage["next_offset"]
    assert _is_int(next_offset), "continuation offset must be an integer, not a bare has_more flag"
    assert next_offset == first_count

    # The continuation must execute through the PUBLIC smart-search entry (an
    # offset/continuation parameter), never by calling the fake directly.
    page_two = SmartSearchOrchestrator().search(query, include_evidence=True, offset=next_offset)
    page_one_ids = {_result_identity(item) for item in page_one["filtered_results"]}
    page_two_ids = {_result_identity(item) for item in page_two["filtered_results"]}
    assert page_two_ids, "continuation returned no new evidence"
    assert not (page_two_ids & page_one_ids), "continuation re-returned page one evidence"


def _phase2a_child(
    items: list[dict[str, Any]],
    *,
    coverage: dict[str, Any] | None = None,
    has_more: bool = False,
    success: bool = True,
) -> dict[str, Any]:
    """Build a child result shaped like the real retrieval layer output.

    ``merged_results`` carries the full admitted set (the retrieval layer never
    truncates) with the coverage authority plus its legacy projections. Override
    ``coverage`` to model a partial child, or drop ``success`` to model failure.
    """
    if coverage is None:
        coverage = build_retrieval_coverage(observed_total=len(items), returned=len(items))
    return {
        "success": success,
        "query_params": {"query": "child"},
        "merged_results": items,
        "semantic_results": [],
        "total_available": coverage["observed_total"],
        "total_matches": coverage["observed_total"],
        "total_found": coverage["returned"],
        "has_more": has_more,
        "no_confident_match": not items,
        "performance": {"total_time_ms": 1.0},
        "warnings": [],
        "retrieval_coverage": coverage,
    }


def _phase2a_items(count: int, *, prefix: str = "Journals/2026/02") -> list[dict[str, Any]]:
    return [
        {
            "path": f"{prefix}/life-index_2026-02-{index + 1:02d}_001.md",
            "rel_path": f"{prefix}/life-index_2026-02-{index + 1:02d}_001.md",
            "title": f"Phase2A Entry {index}",
            "date": f"2026-02-{index + 1:02d}",
            "snippet": f"snippet {index}",
            "source": "fts",
            "rrf_score": float(100 - index),
            "confidence": "high" if index % 2 == 0 else "medium",
        }
        for index in range(count)
    ]


# Slice 1: single-query window honesty + executable continuation (R1)


def test_single_query_over_window_carries_partial_coverage_and_next_offset() -> None:
    """First page returns 15 items but proves the remainder via coverage."""
    child = _phase2a_child(_phase2a_items(20))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    assert len(result["filtered_results"]) == 15
    coverage = result["retrieval_coverage"]
    assert _is_coverage_object(coverage)
    assert coverage["status"] == "partial"
    assert coverage["observed_total"] == 20
    assert coverage["returned"] == 15
    assert coverage["next_offset"] == 15
    assert "unread_page" in coverage["partial_reasons"]


def test_single_query_continuation_pages_are_disjoint_and_lossless() -> None:
    """Continuation via the public offset entry neither repeats nor omits."""
    child = _phase2a_child(_phase2a_items(20))
    expected = {item["rel_path"] for item in child["merged_results"]}
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        page_one = SmartSearchOrchestrator().search("phase2a")
        page_two = SmartSearchOrchestrator().search("phase2a", offset=15)

    page_one_ids = {_result_identity(item) for item in page_one["filtered_results"]}
    page_two_ids = {_result_identity(item) for item in page_two["filtered_results"]}
    assert len(page_one_ids) == 15
    assert page_two_ids
    assert not (page_one_ids & page_two_ids)
    assert page_one_ids | page_two_ids == expected
    final_coverage = page_two["retrieval_coverage"]
    assert final_coverage["next_offset"] is None
    # A final nonzero-offset page is still partial: it does not carry the whole set.
    assert final_coverage["status"] == "partial"
    assert "unread_page" in final_coverage["partial_reasons"]


def test_single_query_offset_past_end_returns_empty_window_without_cursor() -> None:
    """An offset beyond the observed set is empty and never loops the caller."""
    child = _phase2a_child(_phase2a_items(20))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        result = SmartSearchOrchestrator().search("phase2a", offset=20)

    assert result["filtered_results"] == []
    coverage = result["retrieval_coverage"]
    assert coverage["returned"] == 0
    assert coverage["next_offset"] is None
    assert coverage["status"] == "partial"


def test_single_query_small_complete_set_proves_complete_coverage() -> None:
    child = _phase2a_child(_phase2a_items(3))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    assert len(result["filtered_results"]) == 3
    _require_complete_coverage(result)


# Slice 2/3: multi-query parent status follows the child coverage authority (R2/R3)


def test_multi_query_partial_child_coverage_forces_parent_partial() -> None:
    """A partial child makes the parent partial even when fused unique < 15.

    The child's legacy projections look complete (has_more=False, totals equal
    the item count); only its ``retrieval_coverage.v1`` reveals the gap, so the
    parent must consume the coverage authority — not has_more or list length.
    """
    partial_child = _phase2a_child(
        _phase2a_items(4),
        coverage=build_retrieval_coverage(
            observed_total=4,
            returned=4,
            partial_reasons=[REASON_THRESHOLD_EXCLUDED],
            limits_applied=["fts_threshold:0.35"],
        ),
    )
    complete_child = _phase2a_child(_phase2a_items(4, prefix="Journals/2026/03"))

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return partial_child if query == "first" else complete_child

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert REASON_THRESHOLD_EXCLUDED in coverage["partial_reasons"]
    assert coverage["observed_total"] == 8
    assert coverage["returned"] == 8
    assert coverage["next_offset"] is None


def test_multi_query_all_children_complete_small_union_is_complete() -> None:
    first = _phase2a_child(_phase2a_items(6))
    second = _phase2a_child(_phase2a_items(6, prefix="Journals/2026/03"))

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return first if query == "first" else second

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    _require_complete_coverage(result["retrieval_coverage"])
    assert result["retrieval_coverage"]["observed_total"] == 12
    assert len(result["candidates"]) == 12


def test_multi_query_fused_union_over_window_stays_partial_with_cursor() -> None:
    first = _phase2a_child(_phase2a_items(10))
    second = _phase2a_child(_phase2a_items(10, prefix="Journals/2026/03"))

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return first if query == "first" else second

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert coverage["observed_total"] == 20
    assert coverage["returned"] == 15
    assert coverage["next_offset"] == 15


# Slice 4: child failure is honest partial, never success+complete (R4)


def test_multi_query_child_failure_is_partial_with_child_failed_reason() -> None:
    working = _phase2a_child(_phase2a_items(2))
    failure = {
        "success": False,
        "error": {"code": "search_failed", "message": "synthetic failure"},
        "merged_results": [],
        "total_available": 0,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
    }

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return failure if query == "broken" else working

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["working", "broken"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        result = SmartSearchOrchestrator().search("combined")

    assert result["success"] is True
    assert [item["rel_path"] for item in result["filtered_results"]] == [
        item["rel_path"] for item in working["merged_results"]
    ]
    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert result["performance"]["total_available"] == 2
    # No success+complete fake: the envelope cannot prove completeness.
    assert not (
        coverage["status"] == "complete" and coverage["observed_total"] == coverage["returned"]
    )


def test_multi_query_child_failure_warning_carries_no_user_content() -> None:
    working = _phase2a_child(_phase2a_items(1))
    failure = {
        "success": False,
        "error": {"code": "search_failed", "message": "synthetic failure"},
        "merged_results": [],
        "total_available": 0,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
    }

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return failure if query == "秘密关键词" else working

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["正常词", "秘密关键词"],
        "time_range": None,
    }
    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        result = SmartSearchOrchestrator().execute_search(rewritten)

    failure_warnings = [
        warning
        for warning in result["raw_results"]["warnings"]
        if warning.startswith("subquery_failed:")
    ]
    assert failure_warnings
    assert all(
        "秘密关键词" not in warning and "正常词" not in warning for warning in failure_warnings
    )


def test_single_query_child_failure_is_partial_not_fake_complete() -> None:
    failure = {
        "success": False,
        "error": {"code": "search_failed", "message": "synthetic failure"},
        "merged_results": [],
        "total_available": 0,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: failure,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    assert result["filtered_results"] == []
    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert coverage["next_offset"] is None


# Slice 5: continuation keeps stable identity + source_queries provenance (R5)


def test_multi_query_continuation_keeps_identity_and_source_queries_provenance() -> None:
    first_items = _phase2a_items(12)
    # Overlapping candidate: same identity appears in both children.
    shared = dict(first_items[0])
    second_items = [shared] + _phase2a_items(9, prefix="Journals/2026/03")

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        if query == "first":
            return _phase2a_child(first_items)
        return _phase2a_child(second_items)

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        page_one = SmartSearchOrchestrator().search("combined")
        page_two = SmartSearchOrchestrator().search("combined", offset=15)

    page_one_ids = {_result_identity(item) for item in page_one["filtered_results"]}
    page_two_ids = {_result_identity(item) for item in page_two["filtered_results"]}
    assert len(page_one_ids) == 15
    assert page_two_ids
    assert not (page_one_ids & page_two_ids)
    assert len(page_one_ids | page_two_ids) == 21  # 12 + 9 unique (shared fused once)

    # source_queries provenance is stable per identity across pages.
    def provenance_by_identity(page: dict[str, Any]) -> dict[str, Any]:
        return {
            _result_identity(item): item.get("source_queries") for item in page["filtered_results"]
        }

    page_one_prov = provenance_by_identity(page_one)
    page_two_prov = provenance_by_identity(page_two)
    shared_key = _result_identity(shared)
    assert page_one_prov[shared_key] == ["first", "second"]
    for identity, source_queries in {**page_one_prov, **page_two_prov}.items():
        assert source_queries, f"missing source_queries provenance for {identity}"
        assert set(source_queries) <= {"first", "second"}


# Slice 6: compat projections derive from project_legacy_from_coverage (R6)


def test_compat_projections_derive_from_coverage_authority_windowed() -> None:
    """Windowed partial: has_more means exactly next_offset is not None."""
    child = _phase2a_child(_phase2a_items(20))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        result = SmartSearchOrchestrator().search("phase2a", include_evidence=True)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert coverage["next_offset"] == 15
    pack = result["evidence_pack"]
    assert pack["has_more"] is True
    assert pack["total_available"] == coverage["observed_total"] == 20
    assert len(pack["items"]) == coverage["returned"] == 15


def test_complete_coverage_keeps_compat_has_more_false_everywhere() -> None:
    child = _phase2a_child(_phase2a_items(3))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        result = SmartSearchOrchestrator().search("phase2a", include_evidence=True)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "complete"
    assert result["evidence_pack"]["has_more"] is False
    assert result["evidence_pack"]["total_available"] == 3


def test_uncontinuable_partial_has_truthfully_false_has_more() -> None:
    """child_failed partial: next_offset null, has_more false, still partial.

    Revision 4: has_more only signals a mechanical next page. An uncontinuable
    partial keeps has_more=false; completeness remains governed only by
    retrieval_coverage.status / partial_reasons, and the raw envelope's legacy
    totals are projected from the same coverage object.
    """
    failure = {
        "success": False,
        "error": {"code": "search_failed", "message": "synthetic failure"},
        "merged_results": [],
        "total_available": 0,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
    }

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return failure

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        result = SmartSearchOrchestrator().search("combined", include_evidence=True)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert coverage["next_offset"] is None
    pack = result["evidence_pack"]
    assert pack["items"] == []
    assert pack["total_available"] == 0
    assert pack["has_more"] is False
    warnings = pack["query_context"]["warnings"]
    assert any(warning.startswith("subquery_failed:") for warning in warnings)


def test_raw_envelope_legacy_fields_are_projected_from_coverage() -> None:
    """total_matches/total_available/total_found/has_more mirror the coverage.

    Single-query windowed partial and multi-query fused window both project
    exactly ``observed_total / observed_total / returned / next_offset is not
    None`` — never a status-derived has_more.
    """
    child = _phase2a_child(_phase2a_items(20))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        single = SmartSearchOrchestrator().execute_search(
            {"rewritten_query": "phase2a", "sub_queries": ["phase2a"], "time_range": None}
        )

    coverage = single["retrieval_coverage"]
    raw = single["raw_results"]
    assert raw["total_matches"] == coverage["observed_total"] == 20
    assert raw["total_available"] == coverage["observed_total"] == 20
    assert raw["total_found"] == coverage["returned"] == 15
    assert raw["has_more"] is (coverage["next_offset"] is not None) is True

    first = _phase2a_child(_phase2a_items(10))
    second = _phase2a_child(_phase2a_items(10, prefix="Journals/2026/03"))

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        return first if query == "first" else second

    with patch("tools.search_journals.orchestrator._get_search_fn", return_value=search):
        multi = SmartSearchOrchestrator().execute_search(
            {
                "rewritten_query": "combined",
                "sub_queries": ["first", "second"],
                "time_range": None,
            }
        )

    coverage = multi["retrieval_coverage"]
    raw = multi["raw_results"]
    assert coverage["observed_total"] == 20
    assert coverage["returned"] == 15
    assert coverage["next_offset"] == 15
    assert raw["total_matches"] == raw["total_available"] == 20
    assert raw["total_found"] == 15
    assert raw["has_more"] is True


def test_final_page_projection_has_false_has_more_but_stays_partial() -> None:
    child = _phase2a_child(_phase2a_items(20))
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: child,
    ):
        result = SmartSearchOrchestrator().search("phase2a", include_evidence=True, offset=15)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert coverage["next_offset"] is None
    pack = result["evidence_pack"]
    assert pack["has_more"] is False
    assert pack["total_available"] == 20
    assert len(pack["items"]) == 5


# Legacy compatibility inputs degrade conservatively (design constraint)


def test_legacy_child_without_coverage_degrades_conservatively_to_partial() -> None:
    """Old callers/mocks without retrieval_coverage never yield complete.

    Revision 4 closed vocabulary: a missing/invalid child coverage authority
    fails closed for completeness via the existing ``child_failed`` reason —
    no invented reason is published — plus a safe warning without user query
    content. Legacy ``has_more`` / ``total_*`` projections are compatibility
    inputs only and can never prove completeness.
    """
    legacy = {
        "success": True,
        "query_params": {"query": "legacy"},
        "merged_results": _phase2a_items(3),
        "semantic_results": [],
        "total_available": 3,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: legacy,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    coverage = result["retrieval_coverage"]
    assert _is_coverage_object(coverage)
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert all(
        reason
        in {
            "unread_page",
            "source_cap",
            "threshold_excluded",
            "child_failed",
            "index_not_fresh",
        }
        for reason in coverage["partial_reasons"]
    ), f"non-closed-vocabulary reason emitted: {coverage['partial_reasons']}"
    assert coverage["observed_total"] == 3
    # Revision 4: the partial has no executable continuation, so has_more is
    # truthfully false — completeness is governed only by status/reasons.
    assert coverage["next_offset"] is None


def test_missing_authority_fails_closed_via_child_failed_with_safe_warning() -> None:
    """A child without a valid coverage authority never proves complete.

    Single-query variant: legacy projections look complete (totals equal the
    item count, has_more false), yet the response must be partial with the
    closed-vocabulary ``child_failed`` reason and a safe warning that carries
    no user query or journal content.
    """
    legacy = {
        "success": True,
        "query_params": {"query": "legacy"},
        "merged_results": _phase2a_items(3),
        "semantic_results": [],
        "total_available": 3,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
        "warnings": [],
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: legacy,
    ):
        result = SmartSearchOrchestrator().search("phase2a", include_evidence=True)

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert "coverage_authority_missing" not in coverage["partial_reasons"]
    warnings = result["evidence_pack"]["query_context"]["warnings"]
    missing_warnings = [
        warning for warning in warnings if warning.startswith("subquery_coverage_missing:")
    ]
    assert missing_warnings, "missing safe subquery_coverage_missing warning"
    assert all("legacy" not in warning for warning in missing_warnings)


def test_invalid_authority_fails_closed_via_child_failed() -> None:
    """A malformed coverage object is not an authority and fails closed too."""
    bogus = {
        "success": True,
        "query_params": {"query": "bogus"},
        "merged_results": _phase2a_items(2),
        "semantic_results": [],
        "total_available": 2,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
        "retrieval_coverage": {"schema_version": "retrieval_coverage.v9", "status": "complete"},
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: bogus,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    coverage = result["retrieval_coverage"]
    assert coverage["schema_version"] == "retrieval_coverage.v1"
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]


def test_reason_child_failed_is_centralized_in_coverage_module() -> None:
    """The fifth closed reason lives in coverage.py, not the orchestrator."""
    import tools.search_journals.coverage as coverage_module
    import tools.search_journals.orchestrator as orchestrator_module

    assert coverage_module.REASON_CHILD_FAILED == "child_failed"
    assert orchestrator_module.REASON_CHILD_FAILED is coverage_module.REASON_CHILD_FAILED
    assert not hasattr(orchestrator_module, "REASON_COVERAGE_AUTHORITY_MISSING")


def test_legacy_child_has_more_forces_partial_coverage() -> None:
    legacy = {
        "success": True,
        "query_params": {"query": "legacy"},
        "merged_results": _phase2a_items(3),
        "semantic_results": [],
        "total_available": 50,
        "has_more": True,
        "performance": {"total_time_ms": 1.0},
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: legacy,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "unread_page" in coverage["partial_reasons"]


def test_negative_offset_is_rejected_by_public_entry() -> None:
    with pytest.raises(ValueError):
        SmartSearchOrchestrator().search("phase2a", offset=-1)


# Revision 4 correction: deterministic equal-score ordering + causal
# rank-tie continuation (repeat execution and page boundaries).


def _tied_items(count: int, *, prefix: str) -> list[dict[str, Any]]:
    """Build ``count`` items that ALL share one rrf_score (rank ties).

    Identities are deliberately not in ascending path order so a
    child-iteration-order-dependent sort would be observable.
    """
    seq = [(index * 7) % count for index in range(count)]  # deterministic shuffle
    return [
        {
            "path": f"{prefix}/life-index_2026-05-{value + 1:02d}_001.md",
            "rel_path": f"{prefix}/life-index_2026-05-{value + 1:02d}_001.md",
            "title": f"Tied Entry {value}",
            "date": f"2026-05-{value + 1:02d}",
            "snippet": f"snippet {value}",
            "source": "fts",
            "rrf_score": 7.0,  # every item ties
            "confidence": "high",
        }
        for value in seq
    ]


def test_rank_tie_continuation_is_deterministic_and_lossless() -> None:
    """Equal-score fused ordering is identity-stable across pages and repeats.

    Causal contract: with every fused candidate tied on rrf_score, page one
    must be identical across repeat executions (and across flipped child
    result order), page boundaries must not duplicate or omit any identity,
    and source_queries provenance must stay stable per identity.
    """
    first_items = _tied_items(12, prefix="Journals/2026/05")
    second_items = _tied_items(9, prefix="Journals/2026/06")
    # Shared identity across children to exercise fusion + provenance.
    shared = dict(first_items[0])
    second_items = [shared, *second_items]

    call_count = {"n": 0}

    def search(query: str = "", **kwargs: Any) -> dict[str, Any]:
        items = first_items if query == "first" else second_items
        # Flip the child item order on alternate executions: a deterministic
        # tie-break must not depend on child iteration order.
        call_count["n"] += 1
        ordered = list(reversed(items)) if call_count["n"] % 2 == 0 else list(items)
        return _phase2a_child(ordered)

    rewritten: Any = {
        "rewritten_query": "combined",
        "sub_queries": ["first", "second"],
        "time_range": None,
    }
    with (
        patch.object(SmartSearchOrchestrator, "rewrite_query", return_value=rewritten),
        patch("tools.search_journals.orchestrator._get_search_fn", return_value=search),
    ):
        page_one = SmartSearchOrchestrator().search("combined")
        page_one_repeat = SmartSearchOrchestrator().search("combined")
        page_two = SmartSearchOrchestrator().search("combined", offset=15)

    expected_unique = {item["rel_path"] for item in first_items} | {
        item["rel_path"] for item in second_items
    }
    assert len(expected_unique) == 21  # 12 + 9 unique (shared fused once)

    def identities(page: dict[str, Any]) -> list[str]:
        return [_result_identity(item) for item in page["filtered_results"]]

    page_one_ids = identities(page_one)
    page_two_ids = identities(page_two)

    # Repeat execution is byte-stable in ordering.
    assert identities(page_one_repeat) == page_one_ids
    # Equal-score group is ordered by stable journal identity (ascending).
    assert page_one_ids == sorted(page_one_ids)
    # Window + continuation: no duplicates, no omissions.
    assert len(page_one_ids) == 15
    assert len(set(page_one_ids)) == 15
    assert page_two_ids
    assert not (set(page_one_ids) & set(page_two_ids))
    assert set(page_one_ids) | set(page_two_ids) == expected_unique
    assert identities(page_two) == sorted(identities(page_two))

    # Provenance is stable per identity across pages and repeat executions.
    def provenance(page: dict[str, Any]) -> dict[str, list[str]]:
        return {
            _result_identity(item): item.get("source_queries") for item in page["filtered_results"]
        }

    page_one_prov = provenance(page_one)
    assert provenance(page_one_repeat) == page_one_prov
    for identity, source_queries in {**page_one_prov, **provenance(page_two)}.items():
        assert source_queries, f"missing source_queries provenance for {identity}"
        assert set(source_queries) <= {"first", "second"}
    shared_key = _result_identity(shared)
    assert page_one_prov[shared_key] == ["first", "second"]


# Revision 4 correction: strongly-typed child coverage authority validation.
# An authority object must satisfy the full public retrieval_coverage.v1
# contract — required fields with documented types (int excludes bool,
# nonnegative counts/offset), the closed five-reason vocabulary, string
# limits, and a status consistent with the completeness invariant. Anything
# else is not an authority and must fail closed via child_failed.


def _valid_coverage_dict() -> dict[str, Any]:
    """A minimal well-formed authority object (production builder output)."""
    return build_retrieval_coverage(observed_total=1, returned=1)


def _mutated(
    base: dict[str, Any], *, pop: tuple[str, ...] = (), **overrides: Any
) -> dict[str, Any]:
    obj = dict(base)
    for key in pop:
        obj.pop(key, None)
    obj.update(overrides)
    return obj


_INVALID_AUTHORITY_CASES: list[tuple[str, dict[str, Any]]] = [
    (
        "lead_exact_artifact_invented_reason_and_missing_fields",
        {
            "schema_version": "retrieval_coverage.v1",
            "status": "partial",
            "partial_reasons": ["invented_reason"],
            "observed_total": 1,
        },
    ),
    (
        # The Lead's exact false-complete artifact: a hand-made 'partial'
        # claim with no defect signal. Two-way iff: an object that proves
        # completeness must say 'complete'; saying 'partial' while proving
        # completeness is self-inconsistent and not an authority.
        "lead_exact_artifact_partial_claim_without_defect_signal",
        {
            "schema_version": "retrieval_coverage.v1",
            "status": "partial",
            "observed_total": 1,
            "returned": 1,
            "next_offset": None,
            "partial_reasons": [],
            "limits_applied": [],
        },
    ),
    (
        "returned_exceeds_observed_total",
        _mutated(
            _valid_coverage_dict(),
            observed_total=1,
            returned=3,
            status="partial",
        ),
    ),
    (
        "returned_exceeds_observed_total_complete_claim",
        _mutated(
            _valid_coverage_dict(),
            observed_total=1,
            returned=3,
            status="complete",
        ),
    ),
    (
        "missing_all_required_fields",
        {"schema_version": "retrieval_coverage.v1", "status": "partial"},
    ),
    ("missing_observed_total", _mutated(_valid_coverage_dict(), pop=("observed_total",))),
    ("missing_returned", _mutated(_valid_coverage_dict(), pop=("returned",))),
    ("missing_next_offset", _mutated(_valid_coverage_dict(), pop=("next_offset",))),
    ("missing_partial_reasons", _mutated(_valid_coverage_dict(), pop=("partial_reasons",))),
    ("missing_limits_applied", _mutated(_valid_coverage_dict(), pop=("limits_applied",))),
    ("bool_observed_total", _mutated(_valid_coverage_dict(), observed_total=True)),
    ("bool_returned", _mutated(_valid_coverage_dict(), returned=False)),
    ("negative_observed_total", _mutated(_valid_coverage_dict(), observed_total=-1)),
    ("negative_returned", _mutated(_valid_coverage_dict(), returned=-3)),
    ("string_observed_total", _mutated(_valid_coverage_dict(), observed_total="1")),
    ("float_returned", _mutated(_valid_coverage_dict(), returned=1.0)),
    ("bool_next_offset", _mutated(_valid_coverage_dict(), next_offset=True)),
    ("negative_next_offset", _mutated(_valid_coverage_dict(), next_offset=-5)),
    ("string_next_offset", _mutated(_valid_coverage_dict(), next_offset="15")),
    ("string_partial_reasons", _mutated(_valid_coverage_dict(), partial_reasons="unread_page")),
    ("dict_limits_applied", _mutated(_valid_coverage_dict(), limits_applied={"a": 1})),
    ("non_string_limit_entry", _mutated(_valid_coverage_dict(), limits_applied=[15])),
    (
        "unknown_partial_reason",
        _mutated(
            _valid_coverage_dict(),
            status="partial",
            partial_reasons=["invented_reason"],
        ),
    ),
    (
        "complete_but_returned_below_observed",
        _mutated(_valid_coverage_dict(), observed_total=5, returned=3, status="complete"),
    ),
    (
        "complete_but_next_offset_present",
        _mutated(
            _valid_coverage_dict(),
            next_offset=3,
            status="complete",
        ),
    ),
    (
        "complete_but_reasons_present",
        _mutated(
            _valid_coverage_dict(),
            status="complete",
            partial_reasons=["unread_page"],
        ),
    ),
    (
        "complete_but_limits_present",
        _mutated(
            _valid_coverage_dict(),
            status="complete",
            limits_applied=["result_limit:15"],
        ),
    ),
]


@pytest.mark.parametrize(
    ("label", "candidate"),
    _INVALID_AUTHORITY_CASES,
    ids=[label for label, _ in _INVALID_AUTHORITY_CASES],
)
def test_malformed_coverage_object_is_not_a_child_authority(
    label: str, candidate: dict[str, Any]
) -> None:
    """Each contract violation disqualifies the object as an authority."""
    from tools.search_journals.orchestrator import _is_authority_coverage

    assert (
        _is_authority_coverage(candidate) is False
    ), f"malformed coverage object accepted as authority: {label}"


@pytest.mark.parametrize(
    "candidate",
    [
        build_retrieval_coverage(observed_total=4, returned=4),
        build_retrieval_coverage(observed_total=20, returned=15),
        build_retrieval_coverage(
            observed_total=4,
            returned=4,
            partial_reasons=["threshold_excluded"],
            limits_applied=["fts_threshold:0.35"],
        ),
        build_retrieval_coverage(
            observed_total=20,
            returned=15,
            partial_reasons=["child_failed", "unread_page"],
            limits_applied=["result_limit:15"],
        ),
        build_retrieval_coverage(observed_total=0, returned=0),
    ],
)
def test_well_formed_coverage_objects_remain_valid_authorities(
    candidate: dict[str, Any],
) -> None:
    """Production-builder outputs (complete, partial, empty) stay valid."""
    from tools.search_journals.orchestrator import _is_authority_coverage

    assert _is_authority_coverage(candidate) is True


def test_invented_reason_never_propagates_from_malformed_authority() -> None:
    """The Lead's exact artifact: invented reason must not become authority.

    A schema_version/status-shaped object with missing required fields and an
    invented partial reason is NOT an authority: the child fails closed via
    ``child_failed`` (closed vocabulary), the invented reason never propagates,
    and the safe count-only warning is emitted.
    """
    bogus = {
        "success": True,
        "query_params": {"query": "bogus"},
        "merged_results": _phase2a_items(1),
        "semantic_results": [],
        "total_available": 1,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
        "warnings": [],
        "retrieval_coverage": {
            "schema_version": "retrieval_coverage.v1",
            "status": "partial",
            "partial_reasons": ["invented_reason"],
            "observed_total": 1,
        },
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: bogus,
    ):
        result = SmartSearchOrchestrator().search("phase2a", include_evidence=True)

    coverage = result["retrieval_coverage"]
    assert coverage["schema_version"] == "retrieval_coverage.v1"
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    assert "invented_reason" not in coverage["partial_reasons"]
    assert all(
        reason
        in {"unread_page", "source_cap", "threshold_excluded", "child_failed", "index_not_fresh"}
        for reason in coverage["partial_reasons"]
    )
    assert coverage["next_offset"] is None
    warnings = result["evidence_pack"]["query_context"]["warnings"]
    missing_warnings = [
        warning for warning in warnings if warning.startswith("subquery_coverage_missing:")
    ]
    assert missing_warnings, "missing safe subquery_coverage_missing warning"
    assert all("bogus" not in warning and "phase2a" not in warning for warning in missing_warnings)


def test_inconsistent_complete_authority_fails_closed_via_child_failed() -> None:
    """A status='complete' claim with a remainder is not provable."""
    bogus = {
        "success": True,
        "query_params": {"query": "bogus"},
        "merged_results": _phase2a_items(3),
        "semantic_results": [],
        "total_available": 3,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
        "warnings": [],
        "retrieval_coverage": {
            "schema_version": "retrieval_coverage.v1",
            "status": "complete",
            "observed_total": 5,
            "returned": 3,
            "next_offset": None,
            "partial_reasons": [],
            "limits_applied": [],
        },
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: bogus,
    ):
        result = SmartSearchOrchestrator().search("phase2a")

    coverage = result["retrieval_coverage"]
    assert coverage["status"] == "partial"
    assert "child_failed" in coverage["partial_reasons"]
    # Legacy compatibility fallback keeps the observed lower bound.
    assert coverage["observed_total"] == 3
    assert coverage["returned"] == 3
    assert coverage["next_offset"] is None


def test_partial_claim_without_defect_signal_never_rebuilds_complete() -> None:
    """The Lead's exact false-complete path must stay impossible.

    A child coverage object shaped as ``status='partial'`` with
    ``observed_total == returned``, ``next_offset=null`` and empty
    reasons/limits carries no defect signal: it is NOT an authority (the
    public contract's two-way iff says such an object must claim 'complete'),
    so the child fails closed via ``child_failed`` and the public parent
    coverage stays partial — it must never be rebuilt as a false complete.
    """
    bogus = {
        "success": True,
        "query_params": {"query": "bogus"},
        "merged_results": _phase2a_items(1),
        "semantic_results": [],
        "total_available": 1,
        "has_more": False,
        "performance": {"total_time_ms": 1.0},
        "warnings": [],
        "retrieval_coverage": {
            "schema_version": "retrieval_coverage.v1",
            "status": "partial",
            "observed_total": 1,
            "returned": 1,
            "next_offset": None,
            "partial_reasons": [],
            "limits_applied": [],
        },
    }
    with patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=lambda **kwargs: bogus,
    ):
        result = SmartSearchOrchestrator().search("phase2a", include_evidence=True)

    coverage = result["retrieval_coverage"]
    assert coverage["schema_version"] == "retrieval_coverage.v1"
    assert coverage["status"] == "partial", "false-complete rebuild of an invalid authority"
    assert "child_failed" in coverage["partial_reasons"]
    assert coverage["next_offset"] is None
    # Legacy projection stays truthful: no mechanical continuation.
    assert result["evidence_pack"]["has_more"] is False
    warnings = result["evidence_pack"]["query_context"]["warnings"]
    missing_warnings = [
        warning for warning in warnings if warning.startswith("subquery_coverage_missing:")
    ]
    assert missing_warnings, "missing safe subquery_coverage_missing warning"
