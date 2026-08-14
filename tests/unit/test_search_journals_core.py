#!/usr/bin/env python3
"""
Unit tests for tools/search_journals/core.py

Tests cover:
- Hierarchical search function
- Level 1/2/3 search integration
- Result merging and ranking
- Dual-pipeline parallel architecture (v1.2)

Note: After Phase 2B refactoring, mock targets changed:
- Level 3 keyword pipeline: patch at keyword_pipeline module
- Semantic/vector flags: deprecated no-op compatibility only
- Level 1/2: still patch at core module
"""

import pytest
from pathlib import Path
from unittest.mock import patch
import importlib
import sys
import os

from tools.lib.index_freshness import FreshnessReport

DEFAULT_ENTITY_GRAPH = {
    "entities": [
        {
            "id": "author-self",
            "type": "actor",
            "primary_name": "我",
            "aliases": ["作者", "自己"],
            "attributes": {},
            "relationships": [],
        },
        {
            "id": "mama",
            "type": "actor",
            "primary_name": "妈妈",
            "aliases": ["老妈", "婆婆", "王阿姨"],
            "attributes": {},
            "relationships": [{"target": "author-self", "relation": "mother_of"}],
        },
        {
            "id": "tuantuan",
            "type": "actor",
            "primary_name": "晴岚",
            "aliases": ["圆圆"],
            "attributes": {},
            "relationships": [{"target": "mama", "relation": "granddaughter_of"}],
        },
    ]
}


