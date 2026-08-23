#!/usr/bin/env python3
"""Contract test: unified main CLI help and unknown-command surface.

Verifies:
- `python -m tools --help` exits 0 and prints stable command names
- `python -m tools -h` exits 0 and prints stable command names
- `python -m tools help` exits 0 and prints stable command names
- Unknown command exits non-zero, prints "Unknown command: ...", and prints usage

All invocations use subprocess to test the real CLI surface, not internal
functions.  No user data is read or written.
"""

import subprocess
import sys

# Stable representative subset - not the exhaustive command list.
STABLE_COMMANDS = {
    "write",
    "search",
    "smart-search",
    "aggregate",
    "analyze",
    "journal",
    "bootstrap",
    "import",
    "index-tree",
    "health",
    "version",
    "on-this-day",
    "sync-skill",
    "upgrade",
}


def _invoke(*extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools", *extra_args],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )


def _invoke_entity(*extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools.entity", *extra_args],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )


class TestHelpSurface:
    def test_dash_dash_help_exits_0(self):
        result = _invoke("--help")
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_dash_h_exits_0(self):
        result = _invoke("-h")
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_help_subcommand_exits_0(self):
        result = _invoke("help")
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_help_outputs_stable_commands_dash_dash_help(self):
        result = _invoke("--help")
        stdout = result.stdout
        for cmd in STABLE_COMMANDS:
            assert cmd in stdout, f"Command '{cmd}' not found in --help output"

    def test_help_outputs_stable_commands_dash_h(self):
        result = _invoke("-h")
        stdout = result.stdout
        for cmd in STABLE_COMMANDS:
            assert cmd in stdout, f"Command '{cmd}' not found in -h output"

    def test_help_outputs_stable_commands_help(self):
        result = _invoke("help")
        stdout = result.stdout
        for cmd in STABLE_COMMANDS:
            assert cmd in stdout, f"Command '{cmd}' not found in help output"

    def test_help_outputs_usage_line(self):
        result = _invoke("--help")
        assert "Usage:" in result.stdout

    def test_help_outputs_run_hint(self):
        result = _invoke("--help")
        assert "Run 'life-index <command> --help'" in result.stdout

    def test_help_outputs_python_m_tools_usage_line_dash_dash_help(self):
        result = _invoke("--help")
        assert "python -m tools <command> [options]" in result.stdout

    def test_help_outputs_python_m_tools_usage_line_dash_h(self):
        result = _invoke("-h")
        assert "python -m tools <command> [options]" in result.stdout

    def test_help_outputs_python_m_tools_usage_line_help(self):
        result = _invoke("help")
        assert "python -m tools <command> [options]" in result.stdout

    def test_help_outputs_developer_mode_dash_dash_help(self):
        result = _invoke("--help")
        assert "Developer mode:" in result.stdout

    def test_help_outputs_developer_mode_dash_h(self):
        result = _invoke("-h")
        assert "Developer mode:" in result.stdout

    def test_help_outputs_developer_mode_help(self):
        result = _invoke("help")
        assert "Developer mode:" in result.stdout

    def test_help_marks_recall_as_compatibility_wrapper(self):
        result = _invoke("--help")
        assert "recall    Deprecated compatibility wrapper over search" in result.stdout
        assert "Recall search with mode selection" not in result.stdout

    def test_help_describes_smart_search_as_host_agent_scaffold(self):
        result = _invoke("--help")
        assert "smart-search  Deterministic evidence scaffold for host agents" in result.stdout
        assert "LLM orchestration" not in result.stdout

    def test_help_subcommand_does_not_claim_smart_search_llm_orchestration(self):
        result = _invoke("help")
        assert "smart-search  Deterministic evidence scaffold for host agents" in result.stdout
        assert "LLM orchestration" not in result.stdout

    def test_entity_help_removes_retired_top_level_primitives(self):
        result = _invoke_entity("--help")

        assert result.returncode == 0
        assert "Workflow gates:" in result.stdout
        assert "life-index entity build --from-journals --preview --json" in result.stdout
        assert "life-index entity profile --id ENTITY_ID --json" in result.stdout
        assert "life-index entity audit --json" in result.stdout
        assert "life-index entity maintain --normalize --preview --json" in result.stdout
        assert (
            "life-index entity maintain --delete --id ENTITY_ID --preview --json" in result.stdout
        )
        assert "Advanced primitives appendix:" in result.stdout
        assert "Advanced compatibility / high-risk primitives:" not in result.stdout
        for retired_flag in ("--seed", "--merge", "--update"):
            assert retired_flag not in result.stdout
        assert "  --delete" not in result.stdout
        assert "[--delete]" not in result.stdout


class TestHealthHelpSurface:
    def _assert_health_help_text(self, result: subprocess.CompletedProcess) -> None:
        assert result.returncode == 0, (
            f"Expected exit code 0, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        stdout = result.stdout
        assert "Usage: life-index health [options]" in stdout
        assert "--json" in stdout
        assert "--data-audit" in stdout
        assert "--cache-audit" in stdout
        assert not stdout.lstrip().startswith("{")
        assert "schema_version" not in stdout
        assert "data_directory" not in stdout

    def test_health_dash_dash_help_is_text_not_json(self):
        result = _invoke("health", "--help")
        self._assert_health_help_text(result)

    def test_health_dash_h_is_text_not_json(self):
        result = _invoke("health", "-h")
        self._assert_health_help_text(result)

    def test_health_data_audit_help_is_text_not_audit_json(self):
        result = _invoke("health", "--data-audit", "--help")
        self._assert_health_help_text(result)

    def test_health_cache_audit_help_is_text_not_audit_json(self):
        result = _invoke("health", "--cache-audit", "--help")
        self._assert_health_help_text(result)


class TestNoArgsSurface:
    def test_no_args_exits_non_zero(self):
        result = _invoke()
        assert result.returncode != 0, (
            f"Expected non-zero exit code, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_no_args_prints_usage(self):
        result = _invoke()
        assert "Usage:" in result.stdout

    def test_no_args_prints_python_m_tools_usage_line(self):
        result = _invoke()
        assert "python -m tools <command> [options]" in result.stdout

    def test_no_args_includes_stable_commands(self):
        result = _invoke()
        stdout = result.stdout
        for cmd in STABLE_COMMANDS:
            assert cmd in stdout, f"Command '{cmd}' not found in no-args output"

    def test_no_args_prints_developer_mode(self):
        result = _invoke()
        assert "Developer mode:" in result.stdout


class TestUnknownCommandSurface:
    def test_unknown_command_exits_non_zero(self):
        result = _invoke("not-a-life-index-command")
        assert result.returncode != 0, (
            f"Expected non-zero exit code, got {result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_unknown_command_prints_unknown_message(self):
        result = _invoke("not-a-life-index-command")
        assert "Unknown command: not-a-life-index-command" in result.stdout

    def test_unknown_command_prints_usage(self):
        result = _invoke("not-a-life-index-command")
        assert "Usage:" in result.stdout

    def test_unknown_command_includes_stable_commands(self):
        result = _invoke("not-a-life-index-command")
        stdout = result.stdout
        for cmd in STABLE_COMMANDS:
            assert cmd in stdout, f"Command '{cmd}' not found in unknown-command output"
