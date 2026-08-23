#!/usr/bin/env python3
"""Contract tests: smart-search response shape.

Verifies that SmartSearchOrchestrator output conforms to the contract
documented in docs/API.md:
1. Default output contains public stable fields
2. --include-evidence adds evidence_pack
3. --synthesize remains a deterministic no-op/no-answer compatibility path
4. Combined flags add evidence without adding an answer path
5. --explain swaps agent_decisions_summary for agent_decisions
6. Performance sub-fields are conditionally present
7. evidence_pack.diagnostics present and well-formed when --include-evidence
"""

import json
from unittest.mock import MagicMock, patch

from tools.search_journals.orchestrator import SmartSearchOrchestrator


def _mock_hierarchical_search(query="", **kwargs):
    """Mock deterministic search returning minimal valid output."""
    return {
        "success": True,
        "merged_results": [
            {
                "title": "Test Journal Entry",
                "path": "Journals/2026/03/life-index_2026-03-06_001.md",
                "rel_path": "Journals/2026/03/life-index_2026-03-06_001.md",
                "date": "2026-03-06",
                "rrf_score": 0.85,
                "abstract": "A test abstract about memories.",
                "snippet": "Test snippet content.",
            }
        ],
        "total_found": 1,
        "total_available": 1,
        "performance": {"total_time_ms": 10.0},
    }


def _mock_semantic_noop_search(query="", **kwargs):
    """Mock deterministic search where deprecated semantic flags were requested."""
    result = _mock_hierarchical_search(query=query, **kwargs)
    result["semantic_fallback_used"] = False
    result["semantic_effective_policy"] = "deprecated_noop"
    return result


def _mock_multi_query_search(query="", **kwargs):
    """Mock deterministic search returning one distinct result per query."""
    return {
        "success": True,
        "merged_results": [
            {
                "title": f"Entry for {query}",
                "path": f"Journals/2026/03/{query}.md",
                "rel_path": f"Journals/2026/03/{query}.md",
                "date": "2026-03-06",
                "rrf_score": 0.85,
                "abstract": f"Abstract for {query}",
                "snippet": f"Snippet for {query}",
            }
        ],
        "total_found": 1,
        "total_available": 1,
        "performance": {"total_time_ms": 10.0},
        "semantic_fallback_used": False,
    }


def _mock_recording_search(calls):
    """Build a search mock that records query/kwargs for contract assertions."""

    def _search(query="", **kwargs):
        calls.append({"query": query, "kwargs": kwargs})
        return _mock_multi_query_search(query=query, **kwargs)

    return _search


def _mock_short_keyword_zero(calls):
    """Record calls and simulate a short-keyword zero-result path."""

    def _search(query="", **kwargs):
        calls.append({"query": query, "kwargs": kwargs})
        if query == "睡得":
            return {
                "success": True,
                "merged_results": [],
                "total_found": 0,
                "total_available": 0,
                "performance": {"total_time_ms": 10.0},
                "semantic_fallback_used": False,
                "warnings": ["noise_gate: semantic bypassed for '睡得' (too_short)"],
            }

        return _mock_hierarchical_search(query=query, **kwargs)

    return _search


# Default output shape


