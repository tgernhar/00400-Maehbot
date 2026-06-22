"""Tests for training session helpers."""

from __future__ import annotations

from pathlib import Path

from storage.database import Database
from storage.paths import StoragePaths
from training.session import extract_frame_jpeg, register_snapshot_session


def test_register_snapshot_session(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    db = Database(paths.db_path)
    jpeg = b"\xff\xd8\xff\xd9"
    result = register_snapshot_session(paths, db, "Testfoto", jpeg)
    assert result["frame_count"] == 1
    assert result["name"] == "Testfoto"
    assert Path(result["video_path"]).is_file()
    assert extract_frame_jpeg(result["video_path"], 0) == jpeg
    assert extract_frame_jpeg(result["video_path"], 1) is None
