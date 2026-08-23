#!/usr/bin/env python3
"""Pure deterministic builder for aggregate claim envelope and evidence pack.

No LLM, no filesystem writes, no search calls.
"""

from typing import Any, Dict, List, Optional

from ..generate_index.navigation import (
    index_node_ref_for_date as _nav_index_node_ref_for_date,
    index_node_refs_for_range as _nav_index_node_refs_for_range,
)

CLAIM_SCHEMA_VERSION = "m02a.claim_envelope.v0"
EVIDENCE_SCHEMA_VERSION = "m02a.aggregate_evidence_pack.v0"
RETRIEVAL_COVERAGE_SCHEMA_VERSION = "retrieval_coverage.v1"


def claim_type_from_exactness(exactness: str) -> str:
    if exactness == "exact":
        return "measurable_exact"
    if exactness == "approximate":
        return "measurable_approximate"
    if exactness == "partial":
        return "measurable_partial"
    return "not_measurable"


def index_node_ref_for_date(date_str: str) -> Optional[Dict[str, str]]:
    return _nav_index_node_ref_for_date(date_str)


def build_claim_envelope(aggregate_result: Dict[str, Any]) -> Dict[str, Any]:
    """Build a claim envelope from an aggregate result dict."""
    result = aggregate_result.get("result", {})
    exactness = result.get("exactness", "not_measurable")

    envelope: Dict[str, Any] = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "claim_type": claim_type_from_exactness(exactness),
        "source_command": "aggregate",
        "query": aggregate_result.get("query", ""),
        "metric": aggregate_result.get("metric", ""),
        "unit": aggregate_result.get("unit", ""),
        "time_range": aggregate_result.get("range", {}),
        "predicate": aggregate_result.get("predicate", {}),
        "value": result.get("count", 0),
        "denominator": result.get("denominator", 0),
        "exactness": exactness,
        "confidence": result.get("confidence", "low"),
        "limitations": aggregate_result.get("limitations", []),
        "evidence_pack_ref": "aggregate.evidence_pack",
    }

    for bound_field in (
        "min_count",
        "max_count",
        "unknown_count",
        "unknown_bucket_count",
        "count_semantics",
    ):
        if bound_field in result:
            envelope[bound_field] = result[bound_field]

    return envelope


def build_retrieval_coverage_from_scan(
    scan_stats: Dict[str, Any], *, returned: int
) -> Dict[str, Any]:
    """Project aggregate's OWN enumeration facts onto ``retrieval_coverage.v1``.

    Aggregate is the coverage authority for its own scan; nothing here changes
    which files participate in the aggregation. Rules:

    * ``status="complete"`` iff the scan was a fallback full-tree sweep, or the
      month directories actually visited match a cheap directory-listing census
      of month dirs within range — AND no candidate failed to parse;
    * otherwise ``status="partial"``; ``partial_reasons`` only carries closed-set
      codes (month-census mismatch → ``"index_not_fresh"``). Parse-failure
      candidates are disclosed via the existing ``limitations`` channel and are
      NOT given a new closed-set reason code;
    * ``observed_total`` counts candidate paths observed this run (a lower bound
      when partial); ``returned`` is the number of evidence items actually
      carried;
    * ``next_offset`` is always null and ``page_info.has_more`` stays false:
      aggregate has no pagination;
    * ``limits_applied`` lists only limits that truly excluded candidates.
    """
    mode = str(scan_stats.get("mode", "month_refs"))
    months_consistent = bool(scan_stats.get("months_consistent", True))
    unparseable_count = int(scan_stats.get("unparseable_count", 0))
    observed_total = int(scan_stats.get("candidate_count", 0))

    partial_reasons: List[str] = []
    if mode != "fallback_full_scan" and not months_consistent:
        partial_reasons.append("index_not_fresh")

    is_complete = (mode == "fallback_full_scan" or months_consistent) and unparseable_count == 0

    return {
        "schema_version": RETRIEVAL_COVERAGE_SCHEMA_VERSION,
        "status": "complete" if is_complete else "partial",
        "observed_total": observed_total,
        "returned": int(returned),
        "next_offset": None,
        "partial_reasons": partial_reasons,
        "limits_applied": [],
    }


def build_evidence_pack(
    *,
    aggregate_result: Dict[str, Any],
    entry_dates: Dict[str, str],
    bucket_by_path: Dict[str, str],
    retrieval_coverage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an evidence pack from aggregate result metadata."""
    matched = set(aggregate_result.get("matched_entries", []))
    excluded = set(aggregate_result.get("excluded_entries", []))
    unknown_entries = aggregate_result.get("unknown_entries", [])
    unknown_paths = {u["path"] for u in unknown_entries}

    items: List[Dict[str, Any]] = []
    all_paths = set(entry_dates.keys())

    for path in sorted(all_paths):
        if path in matched:
            role = "matched"
            reason = None
        elif path in excluded:
            role = "excluded"
            reason = None
        elif path in unknown_paths:
            role = "unknown"
            # Find the reason from unknown_entries
            reason = next(
                (u["reason"] for u in unknown_entries if u["path"] == path),
                None,
            )
        else:
            role = "unknown"
            reason = None

        item: Dict[str, Any] = {
            "path": path,
            "date": entry_dates.get(path),
            "role": role,
            "bucket": bucket_by_path.get(path),
        }
        if reason is not None:
            item["reason"] = reason
        index_ref = index_node_ref_for_date(entry_dates.get(path, ""))
        if index_ref is not None:
            item["index_node_ref"] = index_ref
        items.append(item)

    time_range = aggregate_result.get("range", {})
    scope_refs: list[Dict[str, str]] = []
    since = time_range.get("since")
    until = time_range.get("until")
    if since and until:
        scope_refs = _nav_index_node_refs_for_range(since, until)

    pack: Dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "source_command": "aggregate",
        "query": aggregate_result.get("query", ""),
        "time_range": time_range,
        "predicate": aggregate_result.get("predicate", {}),
        "items": items,
        "index_scope": {
            "type": "month_range",
            "refs": scope_refs,
            "note": "navigation anchors only; evidence items remain authoritative",
        },
    }
    if retrieval_coverage is not None:
        pack["retrieval_coverage"] = retrieval_coverage
    pack["page_info"] = {
        "has_more": False,
        "cursor": None,
        "cursor_hint": None,
    }
    return pack
