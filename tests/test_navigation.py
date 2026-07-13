"""Tests for SLAM navigation: line generator, planner, navigator, odometry."""

from __future__ import annotations

import math

import pytest

from navigation.navigator import (
    Navigator,
    NavState,
    generate_zone_lines,
    normalize_angle_deg,
)
from navigation.planner import (
    astar,
    downsample_grid,
    inflate,
    plan_path,
    simplify_path,
)
from navigation.slam import motion_deltas, scan_to_slam


# -- zone line generator -------------------------------------------------------


def test_zone_lines_axis_aligned() -> None:
    lines = generate_zone_lines(0.0, 0.0, 2.0, 1.0, direction_deg=0.0, spacing_m=0.25)
    assert len(lines) == 4  # 1 m height / 0.25 m spacing
    for (x0, y0), (x1, y1) in lines:
        assert y0 == pytest.approx(y1)  # horizontal lines
        assert abs(x1 - x0) == pytest.approx(2.0)
        assert 0.0 <= y0 <= 1.0


def test_zone_lines_alternate_direction() -> None:
    lines = generate_zone_lines(0.0, 0.0, 2.0, 1.0, direction_deg=0.0, spacing_m=0.25)
    assert lines[0][0][0] < lines[0][1][0]  # first line left -> right
    assert lines[1][0][0] > lines[1][1][0]  # second line right -> left


def test_zone_lines_rotated_90() -> None:
    lines = generate_zone_lines(0.0, 0.0, 1.0, 2.0, direction_deg=90.0, spacing_m=0.25)
    assert len(lines) == 4  # spacing spans the 1 m width now
    for (x0, y0), (x1, y1) in lines:
        assert x0 == pytest.approx(x1)  # vertical lines
        assert abs(y1 - y0) == pytest.approx(2.0)


def test_zone_lines_diagonal_stay_inside() -> None:
    lines = generate_zone_lines(1.0, 1.0, 2.0, 2.0, direction_deg=45.0, spacing_m=0.3)
    assert lines
    for (x0, y0), (x1, y1) in lines:
        for x, y in ((x0, y0), (x1, y1)):
            assert 1.0 - 1e-6 <= x <= 3.0 + 1e-6
            assert 1.0 - 1e-6 <= y <= 3.0 + 1e-6


def test_zone_lines_empty_for_zero_area() -> None:
    assert generate_zone_lines(0.0, 0.0, 0.0, 1.0, 0.0, 0.25) == []
    assert generate_zone_lines(0.0, 0.0, 1.0, 1.0, 0.0, 0.0) == []


# -- planner --------------------------------------------------------------------


def _grid(size: int, walls: set[tuple[int, int]]) -> bytes:
    """Grayscale grid: 255 free, 0 wall at (col, row)."""
    data = bytearray([255] * size * size)
    for col, row in walls:
        data[row * size + col] = 0
    return bytes(data)


def test_astar_straight_line() -> None:
    blocked = [False] * 100
    path = astar(blocked, 10, (0, 0), (9, 9))
    assert path is not None
    assert path[0] == (0, 0)
    assert path[-1] == (9, 9)


def test_astar_routes_around_wall() -> None:
    size = 10
    blocked = [False] * (size * size)
    for row in range(9):  # vertical wall at col 5 with gap at row 9
        blocked[row * size + 5] = True
    path = astar(blocked, size, (0, 0), (9, 0))
    assert path is not None
    assert any(row >= 9 for _, row in path)  # goes through the gap


def test_astar_no_path() -> None:
    size = 10
    blocked = [False] * (size * size)
    for row in range(size):  # full wall
        blocked[row * size + 5] = True
    assert astar(blocked, size, (0, 0), (9, 0)) is None


def test_simplify_path_collapses_straight_runs() -> None:
    blocked = [False] * 100
    path = [(0, 0), (1, 1), (2, 2), (3, 3), (4, 4)]
    assert simplify_path(path, blocked, 10) == [(0, 0), (4, 4)]


def test_inflate_grows_obstacles() -> None:
    size = 5
    blocked = [False] * (size * size)
    blocked[2 * size + 2] = True
    grown = inflate(blocked, size, 1)
    assert grown[1 * size + 1] and grown[3 * size + 3]
    assert not grown[0 * size + 0]


def test_downsample_marks_blocked_cells() -> None:
    grid = _grid(8, {(3, 3)})
    blocked, coarse = downsample_grid(grid, 8, 4)
    assert coarse == 2
    assert blocked[0 * 2 + 0]  # cell containing (3,3)
    assert not blocked[1 * 2 + 1]


def test_plan_path_end_to_end() -> None:
    size = 40
    walls = {(20, row) for row in range(0, 35)}  # wall with gap at bottom
    grid = _grid(size, walls)
    path = plan_path(
        grid,
        size_px=size,
        size_m=10.0,
        start_m=(2.0, 2.0),
        goal_m=(8.0, 2.0),
        robot_radius_m=0.2,
        downsample=2,
    )
    assert path is not None
    assert path[-1] == (8.0, 2.0)
    assert any(wy > 7.0 for _, wy in path)  # detours through the gap


def test_plan_path_unreachable() -> None:
    size = 40
    walls = {(20, row) for row in range(size)}  # full wall
    grid = _grid(size, walls)
    path = plan_path(
        grid,
        size_px=size,
        size_m=10.0,
        start_m=(2.0, 2.0),
        goal_m=(8.0, 2.0),
        robot_radius_m=0.2,
        downsample=2,
    )
    assert path is None


