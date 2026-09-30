"""Lightweight SQLite settings/workout cache (Phase A minimal)."""

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
