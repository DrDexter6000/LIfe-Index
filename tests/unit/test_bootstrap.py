"""Unit tests for Life Index bootstrap detection."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tools.bootstrap as _mod
from tools.bootstrap import (
    BOOTSTRAP_SCHEMA_VERSION,
    assess_checkout,
    build_bootstrap_result,
    decide_route,
    detect_data_state,
)


def _write_journal(path: Path, name: str = "life-index_2026-01-01_001.md") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    journal = path / name
    journal.write_text("---\ntitle: t\ndate: 2026-01-01\n---\nbody", encoding="utf-8")
    return journal


def _freshness(
    freshness: str = "current",
    latest_release: str | None = "1.2.3",
    update_available: str | None = None,
    freshness_error: str | None = None,
) -> dict[str, object]:
    return {
        "freshness": freshness,
        "latest_release": latest_release,
        "update_available": update_available,
        "update_reasons": ["release"] if update_available else [],
        "freshness_error": freshness_error,
        "suggested_refresh_step": None,
        "git_freshness": "not_applicable",
        "git_upstream": None,
        "git_behind_count": None,
        "git_ahead_count": None,
        "git_error": None,
    }


class TestDetectDataState:
    def test_nonexistent_data_dir_has_no_user_data(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: None)
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "unknown")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))
        assert state["has_user_data"] is False
        assert state["journal_count"] == 0
        assert state["migration_needed"] == 0
        assert state["migration_check_error"] is None

    def test_life_index_journals_are_counted(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "editable")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        data_dir = tmp_path / "Life-Index"
        _write_journal(data_dir / "Journals" / "2026" / "01")
        (data_dir / "Journals" / "2026" / "01" / "README.md").write_text("ignore", encoding="utf-8")

        state = detect_data_state(data_dir=str(data_dir))

        assert state["has_user_data"] is True
        assert state["journal_count"] == 1

    def test_required_keys_are_present(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: None)
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "unknown")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))
        assert set(state) == {
            "has_user_data",
            "journal_count",
            "data_dir",
            "installed_version",
            "manifest_version",
            "install_in_sync",
            "install_type",
            "freshness",
            "latest_release",
            "update_available",
            "update_reasons",
            "freshness_error",
            "suggested_refresh_step",
            "git_freshness",
            "git_upstream",
            "git_behind_count",
            "git_ahead_count",
            "git_error",
            "migration_needed",
            "migration_check_error",
        }

    def test_install_in_sync_true_when_versions_match(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "editable")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))
        assert state["install_in_sync"] is True

    def test_install_in_sync_false_when_versions_differ(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.2.2")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "package")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))
        assert state["install_in_sync"] is False

    def test_install_in_sync_none_when_installed_version_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: None)
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "unknown")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))
        assert state["install_in_sync"] is None

    def test_migration_needed_uses_scan_journals_in_process(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "editable")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())
        monkeypatch.setattr(_mod, "scan_journals", lambda p: {"needs_migration": 4})
        data_dir = tmp_path / "Life-Index"
        _write_journal(data_dir / "Journals" / "2026" / "01")

        state = detect_data_state(data_dir=str(data_dir))

        assert state["migration_needed"] == 4
        assert state["migration_check_error"] is None

    def test_migration_scan_failure_is_not_reported_as_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.2.3")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "editable")
        monkeypatch.setattr(_mod, "_detect_release_freshness", lambda *args, **kwargs: _freshness())

        def boom(path):
            raise RuntimeError("scan failed")

        monkeypatch.setattr(_mod, "scan_journals", boom)
        data_dir = tmp_path / "Life-Index"
        _write_journal(data_dir / "Journals" / "2026" / "01")

        state = detect_data_state(data_dir=str(data_dir))

        assert state["migration_needed"] is None
        assert "scan failed" in state["migration_check_error"]

    def test_pypi_newer_than_local_reports_update_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.3.1")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.3.1")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "package")
        monkeypatch.setattr(_mod, "_detect_git_checkout_path", lambda install_type: None)
        monkeypatch.setattr(_mod, "_query_latest_release", lambda: "1.3.2")

        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))

        assert state["install_in_sync"] is True
        assert state["install_type"] == "package"
        assert state["freshness"] == "update_available"
        assert state["latest_release"] == "1.3.2"
        assert state["update_available"] == "1.3.2"
        assert state["suggested_refresh_step"] == "life-index upgrade --plan --json"
        assert state["freshness_error"] is None

    def test_pypi_lookup_failure_reports_unknown_without_crashing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.3.1")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.3.1")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "editable")
        monkeypatch.setattr(_mod, "_detect_git_checkout_path", lambda install_type: None)

        def timeout() -> str:
            raise TimeoutError("network timed out")

        monkeypatch.setattr(_mod, "_query_latest_release", timeout)

        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))

        assert state["freshness"] == "unknown"
        assert state["latest_release"] is None
        assert state["update_available"] is None
        assert "network timed out" in state["freshness_error"]

    def test_life_index_no_net_disables_release_lookup(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_get_installed_version", lambda: "1.3.1")
        monkeypatch.setattr(_mod, "_get_manifest_version", lambda: "1.3.1")
        monkeypatch.setattr(_mod, "_detect_install_type", lambda: "editable")
        monkeypatch.setenv("LIFE_INDEX_NO_NET", "1")

        def forbidden() -> str:
            raise AssertionError("network should not be called")

        monkeypatch.setattr(_mod, "_query_latest_release", forbidden)
        monkeypatch.setattr(_mod, "_run_git", forbidden)

        state = detect_data_state(data_dir=str(tmp_path / "Life-Index"))

        assert state["freshness"] == "unknown"
        assert state["latest_release"] is None
        assert state["update_available"] is None
        assert state["freshness_error"] == "disabled by LIFE_INDEX_NO_NET"
        assert state["git_freshness"] == "unknown"

    def test_git_checkout_detection_prefers_imported_checkout(self, monkeypatch):
        def wrong_editable_path() -> Path | None:
            raise AssertionError("editable metadata should not be consulted")

        monkeypatch.setattr(_mod, "_detect_editable_checkout_path", wrong_editable_path)

        checkout = _mod._detect_git_checkout_path("editable")

        assert checkout == Path(_mod.__file__).resolve().parents[2]

    def test_git_behind_same_version_reports_update_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_mod, "_query_latest_release", lambda: "1.3.4")
        origin = tmp_path / "origin"
        checkout = tmp_path / "checkout"
        _git(origin.parent, "init", "origin")
        _git(origin, "config", "user.email", "test@example.com")
        _git(origin, "config", "user.name", "Test User")
        (origin / "marker.txt").write_text("one\n", encoding="utf-8")
        _git(origin, "add", "marker.txt")
        _git(origin, "commit", "-m", "one")
        _git(tmp_path, "clone", str(origin), str(checkout))
        (origin / "marker.txt").write_text("two\n", encoding="utf-8")
        _git(origin, "add", "marker.txt")
        _git(origin, "commit", "-m", "two")

        freshness = _mod._detect_release_freshness(
            "1.3.4",
            "1.3.4",
            install_type="editable",
            git_checkout=checkout,
        )

        assert freshness["freshness"] == "unknown"
        assert freshness["update_available"] is None
        assert freshness["update_reasons"] == []
        assert freshness["git_freshness"] == "unknown"
        assert freshness["git_behind_count"] is None
        assert "life-index upgrade --plan --json" in freshness["git_error"]
        assert freshness["suggested_refresh_step"] == "life-index upgrade --plan --json"

    def test_git_freshness_never_fetches_or_updates_refs(self, tmp_path, monkeypatch):
        checkout = tmp_path / "checkout"
        checkout.mkdir()
        commands: list[list[str]] = []

        def fake_run_git(path: Path, args: list[str]):
            commands.append(args)
            if args[:4] == ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]:
                return subprocess.CompletedProcess([], 0, "origin/main\n", "")
            if args == ["rev-parse", "origin/main"]:
                return subprocess.CompletedProcess([], 0, "local-tracking-head\n", "")
            if args == ["ls-remote", "--heads", "origin", "main"]:
                return subprocess.CompletedProcess([], 0, "remote-head\trefs/heads/main\n", "")
            raise AssertionError(f"Unexpected git command: {args}")

        monkeypatch.setattr(_mod, "_run_git", fake_run_git)

        freshness = _mod._detect_git_freshness(checkout)

        assert all(command[0] not in {"fetch", "pull", "reset"} for command in commands)
        assert freshness["git_freshness"] == "unknown"
        assert freshness["git_behind_count"] is None
        assert "life-index upgrade --plan --json" in freshness["git_error"]

    def test_package_install_without_git_keeps_version_only_freshness(self, monkeypatch):
        monkeypatch.setattr(_mod, "_query_latest_release", lambda: "1.3.4")

        freshness = _mod._detect_release_freshness(
            "1.3.4",
            "1.3.4",
            install_type="package",
            git_checkout=None,
        )

        assert freshness["freshness"] == "current"
        assert freshness["update_available"] is None
        assert freshness["git_freshness"] == "not_applicable"


class TestDetectInstallType:
    def test_direct_url_editable_install_detected(self, monkeypatch):
        class Dist:
            def read_text(self, name: str) -> str | None:
                assert name == "direct_url.json"
                return '{"url": "file:///repo", "dir_info": {"editable": true}}'

        monkeypatch.setattr(_mod, "_pkg_distribution", lambda name: Dist())

        assert _mod._detect_install_type() == "editable"

    def test_direct_url_non_editable_install_detected_as_package(self, monkeypatch):
        class Dist:
            def read_text(self, name: str) -> str | None:
                assert name == "direct_url.json"
                return '{"url": "https://example.invalid/life-index.tar.gz"}'

        monkeypatch.setattr(_mod, "_pkg_distribution", lambda name: Dist())

        assert _mod._detect_install_type() == "package"

    def test_missing_distribution_reports_unknown(self, monkeypatch):
        def missing(name: str):
            raise _mod.PackageNotFoundError

        monkeypatch.setattr(_mod, "_pkg_distribution", missing)

        assert _mod._detect_install_type() == "unknown"


def _make_checkout(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for name in ("SKILL.md", "pyproject.toml", "bootstrap-manifest.json"):
        (path / name).write_text("x", encoding="utf-8")
    return path


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )


class TestAssessCheckout:
    def test_missing_required_files_is_invalid(self, tmp_path):
        checkout = tmp_path / "skills" / "life-index"
        checkout.mkdir(parents=True)
        (checkout / "SKILL.md").write_text("# Life Index", encoding="utf-8")

        result = assess_checkout(checkout)

        assert result["verdict"] == "invalid"
        assert result["safe_to_adopt"] is False
        assert "pyproject.toml" in result["reason"]

    def test_discovered_clean_checkout_is_ambiguous_not_adopt(self, tmp_path):
        checkout = _make_checkout(tmp_path / "Downloads" / "life-index")

        result = assess_checkout(checkout, checkout_origin="discovered")

        assert result["verdict"] == "ambiguous"
        assert result["safe_to_adopt"] is False
        assert result["origin"] == "discovered"

    def test_host_managed_clean_checkout_is_adoptable(self, tmp_path):
        checkout = _make_checkout(tmp_path / ".agent" / "skills" / "life-index")

        result = assess_checkout(checkout, checkout_origin="host_managed")

        assert result["verdict"] == "adopt"
        assert result["safe_to_adopt"] is True

    def test_user_designated_clean_checkout_is_adoptable(self, tmp_path):
        checkout = _make_checkout(tmp_path / "custom" / "life-index")

        result = assess_checkout(checkout, checkout_origin="user_designated")

        assert result["verdict"] == "adopt"
        assert result["safe_to_adopt"] is True

    def test_cross_platform_venv_is_dev_dir(self, tmp_path):
        checkout = _make_checkout(tmp_path / "skills" / "life-index")
        if sys.platform == "win32":
            (checkout / ".venv" / "bin").mkdir(parents=True)
            (checkout / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            expected_signal = "linux_venv_from_windows"
        else:
            (checkout / ".venv" / "Scripts").mkdir(parents=True)
            (checkout / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
            expected_signal = "windows_venv_from_non_windows"

        result = assess_checkout(checkout, checkout_origin="host_managed")

        assert result["verdict"] == "dev_dir"
        assert result["safe_to_adopt"] is False
        assert expected_signal in result["signals"]

    def test_projects_path_token_alone_is_only_a_hint(self, tmp_path):
        checkout = _make_checkout(tmp_path / "Projects" / "life-index")

        result = assess_checkout(checkout, checkout_origin="host_managed")

        assert result["verdict"] == "adopt"
        assert result["safe_to_adopt"] is True
        assert "dev_path_hint" in result["signals"]

    def test_projects_path_with_git_is_dev_dir(self, tmp_path):
        checkout = _make_checkout(tmp_path / "Projects" / "life-index")
        (checkout / ".git").mkdir()

        result = assess_checkout(checkout, checkout_origin="host_managed")

        assert result["verdict"] == "dev_dir"
        assert result["safe_to_adopt"] is False
        assert "dev_path_with_git" in result["signals"]

    def test_dev_tool_in_venv_is_dev_dir(self, tmp_path):
        checkout = _make_checkout(tmp_path / "skills" / "life-index")
        bin_dir = checkout / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
        bin_dir.mkdir(parents=True)
        tool = "pytest.exe" if sys.platform == "win32" else "pytest"
        (bin_dir / tool).write_text("", encoding="utf-8")

        result = assess_checkout(checkout, checkout_origin="host_managed")

        assert result["verdict"] == "dev_dir"
        assert result["safe_to_adopt"] is False
        assert "dev_package_pytest" in result["signals"]


def _state(
    has_user_data: bool,
    journal_count: int = 0,
    install_in_sync: bool | None = True,
    migration_needed: int | None = 0,
    migration_check_error: str | None = None,
    install_type: str = "editable",
    freshness: str = "current",
    latest_release: str | None = "1.2.3",
    update_available: str | None = None,
    update_reasons: list[str] | None = None,
    freshness_error: str | None = None,
    suggested_refresh_step: str | None = None,
) -> dict:
    return {
        "has_user_data": has_user_data,
        "journal_count": journal_count,
        "data_dir": "D:/data/Life-Index",
        "installed_version": "1.2.3",
        "manifest_version": "1.2.3",
        "install_in_sync": install_in_sync,
        "install_type": install_type,
        "freshness": freshness,
        "latest_release": latest_release,
        "update_available": update_available,
        "update_reasons": (
            update_reasons
            if update_reasons is not None
            else (["release"] if update_available else [])
        ),
        "freshness_error": freshness_error,
        "suggested_refresh_step": suggested_refresh_step,
        "git_freshness": "not_applicable",
        "git_upstream": None,
        "git_behind_count": None,
        "git_ahead_count": None,
        "git_error": None,
        "migration_needed": migration_needed,
        "migration_check_error": migration_check_error,
    }


def _checkout(verdict: str, safe: bool) -> dict:
    return {
        "path": "D:/checkout/life-index",
        "origin": "discovered",
        "verdict": verdict,
        "signals": [],
        "safe_to_adopt": safe,
        "reason": "reason",
    }


class TestDecideRoute:
    def test_upgrade_steps_deploy_agent_artifacts_and_indexes(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=False,
                migration_needed=0,
            )
        )

        assert result["route"] == "upgrade"
        assert result["safe_next_steps"] == [
            "life-index upgrade --plan --json",
            "life-index migrate --dry-run",
            "life-index index --rebuild",
            "life-index index-tree materialize --json",
            "life-index generate-index --all-months",
            "life-index sync-skill",
            "life-index health",
        ]
        assert not any(step.startswith("life-index entity") for step in result["safe_next_steps"])

    def test_update_available_for_editable_checkout_adds_editable_refresh_first(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=True,
                install_type="editable",
                freshness="update_available",
                latest_release="1.3.2",
                update_available="1.3.2",
            )
        )

        assert result["safe_next_steps"][0] == "life-index upgrade --plan --json"
        assert result["safe_next_steps"][-1] == "life-index health"

    def test_update_available_for_package_install_adds_package_refresh_first(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=True,
                install_type="package",
                freshness="update_available",
                latest_release="1.3.2",
                update_available="1.3.2",
            )
        )

        assert result["safe_next_steps"][0] == "life-index upgrade --plan --json"
        assert "pip install -e ." not in result["safe_next_steps"]
        assert result["safe_next_steps"][-1] == "life-index health"

    def test_suggested_refresh_step_overrides_install_type_default(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=True,
                install_type="package",
                freshness="update_available",
                update_available="git-behind",
                update_reasons=["git_behind"],
                suggested_refresh_step="git pull --ff-only && pip install -e .",
            )
        )

        assert result["safe_next_steps"][0] == "life-index upgrade --plan --json"

    def test_local_version_mismatch_uses_package_refresh_for_package_install(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=False,
                install_type="package",
            )
        )

        assert result["safe_next_steps"][0] == "life-index upgrade --plan --json"
        assert "pip install -e ." not in result["safe_next_steps"]

    def test_local_version_mismatch_uses_editable_refresh_for_editable_install(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=False,
                install_type="editable",
            )
        )

        assert result["safe_next_steps"][0] == "life-index upgrade --plan --json"
        assert result["safe_next_steps"].count("life-index upgrade --plan --json") == 1

    def test_no_user_data_routes_fresh_install_suggests_health(self):
        result = decide_route(_state(has_user_data=False))

        assert result["route"] == "fresh_install"
        assert result["route_reason"] == "No existing journal data found"
        assert result["needs_human"] == []
        # fresh_install must still verify the install runs, not declare "complete"
        # with zero checks; health is the floor (empty data => degraded is OK).
        assert result["safe_next_steps"] == ["life-index health"]

    def test_existing_data_routes_upgrade(self):
        result = decide_route(_state(has_user_data=True, journal_count=12))

        assert result["route"] == "upgrade"
        assert "12 journal" in result["route_reason"]

    def test_upgrade_steps_sync_migration_then_health(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=2,
                install_in_sync=False,
                migration_needed=2,
            )
        )

        assert result["safe_next_steps"][0] == "life-index upgrade --plan --json"
        assert result["safe_next_steps"][1] == "life-index migrate --dry-run"
        assert result["safe_next_steps"][2] == "life-index migrate --apply"
        assert "life-index index --rebuild" in result["safe_next_steps"]
        assert "life-index sync-skill" in result["safe_next_steps"]
        assert result["safe_next_steps"][-1] == "life-index health"

    def test_migration_check_failure_needs_human_and_keeps_health_last(self):
        result = decide_route(
            _state(
                has_user_data=True,
                journal_count=1,
                migration_needed=None,
                migration_check_error="scan failed",
            )
        )

        assert any(item["code"] == "MIGRATION_CHECK_FAILED" for item in result["needs_human"])
        assert "life-index migrate --dry-run" in result["safe_next_steps"]
        assert result["safe_next_steps"][-1] == "life-index health"

    def test_ambiguous_checkout_needs_human(self):
        result = decide_route(
            _state(has_user_data=False),
            checkout_assessment=_checkout("ambiguous", False),
        )

        assert any(item["code"] == "AMBIGUOUS_CHECKOUT" for item in result["needs_human"])

    def test_dev_dir_checkout_needs_human(self):
        result = decide_route(
            _state(has_user_data=False),
            checkout_assessment=_checkout("dev_dir", False),
        )

        assert any(item["code"] == "DEV_DIR_FOUND" for item in result["needs_human"])

    def test_invalid_checkout_needs_human(self):
        result = decide_route(
            _state(has_user_data=False),
            checkout_assessment=_checkout("invalid", False),
        )

        invalid = next(item for item in result["needs_human"] if item["code"] == "INVALID_CHECKOUT")
        assert "Delete and reclone" not in invalid["suggested_action"]
        assert "Leave this path untouched" in invalid["suggested_action"]
        assert "fresh dedicated install" in invalid["suggested_action"]

    def test_adoptable_checkout_does_not_need_human(self):
        result = decide_route(
            _state(has_user_data=False),
            checkout_assessment=_checkout("adopt", True),
        )

        assert result["needs_human"] == []

    def test_result_keys_are_exact(self):
        result = decide_route(_state(has_user_data=False))

        assert set(result) == {
            "route",
            "route_reason",
            "execution_policy",
            "needs_human",
            "safe_next_steps",
        }
        assert result["execution_policy"]["safe_next_steps"] == "run_in_order_without_additions"


class TestBuildBootstrapResult:
    def test_result_top_level_keys_are_exact(self, monkeypatch):
        monkeypatch.setattr(_mod, "detect_data_state", lambda data_dir=None: _state(False))

        result = build_bootstrap_result(data_dir="D:/data/Life-Index")

        assert set(result) == {
            "success",
            "schema_version",
            "command",
            "detected_state",
            "route",
            "route_reason",
            "execution_policy",
            "needs_human",
            "safe_next_steps",
        }
        assert "refused" not in result

    def test_result_envelope_uses_public_schema(self, monkeypatch):
        monkeypatch.setattr(_mod, "detect_data_state", lambda data_dir=None: _state(False))

        result = build_bootstrap_result(data_dir="D:/data/Life-Index")

        assert result["success"] is True
        assert result["schema_version"] == BOOTSTRAP_SCHEMA_VERSION
        assert result["command"] == "bootstrap"

    def test_checkout_origin_is_passed_to_assessment(self, monkeypatch):
        calls = []
        assessment = _checkout("adopt", True)
        monkeypatch.setattr(_mod, "detect_data_state", lambda data_dir=None: _state(False))

        def fake_assess(path: Path, checkout_origin: str):
            calls.append((path, checkout_origin))
            return assessment

        monkeypatch.setattr(_mod, "assess_checkout", fake_assess)

        result = build_bootstrap_result(
            data_dir="D:/data/Life-Index",
            checkout_path="D:/checkout/life-index",
            checkout_origin="user_designated",
        )

        assert calls == [(Path("D:/checkout/life-index"), "user_designated")]
        assert result["detected_state"]["checkout_assessment"] == assessment
