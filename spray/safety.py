"""Safety guards before spray is allowed."""

from __future__ import annotations

from typing import Any

from maehbot.config_loader import is_class_sprayable
from maehbot.types import Detection, SystemStatus


def evaluate_spray_allowed(
    detection: Detection,
    config: dict[str, Any],
    status: SystemStatus,
) -> tuple[bool, str | None]:
    if status.test_mode:
        return False, "test_mode"

    if not status.camera_healthy:
        return False, "camera_unhealthy"

    if not detection.bbox.is_valid():
        return False, "invalid_bbox"

    if detection.image_width > 0 and detection.image_height > 0:
        if (
            detection.bbox.x + detection.bbox.width > detection.image_width
            or detection.bbox.y + detection.bbox.height > detection.image_height
        ):
            return False, "bbox_out_of_frame"

    min_conf = float(config.get("detection", {}).get("min_confidence", 0.75))
    if detection.confidence < min_conf:
        return False, "low_confidence"

    if not is_class_sprayable(config, detection.class_id):
        return False, "class_not_sprayable"

    if not tank_ok_from_gpio(status.tank_empty, status.tank_full):
        return False, "tank_empty"

    return True, None


def tank_ok_from_gpio(tank_empty: bool, tank_full: bool) -> bool:
    if tank_empty:
        return False
    if tank_full and tank_empty:
        return False
    return True
