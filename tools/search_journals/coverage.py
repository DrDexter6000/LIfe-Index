#!/usr/bin/env python3
"""Life Index - Retrieval Coverage (``retrieval_coverage.v1``).

Phase 1 establishes ``retrieval_coverage.v1`` as the single authority for
retrieval completeness. The legacy ``total_found`` / ``total_matches`` /
``total_available`` / ``has_more`` fields remain only as compatibility
projections of this object.

A coverage object is *complete* iff the single response truthfully observed and
returned the same admitted set with no remainder:

* ``returned == observed_total`` (this response carries the whole admitted set),
* ``next_offset`` is ``None`` (no mechanical continuation), and
* neither ``partial_reasons`` nor ``limits_applied`` record a defect.

Anything else — a page slice, an explicit threshold that excluded candidates, an
un-refreshed stale index, or a retrieval cap — makes the coverage *partial* and
lists the honest reason.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "retrieval_coverage.v1"

# Partial-reason vocabulary. These are the only allowed ``partial_reasons``
# entries; each explains why a retrieval is not provably complete. Every entry
# must have a real emission path — unreachable reasons are removed rather than
# advertised.
REASON_UNREAD_PAGE = "unread_page"  # more pages mechanically follow
REASON_THRESHOLD_EXCLUDED = "threshold_excluded"  # explicit relevance threshold dropped >=1
REASON_SOURCE_CAP = "source_cap"  # a retrieval cap truncated the observed set
REASON_INDEX_NOT_FRESH = "index_not_fresh"  # un-refreshed stale / failed update
# A retrieval child failed, or answered without a valid ``retrieval_coverage.v1``
# authority so completeness cannot be proven (Revision 4 closed vocabulary).
REASON_CHILD_FAILED = "child_failed"


def build_retrieval_coverage(
    *,
    observed_total: int,
    returned: int,
    offset: int = 0,
    partial_reasons: list[str] | None = None,
    limits_applied: list[str] | None = None,
) -> dict[str, Any]:
    """Construct a strongly-typed ``retrieval_coverage.v1`` object.

    ``next_offset`` is the deterministic forward-continuation cursor (offset of
    the next page) — it is ``None`` once no more pages mechanically follow. It
    signals ONLY that the same deterministic query can continue; it does not
    imply completeness.

    ``unread_page`` is recorded whenever this single response window does NOT
    carry the whole admitted set (``returned < observed_total``) — including a
    nonzero-offset final page where ``next_offset`` is already null. Such a window
    is always ``partial``.

    ``next_offset`` is emitted only when it strictly advances past the current
    offset; an empty window never yields ``next_offset == 0`` or a cursor equal
    to the offset it was called with (a non-advancing cursor would trap a paging
    caller in a loop).

    ``status`` is derived, never caller-supplied.
    """
    observed_total = int(observed_total or 0)
    returned = int(returned or 0)
    offset = int(offset or 0)

    reasons = list(partial_reasons or [])
    applied = list(limits_applied or [])

    next_offset = (
        offset + returned if returned > 0 and (offset + returned) < observed_total else None
    )
    if returned < observed_total and REASON_UNREAD_PAGE not in reasons:
        reasons.append(REASON_UNREAD_PAGE)

    is_complete = returned == observed_total and next_offset is None and not reasons and not applied

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "complete" if is_complete else "partial",
        "observed_total": observed_total,
        "returned": returned,
        "next_offset": next_offset,
        "partial_reasons": reasons,
        "limits_applied": applied,
    }


def project_legacy_from_coverage(coverage: dict[str, Any]) -> dict[str, Any]:
    """Derive legacy compatibility fields from a coverage object.

    Single source of truth: ``total_matches`` / ``total_available`` mirror
    ``observed_total`` (the full admitted set); ``total_found`` mirrors
    ``returned`` (this response window); ``has_more`` mirrors
    ``next_offset is not None`` (mechanical forward continuation). Projecting
    from the coverage authority keeps the legacy fields from drifting away from
    it.
    """
    return {
        "total_matches": coverage["observed_total"],
        "total_available": coverage["observed_total"],
        "total_found": coverage["returned"],
        "has_more": coverage["next_offset"] is not None,
    }


def _collect_threshold_signal(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract the explicit-threshold partial reason + applied limit, if any.

    ``run_keyword_pipeline`` records ``fts_threshold_excluded`` (count of
    otherwise-matching candidates an explicit relevance threshold dropped) and
    ``fts_threshold`` (the configured threshold value) in ``performance``. A
    threshold that excluded zero candidates is a no-op and must NOT mark the
    retrieval partial.
    """
    perf = result.get("performance") or {}
    excluded = int(perf.get("fts_threshold_excluded", 0) or 0)
    threshold = perf.get("fts_threshold")
    if excluded <= 0:
        return [], []
    reasons = [REASON_THRESHOLD_EXCLUDED]
    applied = [f"fts_threshold:{threshold}"] if threshold is not None else []
    return reasons, applied


