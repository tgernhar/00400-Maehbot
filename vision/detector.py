"""Detection abstraction: mock, IMX500, CPU fallback."""

from __future__ import annotations

import logging
import sys
from abc import ABC, abstractmethod

from maehbot.types import BBox, Detection, Frame

logger = logging.getLogger(__name__)


class Detector(ABC):
    @abstractmethod
    def detect(self, frame: Frame) -> list[Detection]: ...


class MockDetector(Detector):
    """Detects purple blob region in mock frames as clover."""

    def detect(self, frame: Frame) -> list[Detection]:
        from PIL import Image

        img = Image.open(__import__("io").BytesIO(frame.data))
        pixels = img.load()
        w, h = img.size
        min_x, min_y = w, h
        max_x, max_y = 0, 0
        found = False
        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y][:3]
                if r > 100 and b > 100 and g < 80:
                    found = True
                    min_x = min(min_x, x)
                    min_y = min(min_y, y)
                    max_x = max(max_x, x)
                    max_y = max(max_y, y)
        if not found:
            return []
        bbox = BBox(
            x=float(min_x),
            y=float(min_y),
            width=float(max_x - min_x + 1),
            height=float(max_y - min_y + 1),
        )
        return [
            Detection(
                class_id="clover",
                confidence=0.92,
                bbox=bbox,
                frame_timestamp_ms=frame.timestamp_ms,
                image_width=w,
                image_height=h,
            )
        ]


class Imx500Detector(Detector):
    """Placeholder for Sony IMX500 on-sensor inference integration."""

    def detect(self, frame: Frame) -> list[Detection]:
        logger.debug("IMX500 detector: using mock fallback until model deployed")
        return MockDetector().detect(frame)


class CpuFallbackDetector(Detector):
    """CPU fallback — mock-based until TFLite/ONNX model is added."""

    def detect(self, frame: Frame) -> list[Detection]:
        return MockDetector().detect(frame)


def create_detector(config: dict, force_mock: bool = False) -> Detector:
    if force_mock or sys.platform != "linux":
        return MockDetector()
    target = config.get("detection", {}).get("inference_target", "imx500")
    if target == "imx500":
        return Imx500Detector()
    if target == "pi_cpu":
        return CpuFallbackDetector()
    return MockDetector()
