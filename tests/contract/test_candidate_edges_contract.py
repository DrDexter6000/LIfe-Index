#!/usr/bin/env python3
"""Contract test: life-index entity --candidate-edges CLI subprocess interface.

Phase C: Candidate edges report (report-only, zero production graph writes).

Verifies:
- `python -m tools entity --candidate-edges --output=json` exits 0
- Emits valid JSON with required field schema
- Zero entity_graph.yaml writes (before/after hash equality)
- Each candidate has at least 1 evidence_path
- Extractors cover: people, related_entries, wikilinks, co-occurrence
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _hash_file(path: Path) -> str:
    if not path.exists():
        return "file-not-found"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_journal(
    data_dir: Path,
    date_str: str,
    title: str,
    body: str,
    *,
    people: list[str] | None = None,
    related_entries: list[str] | None = None,
) -> Path:
    """Write a journal file under data_dir/Journals/YYYY/MM/."""
    parts = date_str.split("-")
    year, month = parts[0], parts[1]
    month_dir = data_dir / "Journals" / year / month
    month_dir.mkdir(parents=True, exist_ok=True)
    path = month_dir / f"life-index_{date_str}_001.md"

    people_yaml = ""
    if people:
        people_list = ", ".join(f'"{p}"' for p in people)
        people_yaml = f"people: [{people_list}]\n"

    related_yaml = ""
    if related_entries:
        rel_list = ", ".join(f'"{r}"' for r in related_entries)
        related_yaml = f"related_entries: [{rel_list}]\n"

    frontmatter = f"""---
title: "{title}"
date: {date_str}
{people_yaml}{related_yaml}---

# {title}

