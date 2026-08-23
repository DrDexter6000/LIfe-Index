"""Tests for built-in event detectors."""

import os
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from tools.lib.entity_graph import save_entity_graph

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestNoJournalStreakDetector:
    def test_detects_7_day_gap(self, tmp_path: Path):
        """7+ days without a journal should trigger an event."""
        from tools.lib.event_detectors import check_no_journal_streak

        journals_dir = tmp_path / "Journals"
        old_month = journals_dir / "2026" / "03"
        old_month.mkdir(parents=True)
        old_file = old_month / "life-index_2026-03-28_001.md"
        old_file.write_text("---\ntitle: old\n---\n", encoding="utf-8")
        # Set mtime to 10 days ago
        old_time = time.time() - 10 * 86400
        os.utime(old_file, (old_time, old_time))

        events = check_no_journal_streak({"journals_dir": journals_dir})
        assert len(events) == 1
        assert events[0].type == "no_journal_streak"

    def test_no_event_if_recent_journal(self, tmp_path: Path):
        """Recent journal should not trigger streak event."""
        from tools.lib.event_detectors import check_no_journal_streak

        journals_dir = tmp_path / "Journals" / "2026" / "04"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2026-04-08_001.md").write_text(
            "---\ntitle: today\n---\n", encoding="utf-8"
        )

        events = check_no_journal_streak({"journals_dir": journals_dir})
        assert len(events) == 0

    def test_no_crash_if_no_journals_dir(self):
        """Missing journals_dir should return empty list."""
        from tools.lib.event_detectors import check_no_journal_streak

        events = check_no_journal_streak({"journals_dir": None})
        assert events == []


class TestMonthlyReviewDueDetector:
    def test_detects_missing_review(self, tmp_path: Path):
        """Last month without generated monthly index should trigger event."""
        from tools.lib.event_detectors import check_monthly_review_due

        check_date = datetime.now() - timedelta(days=30)
        month_str = f"{check_date.year}-{check_date.month:02d}"
        journals_dir = tmp_path / "Journals" / f"{check_date.year}" / f"{check_date.month:02d}"
        journals_dir.mkdir(parents=True)
        (journals_dir / f"life-index_{month_str}-15_001.md").write_text(
            "---\ntitle: test\n---\n", encoding="utf-8"
        )

        events = check_monthly_review_due({"journals_dir": tmp_path / "Journals"})
        matching_events = [
            e for e in events if e.type == "monthly_review_due" and e.data.get("month") == month_str
        ]
        assert len(matching_events) == 1
        event = matching_events[0]
        assert event.data.get("expected_artifact") == f"index_{month_str}.md"
        assert event.data.get("suggested_command") == f"life-index abstract --month {month_str}"
        assert f"life-index abstract --month {month_str}" in event.message

    def test_no_event_if_monthly_index_exists(self, tmp_path: Path):
        """Existing generated monthly index should not trigger event."""
        from tools.lib.event_detectors import check_monthly_review_due

        check_date = datetime.now() - timedelta(days=30)
        month_str = f"{check_date.year}-{check_date.month:02d}"
        journals_dir = tmp_path / "Journals" / f"{check_date.year}" / f"{check_date.month:02d}"
        journals_dir.mkdir(parents=True)
        (journals_dir / f"life-index_{month_str}-15_001.md").write_text(
            "---\ntitle: test\n---\n", encoding="utf-8"
        )
        (journals_dir / f"index_{month_str}.md").write_text("# Index", encoding="utf-8")

        events = check_monthly_review_due({"journals_dir": tmp_path / "Journals"})
        review_events = [
            e for e in events if e.type == "monthly_review_due" and e.data.get("month") == month_str
        ]
        assert len(review_events) == 0


class TestEntityAuditDueDetector:
    def test_detects_stale_entity_graph(self, tmp_path: Path):
        """entity_graph.yaml > 30 days unmodified should trigger."""
        from tools.lib.event_detectors import check_entity_audit_due

        graph_file = tmp_path / "entity_graph.yaml"
        graph_file.write_text("entities: []", encoding="utf-8")
        old_time = time.time() - 35 * 86400
        os.utime(graph_file, (old_time, old_time))

        events = check_entity_audit_due({"data_dir": tmp_path})
        assert len(events) == 1
        assert events[0].type == "entity_audit_due"

    def test_no_event_if_recently_modified(self, tmp_path: Path):
        """Recently modified entity_graph.yaml should not trigger."""
        from tools.lib.event_detectors import check_entity_audit_due

        graph_file = tmp_path / "entity_graph.yaml"
        graph_file.write_text("entities: []", encoding="utf-8")

        events = check_entity_audit_due({"data_dir": tmp_path})
        assert len(events) == 0

    def test_no_crash_if_no_entity_graph(self, tmp_path: Path):
        """Missing entity_graph.yaml should return empty list."""
        from tools.lib.event_detectors import check_entity_audit_due

        events = check_entity_audit_due({"data_dir": tmp_path})
        assert events == []


