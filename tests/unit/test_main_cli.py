#!/usr/bin/env python3
"""Unit tests for tools.__main__ CLI helpers."""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from tools.__main__ import health_check
from tools.search_journals.__main__ import _apply_presentation_layer


class TestHealthCheck:
    """Tests for unified CLI health check."""

    def test_health_check_uses_configured_data_dir(self, tmp_path, monkeypatch, capsys):
        """Health check should respect config-level data directory overrides."""
        data_dir = tmp_path / "life-index-data"
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-01-01_001.md").write_text("# test\n", encoding="utf-8")

        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True)
        (index_dir / "journals_fts.db").write_text("fts", encoding="utf-8")
        (index_dir / "vectors_simple.pkl").write_text("vec", encoding="utf-8")

        cache_dir = tmp_path / "model-cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "model.onnx").write_text("model", encoding="utf-8")

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setattr("tools.__main__.get_model_cache_dir", lambda: cache_dir)
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))
        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            types.SimpleNamespace(__version__="test"),
        )

        health_check()

        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert payload["success"] is True
        assert payload["data"]["status"] in {"healthy", "degraded"}
        data_directory_check = next(
            check for check in payload["data"]["checks"] if check["name"] == "data_directory"
        )
        search_index_check = next(
            check for check in payload["data"]["checks"] if check["name"] == "search_index"
        )

        assert data_directory_check["path"] == str(data_dir)
        assert data_directory_check["journal_count"] == 1
        assert data_directory_check["last_journal_date"] == "2026-01-01"
        assert search_index_check["path"] == str(index_dir)

    def test_health_data_directory_reports_null_last_journal_date_without_journals(
        self, tmp_path, monkeypatch, capsys
    ):
        """Empty data dirs should expose a nullable deterministic last_journal_date."""
        data_dir = tmp_path / "life-index-data"
        (data_dir / "Journals").mkdir(parents=True)

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))

        health_check()

        payload = json.loads(capsys.readouterr().out)
        data_directory_check = next(
            check for check in payload["data"]["checks"] if check["name"] == "data_directory"
        )
        assert data_directory_check["journal_count"] == 0
        assert data_directory_check["last_journal_date"] is None

    def test_health_reports_semantic_index_disabled(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "life-index-data"
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-01-01_001.md").write_text("# test\n", encoding="utf-8")
        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True)
        (index_dir / "journals_fts.db").write_text("fts", encoding="utf-8")
        (index_dir / "semantic_status.json").write_text(
            '{"status":"building","pid":1234}',
            encoding="utf-8",
        )

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))
        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            types.SimpleNamespace(__version__="test"),
        )

        health_check()

        payload = json.loads(capsys.readouterr().out)
        search_index_check = next(
            check for check in payload["data"]["checks"] if check["name"] == "search_index"
        )
        assert search_index_check["semantic_status"] == "disabled"
        assert search_index_check["semantic"]["status"] == "disabled"
        assert "removed" in search_index_check["semantic"]["reason"]

    def test_health_groups_actionable_and_chronic_issues(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "life-index-data"
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-01-01_001.md").write_text("# test\n", encoding="utf-8")

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))

        health_check()

        payload = json.loads(capsys.readouterr().out)
        data = payload["data"]

        assert "actionable_issues" in data
        assert "chronic_debt" in data
        assert "issue_summary" in data
        assert any("Search index not built" in item for item in data["actionable_issues"])
        assert any("Entity graph" in item for item in data["chronic_debt"])
        assert data["issue_summary"]["actionable_count"] == len(data["actionable_issues"])
        assert data["issue_summary"]["chronic_debt_count"] == len(data["chronic_debt"])

    def test_health_exposes_upgrade_freshness_session_signal(self, tmp_path, monkeypatch, capsys):
        """UF-1: host agents must see stale-checkout signals on the session surface."""
        data_dir = tmp_path / "life-index-data"
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-01-01_001.md").write_text("# test\n", encoding="utf-8")

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))

        def fake_detect_upgrade_freshness_state():
            return {
                "installed_version": "1.3.4",
                "manifest_version": "1.3.5",
                "install_type": "editable",
                "freshness": "update_available",
                "update_available": "git-behind",
                "update_reasons": ["git_behind"],
                "suggested_refresh_step": "git pull --ff-only && python -m pip install -e .",
                "freshness_error": None,
                "git_freshness": "behind",
                "git_upstream": "origin/main",
                "git_behind_count": 2,
                "git_ahead_count": 0,
                "git_error": None,
            }

        monkeypatch.setattr(
            "tools.__main__._detect_upgrade_freshness_state",
            fake_detect_upgrade_freshness_state,
            raising=False,
        )

        health_check()

        payload = json.loads(capsys.readouterr().out)
        freshness = payload["data"]["upgrade_freshness"]
        assert freshness["freshness"] == "update_available"
        assert freshness["git"]["freshness"] == "behind"
        assert freshness["git"]["behind_count"] == 2
        assert freshness["suggested_refresh_step"] == "life-index upgrade --plan --json"
        assert freshness["suggested_refresh_step_side_effect"] == "read"
        assert "read-only" in freshness["suggested_refresh_step_side_effect_note"].lower()
        assert freshness["changelog"] == "CHANGELOG.md"

        check = next(
            item for item in payload["data"]["checks"] if item["name"] == "upgrade_freshness"
        )
        assert check["status"] == "warning"
        assert "git-behind" in check["issue"]
        assert "git pull" not in check["issue"]
        assert "pip install" not in check["issue"]
        assert "sync-skill --install" not in check["issue"]

    def test_local_git_freshness_reports_dirty_worktree(self, tmp_path):
        """Dirty editable checkouts should be visible to host agents before upgrade."""
        from tools import __main__ as main_cli

        repo = tmp_path / "checkout"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8")
        (repo / "friction.md").write_text("agent note in the wrong place\n", encoding="utf-8")

        dirty = main_cli._detect_local_git_freshness(repo)

        assert dirty["git_worktree_dirty"] is True
        assert dirty["git_worktree_dirty_count"] == 1
        assert dirty["git_worktree_dirty_error"] is None

        (repo / "friction.md").unlink()
        clean = main_cli._detect_local_git_freshness(repo)

        assert clean["git_worktree_dirty"] is False
        assert clean["git_worktree_dirty_count"] == 0

    def test_local_git_status_disables_optional_locks(self, tmp_path, monkeypatch):
        from tools import __main__ as main_cli

        commands: list[list[str]] = []

        def fake_run_git(path: Path, args: list[str]):
            commands.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        monkeypatch.setattr(main_cli, "_run_git_local", fake_run_git)

        main_cli._detect_local_git_worktree(tmp_path)

        assert commands == [["--no-optional-locks", "status", "--porcelain"]]

    def test_local_git_freshness_remote_difference_is_unknown_without_ref_writes(
        self,
        tmp_path,
        monkeypatch,
    ):
        from tools import __main__ as main_cli

        repo = tmp_path / "checkout"
        (repo / ".git").mkdir(parents=True)
        commands: list[list[str]] = []

        def fake_run_git(path: Path, args: list[str]):
            commands.append(args)
            if args == ["--no-optional-locks", "status", "--porcelain"]:
                return subprocess.CompletedProcess([], 0, "", "")
            if args == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
                return subprocess.CompletedProcess([], 0, "origin/main\n", "")
            if args == ["rev-parse", "origin/main"]:
                return subprocess.CompletedProcess([], 0, "local-tracking-head\n", "")
            if args == ["ls-remote", "--heads", "origin", "main"]:
                return subprocess.CompletedProcess([], 0, "remote-head\trefs/heads/main\n", "")
            if args == ["rev-list", "--left-right", "--count", "HEAD...origin/main"]:
                return subprocess.CompletedProcess([], 0, "0 0\n", "")
            raise AssertionError(f"Unexpected git command: {args}")

        monkeypatch.setattr(main_cli, "_run_git_local", fake_run_git)

        freshness = main_cli._detect_local_git_freshness(repo)

        assert all(command[0] not in {"fetch", "pull", "reset"} for command in commands)
        assert freshness["git_freshness"] == "unknown"
        assert freshness["git_behind_count"] is None
        assert "life-index upgrade --plan --json" in freshness["git_error"]

    def test_health_freshness_does_not_claim_current_when_remote_truth_is_unknown(
        self,
        tmp_path,
        monkeypatch,
    ):
        from tools import __main__ as main_cli

        checkout = tmp_path / "checkout"
        (checkout / ".git").mkdir(parents=True)
        monkeypatch.setattr(
            main_cli, "BOOTSTRAP_MANIFEST_PATH", checkout / "bootstrap-manifest.json"
        )
        monkeypatch.setattr(main_cli, "read_bootstrap_manifest", lambda: {"repo_version": "1.5.1"})
        monkeypatch.setattr(main_cli, "_raw_installed_package_version", lambda: "1.5.1")
        monkeypatch.setattr(
            main_cli,
            "_detect_local_git_freshness",
            lambda path: {
                "git_freshness": "unknown",
                "git_upstream": "origin/main",
                "git_behind_count": None,
                "git_ahead_count": None,
                "git_error": (
                    "Remote tip differs from local tracking state; run "
                    "life-index upgrade --plan --json."
                ),
                "git_worktree_dirty": False,
                "git_worktree_dirty_count": 0,
                "git_worktree_dirty_error": None,
            },
        )

        state = main_cli._detect_upgrade_freshness_state()

        assert state["freshness"] == "unknown"
        assert state["update_available"] is None
        assert state["suggested_refresh_step"] == "life-index upgrade --plan --json"

    def test_upgrade_freshness_dirty_worktree_is_warning_hint_not_issue(
        self,
        monkeypatch,
    ):
        """Dirty clones should warn with recovery guidance without blocking health."""
        from tools import __main__ as main_cli

        def fake_detect_upgrade_freshness_state():
            return {
                "installed_version": "1.3.7",
                "manifest_version": "1.3.7",
                "install_type": "editable",
                "freshness": "current",
                "update_available": None,
                "update_reasons": [],
                "suggested_refresh_step": None,
                "freshness_error": None,
                "git_freshness": "current",
                "git_upstream": "origin/main",
                "git_behind_count": 0,
                "git_ahead_count": 0,
                "git_error": None,
                "git_worktree_dirty": True,
                "git_worktree_dirty_count": 2,
                "git_worktree_dirty_error": None,
            }

        monkeypatch.setattr(
            main_cli,
            "_detect_upgrade_freshness_state",
            fake_detect_upgrade_freshness_state,
        )

        check, issue = main_cli._check_upgrade_freshness()

        assert issue == ""
        assert check["status"] == "warning"
        assert check["warning"] == (
            "Repository clone has uncommitted changes; dirty clones can cause "
            "Life Index upgrades to fail."
        )
        assert check["suggested_command"] == "git --no-optional-locks status --short"
        assert check["side_effect"] == "read"
        assert "ask the owner" in check["side_effect_note"].lower()
        assert "discard" not in check["side_effect_note"].lower()
        assert check["git"]["dirty"] is True
        assert check["git"]["dirty_count"] == 2
        assert "issue" not in check

    def test_upgrade_freshness_clean_worktree_has_no_dirty_warning(self, monkeypatch):
        """Clean editable checkouts should not surface a dirty-clone hint."""
        from tools import __main__ as main_cli

        def fake_detect_upgrade_freshness_state():
            return {
                "installed_version": "1.3.7",
                "manifest_version": "1.3.7",
                "install_type": "editable",
                "freshness": "current",
                "update_available": None,
                "update_reasons": [],
                "suggested_refresh_step": None,
                "freshness_error": None,
                "git_freshness": "current",
                "git_upstream": "origin/main",
                "git_behind_count": 0,
                "git_ahead_count": 0,
                "git_error": None,
                "git_worktree_dirty": False,
                "git_worktree_dirty_count": 0,
                "git_worktree_dirty_error": None,
            }

        monkeypatch.setattr(
            main_cli,
            "_detect_upgrade_freshness_state",
            fake_detect_upgrade_freshness_state,
        )

        check, issue = main_cli._check_upgrade_freshness()

        assert issue == ""
        assert check["status"] == "ok"
        assert "warning" not in check
        assert check["suggested_command"] is None
        assert "side_effect" not in check
        assert check["git"]["dirty"] is False


