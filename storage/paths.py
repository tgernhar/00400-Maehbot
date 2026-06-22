"""Filesystem layout under storage root."""

from __future__ import annotations

from pathlib import Path


class StoragePaths:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.images = self.root / "images"
        self.videos = self.root / "videos"
        self.annotations = self.root / "annotations"
        self.exports_yolo = self.root / "exports" / "yolo"
        self.db_dir = self.root / "db"
        self.db_path = self.db_dir / "maehbot.sqlite"
        self.status_path = self.root / "status.json"
        self.preview_path = self.root / "preview.jpg"

    def ensure(self) -> None:
        for p in (
            self.images,
            self.videos,
            self.annotations,
            self.exports_yolo,
            self.db_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)

    def image_path(self, detection_id: int) -> Path:
        return self.images / f"{detection_id}.jpg"
