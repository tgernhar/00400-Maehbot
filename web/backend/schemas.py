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
