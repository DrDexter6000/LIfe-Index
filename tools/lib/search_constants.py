"""
Life Index - Search Constants Module
====================================
Centralized constants for search pipelines with ADR rationale.

This module is the SSOT for all search-related magic numbers.
Any change to these values must be documented with the rationale.

ADR-002 / ADR-005 / ADR-010: Deprecated semantic compatibility defaults
-----------------------------------------------------------------------
Semantic/vector retrieval has been removed from the active tool pipeline.
These values remain only as defaults for deprecated CLI/API parameters so
old callers can pass `--semantic*` flags without breaking.

ADR-003: FTS min_relevance=25
----------------------------
BM25 relevance threshold (0-100 scale) for keyword results. Below 25, matches
are typically fragment hits or stop-word contamination.

This value ensures only meaningful keyword matches appear in results.

ADR-004: Deprecated RRF min_score=0.008
---------------------------------------
Retained only as a default for the deprecated `rrf_min_score` compatibility
parameter. Active search no longer runs an RRF or hybrid ranking path.

ADR-005: Deprecated semantic top_k=30
------------------------------------
Retained only as a default for deprecated semantic compatibility parameters.
Active search does not retrieve semantic candidates.

ADR-006: Max results=20
-----------------------
Maximum results returned to user. Beyond 20, cognitive load increases while
marginal value decreases sharply.

Users can paginate or refine queries if they need more.

ADR-007: FTS fallback threshold=5
---------------------------------
When FTS returns fewer than 5 results, we supplement with full-corpus scan.
This catches body-only keyword matches that might be missed by stale index.

5 is low enough to avoid unnecessary scans, but high enough to catch
legitimate low-recall scenarios.

ADR-008: Score weights
----------------------
- L1 base score: 10 (presence indicator)
- L2 base score: 30 (metadata match, must exceed FTS_MIN_RELEVANCE=25)
- L3 base score: BM25 relevance (content match, highest)
- Title match bonus: 10 (strong signal)
- Abstract match bonus: 4 (moderate signal)
- Tags match bonus: 1 (weak auxiliary signal)

These ensure proper ordering: L3 > L2 > L1 for same-query scenarios.
L2 base must exceed FTS_MIN_RELEVANCE so that L2-only results survive the
non-hybrid merge_and_rank_results threshold (which uses FTS_MIN_RELEVANCE as floor).

ADR-009: BM25 relevance formula
-------------------------------
BM25 scores are negative for highly relevant documents (standard BM25 behavior).
We convert to 0-100 relevance using: relevance = max(0, min(100, 70 - bm25_score * 5))

- BM25 <= -5: relevance 95-100% (highly relevant)
- BM25 = 0: relevance 70% (moderately relevant)
- BM25 >= 5: relevance 30% (weakly relevant)

ADR-010: Snippet length=32 tokens
---------------------------------
FTS snippet uses 32 tokens context around match. This provides enough
context to understand the match without overwhelming the UI.

ADR-011: Tokenizer version for index freshness detection
---------------------------------------------------------
A TOKENIZER_VERSION integer is stored alongside the FTS index. When the
Chinese tokenizer (jieba) configuration changes, bumping this version
triggers an automatic full rebuild so that index tokens stay consistent
with query-time segmentation.

ADR-012: Entity hint ranking bonus=6
------------------------------------
When a query resolves to entity hints, results whose metadata people/tags fields
contain one of the entity expansion terms receive a modest bonus.

This bonus should break ties among weak L2/L1 matches without overtaking strong
L3 lexical evidence.

ADR-013: High-frequency term min_relevance=50
---------------------------------------------
Queries dominated by ubiquitous project terms like "Life Index" and "OpenClaw"
produce many weak matches. For these terms, we apply a stricter default FTS
relevance threshold while still allowing explicit `min_relevance` overrides.

ADR-015: Tukey IQR fence for dynamic thresholds
------------------------------------------------
Dynamic thresholds use Tukey's IQR fence method instead of mean-1.5σ.
IQR is more robust to outliers and small sample sizes than mean/stddev.
The minimum sample size remains 8 — below this, the base threshold is used unchanged.
"""

# =============================================================================
# Deprecated RRF Compatibility Defaults
# =============================================================================

