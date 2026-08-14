#!/usr/bin/env python3
"""Life Index - Smart Search CLI Entry Point.

Usage:
    life-index smart-search --query "..."
    python -m tools.smart_search --query "..."

Deterministic smart search entry point. Higher-level interpretation belongs
to the host agent and Skills.
"""

import argparse
import json
import sys
import time
from typing import Any

from tools.lib.tool_call_log import emit_tool_call_log

SCHEMA_VERSION = "m16.smart_search.v0"
SYNTHESIZE_DEPRECATION_WARNING = (
    "DEPRECATED: --synthesize is a compatibility no-op; synthesis belongs to the "
    "Host Agent + Life Index Skill."
)


def _non_negative_int(value: str) -> int:
    """Argparse type for the public continuation offset."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"offset must be >= 0, got {parsed}")
    return parsed


def _emit_json(payload: dict[str, Any]) -> None:
    """Print JSON safely across Windows console encodings."""
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    try:
        print(text)
    except UnicodeEncodeError:
        print(json.dumps(payload, ensure_ascii=True, indent=2, default=str))


def main() -> None:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(
        description="Smart search with a deterministic keyword/entity scaffold",
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        required=True,
        help="Natural language search query",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        default=False,
        help="Include agent decisions in output",
    )
    parser.add_argument(
        "--include-evidence",
        action="store_true",
        default=False,
        help="Include evidence pack in output",
    )
    parser.add_argument(
        "--synthesize",
        action="store_true",
        default=False,
        help="Accepted compatibility no-op; no LLM and no answer",
    )
    parser.add_argument(
        "--format-entity-annotated",
        action="store_true",
        default=False,
        help=(
            "Include human-readable formatted evidence when "
            "--include-evidence is set (explicit opt-in)"
        ),
    )
    parser.add_argument(
        "--offset",
        type=_non_negative_int,
        default=0,
        help=(
            "Continuation offset: pass the previous response's "
            "retrieval_coverage.next_offset to fetch the next result window "
            "(default: 0)"
        ),
    )
    args = parser.parse_args()

    if args.synthesize:
        print(SYNTHESIZE_DEPRECATION_WARNING, file=sys.stderr)

    from tools.search_journals.orchestrator import SmartSearchOrchestrator

    orch = SmartSearchOrchestrator()
    # The continuation cursor is forwarded only when a continuation is actually
    # requested, so callers/mocks of the documented default entry shape stay
    # byte-compatible with the pre-Phase-2A call.
    search_kwargs: dict[str, Any] = {
        "include_evidence": args.include_evidence,
        "synthesize": args.synthesize,
    }
    if args.offset:
        search_kwargs["offset"] = args.offset
    result = orch.search(args.query, **search_kwargs)

    # Opt-in deterministic evidence formatter (additive only)
    if args.include_evidence and getattr(args, "format_entity_annotated", False):
        evidence_pack = result.get("evidence_pack")
        if evidence_pack is not None:
            from tools.evidence.types import EvidencePack
            from tools.evidence.consumer_formatter import format_entity_annotated

            pack = EvidencePack.from_dict(evidence_pack)
            result["formatted_evidence"] = format_entity_annotated(pack)

    # Optionally strip agent_decisions for cleaner output
    if not args.explain and "agent_decisions" in result:
        result["agent_decisions_summary"] = f"{len(result['agent_decisions'])} decisions made"
        del result["agent_decisions"]

    # Add deterministic diagnostics when --explain is requested
    if args.explain:
        perf = result.get("performance", {})
        latency_ms: dict[str, float] = {
            "total": perf.get("total_time_ms", 0),
        }
        if "rewrite_time_ms" in perf:
            latency_ms["rewrite"] = perf["rewrite_time_ms"]
        if "search_time_ms" in perf:
            latency_ms["search"] = perf["search_time_ms"]
        if "filter_time_ms" in perf:
            latency_ms["filter"] = perf["filter_time_ms"]
        if "evidence_build_ms" in perf:
            latency_ms["evidence"] = perf["evidence_build_ms"]
        if "synthesis_ms" in perf:
            latency_ms["synthesis"] = perf["synthesis_ms"]

        result["diagnostics"] = {
            "input_count": perf.get("total_available", 0),
            "filter_drops": {},
            "cache_hits": 0,
            "cache_misses": 0,
            "latency_ms": latency_ms,
            "fallback_path": None,
        }

        from tools.lib.planner_types import QueryPlan

        if "query_plan" not in result:
            result["query_plan"] = QueryPlan(
                raw_query=args.query,
                expanded_query=result.get("query_params", {}).get("expanded_query"),
                sub_queries=[args.query],
                strategy="keyword_only",
                fallback_decision=False,
            ).to_dict()

    result["schema_version"] = SCHEMA_VERSION
    raw_log_evidence_pack = result.get("evidence_pack")
    log_evidence_pack: dict[str, Any] = (
        raw_log_evidence_pack if isinstance(raw_log_evidence_pack, dict) else {}
    )
    raw_evidence_items = log_evidence_pack.get("items")
    evidence_items: list[Any] = raw_evidence_items if isinstance(raw_evidence_items, list) else []
    emit_tool_call_log(
        "smart-search",
        params={
            "query": args.query,
            "include_evidence": args.include_evidence,
            "synthesize": args.synthesize,
            "offset": args.offset,
        },
        result={
            "total_found": result.get("total_found"),
            "total_available": result.get("total_available"),
            "evidence_count": len(evidence_items),
            "mode": result.get("smart_search_mode"),
        },
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
        success=bool(result.get("success")),
    )
    _emit_json(result)
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
