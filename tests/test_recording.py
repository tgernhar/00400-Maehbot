"""Tests for learning-drive recording IPC and state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from storage.database import Database
from storage.paths import StoragePaths
from training.recording import (
    LearningDriveRecorder,
    RecordingError,
    RecordingState,
    consume_recording_command,
    queue_recording_command,
    read_recording_status,
)


def test_queue_and_consume_command(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    queue_recording_command(paths, "start", "test_fahrt")
    cmd = consume_recording_command(paths)
    assert cmd is not None
    assert cmd["action"] == "start"
    assert cmd["name"] == "test_fahrt"
    assert consume_recording_command(paths) is None


def test_queue_snapshot_command(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    queue_recording_command(paths, "snapshot", "Unkraut_1")
    cmd = consume_recording_command(paths)
    assert cmd is not None
    assert cmd["action"] == "snapshot"
    assert cmd["name"] == "Unkraut_1"


def test_recorder_start_pause_resume_stop(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    db = Database(paths.db_path)
    recorder = LearningDriveRecorder(paths, db, fps=10)

    from maehbot.types import Frame

    recorder.start("Fahrt 1")
    assert recorder.state == RecordingState.RECORDING

    frame = Frame(data=b"fake", width=640, height=480, timestamp_ms=1.0)

    def fake_write(_frame: Frame) -> None:
        if recorder.state != RecordingState.RECORDING:
            return
        recorder.frame_count += 1

    recorder.write_frame = fake_write  # type: ignore[method-assign]

    recorder.write_frame(frame)
    recorder.write_frame(frame)
    assert recorder.frame_count == 2

    recorder.pause()
    assert recorder.state == RecordingState.PAUSED
    recorder.write_frame(frame)
    assert recorder.frame_count == 2

    recorder.resume()
    recorder.write_frame(frame)
    assert recorder.frame_count == 3

    # Inject minimal video file so stop succeeds
    assert recorder._video_path is not None
    recorder._video_path.write_bytes(b"\x00")
    session_id = recorder.stop()
    assert session_id > 0
    assert recorder.state == RecordingState.IDLE
    status = read_recording_status(paths)
    assert status["session_id"] == session_id
    assert status["frame_count"] == 3


def test_recorder_rejects_double_start(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    db = Database(paths.db_path)
    recorder = LearningDriveRecorder(paths, db)
    recorder.start("a")
    with pytest.raises(RecordingError):
        recorder.start("b")
