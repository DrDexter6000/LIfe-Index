#!/usr/bin/env python3
"""Contract test: life-index version CLI subprocess interface.

Verifies:
- `python -m tools --version` exits 0 and emits valid JSON
- `python -m tools version` exits 0 and emits valid JSON
- `python -m tools -V` exits 0 and emits valid JSON
- JSON includes required fields
- All three invocations return equivalent payloads
"""

import json
import subprocess
import sys

REQUIRED_TOP_LEVEL_KEYS = {"package_version", "bootstrap_manifest"}
REQUIRED_MANIFEST_KEYS = {
    "repo_version",
    "onboarding_schema_version",
    "requires_checkout_sync",
    "required_authority_docs",
}


def _invoke(*extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "tools", *extra_args],
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
    )


def _parse_payload(result: subprocess.CompletedProcess) -> dict:
    assert (
        result.returncode == 0
    ), f"Exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    return json.loads(result.stdout)


class TestVersionContract:
    def test_double_dash_version_exits_0(self):
        result = _invoke("--version")
        payload = _parse_payload(result)
        assert isinstance(payload, dict)

    def test_subcommand_version_exits_0(self):
        result = _invoke("version")
        payload = _parse_payload(result)
        assert isinstance(payload, dict)

    def test_short_flag_v_exits_0(self):
        result = _invoke("-V")
        payload = _parse_payload(result)
        assert isinstance(payload, dict)

    def test_payload_has_required_top_level_keys(self):
        payload = _parse_payload(_invoke("--version"))
        assert REQUIRED_TOP_LEVEL_KEYS.issubset(payload.keys())

    def test_payload_has_required_manifest_keys(self):
        payload = _parse_payload(_invoke("--version"))
        manifest = payload["bootstrap_manifest"]
        assert isinstance(manifest, dict)
        assert REQUIRED_MANIFEST_KEYS.issubset(manifest.keys())

    def test_manifest_values_sane(self):
        payload = _parse_payload(_invoke("--version"))
        manifest = payload["bootstrap_manifest"]
        assert isinstance(manifest["repo_version"], str) and len(manifest["repo_version"]) > 0
        assert isinstance(manifest["onboarding_schema_version"], str)
        assert isinstance(manifest["requires_checkout_sync"], bool)
        assert isinstance(manifest["required_authority_docs"], list)
        assert len(manifest["required_authority_docs"]) > 0

    def test_package_version_matches_manifest_repo_version(self):
        payload = _parse_payload(_invoke("--version"))
        assert payload["package_version"] == payload["bootstrap_manifest"]["repo_version"]

    def test_equivalent_payloads(self):
        p1 = _parse_payload(_invoke("--version"))
        p2 = _parse_payload(_invoke("version"))
        p3 = _parse_payload(_invoke("-V"))
        assert p1 == p2 == p3
