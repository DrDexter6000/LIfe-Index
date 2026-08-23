from __future__ import annotations

import builtins
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_EVAL_RUNTIME_IMPORTS = (
    "tools.eval.run_eval",
    "tools.eval.private_data",
    "tools.eval.overlay",
    "tools.lib.config",
    "tools.lib.observability",
    "tools.eval.llm_client",
    "openai",
    "anthropic",
)
EXPECTED_LANGUAGE_JUDGE_ERROR = {
    "success": False,
    "error": {
        "code": "EVAL_LLM_JUDGE_HOST_AGENT_REQUIRED",
        "message": ("Language-assisted evaluation belongs to the Host Agent + Life Index Skill."),
    },
}


def _guarded_python(
    source: str,
    *,
    forbidden_imports: tuple[str, ...] = FORBIDDEN_EVAL_RUNTIME_IMPORTS,
) -> subprocess.CompletedProcess[str]:
    forbidden = repr(forbidden_imports)
    probe = f"""
import importlib.abc
import runpy
import sys

FORBIDDEN = {forbidden}

class BlockForbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == name or fullname.startswith(name + '.') for name in FORBIDDEN):
            raise AssertionError('forbidden import: ' + fullname)
        return None

sys.meta_path.insert(0, BlockForbidden())
{source}
"""
    return subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("entry_source", "entry_name"),
    (
        (
            "sys.argv = ['life-index', '--judge', 'llm', '--json']; "
            "runpy.run_module('tools.eval.__main__', run_name='__main__')",
            "python -m tools.eval",
        ),
        (
            "sys.argv = ['life-index', 'eval', '--judge', 'llm', '--json']; "
            "runpy.run_module('tools', run_name='__main__')",
            "python -m tools eval",
        ),
        (
            "sys.argv = ['life-index', 'eval', '--judge', 'llm', '--json']; "
            "from tools.__main__ import main; main()",
            "console entrypoint",
        ),
    ),
)
def test_language_judge_rejects_before_every_eval_runtime_import(
    entry_source: str,
    entry_name: str,
) -> None:
    result = _guarded_python(entry_source)

    assert result.returncode == 2, entry_name + "\n" + result.stdout + result.stderr
    assert json.loads(result.stdout) == EXPECTED_LANGUAGE_JUDGE_ERROR
    assert "forbidden import" not in result.stderr


ENTRYPOINTS = (
    (
        "sys.argv = ['life-index', *ARGS]; "
        "runpy.run_module('tools.eval.__main__', run_name='__main__')",
        "python -m tools.eval",
    ),
    (
        "sys.argv = ['life-index', 'eval', *ARGS]; "
        "runpy.run_module('tools', run_name='__main__')",
        "python -m tools eval",
    ),
    (
        "sys.argv = ['life-index', 'eval', *ARGS]; " "from tools.__main__ import main; main()",
        "console entrypoint",
    ),
)


@pytest.mark.parametrize(("entry_source", "entry_name"), ENTRYPOINTS)
@pytest.mark.parametrize(
    ("args", "rejects"),
    (
        (["--judge", "llm", "--judge", "keyword"], False),
        (["--judge", "keyword", "--judge", "llm"], True),
        (["--judge=llm", "--judge", "keyword"], False),
        (["--judge", "keyword", "--judge=llm"], True),
    ),
)
def test_repeated_judge_final_occurrence_wins_before_heavy_imports(
    entry_source: str,
    entry_name: str,
    args: list[str],
    rejects: bool,
) -> None:
    source = "ARGS = " + repr(args) + "\n" + entry_source
    result = _guarded_python(source)

    if rejects:
        assert result.returncode == 2, entry_name + result.stdout + result.stderr
        assert json.loads(result.stdout) == EXPECTED_LANGUAGE_JUDGE_ERROR
        assert "forbidden import" not in result.stderr
    else:
        assert result.returncode != 2
        assert "forbidden import" in result.stderr


def test_run_evaluation_language_judge_rejects_before_runtime_module_imports() -> None:
    result = _guarded_python(
        "from tools.eval.run_eval import run_evaluation\n"
        "try:\n"
        "    run_evaluation(judge='llm')\n"
        "except ValueError as exc:\n"
        "    print(str(exc))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(9)",
        forbidden_imports=tuple(
            name for name in FORBIDDEN_EVAL_RUNTIME_IMPORTS if name != "tools.eval.run_eval"
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "only deterministic keyword evaluation is supported"
    assert "forbidden import" not in result.stderr


def test_run_evaluation_language_judge_rejects_before_loaders_or_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools.eval import run_eval

    def explode(*_args, **_kwargs):
        raise AssertionError("eval loader or side effect must not run")

    for name in (
        "_get_eval_anchor_date",
        "_inject_eval_anchor",
        "eval_query_set_available",
        "_load_queries_with_overlay",
        "load_aggregate_queries",
        "load_smart_aggregate_queries",
        "load_timeline_queries",
        "_temporary_data_dir",
        "_live_data_dir",
    ):
        monkeypatch.setattr(run_eval, name, explode)

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {
            "tools.eval.overlay",
            "tools.eval.private_data",
            "tools.lib.config",
        }:
            raise AssertionError("runtime import must follow judge validation")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(
        ValueError,
        match="only deterministic keyword evaluation is supported",
    ):
        run_eval.run_evaluation(judge="llm")


def test_eval_cli_llm_judge_fails_fast_without_loading_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools.eval import __main__ as eval_main

    provider_import_attempts: list[str] = []

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name in {"tools.eval.llm_client", "openai", "anthropic"}:
            provider_import_attempts.append(name)
            raise AssertionError("provider module must not be imported")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    exit_code = eval_main.main(["--judge", "llm", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code != 0
    assert payload == EXPECTED_LANGUAGE_JUDGE_ERROR
    assert captured.err == ""
    assert provider_import_attempts == []


def test_unified_cli_llm_judge_fails_before_config_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real_import = builtins.__import__
    config_import_attempts: list[str] = []

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tools.lib.config":
            config_import_attempts.append(name)
            raise AssertionError("eval compatibility failure must precede config import")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "tools.lib.config", raising=False)
    monkeypatch.setattr(sys, "argv", ["life-index", "eval", "--judge", "llm", "--json"])
    monkeypatch.setattr(builtins, "__import__", guarded_import)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("tools", run_name="__main__")

    assert exc_info.value.code == 2
    assert config_import_attempts == []
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "EVAL_LLM_JUDGE_HOST_AGENT_REQUIRED"


def test_eval_gate_guidance_uses_current_host_agent_advisory_route() -> None:
    source = (REPO_ROOT / "scripts" / "run_eval_advisory.sh").read_text(encoding="utf-8")

    assert "--live --judge llm" not in source
    assert "Host Agent" in source
    assert "life-index eval --judge keyword" in source
