"""Contract tests for life-index bootstrap."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _run_bootstrap(tmp_path: Path, extra_args: list[str] | None = None) -> dict:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(tmp_path / "Life-Index")
    env["LIFE_INDEX_NO_NET"] = "1"
    cmd = [sys.executable, "-m", "tools", "bootstrap", "--json"] + (extra_args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=60, encoding="utf-8")
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout)


def _make_journal(data_dir: Path, date: str = "2026-01-01") -> Path:
    jdir = data_dir / "Journals" / date[:4] / date[5:7]
    jdir.mkdir(parents=True, exist_ok=True)
    journal = jdir / f"life-index_{date}_001.md"
    journal.write_text(
        f"---\ntitle: t\ndate: {date}\ntopic: [life]\n---\nbody",
        encoding="utf-8",
    )
    return journal


def _snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestBootstrapJsonContract:
    def test_required_top_level_keys_present(self, tmp_path):
        payload = _run_bootstrap(tmp_path)
        assert set(payload) == {
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

    def test_schema_version_uses_project_family(self, tmp_path):
        payload = _run_bootstrap(tmp_path)
        assert payload["schema_version"] == "m34.bootstrap.v0"

    def test_detected_state_keys_present(self, tmp_path):
        payload = _run_bootstrap(tmp_path)
        assert set(payload["detected_state"]) == {
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
            "checkout_assessment",
        }

    def test_empty_data_dir_routes_fresh_install(self, tmp_path):
        payload = _run_bootstrap(tmp_path)
        assert payload["route"] == "fresh_install"
        assert payload["detected_state"]["has_user_data"] is False
        assert payload["safe_next_steps"][-1] == "life-index health"

    def test_existing_journal_routes_upgrade_and_suggests_health(self, tmp_path):
        data_dir = tmp_path / "Life-Index"
        _make_journal(data_dir)
        payload = _run_bootstrap(tmp_path)
        assert payload["route"] == "upgrade"
        assert payload["detected_state"]["journal_count"] == 1
        assert payload["safe_next_steps"][-1] == "life-index health"

    def test_execution_policy_makes_bootstrap_self_sufficient(self, tmp_path):
        payload = _run_bootstrap(tmp_path)

        assert payload["execution_policy"] == {
            "needs_human": "relay_items_and_stop",
            "safe_next_steps": "run_in_order_without_additions",
            "uncertain_or_failed_step": "stop_and_report_exact_output",
            "data_safety": "never_delete_or_overwrite_user_data",
            "default_recovery": "refresh_or_reinstall_code_only_then_rerun_bootstrap",
        }

    def test_discovered_checkout_is_ambiguous(self, tmp_path):
        checkout = tmp_path / "Downloads" / "life-index"
        checkout.mkdir(parents=True)
        for name in ("SKILL.md", "pyproject.toml", "bootstrap-manifest.json"):
            (checkout / name).write_text("x", encoding="utf-8")
        payload = _run_bootstrap(tmp_path, ["--checkout-path", str(checkout)])
        assessment = payload["detected_state"]["checkout_assessment"]
        assert assessment["verdict"] == "ambiguous"
        assert assessment["safe_to_adopt"] is False
        assert any(item["code"] == "AMBIGUOUS_CHECKOUT" for item in payload["needs_human"])

    def test_user_designated_checkout_is_adoptable(self, tmp_path):
        checkout = tmp_path / "chosen" / "life-index"
        checkout.mkdir(parents=True)
        for name in ("SKILL.md", "pyproject.toml", "bootstrap-manifest.json"):
            (checkout / name).write_text("x", encoding="utf-8")
        payload = _run_bootstrap(
            tmp_path,
            ["--checkout-path", str(checkout), "--checkout-origin", "user_designated"],
        )
        assessment = payload["detected_state"]["checkout_assessment"]
        assert assessment["verdict"] == "adopt"
        assert assessment["safe_to_adopt"] is True

    def test_bootstrap_does_not_modify_data_dir_files(self, tmp_path):
        data_dir = tmp_path / "Life-Index"
        _make_journal(data_dir)
        before = _snapshot(data_dir)
        payload = _run_bootstrap(tmp_path)
        after = _snapshot(data_dir)
        assert payload["success"] is True
        assert after == before
