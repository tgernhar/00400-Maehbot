"""Tests for storage retention."""

import time
from pathlib import Path

from maehbot.types import BBox, Detection, SprayEvent
from storage.async_writer import AsyncStorageWriter
from storage.database import Database
from storage.paths import StoragePaths
from storage.retention import RetentionManager, dir_size_bytes


def test_retention_removes_old_images(tmp_path: Path):
    root = tmp_path / "data"
    paths = StoragePaths(root)
    paths.ensure()
    db = Database(paths.db_path)
    retention = RetentionManager(paths, db, max_archived_images=2, max_total_bytes=10**9)

    for i in range(4):
        det_id = db.insert_detection(
            timestamp_ms=i,
            class_id="clover",
            confidence=0.9,
            bbox={"x": 1, "y": 1, "width": 10, "height": 10},
            image_path=None,
            spray_scheduled=False,
            spray_blocked_reason="test_mode",
            created_at=time.time(),
        )
        img = paths.image_path(det_id)
        img.write_bytes(b"x" * 100)
        with db._lock:
            with db._connect() as conn:
                conn.execute(
                    "UPDATE detections SET image_path = ? WHERE id = ?",
                    (str(img), det_id),
                )

    retention.enforce()
    assert db.count_detections_with_images() <= 2


def test_async_writer_persists(tmp_path: Path):
    root = tmp_path / "async"
    paths = StoragePaths(root)
    db = Database(paths.db_path)
    retention = RetentionManager(paths, db, max_archived_images=100, max_total_bytes=10**9)
    writer = AsyncStorageWriter(paths, db, retention)
    writer.start()

    det = Detection(
        class_id="clover",
        confidence=0.9,
        bbox=BBox(1, 1, 10, 10),
        frame_timestamp_ms=1.0,
    )
    event = SprayEvent(
        detection=det,
        spray_scheduled=False,
        spray_blocked_reason="test_mode",
        image_bytes=b"fakejpeg",
    )
    writer.enqueue(event)
    time.sleep(0.5)
    writer.stop()

    rows = db.list_detections(10)
    assert len(rows) == 1
    assert rows[0]["image_path"] is not None


def test_dir_size_bytes(tmp_path: Path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"12345")
    assert dir_size_bytes(tmp_path) == 5