class TestDefaultOutputShape:
    """Verify default (no flags) output contains exactly the public stable fields."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_has_required_fields(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")

        # Public stable fields
        assert "success" in result
        assert "query" in result
        assert "rewritten_query" in result
        assert "filtered_results" in result
        assert "summary" in result
        assert "citations" in result
        assert "agent_unavailable" in result
        assert "performance" in result

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_no_evidence_pack(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert "evidence_pack" not in result

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_no_answer(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert "answer" not in result

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_semantic_noop_search,
    )
    def test_semantic_noop_status_is_propagated(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert result["semantic_fallback_used"] is False

    def test_deterministic_scaffold_uses_keyword_search(self):
        calls = []
        with patch(
            "tools.search_journals.orchestrator._get_search_fn",
            return_value=_mock_recording_search(calls),
        ):
            orch = SmartSearchOrchestrator()
            result = orch.search("投资")

        assert calls
        assert calls[0]["query"] == "投资"
        assert "semantic" not in calls[0]["kwargs"]
        assert "semantic_policy" not in calls[0]["kwargs"]
        assert result["query_plan"]["strategy"] == "keyword_only"

    def test_natural_language_query_uses_extracted_keyword_sub_queries(self):
        calls = []
        with patch(
            "tools.search_journals.orchestrator._get_search_fn",
            return_value=_mock_recording_search(calls),
        ):
            orch = SmartSearchOrchestrator()
            result = orch.search("晚睡熬夜作息")

        assert [call["query"] for call in calls] == ["晚睡", "熬夜", "作息"]
        assert result["query_plan"]["sub_queries"] == ["晚睡", "熬夜", "作息"]
        assert result["query_plan"]["strategy"] == "keyword_multi_pass"

    def test_multi_query_scaffold_keeps_evidence_pack_shape(self):
        calls = []
        with patch(
            "tools.search_journals.orchestrator._get_search_fn",
            return_value=_mock_recording_search(calls),
        ):
            orch = SmartSearchOrchestrator()
            result = orch.search("晚睡熬夜作息", include_evidence=True)

        assert "evidence_pack" in result
        assert result["evidence_pack"]["query_context"]["query"] == "晚睡熬夜作息"
        assert len(result["evidence_pack"]["items"]) == 3

    def test_short_keyword_natural_language_does_not_retry_raw_semantic_fallback(self):
        calls = []
        with patch(
            "tools.search_journals.orchestrator._get_search_fn",
            return_value=_mock_short_keyword_zero(calls),
        ):
            orch = SmartSearchOrchestrator()
            result = orch.search("最近睡得怎么样")

        assert [call["query"] for call in calls] == ["睡得"]
        assert result["filtered_results"] == []
        assert result["semantic_fallback_used"] is False
        assert result["query_plan"]["sub_queries"] == ["睡得"]
        assert "semantic_fallback_query" not in result["query_plan"]
        assert result["query_plan"]["strategy"] == "keyword_temporal"

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_has_agent_decisions_list(self, _mock):
        """Default orchestrator output includes agent_decisions list."""
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert "agent_decisions" in result
        assert isinstance(result["agent_decisions"], list)

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_no_agent_decisions_summary(self, _mock):
        """Orchestrator does NOT produce agent_decisions_summary; CLI layer does."""
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert "agent_decisions_summary" not in result

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_degradation_mode_agent_unavailable(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert result["agent_unavailable"] is True

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_output_includes_agent_ready_scaffold(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("我和女儿之间有哪些珍贵回忆")

        assert result["agent_unavailable"] is True
        assert result["smart_search_mode"] == "deterministic_scaffold"
        assert result["agent_instructions"]["role"] == "calling_agent"
        assert (
            "Use filtered_results as bounded evidence" in result["agent_instructions"]["steps"][0]
        )
        assert result["answer_scaffold"]["query"] == "我和女儿之间有哪些珍贵回忆"
        assert result["answer_scaffold"]["citation_policy"] == "cite_only_returned_results"

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_no_stale_fields(self, _mock):
        """Fields documented as not existing must not appear."""
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert "results" not in result
        assert "total_found" not in result
        assert "mode" not in result

    def test_aggregate_intent_adds_aggregate_result(self, monkeypatch):
        """Clear aggregate intents add aggregate_result without fabricating answer."""
        monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-13")
        orch = SmartSearchOrchestrator()
        result = orch.search("过去60天我有多少天晚睡")
        assert "aggregate_result" in result
        assert result["aggregate_result"]["command"] == "aggregate"
        assert result["aggregate_result"]["predicate"]["type"] == "entry_time_after"
        assert result["aggregate_result"]["range"] == {
            "since": "2026-03-15",
            "until": "2026-05-13",
        }
        assert "answer" not in result
        assert "filtered_results" in result

    def test_past_days_journal_entries_route_to_aggregate_entry_count(self, monkeypatch):
        """Past-N-day journal entry count questions route to aggregate journal_count."""
        monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-15")
        orch = SmartSearchOrchestrator()
        result = orch.search("过去90天有多少篇日志")
        assert "aggregate_result" in result
        aggregate = result["aggregate_result"]
        assert aggregate["command"] == "aggregate"
        assert aggregate["predicate"]["type"] == "journal_count"
        assert aggregate["unit"] == "entry"
        assert aggregate["range"] == {
            "since": "2026-02-15",
            "until": "2026-05-15",
        }

    def test_past_days_journal_days_route_to_aggregate_day_count(self, monkeypatch):
        """Past-N-day journal day count questions route to aggregate journal_count."""
        monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-15")
        orch = SmartSearchOrchestrator()
        result = orch.search("过去90天有多少天写日志")
        assert "aggregate_result" in result
        aggregate = result["aggregate_result"]
        assert aggregate["predicate"]["type"] == "journal_count"
        assert aggregate["unit"] == "day"
        assert aggregate["range"] == {
            "since": "2026-02-15",
            "until": "2026-05-15",
        }

    def test_past_days_journal_entries_english_route_to_aggregate(self, monkeypatch):
        """English past-N-day journal entry count questions route deterministically."""
        monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-15")
        orch = SmartSearchOrchestrator()
        result = orch.search("past 30 days how many journal entries")
        assert "aggregate_result" in result
        aggregate = result["aggregate_result"]
        assert aggregate["predicate"]["type"] == "journal_count"
        assert aggregate["unit"] == "entry"
        assert aggregate["range"] == {
            "since": "2026-04-16",
            "until": "2026-05-15",
        }

    def test_explicit_field_equals_route_to_aggregate(self, monkeypatch):
        """Explicit frontmatter field filters route to aggregate field_equals."""
        monkeypatch.setenv("LIFE_INDEX_TIME_ANCHOR", "2026-05-15")
        orch = SmartSearchOrchestrator()
        result = orch.search("过去60天有多少篇 topic=work 的日志")
        assert "aggregate_result" in result
        aggregate = result["aggregate_result"]
        assert aggregate["predicate"]["type"] == "field_equals"
        assert aggregate["predicate"]["field"] == "topic"
        assert aggregate["predicate"]["value"] == "work"
        assert aggregate["unit"] == "entry"
        assert aggregate["range"] == {
            "since": "2026-03-17",
            "until": "2026-05-15",
        }


# Performance sub-fields


class TestPerformanceFields:
    """Verify performance sub-fields are conditionally present."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_always_present_fields(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        perf = result["performance"]
        assert "total_time_ms" in perf
        assert "search_time_ms" in perf
        assert "total_available" in perf

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_synthesize_noop_adds_no_synthesis_ms(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query", synthesize=True)
        perf = result["performance"]
        assert "synthesis_ms" not in perf


# --include-evidence output shape


class TestIncludeEvidenceShape:
    """Verify --include-evidence adds evidence_pack."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_evidence_pack_present(self, mock_ev, _mock):
        from tools.evidence.types import (
            DocumentRef,
            EvidenceItem,
            EvidencePack,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(query="test"),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1),
                    snippet="test snippet",
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        assert "evidence_pack" in result
        assert "items" in result["evidence_pack"]
        assert "performance" in result
        assert "evidence_build_ms" in result["performance"]

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch(
        "tools.evidence.adapter.extract_evidence_from_orchestrator",
        side_effect=Exception("build failed"),
    )
    def test_evidence_failure_still_succeeds(self, mock_ev, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        assert result["success"] is True
        assert "evidence_pack" not in result
        assert "evidence_build_ms" in result["performance"]
        assert "evidence_error" in result["performance"]


# --synthesize output shape


class TestSynthesizeShape:
    """Verify --synthesize remains a deterministic no-answer path."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_answer_no_llm(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query", synthesize=True)
        assert "answer" not in result


