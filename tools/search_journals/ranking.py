#!/usr/bin/env python3
"""
Life Index - Search Journals Tool - Ranking
结果排序算法模块
"""

from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from ..lib.frontmatter import parse_journal_file
from ..lib.metadata_cache import get_backlinked_by, init_metadata_cache
from ..lib.path_contract import build_journal_path_fields
from ..lib.paths import get_journals_dir, get_user_data_dir
from ..lib.search_constants import (
    SCORE_L1_BASE,
    SCORE_L2_BASE,
    SCORE_TITLE_MATCH_BONUS,
    SCORE_TITLE_MATCH_BONUS_L2,
    SCORE_ABSTRACT_MATCH_BONUS,
    SCORE_TAGS_MATCH_BONUS,
    SCORE_ENTITY_BONUS,
    SCORE_LOCATION_MATCH_BONUS,
    TOPIC_HINT_BOOST,
    NON_RRF_MIN_SCORE,
    MAX_RESULTS_DEFAULT,
    FTS_MIN_RELEVANCE,
    SOURCE_TIER_WEIGHTS,
)
from .l2_metadata import _query_matches_tags, _query_matches_text
from .utils import parse_frontmatter


def enrich_semantic_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight metadata enrichment for legacy semantic-score inputs.

    Active search no longer calls a semantic backend, but ranking tests and
    adapter code can still pass precomputed semantic-like rows. Enrichment must
    stay deterministic and must not import model/vector runtime.
    """
    enriched = result.copy()
    path = enriched.get("path")
    if not path:
        return enriched

    try:
        file_path = Path(str(path))
        if not file_path.exists():
            return enriched
        metadata, _body = parse_frontmatter(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return enriched

    if not enriched.get("title") and metadata.get("title"):
        enriched["title"] = metadata["title"]

    for field in (
        "abstract",
        "tags",
        "topic",
        "mood",
        "project",
        "location",
        "weather",
        "people",
    ):
        if metadata.get(field):
            enriched[field] = metadata[field]
    enriched["metadata"] = metadata
    return enriched


def _to_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value]
    return []


def _entity_bonus(result: dict[str, Any], entity_hints: list[dict[str, Any]]) -> int:
    """Return entity bonus if any expansion term appears in result signals.

    B-9: Checks metadata (people|tags) AND lightweight text signals (title,
    snippet/abstract) so entity matching is not overly dependent on metadata
    completeness.
    """
    if not entity_hints:
        return 0

    expansion_terms: set[str] = set()
    for hint in entity_hints:
        expansion_terms.update(str(term) for term in hint.get("expansion_terms", []))

    if not expansion_terms:
        return 0

    # Check metadata signals (people, tags)
    metadata = result.get("metadata", {})
    if isinstance(metadata, dict):
        people = set(_to_string_list(metadata.get("people")))
        tags = set(_to_string_list(metadata.get("tags")))
        if (people | tags) & expansion_terms:
            return SCORE_ENTITY_BONUS

    # B-9: Also check lightweight text signals (title, snippet)
    title = str(result.get("title", ""))
    snippet = str(result.get("snippet", ""))
    # Also check abstract from metadata
    abstract = ""
    if isinstance(metadata, dict):
        abstract = str(metadata.get("abstract", ""))

    text_signals = f"{title} {snippet} {abstract}".lower()
    for term in expansion_terms:
        if term.lower() in text_signals:
            return SCORE_ENTITY_BONUS

    return 0


def _topic_boost_multiplier(result: dict[str, Any], topic_hints: list[str] | None) -> float:
    """Return TOPIC_HINT_BOOST if result's topic matches any topic_hints.

    Phase 4 T4.2: Conservative boost — only 1.1x, not enough to override
    large FTS/RRF score gaps.
    """
    if not topic_hints:
        return 1.0

    result_topics: set[str] = set()

    # Check top-level topic field
    topic = result.get("topic")
    if isinstance(topic, list):
        result_topics.update(str(t) for t in topic)
    elif isinstance(topic, str):
        result_topics.add(topic)

    # Check metadata.topic
    metadata = result.get("metadata", {})
    if isinstance(metadata, dict):
        meta_topic = metadata.get("topic")
        if isinstance(meta_topic, list):
            result_topics.update(str(t) for t in meta_topic)
        elif isinstance(meta_topic, str):
            result_topics.add(meta_topic)

    if result_topics & set(topic_hints):
        return TOPIC_HINT_BOOST
    return 1.0


def _compute_source_tier(result: dict[str, Any]) -> str:
    """Determine source tier from result path and metadata.

    Tiers reflect evidence quality: well-curated journals with rich frontmatter
    are primary sources; generated reports and attachments are secondary.
    """
    path = str(result.get("path", ""))
    metadata = result.get("metadata", {}) or {}
    if not isinstance(metadata, dict):
        metadata = {}

    # Generated reports / indexes (not currently in search corpus but future-proof)
    if "Abstracts/" in path or "by-topic/" in path:
        return "generated_report"
    if "attachments/" in path:
        return "attachment_ocr"

    # Journal entries: classify by frontmatter richness
    topic = metadata.get("topic")
    people = metadata.get("people")
    tags = metadata.get("tags")
    related = metadata.get("related_entries")

    has_topic = bool(topic)
    has_people = bool(people and ((isinstance(people, list) and people) or isinstance(people, str)))
    has_tags = bool(tags and ((isinstance(tags, list) and tags) or isinstance(tags, str)))
    has_related = bool(related and isinstance(related, list) and related)

    if has_topic and (has_people or has_tags or has_related):
        return "journal_rich"
    if has_topic or has_people or has_tags:
        return "journal_standard"
    return "journal_basic"


def _apply_source_tier_boost(
    scored: dict[str, dict[str, Any]],
    enable: bool,
) -> None:
    """Apply source-tier weight multiplier to final_score in-place.

    Only mutates scores when enable=True.  Default-off preserves exact
    backward compatibility.
    """
    if not enable:
        return
    for entry in scored.values():
        tier = _compute_source_tier(entry.get("data", {}))
        weight = SOURCE_TIER_WEIGHTS.get(tier, 1.0)
        # Keyword path uses "score" key.
        if "score" in entry:
            entry["score"] = entry["score"] * weight
        # Hybrid path uses "final_score" key
        if "final_score" in entry:
            entry["final_score"] = entry["final_score"] * weight


def _structured_intent_match(
    result: dict[str, Any],
    date_range: dict[str, str] | None,
    topic_hints: list[str] | None,
) -> bool:
    """Return True if result's date falls within date_range AND topic hits topic_hints.

    R1: Narrow bonus gate — only activates when search_plan explicitly
    provides both date_range and topic_hints, and the candidate's frontmatter
    matches both dimensions.
    """
    if not date_range or not topic_hints:
        return False

    since = date_range.get("since")
    until = date_range.get("until")
    if not since or not until:
        return False

    # Date match
    date_str = result.get("date", "")
    if not date_str:
        return False
    try:
        from datetime import datetime

        d = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        d_str = d.strftime("%Y-%m-%d")
        if not (since <= d_str <= until):
            return False
    except Exception:
        return False

    # Topic match (reuse logic from _topic_boost_multiplier)
    result_topics: set[str] = set()
    topic = result.get("topic")
    if isinstance(topic, list):
        result_topics.update(str(t) for t in topic)
    elif isinstance(topic, str):
        result_topics.add(topic)
    metadata = result.get("metadata", {})
    if isinstance(metadata, dict):
        meta_topic = metadata.get("topic")
        if isinstance(meta_topic, list):
            result_topics.update(str(t) for t in meta_topic)
        elif isinstance(meta_topic, str):
            result_topics.add(meta_topic)

    return bool(result_topics & set(topic_hints))


def _dynamic_threshold_floor(base_threshold: float, dynamic_threshold: float) -> float:
    """Keep dynamic thresholds from becoming more permissive than baseline."""
    return max(base_threshold, dynamic_threshold)


def _tukey_fence_threshold(
    scores: list[float], *, base_threshold: float, k: float = 1.5
) -> float:  # Tukey standard k=1.5 (mild outliers)
    """Compute a robust threshold using Tukey's IQR fence method.

    More resistant to outliers than mean/stddev for small sample sizes.

    Args:
        scores: Non-zero score values from scored results.
        base_threshold: Minimum floor — dynamic threshold never goes below this.
        k: Tukey multiplier (1.5 = standard, 3.0 = far outliers).

    Returns:
        A threshold value ≥ base_threshold.
    """
    if len(scores) < 8:
        return base_threshold

    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    q1 = sorted_scores[n // 4]
    q3 = sorted_scores[3 * n // 4]
    iqr = q3 - q1

    if iqr <= 0:
        # All scores very similar — no meaningful spread to exploit
        return base_threshold

    lower_fence = q1 - k * iqr
    return _dynamic_threshold_floor(base_threshold, lower_fence)


def _compute_dynamic_fts_threshold(
    scored_results: list[dict[str, Any]],
    *,
    base_threshold: float,
) -> float:
    """Compute a stricter FTS threshold from score distribution using Tukey IQR."""
    scores = [float(item["score"]) for item in scored_results if float(item["score"]) > 0]
    return _tukey_fence_threshold(scores, base_threshold=base_threshold)


def _attach_relation_context(
    data: Dict[str, Any],
    *,
    metadata_conn: Any | None = None,
    source_backlinks: dict[str, list[str]] | None = None,
) -> Dict[str, Any]:
    """Attach related_entries and backlinked_by to final search result payload."""
    enriched = data.copy()
    metadata = enriched.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        enriched["metadata"] = metadata

    rel_path = enriched.get("rel_path")
    related_entries = metadata.get("related_entries", enriched.get("related_entries", []))
    if not isinstance(related_entries, list):
        related_entries = []

    backlinked_by: list[str] = []
    if isinstance(rel_path, str) and rel_path and metadata_conn is not None:
        backlinked_by = get_backlinked_by(metadata_conn, rel_path)
    elif isinstance(rel_path, str) and rel_path and source_backlinks is not None:
        backlinked_by = source_backlinks.get(rel_path, [])

    enriched["related_entries"] = related_entries
    enriched["backlinked_by"] = backlinked_by
    metadata.setdefault("related_entries", related_entries)
    metadata["backlinked_by"] = backlinked_by
    return enriched


def _build_source_backlinks() -> dict[str, list[str]]:
    """Derive reverse journal relations directly from frontmatter."""
    journals_dir = get_journals_dir()
    if not journals_dir.exists():
        return {}

    backlinks: dict[str, set[str]] = {}
    for journal_path in sorted(journals_dir.glob("*/*/life-index_*.md")):
        try:
            metadata = parse_journal_file(journal_path)
            related_entries = metadata.get("related_entries", [])
            if not isinstance(related_entries, list):
                continue
            source_rel_path = build_journal_path_fields(
                journal_path,
                journals_dir=journals_dir,
                user_data_dir=get_user_data_dir(),
            )["rel_path"]
        except (OSError, ValueError):
            continue

        for target_path in related_entries:
            if not isinstance(target_path, str) or not target_path:
                continue
            backlinks.setdefault(target_path, set()).add(source_rel_path)

    return {target_path: sorted(sources) for target_path, sources in backlinks.items()}


def _classify_confidence(**kwargs: Any) -> str:
    result: str = import_module("tools.search_journals.confidence").classify_confidence(**kwargs)
    return result


def merge_and_rank_results(
    l1_results: List[Dict],
    l2_results: List[Dict],
    l3_results: List[Dict],
    query: Optional[str] = None,
    min_score: float = FTS_MIN_RELEVANCE,
    max_results: int = MAX_RESULTS_DEFAULT,
    entity_hints: Optional[List[Dict[str, Any]]] = None,
    explain: bool = False,
    topic_hints: Optional[List[str]] = None,
    date_range: Optional[Dict[str, str]] = None,
    enable_source_tier: bool = False,
    relation_context: Literal["cache", "source"] = "cache",
) -> List[Dict]:
    """
    合并三层搜索结果并按相关性排序

    排序策略：
    1. L3 内容匹配（最高优先级）：使用 BM25 分数
    2. L2 元数据匹配：title/abstract 匹配加分
    3. L1 索引匹配：基础存在分
    """
    scored: Dict[str, Dict[str, Any]] = {}  # path -> {data, score, tier}

    # L3: 内容匹配（最高优先级，BM25 分数已计算）
    for r in l3_results:
        path = r["path"]
        # BM25 分数转换：relevance 已经是 0-100 的匹配度
        base_score = r.get("relevance", 0)
        # 标题匹配额外加分
        if r.get("title_match"):
            base_score += SCORE_TITLE_MATCH_BONUS
        scored[path] = {"data": r, "score": base_score, "tier": 3}

    # L2: 元数据匹配（当不在 L3 中时添加；当已在 L3 中时叠加 bonus）
    for r in l2_results:
        path = r["path"]
        bonus = 0

        if query:
            title = r.get("title", "")
            metadata = r.get("metadata", {})
            abstract = (
                metadata.get("abstract", "") if isinstance(metadata.get("abstract"), str) else ""
            )
            tags = metadata.get("tags", [])

            # Multi-token query: OR semantics for metadata matching (C1-b alias support)
            query_tokens = query.split()
            tokens = query_tokens if len(query_tokens) > 1 else [query]
            location = (
                metadata.get("location", "") if isinstance(metadata.get("location"), str) else ""
            )
            location_matched = False
            for token in tokens:
                if _query_matches_text(title, token):
                    bonus += SCORE_TITLE_MATCH_BONUS_L2
                if _query_matches_text(abstract, token):
                    bonus += SCORE_ABSTRACT_MATCH_BONUS
                if _query_matches_tags(tags, token):
                    bonus += SCORE_TAGS_MATCH_BONUS
                if not location_matched and _query_matches_text(location, token):
                    bonus += SCORE_LOCATION_MATCH_BONUS
                    location_matched = True

            # Extra bonus for title containing the full query phrase
            if len(query_tokens) > 1:
                title_lower = title.lower()
                query_lower = query.lower()
                if title_lower.startswith(query_lower):
                    bonus += 10
                elif query_lower in title_lower:
                    bonus += 3

        bonus += _entity_bonus(r, entity_hints or [])

        if path in scored:
            if bonus > 0:
                scored[path]["score"] += bonus
            continue

        # L2 基础分必须低于 L3 最低分（L3 最低约 30-40）
        # 确保即使 L2 title 完全匹配，也不超过 L3 的 BM25 分数
        score = SCORE_L2_BASE + bonus
        scored[path] = {"data": r, "score": score, "tier": 2}

    # L1: 索引匹配（最低优先级）
    for r in l1_results:
        path = r["path"]
        if path in scored:
            continue
        scored[path] = {
            "data": r,
            "score": SCORE_L1_BASE,  # L1 基础分
            "tier": 1,
        }

    # Phase 4 T4.2: Apply topic hint boost (conservative multiplier)
    if topic_hints:
        for path, entry in scored.items():
            boost = _topic_boost_multiplier(entry["data"], topic_hints)
            if boost > 1.0:
                entry["score"] = entry["score"] * boost

    # R1: Structured intent match bonus for keyword-only path.
    if date_range and topic_hints:
        from ..lib.search_constants import STRUCTURED_INTENT_MATCH_BONUS_KEYWORD

        for path, entry in scored.items():
            if _structured_intent_match(entry["data"], date_range, topic_hints):
                entry["score"] = entry["score"] + STRUCTURED_INTENT_MATCH_BONUS_KEYWORD

    # Phase B: Apply source-tier boost (opt-in, default off)
    _apply_source_tier_boost(scored, enable_source_tier)

    # 按分数降序排序，分数相同按 tier 排序（高 tier 优先），
    # 再按 title 中完整短语出现位置排序（越靠前越优先，C1-a/b）
    def _title_phrase_position(data: dict, q: str) -> int:
        title = data.get("title", "").lower()
        pos = title.find(q.lower()) if q else -1
        return pos if pos != -1 else 9999

    def _candidate_sort_path(data: dict) -> str:
        """Canonical path used as the FINAL tie-breaker (path-ascending).

        Phase 1 (#3): when score, tier, and title-phrase position all tie, a
        deterministic path-ascending order guarantees that paginating the same
        query never overlaps or skips. We pre-sort by this key, then run the
        stable main sort so equal-key rows retain path-ascending order.
        """
        return str(data.get("rel_path") or data.get("journal_route_path") or data.get("path") or "")

    # Two-step stable sort: (1) path-ascending baseline, then (2) the main sort
    # by (score desc, tier desc, title-position asc). Python's stable sort keeps
    # the path-ascending order among rows that tie on every main key, so the
    # path tie-breaker applies only when all existing sort keys tie.
    sorted_results = sorted(scored.values(), key=lambda x: _candidate_sort_path(x["data"]))
    sorted_results.sort(
        key=lambda x: (
            x["score"],
            x["tier"],
            -_title_phrase_position(x["data"], query or ""),
        ),
        reverse=True,
    )

    # 分层阈值：L3 (FTS) 使用 min_score（Phase 1：默认 token-match 阈值=0，不再用
    # 动态 Tukey 阈值丢弃低相关 token-match），L2/L1 使用更宽松的 NON_RRF_MIN_SCORE。
    # _compute_dynamic_fts_threshold / _tukey_fence_threshold 保留定义（单元测试覆盖），
    # 但不再在合并/排序路径调用。
    effective_fts_threshold = min_score

    def _passes_threshold(item: Dict[str, Any]) -> bool:
        tier: int = int(item.get("tier", 0))
        score: float = float(item["score"])
        if tier >= 3:
            # L3 (FTS content match) uses FTS threshold
            return score >= effective_fts_threshold
        else:
            # L2/L1 (metadata/index) use more lenient threshold
            return score >= NON_RRF_MIN_SCORE

    sorted_results = [item for item in sorted_results if _passes_threshold(item)]
    # NOTE: Truncation removed per Phase 2 (Task 3) — ranking returns ALL results.
    # Truncation now happens in core.py (presentation concern, not ranking concern).

    # 提取数据并添加排名信息
    merged = []
    if relation_context == "cache":
        metadata_conn = init_metadata_cache()
        source_backlinks: dict[str, list[str]] | None = None
    else:
        metadata_conn = None
        source_backlinks = _build_source_backlinks() if sorted_results else {}
    try:
        for rank, item in enumerate(sorted_results, 1):
            data = _attach_relation_context(
                item["data"],
                metadata_conn=metadata_conn,
                source_backlinks=source_backlinks,
            )
            data["search_rank"] = rank
            # T4.2: Unified score fields (keyword path)
            data["rrf_score"] = 0.0  # Keyword path has no RRF fusion.
            data["final_score"] = round(float(item["score"]), 2)
            data["relevance_score"] = data["final_score"]  # backward-compat alias
            data["fts_score"] = round(float(item["score"]), 2)
            data["semantic_score"] = 0.0
            # T4.3: Source field (keyword path: all results are FTS-tier, no semantic)
            data["source"] = "fts" if item.get("tier", 0) >= 3 else "none"
            data["confidence"] = _classify_confidence(
                fts_score=float(item["score"]),
                semantic_score=0.0,
                rrf_score=0.0,
            )
            # T3.4: Explain support for keyword path
            if explain:
                data["explain"] = {
                    "keyword_pipeline": {
                        "fts_score": round(float(item["score"]), 2),
                        "has_fts_match": item.get("tier", 0) >= 3,
                    },
                    "semantic_pipeline": {
                        "cosine_similarity": 0.0,
                        "has_semantic_match": False,
                    },
                    "fusion": {
                        "rrf_score": 0.0,
                        "has_rrf": False,
                    },
                }
            merged.append(data)
    finally:
        if metadata_conn is not None:
            metadata_conn.close()

    return merged
