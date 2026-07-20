"""Pose-feedback navigation: go-to-point and line (boustrophedon) mowing.

The ``Navigator`` closes the loop with the SLAM pose (unlike the timed
``CoverageController``): it plans a path on the occupancy grid, turns
towards the next waypoint, drives with continuous heading correction and
re-plans when the LiDAR reports an obstacle ahead.

Zone mowing generates parallel lines across a user-drawn rectangle. The
line orientation (``direction_deg``, 0 = along the map x-axis) is chosen
by the user; the robot navigates to each line start and mows line by
line in alternating directions.

IPC mirrors coverage: web queues ``nav_command.json``; core consumes it
and publishes ``nav_status.json``. Zones persist in ``zones.json``.
"""

from __future__ import annotations

import json
import logging
import math
import time
from enum import Enum
from typing import Any, Callable

from navigation.lidar import LidarReader
from navigation.planner import plan_path
from storage.paths import StoragePaths

logger = logging.getLogger(__name__)

_FRONT_DEG = 0.0

PoseSource = Callable[[], "tuple[float, float, float] | None"]
GridSource = Callable[[], "tuple[bytes, int, float] | None"]


def normalize_angle_deg(angle: float) -> float:
    """Wrap to [-180, 180)."""
    return (angle + 180.0) % 360.0 - 180.0


