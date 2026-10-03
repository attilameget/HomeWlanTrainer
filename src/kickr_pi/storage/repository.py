"""Lightweight SQLite settings and saved rides."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
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
"""


class Repository:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM settings WHERE id = 1").fetchone()
            if not row:
                return {}
            return json.loads(row["data"])

    def save_settings(self, data: dict[str, Any]) -> None:
        payload = json.dumps(data)
        with self._connect() as conn:
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