{body}
"""
    path.write_text(frontmatter, encoding="utf-8")
    return path


@pytest.fixture
def sandbox(tmp_path: Path):
    """Create sandbox with journals exercising all 4 extractor types.

    Journals:
    - Entry 1: people=["Alice", "Bob"], wikilink [[Charlie]]
    - Entry 2: people=["Alice"], wikilinks [[Bob]], [[Charlie]]
    - Entry 3: people=["Bob", "Charlie"], related=["Journals/2026/05/other.md"]
    - Entry 4: co-occurrence only (Alice+Bob in body, no frontmatter people)
    """
    data_dir = tmp_path / "Life-Index"

    _write_journal(
        data_dir,
        "2026-05-10",
        "Meeting",
        "Met with Alice and Bob. Also discussed [[Charlie]]'s proposal.",
        people=["Alice", "Bob"],
    )
    _write_journal(
        data_dir,
        "2026-05-11",
        "Follow-up",
        "Followed up with Alice. [[Bob]] and [[Charlie]] are in agreement.",
        people=["Alice"],
    )
    _write_journal(
        data_dir,
        "2026-05-12",
        "Review",
        "Bob and Charlie reviewed. No wikilinks here.",
        people=["Bob", "Charlie"],
        related_entries=["Journals/2026/05/other.md"],
    )
    _write_journal(
        data_dir,
        "2026-05-13",
        "Co-occurrence",
        "Alice and Bob discussed the project together.",
    )

    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    return data_dir, env


class TestCandidateEdgesContract:
    """Contract tests for entity --candidate-edges --output=json."""

    def test_cli_exits_0_and_emits_valid_json(self, sandbox):
        """RED: --candidate-edges flag should be routed by entity/__main__.py."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        payload = json.loads(result.stdout)
        assert payload["success"] is True
        assert "candidates" in payload

    def test_output_schema_has_required_fields(self, sandbox):
        """Each candidate must have type, source, target, evidence_paths,
        confidence, and suggested_action."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        required = {"type", "source", "target", "evidence_paths", "confidence", "suggested_action"}
        for candidate in payload["candidates"]:
            missing = required - set(candidate.keys())
            assert not missing, f"Candidate missing fields: {missing} -> {candidate}"

    def test_each_candidate_has_at_least_one_evidence_path(self, sandbox):
        """Evidence paths must be non-empty lists of relative paths."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        for candidate in payload["candidates"]:
            paths = candidate["evidence_paths"]
            assert isinstance(paths, list), f"evidence_paths not a list: {candidate}"
            assert len(paths) >= 1, f"evidence_paths empty: {candidate}"
            for p in paths:
                assert not os.path.isabs(p), f"Absolute path: {p}"
                assert "\\" not in p, f"Backslash in path: {p}"

    def test_confidence_is_valid_float(self, sandbox):
        """Confidence must be a float between 0.0 and 1.0."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        for candidate in payload["candidates"]:
            conf = candidate["confidence"]
            assert isinstance(conf, (int, float)), f"confidence not numeric: {conf}"
            assert 0.0 <= float(conf) <= 1.0, f"confidence out of range: {conf}"

    def test_suggested_action_is_valid_enum(self, sandbox):
        """suggested_action must be one of the three known values."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        valid_actions = {
            "auto-confirm-recommended",
            "review-recommended",
            "review-required-low-confidence",
        }
        for candidate in payload["candidates"]:
            action = candidate["suggested_action"]
            assert action in valid_actions, f"Invalid suggested_action: {action}"

    def test_zero_entity_graph_writes(self, sandbox):
        """Running --candidate-edges must not modify entity_graph.yaml."""
        data_dir, env = sandbox
        graph_path = data_dir / "entity_graph.yaml"

        # Seed a minimal entity graph to ensure it exists
        graph_path.write_text(
            ('entities:\n- id: "person-alice"\n  type: "actor"\n' '  primary_name: "Alice"\n'),
            encoding="utf-8",
        )

        hash_before = _hash_file(graph_path)

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        hash_after = _hash_file(graph_path)
        assert hash_before == hash_after, (
            "entity_graph.yaml MODIFIED by --candidate-edges! "
            f"hash before={hash_before} after={hash_after}"
        )

    def test_candidates_are_deduplicated(self, sandbox):
        """No two candidates should have the same (type, source, target) triple."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        keys = []
        for c in payload["candidates"]:
            key = (c["type"], c["source"], c["target"])
            assert key not in keys, f"Duplicate candidate: {key}"
            keys.append(key)

    def test_people_extractor_produces_candidates(self, sandbox):
        """People in frontmatter should generate co-occurrence candidates."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        types = {c["type"] for c in payload["candidates"]}
        assert "people_cooccurrence" in types, (
            f"Expected people_cooccurrence in types, got: {types}. "
            f"Candidates: {json.dumps(payload['candidates'], indent=2)[:500]}"
        )

    def test_wikilink_extractor_produces_candidates(self, sandbox):
        """Wikilinks [[X]] in body text should generate candidates with type=wikilink."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        types = {c["type"] for c in payload["candidates"]}
        assert "wikilink" in types, (
            f"Expected wikilink in types, got: {types}. "
            f"Candidates: {json.dumps(payload['candidates'], indent=2)[:500]}"
        )

    def test_related_entries_extractor_produces_candidates(self, sandbox):
        """related_entries links should generate candidates with type=related_entry."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        types = {c["type"] for c in payload["candidates"]}
        assert "related_entry" in types, (
            f"Expected related_entry in types, got: {types}. "
            f"Candidates: {json.dumps(payload['candidates'], indent=2)[:500]}"
        )

    def test_edge_type_is_valid(self, sandbox):
        """Edge type must be one of the known extractor types."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        valid_types = {
            "people_cooccurrence",
            "related_entry",
            "wikilink",
            "body_cooccurrence",
        }
        for candidate in payload["candidates"]:
            assert (
                candidate["type"] in valid_types
            ), f"Invalid type: {candidate['type']} for candidate {candidate}"

    def test_candidate_edges_no_graph_write(self):
        """Static invariant: candidate_edges.py must not contain graph write paths."""
        import ast

        ce_path = Path(__file__).resolve().parents[2] / "tools" / "entity" / "candidate_edges.py"
        if not ce_path.exists():
            pytest.skip("candidate_edges.py not found")
        tree = ast.parse(ce_path.read_text(encoding="utf-8"), filename=str(ce_path))

        graph_write_calls = {"save_entity_graph", "write_text", "write_bytes", "dump"}
        write_mode_markers = {"w", "a", "x", "+"}
        offenders: list[str] = []

        def _call_name(call: ast.Call) -> str | None:
            if isinstance(call.func, ast.Attribute):
                return call.func.attr
            if isinstance(call.func, ast.Name):
                return call.func.id
            return None

        def _literal_mode(call: ast.Call) -> str | None:
            mode_node: ast.expr | None = None
            if len(call.args) >= 2:
                mode_node = call.args[1]
            for keyword in call.keywords:
                if keyword.arg == "mode":
                    mode_node = keyword.value
            if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
                return mode_node.value
            return None

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _call_name(node)
            if name in graph_write_calls:
                offenders.append(f"calls {name}()")
            if name == "open":
                mode = _literal_mode(node)
                if mode and any(marker in mode for marker in write_mode_markers):
                    offenders.append(f"opens file with write-capable mode {mode!r}")

        assert offenders == [], f"candidate_edges.py contains graph write paths: {offenders}"

    def test_output_includes_schema_version(self, sandbox):
        """Output must include schema_version (additive, following project convention)."""
        _data_dir, env = sandbox
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.entity",
                "--candidate-edges",
                "--output=json",
            ],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            encoding="utf-8",
        )
        payload = json.loads(result.stdout)
        assert "schema_version" in payload, "Missing schema_version in output"
