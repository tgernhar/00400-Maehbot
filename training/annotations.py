"""Annotation storage as JSON alongside database."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from storage.database import Database
from storage.paths import StoragePaths


def save_annotation(
    paths: StoragePaths,
    db: Database,
    session_id: int,
    frame_index: int,
    class_id: str,
    bbox: dict[str, float],
) -> dict[str, Any]:
    ann_id = db.insert_annotation(
        session_id=session_id,
        frame_index=frame_index,
        class_id=class_id,
        bbox=bbox,
        created_at=time.time(),
    )
    session_dir = paths.annotations / str(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "id": ann_id,
        "session_id": session_id,
        "frame_index": frame_index,
        "class_id": class_id,
        "bbox": bbox,
        "created_at": time.time(),
    }
    out = session_dir / f"frame_{frame_index}_{ann_id}.json"
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def list_session_annotations(db: Database, session_id: int) -> list[dict[str, Any]]:
    return db.list_annotations(session_id)
