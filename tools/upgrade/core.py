from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import distribution
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen

from tools.lib.bootstrap_manifest import REPO_BOOTSTRAP_MANIFEST_PATH
from tools.lib.bootstrap_manifest import get_manifest_version

UPGRADE_SCHEMA_VERSION = "m36.upgrade.v0"
CANONICAL_ONBOARDING_PATH = "AGENT_ONBOARDING.md"
PYPI_JSON_URL = "https://pypi.org/pypi/life-index/json"
PYPI_TIMEOUT_SECONDS = 4.0


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    yanked: bool = False
    yanked_reason: str | None = None


@dataclass(frozen=True)
class InstallContext:
    package_version: str | None
    manifest_version: str | None
    install_type: str
    repo_path: Path | None = None


@dataclass(frozen=True)
class GitState:
    repo_path: Path
    branch: str | None
    dirty: bool | None
    dirty_count: int | None
    upstream: str | None
    ahead_count: int | None
    behind_count: int | None
    can_fast_forward: bool
    error: str | None = None


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class ReleaseProvider(Protocol):
    def fetch(self) -> list[ReleaseInfo]: ...


class GitRunner(Protocol):
    def inspect(self, repo_path: Path) -> GitState: ...

    def probe_remote(self, repo_path: Path) -> dict[str, Any]: ...


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult: ...


