"""Training session management."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from storage.database import Database
from storage.paths import StoragePaths


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


def _count_frames(video_path: Path) -> int:
    try:
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return max(count, 0)
    except Exception:
        return 0


def extract_frame_jpeg(video_path: str, frame_index: int) -> bytes | None:
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
