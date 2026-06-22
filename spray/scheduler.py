"""Spray timing: travel delay from camera to nozzle."""

from __future__ import annotations


def compute_travel_ms(camera_to_nozzle_mm: float, mower_speed_mm_s: float) -> float:
    if mower_speed_mm_s <= 0:
        return 0.0
    return (camera_to_nozzle_mm / mower_speed_mm_s) * 1000.0


def compute_fire_at_ms(
    detection_timestamp_ms: float,
    spray_delay_ms: float,
    camera_to_nozzle_mm: float,
    mower_speed_mm_s: float,
) -> float:
    travel_ms = compute_travel_ms(camera_to_nozzle_mm, mower_speed_mm_s)
    return detection_timestamp_ms + spray_delay_ms + travel_ms


class SprayScheduler:
    def __init__(
        self,
        spray_delay_ms: float,
        camera_to_nozzle_mm: float,
        mower_speed_mm_s: float,
    ) -> None:
        self.spray_delay_ms = spray_delay_ms
        self.camera_to_nozzle_mm = camera_to_nozzle_mm
        self.mower_speed_mm_s = mower_speed_mm_s

    def update(
        self,
        spray_delay_ms: float | None = None,
        camera_to_nozzle_mm: float | None = None,
        mower_speed_mm_s: float | None = None,
    ) -> None:
        if spray_delay_ms is not None:
            self.spray_delay_ms = spray_delay_ms
        if camera_to_nozzle_mm is not None:
            self.camera_to_nozzle_mm = camera_to_nozzle_mm
        if mower_speed_mm_s is not None:
            self.mower_speed_mm_s = mower_speed_mm_s

    def schedule_fire_at(self, detection_timestamp_ms: float) -> float:
        return compute_fire_at_ms(
            detection_timestamp_ms,
            self.spray_delay_ms,
            self.camera_to_nozzle_mm,
            self.mower_speed_mm_s,
        )