# Combined flags


class TestCombinedFlags:
    """Verify --include-evidence --synthesize keeps deterministic evidence."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_combined_has_both(self, mock_ev, _mock):
        from tools.evidence.types import (
            DocumentRef,
            EvidenceItem,
            EvidencePack,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(query="test"),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1, confidence="medium"),
                    snippet="test snippet",
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True, synthesize=True)

        assert "evidence_pack" in result
        assert "answer" not in result
        assert "synthesis_ms" not in result["performance"]
        assert "evidence_build_ms" in result["performance"]


# CLI --explain shape


# Phase 2A: top-level retrieval_coverage + public continuation parameter


class TestRetrievalCoverageContract:
    """Phase 2A: smart-search carries a top-level retrieval_coverage authority."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_default_output_carries_top_level_retrieval_coverage(self, _mock):
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")

        coverage = result["retrieval_coverage"]
        assert coverage["schema_version"] == "retrieval_coverage.v1"
        assert coverage["status"] in {"complete", "partial"}
        assert isinstance(coverage["observed_total"], int)
        assert isinstance(coverage["returned"], int)
        assert coverage["next_offset"] is None or isinstance(coverage["next_offset"], int)
        assert isinstance(coverage["partial_reasons"], list)
        assert isinstance(coverage["limits_applied"], list)

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_coverage_is_additive_to_stable_fields(self, _mock):
        """retrieval_coverage is added without replacing any stable field."""
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")

        for field in (
            "success",
            "query",
            "rewritten_query",
            "filtered_results",
            "summary",
            "citations",
            "agent_unavailable",
            "performance",
            "smart_search_mode",
            "agent_instructions",
            "answer_scaffold",
            "query_plan",
        ):
            assert field in result, f"Missing stable field: {field}"
        assert "retrieval_coverage" in result
        # No compatibility totals leak to the smart-search top level.
        assert "total_found" not in result

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_legacy_projection_input_degrades_conservatively_to_partial(self, _mock):
        """A child without coverage authority can never prove completeness.

        Revision 4 closed vocabulary: the fail-closed reason is the existing
        ``child_failed`` — no invented reason (e.g. coverage_authority_missing)
        is published.
        """
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")

        coverage = result["retrieval_coverage"]
        assert coverage["status"] == "partial"
        assert "child_failed" in coverage["partial_reasons"]
        assert all(
            reason
            in {
                "unread_page",
                "source_cap",
                "threshold_excluded",
                "child_failed",
                "index_not_fresh",
            }
            for reason in coverage["partial_reasons"]
        )


