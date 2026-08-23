"""Contract tests for graph ablation evaluation module.

Tests verify the ablation CLI and output structure contract without
requiring a populated data directory.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from tools.eval.private_data import get_fixtures_dir

WORKTREE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = get_fixtures_dir() / "ablation_queries.json"


def test_ablation_cli_runs() -> None:
    """Verify the ablation CLI module can be invoked with --help."""
    result = subprocess.run(
        ["python", "-m", "tools.eval.ablation", "--help"],
        capture_output=True,
        text=True,
        cwd=str(WORKTREE_ROOT),
        timeout=30,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"CLI --help failed: {result.stderr}"
    assert "usage" in result.stdout or "ablation" in result.stdout.lower()


def _run_ablation_json(data_dir: Path) -> dict[str, Any]:
    """Run ablation and return parsed JSON output."""
    if not FIXTURE_PATH.exists():
        pytest.skip("local/private ablation query fixture not present in public checkout")
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)

    result = subprocess.run(
        [
            "python",
            "-m",
            "tools.eval.ablation",
            "--queries",
            str(FIXTURE_PATH),
            "--data-dir",
            str(data_dir),
            "--output",
            "stdout",
        ],
        capture_output=True,
        text=True,
        cwd=str(WORKTREE_ROOT),
        env=env,
        timeout=120,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"Ablation failed: {result.stderr}\nSTDOUT: {result.stdout}"
    return json.loads(result.stdout)


def test_ablation_output_has_8_combinations() -> None:
    """Ablation output must contain exactly 8 combinations (2^3)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_dir = Path(tmp_dir)
        # Ensure journals directory exists so search doesn't crash
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True, exist_ok=True)
        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True, exist_ok=True)
        # Create an empty entity graph to avoid search warnings
        entity_graph_path = data_dir / "entity_graph.yaml"
        entity_graph_path.write_text("")

        output = _run_ablation_json(data_dir)
        combinations = output.get("combinations", [])
        assert len(combinations) == 8, f"Expected 8 combinations, got {len(combinations)}"


def test_ablation_entry_has_required_fields() -> None:
    """Each ablation entry must have entity_graph, semantic, hybrid flags
    plus precision_at_5, recall_at_5, mrr_at_5."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_dir = Path(tmp_dir)
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True, exist_ok=True)
        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True, exist_ok=True)
        entity_graph_path = data_dir / "entity_graph.yaml"
        entity_graph_path.write_text("")

        output = _run_ablation_json(data_dir)
        combinations = output.get("combinations", [])

        required_fields = {
            "entity_graph",
            "semantic",
            "hybrid",
            "precision_at_5",
            "recall_at_5",
            "mrr_at_5",
        }
        for idx, entry in enumerate(combinations):
            missing = required_fields - set(entry.keys())
            assert not missing, (
                f"Combination {idx} missing required fields: {missing}. "
                f"Got: {list(entry.keys())}"
            )


def test_ablation_metrics_are_numeric() -> None:
    """All metrics must be float values between 0.0 and 1.0."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_dir = Path(tmp_dir)
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True, exist_ok=True)
        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True, exist_ok=True)
        entity_graph_path = data_dir / "entity_graph.yaml"
        entity_graph_path.write_text("")

        output = _run_ablation_json(data_dir)
        combinations = output.get("combinations", [])

        metric_fields = ["precision_at_5", "recall_at_5", "mrr_at_5"]
        for idx, entry in enumerate(combinations):
            for field in metric_fields:
                value = entry.get(field)
                assert isinstance(value, (int, float)), (
                    f"Combination {idx} field '{field}' is not numeric: "
                    f"got {type(value).__name__} = {value}"
                )
                assert 0.0 <= float(value) <= 1.0, (
                    f"Combination {idx} field '{field}' out of range: " f"got {value}"
                )


def test_ablation_schema_version() -> None:
    """Ablation output must include schema_version field."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        data_dir = Path(tmp_dir)
        journals_dir = data_dir / "Journals"
        journals_dir.mkdir(parents=True, exist_ok=True)
        index_dir = data_dir / ".index"
        index_dir.mkdir(parents=True, exist_ok=True)
        entity_graph_path = data_dir / "entity_graph.yaml"
        entity_graph_path.write_text("")

        output = _run_ablation_json(data_dir)
        assert output.get("schema_version") == "gbrain-ablation.v1", (
            f"Expected schema_version 'gbrain-ablation.v1', " f"got {output.get('schema_version')}"
        )
        assert "query_count" in output, "Output missing 'query_count' field"
        assert isinstance(output.get("query_count"), int), "query_count must be an integer"


def test_ablation_fixture_loads() -> None:
    """Verify the fixture JSON is well-formed."""
    if not FIXTURE_PATH.exists():
        pytest.skip("local/private ablation query fixture not present in public checkout")
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, list), "Fixture must be a JSON array"
    assert len(data) >= 20, f"Fixture must have 20+ queries, got {len(data)}"

    for idx, entry in enumerate(data):
        assert isinstance(entry, dict), f"Entry {idx} is not a dict"
        assert "id" in entry, f"Entry {idx} missing 'id'"
        assert "query" in entry, f"Entry {idx} missing 'query'"
        assert "category" in entry, f"Entry {idx} missing 'category'"
        assert "expected_relevant_ids" in entry, f"Entry {idx} missing 'expected_relevant_ids'"
        assert isinstance(
            entry["expected_relevant_ids"], list
        ), f"Entry {idx} expected_relevant_ids must be a list"
