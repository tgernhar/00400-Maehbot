"""Vision pipeline with latency logging."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable

from maehbot.types import Detection, Frame
from vision.camera import Camera
from vision.detector import Detector

logger = logging.getLogger(__name__)


@dataclass
class LatencyStats:
    frame_to_detect_ms: list[float] = field(default_factory=list)
    detect_to_callback_ms: list[float] = field(default_factory=list)

    def record_frame_to_detect(self, ms: float) -> None:
        self.frame_to_detect_ms.append(ms)
        if len(self.frame_to_detect_ms) > 500:
            self.frame_to_detect_ms.pop(0)

    def record_detect_to_callback(self, ms: float) -> None:
        self.detect_to_callback_ms.append(ms)
        if len(self.detect_to_callback_ms) > 500:
            self.detect_to_callback_ms.pop(0)

    def summary(self) -> dict[str, float]:
        def avg(vals: list[float]) -> float:
            return sum(vals) / len(vals) if vals else 0.0

        return {
            "avg_frame_to_detect_ms": avg(self.frame_to_detect_ms),
            "avg_detect_to_callback_ms": avg(self.detect_to_callback_ms),
        }


class VisionPipeline:
    def __init__(
        self,
        camera: Camera,
        detector: Detector,
        on_detections: Callable[[Frame, list[Detection]], None],
    ) -> None:
        self.camera = camera
        self.detector = detector
        self.on_detections = on_detections
        self.latency = LatencyStats()
        self._running = False

    def start(self) -> None:
        self.camera.start()
        self._running = True

    def stop(self) -> None:
        self._running = False
        self.camera.stop()

    def process_one(self) -> bool:
        if not self._running:
            return False
        t0 = time.monotonic()
        frame = self.camera.read()
        if frame is None:
            return False
        t1 = time.monotonic()
        detections = self.detector.detect(frame)
        t2 = time.monotonic()
        self.latency.record_frame_to_detect((t1 - t0) * 1000.0)
        if detections:
            self.on_detections(frame, detections)
            self.latency.record_detect_to_callback((time.monotonic() - t2) * 1000.0)
        return True

    def run_loop(self, target_fps: int = 30) -> None:
        interval = 1.0 / max(target_fps, 1)
        while self._running:
            start = time.monotonic()
            self.process_one()
            elapsed = time.monotonic() - start
            if elapsed < interval:
                time.sleep(interval - elapsed)
