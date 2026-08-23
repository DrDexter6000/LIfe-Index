"""Contract tests for v1.1.1 provenance helper (A1) and CLI wiring (A2).

A1 tests validate the reusable provenance envelope that JSON-generating
commands consume.  A2 tests validate that the six covered CLI commands
actually emit ``schema_version`` and ``provenance`` in their JSON output.
"""

import copy
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_observability():
    from tools.lib.observability import build_provenance_envelope

    return build_provenance_envelope


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


class TestProvenanceEnvelopeSchema:
    """Top-level schema_version + provenance field contract."""

    def test_schema_version_is_v111(self):
        build = _import_observability()
        result = build(
            source_data={"k": "v"},
            generator="search",
            params={"query": "test"},
        )
        assert result["schema_version"] == "v1.1.1"

    def test_provenance_key_exists(self):
        build = _import_observability()
        result = build(
            source_data={"k": "v"},
            generator="search",
            params={"query": "test"},
        )
        assert "provenance" in result

    def test_provenance_has_all_required_fields(self):
        build = _import_observability()
        result = build(
            source_data={"k": "v"},
            generator="search",
            params={"query": "test"},
        )
        prov = result["provenance"]
        required = [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]
        for field in required:
            assert field in prov, f"missing field: {field}"


class TestSourceHash:
    """source_hash: stable SHA-256 for semantically identical inputs."""

    def test_stable_for_same_input(self):
        build = _import_observability()
        data = {"entries": ["a", "b", "c"]}
        r1 = build(source_data=data, generator="search", params={})
        r2 = build(source_data=data, generator="search", params={})
        assert r1["provenance"]["source_hash"] == r2["provenance"]["source_hash"]

    def test_differs_for_different_input(self):
        build = _import_observability()
        r1 = build(source_data={"x": 1}, generator="search", params={})
        r2 = build(source_data={"x": 2}, generator="search", params={})
        assert r1["provenance"]["source_hash"] != r2["provenance"]["source_hash"]

    def test_prefix_sha256(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        assert result["provenance"]["source_hash"].startswith("sha256:")

    def test_json_serialization_order_stability(self):
        build = _import_observability()
        data1 = {"a": 1, "b": 2}
        data2 = {"b": 2, "a": 1}
        r1 = build(source_data=data1, generator="search", params={})
        r2 = build(source_data=data2, generator="search", params={})
        assert r1["provenance"]["source_hash"] == r2["provenance"]["source_hash"]


class TestParamsHash:
    """params_hash: stable hash for command parameters."""

    def test_stable_for_same_params(self):
        build = _import_observability()
        params = {"query": "hello", "level": 3}
        r1 = build(source_data={}, generator="search", params=params)
        r2 = build(source_data={}, generator="search", params=params)
        assert r1["provenance"]["params_hash"] == r2["provenance"]["params_hash"]

    def test_differs_for_different_params(self):
        build = _import_observability()
        r1 = build(source_data={}, generator="search", params={"q": "a"})
        r2 = build(source_data={}, generator="search", params={"q": "b"})
        assert r1["provenance"]["params_hash"] != r2["provenance"]["params_hash"]

    def test_prefix_sha256(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        assert result["provenance"]["params_hash"].startswith("sha256:")


class TestGeneratedAt:
    """generated_at: ISO 8601 UTC, testable without wall-clock flakiness."""

    def test_iso8601_utc_format(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        ts = result["provenance"]["generated_at"]
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is not None

    def test_utc_timezone(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        ts = result["provenance"]["generated_at"]
        assert ts.endswith("+00:00") or ts.endswith("Z")

    def test_accepts_override_for_determinism(self):
        build = _import_observability()
        fixed_ts = "2026-01-01T00:00:00+00:00"
        result = build(
            source_data={},
            generator="search",
            params={},
            generated_at=fixed_ts,
        )
        assert result["provenance"]["generated_at"] == fixed_ts


class TestGeneratorEnum:
    """generator: validate against the planned enum family."""

    VALID_GENERATORS = [
        "search",
        "index",
        "eval",
        "entity",
        "maintenance",
        "trajectory",
    ]

    @pytest.mark.parametrize("gen", VALID_GENERATORS)
    def test_valid_generators_accepted(self, gen):
        build = _import_observability()
        result = build(source_data={}, generator=gen, params={})
        assert result["provenance"]["generator"] == gen

    def test_invalid_generator_rejected(self):
        build = _import_observability()
        with pytest.raises(ValueError):
            build(source_data={}, generator="invalid_tool", params={})


class TestToolVersion:
    """tool_version: sourced from existing project version mechanism."""

    def test_tool_version_is_string(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        assert isinstance(result["provenance"]["tool_version"], str)

    def test_tool_version_not_empty(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        assert len(result["provenance"]["tool_version"]) > 0


class TestFixtureVersion:
    """fixture_version: null by default, set only for eval."""

    def test_default_null(self):
        build = _import_observability()
        result = build(source_data={}, generator="search", params={})
        assert result["provenance"]["fixture_version"] is None

    def test_can_be_set(self):
        build = _import_observability()
        result = build(
            source_data={},
            generator="eval",
            params={},
            fixture_version="2026-05-22",
        )
        assert result["provenance"]["fixture_version"] == "2026-05-22"


class TestInputImmutability:
    """Helper must not mutate caller's input."""

    def test_source_data_not_mutated(self):
        build = _import_observability()
        original = {"key": "value", "nested": [1, 2, 3]}
        frozen = copy.deepcopy(original)
        build(source_data=original, generator="search", params={})
        assert original == frozen

    def test_params_not_mutated(self):
        build = _import_observability()
        original = {"query": "test", "level": 3}
        frozen = copy.deepcopy(original)
        build(source_data={}, generator="search", params=original)
        assert original == frozen

    def test_result_independent_of_input_mutation(self):
        build = _import_observability()
        data = {"k": "v"}
        result = build(source_data=data, generator="search", params={})
        data["k"] = "mutated"
        result2 = build(source_data={"k": "v"}, generator="search", params={})
        assert result["provenance"]["source_hash"] == result2["provenance"]["source_hash"]


class TestJsonSerializable:
    """Entire result must be JSON-serializable."""

    def test_json_round_trip(self):
        build = _import_observability()
        result = build(
            source_data={"entries": [1, 2]},
            generator="index",
            params={"rebuild": False},
        )
        serialized = json.dumps(result)
        deserialized = json.loads(serialized)
        assert deserialized == result


# ====================================================================
# A2 CLI wiring tests — each covered command emits provenance
# ====================================================================


class TestSearchProvenance:
    """search --json output contains provenance envelope."""

    def test_schema_version_v111(self, isolated_data_dir):
        payload = _run_cli(
            ["search", "--query", "test", "--no-semantic"],
            isolated_data_dir,
        )
        assert payload["schema_version"] == "v1.1.1"

    def test_provenance_generator_is_search(self, isolated_data_dir):
        payload = _run_cli(
            ["search", "--query", "test", "--no-semantic"],
            isolated_data_dir,
        )
        assert payload["provenance"]["generator"] == "search"

    def test_provenance_has_required_fields(self, isolated_data_dir):
        payload = _run_cli(
            ["search", "--query", "test", "--no-semantic"],
            isolated_data_dir,
        )
        for field in [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]:
            assert field in payload["provenance"], f"missing: {field}"

    def test_existing_fields_preserved(self, isolated_data_dir):
        payload = _run_cli(
            ["search", "--query", "test", "--no-semantic"],
            isolated_data_dir,
        )
        assert "success" in payload
        assert "merged_results" in payload


class TestIndexProvenance:
    """index --json output contains provenance envelope."""

    def test_schema_version_v111(self, isolated_data_dir):
        payload = _run_cli(["index", "--json"], isolated_data_dir)
        assert payload["schema_version"] == "v1.1.1"

    def test_provenance_generator_is_index(self, isolated_data_dir):
        payload = _run_cli(["index", "--json"], isolated_data_dir)
        assert payload["provenance"]["generator"] == "index"

    def test_provenance_has_required_fields(self, isolated_data_dir):
        payload = _run_cli(["index", "--json"], isolated_data_dir)
        for field in [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]:
            assert field in payload["provenance"], f"missing: {field}"

    def test_existing_fields_preserved(self, isolated_data_dir):
        payload = _run_cli(["index", "--json"], isolated_data_dir)
        assert "success" in payload


class TestEvalProvenance:
    """eval --json output contains provenance envelope."""

    def test_schema_version_v111(self, isolated_data_dir):
        payload = _run_cli(["eval", "--json"], isolated_data_dir)
        assert payload["schema_version"] == "v1.1.1"

    def test_provenance_generator_is_eval(self, isolated_data_dir):
        payload = _run_cli(["eval", "--json"], isolated_data_dir)
        assert payload["provenance"]["generator"] == "eval"

    def test_provenance_has_required_fields(self, isolated_data_dir):
        payload = _run_cli(["eval", "--json"], isolated_data_dir)
        for field in [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]:
            assert field in payload["provenance"], f"missing: {field}"

    def test_existing_fields_preserved(self, isolated_data_dir):
        payload = _run_cli(["eval", "--json"], isolated_data_dir)
        assert "success" in payload
        assert "data" in payload


class TestEntityProvenance:
    """entity --list output contains provenance envelope."""

    def test_schema_version_v111(self, isolated_data_dir):
        payload = _run_cli(["entity", "--list"], isolated_data_dir)
        assert payload["schema_version"] == "v1.1.1"

    def test_provenance_generator_is_entity(self, isolated_data_dir):
        payload = _run_cli(["entity", "--list"], isolated_data_dir)
        assert payload["provenance"]["generator"] == "entity"

    def test_provenance_has_required_fields(self, isolated_data_dir):
        payload = _run_cli(["entity", "--list"], isolated_data_dir)
        for field in [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]:
            assert field in payload["provenance"], f"missing: {field}"

    def test_existing_fields_preserved(self, isolated_data_dir):
        payload = _run_cli(["entity", "--list"], isolated_data_dir)
        assert "success" in payload


class TestMaintenanceProvenance:
    """maintenance --output=json output contains provenance envelope."""

    def test_schema_version_v111(self, isolated_data_dir):
        payload = _run_cli(["maintenance", "--output=json"], isolated_data_dir)
        assert payload["schema_version"] == "v1.1.1"

    def test_provenance_generator_is_maintenance(self, isolated_data_dir):
        payload = _run_cli(["maintenance", "--output=json"], isolated_data_dir)
        assert payload["provenance"]["generator"] == "maintenance"

    def test_provenance_has_required_fields(self, isolated_data_dir):
        payload = _run_cli(["maintenance", "--output=json"], isolated_data_dir)
        for field in [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]:
            assert field in payload["provenance"], f"missing: {field}"

    def test_existing_fields_preserved(self, isolated_data_dir):
        payload = _run_cli(["maintenance", "--output=json"], isolated_data_dir)
        assert "success" in payload


class TestTrajectoryProvenance:
    """trajectory output contains provenance envelope."""

    def test_schema_version_v111(self, isolated_data_dir):
        payload = _run_cli(
            ["trajectory", "--field=weight", "--range=2025-01..2025-01"],
            isolated_data_dir,
        )
        assert payload["schema_version"] == "v1.1.1"

    def test_provenance_generator_is_trajectory(self, isolated_data_dir):
        payload = _run_cli(
            ["trajectory", "--field=weight", "--range=2025-01..2025-01"],
            isolated_data_dir,
        )
        assert payload["provenance"]["generator"] == "trajectory"

    def test_provenance_has_required_fields(self, isolated_data_dir):
        payload = _run_cli(
            ["trajectory", "--field=weight", "--range=2025-01..2025-01"],
            isolated_data_dir,
        )
        for field in [
            "source_hash",
            "tool_version",
            "generated_at",
            "generator",
            "params_hash",
            "fixture_version",
        ]:
            assert field in payload["provenance"], f"missing: {field}"

    def test_existing_fields_preserved(self, isolated_data_dir):
        payload = _run_cli(
            ["trajectory", "--field=weight", "--range=2025-01..2025-01"],
            isolated_data_dir,
        )
        assert "success" in payload
