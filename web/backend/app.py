"""FastAPI application for Maehbot web UI and REST API."""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from drive.command import queue_drive_command, read_drive_status
from spray.servo import SERVO_NAMES, servo_limits
from spray.servo_command import queue_servo_command, read_servo_status

try:
    from spray.servo import hold_until_from_config, sequence_steps_from_config
except ImportError:

    def hold_until_from_config(servo_cfg: dict[str, Any]) -> dict[str, int | None]:
        return {name: None for name in SERVO_NAMES}

    def sequence_steps_from_config(servo_cfg: dict[str, Any]) -> list[dict[str, Any]]:
        """Fallback when spray/servo.py on the device is not yet updated."""
        raw = servo_cfg.get("test_sequence")
        if raw:
            steps: list[dict[str, Any]] = []
            for item in raw:
                name = str(item.get("servo", ""))
                if name in SERVO_NAMES:
                    hold = item.get("hold_until_step")
                    hold_val = int(hold) if hold not in (None, "") else None
                    steps.append(
                        {
                            "servo": name,
                            "angle": float(item.get("angle", 0.0)),
                            "hold_until_step": hold_val,
                        }
                    )
            if steps:
                return steps
        angles = servo_cfg.get("test_angles", {}) or {}
        legacy = [
            ("tension", float(angles.get("tension", 0.0))),
            ("position", float(angles.get("position", 0.0))),
            ("trigger", float(angles.get("trigger", 0.0))),
            ("trigger", 0.0),
            ("tension", -45.0),
            ("position", 0.0),
            ("tension", 0.0),
            ("trigger", 0.0),
        ]
        return [{"servo": name, "angle": angle} for name, angle in legacy]
from maehbot.config_loader import get_project_root, load_config, save_local_config
from navigation.coverage import queue_coverage_command, read_coverage_status
from maehbot.node import NodeConfig
from storage.database import Database
from storage.paths import StoragePaths
from training.annotations import list_session_annotations, save_annotation
from training.export_yolo import export_session_to_yolo
from training.recording import queue_recording_command, read_recording_status
from training.session import delete_training_session, extract_frame_jpeg, register_video_session
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
    CoverageConfigIn,
    CoverageConfigOut,
    CoverageStartIn,
    CoverageStatusOut,
    DetectionOut,
    DriveCommandIn,
    DriveConfigIn,
    DriveConfigOut,
    DriveStatusOut,
    LoginIn,
    ModeConfigIn,
    ModeConfigOut,
    RecordingStartIn,
    RecordingStatusOut,
    ServoConfigOut,
    ServoLimitOut,
    ServoStepIn,
    ServoStepOut,
    ServoStepRunIn,
    ServoStatusOut,
    ServoTestIn,
    SprayConfigIn,
    SprayConfigOut,
    StatusOut,
    TokenOut,
    TrainingSessionOut,
    YoloExportOut,
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


def _load_node(config: dict[str, Any]) -> NodeConfig:
    try:
        return NodeConfig(config)
    except ValueError as exc:
        logger.warning("%s — nutze Rolle 'all'", exc)
        return NodeConfig({})


def get_app_state() -> dict[str, Any]:
    if not _state:
        config = load_config()
        root = _resolve_storage_root(config)
        paths = StoragePaths(root)
        paths.ensure()
        _state["config"] = config
        _state["paths"] = paths
        _state["db"] = Database(paths.db_path)
        _state["node"] = _load_node(config)
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
    state["node"] = _load_node(config)
    return config


# Endpoints owned by the vision node. On a drive-only node with a configured
# vision peer these are transparently forwarded, so the browser only ever
# talks to one web UI. Camera preview and drive endpoints stay local.
_VISION_PROXY_PREFIXES = (
    "/api/detections",
    "/api/classes",
    "/api/training",
    "/api/config/spray",
    "/api/config/mode",
    "/api/camera/preview/vision",
    "/api/servo",
    "/api/config/servo",
)


