"""Background writer: queue spray events, never block hot path."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

from maehbot.types import SprayEvent
from storage.database import Database
from storage.paths import StoragePaths
from storage.retention import RetentionManager

logger = logging.getLogger(__name__)


class AsyncStorageWriter:
    def __init__(
        self,
        paths: StoragePaths,
        db: Database,
        retention: RetentionManager,
        max_queue: int = 256,
    ) -> None:
        self.paths = paths
        self.db = db
        self.retention = retention
        self._queue: queue.Queue[SprayEvent | None] = queue.Queue(maxsize=max_queue)
        self._thread = threading.Thread(target=self._run, name="async-storage", daemon=True)
        self._running = False

    def start(self) -> None:
        self.paths.ensure()
        self._running = True
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._thread.join(timeout=5)

    def enqueue(self, event: SprayEvent) -> bool:
        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            logger.warning("Storage queue full, dropping detection event")
            return False

    def _run(self) -> None:
        while self._running:
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
            try:
                self._persist(item)
            except Exception:
                logger.exception("Failed to persist detection")

    def _persist(self, event: SprayEvent) -> None:
        det = event.detection
        created_at = time.time()
        image_path: str | None = None

        det_id = self.db.insert_detection(
            timestamp_ms=det.frame_timestamp_ms,
            class_id=det.class_id,
            confidence=det.confidence,
            bbox=det.bbox.to_dict(),
            image_path=None,
            spray_scheduled=event.spray_scheduled,
            spray_blocked_reason=event.spray_blocked_reason,
            created_at=created_at,
        )

        if event.image_bytes:
            img_path = self.paths.image_path(det_id)
            img_path.write_bytes(event.image_bytes)
            image_path = str(img_path)
            with self.db._lock:
                with self.db._connect() as conn:
                    conn.execute(
                        "UPDATE detections SET image_path = ? WHERE id = ?",
                        (image_path, det_id),
                    )

        self.retention.enforce()

    def write_status(self, status: dict[str, Any]) -> None:
        import json

        self.paths.status_path.write_text(json.dumps(status), encoding="utf-8")
