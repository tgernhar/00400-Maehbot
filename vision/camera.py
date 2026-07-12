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


def _encode_frame(img: Image.Image, *, rotate_180: bool = False, quality: int = 85) -> bytes:
    if rotate_180:
        img = img.rotate(180)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


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
    """CSI camera (IMX500, OV5647, ...) via picamera2/libcamera on Raspberry Pi."""

    def __init__(
        self,
        fps: int = 30,
        width: int = 640,
        height: int = 480,
        *,
        rotate_180: bool = False,
    ) -> None:
        self.fps = fps
        self.width = width
        self.height = height
        self.rotate_180 = rotate_180
        self._picam = None

    def start(self) -> None:
        from picamera2 import Picamera2

        self._picam = Picamera2()
        config = self._picam.create_preview_configuration(
            main={"size": (self.width, self.height), "format": "RGB888"}
        )
        self._picam.configure(config)
        self._picam.start()
        logger.info("Picamera2 started (%dx%d)", self.width, self.height)

    def read(self) -> Frame | None:
        if not self._picam:
            return None
        ts = time.monotonic() * 1000.0
        array = self._picam.capture_array()
        img = Image.fromarray(array)
        data = _encode_frame(img, rotate_180=self.rotate_180)
        return Frame(
            data=data,
            width=img.width,
            height=img.height,
            timestamp_ms=ts,
        )

    def stop(self) -> None:
        if self._picam:
            self._picam.stop()
            self._picam = None


class UsbCamera(Camera):
    """USB webcam via OpenCV V4L2 (fallback for nodes without CSI camera)."""

    def __init__(
        self,
        device: int = 0,
        fps: int = 30,
        width: int = 640,
        height: int = 480,
        *,
        rotate_180: bool = False,
    ) -> None:
        self.device = device
        self.fps = fps
        self.width = width
        self.height = height
        self.rotate_180 = rotate_180
        self._cap = None

    def start(self) -> None:
        import cv2

        self._cap = cv2.VideoCapture(self.device)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.fps)
        if not self._cap.isOpened():
            raise RuntimeError(f"USB-Kamera {self.device} konnte nicht geöffnet werden")
        logger.info("USB camera %d started (%dx%d)", self.device, self.width, self.height)

    def read(self) -> Frame | None:
        if not self._cap:
            return None
        import cv2

        ok, bgr = self._cap.read()
        if not ok:
            return None
        ts = time.monotonic() * 1000.0
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        data = _encode_frame(img, rotate_180=self.rotate_180)
        return Frame(data=data, width=img.width, height=img.height, timestamp_ms=ts)

    def stop(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None


def _picamera2_available() -> bool:
    try:
        from picamera2 import Picamera2  # noqa: F401

        return True
    except Exception:
        return False


def create_camera(config: dict, force_mock: bool = False) -> Camera:
    cam_cfg = config.get("camera", {})
    fps = int(cam_cfg.get("fps", 30))
    width = int(cam_cfg.get("width", 640))
    height = int(cam_cfg.get("height", 480))
    rotate_180 = bool(cam_cfg.get("rotate_180", False))
    source = str(cam_cfg.get("source", "auto")).lower()
    if force_mock or sys.platform != "linux" or source == "mock":
        return MockCamera(fps=fps, width=width, height=height)
    if source == "usb":
        return UsbCamera(
            device=int(cam_cfg.get("usb_device", 0)),
            fps=fps,
            width=width,
            height=height,
            rotate_180=rotate_180,
        )
    # source: picamera2 or auto
    if _picamera2_available():
        return Picamera2Camera(
            fps=fps, width=width, height=height, rotate_180=rotate_180
        )
    if source == "picamera2":
        logger.warning("Picamera2 nicht verfügbar, nutze MockCamera")
    return MockCamera(fps=fps, width=width, height=height)


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