@app.middleware("http")
async def vision_peer_proxy(request: Request, call_next: Any) -> Any:
    node: NodeConfig = get_app_state()["node"]
    path = request.url.path
    if node and node.has_vision_peer and path.startswith(_VISION_PROXY_PREFIXES):
        url = f"{node.vision_url}{path}"
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length")
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                upstream = await client.request(
                    request.method,
                    url,
                    params=request.query_params,
                    headers=headers,
                    content=await request.body(),
                )
            return Response(
                content=upstream.content,
                status_code=upstream.status_code,
                media_type=upstream.headers.get("content-type"),
            )
        except httpx.HTTPError:
            logger.warning("Vision-Knoten nicht erreichbar: %s", url)
            return JSONResponse(
                status_code=502,
                content={"detail": "Vision-Knoten nicht erreichbar"},
            )
    return await call_next(request)


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
    node: NodeConfig = state["node"]
    status_path = state["paths"].status_path
    data: dict[str, Any] = {}
    if status_path.exists():
        data = json.loads(status_path.read_text(encoding="utf-8"))

    vision_connected = node.runs_vision
    if node.has_vision_peer:
        # Merge spray/tank/test-mode state from the vision node into one status
        try:
            r = httpx.get(f"{node.vision_url}/api/status", timeout=2.0)
            if r.status_code == 200:
                peer = r.json()
                data["test_mode"] = peer.get("test_mode", data.get("test_mode"))
                data["tank_empty"] = peer.get("tank_empty", False)
                data["tank_full"] = peer.get("tank_full", False)
                data.setdefault("latency", peer.get("latency", {}))
                vision_connected = True
        except httpx.HTTPError:
            vision_connected = False

    return StatusOut(
        test_mode=bool(data.get("test_mode", config.get("mode", {}).get("test_mode", True))),
        camera_healthy=bool(data.get("camera_healthy", False)),
        tank_empty=bool(data.get("tank_empty", False)),
        tank_full=bool(data.get("tank_full", False)),
        auth_enabled=bool(config.get("web", {}).get("auth_enabled", False)),
        latency=data.get("latency", {}),
        role=node.role,
        vision_connected=vision_connected,
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


@app.get("/api/camera/preview")
def get_camera_preview(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> Response:
    """Drive-node teleop camera (local preview.jpg)."""
    path = state["paths"].preview_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="Kameravorschau noch nicht verfügbar")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/camera/preview/vision")
def get_vision_camera_preview(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> Response:
    """Spray/vision-node camera (preview_vision.jpg on the vision Pi)."""
    paths = state["paths"]
    path = paths.vision_preview_path
    if not path.exists():
        path = paths.preview_path
    if not path.exists():
        # region agent log
        logger.warning(
            "vision preview missing: %s and %s",
            paths.vision_preview_path,
            paths.preview_path,
        )
        # endregion
        raise HTTPException(status_code=404, detail="Vision-Kameravorschau noch nicht verfügbar")
    # region agent log
    logger.debug("Serving vision preview from %s", path)
    # endregion
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


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


@app.get("/api/config/drive", response_model=DriveConfigOut)
def get_drive_config(state: dict[str, Any] = Depends(get_app_state)) -> DriveConfigOut:
    drive = state["config"].get("drive", {})
    return DriveConfigOut(
        enabled=bool(drive.get("enabled", True)),
        max_speed=float(drive.get("max_speed", 1.0)),
        watchdog_timeout_ms=float(drive.get("watchdog_timeout_ms", 1000)),
        invert_left=bool(drive.get("invert_left", False)),
        invert_right=bool(drive.get("invert_right", False)),
    )


@app.put("/api/config/drive", response_model=DriveConfigOut)
def put_drive_config(
    body: DriveConfigIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> DriveConfigOut:
    updates: dict[str, Any] = {"drive": {}}
    drive = state["config"].setdefault("drive", {})
    for field in ("enabled", "max_speed", "watchdog_timeout_ms", "invert_left", "invert_right"):
        value = getattr(body, field)
        if value is not None:
            updates["drive"][field] = value
            drive[field] = value
    save_local_config(updates)
    reload_config(state)
    drive = state["config"].get("drive", {})
    return DriveConfigOut(
        enabled=bool(drive.get("enabled", True)),
        max_speed=float(drive.get("max_speed", 1.0)),
        watchdog_timeout_ms=float(drive.get("watchdog_timeout_ms", 1000)),
        invert_left=bool(drive.get("invert_left", False)),
        invert_right=bool(drive.get("invert_right", False)),
    )


@app.get("/api/drive/status", response_model=DriveStatusOut)
def get_drive_status(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> DriveStatusOut:
    return DriveStatusOut(**read_drive_status(state["paths"]))


@app.post("/api/drive/command", response_model=DriveStatusOut)
def post_drive_command(
    body: DriveCommandIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> DriveStatusOut:
    queue_drive_command(state["paths"], body.left, body.right)
    return DriveStatusOut(**read_drive_status(state["paths"]))


@app.post("/api/drive/stop", response_model=DriveStatusOut)
def post_drive_stop(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> DriveStatusOut:
    queue_drive_command(state["paths"], 0.0, 0.0)
    return DriveStatusOut(**read_drive_status(state["paths"]))


def _servo_config_out(config: dict[str, Any]) -> ServoConfigOut:
    servo_cfg = config.get("servo", {})
    limits = servo_limits(servo_cfg)
    return ServoConfigOut(
        test_sequence=[
            ServoStepOut(
                servo=s["servo"],
                angle=s["angle"],
                hold_until_step=s.get("hold_until_step"),
            )
            for s in sequence_steps_from_config(servo_cfg)
        ],
        limits={
            name: ServoLimitOut(min_angle=lo, max_angle=hi)
            for name, (lo, hi) in limits.items()
        },
    )


def _validate_step_hold(
    step_index: int,
    hold_until: int | None,
    total_steps: int,
) -> int | None:
    if hold_until is None:
        return None
    if hold_until < step_index or hold_until > total_steps:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Halten-bis-Schritt in Schritt {step_index} muss zwischen "
                f"{step_index} und {total_steps} liegen"
            ),
        )
    return int(hold_until)


def _validate_servo_step(
    step: ServoStepIn,
    config: dict[str, Any],
    *,
    step_index: int | None = None,
    total_steps: int | None = None,
) -> dict[str, Any]:
    limits = servo_limits(config.get("servo", {}))
    name = step.servo
    if name not in SERVO_NAMES:
        raise HTTPException(
            status_code=422,
            detail=f"Unbekannter Servo '{name}'",
        )
    lo, hi = limits[name]
    if not lo <= step.angle <= hi:
        raise HTTPException(
            status_code=422,
            detail=f"Winkel für Servo '{name}' muss zwischen {lo:g}° und {hi:g}° liegen",
        )
    hold = step.hold_until_step
    if hold is not None and step_index is not None and total_steps is not None:
        hold = _validate_step_hold(step_index, hold, total_steps)
    return {
        "servo": name,
        "angle": float(step.angle),
        "hold_until_step": hold,
    }


@app.get("/api/servo/status", response_model=ServoStatusOut)
def get_servo_status(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> ServoStatusOut:
    return ServoStatusOut(**read_servo_status(state["paths"]))


@app.get("/api/config/servo", response_model=ServoConfigOut)
def get_servo_config(state: dict[str, Any] = Depends(get_app_state)) -> ServoConfigOut:
    return _servo_config_out(state["config"])


@app.post("/api/servo/test", response_model=ServoStatusOut)
def post_servo_test(
    body: ServoTestIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> ServoStatusOut:
    steps: list[dict[str, Any]] = []
    total = len(body.steps)
    for idx, step in enumerate(body.steps, start=1):
        steps.append(
            _validate_servo_step(
                step, state["config"], step_index=idx, total_steps=total
            )
        )
    current = read_servo_status(state["paths"])
    if current.get("state") not in (None, "idle"):
        raise HTTPException(status_code=409, detail="Servo-Sequenz läuft bereits")
    save_local_config({"servo": {"test_sequence": steps}})
    reload_config(state)
    queue_servo_command(state["paths"], "test", steps=steps)
    return ServoStatusOut(**read_servo_status(state["paths"]))


@app.post("/api/servo/step", response_model=ServoStatusOut)
def post_servo_step(
    body: ServoStepRunIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> ServoStatusOut:
    servo_cfg = state["config"].get("servo", {})
    total_steps = max(
        len(sequence_steps_from_config(servo_cfg)),
        body.step_index,
    )
    step = _validate_servo_step(
        body,
        state["config"],
        step_index=body.step_index,
        total_steps=total_steps,
    )
    current = read_servo_status(state["paths"])
    if current.get("state") not in (None, "idle"):
        raise HTTPException(status_code=409, detail="Servo-Sequenz läuft bereits")
    queue_servo_command(
        state["paths"],
        "step",
        steps=[step],
        step_index=body.step_index,
    )
    return ServoStatusOut(**read_servo_status(state["paths"]))


@app.post("/api/servo/home", response_model=ServoStatusOut)
def post_servo_home(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> ServoStatusOut:
    current = read_servo_status(state["paths"])
    if current.get("state") not in (None, "idle"):
        raise HTTPException(status_code=409, detail="Servo-Sequenz läuft bereits")
    queue_servo_command(state["paths"], "home")
    return ServoStatusOut(**read_servo_status(state["paths"]))


@app.get("/api/lidar/preview")
def get_lidar_preview(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> Response:
    path = state["paths"].lidar_preview_path
    if not path.exists():
        raise HTTPException(status_code=404, detail="LiDAR-Bild noch nicht verfügbar")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/api/coverage/status", response_model=CoverageStatusOut)
def get_coverage_status(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> CoverageStatusOut:
    return CoverageStatusOut(**read_coverage_status(state["paths"]))


@app.post("/api/coverage/start", response_model=CoverageStatusOut)
def post_coverage_start(
    body: CoverageStartIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> CoverageStatusOut:
    current = read_coverage_status(state["paths"])
    if current.get("state") in ("driving", "turning", "avoiding"):
        raise HTTPException(status_code=409, detail="Bereichsfahrt läuft bereits")
    queue_coverage_command(state["paths"], "start", body.length_m, body.width_m)
    return CoverageStatusOut(**read_coverage_status(state["paths"]))


@app.post("/api/coverage/stop", response_model=CoverageStatusOut)
def post_coverage_stop(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> CoverageStatusOut:
    queue_coverage_command(state["paths"], "stop")
    return CoverageStatusOut(**read_coverage_status(state["paths"]))


def _coverage_config_out(config: dict[str, Any]) -> CoverageConfigOut:
    cov = config.get("coverage", {})
    return CoverageConfigOut(
        drive_speed=float(cov.get("drive_speed", 0.5)),
        turn_speed=float(cov.get("turn_speed", 0.5)),
        speed_m_s=float(cov.get("speed_m_s", 0.10)),
        pivot_deg_s=float(cov.get("pivot_deg_s", 45.0)),
        first_leg_m=float(cov.get("first_leg_m", 0.20)),
        second_leg_m=float(cov.get("second_leg_m", 0.15)),
        track_spacing_m=float(cov.get("track_spacing_m", 0.15)),
        turn_direction=str(cov.get("turn_direction", "left")),
        obstacle_stop_m=float(cov.get("obstacle_stop_m", 0.30)),
        obstacle_sector_deg=float(cov.get("obstacle_sector_deg", 60.0)),
        obstacle_wait_s=float(cov.get("obstacle_wait_s", 3.0)),
        detour_m=float(cov.get("detour_m", 0.30)),
        max_avoid_attempts=int(cov.get("max_avoid_attempts", 3)),
    )


@app.get("/api/config/coverage", response_model=CoverageConfigOut)
def get_coverage_config(state: dict[str, Any] = Depends(get_app_state)) -> CoverageConfigOut:
    return _coverage_config_out(state["config"])


@app.put("/api/config/coverage", response_model=CoverageConfigOut)
def put_coverage_config(
    body: CoverageConfigIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> CoverageConfigOut:
    updates: dict[str, Any] = {"coverage": {}}
    for field in CoverageConfigIn.model_fields:
        value = getattr(body, field)
        if value is not None:
            updates["coverage"][field] = value
    save_local_config(updates)
    reload_config(state)
    return _coverage_config_out(state["config"])


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


@app.delete("/api/training/sessions/{session_id}")
def remove_training_session(
    session_id: int,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> dict[str, bool]:
    if not delete_training_session(state["paths"], state["db"], session_id):
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    return {"ok": True}


@app.get("/api/training/record/status", response_model=RecordingStatusOut)
def get_recording_status(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> RecordingStatusOut:
    data = read_recording_status(state["paths"])
    return RecordingStatusOut(**data)


@app.post("/api/training/record/start", response_model=RecordingStatusOut)
def start_recording(
    body: RecordingStartIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> RecordingStatusOut:
    current = read_recording_status(state["paths"])
    if current.get("state") in ("recording", "paused"):
        raise HTTPException(status_code=409, detail="Aufnahme läuft bereits")
    queue_recording_command(state["paths"], "start", body.name.strip())
    return RecordingStatusOut(**read_recording_status(state["paths"]))


@app.post("/api/training/record/pause", response_model=RecordingStatusOut)
def pause_recording(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> RecordingStatusOut:
    queue_recording_command(state["paths"], "pause")
    return RecordingStatusOut(**read_recording_status(state["paths"]))


@app.post("/api/training/record/resume", response_model=RecordingStatusOut)
def resume_recording(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> RecordingStatusOut:
    queue_recording_command(state["paths"], "resume")
    return RecordingStatusOut(**read_recording_status(state["paths"]))


@app.post("/api/training/record/stop", response_model=RecordingStatusOut)
def stop_recording(
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> RecordingStatusOut:
    queue_recording_command(state["paths"], "stop")
    return RecordingStatusOut(**read_recording_status(state["paths"]))


@app.post("/api/training/record/snapshot", response_model=RecordingStatusOut)
def snapshot_recording(
    body: RecordingStartIn,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> RecordingStatusOut:
    current = read_recording_status(state["paths"])
    if current.get("state") in ("recording", "paused"):
        raise HTTPException(
            status_code=409,
            detail="Während Videoaufnahme kein Einzelfoto möglich",
        )
    name = body.name.strip() or "Foto"
    queue_recording_command(state["paths"], "snapshot", name)
    return RecordingStatusOut(**read_recording_status(state["paths"]))


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


@app.post("/api/training/sessions/{session_id}/export-yolo", response_model=YoloExportOut)
def export_yolo(
    session_id: int,
    state: dict[str, Any] = Depends(get_app_state),
    _user: str | None = Depends(auth_dependency),
) -> YoloExportOut:
    session = state["db"].get_training_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session nicht gefunden")
    class_ids = [c["id"] for c in state["config"].get("classes", [])]
    try:
        result = export_session_to_yolo(state["paths"], state["db"], session_id, class_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("YOLO export failed for session %s", session_id)
        raise HTTPException(status_code=500, detail="YOLO-Export fehlgeschlagen") from exc
    return YoloExportOut(
        export_path=str(result.export_dir),
        image_count=result.image_count,
        label_count=result.label_count,
        annotation_count=result.annotation_count,
    )


# Static frontend (SPA: API routes above; assets + index.html fallback below)
_frontend_dist = get_project_root() / "web" / "frontend" / "dist"


def _register_frontend_routes() -> None:
    if not _frontend_dist.is_dir():
        logger.warning("Frontend dist missing at %s — build web/frontend first", _frontend_dist)
        return

    assets_dir = _frontend_dist / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    index_html = _frontend_dist / "index.html"

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str = "") -> FileResponse:
        if full_path.startswith("api") or full_path.startswith("assets/"):
            raise HTTPException(status_code=404)
        if full_path:
            candidate = (_frontend_dist / full_path).resolve()
            try:
                candidate.relative_to(_frontend_dist.resolve())
            except ValueError:
                raise HTTPException(status_code=404) from None
            if candidate.is_file():
                return FileResponse(candidate)
        if not index_html.is_file():
            raise HTTPException(status_code=404, detail="Frontend index missing")
        return FileResponse(index_html)


_register_frontend_routes()


def run() -> None:
    config = load_config()
    web_cfg = config.get("web", {})
    host = web_cfg.get("host", "0.0.0.0")
    port = int(web_cfg.get("port", 8080))
    uvicorn.run("web.backend.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
