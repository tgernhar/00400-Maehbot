"""FastAPI application for Maehbot web UI and REST API."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from maehbot.config_loader import get_project_root, load_config, save_local_config
from storage.database import Database
from storage.paths import StoragePaths
from training.annotations import list_session_annotations, save_annotation
from training.export_yolo import export_session_to_yolo
from training.session import extract_frame_jpeg, register_video_session
from web.backend.auth import (
    DEFAULT_PASSWORD,
    DEFAULT_USER,
    create_access_token,
    hash_password,
    optional_auth,
    security,
    verify_password,
)
from web.backend.schemas import (
    AnnotationIn,
    AnnotationOut,
    BBoxSchema,
    ClassOut,
    DetectionOut,
    LoginIn,
    ModeConfigIn,
    ModeConfigOut,
    SprayConfigIn,
    SprayConfigOut,
    StatusOut,
    TokenOut,
    TrainingSessionOut,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maehbot.web")

app = FastAPI(title="Maehbot API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_state: dict[str, Any] = {}


def _resolve_storage_root(config: dict[str, Any]) -> str:
    root = config.get("storage", {}).get("root_path", "/var/lib/maehbot")
    if sys.platform != "linux" and str(root).startswith("/var"):
        return str(get_project_root() / "data" / "maehbot")
    return root


def get_app_state() -> dict[str, Any]:
    if not _state:
        config = load_config()
        root = _resolve_storage_root(config)
        paths = StoragePaths(root)
        paths.ensure()
        _state["config"] = config
        _state["paths"] = paths
        _state["db"] = Database(paths.db_path)
        _state["password_hash"] = hash_password(DEFAULT_PASSWORD)
    return _state


async def auth_dependency(
    state: dict[str, Any] = Depends(get_app_state),
    credentials: Any = Depends(security),
) -> str | None:
    return await optional_auth(state["config"], credentials)


def reload_config(state: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    root = _resolve_storage_root(config)
    state["config"] = config
    state["paths"] = StoragePaths(root)
    state["paths"].ensure()
    state["db"] = Database(state["paths"].db_path)
    return config


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login", response_model=TokenOut)
def login(body: LoginIn, state: dict[str, Any] = Depends(get_app_state)) -> TokenOut:
    config = state["config"]
    if not config.get("web", {}).get("auth_enabled", False):
        return TokenOut(access_token=create_access_token({"sub": "dev"}))
    if body.username != DEFAULT_USER or not verify_password(body.password, state["password_hash"]):
        raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten")
    return TokenOut(access_token=create_access_token({"sub": body.username}))


@app.get("/api/status", response_model=StatusOut)
def get_status(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> StatusOut:
    config = reload_config(state)
    status_path = state["paths"].status_path
    data: dict[str, Any] = {}
    if status_path.exists():
        data = json.loads(status_path.read_text(encoding="utf-8"))
    return StatusOut(
        test_mode=bool(data.get("test_mode", config.get("mode", {}).get("test_mode", True))),
        camera_healthy=bool(data.get("camera_healthy", False)),
        tank_empty=bool(data.get("tank_empty", False)),
        tank_full=bool(data.get("tank_full", False)),
        auth_enabled=bool(config.get("web", {}).get("auth_enabled", False)),
        latency=data.get("latency", {}),
    )


@app.get("/api/classes", response_model=list[ClassOut])
def list_classes(state: dict[str, Any] = Depends(get_app_state)) -> list[ClassOut]:
    config = state["config"]
    return [ClassOut(**c) for c in config.get("classes", [])]


@app.get("/api/detections", response_model=list[DetectionOut])
def list_detections(
    limit: int = 100,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> list[DetectionOut]:
    config = state["config"]
    ui_limit = int(config.get("storage", {}).get("ui_detection_limit", 100))
    limit = min(limit, ui_limit)
    rows = state["db"].list_detections(limit=limit)
    return [
        DetectionOut(
            id=r["id"],
            timestamp_ms=r["timestamp_ms"],
            class_id=r["class_id"],
            confidence=r["confidence"],
            bbox=BBoxSchema(**r["bbox"]),
            image_path=r["image_path"],
            spray_scheduled=r["spray_scheduled"],
            spray_blocked_reason=r["spray_blocked_reason"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@app.get("/api/detections/{detection_id}", response_model=DetectionOut)
def get_detection(
    detection_id: int,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> DetectionOut:
    row = state["db"].get_detection(detection_id)
    if not row:
        raise HTTPException(status_code=404, detail="Erkennung nicht gefunden")
    return DetectionOut(
        id=row["id"],
        timestamp_ms=row["timestamp_ms"],
        class_id=row["class_id"],
        confidence=row["confidence"],
        bbox=BBoxSchema(**row["bbox"]),
        image_path=row["image_path"],
        spray_scheduled=row["spray_scheduled"],
        spray_blocked_reason=row["spray_blocked_reason"],
        created_at=row["created_at"],
    )


@app.get("/api/detections/{detection_id}/image")
def get_detection_image(
    detection_id: int,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> Response:
    row = state["db"].get_detection(detection_id)
    if not row or not row["image_path"]:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    path = Path(row["image_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Bilddatei fehlt")
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/config/spray", response_model=SprayConfigOut)
def get_spray_config(state: dict[str, Any] = Depends(get_app_state)) -> SprayConfigOut:
    spray = state["config"].get("spray", {})
    return SprayConfigOut(
        delay_ms=float(spray.get("delay_ms", 0)),
        duration_ms=float(spray.get("duration_ms", 100)),
        camera_to_nozzle_mm=float(spray.get("camera_to_nozzle_mm", 20)),
        mower_speed_mm_s=float(spray.get("mower_speed_mm_s", 100)),
    )


@app.put("/api/config/spray", response_model=SprayConfigOut)
def put_spray_config(
    body: SprayConfigIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> SprayConfigOut:
    updates: dict[str, Any] = {"spray": {}}
    spray = state["config"].get("spray", {})
    if body.delay_ms is not None:
        updates["spray"]["delay_ms"] = body.delay_ms
        spray["delay_ms"] = body.delay_ms
    if body.duration_ms is not None:
        updates["spray"]["duration_ms"] = body.duration_ms
        spray["duration_ms"] = body.duration_ms
    if body.camera_to_nozzle_mm is not None:
        updates["spray"]["camera_to_nozzle_mm"] = body.camera_to_nozzle_mm
        spray["camera_to_nozzle_mm"] = body.camera_to_nozzle_mm
    if body.mower_speed_mm_s is not None:
        updates["spray"]["mower_speed_mm_s"] = body.mower_speed_mm_s
        spray["mower_speed_mm_s"] = body.mower_speed_mm_s
    save_local_config(updates)
    reload_config(state)
    return SprayConfigOut(
        delay_ms=float(spray.get("delay_ms", 0)),
        duration_ms=float(spray.get("duration_ms", 100)),
        camera_to_nozzle_mm=float(spray.get("camera_to_nozzle_mm", 20)),
        mower_speed_mm_s=float(spray.get("mower_speed_mm_s", 100)),
    )


@app.get("/api/config/mode", response_model=ModeConfigOut)
def get_mode_config(state: dict[str, Any] = Depends(get_app_state)) -> ModeConfigOut:
    mode = state["config"].get("mode", {})
    detection = state["config"].get("detection", {})
    return ModeConfigOut(
        test_mode=bool(mode.get("test_mode", True)),
        min_confidence=float(detection.get("min_confidence", 0.75)),
    )


@app.put("/api/config/mode", response_model=ModeConfigOut)
def put_mode_config(
    body: ModeConfigIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> ModeConfigOut:
    updates: dict[str, Any] = {}
    mode = state["config"].get("mode", {})
    detection = state["config"].get("detection", {})
    if body.test_mode is not None:
        updates["mode"] = {"test_mode": body.test_mode}
        mode["test_mode"] = body.test_mode
    if body.min_confidence is not None:
        updates.setdefault("detection", {})["min_confidence"] = body.min_confidence
        detection["min_confidence"] = body.min_confidence
    save_local_config(updates)
    reload_config(state)
    return ModeConfigOut(
        test_mode=bool(mode.get("test_mode", True)),
        min_confidence=float(detection.get("min_confidence", 0.75)),
    )


@app.get("/api/training/sessions", response_model=list[TrainingSessionOut])
def list_training_sessions(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> list[TrainingSessionOut]:
    rows = state["db"].list_training_sessions()
    return [TrainingSessionOut(**r) for r in rows]


@app.post("/api/training/sessions", response_model=TrainingSessionOut)
async def create_training_session(
    name: str = Form(...),
    file: UploadFile = File(...),
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> TrainingSessionOut:
    tmp = state["paths"].videos / f"upload_{int(time.time())}_{file.filename}"
    content = await file.read()
    tmp.write_bytes(content)
    result = register_video_session(state["paths"], state["db"], name, tmp)
    return TrainingSessionOut(**result)


@app.get("/api/training/sessions/{session_id}/frames/{frame_index}/image")
def get_training_frame(
    session_id: int,
    frame_index: int,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> Response:
    session = state["db"].get_training_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    jpeg = extract_frame_jpeg(session["video_path"], frame_index)
    if not jpeg:
        raise HTTPException(status_code=404, detail="Frame nicht gefunden")
    return Response(content=jpeg, media_type="image/jpeg")


@app.get("/api/training/sessions/{session_id}/frames")
def list_frame_info(
    session_id: int,
    state: dict[str, Any] = Depends(get_app_state),
) -> dict[str, int]:
    session = state["db"].get_training_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return {"frame_count": session["frame_count"]}


@app.post("/api/training/annotations", response_model=AnnotationOut)
def post_annotation(
    body: AnnotationIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> AnnotationOut:
    record = save_annotation(
        state["paths"],
        state["db"],
        body.session_id,
        body.frame_index,
        body.class_id,
        body.bbox.model_dump(),
    )
    return AnnotationOut(
        id=record["id"],
        session_id=record["session_id"],
        frame_index=record["frame_index"],
        class_id=record["class_id"],
        bbox=BBoxSchema(**record["bbox"]),
    )


@app.get("/api/training/sessions/{session_id}/annotations", response_model=list[AnnotationOut])
def get_session_annotations(
    session_id: int,
    state: dict[str, Any] = Depends(get_app_state),
) -> list[AnnotationOut]:
    rows = list_session_annotations(state["db"], session_id)
    return [
        AnnotationOut(
            id=r["id"],
            session_id=r["session_id"],
            frame_index=r["frame_index"],
            class_id=r["class_id"],
            bbox=BBoxSchema(**r["bbox"]),
        )
        for r in rows
    ]


@app.post("/api/training/sessions/{session_id}/export-yolo")
def export_yolo(
    session_id: int,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> dict[str, str]:
    class_ids = [c["id"] for c in state["config"].get("classes", [])]
    export_dir = export_session_to_yolo(state["paths"], state["db"], session_id, class_ids)
    return {"export_path": str(export_dir)}


# Static frontend
_frontend_dist = get_project_root() / "web" / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="static")


def run() -> None:
    config = load_config()
    web_cfg = config.get("web", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = int(web_cfg.get("port", 8080))
    uvicorn.run("web.backend.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
