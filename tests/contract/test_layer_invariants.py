"""Contract tests for Foundation Freeze layer invariants.

These tests are intentionally static and dependency-light.  They guard the
project structure that keeps L2 deterministic while allowing explicit L3 /
developer-only LLM entry points.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import stat
import subprocess
from uuid import uuid4

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COVERAGE_GATE_RUNNER = REPO_ROOT / "scripts" / "run_coverage_gate.sh"

L2_PRODUCTION_ROOTS = (
    REPO_ROOT / "tools" / "aggregate",
    REPO_ROOT / "tools" / "backup",
    REPO_ROOT / "tools" / "build_index",
    REPO_ROOT / "tools" / "edit_journal",
    REPO_ROOT / "tools" / "entity",
    REPO_ROOT / "tools" / "evidence",
    REPO_ROOT / "tools" / "generate_index",
    REPO_ROOT / "tools" / "lib",
    REPO_ROOT / "tools" / "migrate",
    REPO_ROOT / "tools" / "query_weather",
    REPO_ROOT / "tools" / "search_journals",
    REPO_ROOT / "tools" / "timeline",
    REPO_ROOT / "tools" / "verify",
    REPO_ROOT / "tools" / "write_journal",
)

L2_ALLOWED_FILES = {
    # L3 orchestrator lives beside search primitives for historical import
    # compatibility, but it is the explicit intelligence-layer boundary.
    REPO_ROOT
    / "tools"
    / "search_journals"
    / "orchestrator.py",
}

# Deterministic L2 module roots that MUST be covered by layer-invariant tests.
# Every tool module that is purely deterministic (no LLM calls, no L3 orchestration)
# must appear here so that the invariant scan covers it.
REQUIRED_L2_ROOTS = {
    "aggregate",
    "backup",
    "build_index",
    "edit_journal",
    "entity",
    "evidence",
    "generate_index",
    "lib",
    "migrate",
    "query_weather",
    "search_journals",
    "timeline",
    "verify",
    "write_journal",
}

DISALLOWED_PROVIDER_IMPORTS = {
    "anthropic",
    "openai",
}

DISALLOWED_L3_IMPORTS = {
    "tools.smart_search",
    "tools.search_journals.orchestrator",
}

# L2 modules that must not import from L3 packages even if they are in
# L2_ALLOWED_FILES (whitelisted for other reasons).  This catches upward
# dependencies that the generic _production_l2_files scan skips.
L2_STRICT_L3_FREE_FILES = {
    REPO_ROOT / "tools" / "search_journals" / "orchestrator.py",
}


def _production_l2_files() -> list[Path]:
    files: list[Path] = []
    for root in L2_PRODUCTION_ROOTS:
        files.extend(path for path in root.rglob("*.py") if path not in L2_ALLOWED_FILES)
    return sorted(files)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_contract_gate_is_hard_required_check() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    )
    contract_job = workflow["jobs"]["contract"]

    assert contract_job.get("continue-on-error") is not True


def _workflow(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / path).read_text(encoding="utf-8"))


def _workflow_on(workflow: dict) -> dict:
    # PyYAML follows YAML 1.1 and parses the GitHub Actions "on" key as True.
    return workflow.get("on") or workflow.get(True)


def _coverage_gate_bash() -> str:
    """Locate a real Bash without hard-coding an operator-specific Windows path."""
    if os.name != "nt":
        bash = shutil.which("bash")
        if bash:
            return bash
        pytest.skip("bash is required for the coverage-gate subprocess seam")

    git = shutil.which("git")
    if git:
        for root in Path(git).resolve().parents:
            candidate = root / "bin" / "bash.exe"
            if candidate.is_file():
                return str(candidate)

    bash = shutil.which("bash")
    if bash and Path(bash).resolve().parent.name.lower() != "system32":
        return bash
    pytest.skip("Git Bash is required for the Windows coverage-gate subprocess seam")


def _write_test_python_stub(tmp_path: Path) -> Path:
    stub_dir = tmp_path / "coverage-gate-stub-bin"
    stub_dir.mkdir()
    stub = stub_dir / "python"
    stub.write_text(
        """#!/usr/bin/env bash
set -eu

if [ "${1:-}" = "-" ]; then
    cat >/dev/null
    printf '%s\n' '__GATE_PYTHON_DEPENDENCY_PROBE__'
    exit 0
fi

