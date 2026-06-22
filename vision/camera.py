"""Camera abstraction: IMX500 on Pi, mock on PC."""

from __future__ import annotations

import io
import logging
import sys
import time
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image, ImageDraw

from maehbot.types import Frame

logger = logging.getLogger(__name__)


class Camera(ABC):
    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def read(self) -> Frame | None: ...

    @abstractmethod
    def stop(self) -> None: ...


class MockCamera(Camera):
    """Generates synthetic frames with a movable blob for detection testing."""

    def __init__(self, fps: int = 30, width: int = 640, height: int = 480) -> None:
        self.fps = fps
        self.width = width
        self.height = height
        self._frame_idx = 0
        self._running = False

    def start(self) -> None:
        self._running = True

    def read(self) -> Frame | None:
        if not self._running:
            return None
        self._frame_idx += 1
        img = Image.new("RGB", (self.width, self.height), color=(34, 120, 34))
        draw = ImageDraw.Draw(img)
        x = (self._frame_idx * 5) % (self.width - 80)
        draw.rectangle([x, 200, x + 60, 260], fill=(128, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        ts = time.monotonic() * 1000.0
        return Frame(data=buf.getvalue(), width=self.width, height=self.height, timestamp_ms=ts)

    def stop(self) -> None:
        self._running = False


class Picamera2Camera(Camera):
    """IMX500 via picamera2 on Raspberry Pi."""

    def __init__(self, fps: int = 30) -> None:
        self.fps = fps
        self._picam = None

    def start(self) -> None:
        from picamera2 import Picamera2

        self._picam = Picamera2()
        config = self._picam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        )
        self._picam.configure(config)
        self._picam.start()
        logger.info("Picamera2 started")

    def read(self) -> Frame | None:
        if not self._picam:
            return None
        ts = time.monotonic() * 1000.0
        array = self._picam.capture_array()
        img = Image.fromarray(array)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return Frame(
            data=buf.getvalue(),
            width=img.width,
            height=img.height,
            timestamp_ms=ts,
        )

    def stop(self) -> None:
        if self._picam:
            self._picam.stop()
            self._picam = None


def _picamera2_available() -> bool:
    try:
        from picamera2 import Picamera2  # noqa: F401

        return True
    except Exception:
        return False


def create_camera(config: dict, force_mock: bool = False) -> Camera:
    fps = int(config.get("camera", {}).get("fps", 30))
    inference = config.get("detection", {}).get("inference_target", "imx500")
    if force_mock or sys.platform != "linux":
        return MockCamera(fps=fps)
    if inference == "imx500" or inference == "pi_cpu":
        if _picamera2_available():
            return Picamera2Camera(fps=fps)
        logger.warning("Picamera2 unavailable, using MockCamera")
        return MockCamera(fps=fps)
    return MockCamera(fps=fps)


class VideoFileCamera(Camera):
    """Read frames from a video file for training preview."""

    def __init__(self, video_path: Path, fps: int = 30) -> None:
        self.video_path = video_path
        self.fps = fps
        self._cap = None
        self._running = False

    def start(self) -> None:
        import cv2

        self._cap = cv2.VideoCapture(str(self.video_path))
        self._running = True

    def read(self) -> Frame | None:
        if not self._cap or not self._running:
            return None
        import cv2

        ok, bgr = self._cap.read()
        if not ok:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        ts = time.monotonic() * 1000.0
        return Frame(data=buf.getvalue(), width=img.width, height=img.height, timestamp_ms=ts)

    def stop(self) -> None:
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