def _collect_min_hits_signal(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract the FTS min-hits partial reason + applied limit, if any.

    ``run_keyword_pipeline`` records ``fts_min_hits_excluded`` (count of
    candidates the segmented-query min-hits post-filter dropped and that no
    fallback recovered) and ``fts_min_hits_required`` (the required distinct
    token hits) in ``performance``. Exclusions the fallback fully recovered are
    not recorded there, so a recovered exclusion never double-reports a gap.
    """
    perf = result.get("performance") or {}
    excluded = int(perf.get("fts_min_hits_excluded", 0) or 0)
    if excluded <= 0:
        return [], []
    required = perf.get("fts_min_hits_required")
    applied = [f"fts_min_hits:{required}"] if required is not None else []
    return [REASON_THRESHOLD_EXCLUDED], applied


def _collect_index_freshness_signal(result: dict[str, Any]) -> list[str]:
    """Extract the index-not-fresh reason for an un-refreshed stale index.

    A self-healed index (``auto_updated is True``) is fresh at retrieval time:
    the preceding ``index_stale:`` warning is a process note, not a completeness
    defect. Only an index that stayed stale (no auto-update happened, or the
    update failed) makes the retrieval partial.
    """
    index_status = result.get("index_status") or {}
    if index_status.get("auto_updated") is True:
        return []
    warnings = result.get("warnings") or []
    has_stale = any(str(w).startswith("index_stale:") for w in warnings)
    has_failed_update = any(
        str(w).startswith(("pending_index_update_failed:", "index_update_failed:"))
        for w in warnings
    )
    return [REASON_INDEX_NOT_FRESH] if (has_stale or has_failed_update) else []


def _collect_source_cap_signal(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract the L2 source-cap partial reason + applied limit, if capped.

    ``l2_truncated`` is set only when the L2 metadata source actually truncated
    the observed set — a configured cap that excluded nothing leaves it False, so
    nothing is recorded. The stable closed-set limit string is derived from the
    existing ``l2_total_available`` field.
    """
    if result.get("l2_truncated") is not True:
        return [], []
    available = result.get("l2_total_available")
    limit_str = f"l2_source_cap:{available}" if available is not None else "l2_source_cap"
    return [REASON_SOURCE_CAP], [limit_str]


def collect_coverage_signals(result: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Gather all partial reasons and applied limits from a retrieval result."""
    reasons: list[str] = []
    applied: list[str] = []

    thr_reasons, thr_applied = _collect_threshold_signal(result)
    reasons.extend(thr_reasons)
    applied.extend(thr_applied)

    min_hits_reasons, min_hits_applied = _collect_min_hits_signal(result)
    reasons.extend(min_hits_reasons)
    applied.extend(min_hits_applied)

    reasons.extend(_collect_index_freshness_signal(result))

    cap_reasons, cap_applied = _collect_source_cap_signal(result)
    reasons.extend(cap_reasons)
    applied.extend(cap_applied)
    return reasons, applied


def build_coverage_for_result(
    result: dict[str, Any],
    *,
    returned: int,
    offset: int = 0,
    presentation_limit: int | None = None,
) -> dict[str, Any]:
    """Build the coverage object for a result, scoped to one response window.

    ``observed_total`` is the post-threshold admitted-set size
    (``total_matches``); ``returned``/``offset`` describe the window this
    particular response carries (full set for ``limit=0``, a slice otherwise).

    ``presentation_limit`` is the CLI ``limit`` in effect. A binding cap is
    recorded as a ``result_limit:<n>`` closed-set entry in ``limits_applied`` —
    but ONLY when the limit truly bound the result window, i.e. the window would
    have carried more admitted candidates without it (``offset + limit <
    observed_total``). A final page whose shortfall comes from the OFFSET alone
    (``offset + limit >= observed_total``) records no ``result_limit``: the
    offset, not the limit, bounded that window.
    """
    observed_total = int(result.get("total_matches", 0) or 0)
    reasons, applied = collect_coverage_signals(result)
    if (
        presentation_limit is not None
        and int(presentation_limit) > 0
        and (offset + int(presentation_limit)) < observed_total
    ):
        applied.append(f"result_limit:{int(presentation_limit)}")
    return build_retrieval_coverage(
        observed_total=observed_total,
        returned=returned,
        offset=offset,
        partial_reasons=reasons,
        limits_applied=applied,
    )
