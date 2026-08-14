#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - CLI Entry Point
分层检索日志（keyword/entity only；--semantic* 为废弃兼容 no-op）
"""

# ruff: noqa: E402

# ── Encoding protection (R10 fix) ──────────────────────────────────────
# MUST run before imports that might emit subprocess-visible output.
# On Windows, non-UTF-8 bytes on stderr can corrupt JSON callers that read
# with encoding='utf-8'.
from ._bootstrap import ensure_utf8_io

ensure_utf8_io()

import argparse
import json
import sys
import time
from importlib import import_module
from typing import Literal

from .core import hierarchical_search
from ..lib.config import ensure_dirs
from ..lib.observability import build_provenance_envelope
from ..lib.paths import get_journals_dir, get_user_data_dir
from ..lib.trace import Trace
from ..lib.tool_call_log import emit_tool_call_log

SCHEMA_VERSION = "m16.search.v0"


def _apply_presentation_layer(result: dict, *, limit: int | None, offset: int = 0) -> None:
    """Slice merged_results for display only. Mutates result in place.

    Retrieval layer returns complete ranked candidate set with total_matches
    (full count).  This function slices for CLI display only, preserving
    total_matches.  Per CHARTER §1.11 rule #2: truncation lives in the
    display layer only.

    * limit = 0  →  no truncation (return full set)
    * limit >= 1 →  return at most ``limit`` results
    * offset >= 1 →  skip first ``offset`` results before applying limit
    """
    if "merged_results" not in result:
        return

    # Fail-closed result: respect the closed error envelope. Do not slice, do not
    # synthesize a false-complete coverage object, and do not override the closed
    # legacy totals already set by the retrieval layer.
    if result.get("success") is False:
        return

    total_matches = result.get("total_matches", len(result["merged_results"]))
    all_results = result["merged_results"]

    if offset and offset > 0:
        all_results = all_results[offset:]

    if limit is not None and limit > 0:
        all_results = all_results[:limit]

    displayed = len(all_results)
    result["merged_results"] = all_results

    # Phase 1 (#3/#4): re-scope retrieval_coverage.v1 to THIS response window and
    # PROJECT the legacy total_*/has_more fields from it (single authority). The
    # retrieval layer built the object against the full admitted set
    # (returned=total_matches, offset=0); pagination narrows it to the slice
    # actually carried by this response. ``observed_total`` stays the full
    # admitted-set size, so a page (final or not) with returned < observed_total
    # is honestly ``partial`` and lists ``unread_page``. A binding presentation
    # limit is recorded as ``result_limit:<n>`` only when it actually excluded
    # candidates. ``has_more`` / ``next_offset`` signal only whether the same
    # deterministic query can mechanically continue.
    from .coverage import build_coverage_for_result, project_legacy_from_coverage

    result["retrieval_coverage"] = build_coverage_for_result(
        result, returned=displayed, offset=offset, presentation_limit=limit
    )
    result.update(project_legacy_from_coverage(result["retrieval_coverage"]))

    if total_matches > 0:
        result["display_summary"] = f"Showing {displayed} of {total_matches} results"
    else:
        result["display_summary"] = "No results found"


def _attach_events(payload: dict) -> None:
    """Attach the existing piggyback-event envelope to a domain result."""
    from ..lib.events import detect_events
    from ..lib.event_detectors import register_all_detectors

    register_all_detectors()
    context = {"journals_dir": get_journals_dir(), "data_dir": get_user_data_dir()}
    events = detect_events(context=context)
    payload["events"] = [e.to_dict() for e in events]


def _emit_json(payload: dict, *, include_events: bool = True) -> None:
    """Print JSON safely across Windows console encodings."""
    if include_events:
        _attach_events(payload)

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        print(text)
    except UnicodeEncodeError:
        fallback_text = json.dumps(payload, ensure_ascii=True, indent=2)
        print(fallback_text)


def run_search(
    *,
    query: str | None = None,
    topic: str | None = None,
    year: int | None = None,
    month: int | None = None,
    project: str | None = None,
    tags: tuple[str, ...] | list[str] | None = None,
    mood: tuple[str, ...] | list[str] | None = None,
    people: tuple[str, ...] | list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    weather: str | None = None,
    level: int = 3,
    use_index: bool = True,
    semantic: bool = False,
    semantic_weight: float = 1.0,
    fts_weight: float = 1.0,
    explain: bool = False,
    semantic_policy: Literal["fallback", "hybrid"] = "fallback",
    enable_source_tier: bool = False,
    limit: int = 20,
    offset: int = 0,
    include_events: bool = True,
    source_safe: bool = False,
) -> dict:
    """Run the canonical search application function without CLI parsing.

    Direct CLI and transport-neutral callers share this function so the search
    domain envelope, retrieval, presentation, trace, provenance, and tool-call
    logging stay owned by the existing Core implementation.  The closed Host
    Agent channel uses ``source_safe`` to preserve its explicit ``.index``-only
    derived-state authority without changing direct CLI defaults.
    """
    started = time.perf_counter()
    if not source_safe:
        ensure_dirs()
    normalized_tags = list(tags) if tags else None
    normalized_mood = list(mood) if mood else None
    normalized_people = list(people) if people else None

    with Trace("search") as trace:
        with trace.step("hierarchical_search"):
            result = hierarchical_search(
                query=query,
                topic=topic,
                project=project,
                tags=normalized_tags,
                mood=normalized_mood,
                people=normalized_people,
                date_from=date_from,
                date_to=date_to,
                location=location,
                weather=weather,
                year=year,
                month=month,
                level=level,
                use_index=use_index,
                semantic=semantic,
                semantic_weight=semantic_weight,
                fts_weight=fts_weight,
                explain=explain,
                semantic_policy=semantic_policy,
                enable_source_tier=enable_source_tier,
                emit_metrics=not source_safe,
                use_metadata_cache=not source_safe,
                derived_index_only=source_safe,
            )

    _apply_presentation_layer(result, limit=limit, offset=offset)
    result["_trace"] = trace.to_dict()
    provenance_envelope = build_provenance_envelope(
        source_data=result,
        generator="search",
        params={"query": query, "topic": topic, "level": level},
    )
    result["schema_version"] = provenance_envelope["schema_version"]
    result["provenance"] = provenance_envelope["provenance"]
    # The source-safe typed channel is traced once at its registry/dispatcher
    # boundary, where parameters and result content are deliberately omitted.
    # Direct CLI execution keeps its existing opt-in diagnostic record.
    if not source_safe:
        emit_tool_call_log(
            "search",
            params={
                "query": query,
                "topic": topic,
                "project": project,
                "tags": normalized_tags,
                "mood": normalized_mood,
                "people": normalized_people,
                "date_from": date_from,
                "date_to": date_to,
                "location": location,
                "weather": weather,
                "year": year,
                "month": month,
                "level": level,
                "semantic": semantic,
                "limit": limit,
                "offset": offset,
            },
            result={
                "total_matches": result.get("total_matches"),
                "total_found": result.get("total_found"),
                "total_available": result.get("total_available"),
                "has_more": result.get("has_more"),
            },
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            success=bool(result.get("success")),
        )
    if include_events:
        _attach_events(result)
    return result


def main() -> None:
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Life Index - Search Journals Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m tools.search_journals --query "重构"
    python -m tools.search_journals --query "重构" --level 3
    python -m tools.search_journals --topic work --project Life-Index
    python -m tools.search_journals --date-from 2026-01-01 --date-to 2026-03-04
    python -m tools.search_journals --query "学习笔记" --semantic  # deprecated no-op
        """,
    )

    parser.add_argument("--query", help="搜索关键词")
    parser.add_argument("--topic", help="按主题过滤 (如 work, learn, life)")
    parser.add_argument("--year", type=int, help="L0 prefilter: restrict to year")
    parser.add_argument(
        "--month", type=int, help="L0 prefilter: restrict to month (requires --year)"
    )
    parser.add_argument("--project", help="按项目过滤")
    parser.add_argument("--tags", help="按标签过滤（逗号分隔多个）")
    parser.add_argument("--mood", help="按心情过滤（逗号分隔多个）")
    parser.add_argument("--people", help="按人物过滤（逗号分隔多个）")
    parser.add_argument("--date-from", dest="date_from", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--date-to", dest="date_to", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--location", help="按地点过滤")
    parser.add_argument("--weather", help="按天气过滤")
    parser.add_argument(
        "--level",
        type=int,
        choices=[1, 2, 3],
        default=3,
        help="搜索层级：1=索引, 2=元数据, 3=全文检索 (默认: 3)",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="禁用 FTS 索引（回退到文件扫描，默认启用 FTS）",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help="废弃兼容参数：接受但忽略，行为等同关键词/实体检索",
    )
    parser.add_argument(
        "--no-semantic",
        action="store_true",
        help="废弃兼容参数：接受但忽略，行为等同关键词/实体检索",
    )
    parser.add_argument(
        "--semantic-policy",
        choices=["fallback", "hybrid"],
        default="fallback",
        help="废弃兼容参数：接受 fallback/hybrid 但忽略",
    )
    parser.add_argument(
        "--semantic-weight",
        type=float,
        default=1.0,
        help="废弃兼容参数：接受但忽略",
    )
    parser.add_argument(
        "--fts-weight",
        type=float,
        default=1.0,
        help="废弃兼容参数：接受但忽略",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="返回结果数量限制 (默认: 20; 0 = 全部)",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="结果偏移量（分页起始位置，默认: 0）",
    )
    parser.add_argument(
        "--read-top",
        type=int,
        default=0,
        help="读取前 N 条结果的完整正文（Task 1.2.3，默认: 0 不读取）",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="输出搜索评分详情（Task 2.1）",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="输出最近搜索行为诊断摘要并退出",
    )
    parser.add_argument(
        "--diagnose-days",
        type=int,
        default=7,
        help="诊断回看天数（默认: 7）",
    )
    parser.add_argument(
        "--enable-source-tier",
        action="store_true",
        help="启用 source-tier 排名加权（gbrain Phase B，默认关闭）",
    )

    args = parser.parse_args()

    if args.diagnose:
        ensure_dirs()
        diagnose_search = import_module("tools.lib.search_diagnose").diagnose_search
        _emit_json(diagnose_search(days=args.diagnose_days), include_events=False)
        sys.exit(0)

    # 解析列表参数（支持全角逗号）
    tags = (
        [t.strip() for t in args.tags.replace("，", ",").split(",") if t.strip()]
        if args.tags
        else None
    )
    mood = (
        [m.strip() for m in args.mood.replace("，", ",").split(",") if m.strip()]
        if args.mood
        else None
    )
    people = (
        [p.strip() for p in args.people.replace("，", ",").split(",") if p.strip()]
        if args.people
        else None
    )

    result = run_search(
        query=args.query,
        topic=args.topic,
        project=args.project,
        tags=tags,
        mood=mood,
        people=people,
        date_from=args.date_from,
        date_to=args.date_to,
        location=args.location,
        weather=args.weather,
        year=args.year,
        month=args.month,
        level=args.level,
        use_index=not args.no_index,
        semantic=args.semantic and not args.no_semantic,
        semantic_weight=args.semantic_weight,
        fts_weight=args.fts_weight,
        explain=args.explain,
        semantic_policy=args.semantic_policy,
        enable_source_tier=args.enable_source_tier,
        limit=args.limit,
        offset=args.offset or 0,
    )

    # Task 1.2.3: Read full content for top N results
    if args.read_top > 0 and result.get("success") and result.get("merged_results"):
        from pathlib import Path
        from ..lib.paths import get_journals_dir

        _journals_dir = get_journals_dir()

        top_n = min(args.read_top, len(result["merged_results"]))
        for i in range(top_n):
            item = result["merged_results"][i]
            path = item.get("path", "")

            if path:
                # Construct full path
                if path.startswith("Journals/"):
                    full_path = _journals_dir.parent / path
                else:
                    full_path = Path(path)

                # Read full content
                try:
                    if full_path.exists():
                        content = full_path.read_text(encoding="utf-8")
                        # Extract body (after frontmatter)
                        if content.startswith("---"):
                            parts = content.split("---", 2)
                            if len(parts) >= 3:
                                item["full_content"] = parts[2].strip()
                            else:
                                item["full_content"] = content
                        else:
                            item["full_content"] = content
                    else:
                        item["full_content"] = None
                except Exception as e:
                    item["full_content"] = None
                    item["read_error"] = str(e)

    _emit_json(result, include_events=False)

    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
