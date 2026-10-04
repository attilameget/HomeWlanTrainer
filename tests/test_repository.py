"""SQLite repository: merge settings + additive migrations preserve data."""

from __future__ import annotations

from pathlib import Path

from kickr_pi.storage.repository import SCHEMA_VERSION, Repository


def test_save_settings_merges_and_preserves_unknown_keys(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    repo = Repository(db)
    repo.save_settings(
        {
            "ftp_w": 200,
            "plan_weeks": 4,
            "legacy_custom_flag": True,
        }
    )
    repo.save_settings(
        {
            "plan_weeks": 8,
            "plan_strength_days_per_week": 2,
            "plan_rest_weekdays": [4, 6],
        }
    )
    saved = repo.get_settings()
    assert saved["ftp_w"] == 200
    assert saved["plan_weeks"] == 8
    assert saved["plan_strength_days_per_week"] == 2
    assert saved["plan_rest_weekdays"] == [4, 6]
    assert saved["legacy_custom_flag"] is True


def test_clear_training_plan_keeps_settings(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    repo = Repository(db)
    repo.save_settings(
        {
            "plan_weeks": 12,
            "plan_bike_days_per_week": 4,
            "plan_notes": "keep me",
        }
    )
    repo.save_training_plan({"id": "x", "days": [], "summary": "tmp"})
    assert repo.get_training_plan() is not None
    repo.clear_training_plan()
    assert repo.get_training_plan() is None
    saved = repo.get_settings()
    assert saved["plan_weeks"] == 12
    assert saved["plan_notes"] == "keep me"


def test_migration_from_legacy_db_without_schema_meta(tmp_path: Path) -> None:
    """Pre-schema_meta DBs still open; settings/rides survive."""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            data TEXT NOT NULL
        );
        CREATE TABLE rides (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL,
            duration_s REAL NOT NULL,
            avg_power_w INTEGER,
            workout_name TEXT,
            fit_path TEXT NOT NULL
        );
        INSERT INTO settings (id, data) VALUES (
            1, '{"ftp_w": 245, "plan_goal": "event", "keep": 1}'
        );
        INSERT INTO rides (
            id, started_at, ended_at, duration_s, avg_power_w, workout_name, fit_path
        ) VALUES (
            'r1', '2026-01-01T10:00:00+00:00', '2026-01-01T11:00:00+00:00',
            3600, 180, 'Test', '/tmp/r1.fit'
        );
        """
    )
    conn.commit()
    conn.close()

    repo = Repository(db)
    saved = repo.get_settings()
    assert saved["ftp_w"] == 245
    assert saved["plan_goal"] == "event"
    assert saved["keep"] == 1
    rides = repo.list_rides()
    assert len(rides) == 1 and rides[0]["id"] == "r1"

    with sqlite3.connect(db) as c2:
        ver = c2.execute("SELECT version FROM schema_meta WHERE id = 1").fetchone()
        assert ver is not None
        assert int(ver[0]) == SCHEMA_VERSION


def test_add_column_if_missing_is_idempotent(tmp_path: Path) -> None:
    import sqlite3

    db = tmp_path / "cols.db"
    repo = Repository(db)
    with repo._connect() as conn:
        Repository.add_column_if_missing(conn, "rides", "notes", "TEXT")
        Repository.add_column_if_missing(conn, "rides", "notes", "TEXT")
        conn.commit()
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(rides)").fetchall()}
    assert "notes" in cols
    # Existing ride columns still present
    assert "fit_path" in cols