@pytest.mark.critical
class TestHierarchicalSearch:
    """Tests for hierarchical_search function"""

    @pytest.fixture(autouse=True)
    def _entity_graph(self, tmp_path: Path, monkeypatch):
        graph_path = tmp_path / "entity_graph.yaml"
        graph_path.write_text(
            __import__("yaml").safe_dump(DEFAULT_ENTITY_GRAPH, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(tmp_path))

    @pytest.fixture(autouse=True)
    def _mock_fresh_index_state(self):
        fresh_report = FreshnessReport(
            fts_fresh=True,
            vector_fresh=True,
            overall_fresh=True,
            issues=[],
        )
        with patch("tools.lib.index_freshness.check_full_freshness", return_value=fresh_report):
            with patch("tools.lib.pending_writes.has_pending", return_value=False):
                yield

    def test_search_results_reflect_fresh_backlinks_after_incremental_write_and_edit(
        self, tmp_path: Path
    ):
        import tools.lib.metadata_cache as mc
        import tools.lib.paths as paths_module
        import tools.lib.config as config_module
        import tools.write_journal.core as write_core
        import tools.edit_journal as edit_module
        from tools.search_journals.ranking import merge_and_rank_results

        original_env = os.environ.get("LIFE_INDEX_DATA_DIR")
        os.environ["LIFE_INDEX_DATA_DIR"] = str(tmp_path)
        importlib.reload(paths_module)
        importlib.reload(config_module)
        importlib.reload(mc)

        journals_dir = tmp_path / "Journals"
        journals_dir.mkdir(parents=True, exist_ok=True)
        target_path = journals_dir / "2026" / "03" / "target.md"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            '---\ntitle: "Target"\ndate: 2026-03-13\n---\n\nBody\n',
            encoding="utf-8",
        )

        try:
            with (
                patch.object(write_core, "get_journals_dir", return_value=journals_dir),
                patch.object(
                    write_core,
                    "get_journals_lock_path",
                    return_value=tmp_path / ".cache" / "journals.lock",
                ),
                patch.object(write_core, "get_year_month", return_value=(2026, 3)),
                patch.object(write_core, "get_next_sequence", return_value=1),
                patch.object(write_core, "query_weather_for_location", return_value="Sunny 25°C"),
                patch.object(write_core, "normalize_location", return_value="Chongqing, China"),
                patch.object(write_core, "extract_file_paths_from_content", return_value=[]),
                patch.object(write_core, "process_attachments", return_value=[]),
                patch.object(
                    write_core,
                    "update_monthly_abstract",
                    return_value={"abstract_path": None, "updated": False},
                ),
                patch.object(write_core, "update_topic_index", return_value=[]),
                patch.object(write_core, "update_project_index", return_value=None),
                patch.object(write_core, "update_tag_indices", return_value=[]),
                patch.object(write_core, "mark_pending"),
            ):
                (tmp_path / ".cache").mkdir(parents=True, exist_ok=True)
                (tmp_path / ".cache" / "journals.lock").touch()
                write_result = write_core.write_journal(
                    {
                        "date": "2026-03-14",
                        "title": "Source",
                        "content": "Body",
                        "related_entries": ["Journals/2026/03/target.md"],
                    },
                    dry_run=False,
                )

            source_path = Path(write_result["journal_path"])
            merged_after_write = merge_and_rank_results(
                [],
                [
                    {
                        "path": str(target_path).replace("\\", "/"),
                        "rel_path": "Journals/2026/03/target.md",
                        "title": "Target",
                        "metadata": {"related_entries": []},
                    }
                ],
                [],
                query="Target",
                min_score=0,
            )

            with (
                patch.object(edit_module, "get_journals_dir", return_value=journals_dir),
                patch.object(edit_module, "mark_pending"),
            ):
                edit_module.edit_journal(
                    journal_path=source_path,
                    frontmatter_updates={"remove_related_entries": ["Journals/2026/03/target.md"]},
                )

            merged_after_edit = merge_and_rank_results(
                [],
                [
                    {
                        "path": str(target_path).replace("\\", "/"),
                        "rel_path": "Journals/2026/03/target.md",
                        "title": "Target",
                        "metadata": {"related_entries": []},
                    }
                ],
                [],
                query="Target",
                min_score=0,
            )
        finally:
            if original_env is not None:
                os.environ["LIFE_INDEX_DATA_DIR"] = original_env
            else:
                del os.environ["LIFE_INDEX_DATA_DIR"]
            importlib.reload(paths_module)
            importlib.reload(config_module)
            importlib.reload(mc)

        assert merged_after_write[0]["backlinked_by"] == [
            "Journals/2026/03/life-index_2026-03-14_001.md"
        ]
        assert merged_after_edit[0]["backlinked_by"] == []

    def test_search_level3_keyword_results_surface_related_entries_and_backlinks(self):
        """Merged keyword search results should expose relation context."""
        from tools.search_journals.core import hierarchical_search

        merged_results = [
            {
                "path": "test.md",
                "rel_path": "Journals/2026/03/test.md",
                "title": "Test",
                "related_entries": ["Journals/2026/03/other.md"],
                "backlinked_by": ["Journals/2026/03/source.md"],
                "score": 0.9,
            }
        ]

        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "test.md", "relevance": 0.9}]
                    mock_rank.return_value = merged_results
                    result = hierarchical_search(
                        query="Python", level=3, semantic=False, use_index=False
                    )

        assert result["success"] is True
        assert result["merged_results"][0]["related_entries"] == ["Journals/2026/03/other.md"]
        assert result["merged_results"][0]["backlinked_by"] == ["Journals/2026/03/source.md"]

    def test_search_level3_sets_no_confident_match_when_all_results_are_low(self):
        """Top-level no_confident_match should be true when all results are low."""
        from tools.search_journals.core import hierarchical_search

        merged_results = [
            {
                "path": "test.md",
                "rel_path": "Journals/2026/03/test.md",
                "title": "Test",
                "confidence": "low",
            }
        ]

        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "test.md", "relevance": 0.9}]
                    mock_rank.return_value = merged_results
                    result = hierarchical_search(
                        query="Python", level=3, semantic=False, use_index=False
                    )

        assert result["no_confident_match"] is True

    def test_search_deprecated_semantic_results_surface_related_entries_and_backlinks(self):
        """Deprecated semantic flags still use keyword ranking with relation context."""
        from tools.search_journals.core import hierarchical_search

        merged_results = [
            {
                "path": "test.md",
                "rel_path": "Journals/2026/03/test.md",
                "title": "Test",
                "related_entries": ["Journals/2026/03/other.md"],
                "backlinked_by": ["Journals/2026/03/source.md"],
                "score": 0.8,
            }
        ]

        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = []
                    mock_rank.return_value = merged_results
                    result = hierarchical_search(
                        query="Python", level=3, semantic=True, use_index=False
                    )

        assert result["success"] is True
        assert result["merged_results"][0]["related_entries"] == ["Journals/2026/03/other.md"]
        assert result["merged_results"][0]["backlinked_by"] == ["Journals/2026/03/source.md"]

    def test_search_level1_no_filters_scans_all(self):
        """Level 1 without filters should scan all indices"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.scan_all_indices") as mock_scan:
            mock_scan.return_value = [{"path": "all.md", "date": "2026-03-14"}]
            result = hierarchical_search(level=1)

        assert result["success"] is True
        assert result["l1_results"] == [{"path": "all.md", "date": "2026-03-14"}]
        mock_scan.assert_called_once()

    def test_search_level1_by_topic(self):
        """Level 1 search by topic"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            mock_l1.return_value = [{"path": "test.md", "date": "2026-03-14"}]
            result = hierarchical_search(topic="work", level=1)

        assert result["success"] is True
        assert len(result["l1_results"]) >= 1
        mock_l1.assert_called_once_with("topic", "work")

    def test_search_level1_by_project(self):
        """Level 1 search by project"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            mock_l1.return_value = [{"path": "test.md", "date": "2026-03-14"}]
            result = hierarchical_search(project="Life-Index", level=1)

        assert result["success"] is True
        mock_l1.assert_called_once_with("project", "Life-Index")

    def test_search_level1_by_tags(self):
        """Level 1 search by tags"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            mock_l1.return_value = [{"path": "test.md", "date": "2026-03-14"}]
            result = hierarchical_search(tags=["python", "testing"], level=1)

        assert result["success"] is True
        assert mock_l1.call_count == 2  # One call per tag

    def test_search_level2_metadata(self):
        """Level 2 search with metadata"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l2_metadata") as mock_l2:
            mock_l2.return_value = {
                "results": [{"path": "test.md", "date": "2026-03-14"}],
                "truncated": False,
                "total_available": 1,
            }
            result = hierarchical_search(
                location="Beijing",
                date_from="2026-01-01",
                date_to="2026-03-31",
                level=2,
            )

        assert result["success"] is True
        mock_l2.assert_called_once()

    def test_search_level2_truncated_response(self):
        """Level 2 should propagate truncated metadata response"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l2_metadata") as mock_l2:
            mock_l2.return_value = {
                "results": [{"path": "test.md", "date": "2026-03-14"}],
                "truncated": True,
                "total_available": 100,
            }
            result = hierarchical_search(level=2)

        assert result["success"] is True
        assert result["l2_truncated"] is True
        assert result["l2_total_available"] == 100

    def test_search_level3_content(self):
        """Level 3 search with content query (keyword-only, semantic disabled)"""
        from tools.search_journals.core import hierarchical_search

        # Level 3 keyword pipeline uses keyword_pipeline module
        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "test.md", "relevance": 0.9}]
                    mock_rank.return_value = [{"path": "test.md", "score": 0.9}]
                    result = hierarchical_search(
                        query="Python", level=3, semantic=False, use_index=False
                    )

        assert result["success"] is True

    def test_search_semantic_flag_is_deprecated_noop(self):
        """Search accepts semantic=True but uses keyword ranking."""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = []
                    mock_rank.return_value = [{"path": "test.md", "score": 0.8}]
                    result = hierarchical_search(
                        query="Python", level=3, semantic=True, use_index=False
                    )

        assert result["success"] is True
        assert result["semantic_results"] == []
        assert result["semantic_effective_policy"] == "deprecated_noop"

    def test_search_no_results(self):
        """Search with no matching results"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            mock_l1.return_value = []
            result = hierarchical_search(topic="nonexistent", level=1)

        assert result["success"] is True
        assert result["total_found"] == 0

    def test_search_deduplication(self):
        """Results are deduplicated"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            # Return duplicate paths
            mock_l1.return_value = [
                {"path": "same.md", "date": "2026-03-14"},
                {"path": "same.md", "date": "2026-03-14"},
            ]
            result = hierarchical_search(topic="work", level=1)

        # Should deduplicate
        paths = [r["path"] for r in result["l1_results"]]
        assert paths.count("same.md") <= 1

    def test_search_includes_performance_metrics(self):
        """Search includes performance metrics"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            mock_l1.return_value = []
            result = hierarchical_search(topic="work", level=1)

        assert "performance" in result

    def test_search_default_semantic_false(self):
        """v1.2: semantic defaults to False (per CHARTER §1.11, ADR-028)."""
        from tools.search_journals.core import hierarchical_search

        with (
            patch(
                "tools.search_journals.core.run_keyword_pipeline",
                return_value=(
                    [],
                    [],
                    [],
                    False,
                    0,
                    {"l1_time_ms": 1.0, "l2_time_ms": 1.0, "l3_time_ms": 1.0},
                ),
            ),
            patch(
                "tools.search_journals.core._filter_results_by_candidates",
                side_effect=lambda x, _: x,
            ),
            patch(
                "tools.search_journals.core.merge_and_rank_results",
                side_effect=lambda l1, l2, l3, *a, **kw: l3,
            ),
        ):
            result = hierarchical_search(query="Python", level=3, use_index=False)

        assert result["success"] is True
        assert result["query_params"]["semantic"] is False

    def test_search_deprecated_semantic_policy_uses_keyword_pipeline(self):
        """level=3 with --semantic --semantic-policy hybrid stays keyword-only."""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "fts.md", "relevance": 80}]
                    mock_rank.return_value = [{"path": "fts.md", "score": 0.9}]
                    result = hierarchical_search(
                        query="test",
                        level=3,
                        use_index=False,
                        semantic=True,
                        semantic_policy="hybrid",
                    )

        assert result["success"] is True
        assert len(result["l3_results"]) >= 1
        assert result["semantic_results"] == []
        assert result["semantic_effective_policy"] == "deprecated_noop"
        assert "l3_time_ms" in result["performance"]
        assert "semantic_encode_ms" not in result["performance"]
        assert "semantic_search_ms" not in result["performance"]

    def test_search_no_semantic_flag(self):
        """v1.2: semantic=False disables semantic pipeline"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "test.md", "relevance": 80}]
                    mock_rank.return_value = [{"path": "test.md", "score": 0.8}]
                    result = hierarchical_search(
                        query="test", level=3, semantic=False, use_index=False
                    )

        assert result["success"] is True
        assert result["semantic_results"] == []
        assert result["semantic_available"] is False
        assert "semantic_note" in result

    def test_search_semantic_missing_index_degrades_to_keyword_only(self):
        """Missing semantic index should degrade gracefully with a user-facing note."""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "keyword.md", "relevance": 88}]
                    mock_rank.return_value = [{"path": "keyword.md", "score": 0.88}]

                    result = hierarchical_search(
                        query="test",
                        level=3,
                        semantic=True,
                        semantic_policy="hybrid",
                        use_index=False,
                    )

        assert result["success"] is True
        assert result["semantic_results"] == []
        assert result["semantic_available"] is False
        assert result["merged_results"] == [
            {"path": "keyword.md", "score": 0.88, "title_promoted": False}
        ]
        assert "disabled" in result["semantic_note"]
        assert "semantic_degraded" not in result["performance"]

    def test_search_invalid_legacy_entity_graph_degrades_gracefully(
        self, tmp_path: Path, monkeypatch
    ):
        """Legacy invalid entity graphs should not break search query expansion."""
        from tools.search_journals.core import hierarchical_search

        graph_path = tmp_path / "entity_graph.yaml"
        legacy_graph = {
            "entities": [
                {
                    "id": "mama",
                    "type": "actor",
                    "primary_name": "妈妈",
                    "aliases": ["老妈"],
                    "attributes": {},
                    "relationships": [{"target": "author", "relation": "mother_of"}],
                }
            ]
        }
        graph_path.write_text(
            __import__("yaml").safe_dump(legacy_graph, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(tmp_path))

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_l3.return_value = [{"path": "test.md", "relevance": 0.9}]
                    mock_rank.return_value = [{"path": "test.md", "score": 0.9}]

                    result = hierarchical_search(
                        query="Python", level=3, semantic=False, use_index=False
                    )

        assert result["success"] is True
        assert result["query_params"]["query"] == "Python"

    def test_search_level3_fts_query_preprocessing_and_success(self):
        """Level 3 should preprocess multi-keyword query and use FTS index results"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                with patch("tools.lib.search_index.search_fts") as mock_fts:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_fts.return_value = [
                        {
                            "path": "Journals/2026/03/test.md",
                            "date": "2026-03-14",
                            "title": "Test",
                            "snippet": "match",
                            "relevance": 88,
                        }
                    ]
                    mock_rank.return_value = [{"path": "test.md", "score": 0.88}]

                    result = hierarchical_search(
                        query="python testing code",
                        level=3,
                        semantic=False,
                        use_index=True,
                    )

        assert result["success"] is True
        assert result["l3_results"][0]["source"] == "fts_index"
        assert " OR " in mock_fts.call_args[0][0]

    def test_search_level3_fts_fallback_to_file_scan(self):
        """Level 3 should fall back to file scan when FTS import/search path fails"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l1_index") as mock_l1:
                with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                    with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                        mock_l2.return_value = {
                            "results": [{"path": "l2.md", "date": "2026-03-14"}],
                            "truncated": False,
                            "total_available": 1,
                        }
                        mock_l1.return_value = [{"path": "l1.md", "date": "2026-03-14"}]
                        mock_l3.return_value = [{"path": "scan.md", "relevance": 77}]
                        mock_rank.return_value = [{"path": "scan.md", "score": 0.77}]

                        result = hierarchical_search(
                            query="fallback query",
                            topic="work",
                            level=3,
                            semantic=False,
                            use_index=True,
                        )

        assert result["success"] is True
        assert result["l3_results"] == [{"path": "scan.md", "relevance": 77}]
        mock_l3.assert_called_once()

    def test_search_level3_fallback_results_do_not_get_default_relevance_50(self):
        """Fallback-only L3 results must not be inflated by ranking defaults.

        Phase 1 (#1): the default token-match relevance threshold is 0, so a
        weak fallback token-match is admitted rather than dropped by a nonzero
        ranking threshold. The guard this test locks is the absence of the
        legacy relevance-inflation default: a fallback without an explicit
        ``relevance`` must NOT be assigned 50 — it stays at its true value (0).
        """
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                mock_l2.return_value = {
                    "results": [],
                    "truncated": False,
                    "total_available": 0,
                }
                mock_l3.return_value = [
                    {
                        "path": "scan.md",
                        "title": "Weak fallback",
                        "title_match": False,
                        "body_matches": [{"line": 1, "context": "rat substring once"}],
                        "match_count": 1,
                        "source": "content_search",
                    }
                ]

                result = hierarchical_search(
                    query="rat",
                    level=3,
                    semantic=False,
                    use_index=False,
                )

        assert result["success"] is True
        merged = result["merged_results"]
        # Admitted under the default threshold=0, but NOT inflated to 50.
        assert len(merged) == 1
        assert merged[0]["relevance_score"] == 0

    def test_search_level3_truncated_propagation(self):
        """Level 3 should propagate truncated flag from metadata pipeline"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                    mock_l2.return_value = {
                        "results": [{"path": "test.md", "date": "2026-03-14"}],
                        "truncated": True,
                        "total_available": 50,
                    }
                    mock_l3.return_value = []
                    mock_rank.return_value = []

                    result = hierarchical_search(
                        query="test",
                        level=3,
                        semantic=False,
                        use_index=False,
                    )

        assert result["l2_truncated"] is True
        assert result["l2_total_available"] == 50

    def test_search_level3_no_query_keyword_only_merge(self):
        """Level 3 without query should skip L3 and use keyword-only merge"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                mock_l2.return_value = {
                    "results": [{"path": "meta.md", "date": "2026-03-14"}],
                    "truncated": False,
                    "total_available": 1,
                }
                mock_rank.return_value = [{"path": "meta.md", "score": 1.0}]

                result = hierarchical_search(level=3, semantic=False, use_index=False)

        assert result["success"] is True
        assert result["l3_results"] == []
        assert result["merged_results"] == [
            {"path": "meta.md", "score": 1.0, "title_promoted": False}
        ]

    def test_search_level3_keyword_pipeline_project_and_tags(self):
        """Level 3 keyword pipeline should query project and tag indexes"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l1_index") as mock_l1:
            with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
                with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                    with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                        mock_l1.side_effect = [
                            [{"path": "project.md", "date": "2026-03-14"}],
                            [{"path": "tag1.md", "date": "2026-03-14"}],
                            [{"path": "tag2.md", "date": "2026-03-14"}],
                        ]
                        mock_l2.return_value = {
                            "results": [],
                            "truncated": False,
                            "total_available": 0,
                        }
                        mock_l3.return_value = []
                        mock_rank.return_value = []

                        result = hierarchical_search(
                            query="test",
                            project="Life-Index",
                            tags=["python", "testing"],
                            level=3,
                            semantic=False,
                            use_index=False,
                        )

        assert result["success"] is True
        assert mock_l1.call_args_list[0].args == ("project", "Life-Index")
        assert mock_l1.call_args_list[1].args == ("tag", "python")
        assert mock_l1.call_args_list[2].args == ("tag", "testing")

    def test_search_level3_fts_single_keyword_keeps_original_query(self):
        """Single keyword query should be passed to FTS unchanged"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.core.merge_and_rank_results") as mock_rank:
                with patch("tools.lib.search_index.search_fts") as mock_fts:
                    mock_l2.return_value = {
                        "results": [],
                        "truncated": False,
                        "total_available": 0,
                    }
                    mock_fts.return_value = []
                    mock_rank.return_value = []

                    result = hierarchical_search(
                        query="python",
                        level=3,
                        semantic=False,
                        use_index=True,
                    )

        assert result["success"] is True
        assert mock_fts.call_args[0][0] == "python"