# Accepted no-op default retained for the deprecated rrf_min_score parameter.
RRF_MIN_SCORE: float = 0.008


# =============================================================================
# Deprecated Semantic Compatibility Defaults
# =============================================================================

# Accepted no-op flag default retained for CLI/API compatibility.
SEMANTIC_MIN_SIMILARITY: float = 0.40

# Accepted no-op flag default retained for CLI/API compatibility.
SEMANTIC_TOP_K_DEFAULT: int = 30

# Accepted no-op flag default retained for CLI/API compatibility.
SEMANTIC_WEIGHT_DEFAULT: float = 1.0


# =============================================================================
# FTS (Full-Text Search) Constants
# =============================================================================

# ADR-003: Minimum BM25 relevance (0-100) for FTS results
FTS_MIN_RELEVANCE: int = 25

# Accepted no-op default retained for the deprecated fts_weight parameter.
FTS_WEIGHT_DEFAULT: float = 1.0

# Maximum FTS results to retrieve
FTS_LIMIT: int = 100

# ADR-007: FTS fallback threshold (supplement with full scan if below)
FTS_FALLBACK_THRESHOLD: int = 5

# ADR-014: Retrieval materialization safety bound.
# Phase 1 materializes the full admitted candidate set before paginating
# (CHARTER §1.11), so FTS_LIMIT no longer silently caps retrieval. A
# pathologically large corpus could exhaust memory; this bound is a fail-closed
# backstop only — when exceeded the retrieval raises rather than returning a
# truncated subset that could be mistaken for the complete set. It is far above
# any realistic journal corpus and never reached by the synthetic fixtures.
FTS_MAX_RETRIEVAL_BOUND: int = 100_000

# ADR-010: Snippet token count for FTS highlights
FTS_SNIPPET_TOKENS: int = 32

# ADR-013: stricter defaults for noisy project terms
HIGH_FREQUENCY_TERMS: frozenset[str] = frozenset({"life index", "openclaw"})
HIGH_FREQUENCY_MIN_RELEVANCE: int = 50


# =============================================================================
# Ranking Score Constants
# =============================================================================

# ADR-008: Base scores for each layer
SCORE_L1_BASE: int = 10  # Index presence
# Metadata match (must exceed FTS_MIN_RELEVANCE=25 to survive non-hybrid merge threshold)
SCORE_L2_BASE: int = 30
# L3 uses BM25 relevance directly

# ADR-008: Match bonuses
SCORE_TITLE_MATCH_BONUS: int = 10
SCORE_TITLE_MATCH_BONUS_L2: int = 8  # Slightly lower for L2
SCORE_ABSTRACT_MATCH_BONUS: int = 4
SCORE_TAGS_MATCH_BONUS: int = 3
SCORE_ENTITY_BONUS: int = 6

# R2-A2C: Location metadata ranking bonus
# When a query token matches metadata.location, the L2 candidate receives this
# bonus. Value chosen so that location-only exact match (30+15=45) outranks
# generic L2 title+abstract matches (30+8+4=42) in GQ64. Bounded: max L2 with
# all bonuses (30+8+4+3+6+15=66) stays below L3 ceiling (BM25_RELEVANCE_BASE+10=80).
SCORE_LOCATION_MATCH_BONUS: int = 15

# ADR-016: Topic hint ranking boost (Phase 4 T4.2)
# Conservative 1.1x multiplier applied to results whose topic matches search_plan.topic_hints.
# Must not override large keyword score gaps — only breaks close ties.
TOPIC_HINT_BOOST: float = 1.1

# Minimum score for keyword metadata/index results.
NON_RRF_MIN_SCORE: int = 10

# R1-Prep: Enable structured metadata retrieval when search_plan provides
# both date_range and topic_hints. This supplements the keyword pipeline
# with pure metadata matches (no keyword filtering) to recall logs whose
# body lacks query keywords but whose topic/date align with user intent.
STRUCTURED_RETRIEVAL_ENABLED: bool = True

# Keyword-only path: added to raw score (0-100 scale). 50 lifts GQ53 L2 target
# from base 30 to 80, but keyword L3 floor (~128) still keeps it outside top5.
# Bonus is kept as a conservative safety margin; it does NOT guarantee top5.
STRUCTURED_INTENT_MATCH_BONUS_KEYWORD: int = 50