class TestContinuationOffsetCliContract:
    """--offset is the public CLI continuation parameter."""

    def _run_cli(self, argv):
        from io import StringIO

        captured = StringIO()
        with patch("sys.argv", ["smart-search", *argv]):
            with patch("tools.search_journals.orchestrator.SmartSearchOrchestrator") as MockCls:
                mock_orch = MagicMock()
                mock_orch.search.return_value = {
                    "success": True,
                    "query": "test",
                    "rewritten_query": "test",
                    "filtered_results": [],
                    "summary": "",
                    "citations": [],
                    "agent_decisions": [],
                    "agent_unavailable": True,
                    "performance": {"total_time_ms": 10},
                }
                MockCls.return_value = mock_orch
                with patch(
                    "builtins.print",
                    side_effect=lambda *a, **kw: captured.write(str(a[0])) if a else None,
                ):
                    from tools.smart_search.__main__ import main

                    try:
                        main()
                    except SystemExit as exc:
                        exit_code = exc.code
                    else:
                        exit_code = 0
        return mock_orch, exit_code

    def test_offset_flag_forwarded_to_public_search_entry(self):
        mock_orch, exit_code = self._run_cli(["--query", "test", "--offset", "15"])
        assert exit_code == 0
        assert mock_orch.search.call_args.kwargs.get("offset") == 15

    def test_no_offset_keeps_documented_call_shape(self):
        """Without --offset the CLI call shape stays byte-compatible."""
        mock_orch, exit_code = self._run_cli(["--query", "test"])
        assert exit_code == 0
        assert mock_orch.search.call_args.kwargs.get("offset") is None
        assert mock_orch.search.call_args.kwargs.get("include_evidence") is False
        assert mock_orch.search.call_args.kwargs.get("synthesize") is False

    def test_negative_offset_is_rejected(self):
        mock_orch, exit_code = self._run_cli(["--query", "test", "--offset", "-1"])
        assert exit_code == 2
        mock_orch.search.assert_not_called()

    def test_non_integer_offset_is_rejected(self):
        mock_orch, exit_code = self._run_cli(["--query", "test", "--offset", "abc"])
        assert exit_code == 2
        mock_orch.search.assert_not_called()


