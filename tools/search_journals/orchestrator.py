#!/usr/bin/env python3
"""Deterministic smart-search orchestration over keyword and entity retrieval.

Host agents and Skills own planning, filtering, interpretation, and synthesis.
This module only builds a bounded, provider-free evidence scaffold.

Phase 2A: the smart-search response consumes each search child's
``retrieval_coverage.v1`` as the only completeness authority and scopes its own
top-level ``retrieval_coverage`` to the delivered window. A partial window
carries an executable ``next_offset`` continuation cursor (public
``search(..., offset=...)`` / CLI ``--offset``). Revision 4 semantics: legacy
``has_more`` / ``total_*`` fields are compatibility projections of the coverage
object — ``has_more`` only means a mechanical next page
(``next_offset is not None``); completeness is governed solely by
``retrieval_coverage.status`` / ``partial_reasons`` (closed vocabulary in
``coverage.py``). A child that fails, or answers without a valid coverage
authority, fails closed via ``child_failed`` plus a safe warning carrying no
user query or journal content.
"""

from __future__ import annotations

import calendar
import inspect
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

from ..lib.search_constants import ORCHESTRATOR_MAX_CANDIDATES
from ..lib.planner_types import (
    QueryPlan,
    StageRecord,
    build_planner_record_from_stages,
    merge_planner_into_search_plan,
)
from .coverage import (
    REASON_CHILD_FAILED,
    REASON_INDEX_NOT_FRESH,
    REASON_SOURCE_CAP,
    REASON_THRESHOLD_EXCLUDED,
    REASON_UNREAD_PAGE,
    SCHEMA_VERSION as COVERAGE_SCHEMA_VERSION,
    build_retrieval_coverage,
    project_legacy_from_coverage,
)

_MAX_SMART_SEARCH_SUB_QUERIES = 3
_MAX_SMART_SEARCH_SUB_QUERY_LENGTH = 120

# The closed Revision 4 partial-reason vocabulary, built from the centralized
# ``coverage.py`` constants — an authority object may carry no other reason.
_CLOSED_PARTIAL_REASONS = frozenset(
    {
        REASON_UNREAD_PAGE,
        REASON_THRESHOLD_EXCLUDED,
        REASON_SOURCE_CAP,
        REASON_INDEX_NOT_FRESH,
        REASON_CHILD_FAILED,
    }
)

_SUBQUERY_FAILED_WARNING = (
    "subquery_failed: %d sub-quer%s returned failure envelopes; the fused set "
    "is partial and total_available is an observed lower bound."
)
_SUBQUERY_COVERAGE_MISSING_WARNING = (
    "subquery_coverage_missing: %d sub-quer%s returned no valid "
    "retrieval_coverage.v1; completeness cannot be proven and total_available "
    "is an observed lower bound."
)

_search_fn = None
logger = logging.getLogger(__name__)