# -- odometry / scan conversion ---------------------------------------------------


def test_motion_deltas_straight() -> None:
    dxy_mm, dtheta = motion_deltas(
        0.5, 0.5, 1.0, drive_speed=0.5, turn_speed=0.5, speed_m_s=0.1, pivot_deg_s=45.0
    )
    assert dxy_mm == pytest.approx(100.0)  # 0.1 m/s * 1 s
    assert dtheta == pytest.approx(0.0)


def test_motion_deltas_pivot_left() -> None:
    dxy_mm, dtheta = motion_deltas(
        -0.5, 0.5, 2.0, drive_speed=0.5, turn_speed=0.5, speed_m_s=0.1, pivot_deg_s=45.0
    )
    assert dxy_mm == pytest.approx(0.0)
    assert dtheta == pytest.approx(90.0)  # 45 deg/s * 2 s, left = positive


def test_scan_to_slam_reorders_and_converts() -> None:
    distances = [0.0] * 360
    distances[0] = 1.0  # front
    distances[90] = 2.0  # sensor 90 deg clockwise = right side
    scan = scan_to_slam(distances)
    assert len(scan) == 360
    assert scan[180] == 1000  # front lands at CCW angle 0 (index 180)
    assert scan[90] == 2000  # right side = CCW -90 deg (index 90)


# -- navigator ---------------------------------------------------------------------


class FakePose:
    def __init__(self, x: float, y: float, theta: float) -> None:
        self.x, self.y, self.theta = x, y, theta

    def __call__(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.theta)


def _free_grid_source(size_px: int = 40, size_m: float = 10.0):
    grid = bytes([255] * size_px * size_px)
    return lambda: (grid, size_px, size_m)


def _nav_config() -> dict:
    return {
        "navigation": {
            "drive_speed": 0.5,
            "turn_speed": 0.5,
            "waypoint_tolerance_m": 0.15,
            "heading_tolerance_deg": 8.0,
            "obstacle_stop_m": 0.3,
            "robot_radius_m": 0.2,
            "line_spacing_m": 0.25,
            "max_replans": 2,
        }
    }


def test_navigator_turns_then_drives_then_reaches_goal() -> None:
    pose = FakePose(2.0, 2.0, 90.0)  # facing +y, target is towards +x
    nav = Navigator(pose, _free_grid_source(), lidar=None, config=_nav_config())
    nav.goto(5.0, 2.0)
    assert nav.state == NavState.TURNING

    # Heading error is -90 deg -> pivot right (left forward, right backwards)
    left, right = nav.tick()
    assert left > 0 and right < 0

    pose.theta = 0.0  # aligned with target
    left, right = nav.tick()
    assert nav.state == NavState.DRIVING
    assert left == right == pytest.approx(0.5)

    pose.x = 5.0  # jump to goal
    nav.tick()  # consume final waypoint(s)
    for _ in range(5):
        if nav.state == NavState.DONE:
            break
        nav.tick()
    assert nav.state == NavState.DONE


def test_navigator_aborts_without_pose() -> None:
    nav = Navigator(lambda: None, _free_grid_source(), lidar=None, config=_nav_config())
    nav.goto(5.0, 2.0)
    assert nav.state == NavState.ABORTED
    assert nav.status_dict()["error"] is not None


def test_navigator_aborts_when_goal_unreachable() -> None:
    size = 40
    data = bytearray([255] * size * size)
    for row in range(size):  # full wall in the middle
        data[row * size + 20] = 0
    grid = bytes(data)
    pose = FakePose(2.0, 2.0, 0.0)
    nav = Navigator(pose, lambda: (grid, size, 10.0), lidar=None, config=_nav_config())
    nav.goto(8.0, 2.0)
    assert nav.state == NavState.ABORTED
    assert "Kein Weg" in (nav.status_dict()["error"] or "")


def test_navigator_mow_zone_generates_lines_and_progress() -> None:
    pose = FakePose(1.0, 1.0, 0.0)
    nav = Navigator(pose, _free_grid_source(), lidar=None, config=_nav_config())
    nav.mow_zone(
        {
            "id": "z1",
            "name": "Test",
            "x_m": 2.0,
            "y_m": 2.0,
            "width_m": 2.0,
            "height_m": 1.0,
            "direction_deg": 0.0,
        }
    )
    assert nav.state == NavState.TURNING
    status = nav.status_dict()
    assert status["line_count"] == 4  # 1 m / 0.25 m spacing
    assert status["mode"] == "mow"


def test_navigator_driving_applies_heading_correction() -> None:
    pose = FakePose(2.0, 2.0, 0.0)
    nav = Navigator(pose, _free_grid_source(), lidar=None, config=_nav_config())
    nav.goto(6.0, 2.0)
    pose.theta = 0.0
    nav.tick()  # TURNING -> DRIVING (aligned)
    assert nav.state == NavState.DRIVING

    pose.theta = 10.0  # slightly off to the left -> steer right
    left, right = nav.tick()
    assert left > right


def test_normalize_angle() -> None:
    assert normalize_angle_deg(190.0) == pytest.approx(-170.0)
    assert normalize_angle_deg(-190.0) == pytest.approx(170.0)
    assert normalize_angle_deg(0.0) == pytest.approx(0.0)


def test_bearing_math_matches_convention() -> None:
    # Sanity check: target directly "south" (+y) of robot -> bearing 90 deg
    assert math.degrees(math.atan2(1.0, 0.0)) == pytest.approx(90.0)
