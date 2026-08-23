"""Contract tests for the entity profile assembly primitive."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from tools.lib.entity_graph import save_entity_graph

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_entity_profile(data_dir: Path, *args: str) -> dict:
    env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
    proc = subprocess.run(
        [sys.executable, "-m", "tools.entity", "profile", *args, "--json"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _profile_graph() -> list[dict]:
    return [
        {
            "id": "actor-alice",
            "type": "actor",
            "primary_name": "Alice",
            "aliases": ["Ally"],
            "attributes": {"kind": "human", "self": True},
            "relationships": [
                {
                    "target": "actor-bob",
                    "relation": "friend_of",
                    "source": "user",
                    "created_at": "2026-07-01T00:00:00+00:00",
                    "status": "confirmed",
                    "evidence": [
                        "Journals/2026/03/life-index_2026-03-14_001.md",
                        "Journals/2026/03/life-index_2026-03-15_001.md",
                        "Journals/2026/03/life-index_2026-03-14_001.md",
                    ],
                },
                {
                    "target": "actor-morgan",
                    "relation": "colleague_of",
                    "source": "agent",
                    "created_at": "2026-07-02T00:00:00+00:00",
                    "status": "candidate",
                    "evidence": ["Journals/2026/03/life-index_2026-03-16_001.md"],
                },
            ],
            "source": "user",
            "status": "confirmed",
        },
        {
            "id": "actor-bob",
            "type": "actor",
            "primary_name": "Bob",
            "aliases": [],
            "attributes": {"kind": "human"},
            "relationships": [],
            "source": "user",
            "status": "confirmed",
        },
        {
            "id": "actor-morgan",
            "type": "actor",
            "primary_name": "Morgan",
            "aliases": ["Mo"],
            "attributes": {"kind": "human"},
            "relationships": [],
            "source": "agent",
            "status": "candidate",
        },
    ]


def _write_journal(
    data_dir: Path,
    *,
    filename: str,
    title: str,
    date: str,
    body: str,
) -> None:
    journal_dir = data_dir / "Journals" / "2026" / "03"
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / filename).write_text(
        "---\n" f'title: "{title}"\n' f"date: {date}\n" "topic: [work]\n" "---\n\n" f"{body}\n",
        encoding="utf-8",
    )


def _setup_profile_fixture(data_dir: Path) -> None:
    from tools.lib.search_index import update_index

    save_entity_graph(_profile_graph(), data_dir / "entity_graph.yaml")
    _write_journal(
        data_dir,
        filename="life-index_2026-03-14_001.md",
        title="Alias Mention",
        date="2026-03-14",
        body="Ally joined the planning session.",
    )
    _write_journal(
        data_dir,
        filename="life-index_2026-03-15_001.md",
        title="Primary Mention",
        date="2026-03-15",
        body="Alice shared follow-up notes.",
    )
    assert update_index(incremental=False)["success"] is True


def test_profile_by_id_returns_identity_relationships_mentions_and_stats(
    isolated_data_dir: Path,
) -> None:
    _setup_profile_fixture(isolated_data_dir)

    result = _run_entity_profile(isolated_data_dir, "--id", "actor-alice")

    assert result["success"] is True
    assert result["schema_version"] == "v1.1.1"
    assert result["provenance"]["generator"] == "entity"
    assert result["error"] is None
    data = result["data"]
    assert set(data) == {"identity", "relationships", "mentions", "evidence", "stats"}
    assert data["identity"] == {
        "entity_id": "actor-alice",
        "primary_name": "Alice",
        "aliases": ["Ally"],
        "type": "actor",
        "kind": "human",
        "status": "confirmed",
        "is_self": True,
    }
    assert data["relationships"] == [
        {
            "target": "actor-bob",
            "target_name": "Bob",
            "relation": "friend_of",
            "source": "user",
            "created_at": "2026-07-01T00:00:00+00:00",
            "status": "confirmed",
            "evidence": [
                "Journals/2026/03/life-index_2026-03-14_001.md",
                "Journals/2026/03/life-index_2026-03-15_001.md",
            ],
        }
    ]
    assert data["evidence"] == [
        "Journals/2026/03/life-index_2026-03-14_001.md",
        "Journals/2026/03/life-index_2026-03-15_001.md",
    ]
    assert [mention["title"] for mention in data["mentions"]] == [
        "Primary Mention",
        "Alias Mention",
    ]
    assert [mention["rel_path"] for mention in data["mentions"]] == [
        "Journals/2026/03/life-index_2026-03-15_001.md",
        "Journals/2026/03/life-index_2026-03-14_001.md",
    ]
    assert data["stats"] == {
        "first_mention": "2026-03-14",
        "latest_mention": "2026-03-15",
        "mention_count": 2,
        "relationship_count": 1,
    }


def test_profile_by_unique_name_resolves_alias(isolated_data_dir: Path) -> None:
    _setup_profile_fixture(isolated_data_dir)

    result = _run_entity_profile(isolated_data_dir, "--name", "Ally")

    assert result["success"] is True
    assert result["data"]["identity"]["entity_id"] == "actor-alice"


def test_profile_mentions_treat_entity_names_as_literals(isolated_data_dir: Path) -> None:
    from tools.lib.search_index import update_index

    save_entity_graph(
        [
            {
                "id": "project-life-index",
                "type": "project",
                "primary_name": "Life Index 4.1",
                "aliases": [],
                "attributes": {},
                "relationships": [],
                "source": "user",
                "status": "confirmed",
            }
        ],
        isolated_data_dir / "entity_graph.yaml",
    )
    _write_journal(
        isolated_data_dir,
        filename="life-index_2026-03-17_001.md",
        title="Version Mention",
        date="2026-03-17",
        body="Life Index 4.1 shipped with profile docs.",
    )
    assert update_index(incremental=False)["success"] is True

    result = _run_entity_profile(isolated_data_dir, "--id", "project-life-index")

    assert result["success"] is True
    assert [mention["title"] for mention in result["data"]["mentions"]] == ["Version Mention"]


def test_candidate_entity_profile_fails_closed(isolated_data_dir: Path) -> None:
    _setup_profile_fixture(isolated_data_dir)

    result = _run_entity_profile(isolated_data_dir, "--id", "actor-morgan")

    assert result["success"] is False
    assert result["data"] == {
        "entity_id": "actor-morgan",
        "status": "candidate",
        "suggested_command": "life-index entity --review",
    }
    assert result["error"] == {
        "code": "ENTITY_PROFILE_CANDIDATE",
        "message": "candidate entities do not have confirmed profiles",
    }


def test_profile_name_ambiguity_lists_candidates(isolated_data_dir: Path) -> None:
    entities = _profile_graph()
    entities.append(
        {
            "id": "actor-alicia",
            "type": "actor",
            "primary_name": "Ally",
            "aliases": [],
            "attributes": {"kind": "human"},
            "relationships": [],
            "source": "user",
            "status": "confirmed",
        }
    )
    save_entity_graph(entities, isolated_data_dir / "entity_graph.yaml")

    result = _run_entity_profile(isolated_data_dir, "--name", "Ally")

    assert result["success"] is False
    assert result["data"] == {
        "query": "Ally",
        "candidates": [
            {"entity_id": "actor-alice", "primary_name": "Alice", "status": "confirmed"},
            {"entity_id": "actor-alicia", "primary_name": "Ally", "status": "confirmed"},
        ],
    }
    assert result["error"] == {
        "code": "ENTITY_PROFILE_AMBIGUOUS_NAME",
        "message": "--name matched multiple entities; rerun with --id",
    }


def test_profile_legacy_schema_fails_closed_with_normalize_guidance(
    isolated_data_dir: Path,
) -> None:
    (isolated_data_dir / "entity_graph.yaml").write_text(
        yaml.safe_dump(
            {
                "entities": [
                    {
                        "id": "person-alice",
                        "type": "person",
                        "primary_name": "Alice",
                        "aliases": [],
                        "relationships": [],
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = _run_entity_profile(isolated_data_dir, "--id", "person-alice")

    assert result["success"] is False
    assert result["error"]["code"] == "ENTITY_SCHEMA_LEGACY"
    assert (
        result["data"]["suggested_command"]
        == "life-index entity maintain --normalize --preview --json"
    )