def _is_nonnegative_int(value: Any) -> bool:
    """An actual int (bool excluded) that is not negative."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_authority_coverage(value: Any) -> bool:
    """True when ``value`` is a well-formed ``retrieval_coverage.v1`` object.

    The public strongly-typed contract: every required field present with its
    documented type (``observed_total`` / ``returned`` / ``next_offset`` are
    nonnegative ints, bool excluded; ``next_offset`` may be null), the closed
    Revision 4 partial-reason vocabulary, string-only ``limits_applied``, no
    ``returned`` above ``observed_total``, and a ``status`` matching the
    completeness invariant in BOTH directions — ``complete`` iff
    ``returned == observed_total``, ``next_offset`` is null, and both
    ``partial_reasons`` and ``limits_applied`` are empty; any other shape must
    say ``partial``. Unknown additive keys are tolerated; anything else is not
    an authority and the child fails closed via ``child_failed``.
    """
    if not isinstance(value, dict):
        return False
    if value.get("schema_version") != COVERAGE_SCHEMA_VERSION:
        return False
    if value.get("status") not in {"complete", "partial"}:
        return False
    required_fields = (
        "observed_total",
        "returned",
        "next_offset",
        "partial_reasons",
        "limits_applied",
    )
    if any(field not in value for field in required_fields):
        return False

    observed_total = value["observed_total"]
    returned = value["returned"]
    next_offset = value["next_offset"]
    reasons = value["partial_reasons"]
    limits = value["limits_applied"]

    if not _is_nonnegative_int(observed_total) or not _is_nonnegative_int(returned):
        return False
    if next_offset is not None and not _is_nonnegative_int(next_offset):
        return False
    if not isinstance(reasons, list):
        return False
    if any(reason not in _CLOSED_PARTIAL_REASONS for reason in reasons):
        return False
    if not isinstance(limits, list):
        return False
    if any(not isinstance(limit, str) for limit in limits):
        return False

    # A response cannot return more than it observed.
    if returned > observed_total:
        return False
    # Two-way iff (public contract): the completeness invariant derives the
    # only truthful status, so a hand-made claim in either direction — a
    # 'complete' with a remainder, or a 'partial' that proves completeness —
    # is self-inconsistent and not an authority.
    expected_complete = (
        returned == observed_total and next_offset is None and not reasons and not limits
    )
    return bool(value["status"] == ("complete" if expected_complete else "partial"))


def _get_search_fn() -> Any:
    """Lazy-load hierarchical_search to allow focused test substitution."""
    global _search_fn
    if _search_fn is None:
        from .core import hierarchical_search

        _search_fn = hierarchical_search
    return _search_fn


@dataclass
class SmartSearchResult:
    """Structured output for the smart-search command."""

    success: bool = True
    query: str = ""
    rewritten_query: str = ""
    filtered_results: list[dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    citations: list[str] = field(default_factory=list)
    agent_decisions: list[dict[str, Any]] = field(default_factory=list)
    agent_unavailable: bool = True
    performance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "query": self.query,
            "rewritten_query": self.rewritten_query,
            "filtered_results": self.filtered_results,
            "summary": self.summary,
            "citations": self.citations,
            "agent_decisions": self.agent_decisions,
            "agent_unavailable": self.agent_unavailable,
            "performance": self.performance,
        }


class _RewrittenPlan(TypedDict, total=False):
    core_terms: str
    expanded_terms: list[str]
    time_range: Any
    intent_type: str
    rewritten_query: str
    sub_queries: list[str]
    semantic_fallback_query: str | None
    search_plan: dict[str, Any]


class _SearchExecution(TypedDict):
    raw_results: dict[str, Any]
    candidates: list[dict[str, Any]]
    total_available: int
    sub_queries: list[str]
    strategy: str
    semantic_fallback_used: bool
    semantic_fallback_query: str | None
    retrieval_coverage: dict[str, Any]


@dataclass(frozen=True)
class _EvidenceBuild:
    data: dict[str, Any] | None = None
    elapsed_ms: float = 0.0
    error: str | None = None


def _build_agent_instructions(mode: str) -> dict[str, Any]:
    """Build deterministic instructions for the calling host agent."""
    return {
        "schema_version": "smart_search.agent_instructions.v1",
        "role": "calling_agent",
        "mode": mode,
        "steps": [
            "Use filtered_results as bounded evidence; do not cite outside returned results.",
            "If filtered_results is empty, say that this search did not find enough evidence.",
            "Prefer concise synthesis with file/date citations from returned results.",
            (
                "For broader interpretation, run another explicit smart-search query "
                "rather than inventing evidence."
            ),
        ],
    }


def _build_answer_scaffold(query: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Build provider-free response guidance for host-agent consumers."""
    return {
        "schema_version": "smart_search.answer_scaffold.v1",
        "query": query,
        "citation_policy": "cite_only_returned_results",
        "result_count": len(results),
        "suggested_response_shape": {
            "summary": "brief evidence-backed answer",
            "citations": "file/date references from filtered_results",
            "limitations": "explicitly name missing evidence or low recall",
        },
    }


