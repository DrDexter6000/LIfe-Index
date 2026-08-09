from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class FakeReleaseProvider:
    releases: list[Any]
    error: Exception | None = None

    def fetch(self) -> list[Any]:
        if self.error is not None:
            raise self.error
        return self.releases


@dataclass
class FakeGitRunner:
    state: Any
    remote_probe: dict[str, Any] | None = None
    refreshed_state: Any | None = None
    pulled: bool = False
    refreshed: bool = False

    def inspect(self, repo_path: Path) -> Any:
        if self.refreshed and self.refreshed_state is not None:
            return self.refreshed_state
        return self.state

    def probe_remote(self, repo_path: Path) -> dict[str, Any]:
        return self.remote_probe or {"status": "current", "has_updates": False}

    def refresh_remote(self, repo_path: Path) -> Any:
        self.refreshed = True
        from tools.upgrade.core import CommandResult

        return CommandResult(returncode=0, stdout="remote refreshed\n", stderr="")

    def pull_ff_only(self, repo_path: Path) -> Any:
        self.pulled = True
        from tools.upgrade.core import CommandResult

        return CommandResult(returncode=0, stdout="fast-forward\n", stderr="")


class FakeCommandRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.sync_skill_current = True
        self.version_package = "1.4.4"
        self.version_manifest = "1.4.4"

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> Any:
        self.commands.append(command)
        from tools.upgrade.core import CommandResult

        joined = " ".join(command)
        if "health --json" in joined:
            return CommandResult(
                returncode=0,
                stdout=json.dumps({"success": True, "schema_version": "m16.health.v0"}),
                stderr="",
            )
        if "sync-skill --list --json" in joined:
            discovered = ["/tmp/host/skills/life-index"] if self.sync_skill_current else []
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "success": True,
                        "schema_version": "m35.sync_skill.v0",
                        "data": {
                            "status": "listed",
                            "action": "list",
                            "discovered": discovered,
                            "diagnostics": [],
                        },
                    }
                ),
                stderr="",
            )
        if "sync-skill --install --json" in joined:
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "success": True,
                        "schema_version": "m35.sync_skill.v0",
                        "data": {
                            "status": "installed",
                            "delivered": True,
                            "target_dir": "/tmp/host/skills/life-index",
                            "diagnostics": [],
                        },
                    }
                ),
                stderr="",
            )
        if "pip install" in joined:
            return CommandResult(returncode=0, stdout="installed\n", stderr="")
        if "--version" in joined:
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "package_version": self.version_package,
                        "bootstrap_manifest": {"repo_version": self.version_manifest},
                    }
                ),
                stderr="",
            )
        return CommandResult(returncode=0, stdout="{}\n", stderr="")


class CapturingUpgradeCommandRunner(FakeCommandRunner):
    def __init__(self, health_payload: dict[str, Any] | None = None) -> None:
        super().__init__()
        self.health_payload = health_payload
        self.invocations: list[dict[str, Any]] = []

    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> Any:
        self.invocations.append({"command": command, "cwd": cwd, "env": env})
        if "health --json" in " ".join(command) and self.health_payload is not None:
            from tools.upgrade.core import CommandResult

            return CommandResult(
                returncode=0,
                stdout=json.dumps(self.health_payload),
                stderr="",
            )
        return super().run(command, cwd=cwd)


def test_subprocess_git_runner_status_disables_optional_locks(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from tools.upgrade import core

    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command == ["git", "rev-parse", "--abbrev-ref", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, "main\n", "")
        if command == ["git", "--no-optional-locks", "status", "--porcelain"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "no upstream")

    monkeypatch.setattr(core.subprocess, "run", fake_run)

    core.SubprocessGitRunner().inspect(tmp_path)

    assert ["git", "--no-optional-locks", "status", "--porcelain"] in commands
    assert ["git", "status", "--porcelain"] not in commands


def test_plan_reports_versions_recommended_release_actions_and_json_purity() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, build_upgrade_plan

    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.3",
            manifest_version="1.4.3",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider(
            [
                ReleaseInfo(version="1.4.3"),
                ReleaseInfo(version="1.4.4"),
            ]
        ),
        command_runner=FakeCommandRunner(),
    )

    assert plan["success"] is True
    assert plan["command"] == "upgrade"
    assert plan["mode"] == "plan"
    assert plan["data"]["installed"]["package_version"] == "1.4.3"
    assert plan["data"]["installed"]["bootstrap_manifest_repo_version"] == "1.4.3"
    assert plan["data"]["pypi"]["recommended_version"] == "1.4.4"
    replacement = plan["data"]["recommended_next_step"]
    assert replacement["id"] == "reinstall_managed_environment"
    assert replacement["command"] is None
    assert replacement["safe_to_run"] is False
    assert replacement["requires_human"] is True
    json.loads(json.dumps(plan))


