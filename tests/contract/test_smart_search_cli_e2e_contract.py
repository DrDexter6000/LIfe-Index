#!/usr/bin/env python3
"""CLI-level E2E contract tests for `python -m tools.smart_search`.

These tests invoke the smart-search CLI as a real subprocess.  The subprocess
results are session-scoped because the first isolated-data run builds an empty
index and costs several seconds on Windows.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNTHESIZE_DEPRECATION_WARNING = (
    "DEPRECATED: --synthesize is a compatibility no-op; synthesis belongs to the "
    "Host Agent + Life Index Skill."
)


def _run_smart_search(
    *extra_args: str,
    data_dir: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """Run smart-search CLI as a subprocess with an isolated data dir.

    On timeout the child process is killed before re-raising so that
    stale ``index.lock`` files are not left behind on Windows.
    """
    env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "tools.smart_search", *extra_args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO_ROOT),
        env=env,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(
            args=proc.args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise


def _json(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    """Parse JSON stdout from a smart-search subprocess result."""
    payload = json.loads(proc.stdout)
    assert isinstance(payload, dict)
    return payload


@pytest.fixture(scope="session")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a process-isolated empty Life Index data directory."""
    data_dir = tmp_path_factory.mktemp("life-index-r2f") / "Life-Index"
    (data_dir / "Journals").mkdir(parents=True, exist_ok=True)
    (data_dir / ".index").mkdir(parents=True, exist_ok=True)
    (data_dir / ".cache").mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture(scope="session")