class TestSearchWarnings:
    """Tests for warnings field (Phase 2C)"""

    def test_search_returns_warnings_field(self):
        """搜索结果必须包含 warnings 字段"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                mock_l2.return_value = {
                    "results": [],
                    "truncated": False,
                    "total_available": 0,
                }
                mock_l3.return_value = []
                result = hierarchical_search(query="test", level=3)

        assert "warnings" in result
        assert isinstance(result["warnings"], list)

    def test_semantic_unavailable_produces_warning(self):
        """语义搜索不可用时，warnings 应包含原因"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                mock_l2.return_value = {
                    "results": [],
                    "truncated": False,
                    "total_available": 0,
                }
                mock_l3.return_value = []
                result = hierarchical_search(query="test", level=3, semantic=True, use_index=False)

        assert len(result["warnings"]) >= 1
        assert any("deprecated_noop" in w for w in result["warnings"])
        assert result["semantic_effective_policy"] == "deprecated_noop"

    def test_warnings_empty_when_all_pipelines_ok(self):
        """所有管道正常时，warnings 应为空列表"""
        from tools.lib.index_freshness import FreshnessReport
        from tools.search_journals.core import hierarchical_search

        # Mock freshness guard so real data staleness doesn't leak into warnings
        fresh_report = FreshnessReport(
            fts_fresh=True, vector_fresh=True, overall_fresh=True, issues=[]
        )

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                with patch(
                    "tools.lib.index_freshness.check_full_freshness",
                    return_value=fresh_report,
                ):
                    with patch(
                        "tools.lib.pending_writes.has_pending",
                        return_value=False,
                    ):
                        mock_l2.return_value = {
                            "results": [],
                            "truncated": False,
                            "total_available": 0,
                        }
                        mock_l3.return_value = []
                        result = hierarchical_search(query="test", level=3, use_index=False)

        assert result["warnings"] == []

    def test_semantic_default_off_no_warning(self):
        """v1.2: semantic defaults to False (per CHARTER §1.11).
        No warning needed — keyword-only is the honest default."""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.keyword_pipeline.search_l2_metadata") as mock_l2:
            with patch("tools.search_journals.keyword_pipeline.search_l3_content") as mock_l3:
                mock_l2.return_value = {
                    "results": [],
                    "truncated": False,
                    "total_available": 0,
                }
                mock_l3.return_value = []
                result = hierarchical_search(query="test", level=3, semantic=False, use_index=False)

        assert result["query_params"]["semantic"] is False
        assert "semantic_note" in result


