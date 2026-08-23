"""Tests for generated entity profile documents."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tools.lib.entity_graph import save_entity_graph

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_abstract_entities(data_dir: Path, *args: str) -> list[dict]:
    env = {**os.environ, "LIFE_INDEX_DATA_DIR": str(data_dir)}
    proc = subprocess.run(
        [sys.executable, "-m", "tools", "abstract", "--entities", *args, "--json"],
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
    payload = json.loads(proc.stdout)
    assert isinstance(payload, list)
    return payload


def _entity_graph() -> list[dict]:
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
                    "evidence": ["Journals/2026/03/life-index_2026-03-14_001.md"],
                }
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
            "aliases": [],
            "attributes": {"kind": "human"},
            "relationships": [],
            "source": "agent",
            "status": "candidate",
        },
    ]


def _write_journal(data_dir: Path, *, name: str, title: str, date: str, body: str) -> None:
    journal_dir = data_dir / "Journals" / "2026" / "03"
    journal_dir.mkdir(parents=True, exist_ok=True)
    (journal_dir / name).write_text(
        "\n".join(
            [
                "---",
                f'title: "{title}"',
                f"date: {date}",
                "topic: [life]",
                "---",
                "",
                f"# {title}",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


def _setup_fixture(data_dir: Path) -> bytes:
    from tools.lib.search_index import update_index

    save_entity_graph(_entity_graph(), data_dir / "entity_graph.yaml")
    _write_journal(
        data_dir,
        name="life-index_2026-03-14_001.md",
        title="Alias note",
        date="2026-03-14",
        body="Ally joined the planning session.",
    )
    _write_journal(
        data_dir,
        name="life-index_2026-03-15_001.md",
        title="Primary note",
        date="2026-03-15",
        body="Alice shared follow-up notes.",
    )
    (data_dir / "INDEX.md").write_text(
        "# Life Index\n\n## Existing\n\nKeep this.\n", encoding="utf-8"
    )
    entities_dir = data_dir / "Entities"
    entities_dir.mkdir(parents=True)
    (entities_dir / "actor-morgan.md").write_text(
        "\n".join(
            [
                "---",
                "entity_id: actor-morgan",
                "generated_by: life-index abstract --entities",
                'source_hash: "sha256:old"',
                "---",
                "",
                "# Morgan",
            ]
        ),
        encoding="utf-8",
    )
    assert update_index(incremental=False)["success"] is True
    return (data_dir / "entity_graph.yaml").read_bytes()


def _generated_bytes(data_dir: Path) -> dict[str, bytes]:
    paths = [
        data_dir / "INDEX.md",
        data_dir / "Entities" / "index.md",
        data_dir / "Entities" / "actor-alice.md",
        data_dir / "Entities" / "actor-bob.md",
    ]
    return {path.relative_to(data_dir).as_posix(): path.read_bytes() for path in paths}


def test_abstract_entities_materializes_profiles_idempotently_and_readonly(
    isolated_data_dir: Path,
) -> None:
    graph_before = _setup_fixture(isolated_data_dir)

    payload = _run_abstract_entities(isolated_data_dir)

    assert (isolated_data_dir / "entity_graph.yaml").read_bytes() == graph_before
    result = payload[0]
    assert result["success"] is True
    assert result["type"] == "entity-profiles"
    assert result["profile_count"] == 2
    assert result["skipped_candidate_count"] == 1
    assert result["removed_stale_profiles"] == ["actor-morgan.md"]
    assert result["root_index_path"].endswith("INDEX.md")

    first_bytes = _generated_bytes(isolated_data_dir)
    root_index = first_bytes["INDEX.md"].decode("utf-8")
    assert "[Entity Profiles](Entities/index.md)" in root_index

    entity_index = first_bytes["Entities/index.md"].decode("utf-8")
    assert "# Entity Profiles" in entity_index
    assert "[Alice](actor-alice.md)" in entity_index
    assert "[Bob](actor-bob.md)" in entity_index
    assert "Morgan" not in entity_index

    profile = first_bytes["Entities/actor-alice.md"].decode("utf-8")
    assert "entity_id: actor-alice" in profile
    assert "type: actor" in profile
    assert "kind: human" in profile
    assert "status: confirmed" in profile
    assert "is_self: true" in profile
    assert "- Self: `true`" in profile
    assert "# Alice" in profile
    assert "friend_of" in profile
    assert "Journals/2026/03/life-index_2026-03-14_001.md" in profile
    assert not (isolated_data_dir / "Entities" / "Alice.md").exists()
    assert not (isolated_data_dir / "Entities" / "actor-morgan.md").exists()

    _run_abstract_entities(isolated_data_dir)

    assert _generated_bytes(isolated_data_dir) == first_bytes
    assert (isolated_data_dir / "entity_graph.yaml").read_bytes() == graph_before


def test_abstract_entities_id_materializes_single_profile(isolated_data_dir: Path) -> None:
    _setup_fixture(isolated_data_dir)

    payload = _run_abstract_entities(isolated_data_dir, "--id", "actor-alice")

    assert payload[0]["success"] is True
    assert payload[0]["profile_count"] == 1
    assert (isolated_data_dir / "Entities" / "actor-alice.md").exists()
    assert not (isolated_data_dir / "Entities" / "actor-bob.md").exists()
    assert "Bob" not in (isolated_data_dir / "Entities" / "index.md").read_text(encoding="utf-8")
