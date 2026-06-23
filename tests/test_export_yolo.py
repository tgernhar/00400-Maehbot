"""Tests for YOLO export."""

from __future__ import annotations

from pathlib import Path

import pytest

from storage.database import Database
from storage.paths import StoragePaths
from training.export_yolo import export_session_to_yolo
from training.session import register_snapshot_session


def test_export_yolo_requires_annotations(tmp_path: Path):
    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    db = Database(paths.db_path)
    result = register_snapshot_session(paths, db, "Leer", b"\xff\xd8\xff\xd9")
    with pytest.raises(ValueError, match="Keine Annotationen"):
        export_session_to_yolo(paths, db, result["id"], ["clover", "grass"])


def test_export_yolo_writes_dataset(tmp_path: Path):
    from PIL import Image
    import io

    paths = StoragePaths(tmp_path / "data")
    paths.ensure()
    db = Database(paths.db_path)
    buf = io.BytesIO()
    Image.new("RGB", (640, 480), color=(40, 120, 40)).save(buf, format="JPEG")
    result = register_snapshot_session(paths, db, "Unkraut", buf.getvalue())
    session_id = result["id"]
    db.insert_annotation(
        session_id,
        0,
        "dandelion",
        {"x": 10, "y": 20, "width": 30, "height": 40},
        1.0,
    )
    export = export_session_to_yolo(
        paths,
        db,
        session_id,
        ["grass", "clover", "dandelion", "unknown_weed"],
    )
    assert export.image_count == 1
    assert export.label_count == 1
    assert export.annotation_count == 1
    assert (export.export_dir / "classes.txt").is_file()
    assert list((export.export_dir / "images" / "train").glob("*.jpg"))
    assert list((export.export_dir / "labels" / "train").glob("*.txt"))
