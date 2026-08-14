#!/usr/bin/env python3
"""
Life Index - Keyword Search Pipeline
关键词搜索管道: L1 → L2 → L3

从 core.py 提取的 pipeline_keyword() 函数。
"""

import logging
import math
import re
import time
from pathlib import Path
from typing import Any

from ..lib import chinese_tokenizer
from ..lib.paths import get_user_data_dir, get_journals_dir
from ..lib.path_contract import merge_journal_path_fields
from ..lib.search_constants import (
    FTS_FALLBACK_THRESHOLD,
    FTS_MAX_RETRIEVAL_BOUND,
    FTS_MIN_RELEVANCE,
    KEYWORD_TOKEN_HIT_RATIO,
)

# Deprecated aliases — kept for monkeypatch compatibility (Round 13 lesson)
USER_DATA_DIR = get_user_data_dir()
JOURNALS_DIR = get_journals_dir()

from .l1_index import search_l1_index
from .l2_metadata import search_l2_metadata
from .l3_content import search_l3_content

# 导入 logger
try:
    from ..lib.logger import get_logger

    logger = get_logger("search_journals")
except ImportError:
    logger = logging.getLogger("search_journals")


KeywordPipelineResult = tuple[
    list[dict[str, Any]],  # l1_results
    list[dict[str, Any]],  # l2_results
    list[dict[str, Any]],  # l3_results
    bool,  # l2_truncated
    int,  # l2_total_available
    dict[str, float],  # perf
]

_FTS_LITERAL_QUOTE_TOKENS = {
    "content",
    "date",
    "file_hash",
    "index",
    "location",
    "modified_time",
    "mood",
    "path",
    "people",
    "project",
    "tags",
    "title",
    "title_segmented",
    "topic",
    "weather",
}


def _has_explicit_fts_operator(query: str) -> bool:
    """Return whether query already contains explicit FTS boolean operators.

    Only UPPER-CASE AND/OR/NOT are treated as FTS operators.  Natural-language
    usage like "how and why" should NOT be intercepted (B-2).
    """
    return bool(re.search(r"\b(AND|OR|NOT)\b", query))


def _quote_fts_token(token: str) -> str:
    """Quote a bare token if it contains characters that FTS5 treats as operators.

    FTS5 interprets punctuation and some bare words as query syntax. A query
    like ``2026-01-28`` becomes ``2026 NOT 01 NOT 28``, producing
    ``no such column: 01``; ``2.0`` similarly errors near ``.``. Wrapping the
    token in double quotes forces FTS5 to treat it as a literal phrase.
    """
    if not token or token.startswith('"'):
        return token
    if "-" in token or "." in token or token.lower() in _FTS_LITERAL_QUOTE_TOKENS:
        return f'"{token}"'
    return token


def _quote_fts_boolean_group_literals(group: str) -> str:
    """Quote unsafe literal tokens inside a simple parenthesized FTS group."""
    if not (group.startswith("(") and group.endswith(")")):
        return group
    inner = group[1:-1].strip()
    if not inner:
        return group
    operators = {"AND", "OR", "NOT"}
    tokens = [
        token if token in operators else _quote_fts_token(token) for token in inner.split() if token
    ]
    return f"({' '.join(tokens)})"


def _split_entity_expanded_query(query: str) -> list[str]:
    """Split an entity-expanded query into operator and non-operator fragments.

    Preserves FTS operators (AND, OR, NOT) and parenthesized groups as-is.
    Returns non-operator Chinese text fragments for segmentation.

    Example:
        "在 AND (重庆 OR Chongqing OR 山城) AND 发生过的事"
        → ["在", "AND", "(重庆 OR Chongqing OR 山城)", "AND", "发生过的事"]
    """
    # Pattern matches: parenthesized groups, operators, or remaining tokens
    token_re = re.compile(r"\([^)]+\)|\b(AND|OR|NOT)\b|[一-鿿]+|[^\s()]+")
    return [m.group(0) for m in token_re.finditer(query)]


