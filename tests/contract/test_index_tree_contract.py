#!/usr/bin/env python3
"""Contract tests for the public index-tree CLI surface."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


def _write_journal(
    data_dir: Path,
    *,
    date: str,
    title: str,
    extra_frontmatter: str = "",
) -> Path:
    year, month, _day = date.split("-")
    journal_dir = data_dir / "Journals" / year / month
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / f"life-index_{date}_001.md"
    lines = ["---", f'title: "{title}"', f"date: {date}"]
    if extra_frontmatter:
        lines.extend(extra_frontmatter.rstrip().splitlines())
    lines.extend(["---", "", f"# {title}", "", "alpha body marker"])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_index(path: Path, frontmatter_lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + "\n".join(frontmatter_lines) + "\n---\n\n# Index\n",
        encoding="utf-8",
    )


def _seed_data(data_dir: Path) -> Path:
    journal = _write_journal(
        data_dir,
        date="2026-03-14",
        title="Alpha Work",
        extra_frontmatter='topic: ["work"]\npeople: ["Alice"]\nproject: "Life Index"',
    )
    _write_index(
        data_dir / "Journals" / "2026" / "03" / "index_2026-03.md",
        ["entries: 1", "topics: {work: 1}", 'date_range: "2026-03"'],
    )
    return journal


def _seed_index_b_data(data_dir: Path) -> Path:
    journal = _write_journal(
        data_dir,
        date="2026-03-14",
        title="Alpha Work",
        extra_frontmatter=(
            'topic: ["work"]\n'
            'people: ["Alice"]\n'
            'project: "Atlas"\n'
            'tags: ["planning"]\n'
            'location: "London, United Kingdom"\n'
            'weather: "Cloudy 12C"'
        ),
    )
    _write_index(
        data_dir / "Journals" / "2026" / "03" / "index_2026-03.md",
        ["entries: 1", "topics: {work: 1}", 'date_range: "2026-03"'],
    )
    _write_index(
        data_dir / "Journals" / "2026" / "index_2026.md",
        ["entries: 1", "topics: {work: 1}"],
    )
    _write_index(data_dir / "INDEX.md", ["total_entries: 1", 'date_range: "2026-03"'])
    return journal


def _seed_index_b_multi_month_data(data_dir: Path) -> tuple[Path, Path]:
    march = _write_journal(
        data_dir,
        date="2026-03-14",
        title="March Work",
        extra_frontmatter=(
            'topic: ["work"]\n'
            'people: ["Alice"]\n'
            'project: "Atlas"\n'
            'tags: ["planning"]\n'
            'location: "London, United Kingdom"\n'
            'weather: "Cloudy 12C"'
        ),
    )
    april = _write_journal(
        data_dir,
        date="2026-04-20",
        title="April Home",
        extra_frontmatter=(
            'topic: ["life"]\n'
            'people: ["Bob"]\n'
            'project: "Home"\n'
            'tags: ["family"]\n'
            'location: "Cardiff, United Kingdom"\n'
            'weather: "Sunny 18C"'
        ),
    )
    return march, april


def _invoke(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, "-m", "tools", "index-tree", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _invoke_with_env(
    data_dir: Path, extra_env: dict[str, str], *args: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "tools", "index-tree", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        encoding="utf-8",
    )


def _payload(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return json.loads(result.stdout)


def _all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            found.extend(_all_strings(item))
        return found
    if isinstance(value, dict):
        found = []
        for item in value.values():
            found.extend(_all_strings(item))
        return found
    return []


def test_nodes_json_contract(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_data(data_dir)

    result = _invoke(data_dir, "nodes", "--level", "month", "--json")

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["schema_version"] == "m31.index_tree.v1"
    assert payload["command"] == "index-tree.nodes"
    node = payload["data"]["nodes"][0]
    assert node["node_id"] == "month:2026-03"
    assert node["relative_path"] == "Journals/2026/03/index_2026-03.md"
    assert str(data_dir) not in _all_strings(payload)


def test_lens_json_contract(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    journal = _seed_data(data_dir)

    result = _invoke(data_dir, "lens", "--signal", "topic", "--json")

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["command"] == "index-tree.lens"
    assert payload["data"]["signal"] == "topic"
    assert payload["data"]["items"][0]["value"] == "work"
    assert payload["data"]["items"][0]["evidence_paths"] == [
        journal.relative_to(data_dir).as_posix()
    ]


def test_shadow_json_contract(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_data(data_dir)

    result = _invoke(data_dir, "shadow", "--query", "Alpha", "--json")

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["command"] == "index-tree.shadow"
    assert payload["data"]["diagnostic_only"] is True
    assert payload["data"]["recall_preserved"] is True


def test_materialize_writes_index_b_navigation_docs(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    journal = _seed_index_b_data(data_dir)

    result = _invoke(
        data_dir,
        "materialize",
        "--from",
        "2026-03",
        "--to",
        "2026-03",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["command"] == "index-tree.materialize"
    written_docs = payload["data"]["written_docs"]
    assert ".life-index/index-b/INDEX.md" in written_docs
    assert ".life-index/index-b/Journals/2026/index.md" in written_docs
    assert ".life-index/index-b/Journals/2026/03/index.md" in written_docs

    root_doc = data_dir / ".life-index" / "index-b" / "INDEX.md"
    year_doc = data_dir / ".life-index" / "index-b" / "Journals" / "2026" / "index.md"
    month_doc = data_dir / ".life-index" / "index-b" / "Journals" / "2026" / "03" / "index.md"
    for path in (root_doc, year_doc, month_doc):
        assert path.exists(), f"missing materialized doc: {path}"
        assert path.read_text(encoding="utf-8").strip()

    month_text = month_doc.read_text(encoding="utf-8")
    assert "## Facets" in month_text
    for facet in ("weather", "location", "topic", "project", "tag", "people"):
        assert f"### {facet}" in month_text
    assert "### task" not in month_text
    assert "| Cloudy 12C | 1 |" in month_text
    assert "| London, United Kingdom | 1 |" in month_text
    assert "| work | 1 |" in month_text
    assert "| Atlas | 1 |" in month_text
    assert "| planning | 1 |" in month_text
    assert "| Alice | 1 |" in month_text
    assert journal.relative_to(data_dir).as_posix() in month_text

    root_text = root_doc.read_text(encoding="utf-8")
    year_rel = ".life-index/index-b/Journals/2026/index.md"
    month_rel = ".life-index/index-b/Journals/2026/03/index.md"
    assert year_rel in root_text
    assert month_rel in year_doc.read_text(encoding="utf-8")


def test_index_b_facets_include_write_schema_topic_ssot() -> None:
    from tools.index_tree.materialize import FACETS
    from tools.lib.topics import VALID_TOPICS

    specs = {spec.name: spec for spec in FACETS}

    assert VALID_TOPICS
    assert "topic" in specs
    assert specs["topic"].fields == ("topic", "topics")
    assert "task" not in specs


def test_materialize_manifest_freshness_and_incremental_refresh(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    march_journal, _april_journal = _seed_index_b_multi_month_data(data_dir)

    result = _invoke(
        data_dir,
        "materialize",
        "--from",
        "2026-03",
        "--to",
        "2026-04",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert ".life-index/index-b/manifest.json" in payload["data"]["written_docs"]

    freshness = _payload(
        _invoke(data_dir, "freshness", "--from", "2026-03", "--to", "2026-04", "--json")
    )
    assert freshness["success"] is True
    assert freshness["command"] == "index-tree.freshness"
    assert freshness["data"]["fresh"] is True
    assert freshness["data"]["stale_scopes"] == []

    march_text = march_journal.read_text(encoding="utf-8")
    march_journal.write_text(
        march_text.replace('location: "London, United Kingdom"', 'location: "Paris, France"'),
        encoding="utf-8",
    )

    stale = _payload(
        _invoke(data_dir, "freshness", "--from", "2026-03", "--to", "2026-04", "--json")
    )
    assert stale["data"]["fresh"] is False
    assert "month:2026-03" in stale["data"]["stale_scopes"]
    assert "month:2026-04" in stale["data"]["fresh_scopes"]

    refresh = _payload(
        _invoke(
            data_dir,
            "materialize",
            "--from",
            "2026-03",
            "--to",
            "2026-04",
            "--incremental",
            "--json",
        )
    )
    assert refresh["success"] is True
    assert ".life-index/index-b/Journals/2026/03/index.md" in refresh["data"]["written_docs"]
    assert ".life-index/index-b/Journals/2026/04/index.md" in refresh["data"]["skipped_fresh_docs"]

    month_doc = data_dir / ".life-index" / "index-b" / "Journals" / "2026" / "03" / "index.md"
    assert "Paris, France" in month_doc.read_text(encoding="utf-8")

    fresh_again = _payload(
        _invoke(data_dir, "freshness", "--from", "2026-03", "--to", "2026-04", "--json")
    )
    assert fresh_again["data"]["fresh"] is True


def test_navigate_json_contract_filters_materialized_index_b(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    journal = _write_journal(
        data_dir,
        date="2026-03-14",
        title="Facet Work",
        extra_frontmatter=(
            'project: "Life Index"\n' 'tags: ["ai"]\n' 'location: "Lagos, Nigeria"\n'
        ),
    )
    _write_journal(
        data_dir,
        date="2026-03-15",
        title="Facet Other",
        extra_frontmatter='project: "Other"\ntags: ["ai"]\nlocation: "Lagos, Nigeria"',
    )

    result = _invoke(
        data_dir,
        "navigate",
        "--from",
        "2026-03",
        "--to",
        "2026-03",
        "--filter",
        "location=Lagos, Nigeria",
        "--filter",
        "project=Life Index",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["command"] == "index-tree.navigate"
    assert payload["data"]["source"] == "index-b"
    assert payload["data"]["count"] == 1
    assert payload["data"]["entry_pointers"] == [journal.relative_to(data_dir).as_posix()]
    assert str(data_dir) not in _all_strings(payload)


def test_navigate_entity_neighbors_json_contract(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "entity_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "entities": [
                    {
                        "id": "person-alice",
                        "type": "actor",
                        "primary_name": "Alice",
                        "aliases": ["A."],
                        "relationships": [{"target": "project-atlas", "relation": "works_on"}],
                    },
                    {
                        "id": "project-atlas",
                        "type": "project",
                        "primary_name": "Atlas",
                        "aliases": [],
                        "relationships": [],
                    },
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = _invoke(
        data_dir,
        "navigate",
        "--entity-neighbors",
        "Alice",
        "--entity-relation",
        "works_on",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["command"] == "index-tree.navigate"
    assert payload["data"]["entity_neighbors"][0]["resolved_entity"]["id"] == "person-alice"
    assert payload["data"]["entity_neighbors"][0]["neighbors"][0]["entity_id"] == ("project-atlas")
    assert payload["data"]["entity_neighbors"][0]["neighbors"][0]["edges"][0]["relation"] == (
        "works_on"
    )
    assert str(data_dir) not in _all_strings(payload)


def test_navigate_writes_validation_tool_call_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    log_path = tmp_path / "tool-calls.jsonl"
    journal = _write_journal(
        data_dir,
        date="2026-03-14",
        title="Facet Work",
        extra_frontmatter=(
            'project: "Life Index"\n' 'tags: ["ai"]\n' 'location: "London, United Kingdom"'
        ),
    )

    result = _invoke_with_env(
        data_dir,
        {
            "LIFE_INDEX_VALIDATION_MODE": "1",
            "LIFE_INDEX_TOOL_CALL_LOG": str(log_path),
        },
        "navigate",
        "--from",
        "2026-03",
        "--to",
        "2026-03",
        "--filter",
        "location=London, United Kingdom",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["tool"] == "index-tree.navigate"
    assert records[0]["params"] == {
        "date_from": "2026-03",
        "date_to": "2026-03",
        "filters": ["location=London, United Kingdom"],
    }
    assert records[0]["result"]["count"] == 1
    assert records[0]["result"]["entry_pointers"] == [journal.relative_to(data_dir).as_posix()]
    assert str(data_dir) not in json.dumps(records, ensure_ascii=False)


def test_navigate_entity_neighbors_validation_tool_call_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    log_path = tmp_path / "tool-calls.jsonl"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "entity_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "entities": [
                    {
                        "id": "person-alice",
                        "type": "actor",
                        "primary_name": "Alice",
                        "aliases": [],
                        "relationships": [{"target": "project-atlas", "relation": "works_on"}],
                    },
                    {
                        "id": "project-atlas",
                        "type": "project",
                        "primary_name": "Atlas",
                        "aliases": [],
                        "relationships": [],
                    },
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = _invoke_with_env(
        data_dir,
        {
            "LIFE_INDEX_VALIDATION_MODE": "1",
            "LIFE_INDEX_TOOL_CALL_LOG": str(log_path),
        },
        "navigate",
        "--entity-neighbors",
        "Alice",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["tool"] == "index-tree.navigate"
    assert records[0]["params"]["entity_neighbors"] == ["Alice"]
    assert records[0]["params"]["entity_relations"] == []
    assert records[0]["result"]["entity_neighbor_counts"] == [1]
    assert str(data_dir) not in json.dumps(records, ensure_ascii=False)


def test_discover_json_contract_and_validation_tool_call_log(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    log_path = tmp_path / "tool-calls.jsonl"
    _write_journal(
        data_dir,
        date="2026-03-14",
        title="Facet Work",
        extra_frontmatter=(
            'topic: ["work"]\n'
            'project: "Life Index"\n'
            'tags: ["ai"]\n'
            'location: "London, United Kingdom"'
        ),
    )

    result = _invoke_with_env(
        data_dir,
        {
            "LIFE_INDEX_VALIDATION_MODE": "1",
            "LIFE_INDEX_TOOL_CALL_LOG": str(log_path),
        },
        "discover",
        "--from",
        "2026-03",
        "--to",
        "2026-03",
        "--facet",
        "location",
        "--facet",
        "topic",
        "--json",
    )

    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["command"] == "index-tree.discover"
    assert payload["data"]["facets"]["location"]["values"][0]["value"] == ("London, United Kingdom")
    assert payload["data"]["facets"]["topic"]["values"][0]["value"] == "work"
    assert payload["data"]["facets"]["topic"]["values"][0]["count"] == 1
    assert str(data_dir) not in _all_strings(payload)

    records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert records[0]["tool"] == "index-tree.discover"
    assert records[0]["params"] == {
        "date_from": "2026-03",
        "date_to": "2026-03",
        "facets": ["location", "topic"],
    }
    assert records[0]["result"]["candidate_count"] == 1
    assert records[0]["result"]["facet_value_counts"] == {
        "location": 1,
        "topic": 1,
    }
    assert str(data_dir) not in json.dumps(records, ensure_ascii=False)


def test_task_facet_is_not_a_supported_index_tree_facet(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_index_b_data(data_dir)

    result = _invoke(data_dir, "discover", "--facet", "task", "--json")

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["errors"][0]["code"] == "INDEX_TREE_DISCOVER_INVALID_FACET"
    assert "task" in payload["errors"][0]["message"]


def test_lens_invalid_signal_returns_structured_error(tmp_path: Path) -> None:
    data_dir = tmp_path / "Life-Index"
    _seed_data(data_dir)

    result = _invoke(data_dir, "lens", "--signal", "mood", "--json")

    assert result.returncode != 0
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["errors"][0]["code"] == "INDEX_TREE_INVALID_SIGNAL"


def test_main_help_includes_index_tree() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tools", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )

    assert result.returncode == 0
    assert "index-tree" in result.stdout
