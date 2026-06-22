"""Retention policies: image ring buffer and total storage cap."""

from __future__ import annotations

import os
from pathlib import Path

from storage.database import Database
from storage.paths import StoragePaths


def dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = Path(root) / name
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


class RetentionManager:
    def __init__(
        self,
        paths: StoragePaths,
        db: Database,
        max_archived_images: int,
        max_total_bytes: int,
    ) -> None:
        self.paths = paths
        self.db = db
        self.max_archived_images = max_archived_images
        self.max_total_bytes = max_total_bytes

    def enforce(self) -> None:
        self._enforce_image_count()
        self._enforce_total_size()

    def _enforce_image_count(self) -> None:
        count = self.db.count_detections_with_images()
        excess = count - self.max_archived_images
        if excess <= 0:
            return
        for det_id, image_path in self.db.oldest_detection_ids_with_images(excess):
            self._remove_detection_image(det_id, image_path)

    def _enforce_total_size(self) -> None:
        while dir_size_bytes(self.paths.root) > self.max_total_bytes:
            oldest = self.db.oldest_detection_ids_with_images(1)
            if not oldest:
                break
            det_id, image_path = oldest[0]
            self._remove_detection_image(det_id, image_path)

    def _remove_detection_image(self, detection_id: int, image_path: str) -> None:
        path = Path(image_path)
        if path.exists():
            path.unlink()
        self.db.delete_detection(detection_id)