class TestExplainFlag:
    """Verify --explain output shape at CLI level."""

    def test_explain_keeps_agent_decisions(self):
        """With --explain, agent_decisions list is kept (not replaced by summary)."""
        from io import StringIO

        mock_result = {
            "success": True,
            "query": "test",
            "rewritten_query": "test",
            "filtered_results": [],
            "summary": "",
            "citations": [],
            "agent_decisions": [
                {"stage": "rewrite", "input_summary": "q", "output_summary": "r", "latency_ms": 10}
            ],
            "agent_unavailable": True,
            "performance": {"total_time_ms": 10},
        }

        captured = StringIO()
        with patch("sys.argv", ["smart-search", "--query", "test", "--explain"]):
            with patch("tools.search_journals.orchestrator.SmartSearchOrchestrator") as MockCls:
                mock_orch = MagicMock()
                mock_orch.search.return_value = mock_result.copy()
                MockCls.return_value = mock_orch
                with patch(
                    "builtins.print",
                    side_effect=lambda *a, **kw: captured.write(str(a[0])) if a else None,
                ):
                    from tools.smart_search.__main__ import main

                    try:
                        main()
                    except SystemExit:
                        pass

        result = json.loads(captured.getvalue())
        assert "agent_decisions" in result
        assert isinstance(result["agent_decisions"], list)
        assert "agent_decisions_summary" not in result

    def test_no_explain_replaces_with_summary(self):
        """Without --explain, agent_decisions is replaced by agent_decisions_summary."""
        from io import StringIO

        mock_result = {
            "success": True,
            "query": "test",
            "rewritten_query": "test",
            "filtered_results": [],
            "summary": "",
            "citations": [],
            "agent_decisions": [
                {"stage": "rewrite", "input_summary": "q", "output_summary": "r", "latency_ms": 10}
            ],
            "agent_unavailable": True,
            "performance": {"total_time_ms": 10},
        }

        captured = StringIO()
        with patch("sys.argv", ["smart-search", "--query", "test"]):
            with patch("tools.search_journals.orchestrator.SmartSearchOrchestrator") as MockCls:
                mock_orch = MagicMock()
                mock_orch.search.return_value = mock_result.copy()
                MockCls.return_value = mock_orch
                with patch(
                    "builtins.print",
                    side_effect=lambda *a, **kw: captured.write(str(a[0])) if a else None,
                ):
                    from tools.smart_search.__main__ import main

                    try:
                        main()
                    except SystemExit:
                        pass

        result = json.loads(captured.getvalue())
        assert "agent_decisions" not in result
        assert "agent_decisions_summary" in result
        assert isinstance(result["agent_decisions_summary"], str)


# Evidence Pack Diagnostics


