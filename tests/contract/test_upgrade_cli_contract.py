from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_upgrade_help_is_text_and_does_not_emit_json() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tools", "upgrade", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
    assert "upgrade" in result.stdout
    try:
        json.loads(result.stdout)
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("upgrade --help unexpectedly emitted JSON")


def test_upgrade_plan_json_stdout_is_parseable(monkeypatch, capsys) -> None:
    from tools.upgrade import __main__ as upgrade_cli
    from tools.upgrade.core import InstallContext, ReleaseInfo

    monkeypatch.setattr(
        upgrade_cli,
        "detect_install_context",
        lambda: InstallContext(
            package_version="1.4.4",
            manifest_version="1.4.4",
            install_type="package",
            repo_path=None,
        ),
    )
    monkeypatch.setattr(
        upgrade_cli,
        "PyPIReleaseProvider",
        lambda: type("Provider", (), {"fetch": lambda self: [ReleaseInfo(version="1.4.4")]})(),
    )

    exit_code = upgrade_cli.main(["--plan", "--json"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True
    assert payload["command"] == "upgrade"
    assert payload["mode"] == "plan"


def test_upgrade_apply_reinstall_required_is_valid_v0_json_and_exit_one(
    monkeypatch,
    capsys,
) -> None:
    from jsonschema import validate

    from tools.upgrade import __main__ as upgrade_cli
    from tools.upgrade import core

    class ReadOnlyRunner:
        def run(
            self,
            command: list[str],
            *,
            cwd: Path | None = None,
            env: dict[str, str] | None = None,
        ) -> core.CommandResult:
            joined = " ".join(command)
            if "health --json" in joined:
                payload = {"success": True, "schema_version": "m16.health.v0"}
            elif "sync-skill --list --json" in joined:
                payload = {
                    "success": True,
                    "schema_version": "m35.sync_skill.v0",
                    "data": {
                        "status": "listed",
                        "action": "list",
                        "discovered": ["/tmp/host/skills/life-index"],
                        "diagnostics": [],
                    },
                }
            else:
                raise AssertionError(f"Unexpected apply command: {joined}")
            return core.CommandResult(0, json.dumps(payload), "")

    monkeypatch.setattr(
        upgrade_cli,
        "detect_install_context",
        lambda: core.InstallContext("1.4.3", "1.4.3", "package", None),
    )
    monkeypatch.setattr(
        upgrade_cli,
        "PyPIReleaseProvider",
        lambda: type(
            "Provider",
            (),
            {
                "fetch": lambda self: [
                    core.ReleaseInfo(version="1.4.3"),
                    core.ReleaseInfo(version="1.4.4"),
                ]
            },
        )(),
    )
    monkeypatch.setattr(
        upgrade_cli,
        "apply_upgrade",
        lambda **kwargs: core.apply_upgrade(**kwargs, command_runner=ReadOnlyRunner()),
    )

    exit_code = upgrade_cli.main(["--apply", "--json"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    schema = json.loads(Path("tools/upgrade/schema.json").read_text(encoding="utf-8"))
    validate(instance=payload, schema=schema["output"])
    assert payload["schema_version"] == "m36.upgrade.v0"
    assert payload["error"]["code"] == "UPGRADE_REINSTALL_REQUIRED"
    assert payload["data"]["reinstall_required"] is True
    assert payload["data"]["applied_actions"] == []
    assert payload["data"]["recommended_next_step"]["command"] is None