def _segment_entity_expanded_query(query: str) -> tuple[str, bool]:
    """Segment an entity-expanded query: segment non-operator Chinese fragments.

    Splits the query into structural fragments (operators, parenthesized OR
    groups) and non-operator Chinese text, segments only the Chinese fragments
    with jieba, then reassembles with original operator structure preserved.

    Returns:
        (reassembled_query, was_segmented) — was_segmented is always False
        because the query contains explicit AND/OR operators and must pass
        through _build_fts_queries() via the operator-passthrough path,
        not the OR-join path that would destroy boolean structure.
    """
    fragments = _split_entity_expanded_query(query)
    segment_for_fts = getattr(chinese_tokenizer, "segment_for_fts")

    operators = {"AND", "OR", "NOT"}
    processed: list[str] = []
    for frag in fragments:
        # Skip FTS operators and parenthesized OR groups — preserve as-is
        if frag in operators:
            processed.append(frag)
            continue
        if frag.startswith("("):
            processed.append(_quote_fts_boolean_group_literals(frag))
            continue

        # Check if this fragment has CJK content needing segmentation
        has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF or 0x3400 <= ord(c) <= 0x4DBF for c in frag)
        if has_cjk:
            segmented = segment_for_fts(frag, mode="query").strip()
            if segmented:
                processed.append(segmented)
        else:
            # Quote non-CJK tokens that contain hyphens (e.g., 2026-01-15)
            processed.append(_quote_fts_token(frag))

    cleaned: list[str] = []
    for frag in processed:
        if not frag.strip():
            continue
        if frag in operators:
            # Stopword removal may delete a neighboring text fragment; do not
            # leave FTS operator syntax at expression boundaries or doubled up.
            if not cleaned or cleaned[-1] in operators:
                continue
        cleaned.append(frag)
    while cleaned and cleaned[-1] in operators:
        cleaned.pop()

    return " ".join(cleaned), False


def _segment_query_for_fts(query: str, *, entity_expanded: bool = False) -> tuple[str, bool]:
    """Segment Chinese text in a query for FTS5 matching.

    Handles: pure Chinese, pure English, mixed, FTS operators, and quoted phrases.
    - Quoted phrases are preserved (not segmented)
    - FTS operators (AND/OR/NOT) are preserved
    - Unquoted Chinese text is segmented in query mode (with stopword filtering)

    R2-A3: When entity_expanded=True, the query comes from entity graph expansion
    and contains system-injected AND/OR operators. Instead of bypassing segmentation
    entirely, segment only the non-operator Chinese fragments while preserving the
    boolean structure.

    Returns:
        Tuple of (segmented_query, was_segmented).  When was_segmented is True,
        _build_fts_queries should use OR-based matching for better recall on
        Chinese natural-language tokens.
    """
    if not query or not query.strip():
        return query, False

    # R2-A3: Entity-expanded queries need targeted segmentation, not bypass
    if entity_expanded and _has_explicit_fts_operator(query):
        return _segment_entity_expanded_query(query)

    # If query already has FTS operators or is all ASCII, pass through
    # (entity expansion may have added operators like "晴岚 OR 小风筝")
    if _has_explicit_fts_operator(query):
        return query, False

    # Check if there's any CJK content to segment
    has_cjk = any(0x4E00 <= ord(c) <= 0x9FFF or 0x3400 <= ord(c) <= 0x4DBF for c in query)
    if not has_cjk:
        return query, False

    # Extract and preserve quoted phrases
    quoted_parts: list[str] = []
    cleaned_query = query
    quote_pattern = re.compile(r'"([^"]*)"')
    for i, match in enumerate(quote_pattern.finditer(query)):
        placeholder = f"__QUOTED_{i}__"
        quoted_parts.append(match.group(0))
        cleaned_query = cleaned_query.replace(match.group(0), placeholder, 1)

    # Segment the non-quoted part
    segment_for_fts = getattr(chinese_tokenizer, "segment_for_fts")
    segmented = segment_for_fts(cleaned_query, mode="query")

    # Restore quoted phrases
    for i, quoted in enumerate(quoted_parts):
        segmented = segmented.replace(f"__QUOTED_{i}__", quoted)

    result = segmented if segmented.strip() else query

    # B-3: Use structured return instead of in-band sentinel
    was_segmented = result != query and " " in result
    return result, was_segmented