def test_package_apply_requires_reinstall_without_program_writes() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, apply_upgrade

    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.3",
            manifest_version="1.4.3",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider(
            [ReleaseInfo(version="1.4.3"), ReleaseInfo(version="1.4.4")]
        ),
        command_runner=runner,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["reinstall_required"] is True
    assert result["data"]["applied_actions"] == []
    assert result["data"]["onboarding"] == "AGENT_ONBOARDING.md"
    assert result["data"]["recommended_next_step"]["id"] == ("reinstall_managed_environment")
    assert result["data"]["recommended_next_step"]["command"] is None
    assert not any("pip install" in " ".join(command) for command in runner.commands)
    assert not any("sync-skill --install" in " ".join(command) for command in runner.commands)


def test_editable_apply_requires_fresh_dedicated_install_without_program_writes(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, apply_upgrade

    repo = tmp_path / "shared-checkout"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=2,
            can_fast_forward=True,
        )
    )
    runner = FakeCommandRunner()

    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=runner,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["reinstall_required"] is True
    assert result["data"]["applied_actions"] == []
    action = result["data"]["recommended_next_step"]
    assert action["id"] == "reinstall_managed_environment"
    assert action["command"] is None
    guidance = f'{action["description"]} {action["reason"]}'.lower()
    assert "leave the existing environment and checkout untouched" in guidance
    assert "fresh dedicated install" in guidance
    assert git.pulled is False
    assert git.refreshed is False
    assert not any("pip install" in " ".join(command) for command in runner.commands)
    assert not any("sync-skill --install" in " ".join(command) for command in runner.commands)


def test_dirty_git_repo_plan_warns_and_apply_fails_closed_without_pull(tmp_path: Path) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, apply_upgrade

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=True,
            dirty_count=1,
            upstream="origin/main",
            ahead_count=0,
            behind_count=0,
            can_fast_forward=False,
        )
    )

    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_DIRTY_WORKTREE"
    assert result["data"]["reinstall_required"] is False
    assert result["data"]["applied_actions"] == []
    assert result["data"]["git"]["dirty"] is True
    assert result["data"]["recommended_next_step"]["requires_human"] is True
    assert result["data"]["recommended_next_step"]["command"] == (
        "git --no-optional-locks status --short"
    )
    assert git.pulled is False


def test_clean_behind_git_repo_apply_requires_reinstall_without_fast_forward(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, apply_upgrade

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=2,
            can_fast_forward=True,
        )
    )

    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["reinstall_required"] is True
    assert result["data"]["applied_actions"] == []
    assert git.pulled is False


def test_ahead_or_diverged_git_repo_apply_requires_human(tmp_path: Path) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, apply_upgrade

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=1,
            behind_count=1,
            can_fast_forward=False,
        )
    )

    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_GIT_REQUIRES_HUMAN"
    assert result["data"]["reinstall_required"] is False
    assert result["data"]["applied_actions"] == []
    assert result["data"]["recommended_next_step"]["requires_human"] is True
    assert result["data"]["recommended_next_step"]["command"] == (
        "git --no-optional-locks status --short --branch"
    )
    assert git.pulled is False


def test_yanked_current_release_recommends_latest_non_yanked_target() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, build_upgrade_plan

    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider(
            [
                ReleaseInfo(version="1.4.4", yanked=True, yanked_reason="bad wheel"),
                ReleaseInfo(version="1.4.5", yanked=True, yanked_reason="bad metadata"),
                ReleaseInfo(version="1.4.6"),
            ]
        ),
        command_runner=FakeCommandRunner(),
    )

    assert plan["data"]["pypi"]["current_version_yanked"] is True
    assert plan["data"]["pypi"]["recommended_version"] == "1.4.6"
    assert plan["data"]["recommended_next_step"]["id"] == "reinstall_managed_environment"
    assert plan["data"]["recommended_next_step"]["command"] is None