class PyPIReleaseProvider:
    def fetch(self) -> list[ReleaseInfo]:
        request = Request(PYPI_JSON_URL, headers={"Accept": "application/json"})
        with urlopen(request, timeout=PYPI_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
        releases = payload.get("releases", {})
        if not isinstance(releases, dict):
            raise ValueError("PyPI response did not contain releases")

        result: list[ReleaseInfo] = []
        for release_version, files in releases.items():
            if not isinstance(release_version, str):
                continue
            yanked = False
            reason: str | None = None
            if isinstance(files, list) and files:
                yanked = all(bool(item.get("yanked")) for item in files if isinstance(item, dict))
                reasons = [
                    item.get("yanked_reason")
                    for item in files
                    if isinstance(item, dict) and item.get("yanked_reason")
                ]
                reason = str(reasons[0]) if reasons else None
            result.append(ReleaseInfo(version=release_version, yanked=yanked, yanked_reason=reason))
        if not result:
            raise ValueError("PyPI response did not include any releases")
        return result


class SubprocessCommandRunner:
    def run(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        proc = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)


class SubprocessGitRunner:
    def _git(self, repo_path: Path, *args: str) -> CommandResult:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)

    def inspect(self, repo_path: Path) -> GitState:
        repo_path = repo_path.resolve()
        branch_result = self._git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None

        status_result = self._git(repo_path, "--no-optional-locks", "status", "--porcelain")
        dirty_error = None if status_result.returncode == 0 else status_result.stderr.strip()
        dirty_lines = [line for line in status_result.stdout.splitlines() if line.strip()]
        dirty = bool(dirty_lines) if status_result.returncode == 0 else None
        dirty_count = len(dirty_lines) if status_result.returncode == 0 else None

        upstream_result = self._git(
            repo_path,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        )
        upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else None

        ahead_count: int | None = None
        behind_count: int | None = None
        error = dirty_error
        if upstream:
            counts = self._git(repo_path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
            if counts.returncode == 0:
                raw = counts.stdout.strip().split()
                if len(raw) == 2:
                    ahead_count = int(raw[0])
                    behind_count = int(raw[1])
            else:
                error = counts.stderr.strip() or error
        else:
            error = upstream_result.stderr.strip() or error

        return GitState(
            repo_path=repo_path,
            branch=branch,
            dirty=dirty,
            dirty_count=dirty_count,
            upstream=upstream,
            ahead_count=ahead_count,
            behind_count=behind_count,
            can_fast_forward=bool(
                dirty is False
                and ahead_count == 0
                and isinstance(behind_count, int)
                and behind_count > 0
            ),
            error=error or None,
        )

    def probe_remote(self, repo_path: Path) -> dict[str, Any]:
        repo_path = repo_path.resolve()
        upstream_result = self._git(
            repo_path,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{u}",
        )
        upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else None
        if not upstream or "/" not in upstream:
            return {
                "status": "unknown",
                "has_updates": None,
                "upstream": upstream,
                "error": upstream_result.stderr.strip() or "No upstream branch configured.",
            }

        remote, branch = upstream.split("/", 1)
        head_result = self._git(repo_path, "rev-parse", "HEAD")
        local_head = head_result.stdout.strip() if head_result.returncode == 0 else None
        upstream_head_result = self._git(repo_path, "rev-parse", "@{u}")
        local_upstream_head = (
            upstream_head_result.stdout.strip() if upstream_head_result.returncode == 0 else None
        )
        remote_result = self._git(repo_path, "ls-remote", "--heads", remote, branch)
        if remote_result.returncode != 0:
            return {
                "status": "unreachable",
                "has_updates": None,
                "upstream": upstream,
                "remote": remote,
                "branch": branch,
                "local_head": local_head,
                "local_upstream_head": local_upstream_head,
                "remote_head": None,
                "error": remote_result.stderr.strip() or remote_result.stdout.strip(),
            }

        remote_head = None
        for line in remote_result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                remote_head = parts[0]
                break
        if not remote_head:
            return {
                "status": "unknown",
                "has_updates": None,
                "upstream": upstream,
                "remote": remote,
                "branch": branch,
                "local_head": local_head,
                "local_upstream_head": local_upstream_head,
                "remote_head": None,
                "error": "Remote branch was not found.",
            }

        has_updates = bool(local_head and remote_head != local_head)
        return {
            "status": "behind_remote" if has_updates else "current",
            "has_updates": has_updates,
            "upstream": upstream,
            "remote": remote,
            "branch": branch,
            "local_head": local_head,
            "local_upstream_head": local_upstream_head,
            "remote_head": remote_head,
            "error": None,
        }


def _version_tuple(version: str | None) -> tuple[int, ...] | None:
    if not version:
        return None
    parts: list[int] = []
    for raw in version.split("."):
        digits = ""
        for char in raw:
            if char.isdigit():
                digits += char
            else:
                break
        if digits == "":
            return None
        parts.append(int(digits))
    return tuple(parts)


def _is_newer(candidate: str | None, current: str | None) -> bool:
    candidate_parts = _version_tuple(candidate)
    current_parts = _version_tuple(current)
    if candidate_parts is None or current_parts is None:
        return False
    width = max(len(candidate_parts), len(current_parts))
    return candidate_parts + (0,) * (width - len(candidate_parts)) > current_parts + (0,) * (
        width - len(current_parts)
    )


def _latest_non_yanked(releases: list[ReleaseInfo]) -> ReleaseInfo | None:
    candidates = [release for release in releases if not release.yanked]
    candidates.sort(key=lambda item: _version_tuple(item.version) or ())
    return candidates[-1] if candidates else None


def _release_for_version(releases: list[ReleaseInfo], version: str | None) -> ReleaseInfo | None:
    if not version:
        return None
    for release in releases:
        if release.version == version:
            return release
    return None


def _path_from_file_url(url: str) -> Path | None:
    parsed = urlparse(url)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if sys.platform == "win32" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return Path(path)


def _installed_package_version() -> str | None:
    try:
        return package_version("life-index")
    except PackageNotFoundError:
        return None


def detect_install_context() -> InstallContext:
    package = _installed_package_version()
    manifest = get_manifest_version()
    repo_root = REPO_BOOTSTRAP_MANIFEST_PATH.parent
    repo_path: Path | None = repo_root if (repo_root / ".git").exists() else None
    if repo_path is not None:
        return InstallContext(package or manifest, manifest, "editable", repo_path)

    install_type = "unknown"

    try:
        dist = distribution("life-index")
    except PackageNotFoundError:
        return InstallContext(
            package_version=package or manifest,
            manifest_version=manifest,
            install_type=install_type,
            repo_path=repo_path,
        )

    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = {}
        dir_info = direct_url.get("dir_info")
        path = _path_from_file_url(str(direct_url.get("url", "")))
        if isinstance(dir_info, dict) and dir_info.get("editable") is True:
            return InstallContext(package, manifest, "editable", path or repo_path)
        return InstallContext(package, manifest, "package", None)

    return InstallContext(package, manifest, "package", None)


def _action(
    *,
    action_id: str,
    description: str,
    side_effect: str,
    command: str | None,
    reason: str,
    safe_to_run: bool,
    requires_human: bool,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "description": description,
        "side_effect": side_effect,
        "command": command,
        "reason": reason,
        "safe_to_run": safe_to_run,
        "requires_human": requires_human,
    }


def _git_payload(
    state: GitState | None,
    remote_probe: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if state is None:
        return None
    freshness = "current"
    if state.dirty:
        freshness = "dirty"
    elif (state.ahead_count or 0) > 0 and (state.behind_count or 0) > 0:
        freshness = "diverged"
    elif (state.ahead_count or 0) > 0:
        freshness = "ahead"
    elif (state.behind_count or 0) > 0:
        freshness = "behind"
    elif state.error:
        freshness = "unknown"
    elif remote_probe:
        remote_status = remote_probe.get("status")
        if remote_status == "behind_remote":
            freshness = "behind_remote"
        elif remote_status in {"unreachable", "unknown"}:
            freshness = "unknown"
    return {
        "repo_path": str(state.repo_path),
        "branch": state.branch,
        "upstream": state.upstream,
        "dirty": state.dirty,
        "dirty_count": state.dirty_count,
        "ahead_count": state.ahead_count,
        "behind_count": state.behind_count,
        "can_fast_forward": state.can_fast_forward,
        "freshness": freshness,
        "error": state.error,
        "remote_probe": remote_probe,
    }


def _run_json_check(
    command_runner: CommandRunner,
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    result = command_runner.run(command, cwd=cwd, env=env)
    parsed: Any = None
    parse_error: str | None = None
    if result.stdout:
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    return {
        "command": " ".join(_display_command(command)),
        "returncode": result.returncode,
        "json_parseable": parse_error is None and parsed is not None,
        "parse_error": parse_error,
        "data": parsed,
    }


def _health_upgrade_versions(health_status: dict[str, Any]) -> tuple[str | None, str | None]:
    payload = health_status.get("data")
    if not isinstance(payload, dict):
        return None, None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, None
    freshness = data.get("upgrade_freshness")
    if not isinstance(freshness, dict):
        return None, None
    installed = freshness.get("installed_version")
    manifest = freshness.get("manifest_version")
    return (
        installed if isinstance(installed, str) else None,
        manifest if isinstance(manifest, str) else None,
    )


def _display_command(command: list[str]) -> list[str]:
    if len(command) >= 3 and command[1:3] == ["-m", "tools"]:
        return ["life-index", *command[3:]]
    if len(command) >= 3 and command[1:3] == ["-m", "pip"]:
        return ["python", "-m", "pip", *command[3:]]
    return command


def _sync_skill_list_current(sync_skill_status: dict[str, Any]) -> bool:
    if not sync_skill_status.get("json_parseable"):
        return False
    payload = sync_skill_status.get("data")
    if not isinstance(payload, dict):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    if data.get("status") != "listed":
        return False
    discovered = data.get("discovered")
    if not isinstance(discovered, list):
        return False
    canonical = [
        item
        for item in discovered
        if isinstance(item, str) and item.replace("\\", "/").endswith("skills/life-index")
    ]
    return len(canonical) == 1 and len(discovered) == 1


def _reinstall_action(reasons: list[str]) -> dict[str, Any]:
    return _action(
        action_id="reinstall_managed_environment",
        description=(
            "Leave the existing environment and checkout untouched; create a fresh "
            "dedicated install."
        ),
        side_effect="write",
        command=None,
        reason=" ".join(reasons) + f" Follow {CANONICAL_ONBOARDING_PATH}.",
        safe_to_run=False,
        requires_human=True,
    )


def build_upgrade_plan(
    *,
    context: InstallContext | None = None,
    release_provider: ReleaseProvider | None = None,
    git_runner: GitRunner | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    context = context or detect_install_context()
    release_provider = release_provider or PyPIReleaseProvider()
    git_runner = git_runner or SubprocessGitRunner()
    command_runner = command_runner or SubprocessCommandRunner()
    current = context.package_version or context.manifest_version

    pypi_error: str | None = None
    releases: list[ReleaseInfo] = []
    try:
        releases = release_provider.fetch()
    except Exception as exc:
        pypi_error = str(exc)

    latest = _latest_non_yanked(releases)
    current_release = _release_for_version(releases, current)
    recommended_version: str | None = None
    if latest and (
        current_release and current_release.yanked or _is_newer(latest.version, current)
    ):
        recommended_version = latest.version

    git_state: GitState | None = None
    remote_probe: dict[str, Any] | None = None
    if context.repo_path is not None:
        git_state = git_runner.inspect(context.repo_path)
        remote_probe = git_runner.probe_remote(context.repo_path)

    actions: list[dict[str, Any]] = []
    git_payload = _git_payload(git_state, remote_probe)
    with tempfile.TemporaryDirectory(prefix="life-index-upgrade-probe-") as probe_root_raw:
        probe_root = Path(probe_root_raw)
        probe_env = os.environ.copy()
        probe_env.pop("PYTHONPATH", None)
        probe_env["LIFE_INDEX_VALIDATION_MODE"] = "1"
        probe_env["LIFE_INDEX_DATA_DIR"] = str(probe_root / "data")
        health_status = _run_json_check(
            command_runner,
            [sys.executable, "-m", "tools", "health", "--json"],
            cwd=probe_root,
            env=probe_env,
        )
        sync_skill_status = _run_json_check(
            command_runner,
            [sys.executable, "-m", "tools", "sync-skill", "--list", "--json"],
            cwd=probe_root,
            env=probe_env,
        )
    reinstall_reasons: list[str] = []

    if git_state and git_state.dirty:
        actions.append(
            _action(
                action_id="resolve_dirty_worktree",
                description=(
                    "Leave the existing environment and checkout untouched; inspect "
                    "the uncommitted changes with the owner."
                ),
                side_effect="read",
                command="git --no-optional-locks status --short",
                reason="A dirty checkout is human-owned state and must not be mutated.",
                safe_to_run=False,
                requires_human=True,
            )
        )
    elif git_state and ((git_state.ahead_count or 0) > 0):
        actions.append(
            _action(
                action_id="git_requires_human",
                description=(
                    "Leave the existing environment and checkout untouched; inspect "
                    "the local commits with the owner."
                ),
                side_effect="read",
                command="git --no-optional-locks status --short --branch",
                reason="Ahead or diverged checkouts require human review.",
                safe_to_run=False,
                requires_human=True,
            )
        )
    elif git_state and (git_state.behind_count or 0) > 0:
        reinstall_reasons.append("The source checkout is behind its upstream ref.")
    elif git_state and remote_probe and remote_probe.get("status") == "behind_remote":
        reinstall_reasons.append(
            "The remote branch has commits not visible in local tracking refs."
        )
    elif git_state and remote_probe and remote_probe.get("status") in {"unreachable", "unknown"}:
        actions.append(
            _action(
                action_id="inspect_git_remote",
                description=(
                    "Leave the existing environment and checkout untouched; inspect "
                    "remote freshness before creating a fresh dedicated install."
                ),
                side_effect="read",
                command="git --no-optional-locks status --short --branch",
                reason=remote_probe.get("error") or "Remote freshness could not be verified.",
                safe_to_run=False,
                requires_human=True,
            )
        )

    version_inconsistent = bool(
        context.package_version
        and context.manifest_version
        and context.package_version != context.manifest_version
    )
    if version_inconsistent:
        reinstall_reasons.append("Installed package metadata differs from the bootstrap manifest.")

    if recommended_version:
        reinstall_reasons.append(
            "A newer non-yanked PyPI release requires program-environment replacement."
        )

    if not health_status.get("json_parseable") or health_status.get("returncode") != 0:
        reinstall_reasons.append("The installed health command is not healthy and parseable.")

    health_installed, health_manifest = _health_upgrade_versions(health_status)
    if (
        health_installed and context.package_version and health_installed != context.package_version
    ) or (
        health_manifest and context.manifest_version and health_manifest != context.manifest_version
    ):
        reinstall_reasons.append(
            "The isolated health probe reports different installed version truth than "
            "the upgrade process."
        )

    if not _sync_skill_list_current(sync_skill_status):
        reinstall_reasons.append("The installed agent playbook is not current and canonical.")

    if reinstall_reasons:
        actions.append(_reinstall_action(reinstall_reasons))

    actions.append(
        _action(
            action_id="health_json_check",
            description="Verify health JSON is parseable.",
            side_effect="read",
            command="life-index health --json",
            reason="Upgrade diagnostics require a parseable health surface.",
            safe_to_run=True,
            requires_human=False,
        )
    )
    recommended_next_step = next((action for action in actions if not action["safe_to_run"]), None)
    if recommended_next_step is None:
        recommended_next_step = next(
            (action for action in actions if action["side_effect"] == "write"), None
        )
    if recommended_next_step is None:
        recommended_next_step = {
            "id": "none",
            "description": "No upgrade action is currently recommended.",
            "side_effect": "read",
            "command": None,
            "reason": "Life Index appears current.",
            "safe_to_run": True,
            "requires_human": False,
        }

    return {
        "success": True,
        "schema_version": UPGRADE_SCHEMA_VERSION,
        "command": "upgrade",
        "mode": "plan",
        "data": {
            "installed": {
                "package_version": context.package_version,
                "bootstrap_manifest_repo_version": context.manifest_version,
                "install_type": context.install_type,
                "repo_path": str(context.repo_path) if context.repo_path else None,
            },
            "pypi": {
                "status": "partial" if pypi_error else "ok",
                "error": pypi_error,
                "latest_non_yanked": latest.version if latest else None,
                "recommended_version": recommended_version,
                "current_version_yanked": (
                    bool(current_release.yanked) if current_release else False
                ),
                "current_yanked_reason": current_release.yanked_reason if current_release else None,
            },
            "git": git_payload,
            "health": health_status,
            "sync_skill": sync_skill_status,
            "onboarding": CANONICAL_ONBOARDING_PATH,
            "actions": actions,
            "recommended_next_step": recommended_next_step,
            "partial": bool(
                pypi_error
                or (
                    remote_probe is not None
                    and remote_probe.get("status") in {"unreachable", "unknown"}
                )
            ),
        },
    }


def _error_result(
    code: str,
    message: str,
    plan: dict[str, Any],
    extra_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = dict(plan["data"])
    if extra_data:
        data.update(extra_data)
    return {
        "success": False,
        "schema_version": UPGRADE_SCHEMA_VERSION,
        "command": "upgrade",
        "mode": "apply",
        "error": {"code": code, "message": message},
        "data": data,
    }


def apply_upgrade(
    *,
    context: InstallContext | None = None,
    release_provider: ReleaseProvider | None = None,
    git_runner: GitRunner | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    context = context or detect_install_context()
    git_runner = git_runner or SubprocessGitRunner()
    command_runner = command_runner or SubprocessCommandRunner()
    plan = build_upgrade_plan(
        context=context,
        release_provider=release_provider,
        git_runner=git_runner,
        command_runner=command_runner,
    )
    git_data = plan["data"].get("git")
    no_write_data = {"reinstall_required": False, "applied_actions": []}

    if isinstance(git_data, dict) and git_data.get("dirty") is True:
        return _error_result(
            "UPGRADE_DIRTY_WORKTREE",
            "Refusing to upgrade a dirty source checkout.",
            plan,
            no_write_data,
        )
    if isinstance(git_data, dict) and int(git_data.get("ahead_count") or 0) > 0:
        return _error_result(
            "UPGRADE_GIT_REQUIRES_HUMAN",
            "Refusing to upgrade an ahead or diverged source checkout.",
            plan,
            no_write_data,
        )

    reinstall_required = any(
        action.get("id") == "reinstall_managed_environment"
        for action in plan["data"].get("actions", [])
    )
    if reinstall_required:
        return _error_result(
            "UPGRADE_REINSTALL_REQUIRED",
            "The program environment must be replaced through the canonical onboarding path.",
            plan,
            {
                "reinstall_required": True,
                "applied_actions": [],
                "onboarding": CANONICAL_ONBOARDING_PATH,
            },
        )

    blocking_actions = [
        action
        for action in plan["data"].get("actions", [])
        if action.get("safe_to_run") is False or action.get("requires_human") is True
    ]
    if blocking_actions:
        return _error_result(
            "UPGRADE_REQUIRES_HUMAN",
            "Refusing to apply while the read-only plan requires human review.",
            plan,
            {
                **no_write_data,
                "blocking_actions": blocking_actions,
            },
        )

    return {
        "success": True,
        "schema_version": UPGRADE_SCHEMA_VERSION,
        "command": "upgrade",
        "mode": "apply",
        "data": {
            **plan["data"],
            **no_write_data,
        },
    }