def _build_fts_queries(query: str, *, was_segmented: bool = False) -> tuple[str, str | None]:
    """Build primary/fallback FTS queries for keyword pipeline.

    Multi-word queries default to AND-first with OR fallback, unless the user
    already supplied explicit boolean operators or quotes.

    B-3: Uses was_segmented flag instead of in-band __SEGMENTED__ sentinel.
    For segmented Chinese queries, we use OR matching for better recall —
    Chinese natural language queries are conceptually cohesive, and strict AND
    matching between jieba tokens produces zero results.

    T3.3: English stopwords are filtered from non-segmented queries to prevent
    noise tokens like 'my', 'the', 'is' from polluting FTS matches.
    """
    # Handle segmented Chinese queries — use OR for better recall
    if was_segmented:
        keywords = [kw.strip() for kw in query.split() if kw.strip()]
        if len(keywords) <= 1:
            if keywords:
                return _quote_fts_token(keywords[0]), None
            return query, None
        keywords = [_quote_fts_token(kw) for kw in keywords]
        return " OR ".join(keywords), None

    if '"' in query or _has_explicit_fts_operator(query) or " " not in query:
        if " " not in query and not _has_explicit_fts_operator(query) and '"' not in query:
            return _quote_fts_token(query), None
        return query, None

    keywords = [keyword.strip() for keyword in query.split() if keyword.strip()]
    if len(keywords) <= 1:
        if keywords:
            return _quote_fts_token(keywords[0]), None
        return query, None

    # T3.3: Filter English stopwords from keyword list
    from .stopwords import load_stopwords as _load_sw

    en_sw = _load_sw("en")
    if en_sw:
        keywords = [kw for kw in keywords if kw.lower() not in en_sw]
    if len(keywords) <= 1:
        if keywords:
            return _quote_fts_token(keywords[0]), None
        return query, None

    keywords = [_quote_fts_token(kw) for kw in keywords]
    return " AND ".join(keywords), " OR ".join(keywords)