class TestMainCli:
    def test_serve_command_is_not_available(self, monkeypatch, capsys) -> None:
        from tools import __main__

        monkeypatch.setattr(__main__.sys, "argv", ["life-index", "serve"])

        with pytest.raises(SystemExit) as exc_info:
            __main__.main()

        output = capsys.readouterr().out
        assert exc_info.value.code == 1
        assert "Unknown command: serve" in output


class TestHealthCheckIndexTree:
    """TDD 3 RED: health check must report Index Tree freshness/status."""

    def test_health_includes_index_tree_check(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "life-index-data"
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-01-01_001.md").write_text("# test\n", encoding="utf-8")

        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True)
        (index_dir / "journals_fts.db").write_text("fts", encoding="utf-8")

        cache_dir = tmp_path / "model-cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "model.onnx").write_text("model", encoding="utf-8")

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setattr("tools.__main__.get_model_cache_dir", lambda: cache_dir)
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))
        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            types.SimpleNamespace(__version__="test"),
        )

        health_check()

        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert payload["success"] is True
        checks = payload["data"]["checks"]
        check_names = [c["name"] for c in checks]
        assert "index_tree" in check_names

        it_check = next(c for c in checks if c["name"] == "index_tree")
        assert "status" in it_check
        assert it_check["status"] in ("ok", "warning", "info")
        if it_check.get("suggested_command"):
            assert it_check["side_effect"] == "write"
            assert "derived" in it_check["side_effect_note"]

    def test_health_index_tree_not_critical_when_missing(self, tmp_path, monkeypatch, capsys):
        data_dir = tmp_path / "life-index-data"
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-01-01_001.md").write_text("# test\n", encoding="utf-8")

        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True)
        (index_dir / "journals_fts.db").write_text("fts", encoding="utf-8")

        cache_dir = tmp_path / "model-cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "model.onnx").write_text("model", encoding="utf-8")

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))
        monkeypatch.setattr("tools.__main__.get_model_cache_dir", lambda: cache_dir)
        monkeypatch.setitem(sys.modules, "yaml", types.SimpleNamespace(__version__="test"))
        monkeypatch.setitem(
            sys.modules,
            "sentence_transformers",
            types.SimpleNamespace(__version__="test"),
        )

        health_check()

        captured = capsys.readouterr()
        payload = json.loads(captured.out)

        assert payload["success"] is True
        assert payload["data"]["status"] != "unhealthy"

        it_check = next(c for c in payload["data"]["checks"] if c["name"] == "index_tree")
        assert it_check["status"] in ("warning", "info")

    def test_index_tree_issue_suggests_runnable_generate_all_months_command(
        self, tmp_path, monkeypatch
    ):
        from tools import __main__ as main_cli

        data_dir = tmp_path / "life-index-data"
        journal_dir = data_dir / "Journals" / "2026" / "03"
        journal_dir.mkdir(parents=True)
        (journal_dir / "life-index_2026-03-14_001.md").write_text(
            "---\ndate: 2026-03-14\ntitle: Test\n---\n\n# Test\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(data_dir))

        check = main_cli._check_index_tree()

        assert check["status"] == "warning"
        assert check["suggested_command"] == "life-index generate-index --all-months"
        assert check["side_effect"] == "write"
        assert "derived" in check["side_effect_note"]
        assert "life-index generate-index --all-months" in check["issue"]
        assert "run 'life-index generate-index'" not in check["issue"]

    def test_health_help_does_not_run_health_checks(self, monkeypatch, capsys):
        """health --help must return usage text before running detectors/checks."""
        from tools import __main__ as main_cli

        def fail_if_called() -> None:
            raise AssertionError("health_check should not run for health --help")

        monkeypatch.setattr(main_cli.sys, "argv", ["life-index", "health", "--help"])
        monkeypatch.setattr(main_cli, "health_check", fail_if_called)

        main_cli.main()

        captured = capsys.readouterr()
        assert "Usage: life-index health [options]" in captured.out
        assert not captured.out.lstrip().startswith("{")


class TestApplyPresentationLayer:
    """Regression tests for _apply_presentation_layer (lead review finding 2026-05-24).

    The original implementation called this helper from main() but never
    defined it, causing NameError at runtime.  These tests would have caught
    that bug before it reached the lead reviewer.
    """

    def test_function_exists_and_is_callable(self):
        """Regression gate: _apply_presentation_layer is defined and importable."""
        assert callable(_apply_presentation_layer)

    def test_limit_5_truncates_to_5(self):
        """--limit 5: merged_results sliced to 5, total_matches preserved."""
        result = {
            "merged_results": [
                {"path": f"/test/doc_{i}.md", "score": 0.9 - i * 0.01} for i in range(20)
            ],
            "total_matches": 20,
            "total_found": 20,
            "total_available": 20,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=5, offset=0)

        assert len(result["merged_results"]) == 5
        assert result["total_matches"] == 20  # preserved
        assert result["total_found"] == 5  # displayed count
        assert result["total_available"] == 20  # backward compat
        assert result["has_more"] is True
        assert result["display_summary"] == "Showing 5 of 20 results"

    def test_limit_0_returns_all_results(self):
        """--limit 0: no truncation, all results returned."""
        result = {
            "merged_results": [{"path": f"/test/doc_{i}.md", "score": 0.9} for i in range(15)],
            "total_matches": 15,
            "total_found": 15,
            "total_available": 15,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=0, offset=0)

        assert len(result["merged_results"]) == 15
        assert result["total_matches"] == 15
        assert result["total_found"] == 15
        assert result["has_more"] is False
        assert result["display_summary"] == "Showing 15 of 15 results"

    def test_offset_skip_first_n_results(self):
        """Offset skips first N results before limit is applied."""
        result = {
            "merged_results": [
                {"path": f"/test/doc_{i}.md", "score": 0.9 - i * 0.01} for i in range(20)
            ],
            "total_matches": 20,
            "total_found": 20,
            "total_available": 20,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=5, offset=10)

        assert len(result["merged_results"]) == 5
        assert result["merged_results"][0]["path"] == "/test/doc_10.md"

    def test_zero_results_has_display_summary(self):
        """Zero-result response gets appropriate display_summary."""
        result = {
            "merged_results": [],
            "total_matches": 0,
            "total_found": 0,
            "total_available": 0,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=20, offset=0)

        assert result["total_matches"] == 0
        assert result["display_summary"] == "No results found"
        assert result["has_more"] is False

    def test_no_merged_results_key_does_not_raise(self):
        """Result dict without merged_results key is a no-op."""
        result: dict = {"success": False, "total_matches": 0}
        _apply_presentation_layer(result, limit=20, offset=0)
        assert "display_summary" not in result  # unchanged

    def test_limit_none_is_treated_as_zero_full(self):
        """limit=None (legacy) treated same as limit=0 (all results)."""
        result = {
            "merged_results": [{"path": "/test/doc_0.md", "score": 0.9} for _ in range(8)],
            "total_matches": 8,
            "total_found": 8,
            "total_available": 8,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=None, offset=0)

        assert len(result["merged_results"]) == 8  # no truncation

    def test_invariant_total_matches_ge_returned_results(self):
        """total_matches >= len(merged_results) always holds after slicing."""
        result = {
            "merged_results": [{"path": f"/test/doc_{i}.md", "score": 0.9} for i in range(30)],
            "total_matches": 30,
            "total_found": 30,
            "total_available": 30,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=7, offset=3)

        assert result["total_matches"] >= len(result["merged_results"])
        assert result["total_matches"] == 30
        assert len(result["merged_results"]) == 7

    def test_has_more_false_for_tail_page_offset(self):
        """has_more must be False when offset+displayed reaches total_matches.

        Lead review finding 2: has_more semantics were based on displayed < total_matches,
        which breaks for tail pages with offset.  Correct invariant:
        has_more == (offset + displayed < total_matches).
        """
        result = {
            "merged_results": [
                {"path": f"/test/doc_{i}.md", "score": 0.9 - i * 0.01} for i in range(20)
            ],
            "total_matches": 20,
            "total_found": 20,
            "total_available": 20,
            "has_more": True,
        }
        _apply_presentation_layer(result, limit=0, offset=10)

        assert len(result["merged_results"]) == 10
        assert result["has_more"] is False
        assert result["display_summary"] == "Showing 10 of 20 results"

    def test_has_more_true_for_mid_page_with_offset(self):
        """has_more must be True when offset+displayed < total_matches."""
        result = {
            "merged_results": [
                {"path": f"/test/doc_{i}.md", "score": 0.9 - i * 0.01} for i in range(25)
            ],
            "total_matches": 25,
            "total_found": 25,
            "total_available": 25,
            "has_more": False,
        }
        _apply_presentation_layer(result, limit=5, offset=5)

        assert len(result["merged_results"]) == 5
        assert result["has_more"] is True
        assert result["display_summary"] == "Showing 5 of 25 results"

    def test_has_more_false_for_exact_page_boundary(self):
        """has_more must be False when offset+displayed equals total_matches (exact boundary)."""
        result = {
            "merged_results": [
                {"path": f"/test/doc_{i}.md", "score": 0.9 - i * 0.01} for i in range(15)
            ],
            "total_matches": 15,
            "total_found": 15,
            "total_available": 15,
            "has_more": True,
        }
        _apply_presentation_layer(result, limit=10, offset=5)

        assert len(result["merged_results"]) == 10
        assert result["has_more"] is False
        assert result["display_summary"] == "Showing 10 of 15 results"
