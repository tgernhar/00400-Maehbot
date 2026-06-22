"""Learning-drive video recording (core) and IPC with web."""

from __future__ import annotations

import io
import json
import logging
import re
import time
from enum import Enum
from pathlib import Path
from typing import Any

from maehbot.types import Frame
from storage.database import Database
from storage.paths import StoragePaths

logger = logging.getLogger(__name__)


class RecordingError(Exception):
    pass


class RecordingState(str, Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    return cleaned.strip("_") or "anlernfahrt"


def read_recording_status(paths: StoragePaths) -> dict[str, Any]:
    path = paths.recording_status_path
    if not path.exists():
        return default_recording_status()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default_recording_status(), **data}
    except (json.JSONDecodeError, OSError):
        return default_recording_status()


def default_recording_status() -> dict[str, Any]:
    return {
        "state": RecordingState.IDLE.value,
        "session_name": "",
        "frame_count": 0,
        "session_id": None,
        "error": None,
    }


def write_recording_status(paths: StoragePaths, status: dict[str, Any]) -> None:
    paths.recording_status_path.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def queue_recording_command(paths: StoragePaths, action: str, name: str = "") -> None:
    payload: dict[str, Any] = {"action": action, "ts": time.time()}
    if name:
        payload["name"] = name
    paths.recording_command_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_recording_command(paths: StoragePaths) -> dict[str, Any] | None:
    path = paths.recording_command_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Invalid recording command file: %s", exc)
        path.unlink(missing_ok=True)
        return None


class LearningDriveRecorder:
    """Writes camera frames to MP4 for training sessions."""

    def __init__(self, paths: StoragePaths, db: Database, fps: int = 30) -> None:
        self.paths = paths
        self.db = db
        self.fps = max(fps, 1)
        self.state = RecordingState.IDLE
        self.session_name = ""
        self.frame_count = 0
        self.session_id: int | None = None
        self._writer: Any = None
        self._video_path: Path | None = None
        self._last_error: str | None = None

    def status_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "session_name": self.session_name,
            "frame_count": self.frame_count,
            "session_id": self.session_id,
            "error": self._last_error,
        }

    def publish_status(self) -> None:
        write_recording_status(self.paths, self.status_dict())

    def start(self, name: str) -> None:
        if self.state != RecordingState.IDLE:
            raise RecordingError("Aufnahme läuft bereits")
        self.paths.ensure()
        stem = _safe_stem(name or "anlernfahrt")
        self._video_path = self.paths.videos / f"{int(time.time())}_{stem}.mp4"
        self.session_name = name.strip() or stem
        self.frame_count = 0
        self.session_id = None
        self._writer = None
        self._last_error = None
        self.state = RecordingState.RECORDING
        logger.info("Learning drive recording started: %s", self._video_path)
        self.publish_status()

    def pause(self) -> None:
        if self.state == RecordingState.RECORDING:
            self.state = RecordingState.PAUSED
            logger.info("Learning drive recording paused")
            self.publish_status()
        elif self.state == RecordingState.IDLE:
            raise RecordingError("Keine laufende Aufnahme")

    def resume(self) -> None:
        if self.state == RecordingState.PAUSED:
            self.state = RecordingState.RECORDING
            logger.info("Learning drive recording resumed")
            self.publish_status()
        elif self.state == RecordingState.IDLE:
            raise RecordingError("Keine pausierte Aufnahme")

    def stop(self) -> int:
        if self.state == RecordingState.IDLE:
            raise RecordingError("Keine laufende Aufnahme")
        self._close_writer()
        if not self._video_path or not self._video_path.exists() or self.frame_count == 0:
            if self._video_path and self._video_path.exists():
                self._video_path.unlink(missing_ok=True)
            self._reset_idle()
            raise RecordingError("Keine Frames aufgenommen")

        session_id = self.db.insert_training_session(
            name=self.session_name,
            video_path=str(self._video_path),
            frame_count=self.frame_count,
            created_at=time.time(),
        )
        saved_frames = self.frame_count
        saved_name = self.session_name
        logger.info(
            "Learning drive saved session %s (%s frames)",
            session_id,
            saved_frames,
        )
        self._reset_idle()
        write_recording_status(
            self.paths,
            {
                "state": RecordingState.IDLE.value,
                "session_name": saved_name,
                "frame_count": saved_frames,
                "session_id": session_id,
                "error": None,
            },
        )
        return session_id

    def write_frame(self, frame: Frame) -> None:
        if self.state != RecordingState.RECORDING:
            return
        if not self._video_path:
            return
        try:
            import cv2
            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(frame.data))
            bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            if self._writer is None:
                h, w = bgr.shape[:2]
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                self._writer = cv2.VideoWriter(
                    str(self._video_path),
                    fourcc,
                    float(self.fps),
                    (w, h),
                )
                if not self._writer.isOpened():
                    raise RecordingError("VideoWriter konnte nicht geöffnet werden")
            self._writer.write(bgr)
            self.frame_count += 1
        except Exception as exc:
            logger.exception("Frame write failed during learning drive")
            self._last_error = str(exc)
            self._close_writer()
            if self._video_path and self._video_path.exists():
                self._video_path.unlink(missing_ok=True)
            self._reset_idle()
            self.publish_status()

    def handle_command(self, command: dict[str, Any]) -> None:
        action = str(command.get("action", "")).lower()
        try:
            if action == "start":
                self.start(str(command.get("name", "anlernfahrt")))
            elif action == "pause":
                self.pause()
            elif action == "resume":
                self.resume()
            elif action == "stop":
                self.stop()
            else:
                logger.warning("Unknown recording action: %s", action)
        except RecordingError as exc:
            self._last_error = str(exc)
            self.publish_status()
            logger.warning("Recording command failed: %s", exc)

    def poll_commands(self) -> None:
        command = consume_recording_command(self.paths)
        if command:
            self.handle_command(command)

    def shutdown(self) -> None:
        if self.state == RecordingState.IDLE:
            return
        try:
            if self.frame_count > 0:
                self.stop()
            else:
                self._close_writer()
                if self._video_path and self._video_path.exists():
                    self._video_path.unlink(missing_ok=True)
                self._reset_idle()
                self.publish_status()
        except RecordingError:
            self._close_writer()
            self._reset_idle()
            self.publish_status()

    def _close_writer(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def _reset_idle(self) -> None:
        self.state = RecordingState.IDLE
        self.session_name = ""
        self.frame_count = 0
        self._video_path = None
        self._writer = None