class TestEntityProfilesStaleDetector:
    def test_missing_profiles_emit_suggested_materialize_command(self, tmp_path: Path):
        """Existing confirmed graph without generated profiles should trigger a hint."""
        from tools.lib.event_detectors import check_entity_profiles_stale

        save_entity_graph(
            [
                {
                    "id": "actor-alice",
                    "type": "actor",
                    "primary_name": "Alice",
                    "aliases": [],
                    "attributes": {"kind": "human"},
                    "relationships": [],
                    "source": "user",
                    "status": "confirmed",
                }
            ],
            tmp_path / "entity_graph.yaml",
        )

        events = check_entity_profiles_stale({"data_dir": tmp_path})

        assert len(events) == 1
        event = events[0]
        assert event.type == "entity_profiles_stale"
        assert event.severity.value == "info"
        assert "life-index abstract --entities" in event.message
        assert event.data["suggested_command"] == "life-index abstract --entities"
        assert event.data["side_effect"] == "write"
        assert "derived" in event.data["side_effect_note"]
        assert "entity_graph.yaml" in event.data["side_effect_note"]
        assert event.data["reason"] == "missing_profiles"

    def test_materializing_profiles_clears_stale_signal(self, tmp_path: Path, monkeypatch):
        """stale -> materialize -> no stale event."""
        from tools.generate_index.entity_profiles import materialize_entity_profiles
        from tools.lib.event_detectors import check_entity_profiles_stale

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(tmp_path))
        save_entity_graph(
            [
                {
                    "id": "actor-alice",
                    "type": "actor",
                    "primary_name": "Alice",
                    "aliases": [],
                    "attributes": {"kind": "human"},
                    "relationships": [],
                    "source": "user",
                    "status": "confirmed",
                }
            ],
            tmp_path / "entity_graph.yaml",
        )

        assert [event.type for event in check_entity_profiles_stale({"data_dir": tmp_path})] == [
            "entity_profiles_stale"
        ]

        result = materialize_entity_profiles(data_dir=tmp_path)

        assert result["success"] is True
        assert check_entity_profiles_stale({"data_dir": tmp_path}) == []

    def test_cli_materialization_clears_stale_signal(self, tmp_path: Path):
        """The public command clears the health freshness hint."""
        from tools.lib.event_detectors import check_entity_profiles_stale

        save_entity_graph(
            [
                {
                    "id": "actor-alice",
                    "type": "actor",
                    "primary_name": "Alice",
                    "aliases": [],
                    "attributes": {"kind": "human"},
                    "relationships": [],
                    "source": "user",
                    "status": "confirmed",
                }
            ],
            tmp_path / "entity_graph.yaml",
        )
        assert check_entity_profiles_stale({"data_dir": tmp_path})

        proc = subprocess.run(
            [sys.executable, "-m", "tools", "abstract", "--entities", "--json"],
            cwd=REPO_ROOT,
            env={**os.environ, "LIFE_INDEX_DATA_DIR": str(tmp_path)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
            encoding="utf-8",
        )

        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout)[0]["success"] is True
        assert check_entity_profiles_stale({"data_dir": tmp_path}) == []

    def test_graph_hash_change_re_emits_stale_signal(self, tmp_path: Path, monkeypatch):
        """A changed graph hash should make existing profile docs stale."""
        from tools.generate_index.entity_profiles import materialize_entity_profiles
        from tools.lib.event_detectors import check_entity_profiles_stale

        monkeypatch.setenv("LIFE_INDEX_DATA_DIR", str(tmp_path))
        entities = [
            {
                "id": "actor-alice",
                "type": "actor",
                "primary_name": "Alice",
                "aliases": [],
                "attributes": {"kind": "human"},
                "relationships": [],
                "source": "user",
                "status": "confirmed",
            }
        ]
        save_entity_graph(entities, tmp_path / "entity_graph.yaml")
        assert materialize_entity_profiles(data_dir=tmp_path)["success"] is True

        entities[0]["aliases"] = ["Ally"]
        save_entity_graph(entities, tmp_path / "entity_graph.yaml")

        events = check_entity_profiles_stale({"data_dir": tmp_path})

        assert len(events) == 1
        assert events[0].data["reason"] == "source_hash_mismatch"


class TestSchemaMigrationAvailableDetector:
    def test_detects_outdated_schema(self, tmp_path: Path):
        """Journals with old schema version should trigger event."""
        from tools.lib.event_detectors import check_schema_migration_available

        journals_dir = tmp_path / "Journals" / "2025" / "01"
        journals_dir.mkdir(parents=True)
        (journals_dir / "life-index_2025-01-01_001.md").write_text(
            "---\nschema_version: 1\ntitle: old\ndate: 2025-01-01\n---\n",
            encoding="utf-8",
        )

        events = check_schema_migration_available({"journals_dir": tmp_path / "Journals"})
        assert len(events) == 1
        assert events[0].type == "schema_migration_available"


