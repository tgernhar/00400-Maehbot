"""Training session management."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from storage.database import Database
from storage.paths import StoragePaths

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def _safe_stem(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    return cleaned.strip("_") or "anlernfahrt"


def register_video_session(
    paths: StoragePaths,
    db: Database,
    name: str,
    source_path: Path,
) -> dict:
    paths.ensure()
    dest = paths.videos / f"{int(time.time())}_{source_path.name}"
    shutil.copy2(source_path, dest)
    frame_count = _count_frames(dest)
    session_id = db.insert_training_session(
        name=name,
        video_path=str(dest),
        frame_count=frame_count,
        created_at=time.time(),
    )
    return {
        "id": session_id,
        "name": name,
        "video_path": str(dest),
        "frame_count": frame_count,
    }


def register_snapshot_session(
    paths: StoragePaths,
    db: Database,
    name: str,
    jpeg_bytes: bytes,
) -> dict:
    paths.ensure()
    stem = _safe_stem(name or "Foto")
    display_name = name.strip() or stem
    dest = paths.videos / f"{int(time.time())}_{stem}.jpg"
    dest.write_bytes(jpeg_bytes)
    session_id = db.insert_training_session(
        name=display_name,
        video_path=str(dest),
        frame_count=1,
        created_at=time.time(),
    )
    return {
        "id": session_id,
        "name": display_name,
        "video_path": str(dest),
        "frame_count": 1,
    }


def delete_training_session(
    paths: StoragePaths,
    db: Database,
    session_id: int,
) -> bool:
    session = db.get_training_session(session_id)
    if not session:
        return False
    video = Path(session["video_path"])
    if video.is_file():
        video.unlink(missing_ok=True)
    export_dir = paths.exports_yolo / f"session_{session_id}"
    if export_dir.is_dir():
        shutil.rmtree(export_dir, ignore_errors=True)
    return db.delete_training_session(session_id)


def _count_frames(video_path: Path) -> int:
    if video_path.suffix.lower() in _IMAGE_SUFFIXES:
        return 1 if video_path.is_file() else 0
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return max(count, 0)
    except Exception:
        return 0


def extract_frame_jpeg(video_path: str, frame_index: int) -> bytes | None:
    path = Path(video_path)
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        if frame_index != 0 or not path.is_file():
            return None
        return path.read_bytes()
    try:
        import cv2
        from PIL import Image
        import io

        cap = cv2.VideoCapture(video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, bgr = cap.read()
        cap.release()
        if not ok:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return None