def _result_identity(item: dict[str, Any]) -> str:
    """Return a stable deduplication key for search candidates."""
    for key in ("rel_path", "path", "title"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


class SmartSearchOrchestrator:
    """Build a deterministic smart-search scaffold."""

    @staticmethod
    def _bounded_unique_strings(values: list[str]) -> list[str]:
        """Return bounded, de-duplicated non-empty strings preserving order."""
        normalized: list[str] = []
        for item in values:
            value = item.strip()
            if not value or value in normalized:
                continue
            normalized.append(value[:_MAX_SMART_SEARCH_SUB_QUERY_LENGTH])
            if len(normalized) >= _MAX_SMART_SEARCH_SUB_QUERIES:
                break
        return normalized

    def _deterministic_rewrite_query(self, query: str) -> _RewrittenPlan:
        """Build the smart-search scaffold from the shared deterministic plan."""
        from .query_preprocessor import build_search_plan

        plan = build_search_plan(query)
        plan_dict = plan.to_dict()
        keywords = [kw for kw in plan.keywords if isinstance(kw, str) and kw.strip()]
        query_mode = plan_dict.get("query_mode")
        base_query = plan.expanded_query or plan.normalized_query or plan.raw_query or query

        if query_mode in {"natural_language", "mixed"} and keywords:
            sub_queries = self._bounded_unique_strings(keywords)
        else:
            sub_queries = self._bounded_unique_strings([base_query])
        if not sub_queries:
            sub_queries = [query[:_MAX_SMART_SEARCH_SUB_QUERY_LENGTH]]

        return {
            "core_terms": " ".join(keywords) if keywords else base_query,
            "expanded_terms": [],
            "time_range": plan_dict.get("date_range"),
            "intent_type": plan_dict.get("intent_type", "unknown"),
            "rewritten_query": base_query,
            "sub_queries": sub_queries,
            "semantic_fallback_query": None,
            "search_plan": plan_dict,
        }

    def rewrite_query(self, query: str) -> _RewrittenPlan:
        """Build a deterministic structured query plan."""
        return self._deterministic_rewrite_query(query)

    def _normalize_sub_queries(self, rewritten: _RewrittenPlan) -> list[str]:
        """Clamp deterministic query decomposition to a bounded list."""
        base_query = str(
            rewritten.get("rewritten_query") or rewritten.get("core_terms") or ""
        ).strip()
        raw = rewritten.get("sub_queries")
        if not isinstance(raw, list) or not raw:
            raw = [base_query]
        normalized = self._bounded_unique_strings([item for item in raw if isinstance(item, str)])
        return normalized or [base_query[:_MAX_SMART_SEARCH_SUB_QUERY_LENGTH]]

    @staticmethod
    def _coerce_iso_date(value: Any) -> str | None:
        """Accept only exact ISO calendar dates."""
        if not isinstance(value, str):
            return None
        candidate = value.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            return candidate
        return None

    @classmethod
    def _resolve_time_range(cls, rewritten: _RewrittenPlan) -> dict[str, str]:
        """Map deterministic time-range metadata to search date filters."""
        raw = rewritten.get("time_range")
        if raw is None:
            return {}
        if isinstance(raw, dict):
            date_from = (
                cls._coerce_iso_date(raw.get("date_from"))
                or cls._coerce_iso_date(raw.get("since"))
                or cls._coerce_iso_date(raw.get("start"))
            )
            date_to = (
                cls._coerce_iso_date(raw.get("date_to"))
                or cls._coerce_iso_date(raw.get("until"))
                or cls._coerce_iso_date(raw.get("end"))
            )
            return {
                key: value
                for key, value in {"date_from": date_from, "date_to": date_to}.items()
                if value
            }
        if not isinstance(raw, str):
            return {}
        value = raw.strip()
        range_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", value)
        if range_match:
            return {"date_from": range_match.group(1), "date_to": range_match.group(2)}
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return {"date_from": value, "date_to": value}
        month_match = re.fullmatch(r"(\d{4})-(\d{2})", value)
        if month_match:
            year = int(month_match.group(1))
            month = int(month_match.group(2))
            if 1 <= month <= 12:
                last_day = calendar.monthrange(year, month)[1]
                return {
                    "date_from": f"{year:04d}-{month:02d}-01",
                    "date_to": f"{year:04d}-{month:02d}-{last_day:02d}",
                }
        year_match = re.fullmatch(r"(\d{4})", value)
        if year_match:
            year = int(year_match.group(1))
            return {"date_from": f"{year:04d}-01-01", "date_to": f"{year:04d}-12-31"}
        return {}

    @staticmethod
    def _select_search_strategy(
        rewritten: _RewrittenPlan,
        sub_queries: list[str],
        search_kwargs: dict[str, str],
    ) -> str:
        """Select a truthful deterministic QueryPlan strategy label."""
        if len(sub_queries) > 1:
            return "keyword_multi_pass"
        if search_kwargs:
            return "keyword_temporal"
        return "keyword_only"

    @staticmethod
    def _child_accepts_offset(search_fn: Any) -> bool:
        """Whether the retrieval backend can apply a continuation offset itself.

        The production backend (``hierarchical_search``) returns the full
        admitted set and takes no ``offset``; the smart-search layer then
        applies the window itself. Only a backend that declares an explicit
        ``offset`` parameter receives the cursor directly — a ``**kwargs``
        sink is not proof that the backend pages, so it never triggers
        forwarding.
        """
        try:
            parameters = inspect.signature(search_fn).parameters
        except (TypeError, ValueError):
            return False
        param = parameters.get("offset")
        return param is not None and param.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )

    @staticmethod
    def _consume_child_coverage(
        result: dict[str, Any],
        child_items: list[dict[str, Any]],
    ) -> tuple[list[str], list[str], int, bool, bool]:
        """Consume one child retrieval's completeness signals.

        The child's ``retrieval_coverage.v1`` is the only completeness
        authority: its ``partial_reasons`` / ``limits_applied`` propagate and
        its ``observed_total`` names the admitted set. A child that fails, or
        answers without a valid coverage authority, fails closed for
        completeness via the closed-vocabulary ``child_failed`` reason —
        legacy ``has_more`` / ``total_*`` projections are compatibility inputs
        that can never prove completeness.

        Returns ``(partial_reasons, limits_applied, observed_total,
        failed_envelope, authority_missing)``.
        """
        reasons: list[str] = []
        applied: list[str] = []
        failed_envelope = result.get("success") is False
        if failed_envelope:
            reasons.append(REASON_CHILD_FAILED)

        coverage = result.get("retrieval_coverage")
        if _is_authority_coverage(coverage):
            # ``_is_authority_coverage`` proved the dict shape; ``cast`` only
            # narrows the type and is a runtime no-op.
            authority = cast(dict[str, Any], coverage)
            observed_total = int(authority.get("observed_total", len(child_items)) or 0)
            for reason in authority.get("partial_reasons") or []:
                value = str(reason)
                if value and value not in reasons:
                    reasons.append(value)
            applied = [str(limit) for limit in authority.get("limits_applied") or []]
            return reasons, applied, observed_total, failed_envelope, False

        # Missing/invalid authority: completeness cannot be proven, so fail
        # closed via ``child_failed`` (Revision 4 closed vocabulary — no
        # invented reason) and derive only conservative legacy signals.
        if REASON_CHILD_FAILED not in reasons:
            reasons.append(REASON_CHILD_FAILED)
        observed_total = int(result.get("total_available", 0) or 0)
        if observed_total <= 0:
            observed_total = int(result.get("total_matches", 0) or 0)
        if observed_total <= 0:
            observed_total = len(child_items)
        if bool(result.get("has_more", False)) or observed_total > len(child_items):
            if REASON_UNREAD_PAGE not in reasons:
                reasons.append(REASON_UNREAD_PAGE)
        return reasons, applied, observed_total, failed_envelope, True

    @staticmethod
    def _build_window_coverage(
        *,
        observed_total: int,
        returned: int,
        offset: int,
        reasons: list[str],
        limits: list[str],
    ) -> dict[str, Any]:
        """Build the smart-search window coverage from consumed child signals.

        The delivered window carries at most ``ORCHESTRATOR_MAX_CANDIDATES``
        items. A window that truly bound the response (the offset alone did
        not) is recorded as ``result_limit:<n>``, mirroring the search
        presentation-layer convention.
        """
        applied = list(limits)
        if offset + ORCHESTRATOR_MAX_CANDIDATES < observed_total:
            applied.append(f"result_limit:{ORCHESTRATOR_MAX_CANDIDATES}")
        return build_retrieval_coverage(
            observed_total=observed_total,
            returned=returned,
            offset=offset,
            partial_reasons=reasons,
            limits_applied=applied,
        )

    def execute_search(self, rewritten: _RewrittenPlan, offset: int = 0) -> _SearchExecution:
        """Execute bounded search using deterministic primitives.

        ``offset`` is the public continuation cursor: the delivered window is
        ``[offset, offset + ORCHESTRATOR_MAX_CANDIDATES)`` of the same
        deterministic ranked list, so pages neither repeat nor omit candidates
        while the corpus is unchanged. The response always carries the
        ``retrieval_coverage`` authority scoped to that window.
        """
        search_fn = _get_search_fn()
        sub_queries = self._normalize_sub_queries(rewritten)
        search_kwargs = self._resolve_time_range(rewritten)
        strategy = self._select_search_strategy(rewritten, sub_queries, search_kwargs)

        if len(sub_queries) == 1:
            child_kwargs: dict[str, Any] = dict(search_kwargs)
            forwarded_offset = False
            if offset > 0 and self._child_accepts_offset(search_fn):
                child_kwargs["offset"] = offset
                forwarded_offset = True
            result = search_fn(query=sub_queries[0], **child_kwargs)
            child_items = result.get("merged_results", [])
            window_reasons, applied, observed_total, failed, authority_missing = (
                self._consume_child_coverage(result, child_items)
            )
            window_warnings = [str(warning) for warning in result.get("warnings", []) if warning]
            if failed:
                window_warnings.append(_SUBQUERY_FAILED_WARNING % (1, "y"))
            elif authority_missing:
                window_warnings.append(_SUBQUERY_COVERAGE_MISSING_WARNING % (1, "y"))
            if forwarded_offset:
                # The backend already applied the window semantics itself.
                merged = child_items[:ORCHESTRATOR_MAX_CANDIDATES]
            else:
                merged = child_items[offset : offset + ORCHESTRATOR_MAX_CANDIDATES]
            coverage = self._build_window_coverage(
                observed_total=observed_total,
                returned=len(merged),
                offset=offset,
                reasons=window_reasons,
                limits=applied,
            )
            raw_results = dict(result)
            raw_results["merged_results"] = merged
            raw_results["warnings"] = window_warnings
            raw_results["retrieval_coverage"] = coverage
            # Revision 4: legacy compatibility fields are projections of the
            # coverage authority — has_more only means a mechanical next page.
            raw_results.update(project_legacy_from_coverage(coverage))
            return {
                "raw_results": raw_results,
                "candidates": merged,
                "total_available": observed_total,
                "sub_queries": sub_queries,
                "strategy": strategy,
                "semantic_fallback_used": False,
                "semantic_fallback_query": None,
                "retrieval_coverage": coverage,
            }

        raw_query_results: list[dict[str, Any]] = []
        fused_by_key: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        applied_limits: list[str] = []
        failed_children = 0
        authority_missing_children = 0
        total_time_ms = 0.0
        warnings: list[str] = []
        # Children are always queried for their full observed set (no offset is
        # forwarded): the fused, ranked union is then windowed locally, which
        # is the only way multi-query pages stay free of repeats and gaps
        # without a persistent cursor authority.
        for sub_query in sub_queries:
            result = search_fn(query=sub_query, **search_kwargs)
            raw_query_results.append({"query": sub_query, "result": result})
            total_time_ms += float(result.get("performance", {}).get("total_time_ms", 0) or 0)
            warnings.extend(str(warning) for warning in result.get("warnings", []) if warning)
            child_items = result.get("merged_results", [])
            child_reasons, child_limits, _child_total, failed, authority_missing = (
                self._consume_child_coverage(result, child_items)
            )
            if failed:
                failed_children += 1
            elif authority_missing:
                authority_missing_children += 1
            for reason in child_reasons:
                if reason not in reasons:
                    reasons.append(reason)
            for limit in child_limits:
                if limit not in applied_limits:
                    applied_limits.append(limit)
            for item in child_items:
                key = _result_identity(item)
                if not key:
                    continue
                candidate = dict(item)
                candidate["source_queries"] = [sub_query]
                existing = fused_by_key.get(key)
                if existing is None:
                    fused_by_key[key] = candidate
                    continue
                existing["source_queries"] = sorted(
                    set(existing.get("source_queries", []) + [sub_query])
                )
                existing_score = float(existing.get("rrf_score", 0) or 0)
                candidate_score = float(candidate.get("rrf_score", 0) or 0)
                if candidate_score > existing_score:
                    for field_name in (
                        "title",
                        "date",
                        "abstract",
                        "snippet",
                        "path",
                        "rel_path",
                    ):
                        if candidate.get(field_name):
                            existing[field_name] = candidate[field_name]
                    existing["rrf_score"] = candidate_score

        if failed_children:
            warnings.append(
                _SUBQUERY_FAILED_WARNING % (failed_children, "y" if failed_children == 1 else "ies")
            )
        if authority_missing_children:
            warnings.append(
                _SUBQUERY_COVERAGE_MISSING_WARNING
                % (authority_missing_children, "y" if authority_missing_children == 1 else "ies")
            )

        observed_unique = len(fused_by_key)
        # Deterministic ordering: rrf_score descending with the stable journal
        # identity as the secondary key, so equal-score candidates never depend
        # on child iteration order and page boundaries stay repeatable.
        ranked = sorted(
            fused_by_key.values(),
            key=lambda item: (
                -float(item.get("rrf_score", 0) or 0),
                _result_identity(item),
            ),
        )
        merged = ranked[offset : offset + ORCHESTRATOR_MAX_CANDIDATES]
        coverage = self._build_window_coverage(
            observed_total=observed_unique,
            returned=len(merged),
            offset=offset,
            reasons=reasons,
            limits=applied_limits,
        )
        raw_results = {
            "success": True,
            "query_params": {
                "query": rewritten.get("rewritten_query") or " ".join(sub_queries),
                "semantic": False,
            },
            "merged_results": merged,
            "semantic_results": [],
            "no_confident_match": observed_unique == 0,
            "performance": {"total_time_ms": round(total_time_ms, 2)},
            "warnings": warnings,
            "search_plan": rewritten.get("search_plan"),
            "semantic_policy": "deprecated_noop",
            "semantic_effective_policy": "off",
            "semantic_fallback_used": False,
            "semantic_fallback_query": None,
            "multi_query_results": raw_query_results,
            "retrieval_coverage": coverage,
        }
        # Revision 4: legacy compatibility fields are projections of the
        # coverage authority — has_more only means a mechanical next page.
        raw_results.update(project_legacy_from_coverage(coverage))
        return {
            "raw_results": raw_results,
            "candidates": merged,
            "total_available": observed_unique,
            "sub_queries": sub_queries,
            "strategy": strategy,
            "semantic_fallback_used": False,
            "semantic_fallback_query": None,
            "retrieval_coverage": coverage,
        }

    @staticmethod
    def _try_aggregate(query: str) -> dict[str, Any] | None:
        """Return a deterministic aggregate result or fall back to search."""
        from .aggregate_router import try_route_aggregate

        aggregate_route = try_route_aggregate(query)
        if aggregate_route is None:
            return None
        try:
            from tools.aggregate.core import run_aggregate

            return run_aggregate(
                range_str=aggregate_route.range_str,
                unit=aggregate_route.unit,
                predicate=aggregate_route.predicate,
                query=aggregate_route.query,
            )
        except Exception as exc:
            logger.warning("[Orchestrator] Aggregate delegation failed: %s", exc)
            return None

    @staticmethod
    def _build_aggregate_envelope(
        query: str,
        aggregate_result: dict[str, Any],
        start_time: float,
    ) -> dict[str, Any]:
        """Build the stable smart-search envelope for aggregate delegation."""
        result = SmartSearchResult(
            query=query,
            rewritten_query=query,
            performance={
                "total_time_ms": round((time.time() - start_time) * 1000, 2),
                "rewrite_time_ms": 0,
                "filter_time_ms": 0,
                "search_time_ms": 0,
                "total_available": 0,
            },
        ).to_dict()
        result["smart_search_mode"] = "deterministic_aggregate"
        result["agent_instructions"] = _build_agent_instructions(result["smart_search_mode"])
        result["answer_scaffold"] = _build_answer_scaffold(query, [])
        result["query_plan"] = QueryPlan(
            raw_query=query,
            expanded_query=query,
            sub_queries=[query],
            strategy="deterministic_aggregate",
            fallback_decision=False,
        ).to_dict()
        result["aggregate_result"] = aggregate_result
        return result

    @staticmethod
    def _build_evidence(
        query: str,
        rewritten: _RewrittenPlan,
        search_result: _SearchExecution,
    ) -> _EvidenceBuild:
        """Build evidence best-effort without affecting search success."""
        from tools.evidence.adapter import extract_evidence_from_orchestrator

        evidence_started = time.time()
        try:
            evidence_pack = extract_evidence_from_orchestrator(
                search_result["raw_results"],
                smart_result={
                    "rewritten_query": rewritten.get("rewritten_query"),
                    "original_query": query,
                },
            )
            evidence_data = evidence_pack.to_dict()
            rewritten_query = evidence_data.pop("rewritten_query", None)
            if rewritten_query:
                evidence_data.setdefault("query_context", {})["rewritten_query"] = rewritten_query
            return _EvidenceBuild(
                data=evidence_data,
                elapsed_ms=(time.time() - evidence_started) * 1000,
            )
        except Exception as exc:
            logger.warning("[Orchestrator] Evidence build failed: %s", exc)
            return _EvidenceBuild(
                elapsed_ms=(time.time() - evidence_started) * 1000,
                error=str(exc),
            )

    @staticmethod
    def _build_search_envelope(
        query: str,
        rewritten: _RewrittenPlan,
        search_result: _SearchExecution,
        planner_stages: list[StageRecord],
        evidence: _EvidenceBuild,
        *,
        include_evidence: bool,
        start_time: float,
    ) -> dict[str, Any]:
        """Assemble planner provenance, performance, evidence, and stable fields."""
        candidates = search_result["candidates"]
        planner_record = build_planner_record_from_stages(planner_stages)
        evidence_data = evidence.data
        if evidence_data is not None:
            query_context = evidence_data.setdefault("query_context", {})
            existing_plan = query_context.get("search_plan")
            query_context["search_plan"] = merge_planner_into_search_plan(
                existing_plan,
                planner_record,
            )

        result = SmartSearchResult(
            query=query,
            rewritten_query=rewritten.get("rewritten_query", query),
            filtered_results=candidates,
            performance={
                "total_time_ms": round((time.time() - start_time) * 1000, 2),
                "rewrite_time_ms": 0,
                "filter_time_ms": 0,
                "search_time_ms": search_result["raw_results"]
                .get("performance", {})
                .get("total_time_ms", 0),
                "total_available": search_result["total_available"],
            },
        ).to_dict()
        raw_fallback = search_result["raw_results"].get("semantic_fallback_used")
        if raw_fallback is not None:
            result["semantic_fallback_used"] = bool(raw_fallback)
        result["smart_search_mode"] = "deterministic_scaffold"
        result["agent_instructions"] = _build_agent_instructions(result["smart_search_mode"])
        result["answer_scaffold"] = _build_answer_scaffold(query, candidates)
        result["query_plan"] = QueryPlan(
            raw_query=query,
            expanded_query=rewritten.get("rewritten_query"),
            sub_queries=search_result.get("sub_queries", [query]),
            strategy=search_result.get("strategy", "keyword_only"),
            fallback_decision=False,
        ).to_dict()
        # Phase 2A: the smart-search window coverage is the additive public
        # completeness authority for this response.
        result["retrieval_coverage"] = search_result["retrieval_coverage"]
        if evidence_data is not None:
            result["performance"]["evidence_build_ms"] = round(evidence.elapsed_ms, 2)
            result["evidence_pack"] = evidence_data
        elif include_evidence:
            result["performance"]["evidence_build_ms"] = round(evidence.elapsed_ms, 2)
            result["performance"]["evidence_error"] = evidence.error
        return result

    def search(
        self,
        query: str,
        *,
        include_evidence: bool = False,
        synthesize: bool = False,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Execute deterministic smart-search; ``synthesize`` is a compatibility no-op.

        ``offset`` is the public continuation cursor: pass the previous
        response's ``retrieval_coverage.next_offset`` to fetch the next window
        of the same deterministic query/filter/date semantics. The tool holds
        no snapshot between pages; each page recomputes against the current
        admitted set and stays honest about it.
        """
        offset = int(offset)
        if offset < 0:
            raise ValueError("smart-search continuation offset must be non-negative")
        start_time = time.time()
        aggregate_result = self._try_aggregate(query)
        if aggregate_result is not None:
            return self._build_aggregate_envelope(query, aggregate_result, start_time)

        rewritten = self.rewrite_query(query)
        planner_stages = [
            StageRecord(
                name="rewrite",
                status="success",
                latency_ms=0.0,
                parameters={"deterministic": True},
            )
        ]
        search_started = time.time()
        search_result = self.execute_search(rewritten, offset=offset)
        candidates = search_result["candidates"]
        planner_stages.append(
            StageRecord(
                name="search",
                status="success",
                latency_ms=round((time.time() - search_started) * 1000, 2),
                parameters={
                    "total_available": search_result["total_available"],
                    "candidates_returned": len(candidates),
                },
            )
        )
        evidence = (
            self._build_evidence(query, rewritten, search_result)
            if include_evidence
            else _EvidenceBuild()
        )
        if include_evidence:
            planner_stages.append(
                StageRecord(
                    name="evidence",
                    status="success" if evidence.data is not None else "failed",
                    latency_ms=round(evidence.elapsed_ms, 2),
                )
            )
        planner_stages.append(
            StageRecord(
                name="filter",
                status="success" if candidates else "skipped",
                latency_ms=0.0,
                parameters={"input_candidates": len(candidates)},
            )
        )
        return self._build_search_envelope(
            query,
            rewritten,
            search_result,
            planner_stages,
            evidence,
            include_evidence=include_evidence,
            start_time=start_time,
        )
