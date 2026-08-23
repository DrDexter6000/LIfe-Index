from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check_l2_no_llm.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_l2_no_llm", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scan_flags_llm_imports_in_core_tools(tmp_path: Path) -> None:
    checker = _load_checker()
    root = tmp_path
    core_file = root / "tools" / "smart_search" / "__main__.py"
    core_file.parent.mkdir(parents=True)
    core_file.write_text(
        "\n".join(
            [
                "from openai import OpenAI",
                "from tools.lib.config import get_llm_config",
                "from tools._optional.llm_extract import extract_metadata_sync",
            ]
        ),
        encoding="utf-8",
    )

    violations = checker.scan_tree(root)

    assert [v.path for v in violations] == ["tools/smart_search/__main__.py"] * 3
    assert [v.import_name for v in violations] == [
        "openai",
        "tools.lib.config.get_llm_config",
        "tools._optional.llm_extract",
    ]


def test_scan_allows_clean_core_and_optional_isolation(tmp_path: Path) -> None:
    checker = _load_checker()
    root = tmp_path
    core_file = root / "tools" / "smart_search" / "__main__.py"
    optional_file = root / "tools" / "_optional" / "llm_extract.py"
    core_file.parent.mkdir(parents=True)
    optional_file.parent.mkdir(parents=True)
    core_file.write_text("from tools.search_journals.orchestrator import SmartSearchOrchestrator\n")
    optional_file.write_text("from openai import OpenAI\n")

    assert checker.scan_tree(root) == []


def test_cli_exits_nonzero_for_violation_and_zero_for_clean(tmp_path: Path) -> None:
    dirty_root = tmp_path / "dirty"
    dirty_file = dirty_root / "tools" / "write_journal" / "prepare.py"
    dirty_file.parent.mkdir(parents=True)
    dirty_file.write_text("from tools._optional.llm_extract import is_llm_available\n")

    clean_root = tmp_path / "clean"
    clean_file = clean_root / "tools" / "write_journal" / "prepare.py"
    clean_file.parent.mkdir(parents=True)
    clean_file.write_text("from tools.write_journal.utils import normalize_text_list\n")

    dirty = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(dirty_root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )
    clean = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--root", str(clean_root)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )

    assert dirty.returncode == 1
    assert "tools/write_journal/prepare.py" in dirty.stdout
    assert "tools._optional.llm_extract" in dirty.stdout
    assert clean.returncode == 0


def test_scan_flags_provider_ownership_in_product_eval_tree(tmp_path: Path) -> None:
    checker = _load_checker()
    eval_file = tmp_path / "tools" / "eval" / "run_eval.py"
    eval_file.parent.mkdir(parents=True)
    eval_file.write_text(
        "from openai import OpenAI\n"
        "provider_client = OpenAI()\n"
        "provider_client.responses.create(model='synthetic')\n",
        encoding="utf-8",
    )

    violations = checker.scan_tree(tmp_path)

    assert violations
    assert {violation.path for violation in violations} == {"tools/eval/run_eval.py"}


def test_scan_parses_utf8_bom_in_product_eval_tree(tmp_path: Path) -> None:
    checker = _load_checker()
    eval_file = tmp_path / "tools" / "eval" / "answer_eval.py"
    eval_file.parent.mkdir(parents=True)
    eval_file.write_text(
        "\ufeffdef evaluate_answer():\n    return {'supported': True}\n", encoding="utf-8"
    )

    assert checker.scan_tree(tmp_path) == []
