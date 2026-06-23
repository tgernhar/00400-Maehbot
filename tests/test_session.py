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


def test_delete_training_session(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    db = Database(paths.db_path)
    jpeg = b"\xff\xd8\xff\xd9"
    result = register_snapshot_session(paths, db, "Löschtest", jpeg)
    session_id = result["id"]
    video_path = Path(result["video_path"])
    assert video_path.is_file()

    db.insert_annotation(session_id, 0, "clover", {"x": 1, "y": 2, "width": 3, "height": 4}, 1.0)
    assert db.list_annotations(session_id)

    from training.session import delete_training_session

    assert delete_training_session(paths, db, session_id) is True
    assert db.get_training_session(session_id) is None
    assert not video_path.exists()
    assert not db.list_annotations(session_id)
    assert delete_training_session(paths, db, session_id) is False
