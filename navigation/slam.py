"""LiDAR SLAM mapping via BreezySLAM (tinySLAM/CoreSLAM).

``SlamMapper`` runs a background thread that feeds the latest 360-degree
LiDAR scan plus a dead-reckoning odometry estimate (derived from the
commanded track speeds and the time-based calibration values) into
``RMHC_SLAM``. It publishes:

- the current pose ``(x_m, y_m, theta_deg)`` in the map frame,
- the occupancy grid for the path planner,
- ``map.png`` (grayscale, 0 = obstacle, 255 = free, ~127 = unknown) for
  the web UI, throttled to ~1 Hz.

BreezySLAM is a C extension installed from GitHub (see
``docs/mapping-navigation.md``). The import is guarded so the core keeps
running without it — mapping then reports ``available = False``.

Frame conventions:
- Map frame: x right, y down when the PNG is displayed row 0 on top;
  theta in degrees, positive = left turn (counter-clockwise in x/y math).
- Sensor scan bins are clockwise with 0 = front; ``scan_to_slam``
  reorders them into the counter-clockwise order BreezySLAM expects.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Any

from navigation.lidar import LidarReader

logger = logging.getLogger(__name__)

try:  # BreezySLAM is optional (built from source on the Pi)
    from breezyslam.algorithms import RMHC_SLAM
    from breezyslam.sensors import Laser

    BREEZYSLAM_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on environment
    RMHC_SLAM = None  # type: ignore[assignment]
    Laser = None  # type: ignore[assignment]
    BREEZYSLAM_AVAILABLE = False

# LDRobot D500: 360 one-degree bins, ~10 Hz scan rate, 12 m max range
_SCAN_SIZE = 360
_SCAN_RATE_HZ = 10.0
_DETECTION_ANGLE_DEG = 360.0
_NO_DETECTION_MM = 12000.0


def scan_to_slam(distances_m: list[float]) -> list[int]:
    """Reorder sensor bins (clockwise, 0 = front) for BreezySLAM.

    BreezySLAM expects the scan counter-clockwise from -180 to +180 degrees
    relative to the robot front. Sensor bin for CCW angle ``a`` is
    ``(-a) % 360``; with ``a = -180 + i`` this gives ``(180 - i) % 360``.
    Distances are converted to integer millimeters, 0 = no echo.
    """
    return [int(distances_m[(180 - i) % 360] * 1000.0) for i in range(_SCAN_SIZE)]


def motion_deltas(
    left: float,
    right: float,
    dt_s: float,
    drive_speed: float,
    turn_speed: float,
    speed_m_s: float,
    pivot_deg_s: float,
) -> tuple[float, float]:
    """Dead-reckoning deltas ``(dxy_mm, dtheta_deg)`` from track speeds.

    Calibration: at normalized track speed ``drive_speed`` the robot moves
    ``speed_m_s``; at differential ``turn_speed`` it pivots ``pivot_deg_s``.
    Linear interpolation in between. Positive dtheta = left turn (CCW).
    """
    linear = (left + right) / 2.0
    angular = (right - left) / 2.0
    v_m_s = speed_m_s * linear / drive_speed if drive_speed > 0 else 0.0
    omega_deg_s = pivot_deg_s * angular / turn_speed if turn_speed > 0 else 0.0
    return (v_m_s * dt_s * 1000.0, omega_deg_s * dt_s)


class SlamMapper:
    """Background SLAM thread fed by the LiDAR reader and drive odometry."""

    def __init__(
        self,
        lidar: LidarReader,
        config: dict[str, Any],
        map_image_path: Path,
        map_meta_path: Path,
        map_saved_path: Path,
    ) -> None:
        self.lidar = lidar
        self.map_image_path = map_image_path
        self.map_meta_path = map_meta_path
        self.map_saved_path = map_saved_path

        mapping = config.get("mapping", {})
        self.map_size_pixels = int(mapping.get("map_size_pixels", 800))
        self.map_size_meters = float(mapping.get("map_size_meters", 20.0))
        self.map_quality = int(mapping.get("map_quality", 50))
        self.hole_width_mm = float(mapping.get("hole_width_mm", 300))
        self.update_interval_s = 1.0 / max(0.5, float(mapping.get("update_rate_hz", 5)))
        self.localize_only = bool(mapping.get("localize_only", False))

        self._slam: Any = None
        self._mapbytes = bytearray(self.map_size_pixels * self.map_size_pixels)
        self._pose: tuple[float, float, float] | None = None
        self._lock = threading.Lock()
        self._odo_lock = threading.Lock()
        self._odo_dxy_mm = 0.0
        self._odo_dtheta_deg = 0.0
        self._odo_dt_s = 0.0
        self._last_scan_ts = 0.0
        self._last_image_write = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self.update_config(config)

    @property
    def available(self) -> bool:
        return BREEZYSLAM_AVAILABLE

    def update_config(self, config: dict[str, Any]) -> None:
        """Refresh odometry calibration (shared with the coverage config)."""
        cov = config.get("coverage", {})
        self._drive_speed = float(cov.get("drive_speed", 0.5))
        self._turn_speed = float(cov.get("turn_speed", 0.5))
        self._speed_m_s = float(cov.get("speed_m_s", 0.10))
        self._pivot_deg_s = float(cov.get("pivot_deg_s", 45.0))
        mapping = config.get("mapping", {})
        self.localize_only = bool(mapping.get("localize_only", False))

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        if not BREEZYSLAM_AVAILABLE:
            logger.warning(
                "BreezySLAM nicht installiert — Kartierung deaktiviert "
                "(siehe docs/mapping-navigation.md)"
            )
            return
        laser = Laser(_SCAN_SIZE, _SCAN_RATE_HZ, _DETECTION_ANGLE_DEG, _NO_DETECTION_MM)
        self._slam = RMHC_SLAM(laser, self.map_size_pixels, self.map_size_meters)
        self._load_saved_map()
        self._write_meta()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="slam-mapper", daemon=True)
        self._thread.start()
        logger.info(
            "SLAM gestartet: %d px / %.1f m, quality=%d",
            self.map_size_pixels,
            self.map_size_meters,
            self.map_quality,
        )

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # -- data access -----------------------------------------------------------

    def pose(self) -> tuple[float, float, float] | None:
        """Current pose (x_m, y_m, theta_deg) in the map frame, or None."""
        with self._lock:
            return self._pose

    def grid(self) -> tuple[bytes, int, float] | None:
        """Occupancy grid copy (bytes, size_pixels, size_meters) for planning."""
        if self._slam is None:
            return None
        with self._lock:
            return (bytes(self._mapbytes), self.map_size_pixels, self.map_size_meters)

    # -- odometry input ----------------------------------------------------------

    def report_motion(self, left: float, right: float, dt_s: float) -> None:
        """Accumulate dead-reckoning motion since the last SLAM update.

        ``left``/``right`` are the normalized track speeds (-1..1) currently
        commanded; called from the core loop every tick, also during teleop.
        """
        if dt_s <= 0.0:
            return
        dxy_mm, dtheta_deg = motion_deltas(
            left,
            right,
            dt_s,
            self._drive_speed,
            self._turn_speed,
            self._speed_m_s,
            self._pivot_deg_s,
        )
        with self._odo_lock:
            self._odo_dxy_mm += dxy_mm
            self._odo_dtheta_deg += dtheta_deg
            self._odo_dt_s += dt_s

    def _pop_odometry(self) -> tuple[float, float, float]:
        with self._odo_lock:
            deltas = (self._odo_dxy_mm, self._odo_dtheta_deg, max(self._odo_dt_s, 1e-3))
            self._odo_dxy_mm = 0.0
            self._odo_dtheta_deg = 0.0
            self._odo_dt_s = 0.0
        return deltas

    # -- map persistence -----------------------------------------------------------

    def save_map(self) -> bool:
        """Persist the current occupancy grid as a grayscale PNG."""
        if self._slam is None:
            return False
        try:
            from PIL import Image

            with self._lock:
                data = bytes(self._mapbytes)
            img = Image.frombytes("L", (self.map_size_pixels, self.map_size_pixels), data)
            img.save(self.map_saved_path, format="PNG")
            logger.info("Karte gespeichert: %s", self.map_saved_path)
            return True
        except Exception:
            logger.exception("Karte konnte nicht gespeichert werden")
            return False

    def reset_map(self) -> None:
        """Discard the saved map and restart SLAM from scratch."""
        if not BREEZYSLAM_AVAILABLE:
            return
        self.map_saved_path.unlink(missing_ok=True)
        laser = Laser(_SCAN_SIZE, _SCAN_RATE_HZ, _DETECTION_ANGLE_DEG, _NO_DETECTION_MM)
        with self._lock:
            self._slam = RMHC_SLAM(laser, self.map_size_pixels, self.map_size_meters)
            self._mapbytes = bytearray(self.map_size_pixels * self.map_size_pixels)
            self._pose = None
        logger.info("Karte zurückgesetzt")

    def _load_saved_map(self) -> None:
        if not self.map_saved_path.exists():
            return
        try:
            from PIL import Image

            img = Image.open(self.map_saved_path).convert("L")
            if img.size != (self.map_size_pixels, self.map_size_pixels):
                logger.warning(
                    "Gespeicherte Karte hat falsche Größe %s — wird ignoriert", img.size
                )
                return
            self._slam.setmap(bytearray(img.tobytes()))
            logger.info("Gespeicherte Karte geladen: %s", self.map_saved_path)
        except Exception:
            logger.exception("Gespeicherte Karte konnte nicht geladen werden")

    def _write_meta(self) -> None:
        try:
            self.map_meta_path.write_text(
                json.dumps(
                    {
                        "size_pixels": self.map_size_pixels,
                        "size_meters": self.map_size_meters,
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            logger.warning("map_meta.json konnte nicht geschrieben werden")

    # -- worker -------------------------------------------------------------------

    def _run(self) -> None:
        while self._running:
            time.sleep(self.update_interval_s)
            try:
                self._update_once()
            except Exception:
                logger.exception("SLAM-Update fehlgeschlagen")

    def _update_once(self) -> None:
        scan = self.lidar.scan()
        if scan is None or scan.timestamp == self._last_scan_ts:
            return
        self._last_scan_ts = scan.timestamp
        scan_mm = scan_to_slam(scan.distances)
        if not any(scan_mm):
            return
        pose_change = self._pop_odometry()
        with self._lock:
            self._slam.update(
                scan_mm,
                pose_change=pose_change,
                should_update_map=not self.localize_only,
            )
            x_mm, y_mm, theta_deg = self._slam.getpos()
            self._pose = (x_mm / 1000.0, y_mm / 1000.0, theta_deg % 360.0)
            self._slam.getmap(self._mapbytes)
        self._maybe_write_image()

    def _maybe_write_image(self) -> None:
        now = time.monotonic()
        if now - self._last_image_write < 1.0:
            return
        self._last_image_write = now
        try:
            from PIL import Image

            with self._lock:
                data = bytes(self._mapbytes)
            img = Image.frombytes("L", (self.map_size_pixels, self.map_size_pixels), data)
            img.save(self.map_image_path, format="PNG")
        except Exception:
            logger.exception("Kartenbild konnte nicht geschrieben werden")
