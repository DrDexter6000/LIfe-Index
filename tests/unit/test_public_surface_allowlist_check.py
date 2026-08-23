from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check_public_surface_allowlist.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_public_surface_allowlist", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.blocker
def test_flags_added_path_outside_public_surface() -> None:
    checker = _load_checker()
    allowlist = checker.parse_allowlist(
        "\n".join(
            [
                "README.md",
                "tools/**",
                "docs/API.md",
            ]
        )
    )

    violations = checker.find_disallowed_paths(
        ["docs/rfc/new-private-process.md", "tools/search.py"],
        allowlist,
    )

    assert violations == ["docs/rfc/new-private-process.md"]


@pytest.mark.blocker
def test_allows_added_path_matching_public_surface() -> None:
    checker = _load_checker()
    allowlist = checker.parse_allowlist(
        "\n".join(
            [
                "README.md",
                "tools/**",
                "docs/API.md",
            ]
        )
    )

    assert checker.find_disallowed_paths(["README.md", "tools/new_tool.py"], allowlist) == []


@pytest.mark.blocker
def test_deny_pattern_overrides_broad_public_directory_allowance() -> None:
    checker = _load_checker()
    allowlist = checker.parse_allowlist(
        "\n".join(
            [
                "tools/**",
                "tests/**",
                ".*",
                "!.eval/**",
                "!tools/eval/golden_queries.yaml",
                "!tests/fixtures/eval/**",
            ]
        )
    )

    violations = checker.find_disallowed_paths(
        [
            "tools/eval/run_eval.py",
            "tools/eval/golden_queries.yaml",
            ".eval/golden_queries.yaml",
            "tests/fixtures/eval/local_queries.json",
            "tests/unit/test_eval_runner.py",
        ],
        allowlist,
    )

    assert violations == [
        "tools/eval/golden_queries.yaml",
        ".eval/golden_queries.yaml",
        "tests/fixtures/eval/local_queries.json",
    ]


@pytest.mark.blocker
def test_allows_new_path_when_same_pr_updates_allowlist() -> None:
    checker = _load_checker()
    allowlist = checker.parse_allowlist(
        "\n".join(
            [
                "README.md",
                "docs/API.md",
                "docs/public-runbook.md",
            ]
        )
    )

    assert checker.find_disallowed_paths(["docs/public-runbook.md"], allowlist) == []


@pytest.mark.blocker
def test_cli_paths_file_exits_nonzero_for_disallowed_and_zero_for_clean(tmp_path: Path) -> None:
    allowlist = tmp_path / "public-surface.allowlist"
    allowlist.write_text(
        "\n".join(
            [
                "README.md",
                "tools/**",
                "docs/API.md",
            ]
        ),
        encoding="utf-8",
    )
    dirty_paths = tmp_path / "dirty.txt"
    dirty_paths.write_text("docs/rfc/new-private-process.md\n", encoding="utf-8")
    clean_paths = tmp_path / "clean.txt"
    clean_paths.write_text("tools/new_tool.py\n", encoding="utf-8")

    dirty = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--allowlist",
            str(allowlist),
            "--paths-file",
            str(dirty_paths),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    clean = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--allowlist",
            str(allowlist),
            "--paths-file",
            str(clean_paths),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )

    assert dirty.returncode == 1
    assert "New public paths are not allowlisted" in dirty.stdout
    assert "docs/rfc/new-private-process.md" in dirty.stdout
    assert clean.returncode == 0
