#!/usr/bin/env python3
"""
Contract tests for v1.1.1 entity graph alias metadata backcompat (B4.1).

Verifies:
1. Old YAML alias shapes (list of strings) load with default metadata.
2. New YAML alias shapes (list of dicts with name/source/confidence/created_at) load.
3. Explicit alias_metadata field merges with aliases.
4. Round-trip save/load preserves metadata.
5. Existing consumers (resolve_entity, --stats, --check) work with both shapes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(args: list[str], data_dir: Path) -> dict:
    env = os.environ.copy()
    env["LIFE_INDEX_DATA_DIR"] = str(data_dir)
    proc = subprocess.run(
        [sys.executable, "-m", "tools"] + args,
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        encoding="utf-8",
    )
    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise AssertionError(
            f"CLI output not valid JSON (exit={proc.returncode}): {exc}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    if not isinstance(payload, dict):
        raise AssertionError("CLI output JSON was not an object")
    return payload


# ── Schema validation tests ──


class TestAliasMetadataBackcompat:
    """Old YAML alias shapes remain readable with deterministic defaults."""

    def test_old_string_aliases_load_with_default_alias_metadata(self) -> None:
        from tools.lib.entity_schema import validate_entity_graph_payload

        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA", "AliasB"],
                }
            ]
        }
        fixed_time = "2026-05-23T01:00:00+00:00"
        validated = validate_entity_graph_payload(payload, load_time=fixed_time)

        entity = validated[0]
        assert entity["aliases"] == ["AliasA", "AliasB"]
        assert "alias_metadata" in entity
        meta = entity["alias_metadata"]
        assert meta["AliasA"]["source"] == "system"
        assert meta["AliasA"]["confidence"] == 1.0
        assert meta["AliasA"]["created_at"] == fixed_time
        assert meta["AliasB"]["source"] == "system"
        assert meta["AliasB"]["confidence"] == 1.0
        assert meta["AliasB"]["created_at"] == fixed_time

    def test_new_dict_aliases_load_with_explicit_alias_metadata(self) -> None:
        from tools.lib.entity_schema import validate_entity_graph_payload

        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": [
                        {
                            "name": "AliasA",
                            "source": "manual",
                            "confidence": 0.9,
                            "created_at": "2026-01-01T00:00:00+00:00",
                        },
                        {"name": "AliasB", "source": "journal", "confidence": 0.8},
                    ],
                }
            ]
        }
        fixed_time = "2026-05-23T01:00:00+00:00"
        validated = validate_entity_graph_payload(payload, load_time=fixed_time)

        entity = validated[0]
        assert entity["aliases"] == ["AliasA", "AliasB"]
        meta = entity["alias_metadata"]
        assert meta["AliasA"]["source"] == "manual"
        assert meta["AliasA"]["confidence"] == 0.9
        assert meta["AliasA"]["created_at"] == "2026-01-01T00:00:00+00:00"
        assert meta["AliasB"]["source"] == "journal"
        assert meta["AliasB"]["confidence"] == 0.8
        assert meta["AliasB"]["created_at"] == fixed_time

    def test_explicit_alias_metadata_field_overrides_defaults(self) -> None:
        from tools.lib.entity_schema import validate_entity_graph_payload

        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA", "AliasB"],
                    "alias_metadata": {
                        "AliasA": {"source": "wikilink", "confidence": 0.95},
                    },
                }
            ]
        }
        fixed_time = "2026-05-23T01:00:00+00:00"
        validated = validate_entity_graph_payload(payload, load_time=fixed_time)

        entity = validated[0]
        meta = entity["alias_metadata"]
        assert meta["AliasA"]["source"] == "wikilink"
        assert meta["AliasA"]["confidence"] == 0.95
        assert meta["AliasA"]["created_at"] == fixed_time
        # AliasB should still have defaults
        assert meta["AliasB"]["source"] == "system"
        assert meta["AliasB"]["confidence"] == 1.0

    def test_mixed_string_aliases_and_dict_aliases(self) -> None:
        from tools.lib.entity_schema import validate_entity_graph_payload

        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": [
                        "AliasA",
                        {"name": "AliasB", "source": "manual", "confidence": 0.7},
                    ],
                }
            ]
        }
        fixed_time = "2026-05-23T01:00:00+00:00"
        validated = validate_entity_graph_payload(payload, load_time=fixed_time)

        entity = validated[0]
        assert entity["aliases"] == ["AliasA", "AliasB"]
        meta = entity["alias_metadata"]
        assert meta["AliasA"]["source"] == "system"
        assert meta["AliasB"]["source"] == "manual"
        assert meta["AliasB"]["confidence"] == 0.7


class TestAliasMetadataRoundtrip:
    """Save/load roundtrip preserves alias metadata."""

    def test_roundtrip_preserves_alias_metadata(self, tmp_path: Path) -> None:
        from tools.lib.entity_graph import load_entity_graph, save_entity_graph

        graph_path = tmp_path / "entity_graph.yaml"
        entities = [
            {
                "id": "person-test",
                "type": "actor",
                "attributes": {"kind": "human"},
                "primary_name": "Test",
                "aliases": ["AliasA", "AliasB"],
                "alias_metadata": {
                    "AliasA": {
                        "source": "manual",
                        "confidence": 0.9,
                        "created_at": "2026-01-01T00:00:00+00:00",
                    },
                    "AliasB": {
                        "source": "system",
                        "confidence": 1.0,
                        "created_at": "2026-02-01T00:00:00+00:00",
                    },
                },
                "relationships": [],
            }
        ]
        save_entity_graph(entities, graph_path)
        loaded = load_entity_graph(graph_path)

        entity = loaded[0]
        assert entity["aliases"] == ["AliasA", "AliasB"]
        meta = entity["alias_metadata"]
        assert meta["AliasA"]["source"] == "manual"
        assert meta["AliasA"]["confidence"] == 0.9
        assert meta["AliasA"]["created_at"] == "2026-01-01T00:00:00+00:00"
        assert meta["AliasB"]["source"] == "system"
        assert meta["AliasB"]["created_at"] == "2026-02-01T00:00:00+00:00"


class TestAliasBackcompatConsumers:
    """Existing resolve_entity and CLI consumers work with new alias shapes."""

    def test_resolve_entity_alias_backcompat_with_old_shape(self) -> None:
        from tools.lib.entity_graph import resolve_entity

        graph = [
            {
                "id": "person-test",
                "type": "actor",
                "attributes": {"kind": "human"},
                "primary_name": "Test",
                "aliases": ["AliasA"],
                "relationships": [],
            }
        ]
        assert resolve_entity("AliasA", graph) is not None
        assert resolve_entity("AliasA", graph)["id"] == "person-test"

    def test_resolve_entity_alias_backcompat_with_new_shape(self) -> None:
        from tools.lib.entity_graph import resolve_entity

        graph = [
            {
                "id": "person-test",
                "type": "actor",
                "attributes": {"kind": "human"},
                "primary_name": "Test",
                "aliases": ["AliasA"],
                "alias_metadata": {"AliasA": {"source": "manual", "confidence": 0.9}},
                "relationships": [],
            }
        ]
        assert resolve_entity("AliasA", graph) is not None
        assert resolve_entity("AliasA", graph)["id"] == "person-test"

    def test_alias_conflict_detected_with_dict_aliases(self) -> None:
        from tools.lib.entity_schema import (
            EntityGraphValidationError,
            validate_entity_graph_payload,
        )

        payload = {
            "entities": [
                {
                    "id": "person-a",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "A",
                    "aliases": [{"name": "Shared", "source": "manual"}],
                },
                {
                    "id": "person-b",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "B",
                    "aliases": [{"name": "Shared", "source": "journal"}],
                },
            ]
        }
        with pytest.raises(EntityGraphValidationError, match="alias conflict"):
            validate_entity_graph_payload(payload)

    def test_invalid_alias_dict_missing_name_rejected(self) -> None:
        from tools.lib.entity_schema import (
            EntityGraphValidationError,
            validate_entity_graph_payload,
        )

        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": [{"source": "manual"}],
                }
            ]
        }
        with pytest.raises(EntityGraphValidationError, match="alias.name"):
            validate_entity_graph_payload(payload)


class TestEntityCliAliasBackcompat:
    """life-index entity --stats/--check work with alias_metadata present."""

    def test_entity_stats_reads_alias_metadata_backcompat(self, isolated_data_dir: Path) -> None:
        graph_path = isolated_data_dir / "entity_graph.yaml"
        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA", "AliasB"],
                    "alias_metadata": {
                        "AliasA": {"source": "manual", "confidence": 0.9},
                    },
                    "relationships": [],
                }
            ]
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

        result = _run_cli(["entity", "--stats"], isolated_data_dir)
        assert result["success"] is True
        assert result["data"]["total_aliases"] == 2

    def test_entity_check_reads_alias_metadata_backcompat(self, isolated_data_dir: Path) -> None:
        graph_path = isolated_data_dir / "entity_graph.yaml"
        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA"],
                    "alias_metadata": {
                        "AliasA": {"source": "manual", "confidence": 0.9},
                    },
                    "relationships": [],
                }
            ]
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

        result = _run_cli(["entity", "--check"], isolated_data_dir)
        assert result["success"] is True
        assert result["data"]["total_entities"] == 1
        assert result["data"]["summary"]["duplicate_lookups"] == 0

    def test_entity_audit_reads_alias_metadata_backcompat(self, isolated_data_dir: Path) -> None:
        graph_path = isolated_data_dir / "entity_graph.yaml"
        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA"],
                    "alias_metadata": {
                        "AliasA": {"source": "manual", "confidence": 0.9},
                    },
                    "relationships": [],
                }
            ]
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

        result = _run_cli(["entity", "--audit"], isolated_data_dir)
        assert result["success"] is True
        assert result["data"]["total_entities"] == 1


class TestBoostDecayPlaceholder:
    """boost_decay schema placeholder — echo-only, no runtime ranking effect."""

    def test_boost_decay_defaults_are_declared_in_entity_schema(self) -> None:
        from tools.lib.entity_schema import BOOST_DECAY_DEFAULTS, get_boost_decay_defaults

        assert isinstance(BOOST_DECAY_DEFAULTS, dict)
        assert BOOST_DECAY_DEFAULTS["formula"] == "1 / (1 + k * (n - 1)^2)"
        assert BOOST_DECAY_DEFAULTS["k"] == 0.001
        assert "v1.2.0" in BOOST_DECAY_DEFAULTS["note"]

        defaults = get_boost_decay_defaults()
        assert defaults == BOOST_DECAY_DEFAULTS
        assert defaults is not BOOST_DECAY_DEFAULTS

    def test_entity_audit_echos_boost_decay(self, isolated_data_dir: Path) -> None:
        graph_path = isolated_data_dir / "entity_graph.yaml"
        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA"],
                    "relationships": [],
                }
            ],
            "boost_decay": {
                "formula": "1 / (1 + k * (n - 1)^2)",
                "k": 0.001,
                "note": "Placeholder constant. To be calibrated via eval gate in v1.2.0 Cycle 2.",
            },
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

        result = _run_cli(["entity", "--audit"], isolated_data_dir)
        assert result["success"] is True
        assert "boost_decay" in result["data"]
        assert result["data"]["boost_decay"]["formula"] == "1 / (1 + k * (n - 1)^2)"
        assert result["data"]["boost_decay"]["k"] == 0.001
        assert "v1.2.0" in result["data"]["boost_decay"]["note"]

    def test_entity_stats_echos_boost_decay(self, isolated_data_dir: Path) -> None:
        graph_path = isolated_data_dir / "entity_graph.yaml"
        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA"],
                    "relationships": [],
                }
            ],
            "boost_decay": {
                "formula": "1 / (1 + k * (n - 1)^2)",
                "k": 0.001,
                "note": "Placeholder constant. To be calibrated via eval gate in v1.2.0 Cycle 2.",
            },
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

        result = _run_cli(["entity", "--stats"], isolated_data_dir)
        assert result["success"] is True
        assert "boost_decay" in result["data"]
        assert result["data"]["boost_decay"]["formula"] == "1 / (1 + k * (n - 1)^2)"
        assert result["data"]["boost_decay"]["k"] == 0.001
        assert "v1.2.0" in result["data"]["boost_decay"]["note"]

    def test_missing_boost_decay_defaults_safely(self, isolated_data_dir: Path) -> None:
        graph_path = isolated_data_dir / "entity_graph.yaml"
        payload = {
            "entities": [
                {
                    "id": "person-test",
                    "type": "actor",
                    "attributes": {"kind": "human"},
                    "primary_name": "Test",
                    "aliases": ["AliasA"],
                    "relationships": [],
                }
            ]
        }
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with graph_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)

        result = _run_cli(["entity", "--audit"], isolated_data_dir)
        assert result["success"] is True
        assert "boost_decay" in result["data"]
        assert result["data"]["boost_decay"]["formula"] == "1 / (1 + k * (n - 1)^2)"
        assert result["data"]["boost_decay"]["k"] == 0.001
        assert "v1.2.0" in result["data"]["boost_decay"]["note"]

    def test_boost_decay_not_in_search_ranking(self) -> None:
        forbidden_modules = [
            "tools.lib.search_constants",
            "tools.search_journals",
            "tools.eval.calibrate",
        ]
        for module_name in forbidden_modules:
            try:
                mod = __import__(module_name, fromlist=["*"])
            except ImportError:
                continue
            if "boost_decay" in str(dir(mod)):
                assert False, f"{module_name} exports boost_decay"
