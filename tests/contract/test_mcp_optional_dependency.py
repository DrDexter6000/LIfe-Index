"""Optional MCP dependency isolation contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _blocked_mcp_env(tmp_path: Path, data_dir: Path) -> dict[str, str]:
    blocker = tmp_path / "blocked-mcp"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(
        """
import builtins
_original_import = builtins.__import__
def _block_mcp(name, globals=None, locals=None, fromlist=(), level=0):
    if name == 'mcp' or name.startswith('mcp.'):
        raise ModuleNotFoundError("blocked optional dependency: mcp")
    return _original_import(name, globals, locals, fromlist, level)
builtins.__import__ = _block_mcp
""".strip(),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(blocker), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    env["LIFE_INDEX_VALIDATION_MODE"] = "1"
    return env


def _run_blocked(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
        encoding="utf-8",
    )


def _seed_journal(data_dir: Path) -> str:
    path = data_dir / "Journals" / "2026" / "05" / "life-index_2026-05-28_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '---\ntitle: "optional dependency"\ndate: 2026-05-28\n---\nneedle\n',
        encoding="utf-8",
    )
    return path.relative_to(data_dir).as_posix()


def test_mcp_is_an_exact_optional_extra_not_a_base_dependency() -> None:
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = config["project"]["dependencies"]
    extras = config["project"]["optional-dependencies"]

    assert all(not dependency.startswith("mcp") for dependency in dependencies)
    assert extras["mcp"] == ["mcp==1.27.2"]


@pytest.mark.parametrize(
    "command",
    [
        ("-c", "import tools; import tools.__main__; print('base-import-ok')"),
        ("-m", "tools", "health"),
        (
            "-m",
            "tools",
            "journal",
            "get",
            "--path",
            "Journals/2026/05/life-index_2026-05-28_001.md",
        ),
        ("-m", "tools", "search", "--query", "needle"),
    ],
)
def test_ordinary_base_operations_work_when_mcp_cannot_import(
    tmp_path: Path,
    command: tuple[str, ...],
) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_journal(data_dir)
    result = _run_blocked(_blocked_mcp_env(tmp_path, data_dir), *command)

    assert result.returncode == 0, result.stderr
    if command[0] == "-c":
        assert result.stdout.strip() == "base-import-ok"
    else:
        payload = json.loads(result.stdout)
        assert payload["success"] is True


def test_projection_import_stays_lazy_when_mcp_cannot_import(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    code = """
import sys
import tools
import tools.__main__
from tools.mcp_projection.server import OptionalMcpDependencyError, create_mcp_server
assert not any(name == 'mcp' or name.startswith('mcp.') for name in sys.modules)
try:
    create_mcp_server()
except OptionalMcpDependencyError:
    print('projection-optional-ok')
else:
    raise AssertionError('projection unexpectedly initialized')
"""

    result = _run_blocked(_blocked_mcp_env(tmp_path, data_dir), "-c", code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "projection-optional-ok"