def test_same_version_but_source_checkout_behind_recommends_fresh_install(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, build_upgrade_plan

    repo = tmp_path / "repo"
    repo.mkdir()
    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=FakeGitRunner(
            GitState(
                repo_path=repo,
                branch="main",
                dirty=False,
                dirty_count=0,
                upstream="origin/main",
                ahead_count=0,
                behind_count=3,
                can_fast_forward=True,
            )
        ),
        command_runner=FakeCommandRunner(),
    )

    assert plan["data"]["installed"]["package_version"] == "1.4.4"
    assert plan["data"]["git"]["behind_count"] == 3
    assert plan["data"]["recommended_next_step"]["id"] == ("reinstall_managed_environment")
    assert plan["data"]["recommended_next_step"]["command"] is None


def test_current_apply_does_not_run_sync_skill_install() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, apply_upgrade

    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        command_runner=runner,
    )

    assert result["success"] is True
    assert result["data"]["reinstall_required"] is False
    assert not any("sync-skill --install" in " ".join(cmd) for cmd in runner.commands)


def test_pypi_network_failure_is_partial_and_does_not_block_local_checks() -> None:
    from tools.upgrade.core import InstallContext, build_upgrade_plan

    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider([], error=TimeoutError("network down")),
        command_runner=FakeCommandRunner(),
    )

    assert plan["success"] is True
    assert plan["data"]["partial"] is True
    assert plan["data"]["pypi"]["status"] == "partial"
    assert "network down" in plan["data"]["pypi"]["error"]
    assert plan["data"]["health"]["json_parseable"] is True


def test_detect_install_context_prefers_active_checkout_root_over_noneditable_dist(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools.upgrade import core

    repo = tmp_path / "checkout"
    repo.mkdir()
    (repo / ".git").mkdir()
    manifest = repo / "bootstrap-manifest.json"
    manifest.write_text("{}", encoding="utf-8")

    class FakeDistribution:
        def read_text(self, name: str) -> str | None:
            if name == "direct_url.json":
                return json.dumps({"url": "https://example.invalid/life-index-1.4.4.whl"})
            return None

    monkeypatch.setattr(core, "REPO_BOOTSTRAP_MANIFEST_PATH", manifest)
    monkeypatch.setattr(core, "_installed_package_version", lambda: "1.4.4")
    monkeypatch.setattr(core, "get_manifest_version", lambda: "1.4.4")
    monkeypatch.setattr(core, "distribution", lambda name: FakeDistribution())

    context = core.detect_install_context()

    assert context.install_type == "editable"
    assert context.repo_path == repo


def test_apply_does_not_run_legacy_version_check() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, apply_upgrade

    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        command_runner=runner,
    )

    assert result["success"] is True
    assert result["data"]["applied_actions"] == []
    assert not any("--version" in " ".join(command) for command in runner.commands)


def test_unknown_install_with_newer_release_requires_fresh_dedicated_install() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, apply_upgrade, build_upgrade_plan

    runner = FakeCommandRunner()
    context = InstallContext(
        package_version="1.4.3",
        manifest_version="1.4.3",
        install_type="unknown",
        repo_path=None,
    )
    releases = FakeReleaseProvider([ReleaseInfo(version="1.4.3"), ReleaseInfo(version="1.4.4")])

    plan = build_upgrade_plan(
        context=context,
        release_provider=releases,
        command_runner=runner,
    )
    replacement = plan["data"]["recommended_next_step"]
    assert replacement["id"] == "reinstall_managed_environment"
    assert replacement["command"] is None
    assert "leave the existing environment and checkout untouched" in (
        replacement["description"].lower()
    )

    runner.commands.clear()
    result = apply_upgrade(
        context=context,
        release_provider=releases,
        command_runner=runner,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["reinstall_required"] is True
    assert result["data"]["applied_actions"] == []
    assert not any("pip install" in " ".join(command) for command in runner.commands)
    assert not any(
        "sync-skill --install --json" in " ".join(command) for command in runner.commands
    )


def test_remote_probe_pending_prevents_current_git_freshness(tmp_path: Path) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, build_upgrade_plan

    repo = tmp_path / "repo"
    repo.mkdir()
    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=FakeGitRunner(
            GitState(
                repo_path=repo,
                branch="main",
                dirty=False,
                dirty_count=0,
                upstream="origin/main",
                ahead_count=0,
                behind_count=0,
                can_fast_forward=False,
            ),
            remote_probe={"status": "behind_remote", "has_updates": True, "error": None},
        ),
        command_runner=FakeCommandRunner(),
    )

    assert plan["data"]["git"]["freshness"] != "current"
    assert plan["data"]["git"]["remote_probe"]["status"] == "behind_remote"
    assert plan["data"]["recommended_next_step"]["id"] == ("reinstall_managed_environment")
    assert plan["data"]["recommended_next_step"]["command"] is None