# =============================================================================
# Result Limits
# =============================================================================

# ADR-006: Maximum results returned to user
MAX_RESULTS_DEFAULT: int = 20


# =============================================================================
# BM25 Relevance Conversion Constants
# =============================================================================

# ADR-009: BM25 to relevance conversion
# relevance = max(0, min(100, int(BM25_RELEVANCE_BASE - bm25_score * BM25_RELEVANCE_MULTIPLIER)))
BM25_RELEVANCE_BASE: int = 70
BM25_RELEVANCE_MULTIPLIER: int = 5


# =============================================================================
# Tokenizer Version (Round 8 Phase 1)
# =============================================================================

# ADR-011: Tokenizer version for index freshness detection
# v1 = no segmentation (pre-jieba), v2 = jieba Chinese segmentation
# When this value changes, index must be rebuilt automatically.
TOKENIZER_VERSION: int = 2


# =============================================================================
# Confidence Thresholds (migrated from confidence.py)
# =============================================================================

# Confidence classification thresholds for search results.
# Migrated from confidence.py bare literals per CHARTER §4.3 compliance.
CONFIDENCE_HIGH_FTS: float = 70
CONFIDENCE_HIGH_SEMANTIC: float = 55
CONFIDENCE_HIGH_RRF: float = 0.018
CONFIDENCE_MEDIUM_FTS: float = 50
CONFIDENCE_MEDIUM_SEMANTIC: float = 45
CONFIDENCE_MEDIUM_RRF: float = 0.010


# =============================================================================
# Title Promotion Constants (migrated from title_promotion.py)
# =============================================================================

# Title hard promotion: post-rank multiplier for title-matching results.
# Migrated from title_promotion.py per CHARTER §4.3 compliance.
TITLE_PROMOTION_MULTIPLIER: float = 1.5
TITLE_PROMOTION_COVERAGE_THRESHOLD: float = 0.60
TITLE_PROMOTION_MIN_QUERY_CHARS: int = 3


# =============================================================================
# L3 Fallback Scoring (migrated from l3_content.py)
# =============================================================================

# Fallback search relevance scoring for file-scan results.
# Migrated from l3_content.py per CHARTER §4.3 compliance.
L3_TITLE_MATCH_BONUS: int = 40
L3_BODY_MATCH_PER_HIT: int = 10
L3_MAX_FALLBACK_SCORE: int = 80
L3_MIN_FALLBACK_RELEVANCE: int = 15


# =============================================================================
# Keyword Pipeline Constants (migrated from keyword_pipeline.py)
# =============================================================================

# Token hit ratio for minimum required hits calculation.
# Migrated from keyword_pipeline.py per CHARTER §4.3 compliance.
KEYWORD_TOKEN_HIT_RATIO: float = 0.4


# =============================================================================
# Orchestrator Constants (Round 17 Phase 5)
# =============================================================================

# Maximum deterministic candidates returned in the host-agent evidence scaffold.
# The bound limits payload size while preserving the observed-availability metadata.
ORCHESTRATOR_MAX_CANDIDATES: int = 15


# =============================================================================
# Fuzzy Typo Correction Constants (Round 19 Phase 1-D C1-fuzzy)
# =============================================================================

# Canonical strings for fuzzy typo correction fallback.
# Only "life index" is in scope per plan §3.C1a.1; expansion is R1+ territory.
FUZZY_TYPO_CANONICALS: tuple[str, ...] = ("life index",)

# Standard Levenshtein normalized similarity threshold for fuzzy correction.
# Queries with similarity >= this value are auto-corrected to the canonical.
# Per plan §3.C1a.1 and Mode A Option B (exchange no.11 audit).
FUZZY_TYPO_RATIO_THRESHOLD: float = 0.85

# Maximum allowed length difference between query and canonical.
# Prevents false corrections on extended phrases (e.g. "Life Index 2.0").
FUZZY_TYPO_LEN_DIFF_MAX: int = 2

# Lower bound for Rule 8 typo_near_noise gate.
# Mid-similarity queries in [LOW, THRESHOLD) are blocked as near-typo noise.
NOISE_GATE_TYPO_NEAR_LOW: float = 0.65


