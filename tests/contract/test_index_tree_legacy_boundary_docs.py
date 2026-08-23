"""Contract tests for the agent-facing Index Tree boundary."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
API_MD = REPO_ROOT / "docs" / "API.md"
SKILL_MD = REPO_ROOT / "SKILL.md"
CAPABILITIES_JSON = REPO_ROOT / "tools" / "mcp_discovery" / "capabilities.json"


def _api_endpoint_block() -> str:
    content = API_MD.read_text(encoding="utf-8")
    section_start = content.index("## index-tree")
    start = content.index("### 端点", section_start)
    fence_start = content.index("```bash", start)
    fence_end = content.index("```", fence_start + len("```bash"))
    return content[fence_start:fence_end]


def test_index_tree_primary_api_examples_exclude_legacy_diagnostics() -> None:
    endpoint_block = _api_endpoint_block()

    assert "index-tree materialize" in endpoint_block
    assert "index-tree freshness" in endpoint_block
    assert "index-tree ensure" in endpoint_block
    assert "index-tree discover" in endpoint_block
    assert "index-tree navigate" in endpoint_block

    assert "index-tree nodes" not in endpoint_block
    assert "index-tree lens" not in endpoint_block
    assert "index-tree shadow" not in endpoint_block


def test_index_tree_legacy_diagnostics_are_documented_as_debug_only() -> None:
    api = API_MD.read_text(encoding="utf-8")

    assert "### Debug-only legacy diagnostics" in api
    assert "Host-agent 查询流程应使用" in api
    assert "`ensure`、`discover`、`navigate`" in api
    assert "`nodes`、`lens`、`shadow`" in api
    assert "debug-only legacy 诊断接口" in api


def test_skill_routes_host_agents_to_navigation_not_legacy_diagnostics() -> None:
    skill = SKILL_MD.read_text(encoding="utf-8")

    assert "`ensure` -> `discover` -> `navigate`" in skill
    assert "Do not use `index-tree nodes`, `index-tree lens`, or `index-tree shadow`" in skill
    assert "debug-only legacy" in skill
    assert "diagnostics retained for compatibility" in skill


def test_mcp_capability_marks_nodes_lens_shadow_as_legacy_diagnostics() -> None:
    capabilities = json.loads(CAPABILITIES_JSON.read_text(encoding="utf-8"))
    index_tree = next(entry for entry in capabilities if entry["name"] == "index-tree")
    description = index_tree["description"]

    assert description.startswith("Deterministic Index B navigation:")
    assert "ensure, discover, navigate" in description
    assert "legacy diagnostics: nodes, lens, shadow" in description


def test_index_tree_help_marks_legacy_subcommands_debug_only() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tools", "index-tree", "--help"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    help_text = result.stdout

    assert "Debug-only legacy: emit Index Tree node summaries" in help_text
    assert "Debug-only legacy: emit cross-time derived lens" in help_text
    assert "Debug-only legacy: emit search-shadow diagnostics" in help_text
    assert "Ensure Index B is fresh or return journal fallback" in help_text
    assert "Return scoped deterministic facet value menus" in help_text
    assert "Run deterministic structured navigation over Index B" in help_text