def test_apply_does_not_refresh_or_fast_forward_when_remote_probe_has_updates(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, apply_upgrade

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=0,
            can_fast_forward=False,
        ),
        remote_probe={"status": "behind_remote", "has_updates": True, "error": None},
        refreshed_state=GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=2,
            can_fast_forward=True,
        ),
    )

    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["applied_actions"] == []
    assert git.refreshed is False
    assert git.pulled is False


def test_remote_probe_unreachable_is_partial_and_not_current(tmp_path: Path) -> None:
    from tools.upgrade.core import (
        GitState,
        InstallContext,
        ReleaseInfo,
        apply_upgrade,
        build_upgrade_plan,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=0,
            can_fast_forward=False,
        ),
        remote_probe={
            "status": "unreachable",
            "has_updates": None,
            "error": "network down",
        },
    )
    context = InstallContext(
        package_version="1.4.4",
        manifest_version="1.4.4",
        install_type="editable",
        repo_path=repo,
    )
    plan = build_upgrade_plan(
        context=context,
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    assert plan["data"]["partial"] is True
    assert plan["data"]["git"]["freshness"] == "unknown"
    assert plan["data"]["git"]["remote_probe"]["error"] == "network down"
    assert plan["data"]["recommended_next_step"]["command"] == (
        "git --no-optional-locks status --short --branch"
    )

    result = apply_upgrade(
        context=context,
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )
    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REQUIRES_HUMAN"
    assert result["data"]["reinstall_required"] is False
    assert result["data"]["applied_actions"] == []


def test_editable_behind_plan_and_apply_require_fresh_install_without_writes(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import (
        GitState,
        InstallContext,
        ReleaseInfo,
        apply_upgrade,
        build_upgrade_plan,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=2,
            can_fast_forward=True,
        )
    )
    context = InstallContext(
        package_version="1.4.4",
        manifest_version="1.4.4",
        install_type="editable",
        repo_path=repo,
    )

    plan = build_upgrade_plan(
        context=context,
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    replacement_actions = [
        action
        for action in plan["data"]["actions"]
        if action["id"] == "reinstall_managed_environment"
    ]
    assert len(replacement_actions) == 1
    assert replacement_actions[0]["command"] is None
    assert replacement_actions[0]["safe_to_run"] is False
    assert replacement_actions[0]["requires_human"] is True

    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=context,
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=runner,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["applied_actions"] == []
    assert git.pulled is False
    assert not any("pip install" in " ".join(command) for command in runner.commands)


def test_editable_version_drift_recommends_reinstall_even_when_git_current(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import (
        GitState,
        InstallContext,
        ReleaseInfo,
        apply_upgrade,
        build_upgrade_plan,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    git = FakeGitRunner(
        GitState(
            repo_path=repo,
            branch="main",
            dirty=False,
            dirty_count=0,
            upstream="origin/main",
            ahead_count=0,
            behind_count=0,
            can_fast_forward=False,
        )
    )
    context = InstallContext(
        package_version="1.4.3",
        manifest_version="1.4.4",
        install_type="editable",
        repo_path=repo,
    )

    plan = build_upgrade_plan(
        context=context,
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=FakeCommandRunner(),
    )

    assert plan["data"]["recommended_next_step"]["id"] == ("reinstall_managed_environment")
    assert plan["data"]["recommended_next_step"]["command"] is None

    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=context,
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=git,
        command_runner=runner,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["applied_actions"] == []
    assert not any("pip install" in " ".join(command) for command in runner.commands)


def test_current_state_with_current_skill_has_no_recommended_next_step(tmp_path: Path) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, build_upgrade_plan

    repo = tmp_path / "repo"
    repo.mkdir()
    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=FakeGitRunner(
            GitState(
                repo_path=repo,
                branch="main",
                dirty=False,
                dirty_count=0,
                upstream="origin/main",
                ahead_count=0,
                behind_count=0,
                can_fast_forward=False,
            )
        ),
        command_runner=FakeCommandRunner(),
    )

    assert plan["data"]["recommended_next_step"]["id"] == "none"
    assert not any(action["id"] == "sync_skill_install" for action in plan["data"]["actions"])


def test_healthy_current_apply_is_truthful_noop_without_program_writes() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, apply_upgrade

    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        command_runner=runner,
    )

    assert result["success"] is True
    assert result["mode"] == "apply"
    assert result["data"]["reinstall_required"] is False
    assert result["data"]["applied_actions"] == []
    assert result["data"]["recommended_next_step"]["id"] == "none"
    assert not any("pip install" in " ".join(command) for command in runner.commands)
    assert not any("sync-skill --install" in " ".join(command) for command in runner.commands)


def test_upgrade_health_probe_uses_neutral_synthetic_environment() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, build_upgrade_plan

    runner = CapturingUpgradeCommandRunner()
    build_upgrade_plan(
        context=InstallContext(
            package_version="1.6.2",
            manifest_version="1.6.2",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.6.2")]),
        command_runner=runner,
    )

    health_call = next(
        call for call in runner.invocations if "health --json" in " ".join(call["command"])
    )
    assert health_call["cwd"] is not None
    assert health_call["env"] is not None
    assert health_call["env"]["LIFE_INDEX_VALIDATION_MODE"] == "1"
    assert Path(health_call["env"]["LIFE_INDEX_DATA_DIR"]).parent == health_call["cwd"]
    assert "PYTHONPATH" not in health_call["env"]


def test_upgrade_fails_closed_when_neutral_health_reports_version_mismatch() -> None:
    from tools.upgrade.core import InstallContext, ReleaseInfo, build_upgrade_plan

    runner = CapturingUpgradeCommandRunner(
        {
            "success": True,
            "schema_version": "m16.health.v0",
            "data": {
                "status": "degraded",
                "upgrade_freshness": {
                    "status": "warning",
                    "installed_version": "1.4.5",
                    "manifest_version": "1.4.5",
                    "freshness": "update_available",
                    "update_available": "git-behind",
                },
            },
        }
    )
    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.6.2",
            manifest_version="1.6.2",
            install_type="package",
            repo_path=None,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.6.2")]),
        command_runner=runner,
    )

    assert plan["data"]["recommended_next_step"]["id"] == "reinstall_managed_environment"
    assert "health" in plan["data"]["recommended_next_step"]["reason"].lower()


def test_missing_skill_requires_reinstall_without_sync_skill_install(tmp_path: Path) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, build_upgrade_plan

    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeCommandRunner()
    runner.sync_skill_current = False

    plan = build_upgrade_plan(
        context=InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=FakeGitRunner(
            GitState(
                repo_path=repo,
                branch="main",
                dirty=False,
                dirty_count=0,
                upstream="origin/main",
                ahead_count=0,
                behind_count=0,
                can_fast_forward=False,
            )
        ),
        command_runner=runner,
    )

    assert plan["data"]["recommended_next_step"]["id"] == ("reinstall_managed_environment")
    assert plan["data"]["recommended_next_step"]["command"] is None
    assert not any(action["id"] == "sync_skill_install" for action in plan["data"]["actions"])


def test_editable_version_inconsistency_requires_reinstall_without_command(
    tmp_path: Path,
) -> None:
    from tools.upgrade.core import GitState, InstallContext, ReleaseInfo, apply_upgrade

    repo = tmp_path / "repo"
    repo.mkdir()
    runner = FakeCommandRunner()
    result = apply_upgrade(
        context=InstallContext(
            package_version="1.4.3",
            manifest_version="1.4.4",
            install_type="editable",
            repo_path=repo,
        ),
        release_provider=FakeReleaseProvider([ReleaseInfo(version="1.4.4")]),
        git_runner=FakeGitRunner(
            GitState(
                repo_path=repo,
                branch="main",
                dirty=False,
                dirty_count=0,
                upstream="origin/main",
                ahead_count=0,
                behind_count=0,
                can_fast_forward=False,
            )
        ),
        command_runner=runner,
    )

    assert result["success"] is False
    assert result["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert result["data"]["reinstall_required"] is True
    assert result["data"]["applied_actions"] == []
    assert result["data"]["recommended_next_step"]["command"] is None
    assert not any("pip install" in " ".join(command) for command in runner.commands)
