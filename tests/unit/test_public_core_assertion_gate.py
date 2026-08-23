from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / ".github" / "scripts" / "run_public_core_assertions.py"


def _run_gate(tmp_path: Path, source: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    test_file = tmp_path / "test_synthetic_core.py"
    test_file.write_text(source, encoding="utf-8")
    sentinel = tmp_path / "sentinel.json"
    result = subprocess.run(
        [
            sys.executable,
            str(GATE_SCRIPT),
            "--root",
            str(tmp_path),
            "--target",
            str(test_file),
            "--sentinel",
            str(sentinel),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        encoding="utf-8",
    )
    payload = json.loads(sentinel.read_text(encoding="utf-8")) if sentinel.exists() else {}
    return result, payload


def test_public_core_gate_records_real_assertion_execution(tmp_path: Path) -> None:
    result, payload = _run_gate(
        tmp_path,
        "def test_core_recall_assertion():\n    assert 'token' in 'synthetic token fixture'\n",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["core_assertions_collected"] == 1
    assert payload["core_assertions_executed"] == 1
    assert payload["core_assertions_passed"] == 1
    assert payload["status"] == "PASS"


def test_public_core_gate_creates_fresh_sentinel_parent(tmp_path: Path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("public_core_gate", GATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    sentinel = tmp_path / "fresh-checkout" / "sentinel.json"

    def fake_pytest_main(args, *, plugins):
        basetemp = Path(args[args.index("--basetemp") + 1])
        assert basetemp.parent.is_dir()
        counter = plugins[0]
        counter.collected = 1
        counter.executed = 1
        counter.passed = 1
        return 0

    monkeypatch.setattr(module.pytest, "main", fake_pytest_main)
    result = module.main(
        [
            "--root",
            str(tmp_path),
            "--target",
            "synthetic-target",
            "--sentinel",
            str(sentinel),
        ]
    )

    assert result == 0
    payload = json.loads(sentinel.read_text(encoding="utf-8"))
    assert payload["core_assertions_executed"] == 1
    assert payload["status"] == "PASS"


def test_public_core_gate_rejects_all_skipped_assertions(tmp_path: Path) -> None:
    result, payload = _run_gate(
        tmp_path,
        "import pytest\n\n@pytest.mark.skip(reason='synthetic skip')\n"
        "def test_core_recall_assertion():\n    assert True\n",
    )

    assert result.returncode != 0
    assert payload["core_assertions_collected"] == 1
    assert payload["core_assertions_executed"] == 0
    assert payload["core_assertions_skipped"] == 1
    assert payload["status"] == "FAIL"


def test_public_core_gate_rejects_missing_or_deselected_target(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel.json"
    result = subprocess.run(
        [
            sys.executable,
            str(GATE_SCRIPT),
            "--root",
            str(tmp_path),
            "--target",
            str(tmp_path / "missing_test.py"),
            "--sentinel",
            str(sentinel),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        encoding="utf-8",
    )

    assert result.returncode != 0
    payload = json.loads(sentinel.read_text(encoding="utf-8"))
    assert payload["core_assertions_executed"] == 0
    assert payload["status"] == "FAIL"