def generate_zone_lines(
    x_m: float,
    y_m: float,
    width_m: float,
    height_m: float,
    direction_deg: float,
    spacing_m: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Boustrophedon lines across an axis-aligned rectangle.

    ``(x_m, y_m)`` is the rectangle's min corner, ``direction_deg`` the
    line orientation (0 = along +x, counter-clockwise positive). Returns
    world-coordinate segments in mowing order, alternating direction.
    """
    if width_m <= 0 or height_m <= 0 or spacing_m <= 0:
        return []
    theta = math.radians(direction_deg)
    dx, dy = math.cos(theta), math.sin(theta)  # line direction
    nx, ny = -dy, dx  # normal (line spacing direction)
    cx, cy = x_m + width_m / 2.0, y_m + height_m / 2.0

    corners = [
        (x_m, y_m),
        (x_m + width_m, y_m),
        (x_m, y_m + height_m),
        (x_m + width_m, y_m + height_m),
    ]
    offsets = [(px - cx) * nx + (py - cy) * ny for px, py in corners]
    s_min, s_max = min(offsets), max(offsets)

    lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
    s = s_min + spacing_m / 2.0
    flip = False
    while s <= s_max:
        ox, oy = cx + nx * s, cy + ny * s
        seg = _clip_line_to_rect(ox, oy, dx, dy, x_m, y_m, width_m, height_m)
        if seg is not None:
            lines.append((seg[1], seg[0]) if flip else seg)
            flip = not flip
        s += spacing_m
    return lines


def _clip_line_to_rect(
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    rx: float,
    ry: float,
    rw: float,
    rh: float,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Clip the infinite line O + t*D against the rectangle (Liang-Barsky)."""
    t_min, t_max = -math.inf, math.inf
    for d, o, lo, hi in ((dx, ox, rx, rx + rw), (dy, oy, ry, ry + rh)):
        if abs(d) < 1e-12:
            if o < lo or o > hi:
                return None
            continue
        t0, t1 = (lo - o) / d, (hi - o) / d
        if t0 > t1:
            t0, t1 = t1, t0
        t_min, t_max = max(t_min, t0), min(t_max, t1)
    if t_min >= t_max:
        return None
    return (
        (ox + dx * t_min, oy + dy * t_min),
        (ox + dx * t_max, oy + dy * t_max),
    )


class NavState(str, Enum):
    IDLE = "idle"
    TURNING = "turning"
    DRIVING = "driving"
    DONE = "done"
    ABORTED = "aborted"


class Navigator:
    """Waypoint follower ticked from the core loop; returns track speeds."""

    def __init__(
        self,
        pose_source: PoseSource,
        grid_source: GridSource,
        lidar: LidarReader | None,
        config: dict[str, Any],
    ) -> None:
        self.pose_source = pose_source
        self.grid_source = grid_source
        self.lidar = lidar
        self.update_config(config)
        self.state = NavState.IDLE
        self.mode: str = "goto"  # goto | mow
        self._waypoints: list[tuple[float, float]] = []
        self._target: tuple[float, float] | None = None
        self._lines: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self._line_index = 0
        self._zone_name = ""
        self._replans = 0
        self._error: str | None = None
        self._obstacle_since = 0.0

    def update_config(self, config: dict[str, Any]) -> None:
        nav = config.get("navigation", {})
        self.drive_speed = float(nav.get("drive_speed", 0.5))
        self.turn_speed = float(nav.get("turn_speed", 0.5))
        self.waypoint_tolerance_m = float(nav.get("waypoint_tolerance_m", 0.15))
        self.heading_tolerance_deg = float(nav.get("heading_tolerance_deg", 8.0))
        self.obstacle_stop_m = float(nav.get("obstacle_stop_m", 0.30))
        self.obstacle_sector_deg = float(nav.get("obstacle_sector_deg", 60.0))
        self.robot_radius_m = float(nav.get("robot_radius_m", 0.25))
        self.line_spacing_m = float(nav.get("line_spacing_m", 0.15))
        self.max_replans = int(nav.get("max_replans", 3))

    # -- commands -----------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.state in (NavState.TURNING, NavState.DRIVING)

    def goto(self, x_m: float, y_m: float) -> None:
        if self.active:
            self._error = "Navigation läuft bereits"
            return
        self.mode = "goto"
        self._lines = []
        self._line_index = 0
        self._zone_name = ""
        self._replans = 0
        self._error = None
        if not self._plan_to(x_m, y_m):
            return
        self._target = (x_m, y_m)
        self.state = NavState.TURNING
        logger.info("Navigation zu (%.2f, %.2f) gestartet", x_m, y_m)

    def mow_zone(self, zone: dict[str, Any]) -> None:
        if self.active:
            self._error = "Navigation läuft bereits"
            return
        lines = generate_zone_lines(
            float(zone.get("x_m", 0.0)),
            float(zone.get("y_m", 0.0)),
            float(zone.get("width_m", 0.0)),
            float(zone.get("height_m", 0.0)),
            float(zone.get("direction_deg", 0.0)),
            self.line_spacing_m,
        )
        if not lines:
            self.state = NavState.ABORTED
            self._error = "Zone zu klein — keine Bahnen"
            return
        self.mode = "mow"
        self._lines = lines
        self._line_index = 0
        self._zone_name = str(zone.get("name", ""))
        self._replans = 0
        self._error = None
        if not self._start_line(0):
            return
        self.state = NavState.TURNING
        logger.info(
            "Zonen-Mähen gestartet: %s, %d Bahnen", self._zone_name, len(lines)
        )

    def stop(self, reason: str | None = None) -> None:
        if not self.active:
            return
        self.state = NavState.ABORTED
        self._error = reason or "Manuell gestoppt"
        self._waypoints = []
        logger.info("Navigation gestoppt: %s", self._error)

    # -- planning -----------------------------------------------------------

    def _plan_to(self, x_m: float, y_m: float) -> bool:
        pose = self.pose_source()
        if pose is None:
            self.state = NavState.ABORTED
            self._error = "Keine Position — SLAM nicht bereit"
            return False
        grid = self.grid_source()
        if grid is None:
            self.state = NavState.ABORTED
            self._error = "Keine Karte — SLAM nicht bereit"
            return False
        data, size_px, size_m = grid
        path = plan_path(
            data,
            size_px,
            size_m,
            (pose[0], pose[1]),
            (x_m, y_m),
            self.robot_radius_m,
        )
        if path is None:
            self.state = NavState.ABORTED
            self._error = "Kein Weg zum Ziel gefunden"
            return False
        # path[0] is the robot's own grid cell center — always skip it, and
        # drop any further waypoints that are already within tolerance.
        self._waypoints = [
            wp
            for wp in path[1:]
            if math.hypot(wp[0] - pose[0], wp[1] - pose[1]) > self.waypoint_tolerance_m
        ]
        if not self._waypoints:
            self._waypoints = [(x_m, y_m)]
        return True

    def _start_line(self, index: int) -> bool:
        start, end = self._lines[index]
        if not self._plan_to(start[0], start[1]):
            return False
        self._waypoints.append(end)
        self._target = end
        return True

    # -- main tick ------------------------------------------------------------

    def tick(self) -> tuple[float, float]:
        if not self.active:
            return (0.0, 0.0)
        pose = self.pose_source()
        if pose is None:
            self.stop("Position verloren — SLAM nicht bereit")
            return (0.0, 0.0)

        if self.state == NavState.DRIVING and self._obstacle_ahead():
            return self._handle_obstacle()
        self._obstacle_since = 0.0

        if not self._waypoints:
            self._advance()
            return (0.0, 0.0)

        x, y, theta = pose
        wx, wy = self._waypoints[0]
        dist = math.hypot(wx - x, wy - y)
        if dist <= self.waypoint_tolerance_m:
            self._waypoints.pop(0)
            if not self._waypoints:
                self._advance()
            else:
                self.state = NavState.TURNING
            return (0.0, 0.0)

        bearing = math.degrees(math.atan2(wy - y, wx - x))
        error = normalize_angle_deg(bearing - theta)

        if self.state == NavState.TURNING:
            if abs(error) <= self.heading_tolerance_deg:
                self.state = NavState.DRIVING
                return (self.drive_speed, self.drive_speed)
            # Positive error = target to the left = pivot left (CCW)
            sign = 1.0 if error > 0 else -1.0
            return (-sign * self.turn_speed, sign * self.turn_speed)

        # DRIVING with proportional heading correction
        if abs(error) > 2.0 * self.heading_tolerance_deg:
            self.state = NavState.TURNING
            return (0.0, 0.0)
        correction = self.drive_speed * max(-0.5, min(0.5, error / 45.0))
        return (self.drive_speed - correction, self.drive_speed + correction)

    def _advance(self) -> None:
        """Current waypoint queue finished: next line or done."""
        if self.mode == "mow" and self._line_index + 1 < len(self._lines):
            self._line_index += 1
            self._replans = 0
            if self._start_line(self._line_index):
                self.state = NavState.TURNING
            return
        self.state = NavState.DONE
        logger.info("Navigation abgeschlossen (%s)", self.mode)

    # -- obstacle handling ---------------------------------------------------------

    def _obstacle_ahead(self) -> bool:
        if self.lidar is None:
            return False
        dist = self.lidar.min_distance_in_sector(_FRONT_DEG, self.obstacle_sector_deg)
        return dist is not None and dist <= self.obstacle_stop_m

    def _handle_obstacle(self) -> tuple[float, float]:
        """Stop, wait shortly, then re-plan around the obstacle."""
        now = time.monotonic()
        if self._obstacle_since == 0.0:
            self._obstacle_since = now
            logger.info("Hindernis voraus — warte und plane neu")
            return (0.0, 0.0)
        if now - self._obstacle_since < 2.0:
            return (0.0, 0.0)
        self._obstacle_since = 0.0
        self._replans += 1
        if self._replans > self.max_replans:
            self.stop("Hindernis nicht umfahrbar — Fahrt gestoppt")
            return (0.0, 0.0)
        target = self._target or (self._waypoints[-1] if self._waypoints else None)
        if target is None:
            self.stop("Kein Ziel mehr vorhanden")
            return (0.0, 0.0)
        if not self._plan_to(target[0], target[1]):
            return (0.0, 0.0)
        self.state = NavState.TURNING
        return (0.0, 0.0)

    # -- status ------------------------------------------------------------------

    def status_dict(self) -> dict[str, Any]:
        pose = self.pose_source()
        return {
            "state": self.state.value,
            "mode": self.mode,
            "x_m": round(pose[0], 3) if pose else None,
            "y_m": round(pose[1], 3) if pose else None,
            "theta_deg": round(pose[2], 1) if pose else None,
            "target_x_m": self._target[0] if self._target else None,
            "target_y_m": self._target[1] if self._target else None,
            "waypoints": [[round(wx, 2), round(wy, 2)] for wx, wy in self._waypoints],
            "line_index": self._line_index,
            "line_count": len(self._lines),
            "zone_name": self._zone_name,
            "lidar_connected": bool(self.lidar.connected) if self.lidar else False,
            "error": self._error,
        }


# -- file-based IPC (web -> core commands, core -> web status) -------------------


def default_nav_status() -> dict[str, Any]:
    return {
        "state": NavState.IDLE.value,
        "mode": "goto",
        "x_m": None,
        "y_m": None,
        "theta_deg": None,
        "target_x_m": None,
        "target_y_m": None,
        "waypoints": [],
        "line_index": 0,
        "line_count": 0,
        "zone_name": "",
        "lidar_connected": False,
        "slam_available": False,
        "error": None,
    }


def read_nav_status(paths: StoragePaths) -> dict[str, Any]:
    path = paths.nav_status_path
    if not path.exists():
        return default_nav_status()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {**default_nav_status(), **data}
    except (json.JSONDecodeError, OSError):
        return default_nav_status()


def write_nav_status(paths: StoragePaths, status: dict[str, Any]) -> None:
    paths.nav_status_path.write_text(
        json.dumps(status, ensure_ascii=False),
        encoding="utf-8",
    )


def queue_nav_command(paths: StoragePaths, action: str, **kwargs: Any) -> None:
    payload: dict[str, Any] = {"action": action, "ts": time.time(), **kwargs}
    paths.nav_command_path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def consume_nav_command(paths: StoragePaths) -> dict[str, Any] | None:
    path = paths.nav_command_path
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        path.unlink(missing_ok=True)
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Invalid nav command file: %s", exc)
        path.unlink(missing_ok=True)
        return None


# -- zone persistence -------------------------------------------------------------


def load_zones(paths: StoragePaths) -> list[dict[str, Any]]:
    path = paths.zones_path
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save_zones(paths: StoragePaths, zones: list[dict[str, Any]]) -> None:
    paths.zones_path.write_text(
        json.dumps(zones, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
