"""Shared data types for Maehbot."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BBox:
    x: float
    y: float
    width: float
    height: float

    def is_valid(self) -> bool:
        return self.width > 0 and self.height > 0 and self.x >= 0 and self.y >= 0

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BBox:
        return cls(
            x=float(data["x"]),
            y=float(data["y"]),
            width=float(data["width"]),
            height=float(data["height"]),
        )


@dataclass
class Detection:
    class_id: str
    confidence: float
    bbox: BBox
    frame_timestamp_ms: float
    image_width: int = 0
    image_height: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "confidence": self.confidence,
            "bbox": self.bbox.to_dict(),
            "frame_timestamp_ms": self.frame_timestamp_ms,
            "image_width": self.image_width,
            "image_height": self.image_height,
        }


@dataclass
class Frame:
    data: bytes
    width: int
    height: int
    timestamp_ms: float
    format: str = "jpeg"


@dataclass
class SprayEvent:
    detection: Detection
    spray_scheduled: bool
    spray_blocked_reason: str | None = None
    fire_at_ms: float | None = None
    image_bytes: bytes | None = None


@dataclass
class SystemStatus:
    test_mode: bool = True
    camera_healthy: bool = False
    tank_empty: bool = False
    tank_full: bool = False
    last_frame_ms: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)