def _merge_fts_results(
    primary_results: list[dict[str, Any]], fallback_results: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Merge fallback FTS results while preserving primary-query priority."""
    merged = list(primary_results)
    seen_paths = {str(item.get("path", "")) for item in primary_results}

    for item in fallback_results:
        path = str(item.get("path", ""))
        if path and path not in seen_paths:
            merged.append(item)
            seen_paths.add(path)

    return merged


def _count_distinct_token_hits(text: str, tokens: list[str]) -> int:
    """Count how many distinct tokens appear in the text (case-insensitive)."""
    text_lower = text.lower()
    count = 0
    for token in set(tokens):
        if token.lower() in text_lower:
            count += 1
    return count


def _l3_item_identity(item: dict[str, Any]) -> str:
    """Stable identity of an L3 candidate for cross-stage dedup accounting."""
    return str(item.get("journal_route_path") or item.get("path") or "")


def _compute_min_required_hits(query_tokens: list[str]) -> tuple[int, list[str]]:
    """Compute required distinct token hits based on D8 rule.

    Rule: max(2, ceil(non_stopword_tokens × KEYWORD_TOKEN_HIT_RATIO))
    Single non-stopword token queries: return (0, []) meaning skip filter.

    Returns:
        (required_hits, non_stopword_tokens)
        required_hits=0 means skip the filter (too few content tokens)
    """
    from .stopwords import filter_stopwords

    non_stop = filter_stopwords(query_tokens)
    if len(non_stop) < 2:
        return 0, non_stop
    required = max(2, math.ceil(len(non_stop) * KEYWORD_TOKEN_HIT_RATIO))
    return required, non_stop


def run_keyword_pipeline(
    *,
    query: str | None = None,
    topic: str | None = None,
    project: str | None = None,
    tags: list[str] | None = None,
    mood: list[str] | None = None,
    people: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    location: str | None = None,
    weather: str | None = None,
    use_index: bool = True,
    fts_min_relevance: int = FTS_MIN_RELEVANCE,
    candidate_paths: set[str] | None = None,
    entity_expanded: bool = False,
    use_metadata_cache: bool = True,
) -> KeywordPipelineResult:
    """
    关键词搜索管道: L1 索引 → L2 元数据 → L3 FTS5 内容

    Args:
        query: 搜索关键词
        topic: 按主题过滤
        project: 按项目过滤
        tags: 按标签过滤
        mood: 按心情过滤
        people: 按人物过滤
        date_from: 起始日期
        date_to: 结束日期
        location: 按地点过滤
        weather: 按天气过滤
        use_index: 是否使用 FTS 索引加速
        fts_min_relevance: FTS 最低相关性阈值

    Returns:
        (l1_results, l2_results, l3_results, l2_truncated, l2_total_available, perf)
    """
    perf: dict[str, float] = {}
    normalize_query = getattr(chinese_tokenizer, "normalize_query")
    normalized_query = normalize_query(query) if query is not None else None
    has_effective_query = bool(normalized_query)
    has_other_filters = any(
        value
        for value in (
            topic,
            project,
            tags,
            mood,
            people,
            date_from,
            date_to,
            location,
            weather,
        )
    )

    if not has_effective_query and not has_other_filters:
        perf["l1_time_ms"] = 0.0
        perf["l2_time_ms"] = 0.0
        perf["l3_time_ms"] = 0.0
        logger.info("[SearchPerf] L1 index: 0 results, 0.0ms")
        logger.info("[SearchPerf] L2 metadata: 0 results, 0.0ms")
        logger.info("[SearchPerf] L3 content: 0 results, 0.0ms")
        return ([], [], [], False, 0, perf)

    def _normalize_path(path_value: str) -> str:
        return str(Path(path_value).resolve()).replace("\\", "/")

    def _filter_candidate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if candidate_paths is None:
            return items
        filtered: list[dict[str, Any]] = []
        for item in items:
            path_value = item.get("path") or item.get("journal_route_path") or item.get("rel_path")
            if path_value and _normalize_path(str(path_value)) in candidate_paths:
                filtered.append(item)
        return filtered

    # L1: 索引过滤
    l1_start = time.time()
    l1_results: list[dict] = []
    if topic:
        l1_results.extend(search_l1_index("topic", topic))
    if project:
        l1_results.extend(search_l1_index("project", project))
    if tags:
        for tag in tags:
            l1_results.extend(search_l1_index("tag", tag))
    # 去重
    seen: set = set()
    l1_results = [
        r
        for r in l1_results
        if r["path"] not in seen and not seen.add(r["path"])  # type: ignore[func-returns-value]
    ]
    l1_results = _filter_candidate_items(l1_results)
    perf["l1_time_ms"] = round((time.time() - l1_start) * 1000, 2)
    logger.info(f"[SearchPerf] L1 index: {len(l1_results)} results, {perf['l1_time_ms']}ms")

    # L2: 元数据过滤
    l2_start = time.time()
    l2_kwargs: dict[str, Any] = {
        "date_from": date_from,
        "date_to": date_to,
        "location": location,
        "weather": weather,
        "topic": topic,
        "project": project,
        "tags": tags,
        "mood": mood,
        "people": people,
        "query": normalized_query if has_effective_query else None,
    }
    if not use_metadata_cache:
        l2_kwargs["use_cache"] = False
    l2_response = search_l2_metadata(
        **l2_kwargs,
    )
    l2_results = l2_response["results"]
    l2_results = _filter_candidate_items(l2_results)
    # The source-cap facts describe the UPSTREAM L2 source, not the post-filter
    # window: overwriting total_available with the candidate-filtered count
    # would erase a real retrieval cap from the coverage signal.
    l2_truncated = l2_response.get("truncated", False)
    l2_total_available = l2_response.get("total_available", 0)
    perf["l2_time_ms"] = round((time.time() - l2_start) * 1000, 2)
    logger.info(f"[SearchPerf] L2 metadata: {len(l2_results)} results, {perf['l2_time_ms']}ms")

    # L3: FTS5 内容搜索
    l3_start = time.time()
    l3_results: list[dict] = []
    # Phase 1 corrective: candidates dropped by the FTS min-hits post-filter,
    # tracked so the coverage layer can report the ones no fallback recovered.
    min_hits_excluded: list[dict[str, Any]] = []
    min_hits_required = 0

    if has_effective_query and normalized_query:
        # Segment Chinese text in query before FTS matching (T1.3)
        segmented_query, was_segmented = _segment_query_for_fts(
            normalized_query, entity_expanded=entity_expanded
        )
        fts_query, fallback_fts_query = _build_fts_queries(
            segmented_query, was_segmented=was_segmented
        )

        # 尝试使用 FTS 索引（如果可用且启用）
        if use_index:
            try:
                from ..lib.search_index import search_fts

                # Phase 1 (CHARTER §1.11): retrieve the FULL admitted candidate
                # set (limit=0 → no SQL cap) with min_relevance=0 so the FTS
                # layer does not drop low-relevance token-matches via a dynamic
                # threshold. The explicit ``fts_min_relevance`` threshold is
                # applied (and counted) AFTER retrieval, below, making this
                # pipeline the single threshold authority.
                fts_results = search_fts(
                    fts_query,
                    date_from,
                    date_to,
                    limit=0,
                    min_relevance=0,
                )

                if fallback_fts_query and len(fts_results) < 3:
                    fallback_results = search_fts(
                        fallback_fts_query,
                        date_from,
                        date_to,
                        limit=0,
                        min_relevance=0,
                    )
                    fts_results = _merge_fts_results(fts_results, fallback_results)

                if fts_results:
                    l3_results = [
                        {
                            "date": r["date"],
                            "title": r["title"],
                            "snippet": r.get("snippet", ""),
                            "match_count": 1,
                            "source": "fts_index",
                            "relevance": r.get("relevance", 50),
                            # 元数据字段
                            "location": r.get("location", ""),
                            "weather": r.get("weather", ""),
                            "topic": r.get("topic", []),
                            "project": r.get("project", ""),
                            "tags": r.get("tags", []),
                            "mood": r.get("mood", []),
                            "people": r.get("people", []),
                            **merge_journal_path_fields(
                                {},
                                get_user_data_dir() / r["path"],
                                journals_dir=get_journals_dir(),
                                user_data_dir=get_user_data_dir(),
                            ),
                        }
                        for r in fts_results
                    ]

                    # T3.1 (D8): FTS min-hits post-filter for segmented queries.
                    # Require results to hit ≥ max(2, ceil(non_stopword_tokens ×
                    # KEYWORD_TOKEN_HIT_RATIO)) distinct non-stopword tokens.
                    # Single-token queries skip this filter.
                    # Also skip when date range filters are active — L2 metadata
                    # already constrains results to the target period.
                    if was_segmented and l3_results and not date_from and not date_to:
                        query_tokens = segmented_query.split()
                        required_hits, non_stop_tokens = _compute_min_required_hits(query_tokens)
                        if required_hits > 0 and non_stop_tokens:
                            before_count = len(l3_results)
                            filtered = []
                            for item in l3_results:
                                searchable = " ".join(
                                    [
                                        str(item.get("title", "")),
                                        str(item.get("snippet", "")),
                                    ]
                                ).lower()
                                hits = _count_distinct_token_hits(searchable, non_stop_tokens)
                                if hits >= required_hits:
                                    filtered.append(item)
                                else:
                                    min_hits_excluded.append(item)
                                    logger.debug(
                                        "FTS min-hits filter: removed '%s' " "(hit %d/%d tokens)",
                                        item.get("title", ""),
                                        hits,
                                        required_hits,
                                    )
                            l3_results = filtered
                            if before_count != len(l3_results):
                                min_hits_required = required_hits
                                logger.info(
                                    "FTS min-hits filter: %d → %d results " "(required ≥%d of %s)",
                                    before_count,
                                    len(l3_results),
                                    required_hits,
                                    non_stop_tokens,
                                )

                    # When FTS recall is suspiciously low, supplement with full-corpus
                    # content scan so body-only matches are not missed due to stale or
                    # incomplete index coverage.
                    if normalized_query and len(l3_results) < FTS_FALLBACK_THRESHOLD:
                        from ..lib.fs_consistency import (
                            get_last_sync_ts,
                            has_writes_since,
                        )
                        from ..lib.paths import get_fts_db_path

                        _journals_dir = get_journals_dir()
                        last_sync = get_last_sync_ts(get_fts_db_path())
                        should_fallback = last_sync is None or has_writes_since(
                            last_sync, _journals_dir
                        )

                        if should_fallback:
                            fallback_l3_results = search_l3_content(
                                normalized_query,
                                sorted(candidate_paths) if candidate_paths is not None else None,
                            )
                            seen_paths = {
                                str(item.get("journal_route_path") or item.get("path") or "")
                                for item in l3_results
                            }
                            for item in fallback_l3_results:
                                key = str(item.get("journal_route_path") or item.get("path") or "")
                                if key and key not in seen_paths:
                                    l3_results.append(item)
                                    seen_paths.add(key)
                            logger.debug(
                                "L3 fallback triggered (index stale: %s)",
                                (
                                    "missing_last_updated"
                                    if last_sync is None
                                    else "files_newer_than_last_sync"
                                ),
                            )
                        else:
                            logger.debug(
                                "L3 fallback skipped (index fresh, %d FTS results authoritative)",
                                len(l3_results),
                            )
                    logger.debug(f"FTS found {len(l3_results)} results")
            except (ImportError, OSError) as e:
                logger.debug(f"FTS error: {e}")

        l3_results = _filter_candidate_items(l3_results)

        # 如果没有 FTS 结果，使用传统文件系统扫描
        if not l3_results:
            # IMPORTANT: when FTS is unavailable, fallback must search full corpus.
            # Restricting to L2-filtered candidates causes body-only keyword matches
            # (e.g. names appearing only in content) to be lost before L3 sees them.
            l3_results = search_l3_content(
                normalized_query,
                sorted(candidate_paths) if candidate_paths is not None else None,
            )
            logger.debug(f"File scan found {len(l3_results)} results")

        # Phase 1 corrective: account for min-hits exclusions AFTER every recovery
        # path (stale-index supplement, full-corpus fallback) has run. Only the
        # candidates still absent from the final set are a coverage gap; a
        # fallback-recovered exclusion must not be double-reported. Filtering the
        # accounting set through the same L0 prefilter keeps items the caller's
        # candidate scope never admitted from being miscounted as min-hits gaps.
        if min_hits_excluded:
            recoverable = _filter_candidate_items(min_hits_excluded)
            final_identities = {_l3_item_identity(item) for item in l3_results}
            still_excluded = [
                item for item in recoverable if _l3_item_identity(item) not in final_identities
            ]
            if still_excluded:
                perf["fts_min_hits_excluded"] = float(len(still_excluded))
                perf["fts_min_hits_required"] = float(min_hits_required)

    # Phase 1: high-cardinality fail-closed backstop. With full materialization
    # FTS_LIMIT no longer caps retrieval; a pathologically large observed set
    # must fail CLOSED rather than return a truncated subset that could be
    # mistaken for the complete set. Rather than a bare RuntimeError, this raises
    # a structured LifeIndexError (E0301 + details.reason=retrieval_resource_bound)
    # which the search entry point converts into the standard machine-readable
    # error envelope. See ADR-014 / FTS_MAX_RETRIEVAL_BOUND.
    if len(l3_results) > FTS_MAX_RETRIEVAL_BOUND:
        from ..lib.errors import ErrorCode, LifeIndexError

        raise LifeIndexError(
            ErrorCode.SEARCH_FAILED,
            "Retrieval refused: observed candidate set exceeded the safety bound.",
            details={
                "reason": "retrieval_resource_bound",
                "observed": len(l3_results),
                "bound": int(FTS_MAX_RETRIEVAL_BOUND),
            },
        )

    # Phase 1: explicit threshold authority. Apply ``fts_min_relevance`` AFTER
    # retrieval and COUNT the otherwise-matching candidates it drops, so the
    # coverage layer can mark the retrieval partial only when an exclusion
    # actually happened. A threshold of 0 (default token-match threshold) admits
    # everything and records no exclusion.
    if fts_min_relevance and fts_min_relevance > 0:
        kept: list[dict[str, Any]] = []
        excluded = 0
        for item in l3_results:
            if int(item.get("relevance", 0) or 0) >= fts_min_relevance:
                kept.append(item)
            else:
                excluded += 1
        if excluded:
            l3_results = kept
            perf["fts_threshold_excluded"] = float(excluded)
            perf["fts_threshold"] = float(fts_min_relevance)
            logger.debug(
                "FTS explicit threshold %d excluded %d of %d L3 candidates",
                fts_min_relevance,
                excluded,
                excluded + len(kept),
            )

    perf["l3_time_ms"] = round((time.time() - l3_start) * 1000, 2)
    logger.info(f"[SearchPerf] L3 content: {len(l3_results)} results, {perf['l3_time_ms']}ms")

    return (
        l1_results,
        l2_results,
        l3_results,
        l2_truncated,
        l2_total_available,
        perf,
    )