if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pytest" ]; then
    printf '%s\\n' '__COVERAGE_GATE_STUB_ARGS__'
    printf '%s\\n' "$@"
    printf '%s\\n' '__COVERAGE_GATE_STUB_ENV__'
    printf 'LIFE_INDEX_DATA_DIR=%s\\n' "${LIFE_INDEX_DATA_DIR:-}"
    printf 'COVERAGE_FILE=%s\\n' "${COVERAGE_FILE:-}"
    exit 0
fi

printf 'unexpected stub python invocation: %s\\n' "$*" >&2
exit 64
""",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub_dir


def _coverage_gate_env(stub_dir: Path, basetemp: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = str(stub_dir) + os.pathsep + env.get("PATH", "")
    # If a platform cannot resolve the stub, fail before test collection rather
    # than accidentally executing the real coverage inventory.
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["COVERAGE_GATE_BASETEMP"] = basetemp
    return env


def _run_coverage_gate(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_coverage_gate_bash(), "scripts/run_coverage_gate.sh"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        encoding="utf-8",
    )


def _run_pre_push_env_check(env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [_coverage_gate_bash(), "scripts/pre-push-gate.sh", "--check-env"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )


def _reported_coverage_basetemp(output: str) -> str:
    prefix = "Using pytest basetemp: "
    for line in output.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    raise AssertionError(f"coverage runner did not report a pytest basetemp:\n{output}")


def _stubbed_pytest_capture(output: str) -> tuple[list[str], dict[str, str]]:
    lines = output.splitlines()
    args_marker = lines.index("__COVERAGE_GATE_STUB_ARGS__")
    env_marker = lines.index("__COVERAGE_GATE_STUB_ENV__")
    args = lines[args_marker + 1 : env_marker]
    environment = dict(line.split("=", 1) for line in lines[env_marker + 1 :] if "=" in line)
    return args, environment


def test_pr_test_gates_skip_draft_wip_pushes() -> None:
    workflow = _workflow("tests.yml")
    draft_guard = "github.event.pull_request.draft == false"

    for job_name in ("blocker", "contract", "search-eval-gate"):
        job_if = str(workflow["jobs"][job_name].get("if", ""))
        assert draft_guard in job_if, f"{job_name} must skip draft/WIP PR pushes"


def test_search_eval_gate_remains_tier1_blocking_smoke() -> None:
    workflow = _workflow("tests.yml")
    job = workflow["jobs"]["search-eval-gate"]

    assert job.get("continue-on-error") is not True
    assert "github.event.pull_request.draft == false" in str(job.get("if", ""))


def test_quarantine_remains_tier2_post_merge_only() -> None:
    workflow = _workflow("tests.yml")

    job_if = str(workflow["jobs"]["quarantine"].get("if", ""))
    assert "github.event_name == 'push'" in job_if
    assert "github.ref == 'refs/heads/main'" in job_if
    assert "pull_request" not in job_if


def test_coverage_gate_is_tier1_for_ready_prs_and_main_pushes() -> None:
    workflow = _workflow("tests.yml")
    job_if = str(workflow["jobs"]["coverage"].get("if", ""))

    assert "github.event_name == 'push'" in job_if
    assert "github.ref == 'refs/heads/main'" in job_if
    assert "github.event_name == 'pull_request'" in job_if
    assert "github.event.pull_request.draft == false" in job_if


def test_coverage_gate_ci_delegates_to_the_canonical_runner() -> None:
    workflow = _workflow("tests.yml")
    coverage_steps = workflow["jobs"]["coverage"]["steps"]
    coverage_runs = [str(step.get("run", "")) for step in coverage_steps if "run" in step]
    install_step = next(
        step for step in coverage_steps if step.get("name") == "Install dependencies"
    )
    coverage_step = next(
        step for step in coverage_steps if step.get("name") == "Enforce coverage gate"
    )

    assert "pytest-cov" in str(install_step["run"])
    assert "${{ runner.temp }}" in str(
        coverage_step.get("env", {}).get("COVERAGE_GATE_BASETEMP", "")
    )
    assert coverage_runs.count("bash scripts/run_coverage_gate.sh") == 1
    assert not any("--cov=tools" in run for run in coverage_runs)


def test_pre_push_gate_preflights_and_runs_the_canonical_coverage_runner() -> None:
    source = (REPO_ROOT / "scripts" / "pre-push-gate.sh").read_text(encoding="utf-8")

    assert "pytest_cov" in source
    assert "COVERAGE_TIMEOUT_SECONDS" in source
    assert "bash scripts/run_coverage_gate.sh" in source
    assert "--cov=tools" not in source


def test_pre_push_gate_allocates_a_unique_run_without_shared_temp_cleanup() -> None:
    source = (REPO_ROOT / "scripts" / "pre-push-gate.sh").read_text(encoding="utf-8")

    assert 'mktemp -d "$PYTEST_TEMP_ROOT/prepush.XXXXXX"' in source
    assert "rm -rf .pytest_tmp/*" not in source
    assert 'PYTEST_BASETEMP=".pytest_tmp/prepush_${TIMESTAMP}"' not in source


def test_pre_push_env_preflight_allocates_distinct_owned_run_directories(
    tmp_path: Path,
) -> None:
    env = os.environ.copy()
    if os.name != "nt":
        env["ALLOW_NON_GIT_BASH"] = "1"
    # This test covers only concurrent temp ownership. Its subprocess-local
    # Python stub makes the unrelated optional developer-tool inventory
    # deterministic without changing the production preflight.
    stub_dir = _write_test_python_stub(tmp_path)
    env["PATH"] = str(stub_dir) + os.pathsep + env.get("PATH", "")

    processes = [_run_pre_push_env_check(env) for _ in range(2)]
    outputs = [process.communicate(timeout=30) for process in processes]
    combined_outputs = [stdout + stderr for stdout, stderr in outputs]
    run_directories: list[Path] = []
    prefix = "Run directory: "

    try:
        for process, output in zip(processes, combined_outputs, strict=True):
            assert process.returncode == 0, output
            assert "__GATE_PYTHON_DEPENDENCY_PROBE__" in output
            run_directory = next(
                line.removeprefix(prefix) for line in output.splitlines() if line.startswith(prefix)
            )
            path = REPO_ROOT / run_directory
            assert path.parent == REPO_ROOT / ".pytest_tmp"
            assert path.is_dir()
            run_directories.append(path)

        assert len({path.name for path in run_directories}) == 2
    finally:
        for path in run_directories:
            shutil.rmtree(path, ignore_errors=True)


def test_canonical_coverage_runner_forces_an_isolated_synthetic_data_root() -> None:
    assert COVERAGE_GATE_RUNNER.is_file()
    source = COVERAGE_GATE_RUNNER.read_text(encoding="utf-8")
    assert "COVERAGE_GATE_BASETEMP" in source
    assert "RUNNER_TEMP" in source
    assert "parent resolves outside its allowed isolated root" in source
    assert "pytest_cov" in source
    assert "python -m pytest" in source
    assert '"blocker or contract"' in source
    assert "--cov=tools" in source
    assert "--cov-report=term-missing" in source
    assert '--basetemp="$PYTEST_BASETEMP"' in source
    assert 'export LIFE_INDEX_DATA_DIR="$PYTEST_BASETEMP/data"' in source
    assert 'export COVERAGE_FILE="$PYTEST_BASETEMP/.coverage"' in source
    assert "pwd -P" in source
    assert '*".."*' not in source
    assert "--cov-fail-under" not in source


def test_coverage_runner_forces_data_and_coverage_file_with_a_stubbed_python(
    tmp_path: Path,
) -> None:
    run_root = REPO_ROOT / ".pytest_tmp" / f"coverage-runner-{uuid4().hex}"
    run_root.mkdir(parents=True)
    inherited_data = tmp_path / "inherited-life-index-data"
    inherited_coverage = tmp_path / "inherited-coverage-file"
    relative_basetemp = (Path(".pytest_tmp") / run_root.name / "coverage").as_posix()

    env = _coverage_gate_env(_write_test_python_stub(tmp_path), relative_basetemp)
    env["LIFE_INDEX_DATA_DIR"] = str(inherited_data)
    env["COVERAGE_FILE"] = str(inherited_coverage)

    try:
        result = _run_coverage_gate(env)
        assert result.returncode == 0, result.stdout + result.stderr
        basetemp = _reported_coverage_basetemp(result.stdout)
        pytest_args, captured_env = _stubbed_pytest_capture(result.stdout)

        assert "-m" in pytest_args
        assert "blocker or contract" in pytest_args
        assert "--cov=tools" in pytest_args
        assert "--cov-report=term-missing" in pytest_args
        assert f"--basetemp={basetemp}" in pytest_args
        assert captured_env["LIFE_INDEX_DATA_DIR"] == f"{basetemp}/data"
        assert captured_env["COVERAGE_FILE"] == f"{basetemp}/.coverage"
        assert captured_env["LIFE_INDEX_DATA_DIR"] != str(inherited_data)
        assert captured_env["COVERAGE_FILE"] != str(inherited_coverage)
        assert "Ignoring inherited LIFE_INDEX_DATA_DIR" in result.stdout
        assert "Ignoring inherited COVERAGE_FILE" in result.stdout
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def test_coverage_runner_accepts_a_physically_contained_dotdot_parent(tmp_path: Path) -> None:
    run_root = REPO_ROOT / ".pytest_tmp" / f"coverage-dotdot-{uuid4().hex}"
    (run_root / "normalizing-parent").mkdir(parents=True)
    relative_basetemp = (
        Path(".pytest_tmp") / run_root.name / "normalizing-parent" / ".." / "coverage"
    ).as_posix()

    try:
        result = _run_coverage_gate(
            _coverage_gate_env(_write_test_python_stub(tmp_path), relative_basetemp)
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert _reported_coverage_basetemp(result.stdout).endswith(f"/{run_root.name}/coverage")
    finally:
        shutil.rmtree(run_root, ignore_errors=True)


def test_coverage_runner_rejects_symlinked_parent_before_creating_external_child(
    tmp_path: Path,
) -> None:
    run_root = REPO_ROOT / ".pytest_tmp" / f"coverage-symlink-{uuid4().hex}"
    outside_parent = tmp_path / "outside-parent"
    outside_parent.mkdir()
    run_root.mkdir(parents=True)
    linked_parent = run_root / "linked-parent"
    try:
        linked_parent.symlink_to(outside_parent, target_is_directory=True)
    except OSError:
        shutil.rmtree(run_root, ignore_errors=True)
        pytest.skip("symlink creation is unavailable on this platform")

    relative_basetemp = (
        Path(".pytest_tmp") / run_root.name / "linked-parent" / "coverage"
    ).as_posix()
    try:
        result = _run_coverage_gate(
            _coverage_gate_env(_write_test_python_stub(tmp_path), relative_basetemp)
        )
        assert result.returncode != 0
        assert "COVERAGE GATE FAIL" in result.stdout + result.stderr
        assert not (outside_parent / "coverage").exists()
    finally:
        linked_parent.unlink(missing_ok=True)
        shutil.rmtree(run_root, ignore_errors=True)


def test_ci_inventory_promotes_coverage_and_keeps_quarantine_tier2() -> None:
    inventory = (REPO_ROOT / "docs" / "CI_HARD_CHECKS.md").read_text(encoding="utf-8")

    assert (
        "| 4 | coverage gate | `bash scripts/run_coverage_gate.sh` | tests.yml | "
        "`bash scripts/run_coverage_gate.sh` |"
    ) in inventory
    assert (
        "coverage runs on ready/non-draft pull requests targeting main and on push to main"
        in inventory.lower()
    )
    assert "| C | coverage |" not in inventory
    assert (
        "| Q | quarantine | `pytest -m quarantine --timeout=300` | tests.yml | push to main |"
        in inventory
    )


def test_nightly_tier2_runs_on_schedule_manual_and_post_merge() -> None:
    workflow = _workflow("nightly.yml")
    triggers = _workflow_on(workflow)

    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["main"]
    assert "full-suite" in workflow["jobs"]
    assert "package-onboarding" in workflow["jobs"]


def test_nightly_package_smoke_uses_step_scoped_runner_temp() -> None:
    workflow = _workflow("nightly.yml")
    package_job = workflow["jobs"]["package-onboarding"]

    assert "runner.temp" not in str(package_job.get("env", {}))
    assert "$RUNNER_TEMP" in str(package_job["steps"])


def test_nightly_full_suite_forces_utf8_subprocess_io() -> None:
    workflow = _workflow("nightly.yml")
    env = workflow["jobs"]["full-suite"]["env"]

    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_fast_local_tier1_gate_script_is_documented() -> None:
    script = REPO_ROOT / "scripts" / "tier1-gate.sh"
    source = script.read_text(encoding="utf-8")

    for expected in (
        "Tier 1 fast gate",
        "python -m black --check tools/",
        "python -m flake8 tools/",
        "python -m bandit -r tools/",
        "python -m mypy tools/",
        "python .github/scripts/check_doc_sync.py",
        "python -m pytest -m blocker",
    ):
        assert expected in source


def test_l2_production_modules_do_not_import_llm_providers() -> None:
    offenders: list[str] = []
    for path in _production_l2_files():
        imports = _imported_modules(path)
        if imports & DISALLOWED_PROVIDER_IMPORTS:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: {sorted(imports & DISALLOWED_PROVIDER_IMPORTS)}")

    assert offenders == []


def test_l2_production_modules_do_not_import_l3_orchestrators() -> None:
    offenders: list[str] = []
    for path in _production_l2_files():
        imports = _imported_modules(path)
        for imported in imports:
            if any(
                imported == disallowed or imported.startswith(f"{disallowed}.")
                for disallowed in DISALLOWED_L3_IMPORTS
            ):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {imported}")

    assert offenders == []


def test_l2_production_roots_cover_all_deterministic_modules() -> None:
    """L2_PRODUCTION_ROOTS must include every deterministic L2 tool module.

    Missing roots mean new deterministic code can ship without layer-invariant
    coverage — a coverage gap that the architecture audit flagged as HIGH.
    """
    actual_names = {p.name for p in L2_PRODUCTION_ROOTS}
    missing = sorted(REQUIRED_L2_ROOTS - actual_names)
    assert missing == [], f"L2_PRODUCTION_ROOTS is missing deterministic modules: {missing}"


def test_l2_whitelisted_files_do_not_import_l3() -> None:
    """Even whitelisted L2 files must not import from L3 packages.

    This catches the specific orchestrator.py -> tools.smart_search.planner
    upward dependency that was flagged in the cross-agent architecture audit.
    """
    offenders: list[str] = []
    for path in L2_STRICT_L3_FREE_FILES:
        if not path.exists():
            continue
        imports = _imported_modules(path)
        for imported in imports:
            if any(
                imported == disallowed or imported.startswith(f"{disallowed}.")
                for disallowed in DISALLOWED_L3_IMPORTS
            ):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {imported}")

    assert offenders == [], f"Whitelisted L2 files import from L3 packages: {offenders}"


# --- recall compatibility wrapper invariant tests ---


RECALL_ROOT = REPO_ROOT / "tools" / "recall"


def _recall_files() -> list[Path]:
    """All .py files in the recall module, if it exists."""
    if not RECALL_ROOT.exists():
        return []
    return sorted(RECALL_ROOT.rglob("*.py"))


def test_recall_module_does_not_import_llm_providers() -> None:
    """tools/recall/ must not import anthropic/openai anywhere.

    The recall wrapper is retained only for compatibility and delegates to
    search via subprocess. It must never import LLM providers directly.
    """
    offenders: list[str] = []
    for path in _recall_files():
        imports = _imported_modules(path)
        if imports & DISALLOWED_PROVIDER_IMPORTS:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: {sorted(imports & DISALLOWED_PROVIDER_IMPORTS)}")

    assert offenders == [], f"recall module imports LLM providers: {offenders}"


def test_recall_module_uses_subprocess_not_direct_import() -> None:
    """tools/recall/ must use subprocess to call L2, not direct imports.

    The compatibility wrapper invokes search via subprocess (like on_this_day),
    never importing L2 internals.
    """
    disallowed_l2_imports = {
        "tools.search_journals",
        "tools.smart_search",
    }

    offenders: list[str] = []
    for path in _recall_files():
        imports = _imported_modules(path)
        for imported in imports:
            if any(
                imported == disallowed or imported.startswith(f"{disallowed}.")
                for disallowed in disallowed_l2_imports
            ):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {imported}")

    assert (
        offenders == []
    ), f"recall module directly imports L2 internals (should use subprocess): {offenders}"


# --- Phase A: tools/eval/ablation/ no-default-LLM invariant ---

ABLATION_ROOT = REPO_ROOT / "tools" / "eval" / "ablation"

DISALLOWED_LLM_IMPORTS = {
    "anthropic",
    "openai",
    "llm_client",
}


def _ablation_python_files() -> list[Path]:
    """Collect all .py files under tools/eval/ablation/."""
    if not ABLATION_ROOT.exists():
        return []
    return sorted(ABLATION_ROOT.rglob("*.py"))


def test_ablation_no_default_llm_imports() -> None:
    """Phase A invariant: tools/eval/ablation/ must not import LLM providers.

    The ablation eval surface is a deterministic cross-cutting tool that
    measures search quality across pipeline configurations. It must not
    depend on any LLM provider in its default code path (CHARTER §1.5).
    """
    offenders: list[str] = []
    for path in _ablation_python_files():
        imports = _imported_modules(path)
        found = imports & DISALLOWED_LLM_IMPORTS
        if found:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: {sorted(found)}")

    assert offenders == [], f"tools/eval/ablation/ contains disallowed LLM imports: {offenders}"


# --- Phase D (gbrain #4): maintenance module invariant tests ---


MAINTENANCE_ROOT = REPO_ROOT / "tools" / "maintenance"


def _maintenance_files() -> list[Path]:
    """All .py files in the maintenance module, if it exists."""
    if not MAINTENANCE_ROOT.exists():
        return []
    return sorted(MAINTENANCE_ROOT.rglob("*.py"))


def test_maintenance_no_default_llm_imports() -> None:
    """Phase D invariant: tools/maintenance/ must not import LLM providers.

    The maintenance cycle is a dry-run/report-only command that aggregates
    six health checks via subprocess delegation. It must not depend on any
    LLM provider in its default code path (CHARTER §1.5).
    """
    offenders: list[str] = []
    for path in _maintenance_files():
        imports = _imported_modules(path)
        found = imports & DISALLOWED_LLM_IMPORTS
        if found:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: {sorted(found)}")

    assert offenders == [], f"tools/maintenance/ contains disallowed LLM imports: {offenders}"


def test_maintenance_uses_subprocess_not_direct_import() -> None:
    """Phase D invariant: tools/maintenance/ must not import called module internals.

    The maintenance module delegates to existing CLI commands (index, entity,
    eval/ablation, backup) via subprocess. It must never import their internals
    directly — this preserves the L2/L3 subprocess boundary.
    """
    disallowed_internal_imports = {
        "tools.build_index",
        "tools.entity",
        "tools.eval.ablation",
        "tools.backup",
    }

    offenders: list[str] = []
    for path in _maintenance_files():
        imports = _imported_modules(path)
        for imported in imports:
            if any(
                imported == disallowed or imported.startswith(f"{disallowed}.")
                for disallowed in disallowed_internal_imports
            ):
                rel = path.relative_to(REPO_ROOT).as_posix()
                offenders.append(f"{rel}: {imported}")

    # Allow tools.lib.* (shared utilities) and yaml (for file parsing)
    assert offenders == [], (
        f"maintenance module directly imports called module internals "
        f"(should use subprocess): {offenders}"
    )


# --- B4.2: boost_decay echo-only invariant ---

BOOST_DECAY_FORBIDDEN_FILES = {
    REPO_ROOT / "tools" / "lib" / "search_constants.py",
    REPO_ROOT / "tools" / "search_journals" / "core.py",
    REPO_ROOT / "tools" / "search_journals" / "__main__.py",
    REPO_ROOT / "tools" / "search_journals" / "ranking.py",
    REPO_ROOT / "tools" / "eval" / "calibrate.py",
}


def _search_journals_py_files() -> list[Path]:
    search_dir = REPO_ROOT / "tools" / "search_journals"
    if not search_dir.exists():
        return []
    return sorted(search_dir.rglob("*.py"))


def test_boost_decay_not_imported_by_search_ranking() -> None:
    """B4.2 invariant: boost_decay must not be imported by search ranking/BM25/RRF/calibration.

    boost_decay is a schema placeholder for v1.2.0 Cycle 2 calibration.
    It must not be imported, read, or applied by any search ranking path
    in v1.1.1 (CHARTER + M1 PRD §6.1.2).
    """
    offenders: list[str] = []
    for path in BOOST_DECAY_FORBIDDEN_FILES:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if "boost_decay" in content:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: contains 'boost_decay' reference")

    for path in _search_journals_py_files():
        if path in BOOST_DECAY_FORBIDDEN_FILES:
            continue
        content = path.read_text(encoding="utf-8")
        if "boost_decay" in content:
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}: contains 'boost_decay' reference")

    assert (
        offenders == []
    ), f"Search ranking/BM25/RRF/calibration files must not reference boost_decay: {offenders}"
