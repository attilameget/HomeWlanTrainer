"""Lightweight SQLite settings and saved rides.

Schema changes are additive only. See `_migrate` and `.cursor/rules/sqlite-data-preserving-migrations.mdc`.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Bump when adding a migration step in MIGRATIONS (never reuse a version).
SCHEMA_VERSION = 1

# Base DDL — CREATE IF NOT EXISTS only (safe on existing DBs).
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workouts (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT,
    name TEXT NOT NULL,
    sport TEXT,
    scheduled_date TEXT,
    total_s INTEGER,
    stages_json TEXT NOT NULL,
    raw_json TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS rides (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    duration_s REAL NOT NULL,
    avg_power_w INTEGER,
    workout_name TEXT,
    fit_path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS training_plans (
    id TEXT PRIMARY KEY CHECK (id = 'active'),
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _migration_v1(conn: sqlite3.Connection) -> None:
    """Baseline tables (already applied via SCHEMA CREATE IF NOT EXISTS)."""
    return None


# Ordered migration steps. Each step must be additive / data-preserving.
# Never DROP TABLE, DELETE user rows, or rewrite JSON blobs in a way that
# discards unknown keys. Prefer CREATE TABLE IF NOT EXISTS and
# ALTER TABLE … ADD COLUMN (ignore duplicate-column errors).
MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_v1),
]


class Repository:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT version FROM schema_meta WHERE id = 1"
        ).fetchone()
        current = int(row["version"]) if row else 0
        if current > SCHEMA_VERSION:
            logger.warning(
                "database schema version %s is newer than code %s — skipping migrations",
                current,
                SCHEMA_VERSION,
            )
            return
        for version, step in MIGRATIONS:
            if current >= version:
                continue
            logger.info("applying SQLite migration v%s", version)
            step(conn)
            conn.execute(
                "INSERT INTO schema_meta (id, version) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET version = excluded.version",
                (version,),
            )
            current = version
        if current < SCHEMA_VERSION:
            # SCHEMA_VERSION ahead of last migration entry — keep meta in sync
            conn.execute(
                "INSERT INTO schema_meta (id, version) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET version = excluded.version",
                (SCHEMA_VERSION,),
            )

    @staticmethod
    def add_column_if_missing(
        conn: sqlite3.Connection, table: str, column: str, col_type: str
    ) -> None:
        """Additive column helper for future migrations (preserves all rows)."""
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        names = {str(r["name"]) for r in rows}
        if column in names:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
            if not row:
                return {}
            data = json.loads(row["data"])
            return data if isinstance(data, dict) else {}

    def save_settings(self, data: dict[str, Any]) -> None:
        """
        Merge into the existing settings JSON blob.

        Unknown / future keys already in the DB are preserved when callers
        pass a partial or known-fields-only dict (e.g. persisted_settings()).
        """
        if not isinstance(data, dict):
            raise TypeError("settings data must be a dict")
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
            existing: dict[str, Any] = {}
            if row:
                try:
                    parsed = json.loads(row["data"])
                    if isinstance(parsed, dict):
                        existing = parsed
                except json.JSONDecodeError:
                    logger.warning("corrupt settings blob — replacing with new data")
            merged = {**existing, **data}
            payload = json.dumps(merged)
            conn.execute(
                "INSERT INTO settings (id, data) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (payload,),
            )
            conn.commit()

    def insert_ride(self, ride: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO rides "
                "(id, started_at, ended_at, duration_s, avg_power_w, workout_name, fit_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ride["id"],
                    ride["started_at"],
                    ride["ended_at"],
                    float(ride["duration_s"]),
                    ride.get("avg_power_w"),
                    ride.get("workout_name"),
                    ride["fit_path"],
                ),
            )
            conn.commit()

    def list_rides(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, started_at, ended_at, duration_s, avg_power_w, workout_name "
                "FROM rides ORDER BY started_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_ride(self, ride_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, started_at, ended_at, duration_s, avg_power_w, "
                "workout_name, fit_path FROM rides WHERE id = ?",
                (ride_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_ride(self, ride_id: str) -> dict[str, Any] | None:
        ride = self.get_ride(ride_id)
        if ride is None:
            return None
        with self._connect() as conn:
            conn.execute("DELETE FROM rides WHERE id = ?", (ride_id,))
            conn.commit()
        return ride

    def get_training_plan(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM training_plans WHERE id = 'active'"
            ).fetchone()
            if not row:
                return None
            return json.loads(row["data"])

    def save_training_plan(self, data: dict[str, Any]) -> None:
        from datetime import datetime, timezone

        payload = json.dumps(data)
        updated = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO training_plans (id, data, updated_at) VALUES ('active', ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, "
                "updated_at = excluded.updated_at",
                (payload, updated),
            )
            conn.commit()

    def clear_training_plan(self) -> None:
        """Remove the active plan calendar only — does not touch settings preferences."""
        with self._connect() as conn:
            conn.execute("DELETE FROM training_plans WHERE id = 'active'")
            conn.commit()
