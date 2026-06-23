"""Export annotations to YOLO format."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.database import Database
from storage.paths import StoragePaths
from training.session import extract_frame_jpeg


class YoloExportResult:
    def __init__(
        self,
        export_dir: Path,
        image_count: int,
        label_count: int,
        annotation_count: int,
    ) -> None:
        self.export_dir = export_dir
        self.image_count = image_count
        self.label_count = label_count
        self.annotation_count = annotation_count


def export_session_to_yolo(
    paths: StoragePaths,
    db: Database,
    session_id: int,
    class_ids: list[str],
) -> YoloExportResult:
    session = db.get_training_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    annotations = db.list_annotations(session_id)
    if not annotations:
        raise ValueError("Keine Annotationen — bitte zuerst Unkraut markieren")

    class_map = {cid: idx for idx, cid in enumerate(class_ids)}
    export_dir = paths.exports_yolo / f"session_{session_id}"
    images_train = export_dir / "images" / "train"
    labels_train = export_dir / "labels" / "train"
    images_train.mkdir(parents=True, exist_ok=True)
    labels_train.mkdir(parents=True, exist_ok=True)

    by_frame: dict[int, list[dict[str, Any]]] = {}
    for ann in annotations:
        by_frame.setdefault(ann["frame_index"], []).append(ann)

    video_path = session["video_path"]
    image_count = 0
    label_count = 0
    for frame_index, anns in by_frame.items():
        jpeg = extract_frame_jpeg(video_path, frame_index)
        if not jpeg:
            continue
        stem = f"frame_{frame_index}"
        img_path = images_train / f"{stem}.jpg"
        img_path.write_bytes(jpeg)

        lines: list[str] = []
        for ann in anns:
            cid = ann["class_id"]
            if cid not in class_map:
                continue
            bbox = ann["bbox"]
            x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
            from PIL import Image
            import io

            im = Image.open(io.BytesIO(jpeg))
            iw, ih = im.size
            cx = (x + w / 2) / iw
            cy = (y + h / 2) / ih
            nw = w / iw
            nh = h / ih
            lines.append(f"{class_map[cid]} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")

        if not lines:
            img_path.unlink(missing_ok=True)
            continue

        label_path = labels_train / f"{stem}.txt"
        label_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        image_count += 1
        label_count += 1

    if image_count == 0:
        raise ValueError(
            "Keine Bilder exportiert — Frames konnten nicht gelesen werden "
            "oder Klassen passen nicht zur Konfiguration"
        )

    classes_file = export_dir / "classes.txt"
    classes_file.write_text("\n".join(class_ids) + "\n", encoding="utf-8")
    return YoloExportResult(
        export_dir=export_dir,
        image_count=image_count,
        label_count=label_count,
        annotation_count=len(annotations),
    )


def export_all_sessions(
    paths: StoragePaths,
    db: Database,
    class_ids: list[str],
) -> list[Path]:
    results = []
    for session in db.list_training_sessions():
        try:
            result = export_session_to_yolo(paths, db, session["id"], class_ids)
            results.append(result.export_dir)
        except Exception:
            continue
    return results