class TestModuleImportFallback:
    """Tests for import-time fallbacks in core module"""

    def test_logger_import_fallback(self):
        """Module should fall back to stdlib logging when lib.logger import fails"""
        module_name = "tools.search_journals.core"
        package = importlib.import_module("tools.search_journals")
        original_module = sys.modules.get(module_name)
        had_parent_attr = hasattr(package, "core")
        original_package_attr = getattr(package, "core", None)
        sys.modules.pop(module_name, None)

        real_import = __import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name.endswith("lib.logger"):
                raise ImportError("logger unavailable")
            return real_import(name, globals, locals, fromlist, level)

        try:
            with patch("builtins.__import__", side_effect=fake_import):
                with patch("logging.getLogger") as mock_get_logger:
                    module = importlib.import_module(module_name)
                    assert module.logger is mock_get_logger.return_value
                    mock_get_logger.assert_called_with("search_journals")
        finally:
            sys.modules.pop(module_name, None)
            if original_module is not None:
                sys.modules[module_name] = original_module
            if had_parent_attr:
                setattr(package, "core", original_package_attr)
            elif hasattr(package, "core"):
                delattr(package, "core")

    def test_logger_fallback_restores_package_module_identity(self):
        """Later monkeypatches must resolve the same Core module that imports use."""
        package = importlib.import_module("tools.search_journals")
        module = importlib.import_module("tools.search_journals.core")

        assert package.core is module
        assert sys.modules["tools.search_journals.core"] is module


