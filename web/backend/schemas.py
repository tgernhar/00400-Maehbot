"""Pydantic schemas for Maehbot API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BBoxSchema(BaseModel):
    x: float
    y: float
    width: float
    height: float


class DetectionOut(BaseModel):
    id: int
    timestamp_ms: float
    class_id: str
    confidence: float
    bbox: BBoxSchema
    image_path: str | None = None
    spray_scheduled: bool
    spray_blocked_reason: str | None = None
    created_at: float


class SprayConfigIn(BaseModel):
    delay_ms: float | None = None
    duration_ms: float | None = None
    camera_to_nozzle_mm: float | None = None
    mower_speed_mm_s: float | None = None


class SprayConfigOut(BaseModel):
    delay_ms: float
    duration_ms: float
    camera_to_nozzle_mm: float
    mower_speed_mm_s: float


class DriveCommandIn(BaseModel):
    left: float = Field(ge=-1.0, le=1.0)
    right: float = Field(ge=-1.0, le=1.0)


class DriveStatusOut(BaseModel):
    left: float = 0.0
    right: float = 0.0
    enabled: bool = True
    moving: bool = False
    max_speed: float = 1.0
    error: str | None = None


class DriveConfigIn(BaseModel):
    enabled: bool | None = None
    max_speed: float | None = Field(default=None, ge=0.0, le=1.0)
    watchdog_timeout_ms: float | None = Field(default=None, ge=100.0)
    invert_left: bool | None = None
    invert_right: bool | None = None


class DriveConfigOut(BaseModel):
    enabled: bool
    max_speed: float
    watchdog_timeout_ms: float
    invert_left: bool
    invert_right: bool


class ServoStepIn(BaseModel):
    servo: str
    angle: float


class ServoTestIn(BaseModel):
    steps: list[ServoStepIn] = Field(min_length=1)


class ServoStatusOut(BaseModel):
    state: str = "idle"
    angles: dict[str, float | None] = Field(default_factory=dict)
    error: str | None = None
    updated_at: float = 0.0


class ServoLimitOut(BaseModel):
    min_angle: float
    max_angle: float


class ServoStepOut(BaseModel):
    servo: str
    angle: float


class ServoConfigOut(BaseModel):
    test_sequence: list[ServoStepOut]
    limits: dict[str, ServoLimitOut]


class CoverageStartIn(BaseModel):
    length_m: float = Field(default=1.0, gt=0.0, le=100.0)
    width_m: float = Field(default=1.0, gt=0.0, le=100.0)


class CoverageStatusOut(BaseModel):
    state: str = "idle"
    length_m: float = 0.0
    width_m: float = 0.0
    leg_index: int = 0
    leg_count: int = 0
    progress_percent: float = 0.0
    lidar_connected: bool = False
    error: str | None = None


class CoverageConfigIn(BaseModel):
    drive_speed: float | None = Field(default=None, ge=0.0, le=1.0)
    turn_speed: float | None = Field(default=None, ge=0.0, le=1.0)
    speed_m_s: float | None = Field(default=None, gt=0.0)
    pivot_deg_s: float | None = Field(default=None, gt=0.0)
    first_leg_m: float | None = Field(default=None, gt=0.0)
    second_leg_m: float | None = Field(default=None, gt=0.0)
    track_spacing_m: float | None = Field(default=None, gt=0.0)
    turn_direction: str | None = Field(default=None, pattern="^(left|right)$")
    obstacle_stop_m: float | None = Field(default=None, ge=0.0)
    obstacle_sector_deg: float | None = Field(default=None, ge=0.0, le=360.0)
    obstacle_wait_s: float | None = Field(default=None, ge=0.0)
    detour_m: float | None = Field(default=None, gt=0.0)
    max_avoid_attempts: int | None = Field(default=None, ge=0)


class CoverageConfigOut(BaseModel):
    drive_speed: float
    turn_speed: float
    speed_m_s: float
    pivot_deg_s: float
    first_leg_m: float
    second_leg_m: float
    track_spacing_m: float
    turn_direction: str
    obstacle_stop_m: float
    obstacle_sector_deg: float
    obstacle_wait_s: float
    detour_m: float
    max_avoid_attempts: int


class ModeConfigIn(BaseModel):
    test_mode: bool | None = None
    min_confidence: float | None = None


class ModeConfigOut(BaseModel):
    test_mode: bool
    min_confidence: float


class StatusOut(BaseModel):
    test_mode: bool
    camera_healthy: bool
    tank_empty: bool
    tank_full: bool
    auth_enabled: bool
    latency: dict[str, float] = Field(default_factory=dict)
    role: str = "all"
    vision_connected: bool = True


class TrainingSessionOut(BaseModel):
    id: int
    name: str
    video_path: str
    frame_count: int
    created_at: float


class RecordingStartIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class RecordingStatusOut(BaseModel):
    state: str
    session_name: str = ""
    frame_count: int = 0
    session_id: int | None = None
    error: str | None = None


class AnnotationIn(BaseModel):
    session_id: int
    frame_index: int
    class_id: str
    bbox: BBoxSchema


class AnnotationOut(BaseModel):
    id: int
    session_id: int
    frame_index: int
    class_id: str
    bbox: BBoxSchema


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ClassOut(BaseModel):
    id: str
    name: str
    sprayable: bool


class YoloExportOut(BaseModel):
    export_path: str
    image_count: int
    label_count: int
    annotation_count: int