class TestEvidencePackDiagnostics:
    """Verify evidence_pack.diagnostics contract when --include-evidence."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_diagnostics_ok_outcome_omits_empty_notes(self, mock_ev, _mock):
        """``ok`` outcome produces empty notes/suggestions — serializer omits them."""
        from tools.evidence.types import (
            DocumentRef,
            EvidenceDiagnostics,
            EvidenceItem,
            EvidencePack,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(query="test"),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1, confidence="medium"),
                    snippet="test snippet",
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
            diagnostics=EvidenceDiagnostics(
                retrieval_outcome="ok",
                outcome_reason="confident_results_present",
            ),
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        assert "evidence_pack" in result
        diag = result["evidence_pack"]["diagnostics"]
        assert "retrieval_outcome" in diag
        assert diag["retrieval_outcome"] == "ok"
        assert "outcome_reason" in diag
        assert "notes" not in diag
        assert "suggestions" not in diag

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_diagnostics_has_required_fields(self, mock_ev, _mock):
        """When notes/suggestions are non-empty, serializer includes them."""
        from tools.evidence.types import (
            DocumentRef,
            EvidenceDiagnostics,
            EvidenceItem,
            EvidencePack,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(query="test"),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1, confidence="high"),
                    snippet="test snippet",
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
            diagnostics=EvidenceDiagnostics(
                retrieval_outcome="ok",
                outcome_reason="confident_results_present",
                notes=["High-confidence result found."],
                suggestions=["Results look good."],
            ),
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        diag = result["evidence_pack"]["diagnostics"]
        assert "retrieval_outcome" in diag
        assert diag["retrieval_outcome"] in (
            "ok",
            "weak_results",
            "no_confident_match",
            "zero_results",
        )
        assert "outcome_reason" in diag
        assert "notes" in diag
        assert isinstance(diag["notes"], list)
        assert "suggestions" in diag
        assert isinstance(diag["suggestions"], list)

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    def test_no_diagnostics_without_evidence(self, _mock):
        """Without --include-evidence, no evidence_pack and no diagnostics."""
        orch = SmartSearchOrchestrator()
        result = orch.search("test query")
        assert "evidence_pack" not in result

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_diagnostics_includes_pipeline_composition(self, mock_ev, _mock):
        """Evidence pack diagnostics includes additive pipeline_composition field.

        Asserts the additive contract: pipeline_composition is present alongside
        all other standard diagnostic fields without replacing or omitting them.
        """
        from tools.evidence.types import (
            DocumentRef,
            EvidenceDiagnostics,
            EvidenceItem,
            EvidencePack,
            PipelineComposition,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(query="test"),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1, confidence="high"),
                    snippet="test snippet",
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
            diagnostics=EvidenceDiagnostics(
                retrieval_outcome="ok",
                outcome_reason="confident_results_present",
                pipeline_composition=PipelineComposition(primary_pipeline="fts"),
            ),
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        assert "evidence_pack" in result
        diag = result["evidence_pack"]["diagnostics"]

        # Additive contract: pipeline_composition is present
        assert "pipeline_composition" in diag
        assert diag["pipeline_composition"]["primary_pipeline"] in (
            "none",
            "fts",
            "semantic",
            "hybrid",
        )

        # Additive contract: all other standard fields remain intact
        assert "retrieval_outcome" in diag
        assert diag["retrieval_outcome"] == "ok"
        assert "outcome_reason" in diag
        assert diag["outcome_reason"] == "confident_results_present"
        # notes/suggestions are empty for ok outcome → serializer omits them
        assert "notes" not in diag
        assert "suggestions" not in diag


# S1-C: Entity Match Enrichment


class TestEntityMatchEnrichmentContract:
    """Verify entity_matches in evidence_pack.items[] is additive when included."""

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_entity_matches_additive_in_items(self, mock_ev, _mock):
        """evidence_pack.items[].entity_matches is present alongside all other fields."""
        from tools.evidence.types import (
            DocumentRef,
            EntityMatch,
            EvidenceItem,
            EvidencePack,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(
                query="test",
                entity_hints=[
                    {"matched_term": "Test", "entity_id": "test_entity", "entity_type": "concept"},
                ],
            ),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test Journal Entry",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1, confidence="high"),
                    snippet="Test snippet content.",
                    entity_matches=[
                        EntityMatch(
                            entity_id="test_entity",
                            entity_type="concept",
                            matched_terms=["Test"],
                            match_sources=["snippet"],
                            query_matched_term="Test",
                        ),
                    ],
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        assert "evidence_pack" in result
        items = result["evidence_pack"]["items"]
        assert len(items) == 1

        # Additive: entity_matches is present
        assert "entity_matches" in items[0]
        em = items[0]["entity_matches"]
        assert len(em) == 1
        assert em[0]["entity_id"] == "test_entity"
        assert em[0]["entity_type"] == "concept"
        assert "Test" in em[0]["matched_terms"]
        assert "snippet" in em[0]["match_sources"]
        assert em[0]["query_matched_term"] == "Test"

        # Additive: all other standard item fields remain intact
        assert "document" in items[0]
        assert "scores" in items[0]
        assert "snippet" in items[0]
        assert "provenance" in items[0]

    @patch(
        "tools.search_journals.orchestrator._get_search_fn",
        return_value=_mock_hierarchical_search,
    )
    @patch("tools.evidence.adapter.extract_evidence_from_orchestrator")
    def test_empty_entity_matches_omitted(self, mock_ev, _mock):
        """Items without entity_matches omit the field from serialized output."""
        from tools.evidence.types import (
            DocumentRef,
            EvidenceItem,
            EvidencePack,
            QueryContext,
            ScoreBreakdown,
        )

        pack = EvidencePack(
            query_context=QueryContext(query="test"),
            items=[
                EvidenceItem(
                    document=DocumentRef(
                        doc_id="1",
                        title="Test",
                        path="Journals/2026/03/test.md",
                        date="2026-03-06",
                    ),
                    scores=ScoreBreakdown(source="fts", rank=1, confidence="medium"),
                    snippet="test snippet",
                    entity_matches=[],
                )
            ],
            semantic_candidates=[],
            total_available=1,
            has_more=False,
            no_confident_match=False,
        )
        mock_ev.return_value = pack

        orch = SmartSearchOrchestrator()
        result = orch.search("test query", include_evidence=True)

        items = result["evidence_pack"]["items"]
        assert "entity_matches" not in items[0]
