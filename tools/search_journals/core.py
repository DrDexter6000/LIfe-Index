#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - Core
核心协调模块

分层搜索架构（keyword/entity only；--semantic* 为兼容 no-op）:
  Pipeline A (关键词): L1 索引过滤 → L2 元数据过滤 → L3 FTS5 内容匹配
"""

import logging
import os
import re
import time
from datetime import date
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from ..lib.entity_graph import load_entity_graph
from ..lib.entity_runtime import (
    EntityRuntimeView,
    _expand_related_entities,
    build_runtime_view,
    _iter_entity_term_spans,
    resolve_via_runtime,
)
from ..lib.entity_relations import normalize_relation, relation_aliases
from ..lib.entity_schema import EntityGraphValidationError
from ..lib.errors import LifeIndexError
from ..lib.search_constants import (
    SEMANTIC_TOP_K_DEFAULT,
    SEMANTIC_MIN_SIMILARITY,
    RRF_MIN_SCORE,
    NON_RRF_MIN_SCORE,
    SEMANTIC_WEIGHT_DEFAULT,
    FTS_WEIGHT_DEFAULT,
    STRUCTURED_RETRIEVAL_ENABLED,
)

# 导入子模块
from .l1_index import scan_all_indices, search_l1_index
from .l2_metadata import search_l2_metadata
from .ranking import merge_and_rank_results
from .keyword_pipeline import run_keyword_pipeline

# 导入 logger
try:
    from ..lib.logger import get_logger

    logger = get_logger("search_journals")
except ImportError:
    logger = logging.getLogger("search_journals")


SEARCH_PLAN_SCHEMA_VERSION = "v1.1.1"
SEMANTIC_DEPRECATED_NOOP_WARNING = (
    "deprecated_noop: --semantic* flags are accepted for compatibility but ignored; "
    "search now uses keyword + Entity Graph only."
)

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _emit_search_metrics(result: Dict[str, Any]) -> None:
    metrics_module = import_module("tools.lib.search_metrics")
    metrics_module.emit_search_metrics(result)


def _compute_no_confident_match(results: list[dict[str, Any]]) -> bool:
    confidence_module = import_module("tools.search_journals.confidence")
    result: bool = confidence_module.compute_no_confident_match(results)
    return result


def _normalize_candidate_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _extract_candidate_path(link_target: str) -> Path | None:
    cleaned = link_target.strip()
    if not cleaned or cleaned.startswith(("http://", "https://", "#")):
        return None

    candidate = Path(cleaned)
    if not candidate.is_absolute():
        from ..lib.paths import get_user_data_dir

        candidate = get_user_data_dir() / cleaned

    return candidate.resolve()


def _topic_index_path(topic: str) -> Path:
    from ..lib.paths import get_user_data_dir

    return get_user_data_dir() / "by-topic" / f"主题_{topic}.md"


def _parse_journal_date(filename: str) -> str | None:
    """Extract the date portion (YYYY-MM-DD) from a journal filename.

    Filenames follow the pattern: life-index_YYYY-MM-DD_NNN.md
    Returns None if the filename doesn't match the expected pattern.
    """
    import re as _re

    m = _re.match(r"life-index_(\d{4}-\d{2}-\d{2})_\d+\.md", filename)
    return m.group(1) if m else None


def build_l0_candidate_set(
    *,
    year: int | None = None,
    month: int | None = None,
    topic: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> set[str] | None:
    from ..lib.paths import get_journals_dir

    _journals_dir = get_journals_dir()

    candidate_sets: list[set[str]] = []

    if year is not None:
        if month is not None:
            journal_paths = (_journals_dir / str(year) / f"{month:02d}").glob("life-index_*.md")
        else:
            journal_paths = (_journals_dir / str(year)).glob("**/life-index_*.md")
        candidate_sets.append({_normalize_candidate_path(path) for path in journal_paths})

    if topic:
        topic_index = _topic_index_path(topic)
        if topic_index.exists():
            topic_paths: set[str] = set()
            for link_target in _MARKDOWN_LINK_RE.findall(topic_index.read_text(encoding="utf-8")):
                candidate_path = _extract_candidate_path(link_target)
                if candidate_path and candidate_path.name.startswith("life-index_"):
                    topic_paths.add(_normalize_candidate_path(candidate_path))
            candidate_sets.append(topic_paths)

    # Phase 4 T4.1: date_from/date_to filtering via filename date extraction
    if date_from is not None or date_to is not None:
        date_filtered: set[str] = set()
        for journal_path in _journals_dir.glob("**/life-index_*.md"):
            journal_date = _parse_journal_date(journal_path.name)
            if journal_date is None:
                continue
            if date_from is not None and journal_date < date_from:
                continue
            if date_to is not None and journal_date > date_to:
                continue
            date_filtered.add(_normalize_candidate_path(journal_path))
        candidate_sets.append(date_filtered)

    if not candidate_sets:
        return None

    intersection = set(candidate_sets[0])
    for candidate_set in candidate_sets[1:]:
        intersection &= candidate_set
    return intersection


def _filter_results_by_candidates(
    results: list[dict[str, Any]], candidate_paths: set[str] | None
) -> list[dict[str, Any]]:
    if candidate_paths is None:
        return results

    filtered_results: list[dict[str, Any]] = []
    for item in results:
        path_value = item.get("path") or item.get("journal_route_path") or item.get("rel_path")
        if not path_value:
            continue
        normalized = _normalize_candidate_path(Path(str(path_value)))
        if normalized in candidate_paths:
            filtered_results.append(item)
    return filtered_results


def _merge_multi_word_entity_tokens(
    raw_tokens: list[str],
    view: EntityRuntimeView,
    max_window: int = 4,
) -> list[str]:
    tokens: list[str] = []
    skip: set[int] = set()
    for i in range(len(raw_tokens)):
        if i in skip:
            continue
        merged = False
        for window_len in range(min(len(raw_tokens) - i, max_window), 1, -1):
            if i + window_len > len(raw_tokens):
                continue
            candidate = " ".join(raw_tokens[i : i + window_len])
            if resolve_via_runtime(candidate, view) is not None:
                tokens.append(candidate)
                for k in range(1, window_len):
                    skip.add(i + k)
                merged = True
                break
        if not merged:
            tokens.append(raw_tokens[i])
    return tokens


def _join_entity_expanded_tokens_for_fts(expanded_tokens: list[str]) -> str:
    """Join entity-expanded fragments with explicit FTS5 AND where needed."""
    joined: list[str] = []
    for i, token in enumerate(expanded_tokens):
        if i > 0 and (expanded_tokens[i - 1].endswith(")") or token.startswith("(")):
            joined.append(" AND ")
        elif i > 0:
            joined.append(" ")
        joined.append(token)
    return "".join(joined).strip()


def _entity_expansion_terms(entity: dict[str, Any], *, min_alias_length: int = 1) -> list[str]:
    terms = [str(entity["primary_name"]).strip()]
    for alias in entity.get("aliases", []):
        alias_str = str(alias).strip()
        if len(alias_str) >= min_alias_length:
            terms.append(alias_str)

    deduped: list[str] = []
    for term in terms:
        if term and term not in deduped:
            deduped.append(term)
    return deduped


def _bare_relation_suffix(pattern: dict[str, Any]) -> str:
    suffix = str(pattern.get("suffix") or "").strip()
    if suffix.startswith("的"):
        return suffix[1:]
    return suffix


def _relation_patterns_for_token(token: str, view: EntityRuntimeView) -> list[dict[str, Any]]:
    token_str = token.strip()
    if not token_str:
        return []

    direct_patterns = [
        pattern for pattern in view.phrase_patterns if _bare_relation_suffix(pattern) == token_str
    ]
    if direct_patterns:
        return direct_patterns

    canonical = normalize_relation(token_str)
    if canonical == token_str and not relation_aliases(canonical):
        return []

    return [
        pattern
        for pattern in view.phrase_patterns
        if normalize_relation(str(pattern.get("relation") or "")) == canonical
    ]


def _relation_token_entities(token: str, view: EntityRuntimeView) -> list[dict[str, Any]]:
    """Resolve a bare relation term to confirmed one-hop related entities."""

    matches: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for pattern in _relation_patterns_for_token(token, view):
        relation = str(pattern["relation"])
        direction = str(pattern.get("direction", "symmetric"))
        role_filter = pattern.get("role_filter")
        for source in view.entities:
            for target in _expand_related_entities(
                source=source,
                relation=relation,
                view=view,
                direction=direction,
                role_filter=role_filter,
                observer_id=source["id"],
            ):
                entity_id = str(target["id"])
                if entity_id in seen_ids:
                    continue
                seen_ids.add(entity_id)
                matches.append(target)
    return matches


def expand_query_with_entity_graph(query: str) -> str:
    """Expand a search query using entity graph aliases and relationship phrases.

    Uses the runtime view for O(1) lookup instead of linear scanning.
    Supports phrase patterns from the registry (e.g., X的老婆, X的奶奶, X的妈妈).
    Gracefully degrades if graph is missing or invalid.
    """
    # Read user data dir dynamically via lazy getter to support test isolation
    from ..lib.paths import get_user_data_dir

    graph_path = get_user_data_dir() / "entity_graph.yaml"
    try:
        graph = load_entity_graph(graph_path)
    except EntityGraphValidationError as exc:
        logger.warning("Skipping entity graph expansion due to invalid graph: %s", exc)
        return query
    if not graph:
        return query

    view = build_runtime_view(graph)
    serving_graph = view.entities

    def _expand_entity_names(entity: dict[str, Any]) -> str:
        return "(" + " OR ".join(_entity_expansion_terms(entity, min_alias_length=2)) + ")"

    def _iter_subject_candidates(token: str, suffix: str) -> list[str]:
        subjects: list[str] = []
        if token.endswith(suffix):
            subjects.append(token[: -len(suffix)].strip())

        if suffix.startswith("的"):
            bare_suffix = suffix[1:]
            if bare_suffix and token.endswith(bare_suffix):
                bare_subject = token[: -len(bare_suffix)].strip()
                if bare_subject and bare_subject not in subjects:
                    subjects.append(bare_subject)

        return [subject for subject in subjects if subject]

    # 1. Whole-query exact match (unchanged behavior)
    whole_match = resolve_via_runtime(query, view)
    if whole_match:
        return _expand_entity_names(whole_match)

    # 2. Token-level expansion
    raw_tokens = [token for token in query.split() if token.strip()]

    tokens = _merge_multi_word_entity_tokens(raw_tokens, view)
    expanded_tokens: list[str] = []

    def _expand_phrase_pattern(token: str) -> str | None:
        """Try to match a relationship phrase pattern like X的老婆, X的奶奶."""
        from tools.lib.entity_runtime import _get_matching_role_labels

        for pattern in view.phrase_patterns:
            suffix = pattern["suffix"]
            relation = pattern["relation"]
            direction = pattern.get("direction", "symmetric")
            role_filter = pattern.get("role_filter")
            deduped_names: list[str] = []
            for subject in _iter_subject_candidates(token, suffix):
                source = resolve_via_runtime(subject, view)
                if source is None:
                    continue
                observer_id = source["id"]
                for target in _expand_related_entities(
                    source=source,
                    relation=relation,
                    view=view,
                    direction=direction,
                    role_filter=role_filter,
                    observer_id=observer_id,
                ):
                    for name in [target["primary_name"], *target.get("aliases", [])]:
                        if name not in deduped_names:
                            deduped_names.append(name)
                    for label in _get_matching_role_labels(
                        target, role_filter, observer_id=observer_id
                    ):
                        if label not in deduped_names:
                            deduped_names.append(label)

            if deduped_names:
                return "(" + " OR ".join(deduped_names) + ")"
        return None

    for token in tokens:
        # Try phrase pattern expansion first (e.g., 晴岚的奶奶)
        phrase_expansion = _expand_phrase_pattern(token)
        if phrase_expansion:
            expanded_tokens.append(phrase_expansion)
            continue

        # Try direct entity match (e.g., 老婆 as alias)
        matched_entity = resolve_via_runtime(token, view)
        if matched_entity:
            expanded_tokens.append(_expand_entity_names(matched_entity))
        else:
            relation_entities = _relation_token_entities(token, view)
            if relation_entities:
                relation_terms: list[str] = []
                for entity in relation_entities:
                    for term in _entity_expansion_terms(entity, min_alias_length=2):
                        if term not in relation_terms:
                            relation_terms.append(term)
                expanded_tokens.append("(" + " OR ".join(relation_terms) + ")")
                continue

            # Substring replacement: position-aware, non-overlapping.
            # Collect all (start, end, entity) matches in the original token,
            # prefer longest match at the same start, skip overlaps, then
            # build the result from accepted spans so generated OR groups are
            # never scanned for additional matches.
            spans: list[tuple[int, int, dict[str, Any]]] = []
            for entity in serving_graph:
                for name in [entity["primary_name"], *entity.get("aliases", [])]:
                    if len(str(name).strip()) < 2:
                        continue
                    for idx, end in _iter_entity_term_spans(token, str(name)):
                        spans.append((idx, end, entity))

            # Sort by start ascending, then by length descending (longest first)
            spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

            # Greedy non-overlapping selection: keep longest at each position,
            # skip anything that overlaps a previously accepted span.
            accepted: list[tuple[int, int, dict[str, Any]]] = []
            last_end = 0
            for start, end, ent in spans:
                if start < last_end:
                    continue
                # Check if a longer span already accepted at this start
                if accepted and accepted[-1][0] == start:
                    continue
                accepted.append((start, end, ent))
                last_end = end

            if not accepted:
                expanded_tokens.append(token)
                continue

            # Build FTS-safe segments. When an OR group is embedded inside a
            # larger token, explicit AND boundaries avoid malformed FTS syntax
            # such as "在(重庆 OR Chongqing)发生过的事".
            parts: list[str] = []
            cursor = 0
            for start, end, ent in accepted:
                prefix = token[cursor:start]
                if prefix:
                    parts.append(prefix)
                parts.append(_expand_entity_names(ent))
                cursor = end
            suffix = token[cursor:]
            if suffix:
                parts.append(suffix)

            result = " AND ".join(parts)
            expanded_tokens.append(result)

    # FTS5 requires explicit AND at parenthesized group boundaries.
    # Paths 2/3 produce standalone (OR group) fragments; path 1 already
    # has explicit AND internally via " AND ".join(parts). When adjacent
    # tokens produce )token or token( boundaries, FTS5 throws syntax error.
    expanded = _join_entity_expanded_tokens_for_fts(expanded_tokens)
    return expanded or query


def resolve_query_entities(query: str) -> list[dict[str, Any]]:
    """Resolve entity hints from a query string.

    Returns structured entity hint objects for CLI/Agent consumption.
    Does NOT modify the query — only observes what entities were matched.

    Each hint contains:
        - matched_term: the token that matched
        - entity_id: the resolved entity's id
        - primary_name: deterministic display name for the entity
        - entity_type: actor/place/project/event/artifact/concept
        - expansion_terms: all names/aliases for the entity
        - reason: how the match happened (alias_match / primary_name_match / phrase_match)
    """
    if not query or not query.strip():
        return []

    from ..lib.paths import get_user_data_dir

    graph_path = get_user_data_dir() / "entity_graph.yaml"
    try:
        graph = load_entity_graph(graph_path)
    except EntityGraphValidationError:
        return []
    if not graph:
        return []

    view = build_runtime_view(graph)
    serving_graph = view.entities
    hints: list[dict[str, Any]] = []
    seen_entity_ids: set[str] = set()

    def _add_hint(entity: dict[str, Any], matched_term: str, reason: str) -> None:
        if entity["id"] in seen_entity_ids:
            return
        seen_entity_ids.add(entity["id"])
        hints.append(
            {
                "matched_term": matched_term,
                "entity_id": entity["id"],
                "primary_name": entity["primary_name"],
                "entity_type": entity["type"],
                "expansion_terms": _entity_expansion_terms(entity),
                "reason": reason,
            }
        )

    def _iter_subject_candidates(token: str, suffix: str) -> list[str]:
        subjects: list[str] = []
        if token.endswith(suffix):
            subjects.append(token[: -len(suffix)].strip())

        if suffix.startswith("的"):
            bare_suffix = suffix[1:]
            if bare_suffix and token.endswith(bare_suffix):
                bare_subject = token[: -len(bare_suffix)].strip()
                if bare_subject and bare_subject not in subjects:
                    subjects.append(bare_subject)

        return [subject for subject in subjects if subject]

    def _match_relation(actual_relation: str, expected_relation: str) -> bool:
        return normalize_relation(actual_relation) == normalize_relation(expected_relation)

    # Check whole-query match first
    whole_match = resolve_via_runtime(query.strip(), view)
    if whole_match:
        reason = (
            "primary_name_match" if query.strip() == whole_match["primary_name"] else "alias_match"
        )
        _add_hint(whole_match, query.strip(), reason)
        return hints

    # Token-level matching
    tokens = [t for t in query.split() if t.strip()]

    for token in tokens:
        # Try phrase patterns
        phrase_matched = False
        for pattern in view.phrase_patterns:
            suffix = pattern["suffix"]
            relation = pattern["relation"]
            direction = pattern.get("direction", "symmetric")
            role_filter = pattern.get("role_filter")
            matched_any = False
            for subject in _iter_subject_candidates(token, suffix):
                source = resolve_via_runtime(subject, view)
                if source is None:
                    continue

                for target in _expand_related_entities(
                    source=source,
                    relation=relation,
                    view=view,
                    direction=direction,
                    role_filter=role_filter,
                    observer_id=source["id"],
                ):
                    _add_hint(target, token, "phrase_match")
                    matched_any = True

            if matched_any:
                phrase_matched = True
                break
        if phrase_matched:
            continue

        # Direct entity match
        matched = resolve_via_runtime(token, view)
        if matched:
            reason = "primary_name_match" if token == matched["primary_name"] else "alias_match"
            _add_hint(matched, token, reason)
        else:
            relation_entities = _relation_token_entities(token, view)
            if relation_entities:
                for entity in relation_entities:
                    _add_hint(entity, token, "relation_match")
                continue

            # Substring scanning for entity names embedded in unsplit CJK tokens.
            # Mirrors expand_query_with_entity_graph's Path 1 logic with
            # identical guardrails: two-char minimum, position-aware
            # non-overlapping, longest-match-wins, ASCII word boundaries.
            spans: list[tuple[int, int, dict[str, Any]]] = []
            for entity in serving_graph:
                for name in [entity["primary_name"], *entity.get("aliases", [])]:
                    if len(str(name).strip()) < 2:
                        continue
                    for idx, end in _iter_entity_term_spans(token, str(name)):
                        spans.append((idx, end, entity))

            spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

            accepted: list[tuple[int, int, dict[str, Any]]] = []
            last_end = 0
            for start, end, ent in spans:
                if start < last_end:
                    continue
                if accepted and accepted[-1][0] == start:
                    continue
                accepted.append((start, end, ent))
                last_end = end

            for _, _, ent in accepted:
                _add_hint(ent, token, "embedded_name_match")

    # Multi-word window: try adjacent token spans for entities whose primary
    # name or alias contains spaces (e.g. "Life Index", "Life Index Project").
    # Longer windows tried first so "Life Index Project" is preferred over
    # the shorter "Life Index".
    consumed: set[int] = set()
    for window_len in range(len(tokens), 1, -1):
        for start in range(len(tokens) - window_len + 1):
            if any(start + k in consumed for k in range(window_len)):
                continue
            candidate = " ".join(tokens[start : start + window_len])
            matched = resolve_via_runtime(candidate, view)
            if matched:
                reason = (
                    "primary_name_match" if candidate == matched["primary_name"] else "alias_match"
                )
                _add_hint(matched, candidate, reason)
                for k in range(window_len):
                    consumed.add(start + k)

    return hints


def _search_level_1(
    *,
    result: Dict[str, Any],
    topic: Optional[str],
    project: Optional[str],
    tags: Optional[List[str]],
    start_time: float,
) -> Dict[str, Any]:
    """Level 1: 索引层搜索"""
    l1_start = time.time()

    if topic:
        result["l1_results"].extend(search_l1_index("topic", topic))
    if project:
        result["l1_results"].extend(search_l1_index("project", project))
    if tags:
        for tag in tags:
            result["l1_results"].extend(search_l1_index("tag", tag))

    if not topic and not project and not tags:
        result["l1_results"].extend(scan_all_indices())

    seen_paths: set = set()
    unique_l1: List[Dict] = []
    for item in result["l1_results"]:
        if item["path"] not in seen_paths:
            seen_paths.add(item["path"])
            unique_l1.append(item)
    result["l1_results"] = unique_l1

    result["performance"]["l1_time_ms"] = round((time.time() - l1_start) * 1000, 2)
    result["total_found"] = len(result["l1_results"])
    result["total_matches"] = len(result["l1_results"])
    result["total_available"] = len(result["l1_results"])
    result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


def _search_level_2(
    *,
    result: Dict[str, Any],
    query: Optional[str],
    topic: Optional[str],
    project: Optional[str],
    tags: Optional[List[str]],
    mood: Optional[List[str]],
    people: Optional[List[str]],
    date_from: Optional[str],
    date_to: Optional[str],
    location: Optional[str],
    weather: Optional[str],
    start_time: float,
    use_metadata_cache: bool = True,
) -> Dict[str, Any]:
    """Level 2: 索引 + 元数据搜索"""
    l1_start = time.time()

    if topic:
        result["l1_results"].extend(search_l1_index("topic", topic))
    if project:
        result["l1_results"].extend(search_l1_index("project", project))
    if tags:
        for tag in tags:
            result["l1_results"].extend(search_l1_index("tag", tag))

    seen_paths: set = set()
    unique_l1: List[Dict] = []
    for item in result["l1_results"]:
        if item["path"] not in seen_paths:
            seen_paths.add(item["path"])
            unique_l1.append(item)
    result["l1_results"] = unique_l1
    result["performance"]["l1_time_ms"] = round((time.time() - l1_start) * 1000, 2)

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
        "query": query,
    }
    if not use_metadata_cache:
        l2_kwargs["use_cache"] = False
    l2_response = search_l2_metadata(
        **l2_kwargs,
    )
    result["l2_results"] = l2_response["results"]
    if l2_response.get("truncated"):
        result["l2_truncated"] = True
        result["l2_total_available"] = l2_response.get("total_available", 0)

    result["performance"]["l2_time_ms"] = round((time.time() - l2_start) * 1000, 2)
    result["total_matches"] = len(result["l2_results"])
    result["total_available"] = len(result["l2_results"])
    result["total_found"] = len(result["l2_results"])
    result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
    return result


def _build_search_diagnostics(result: dict[str, Any]) -> dict[str, Any]:
    """Build deterministic diagnostics dict for search --explain output."""
    performance = result.get("performance", {})
    latency_ms: dict[str, float] = {
        "total": performance.get("total_time_ms", 0),
    }
    if "l1_time_ms" in performance:
        latency_ms["l1"] = performance["l1_time_ms"]
    if "l2_time_ms" in performance:
        latency_ms["l2"] = performance["l2_time_ms"]
    if "l3_time_ms" in performance:
        latency_ms["l3"] = performance["l3_time_ms"]
    input_count = result.get("total_available", result.get("total_found", 0))

    return {
        "input_count": input_count,
        "filter_drops": {},
        "cache_hits": 0,
        "cache_misses": 0,
        "latency_ms": latency_ms,
        "fallback_path": None,
    }


def _eval_anchor() -> date | None:
    """Return the eval anchor date from the environment, or None."""
    env = os.environ.get("LIFE_INDEX_TIME_ANCHOR")
    if env:
        return date.fromisoformat(env)
    return None


def _date_range_dict_from_plan(plan: Any | None) -> dict[str, str] | None:
    """Extract a flat date-range dict from a SearchPlan for ranking kwargs.

    Returns None if the plan has no usable date_range.
    """
    if plan is None or plan.date_range is None:
        return None
    dr: dict[str, str] = {}
    if plan.date_range.since:
        dr["since"] = plan.date_range.since
    if plan.date_range.until:
        dr["until"] = plan.date_range.until
    return dr if dr else None


def _is_pure_temporal_query(plan: Any | None) -> bool:
    """Return True when the query contains only a time expression.

    Detects queries like '四月份', '3月4号', '2026-01-28' where the
    entire meaningful content is a temporal expression.  In these cases
    the keyword pipeline should fall back to date-only L2 retrieval.
    """
    if plan is None or plan.date_range is None:
        return False
    from .query_preprocessor import extract_time_expression

    keywords = getattr(plan, "keywords", None)
    if not keywords:
        return True
    return all(extract_time_expression(kw) == kw for kw in keywords)


def _augment_with_structured_metadata(
    l2_results: list[dict[str, Any]],
    candidate_paths: set[str] | None,
    plan: Any | None,
    date_from: str | None,
    date_to: str | None,
    result: dict[str, Any],
    use_metadata_cache: bool = True,
) -> list[str]:
    """Supplement L2 with structured metadata candidates from date_range + topic_hints.

    Returns list of added paths. Mutates l2_results and candidate_paths in place.
    """
    added: list[str] = []
    if not (STRUCTURED_RETRIEVAL_ENABLED and plan and plan.date_range):
        return added
    # M09: Date-navigation mode — when keywords are empty and no topic_hints,
    # retrieve all metadata-matched journals within the date_range. This ensures
    # pure date navigation ("2026年03月的日志") returns candidates.
    if plan.topic_hints:
        for hint in plan.topic_hints:
            structured_kwargs: dict[str, Any] = {
                "date_from": date_from,
                "date_to": date_to,
                "topic": hint,
                "query": None,
            }
            if not use_metadata_cache:
                structured_kwargs["use_cache"] = False
            _structured = search_l2_metadata(**structured_kwargs)
            for r in _structured["results"]:
                r["source"] = "structured_metadata"
                if r["path"] not in {x["path"] for x in l2_results}:
                    l2_results.append(r)
                    added.append(r["path"])
                    if candidate_paths is not None:
                        candidate_paths.add(r["path"])
    elif not plan.keywords:
        # Pure date navigation: no keywords, no topic — just date_range
        structured_kwargs = {
            "date_from": date_from,
            "date_to": date_to,
            "query": None,
        }
        if not use_metadata_cache:
            structured_kwargs["use_cache"] = False
        _structured = search_l2_metadata(**structured_kwargs)
        for r in _structured["results"]:
            r["source"] = "structured_metadata"
            if r["path"] not in {x["path"] for x in l2_results}:
                l2_results.append(r)
                added.append(r["path"])
                if candidate_paths is not None:
                    candidate_paths.add(r["path"])
    if added:
        result["warnings"].append(
            "structured_metadata: added " f"{len(added)} candidates from date_range+topic_hints"
        )
    return added


def _finalize_level3_results(
    result: dict[str, Any],
    query: str | None,
    start_time: float,
    explain: bool,
    is_fallback: bool = False,
    emit_metrics: bool = True,
) -> None:
    """Promote, explain, and log merged results. Mutates result in place.

    Date-only results are sorted by freshness (date descending).
    Truncation is deferred to the presentation layer (__main__.py).
    This layer records total_matches (complete candidate set count) and
    leaves merged_results at full size.  Per CHARTER §1.11 rule #2 and
    §3.1, the retrieval/ranking layer must NOT hard-cap the candidate
    set.
    """
    if not query:
        result["merged_results"].sort(
            key=lambda r: str(r.get("date") or r.get("metadata", {}).get("date", "")),
            reverse=True,
        )

    total_matches = len(result["merged_results"])
    result["total_matches"] = total_matches
    result["total_available"] = total_matches
    result["total_found"] = total_matches
    result["has_more"] = False

    # Phase 1: establish retrieval_coverage.v1 as the single authority for
    # completeness, then PROJECT the legacy total_*/has_more fields from it so
    # they cannot drift. The presentation layer re-scopes ``returned``/``offset``
    # for a paginated response window and re-projects.
    from .coverage import build_coverage_for_result, project_legacy_from_coverage

    result["retrieval_coverage"] = build_coverage_for_result(
        result, returned=total_matches, offset=0
    )
    result.update(project_legacy_from_coverage(result["retrieval_coverage"]))

    result["no_confident_match"] = _compute_no_confident_match(result["merged_results"])

    from .title_promotion import apply_title_promotion

    result["merged_results"] = apply_title_promotion(result["merged_results"], query or "")

    if explain:
        from .ranking_reason import compose as compose_reason

        for r in result["merged_results"]:
            r["query"] = query or ""
            r["ranking_reason"] = compose_reason(r)
            del r["query"]

    result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)

    if explain:
        result["diagnostics"] = _build_search_diagnostics(result)

    if emit_metrics:
        _emit_search_metrics(result)

    total_time = result["performance"]["total_time_ms"]
    l1_time = result["performance"].get("l1_time_ms", 0)
    l2_time = result["performance"].get("l2_time_ms", 0)
    l3_time = result["performance"].get("l3_time_ms", 0)
    suffix = f" (fallback={result['semantic_fallback_used']})" if is_fallback else ""
    logger.info(
        f"[SearchPerf] Total: {total_time}ms "
        f"(L1:{l1_time} L2:{l2_time} L3:{l3_time}) "
        f"| Results: {result['total_found']}{suffix}"
    )


def _classify_query_advisory(query: str) -> str | None:
    """Return a fail-open classification warning without exposing query text."""
    try:
        from .noise_gate import is_noise_query

        is_advisory, advisory_reason = is_noise_query(query)
    except Exception as exc:
        return f"query_classification_error: {type(exc).__name__}; " "retrieval_not_bypassed"

    if is_advisory:
        return f"query_classification: {advisory_reason}; retrieval_not_bypassed"
    return None


def _semantic_noop_requested(
    semantic: bool,
    semantic_policy: Literal["hybrid", "fallback"],
    semantic_weight: float,
) -> bool:
    """Return True when a caller requested now-deprecated semantic behavior."""

    return semantic or semantic_policy != "fallback" or semantic_weight != SEMANTIC_WEIGHT_DEFAULT


def _build_entity_expansion_attribution(entity_hints: list[dict[str, Any]]) -> dict[str, Any]:
    """Build caller-facing attribution for deterministic Entity Graph expansion."""

    expansions: list[dict[str, Any]] = []
    for hint in entity_hints:
        reason = hint.get("reason")
        if reason not in {
            "alias_match",
            "primary_name_match",
            "embedded_name_match",
            "relation_match",
            "phrase_match",
        }:
            continue
        matched_term = str(hint.get("matched_term") or "").strip()
        if not matched_term:
            continue
        targets: list[str] = []
        for term in hint.get("expansion_terms") or []:
            term_str = str(term).strip()
            if term_str and term_str != matched_term and term_str not in targets:
                targets.append(term_str)
        if not targets:
            continue
        expansions.append(
            {
                "from": matched_term,
                "to": targets,
                "via": "relation" if reason in {"relation_match", "phrase_match"} else "alias",
                "entity_id": hint.get("entity_id"),
                "primary_name": hint.get("primary_name"),
            }
        )
    return {"applied": bool(expansions), "expansions": expansions}


def _finalize_fail_closed(
    result: Dict[str, Any], exc: "LifeIndexError", start_time: float, *, emit_metrics: bool = True
) -> None:
    """Fail closed: refuse a potentially-truncated subset. Mutates result in place.

    The retrieval hit the high-cardinality safety bound. Rather than return a
    truncated subset that could be mistaken for the complete set, surface a
    closed, machine-readable resource failure through the EXISTING search error
    envelope (``LifeIndexError`` → E0301 + ``details.reason =
    retrieval_resource_bound``). No merged_results subset and no false-complete
    coverage object are emitted; the error envelope is the authority here.
    """
    err = exc.to_json()
    result["success"] = False
    result["error"] = err["error"]
    result["merged_results"] = []
    result["semantic_results"] = []
    result["total_matches"] = 0
    result["total_found"] = 0
    result["total_available"] = 0
    result["has_more"] = False
    result["no_confident_match"] = True
    result["performance"]["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
    result["warnings"].append(
        "retrieval_resource_bound: observed candidate set exceeded the safety "
        "bound; refusing to return a potentially-truncated subset"
    )
    if emit_metrics:
        _emit_search_metrics(result)


def hierarchical_search(
    query: Optional[str] = None,
    topic: Optional[str] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    project: Optional[str] = None,
    tags: Optional[List[str]] = None,
    mood: Optional[List[str]] = None,
    people: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    level: int = 3,
    use_index: bool = True,
    semantic: bool = False,
    semantic_weight: float = SEMANTIC_WEIGHT_DEFAULT,
    fts_weight: float = FTS_WEIGHT_DEFAULT,
    # Web-only recall overrides
    semantic_top_k: int = SEMANTIC_TOP_K_DEFAULT,
    semantic_min_similarity: float = SEMANTIC_MIN_SIMILARITY,
    # Phase 1 (#1): the default effective token-match relevance threshold is 0.
    # Neither the FTS layer nor the merge/ranking layer may drop low-relevance
    # token-matches via a dynamic threshold by default. An explicit nonzero
    # value still applies (and is counted) — see keyword_pipeline + coverage.
    fts_min_relevance: int = 0,
    rrf_min_score: float = RRF_MIN_SCORE,
    non_rrf_min_score: float = NON_RRF_MIN_SCORE,
    explain: bool = False,  # Task 2.1: explain mode
    semantic_policy: Literal["hybrid", "fallback"] = "fallback",
    enable_source_tier: bool = False,  # gbrain Phase B: opt-in source-tier boost
    emit_metrics: bool = True,
    use_metadata_cache: bool = True,
    derived_index_only: bool = False,
) -> Dict[str, Any]:
    """
    分层搜索（keyword/entity only；--semantic* 已废弃为空操作）

    Pipeline A: L1 索引过滤 → L2 元数据过滤 → L3 FTS5 内容匹配

    当 level=1 或 level=2 时，按原逻辑提前返回（向后兼容）。
    level=3（默认）运行关键词 + Entity Graph 管道。semantic 参数保留为兼容 no-op。
    """
    semantic_noop_requested = _semantic_noop_requested(
        semantic=semantic,
        semantic_policy=semantic_policy,
        semantic_weight=semantic_weight,
    )
    result: Dict[str, Any] = {
        "success": True,
        "query_params": {
            "query": query,
            "topic": topic,
            "year": year,
            "month": month,
            "project": project,
            "tags": tags,
            "mood": mood,
            "people": people,
            "date_from": date_from,
            "date_to": date_to,
            "level": level,
            "semantic": semantic,
            "enable_source_tier": enable_source_tier,
        },
        "l1_results": [],
        "l2_results": [],
        "l3_results": [],
        "semantic_results": [],
        "merged_results": [],
        "total_found": 0,
        "total_matches": 0,
        "total_available": 0,
        "has_more": False,
        "semantic_available": False,
        "performance": {},
        "warnings": [],  # Phase 2C: 降级警告收集
        "entity_hints": [],  # Round 7 Phase 1: structured entity suggestion hints
        "entity_expansion": {"applied": False, "expansions": []},
        # Round 11 Phase 0: query understanding output placeholders
        "search_plan": None,  # Phase 1 implementation: structured query understanding
        "ambiguity": {"has_ambiguity": False, "items": []},  # Phase 2 implementation
        "hints": [],  # Phase 2 implementation: invocation-time hints
        "semantic_policy": semantic_policy,
        "semantic_fallback_used": False,
        "semantic_effective_policy": "deprecated_noop" if semantic_noop_requested else "off",
    }

    # Round 10 T1.2: Expose entity graph status
    from ..lib.entity_graph import check_graph_status
    from ..lib.paths import get_user_data_dir

    graph_status = check_graph_status(get_user_data_dir() / "entity_graph.yaml")
    result["entity_graph_status"] = graph_status

    result["semantic_note"] = (
        "in-tool semantic/vector search is disabled; using keyword + Entity Graph."
    )
    if semantic_noop_requested:
        result["warnings"].append(SEMANTIC_DEPRECATED_NOOP_WARNING)

    # F1: Eval anchor deterministic injection
    # Resolve a single anchor date for all time-dependent subsystems.
    _now = _eval_anchor() or date.today()

    # Round 7 Phase 1: Resolve entity hints before expansion
    entity_hints = resolve_query_entities(query) if query else []
    result["entity_hints"] = entity_hints
    result["entity_expansion"] = _build_entity_expansion_attribution(entity_hints)

    # Round 11 Phase 0→1: Query understanding via preprocessor
    _plan = None
    if query:
        from .query_preprocessor import build_search_plan as _build_plan

        _plan = _build_plan(query, reference_date=_now)
        _plan.entity_hints_used = entity_hints
        _sp_dict = _plan.to_dict()
        _sp_dict["schema_version"] = SEARCH_PLAN_SCHEMA_VERSION
        result["search_plan"] = _sp_dict
        # C1-a/b: Propagate typo-corrected / alias-expanded query into pipeline
        if _plan.normalized_query and _plan.normalized_query != query:
            query = _plan.normalized_query

    # Round 11 Phase 2: Ambiguity detection + hints
    if _plan is not None:
        from .ambiguity_detector import detect_ambiguity as _detect_amb
        from .hints_builder import build_hints as _build_hints

        _ambiguity = _detect_amb(_plan, query or "", entity_hints)
        result["ambiguity"] = _ambiguity.to_dict()
        _hints = _build_hints(_plan, _ambiguity)
        result["hints"] = [h.to_dict() for h in _hints]

    expanded_query = expand_query_with_entity_graph(query) if query else query
    _entity_expanded = expanded_query != query
    if _entity_expanded:
        result["query_params"]["expanded_query"] = expanded_query
    query = expanded_query

    # Phase 2-B: Use preprocessor expanded_query for cleaner keyword search
    # when entity expansion did not modify the query.
    # Only use when it's a single token (no spaces) to avoid breaking
    # _segment_query_for_fts was_segmented detection.
    # M09: Skip when keywords are empty — the expanded_query is then a bare
    # time expression (e.g. "2026年03月") that should not be used as FTS query.
    # In this case the pipeline should rely on date_range filtering instead.
    if (
        _plan
        and _plan.expanded_query
        and expanded_query == _plan.raw_query
        and " " not in _plan.expanded_query
        and _plan.keywords
    ):
        query = _plan.expanded_query

    start_time = time.time()

    # Pre-compute topic hints / date range for keyword ranking.
    _topic_hints = _plan.topic_hints if _plan else None
    _date_range = _date_range_dict_from_plan(_plan)

    # Round 12 Phase 3: Unified freshness guard + pending consumption
    from ..lib.pending_writes import has_pending as _has_pending, clear_pending as _clear_pending
    from ..lib.index_freshness import check_full_freshness as _check_full_freshness
    from ..lib.paths import get_user_data_dir as _get_user_data_dir

    _index_dir = _get_user_data_dir() / ".index"

    # Step 1: If pending writes, trigger build and consume
    if _has_pending():
        result["index_status"] = {
            "pending_before_search": True,
            "auto_updated": False,
            "pending_consumed": False,
        }
        try:
            from ..build_index import build_all as _build_all

            logger.info("Pending writes detected, triggering incremental index update")
            build_kwargs: dict[str, Any] = {"incremental": True, "fts_only": True}
            if derived_index_only:
                build_kwargs["derived_index_only"] = True
            build_result = _build_all(**build_kwargs)
            build_success = (
                build_result.get("success", True) if isinstance(build_result, dict) else True
            )
            if build_success:
                _clear_pending()
                result["pending_consumed"] = True
                result["index_status"]["auto_updated"] = True
                result["index_status"]["pending_consumed"] = True
            else:
                error = (
                    build_result.get("error")
                    or (build_result.get("fts") or {}).get("error")
                    or "unknown index update failure"
                )
                logger.warning("Pending index update returned unsuccessful: %s", error)
                result["warnings"].append(f"pending_index_update_failed: {error}")
                result["pending_consumed"] = False
        except Exception as exc:
            logger.warning("Pending index update failed, continuing with stale index: %s", exc)
            result["warnings"].append(f"pending_index_update_failed: {exc}")
            result["pending_consumed"] = False
    else:
        # Step 2: Check full freshness (FTS + vector + manifest)
        _freshness = _check_full_freshness(_index_dir)
        result["index_status"] = {
            "freshness": _freshness.to_dict(),
        }
        if not _freshness.overall_fresh:
            for issue in _freshness.issues:
                result["warnings"].append(f"index_stale: {issue}")
            try:
                from ..build_index import build_all as _build_all

                logger.info(
                    "Index stale, triggering incremental update: %s",
                    ", ".join(_freshness.issues),
                )
                build_kwargs = {"incremental": True, "fts_only": True}
                if derived_index_only:
                    build_kwargs["derived_index_only"] = True
                _build_all(**build_kwargs)
                result.setdefault("index_status", {})["auto_updated"] = True
            except Exception as exc:
                logger.warning("Auto index update failed: %s", exc)
                result.setdefault("index_status", {})["auto_updated"] = False

    # Round 19 Phase 1-C Track B: Time expression parsing
    # Sub-PRD-2.C: Prefer query_preprocessor date_range (broader pattern coverage)
    # Fallback to time_parser for edge cases not handled by preprocessor.
    _time_filter = None
    if query and not date_from and not date_to:
        if _plan and _plan.date_range:
            date_from = _plan.date_range.since
            date_to = _plan.date_range.until
            result["time_parsed"] = {
                "matched_span": _plan.date_range.source,
                "date_from": date_from,
                "date_to": date_to,
            }
        else:
            from ..lib.time_parser import parse_time_expression

            _time_filter = parse_time_expression(query, now=_now)
            if _time_filter:
                date_from = _time_filter.date_range.start.isoformat()
                date_to = _time_filter.date_range.end.isoformat()
                result["time_parsed"] = {
                    "matched_span": _time_filter.matched_span,
                    "date_from": date_from,
                    "date_to": date_to,
                }
            # NOTE: Topic inference from cleaned query was attempted but
            # reverted because keyword-based topic matching is unreliable
            # (e.g. "开发" maps to "create" but user intent may be "work").
            # GQ53 remains a failure due to ranking, not time parsing.

    candidate_paths = build_l0_candidate_set(
        year=year, month=month, topic=topic, date_from=date_from, date_to=date_to
    )

    # B-C narrow rework: pure temporal query → date-only branch
    if _plan and _plan.date_range and _is_pure_temporal_query(_plan):
        query = None

    # ── Level 1: 索引层（向后兼容，提前返回） ──
    if level == 1:
        level_1_result = _search_level_1(
            result=result,
            topic=topic,
            project=project,
            tags=tags,
            start_time=start_time,
        )
        if explain:
            level_1_result["diagnostics"] = _build_search_diagnostics(level_1_result)
        if emit_metrics:
            _emit_search_metrics(level_1_result)
        return level_1_result

    # ── Level 2: 索引 + 元数据（向后兼容，提前返回） ──
    if level == 2:
        level_2_result = _search_level_2(
            result=result,
            query=query,
            topic=topic,
            project=project,
            tags=tags,
            mood=mood,
            people=people,
            date_from=date_from,
            date_to=date_to,
            location=location,
            weather=weather,
            start_time=start_time,
            use_metadata_cache=use_metadata_cache,
        )
        if explain:
            level_2_result["diagnostics"] = _build_search_diagnostics(level_2_result)
        if emit_metrics:
            _emit_search_metrics(level_2_result)
        return level_2_result

    # ── Level 3: 全文检索（keyword/entity only） ──
    # Query classification is advisory only.  Recall-first retrieval must still
    # execute for every query so a label cannot hide a real token match.
    if query:
        classification_warning = _classify_query_advisory(query)
        if classification_warning:
            result["warnings"].append(classification_warning)

    # Phase 1 (#6): a high-cardinality / resource-bound failure inside the
    # retrieval pipeline raises a structured LifeIndexError. Fail CLOSED — surface
    # it via the standard error envelope (success=false, E0301) instead of
    # returning a truncated subset or letting a bare exception escape.
    try:
        (
            l1_results,
            l2_results,
            l3_results,
            l2_truncated,
            l2_total_available,
            kw_perf,
        ) = run_keyword_pipeline(
            query=query,
            topic=topic,
            project=project,
            tags=tags,
            mood=mood,
            people=people,
            date_from=date_from,
            date_to=date_to,
            location=location,
            weather=weather,
            use_index=use_index,
            fts_min_relevance=fts_min_relevance,
            candidate_paths=candidate_paths,
            entity_expanded=_entity_expanded,
            use_metadata_cache=use_metadata_cache,
        )

        # R1-Prep: Structured metadata retrieval (shared helper)
        _augment_with_structured_metadata(
            l2_results,
            candidate_paths,
            _plan,
            date_from,
            date_to,
            result,
            use_metadata_cache=use_metadata_cache,
        )

        l1_results = _filter_results_by_candidates(l1_results, candidate_paths)
        l2_results = _filter_results_by_candidates(l2_results, candidate_paths)
        l3_results = _filter_results_by_candidates(l3_results, candidate_paths)

        result["l1_results"] = l1_results
        result["l2_results"] = l2_results
        result["l3_results"] = l3_results
        result["semantic_results"] = []
        result["semantic_available"] = False
        if l2_truncated:
            result["l2_truncated"] = True
            result["l2_total_available"] = l2_total_available
        result["performance"].update(kw_perf)

        result["merged_results"] = merge_and_rank_results(
            l1_results,
            l2_results,
            l3_results,
            query,
            min_score=fts_min_relevance,
            entity_hints=entity_hints,
            explain=explain,
            topic_hints=_topic_hints,
            date_range=_date_range,
            enable_source_tier=enable_source_tier,
            relation_context="cache" if use_metadata_cache else "source",
        )

        _finalize_level3_results(result, query, start_time, explain, emit_metrics=emit_metrics)
    except LifeIndexError as exc:
        _finalize_fail_closed(result, exc, start_time, emit_metrics=emit_metrics)

    return result