@pytest.mark.parametrize(
    ("parent_state", "module_state"),
    (
        ("absent", "present"),
        ("none", "present"),
        ("divergent", "present"),
        ("normal", "present"),
        ("none", "absent"),
        ("divergent", "absent"),
    ),
)
def test_logger_fallback_restores_parent_and_sys_modules_independently(
    monkeypatch: pytest.MonkeyPatch,
    parent_state: str,
    module_state: str,
) -> None:
    module_name = "tools.search_journals.core"
    package = importlib.import_module("tools.search_journals")
    module = importlib.import_module(module_name)
    divergent = object()

    if module_state == "present":
        monkeypatch.setitem(sys.modules, module_name, module)
    else:
        monkeypatch.delitem(sys.modules, module_name, raising=False)

    if parent_state == "absent":
        monkeypatch.delattr(package, "core", raising=False)
        expected_parent = None
        expected_parent_present = False
    elif parent_state == "none":
        monkeypatch.setattr(package, "core", None)
        expected_parent = None
        expected_parent_present = True
    elif parent_state == "divergent":
        monkeypatch.setattr(package, "core", divergent)
        expected_parent = divergent
        expected_parent_present = True
    else:
        monkeypatch.setattr(package, "core", module)
        expected_parent = module
        expected_parent_present = True

    TestModuleImportFallback().test_logger_import_fallback()

    assert hasattr(package, "core") is expected_parent_present
    if expected_parent_present:
        assert package.core is expected_parent
    assert (module_name in sys.modules) is (module_state == "present")
    if module_state == "present":
        assert sys.modules[module_name] is module