class TestIndexStaleDetector:
    def test_detects_stale_index(self, tmp_path: Path):
        """Journal mtime > index mtime should trigger event."""
        from tools.lib.event_detectors import check_index_stale

        journals_dir = tmp_path / "Journals" / "2026" / "04"
        journals_dir.mkdir(parents=True)
        index_dir = tmp_path / ".index"
        index_dir.mkdir()

        journal = journals_dir / "life-index_2026-04-08_001.md"
        journal.write_text("---\ntitle: new\n---\n", encoding="utf-8")

        fts_db = index_dir / "journals_fts.db"
        fts_db.write_text("", encoding="utf-8")
        old_time = time.time() - 3600
        os.utime(fts_db, (old_time, old_time))

        events = check_index_stale({"data_dir": tmp_path, "journals_dir": tmp_path / "Journals"})
        assert any(e.type == "index_stale" for e in events)

    def test_no_event_if_index_fresh(self, tmp_path: Path):
        """Index newer than journals with current meta should not trigger."""
        import sqlite3
        from tools.lib.event_detectors import check_index_stale
        from tools.lib.search_constants import TOKENIZER_VERSION
        from tools.lib.search_index import FTS_SCHEMA_VERSION
        from tools.lib.chinese_tokenizer import get_dict_hash

        journals_dir = tmp_path / "Journals" / "2026" / "04"
        journals_dir.mkdir(parents=True)
        index_dir = tmp_path / ".index"
        index_dir.mkdir()

        journal = journals_dir / "life-index_2026-04-08_001.md"
        journal.write_text("---\ntitle: old\n---\n", encoding="utf-8")
        old_time = time.time() - 3600
        os.utime(journal, (old_time, old_time))

        fts_db = index_dir / "journals_fts.db"
        conn = sqlite3.connect(str(fts_db))
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS journals USING fts5(path, title, content)")
        conn.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("tokenizer_version", str(TOKENIZER_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(FTS_SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("dict_hash", get_dict_hash()),
        )
        conn.commit()
        conn.close()

        # Index is newer (current time)
        os.utime(fts_db, None)

        events = check_index_stale({"data_dir": tmp_path, "journals_dir": tmp_path / "Journals"})
        assert not any(e.type == "index_stale" for e in events)

    def test_detects_version_mismatch(self, tmp_path: Path):
        """Tokenizer version mismatch should trigger index_stale event."""
        import sqlite3
        from tools.lib.event_detectors import check_index_stale
        from tools.lib.search_constants import TOKENIZER_VERSION

        journals_dir = tmp_path / "Journals" / "2026" / "04"
        journals_dir.mkdir(parents=True)
        index_dir = tmp_path / ".index"
        index_dir.mkdir()

        # Create a journal file
        journal = journals_dir / "life-index_2026-04-08_001.md"
        journal.write_text("---\ntitle: test\n---\n", encoding="utf-8")

        # Create FTS DB with outdated tokenizer version
        fts_db = index_dir / "journals_fts.db"
        conn = sqlite3.connect(str(fts_db))
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS journals USING fts5(path, title, content)")
        conn.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
        # Write a stale tokenizer version
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("tokenizer_version", str(TOKENIZER_VERSION - 1)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("schema_version", "1"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("dict_hash", "dummy_hash"),
        )
        conn.commit()
        conn.close()

        # Make index mtime newer than journal
        os.utime(fts_db, None)
        os.utime(journal, (time.time() - 3600, time.time() - 3600))

        events = check_index_stale({"data_dir": tmp_path, "journals_dir": tmp_path / "Journals"})
        stale_events = [e for e in events if e.type == "index_stale"]
        assert len(stale_events) >= 1
        assert stale_events[0].data.get("reason") == "version_mismatch"

    def test_no_version_event_if_meta_current(self, tmp_path: Path):
        """No event when tokenizer/schema versions are current."""
        import sqlite3
        from tools.lib.event_detectors import check_index_stale
        from tools.lib.search_constants import TOKENIZER_VERSION
        from tools.lib.search_index import FTS_SCHEMA_VERSION
        from tools.lib.chinese_tokenizer import get_dict_hash

        journals_dir = tmp_path / "Journals" / "2026" / "04"
        journals_dir.mkdir(parents=True)
        index_dir = tmp_path / ".index"
        index_dir.mkdir()

        journal = journals_dir / "life-index_2026-04-08_001.md"
        journal.write_text("---\ntitle: test\n---\n", encoding="utf-8")

        fts_db = index_dir / "journals_fts.db"
        conn = sqlite3.connect(str(fts_db))
        conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS journals USING fts5(path, title, content)")
        conn.execute("CREATE TABLE IF NOT EXISTS index_meta (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("tokenizer_version", str(TOKENIZER_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(FTS_SCHEMA_VERSION)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
            ("dict_hash", get_dict_hash()),
        )
        conn.commit()
        conn.close()

        # Make index newer than journal
        os.utime(fts_db, None)
        os.utime(journal, (time.time() - 3600, time.time() - 3600))

        events = check_index_stale({"data_dir": tmp_path, "journals_dir": tmp_path / "Journals"})
        assert not any(e.type == "index_stale" for e in events)