# =============================================================================
# Source-tier Ranking Boost (gbrain absorption Phase B)
# =============================================================================

# ADR-017: Evidence-quality multipliers applied to final_score when
# --enable-source-tier is passed. Higher values promote well-curated primary
# sources (journals with rich frontmatter) over sparse or generated content.
SOURCE_TIER_WEIGHTS = {
    "journal_rich": 1.08,  # topic + (people|tags|related_entries)
    "journal_standard": 1.04,  # topic or people or tags
    "journal_basic": 1.00,  # minimal metadata
    "generated_report": 0.95,  # abstracts, indexes (future-proof)
    "attachment_ocr": 0.90,  # external attachments (future-proof)
}


# =============================================================================
# Export all constants
# =============================================================================

__all__ = [
    # Deprecated RRF compatibility defaults
    "RRF_MIN_SCORE",
    # Semantic
    "SEMANTIC_MIN_SIMILARITY",
    "SEMANTIC_TOP_K_DEFAULT",
    "SEMANTIC_WEIGHT_DEFAULT",
    # FTS
    "FTS_MIN_RELEVANCE",
    "FTS_WEIGHT_DEFAULT",
    "FTS_LIMIT",
    "FTS_FALLBACK_THRESHOLD",
    "FTS_SNIPPET_TOKENS",
    "HIGH_FREQUENCY_TERMS",
    "HIGH_FREQUENCY_MIN_RELEVANCE",
    # Scoring
    "SCORE_L1_BASE",
    "SCORE_L2_BASE",
    "SCORE_TITLE_MATCH_BONUS",
    "SCORE_TITLE_MATCH_BONUS_L2",
    "SCORE_ABSTRACT_MATCH_BONUS",
    "SCORE_TAGS_MATCH_BONUS",
    "SCORE_ENTITY_BONUS",
    "SCORE_LOCATION_MATCH_BONUS",
    "TOPIC_HINT_BOOST",
    "NON_RRF_MIN_SCORE",
    # Limits
    "MAX_RESULTS_DEFAULT",
    # BM25
    "BM25_RELEVANCE_BASE",
    "BM25_RELEVANCE_MULTIPLIER",
    # Tokenizer
    "TOKENIZER_VERSION",
    # Confidence Thresholds
    "CONFIDENCE_HIGH_FTS",
    "CONFIDENCE_HIGH_SEMANTIC",
    "CONFIDENCE_HIGH_RRF",
    "CONFIDENCE_MEDIUM_FTS",
    "CONFIDENCE_MEDIUM_SEMANTIC",
    "CONFIDENCE_MEDIUM_RRF",
    # Title Promotion
    "TITLE_PROMOTION_MULTIPLIER",
    "TITLE_PROMOTION_COVERAGE_THRESHOLD",
    "TITLE_PROMOTION_MIN_QUERY_CHARS",
    # L3 Fallback Scoring
    "L3_TITLE_MATCH_BONUS",
    "L3_BODY_MATCH_PER_HIT",
    "L3_MAX_FALLBACK_SCORE",
    "L3_MIN_FALLBACK_RELEVANCE",
    # Keyword Pipeline
    "KEYWORD_TOKEN_HIT_RATIO",
    # Orchestrator
    "ORCHESTRATOR_MAX_CANDIDATES",
    # Fuzzy Typo Correction
    "FUZZY_TYPO_CANONICALS",
    "FUZZY_TYPO_RATIO_THRESHOLD",
    "FUZZY_TYPO_LEN_DIFF_MAX",
    "NOISE_GATE_TYPO_NEAR_LOW",
    # Structured Metadata Retrieval (R1-Prep)
    # When search_plan has both date_range and topic_hints, supplement
    # keyword pipeline with pure metadata matches to recall logs whose
    # body lacks query keywords but whose topic/date match the intent.
    "STRUCTURED_RETRIEVAL_ENABLED",
    # R1-safe-bonus: conservative structured-intent boost (does not guarantee top5)
    "STRUCTURED_INTENT_MATCH_BONUS_KEYWORD",
    # Source-tier ranking boost (gbrain absorption Phase B)
    "SOURCE_TIER_WEIGHTS",
]