class TestSearchParams:
    """Tests for search parameters"""

    def test_query_params_recorded(self):
        """Query parameters are recorded in result"""
        from tools.search_journals.core import hierarchical_search

        with patch("tools.search_journals.core.search_l1_index") as mock_l1:
            mock_l1.return_value = []
            result = hierarchical_search(
                query="test",
                topic="work",
                project="Project",
                tags=["tag1"],
                date_from="2026-01-01",
                date_to="2026-12-31",
                level=2,
            )

        assert result["query_params"]["query"] == "test"
        assert result["query_params"]["topic"] == "work"
        assert result["query_params"]["project"] == "Project"
        assert result["query_params"]["level"] == 2


class TestStaleIndexRebuildCorrective:
    """M4 Search Phase 1 corrective: structured rebuild failures stay unfresh."""

    @pytest.fixture(autouse=True)
    def _isolate_data_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(tmp_path))

    def _stale_report(self):
        return FreshnessReport(
            fts_fresh=False,
            vector_fresh=True,
            overall_fresh=False,
            issues=["fts_index_older_than_corpus"],
        )

    def test_stale_rebuild_locktimeout_result_keeps_auto_updated_false(self):
        """A LockTimeout-style structured failure must not claim auto_updated."""
        from tools.lib.errors import ErrorCode, create_error_response
        from tools.search_journals.core import hierarchical_search

        lock_timeout = create_error_response(
            ErrorCode.LOCK_TIMEOUT,
            "无法获取索引锁，请稍后重试",
            {"lock_path": "C:/tmp/index.lock", "timeout": 30},
        )
        with (
            patch("tools.lib.pending_writes.has_pending", return_value=False),
            patch(
                "tools.lib.index_freshness.check_full_freshness",
                return_value=self._stale_report(),
            ),
            patch("tools.build_index.build_all", return_value=lock_timeout),
        ):
            result = hierarchical_search(query="staletoken", level=3, use_index=False)

        assert (
            result["index_status"]["auto_updated"] is False
        ), "a structured success=false rebuild result must not set auto_updated=true"
        assert (
            "index_update_failed: E0005" in result["warnings"]
        ), "the warning must be stable, keyed by the structured error code"

    def test_stale_rebuild_structured_failure_without_error_code(self):
        """A nested fts-error failure is treated identically (no auto_updated)."""
        from tools.search_journals.core import hierarchical_search

        with (
            patch("tools.lib.pending_writes.has_pending", return_value=False),
            patch(
                "tools.lib.index_freshness.check_full_freshness",
                return_value=self._stale_report(),
            ),
            patch(
                "tools.build_index.build_all",
                return_value={"success": False, "fts": {"success": False, "error": "disk full"}},
            ),
        ):
            result = hierarchical_search(query="staletoken", level=3, use_index=False)

        assert result["index_status"]["auto_updated"] is False
        assert any(
            str(w).startswith("index_update_failed:") for w in result["warnings"]
        ), "a stable index_update_failed warning must be recorded"

    def test_stale_rebuild_success_still_sets_auto_updated_true(self):
        """A genuinely successful rebuild keeps the self-healed fast path."""
        from tools.search_journals.core import hierarchical_search

        with (
            patch("tools.lib.pending_writes.has_pending", return_value=False),
            patch(
                "tools.lib.index_freshness.check_full_freshness",
                return_value=self._stale_report(),
            ),
            patch(
                "tools.build_index.build_all",
                return_value={"success": True, "fts": {"success": True}},
            ),
        ):
            result = hierarchical_search(query="staletoken", level=3, use_index=False)

        assert result["index_status"]["auto_updated"] is True
        assert not any(str(w).startswith("index_update_failed:") for w in result["warnings"])

    def test_stale_rebuild_exception_path_stays_fail_safe(self):
        """A raising rebuild keeps the existing fail-safe behavior."""
        from tools.search_journals.core import hierarchical_search

        with (
            patch("tools.lib.pending_writes.has_pending", return_value=False),
            patch(
                "tools.lib.index_freshness.check_full_freshness",
                return_value=self._stale_report(),
            ),
            patch("tools.build_index.build_all", side_effect=RuntimeError("update failed")),
        ):
            result = hierarchical_search(query="staletoken", level=3, use_index=False)

        assert result["index_status"]["auto_updated"] is False
        assert result["success"] is True, "the retrieval itself still proceeds fail-safe"