def default_proc(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return _run_smart_search("--query", "test", data_dir=sandbox)


@pytest.fixture(scope="session")
def evidence_proc(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return _run_smart_search(
        "--query",
        "test",
        "--include-evidence",
        data_dir=sandbox,
    )


@pytest.fixture(scope="session")
def synthesize_proc(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return _run_smart_search("--query", "test", "--synthesize", data_dir=sandbox)


@pytest.fixture(scope="session")
def combined_proc(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return _run_smart_search(
        "--query",
        "test",
        "--include-evidence",
        "--synthesize",
        data_dir=sandbox,
    )


@pytest.fixture(scope="session")
def explain_proc(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return _run_smart_search("--query", "test", "--explain", data_dir=sandbox)


@pytest.fixture(scope="session")
def help_proc(sandbox: Path) -> subprocess.CompletedProcess[str]:
    return _run_smart_search("--help", data_dir=sandbox)


class TestDefaultOutputContract:
    """Default output has the stable public shape."""

    def test_exit_code_zero(self, default_proc: subprocess.CompletedProcess[str]) -> None:
        assert default_proc.returncode == 0, f"stderr: {default_proc.stderr}"

    def test_stdout_is_valid_json(self, default_proc: subprocess.CompletedProcess[str]) -> None:
        assert isinstance(_json(default_proc), dict)

    def test_no_unhandled_traceback(self, default_proc: subprocess.CompletedProcess[str]) -> None:
        assert default_proc.returncode == 0

    def test_stable_fields_present(self, default_proc: subprocess.CompletedProcess[str]) -> None:
        result = _json(default_proc)
        for field in (
            "success",
            "query",
            "rewritten_query",
            "filtered_results",
            "summary",
            "citations",
            "agent_unavailable",
            "agent_decisions_summary",
            "performance",
        ):
            assert field in result, f"Missing stable field: {field}"

    def test_internal_fields_absent_by_default(
        self, default_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(default_proc)
        assert "evidence_pack" not in result
        assert "answer" not in result
        assert "agent_decisions" not in result

    def test_agent_decisions_summary_present(
        self, default_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(default_proc)
        assert "agent_decisions_summary" in result
        assert isinstance(result["agent_decisions_summary"], str)

    def test_deterministic_stage_timings_are_always_zero(
        self, default_proc: subprocess.CompletedProcess[str]
    ) -> None:
        performance = _json(default_proc)["performance"]
        assert performance["rewrite_time_ms"] == 0
        assert performance["filter_time_ms"] == 0


class TestIncludeEvidenceContract:
    """--include-evidence output contract."""

    def test_success_with_evidence_flag(
        self, evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        assert evidence_proc.returncode == 0, f"stderr: {evidence_proc.stderr}"
        assert _json(evidence_proc)["success"] is True

    def test_evidence_build_ms_in_performance(
        self, evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(evidence_proc)
        assert "performance" in result
        assert "evidence_build_ms" in result["performance"]

    def test_evidence_pack_may_be_absent_in_empty_dir(
        self, evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(evidence_proc)
        assert result["success"] is True


class TestSynthesizeNoLlmContract:
    """--synthesize without in-tool LLM: no answer, agent_unavailable true."""

    def test_success_without_answer(
        self, synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        assert synthesize_proc.returncode == 0, f"stderr: {synthesize_proc.stderr}"
        result = _json(synthesize_proc)
        assert result["success"] is True
        assert "answer" not in result

    def test_agent_unavailable_true(
        self, synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        assert _json(synthesize_proc)["agent_unavailable"] is True

    def test_no_evidence_or_synthesis_timing(
        self, synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        performance = _json(synthesize_proc)["performance"]
        assert "evidence_build_ms" not in performance
        assert "synthesis_ms" not in performance

    def test_synthesize_flag_emits_deprecation_warning_and_preserves_domain_output_equivalence(
        self,
        default_proc: subprocess.CompletedProcess[str],
        synthesize_proc: subprocess.CompletedProcess[str],
    ) -> None:
        ordinary = _json(default_proc)
        synthesized = _json(synthesize_proc)
        ordinary_domain = {key: value for key, value in ordinary.items() if key != "performance"}
        synthesized_domain = {
            key: value for key, value in synthesized.items() if key != "performance"
        }

        assert ordinary_domain == synthesized_domain
        assert "answer" not in synthesized
        assert synthesize_proc.stderr.splitlines().count(SYNTHESIZE_DEPRECATION_WARNING) == 1


class TestCombinedEvidenceSynthesizeNoLlmContract:
    """Combined flags do not produce answer; evidence performance stays stable."""

    def test_combined_no_answer(self, combined_proc: subprocess.CompletedProcess[str]) -> None:
        assert combined_proc.returncode == 0, f"stderr: {combined_proc.stderr}"
        result = _json(combined_proc)
        assert result["success"] is True
        assert "answer" not in result

    def test_combined_evidence_build_ms(
        self, combined_proc: subprocess.CompletedProcess[str]
    ) -> None:
        performance = _json(combined_proc)["performance"]
        assert "evidence_build_ms" in performance
        assert "synthesis_ms" not in performance

    def test_combined_synthesize_warns_once_and_preserves_evidence_domain_output(
        self,
        default_proc: subprocess.CompletedProcess[str],
        evidence_proc: subprocess.CompletedProcess[str],
        combined_proc: subprocess.CompletedProcess[str],
    ) -> None:
        assert default_proc.returncode == 0, default_proc.stderr

        def domain_payload(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
            payload = json.loads(json.dumps(_json(proc)))
            assert isinstance(payload, dict)
            payload.pop("performance", None)
            query_context = payload.get("evidence_pack", {}).get("query_context", {})
            query_context.pop("performance", None)
            stages = query_context.get("search_plan", {}).get("orchestrator_stages", [])
            for stage in stages:
                stage.pop("latency_ms", None)
            return payload

        assert domain_payload(evidence_proc) == domain_payload(combined_proc)
        assert combined_proc.stderr.splitlines().count(SYNTHESIZE_DEPRECATION_WARNING) == 1


class TestExplainContract:
    """--explain: agent_decisions present, agent_decisions_summary absent."""

    def test_explain_keeps_agent_decisions(
        self, explain_proc: subprocess.CompletedProcess[str]
    ) -> None:
        assert explain_proc.returncode == 0, f"stderr: {explain_proc.stderr}"
        result = _json(explain_proc)
        assert "agent_decisions" in result
        assert isinstance(result["agent_decisions"], list)

    def test_explain_no_summary(self, explain_proc: subprocess.CompletedProcess[str]) -> None:
        assert "agent_decisions_summary" not in _json(explain_proc)


class TestHelpContract:
    """--help states the exact current deterministic CLI contract."""

    def test_help_describes_keyword_entity_scaffold(
        self, help_proc: subprocess.CompletedProcess[str]
    ) -> None:
        normalized = " ".join(help_proc.stdout.split())
        assert "Smart search with a deterministic keyword/entity scaffold" in normalized
        assert "dual-pipeline" not in normalized

    def test_help_includes_include_evidence(
        self, help_proc: subprocess.CompletedProcess[str]
    ) -> None:
        assert "--include-evidence" in help_proc.stdout

    def test_help_describes_synthesize_as_current_no_op(
        self, help_proc: subprocess.CompletedProcess[str]
    ) -> None:
        normalized = " ".join(help_proc.stdout.split())
        synthesize_help = normalized.rsplit("--synthesize", 1)[1]
        synthesize_help = synthesize_help.split("--format-entity-annotated", 1)[0].strip()
        assert synthesize_help == "Accepted compatibility no-op; no LLM and no answer"

    def test_help_includes_explain(self, help_proc: subprocess.CompletedProcess[str]) -> None:
        assert "--explain" in help_proc.stdout

    def test_help_includes_offset(self, help_proc: subprocess.CompletedProcess[str]) -> None:
        """--offset is documented as the public continuation parameter."""
        assert "--offset" in help_proc.stdout


class TestSeededEntityMatchContract:
    """Seeded CLI subprocess contract: entity_matches appear in evidence items."""

    @pytest.fixture(scope="class")
    def seeded_sandbox(self) -> Iterator[Path]:
        data_dir = Path(tempfile.mkdtemp(prefix="life-index-seeded-")) / "Life-Index"
        journals = data_dir / "Journals" / "2026" / "03"
        journals.mkdir(parents=True, exist_ok=True)
        (data_dir / ".index").mkdir(parents=True, exist_ok=True)
        (data_dir / ".cache").mkdir(parents=True, exist_ok=True)

        entity_graph = data_dir / "entity_graph.yaml"
        entity_graph.write_text(
            "entities:\n"
            "- id: person-test-001\n"
            "  type: actor\n"
            "  primary_name: TestPerson\n"
            "  attributes:\n"
            "    kind: human\n"
            "  aliases:\n"
            "  - TP\n"
            "  - TAlias\n",
            encoding="utf-8",
        )

        journal = journals / "life-index_2026-03-15_001.md"
        journal.write_text(
            "---\n"
            "title: Seeded entity match test\n"
            "date: '2026-03-15'\n"
            "topic:\n"
            "- test\n"
            "abstract: Meeting with TAlias about project\n"
            "---\n"
            "Met TAlias for lunch.\n",
            encoding="utf-8",
        )

        env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
        build_proc = subprocess.run(
            [sys.executable, "-m", "tools.build_index"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=60,
        )
        assert build_proc.returncode == 0, f"build_index failed: stderr={build_proc.stderr}"
        yield data_dir
        shutil.rmtree(data_dir.parent, ignore_errors=True)

    @pytest.fixture(scope="class")
    def seeded_evidence_proc(self, seeded_sandbox: Path) -> subprocess.CompletedProcess[str]:
        return _run_smart_search(
            "--query",
            "TAlias",
            "--include-evidence",
            data_dir=seeded_sandbox,
            timeout=120,
        )

    @pytest.fixture(scope="class")
    def seeded_default_proc(self, seeded_sandbox: Path) -> subprocess.CompletedProcess[str]:
        return _run_smart_search(
            "--query",
            "TAlias",
            data_dir=seeded_sandbox,
            timeout=120,
        )

    def test_seeded_exit_zero(self, seeded_evidence_proc: subprocess.CompletedProcess[str]) -> None:
        assert seeded_evidence_proc.returncode == 0, f"stderr: {seeded_evidence_proc.stderr}"

    def test_seeded_entity_matches_nonempty(
        self, seeded_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_proc)
        assert result["success"] is True
        pack = result.get("evidence_pack")
        assert pack is not None, "evidence_pack missing with --include-evidence on seeded data"
        items = pack.get("items", [])
        has_entity_matches = any(item.get("entity_matches") for item in items)
        assert has_entity_matches, (
            f"No evidence item had non-empty entity_matches. "
            f"Items: {len(items)}, "
            f"entity_hints: {pack.get('query_context', {}).get('entity_hints', [])}"
        )

    def test_seeded_entity_match_has_known_entity_id(
        self, seeded_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_proc)
        pack = result["evidence_pack"]
        for item in pack.get("items", []):
            for em in item.get("entity_matches", []):
                if em.get("entity_id") == "person-test-001":
                    return
        pytest.fail("No entity_match with entity_id=person-test-001 found")

    def test_seeded_evidence_document_paths_are_relative(
        self, seeded_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_proc)
        pack = result["evidence_pack"]
        for item in pack.get("items", []):
            path = item.get("document", {}).get("path")
            if path is None:
                continue
            assert not Path(path).is_absolute()
            assert not (len(path) >= 2 and path[1] == ":")

    def test_seeded_default_no_evidence_pack(
        self, seeded_default_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_default_proc)
        assert result["success"] is True
        assert "evidence_pack" not in result

    @pytest.fixture(scope="class")
    def seeded_evidence_synthesize_proc(
        self, seeded_sandbox: Path
    ) -> subprocess.CompletedProcess[str]:
        return _run_smart_search(
            "--query",
            "TAlias",
            "--include-evidence",
            "--synthesize",
            data_dir=seeded_sandbox,
            timeout=120,
        )

    def test_seeded_evidence_synthesize_success(
        self, seeded_evidence_synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        assert (
            seeded_evidence_synthesize_proc.returncode == 0
        ), f"stderr: {seeded_evidence_synthesize_proc.stderr}"
        result = _json(seeded_evidence_synthesize_proc)
        assert result["success"] is True

    def test_seeded_evidence_synthesize_no_answer(
        self, seeded_evidence_synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_synthesize_proc)
        assert "answer" not in result

    def test_seeded_evidence_synthesize_evidence_pack_present(
        self, seeded_evidence_synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_synthesize_proc)
        assert "evidence_pack" in result

    def test_seeded_evidence_synthesize_entity_matches_nonempty(
        self, seeded_evidence_synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_synthesize_proc)
        pack = result.get("evidence_pack")
        assert pack is not None
        items = pack.get("items", [])
        has_entity_matches = any(item.get("entity_matches") for item in items)
        assert has_entity_matches, (
            f"No evidence item had non-empty entity_matches. " f"Items: {len(items)}"
        )

    def test_seeded_evidence_synthesize_stable_fields_present(
        self, seeded_evidence_synthesize_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(seeded_evidence_synthesize_proc)
        for field in (
            "success",
            "query",
            "rewritten_query",
            "filtered_results",
            "summary",
            "citations",
            "agent_unavailable",
            "performance",
        ):
            assert field in result, f"Missing stable field: {field}"


class TestEvidenceDiagnosticsContract:
    """evidence_pack.diagnostics shape in CLI subprocess output."""

    def test_evidence_diagnostics_present(
        self, evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        """When --include-evidence, evidence_pack.diagnostics exists.

        notes/suggestions are conditionally present — serializer omits them
        when empty (e.g. ``ok`` outcome).  Only assert type when present.
        """
        assert evidence_proc.returncode == 0, f"stderr: {evidence_proc.stderr}"
        result = _json(evidence_proc)
        if "evidence_pack" in result:
            diag = result["evidence_pack"].get("diagnostics")
            assert diag is not None
            assert "retrieval_outcome" in diag
            assert diag["retrieval_outcome"] in (
                "ok",
                "weak_results",
                "no_confident_match",
                "zero_results",
            )
            assert "outcome_reason" in diag
            if "notes" in diag:
                assert isinstance(diag["notes"], list)
            if "suggestions" in diag:
                assert isinstance(diag["suggestions"], list)

    def test_no_diagnostics_without_evidence(
        self, default_proc: subprocess.CompletedProcess[str]
    ) -> None:
        """Default output has no evidence_pack at all."""
        result = _json(default_proc)
        assert "evidence_pack" not in result


class TestFormatEntityAnnotatedContract:
    """--format-entity-annotated produces formatted_evidence
    when combined with --include-evidence.
    """

    @pytest.fixture(scope="class")
    def fmt_sandbox(self) -> Iterator[Path]:
        data_dir = Path(tempfile.mkdtemp(prefix="life-index-fmt-")) / "Life-Index"
        journals = data_dir / "Journals" / "2026" / "03"
        journals.mkdir(parents=True, exist_ok=True)
        (data_dir / ".index").mkdir(parents=True, exist_ok=True)
        (data_dir / ".cache").mkdir(parents=True, exist_ok=True)

        entity_graph = data_dir / "entity_graph.yaml"
        entity_graph.write_text(
            "entities:\n"
            "- id: person-fmt-001\n"
            "  type: actor\n"
            "  primary_name: FormatPerson\n"
            "  attributes:\n"
            "    kind: human\n"
            "  aliases:\n"
            "  - FAlias\n",
            encoding="utf-8",
        )

        journal = journals / "life-index_2026-03-17_001.md"
        journal.write_text(
            "---\n"
            "title: Formatted evidence test\n"
            "date: '2026-03-17'\n"
            "topic:\n"
            "- test\n"
            "abstract: Meeting with FAlias about project\n"
            "---\n"
            "Met FAlias for lunch.\n",
            encoding="utf-8",
        )

        env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
        build_proc = subprocess.run(
            [sys.executable, "-m", "tools.build_index"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=60,
        )
        assert build_proc.returncode == 0, f"build_index failed: stderr={build_proc.stderr}"
        yield data_dir
        shutil.rmtree(data_dir.parent, ignore_errors=True)

    @pytest.fixture(scope="class")
    def fmt_evidence_proc(self, fmt_sandbox: Path) -> subprocess.CompletedProcess[str]:
        return _run_smart_search(
            "--query",
            "FAlias",
            "--include-evidence",
            "--format-entity-annotated",
            data_dir=fmt_sandbox,
            timeout=120,
        )

    @pytest.fixture(scope="class")
    def fmt_no_evidence_proc(self, fmt_sandbox: Path) -> subprocess.CompletedProcess[str]:
        return _run_smart_search(
            "--query",
            "FAlias",
            "--format-entity-annotated",
            data_dir=fmt_sandbox,
            timeout=120,
        )

    def test_fmt_exit_zero(self, fmt_evidence_proc: subprocess.CompletedProcess[str]) -> None:
        assert fmt_evidence_proc.returncode == 0, f"stderr: {fmt_evidence_proc.stderr}"

    def test_fmt_produces_formatted_evidence(
        self, fmt_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(fmt_evidence_proc)
        assert "formatted_evidence" in result
        assert isinstance(result["formatted_evidence"], str)
        assert len(result["formatted_evidence"]) > 0

    def test_fmt_formatted_evidence_contains_entity_id(
        self, fmt_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(fmt_evidence_proc)
        formatted = result["formatted_evidence"]
        assert "person-fmt-001" in formatted

    def test_fmt_formatted_evidence_contains_diagnostics(
        self, fmt_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(fmt_evidence_proc)
        formatted = result["formatted_evidence"]
        assert "Retrieval Quality" in formatted
        assert "Outcome:" in formatted

    def test_fmt_no_evidence_flag_ignores_formatter(
        self, fmt_no_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(fmt_no_evidence_proc)
        assert "formatted_evidence" not in result
        assert result["success"] is True

    def test_fmt_default_output_unchanged(
        self, fmt_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(fmt_evidence_proc)
        for field in (
            "success",
            "query",
            "rewritten_query",
            "filtered_results",
            "summary",
            "citations",
            "agent_unavailable",
            "performance",
        ):
            assert field in result, f"Missing stable field: {field}"


class TestPhase2AContinuationContract:
    """Phase 2A E2E: honest coverage + executable --offset continuation.

    Seeds 18 body-only token matches (above the 15-candidate delivery window),
    then walks two real CLI subprocess pages: page one must honestly report
    ``status=partial`` with an integer ``next_offset``, and page two — fetched
    through the public ``--offset`` parameter — must neither repeat nor omit
    any of the 18 observed journals.
    """

    TOKEN = "phase2acontinuation"

    @pytest.fixture(scope="class")
    def continuation_sandbox(self) -> Iterator[Path]:
        data_dir = Path(tempfile.mkdtemp(prefix="life-index-p2a-")) / "Life-Index"
        journals = data_dir / "Journals" / "2026" / "04"
        journals.mkdir(parents=True, exist_ok=True)
        (data_dir / ".index").mkdir(parents=True, exist_ok=True)
        (data_dir / ".cache").mkdir(parents=True, exist_ok=True)

        for day in range(1, 19):
            date_str = f"2026-04-{day:02d}"
            (journals / f"life-index_{date_str}_001.md").write_text(
                "---\n"
                f"date: {date_str}\n"
                "topic: []\n"
                "tags: []\n"
                "people: []\n"
                "---\n\n"
                "# neutral note\n\n"
                f"Neutral fixture contains {self.TOKEN} in body only.\n",
                encoding="utf-8",
            )

        env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
        build_proc = subprocess.run(
            [sys.executable, "-m", "tools.build_index"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=120,
        )
        assert (
            build_proc.returncode == 0
        ), f"build_index failed: stderr={build_proc.stderr}, stdout={build_proc.stdout}"
        yield data_dir
        shutil.rmtree(data_dir.parent, ignore_errors=True)

    @pytest.fixture(scope="class")
    def continuation_pages(
        self, continuation_sandbox: Path
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        page_one_proc = _run_smart_search(
            "--query",
            self.TOKEN,
            data_dir=continuation_sandbox,
            timeout=120,
        )
        assert page_one_proc.returncode == 0, f"stderr: {page_one_proc.stderr}"
        page_one = _json(page_one_proc)

        coverage = page_one.get("retrieval_coverage")
        assert coverage is not None, "smart-search CLI output lacks retrieval_coverage"
        next_offset = coverage.get("next_offset")
        assert isinstance(next_offset, int) and not isinstance(next_offset, bool)

        page_two_proc = _run_smart_search(
            "--query",
            self.TOKEN,
            "--offset",
            str(next_offset),
            data_dir=continuation_sandbox,
            timeout=120,
        )
        assert page_two_proc.returncode == 0, f"stderr: {page_two_proc.stderr}"
        return page_one, _json(page_two_proc)

    @staticmethod
    def _identities(page: dict[str, Any]) -> set[str]:
        return {
            item.get("rel_path") or item.get("path") or item.get("title") or ""
            for item in page["filtered_results"]
        }

    def test_page_one_is_windowed_not_silent_truncation(
        self, continuation_pages: tuple[dict[str, Any], dict[str, Any]]
    ) -> None:
        page_one, _ = continuation_pages
        assert len(page_one["filtered_results"]) == 15
        coverage = page_one["retrieval_coverage"]
        assert coverage["schema_version"] == "retrieval_coverage.v1"
        assert coverage["status"] == "partial"
        assert coverage["observed_total"] == 18
        assert coverage["returned"] == 15
        assert coverage["next_offset"] == 15
        assert "unread_page" in coverage["partial_reasons"]

    def test_page_two_is_disjoint_and_lossless(
        self, continuation_pages: tuple[dict[str, Any], dict[str, Any]]
    ) -> None:
        page_one, page_two = continuation_pages
        page_one_ids = self._identities(page_one)
        page_two_ids = self._identities(page_two)
        assert len(page_two_ids) == 3
        assert not (page_one_ids & page_two_ids)
        assert len(page_one_ids | page_two_ids) == 18

    def test_final_page_has_no_cursor_and_stays_partial(
        self, continuation_pages: tuple[dict[str, Any], dict[str, Any]]
    ) -> None:
        _, page_two = continuation_pages
        coverage = page_two["retrieval_coverage"]
        assert coverage["next_offset"] is None
        assert coverage["status"] == "partial"
        assert coverage["observed_total"] == 18


class TestCaseInsensitiveSeededEntityMatchContract:
    """Case-insensitive entity match: lowercase query matches seeded uppercase data."""

    @pytest.fixture(scope="class")
    def ci_sandbox(self) -> Iterator[Path]:
        data_dir = Path(tempfile.mkdtemp(prefix="life-index-ci-")) / "Life-Index"
        journals = data_dir / "Journals" / "2026" / "03"
        journals.mkdir(parents=True, exist_ok=True)
        (data_dir / ".index").mkdir(parents=True, exist_ok=True)
        (data_dir / ".cache").mkdir(parents=True, exist_ok=True)

        entity_graph = data_dir / "entity_graph.yaml"
        entity_graph.write_text(
            "entities:\n"
            "- id: person-ci-001\n"
            "  type: actor\n"
            "  primary_name: TestCasePerson\n"
            "  attributes:\n"
            "    kind: human\n"
            "  aliases:\n"
            "  - TCI\n"
            "  - CaseAlias\n",
            encoding="utf-8",
        )

        journal = journals / "life-index_2026-03-16_001.md"
        journal.write_text(
            "---\n"
            "title: Case insensitive entity match test\n"
            "date: '2026-03-16'\n"
            "topic:\n"
            "- test\n"
            "abstract: Meeting with CaseAlias about project\n"
            "---\n"
            "Met CaseAlias for lunch.\n",
            encoding="utf-8",
        )

        env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
        build_proc = subprocess.run(
            [sys.executable, "-m", "tools.build_index"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            env=env,
            timeout=60,
        )
        assert (
            build_proc.returncode == 0
        ), f"build_index failed: stderr={build_proc.stderr}, stdout={build_proc.stdout}"
        yield data_dir
        shutil.rmtree(data_dir.parent, ignore_errors=True)

    @pytest.fixture(scope="class")
    def ci_evidence_proc(self, ci_sandbox: Path) -> subprocess.CompletedProcess[str]:
        return _run_smart_search(
            "--query",
            "casealias",
            "--include-evidence",
            data_dir=ci_sandbox,
            timeout=120,
        )

    def test_ci_exit_zero(self, ci_evidence_proc: subprocess.CompletedProcess[str]) -> None:
        assert ci_evidence_proc.returncode == 0, f"stderr: {ci_evidence_proc.stderr}"

    def test_ci_entity_matches_nonempty(
        self, ci_evidence_proc: subprocess.CompletedProcess[str]
    ) -> None:
        result = _json(ci_evidence_proc)
        assert result["success"] is True
        pack = result.get("evidence_pack")
        assert pack is not None, "evidence_pack missing with --include-evidence on ci sandbox"
        items = pack.get("items", [])
        has_entity_matches = any(item.get("entity_matches") for item in items)
        assert has_entity_matches, (
            f"No evidence item had non-empty entity_matches for case-insensitive query. "
            f"Items: {len(items)}"
        )
