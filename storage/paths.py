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
        self.recording_status_path = self.root / "recording_status.json"
        self.recording_command_path = self.root / "recording_command.json"
        self.drive_status_path = self.root / "drive_status.json"
        self.drive_command_path = self.root / "drive_command.json"
        self.coverage_status_path = self.root / "coverage_status.json"
        self.coverage_command_path = self.root / "coverage_command.json"
        self.servo_status_path = self.root / "servo_status.json"
        self.servo_command_path = self.root / "servo_command.json"
        self.lidar_preview_path = self.root / "lidar.jpg"

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