class TestMinRelevanceZeroDefault:
    """M4 Search Phase 1: min_relevance=0 is the recall-first default, by design."""

    def test_hierarchical_search_defaults_to_zero_min_relevance(self):
        """The public search entry point defaults fts_min_relevance to 0."""
        import inspect

        from tools.search_journals.core import hierarchical_search

        assert inspect.signature(hierarchical_search).parameters["fts_min_relevance"].default == 0

    def test_zero_min_relevance_bypasses_high_frequency_dynamic_threshold(self):
        """An explicit 0 override bypasses the legacy high-frequency threshold."""
        from tools.lib.fts_search import _effective_min_relevance
        from tools.lib.search_constants import FTS_MIN_RELEVANCE

        assert _effective_min_relevance("Life Index 2026", 0) == 0
        assert (
            _effective_min_relevance("Life Index 2026", FTS_MIN_RELEVANCE) > FTS_MIN_RELEVANCE
        ), "the legacy default still raises the threshold for high-frequency terms"

    def test_keyword_pipeline_passes_zero_min_relevance_to_fts(self, tmp_path, monkeypatch):
        """The default search path retrieves with min_relevance=0 and no SQL cap."""
        from tools.search_journals.core import hierarchical_search

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(tmp_path))
        with (
            patch(
                "tools.search_journals.keyword_pipeline.search_l2_metadata",
                return_value={"results": [], "truncated": False, "total_available": 0},
            ),
            patch("tools.lib.search_index.search_fts", return_value=[]) as mock_fts,
            patch("tools.search_journals.core.merge_and_rank_results", return_value=[]),
        ):
            hierarchical_search(query="python testing", level=3, use_index=True, emit_metrics=False)

        assert mock_fts.call_args.kwargs["min_relevance"] == 0
        assert mock_fts.call_args.kwargs["limit"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
