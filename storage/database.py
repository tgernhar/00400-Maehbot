"""SQLite persistence for detections, training sessions, and annotations."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_ms REAL NOT NULL,
    class_id TEXT NOT NULL,
    confidence REAL NOT NULL,
    bbox_json TEXT NOT NULL,
    image_path TEXT,
    spray_scheduled INTEGER NOT NULL DEFAULT 0,
    spray_blocked_reason TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS training_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    video_path TEXT NOT NULL,
    frame_count INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    frame_index INTEGER NOT NULL,
    class_id TEXT NOT NULL,
    bbox_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES training_sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_detections_created ON detections(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_annotations_session ON annotations(session_id);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def insert_detection(
        self,
        timestamp_ms: float,
        class_id: str,
        confidence: float,
        bbox: dict[str, float],
        image_path: str | None,
        spray_scheduled: bool,
        spray_blocked_reason: str | None,
        created_at: float,
    ) -> int:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO detections
                    (timestamp_ms, class_id, confidence, bbox_json, image_path,
                     spray_scheduled, spray_blocked_reason, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp_ms,
                        class_id,
                        confidence,
                        json.dumps(bbox),
                        image_path,
                        1 if spray_scheduled else 0,
                        spray_blocked_reason,
                        created_at,
                    ),
                )
                return int(cur.lastrowid)

    def get_detection(self, detection_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM detections WHERE id = ?", (detection_id,)
            ).fetchone()
        return self._row_to_detection(row) if row else None

    def list_detections(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM detections ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_detection(r) for r in rows]

    def count_detections_with_images(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM detections WHERE image_path IS NOT NULL"
            ).fetchone()
        return int(row["c"])

    def oldest_detection_ids_with_images(self, count: int) -> list[tuple[int, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, image_path FROM detections
                WHERE image_path IS NOT NULL
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (count,),
            ).fetchall()
        return [(int(r["id"]), r["image_path"]) for r in rows]

    def delete_detection(self, detection_id: int) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("DELETE FROM detections WHERE id = ?", (detection_id,))

    def insert_training_session(
        self, name: str, video_path: str, frame_count: int, created_at: float
    ) -> int:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO training_sessions (name, video_path, frame_count, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (name, video_path, frame_count, created_at),
                )
                return int(cur.lastrowid)

    def list_training_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM training_sessions ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_training_session(self, session_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM training_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def delete_training_session(self, session_id: int) -> bool:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT id FROM training_sessions WHERE id = ?", (session_id,)
                ).fetchone()
                if not row:
                    return False
                conn.execute(
                    "DELETE FROM annotations WHERE session_id = ?", (session_id,)
                )
                conn.execute(
                    "DELETE FROM training_sessions WHERE id = ?", (session_id,)
                )
                return True

    def insert_annotation(
        self,
        session_id: int,
        frame_index: int,
        class_id: str,
        bbox: dict[str, float],
        created_at: float,
    ) -> int:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO annotations
                    (session_id, frame_index, class_id, bbox_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        frame_index,
                        class_id,
                        json.dumps(bbox),
                        created_at,
                    ),
                )
                return int(cur.lastrowid)

    def list_annotations(self, session_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM annotations WHERE session_id = ? ORDER BY frame_index",
                (session_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["bbox"] = json.loads(d["bbox_json"])
            result.append(d)
        return result

    @staticmethod
    def _row_to_detection(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "timestamp_ms": row["timestamp_ms"],
            "class_id": row["class_id"],
            "confidence": row["confidence"],
            "bbox": json.loads(row["bbox_json"]),
            "image_path": row["image_path"],
            "spray_scheduled": bool(row["spray_scheduled"]),
            "spray_blocked_reason": row["spray_blocked_reason"],
            "created_at": row["created_at"],
        }
