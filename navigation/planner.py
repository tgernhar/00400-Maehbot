"""Grid path planning: downsample, inflate, A*, line-of-sight simplify.

Works on the BreezySLAM occupancy grid (grayscale bytes: 0 = obstacle,
255 = free, ~127 = unknown). Unknown cells are treated as traversable so
the robot can be sent into unexplored area; only clearly occupied cells
block. The grid is downsampled before planning so A* stays fast in pure
Python (800x800 -> 200x200 by default).

All public helpers use world coordinates in meters (map frame, origin at
the grid's top-left corner, x = column direction, y = row direction).
"""

from __future__ import annotations

import heapq
import math

# Grid cells darker than this count as obstacles (BreezySLAM: 0 = wall)
OBSTACLE_THRESHOLD = 100


def downsample_grid(
    grid: bytes,
    size_px: int,
    factor: int,
) -> tuple[list[bool], int]:
    """Reduce resolution; a coarse cell is blocked if any subcell is blocked."""
    coarse = size_px // factor
    blocked = [False] * (coarse * coarse)
    for row in range(size_px):
        base = row * size_px
        crow = min(row // factor, coarse - 1)
        for col in range(size_px):
            if grid[base + col] < OBSTACLE_THRESHOLD:
                ccol = min(col // factor, coarse - 1)
                blocked[crow * coarse + ccol] = True
    return blocked, coarse


def inflate(blocked: list[bool], size: int, radius_cells: int) -> list[bool]:
    """Grow obstacles by the robot radius (square structuring element)."""
    if radius_cells <= 0:
        return list(blocked)
    result = list(blocked)
    for row in range(size):
        for col in range(size):
            if not blocked[row * size + col]:
                continue
            for dr in range(-radius_cells, radius_cells + 1):
                rr = row + dr
                if rr < 0 or rr >= size:
                    continue
                for dc in range(-radius_cells, radius_cells + 1):
                    cc = col + dc
                    if 0 <= cc < size:
                        result[rr * size + cc] = True
    return result


def astar(
    blocked: list[bool],
    size: int,
    start: tuple[int, int],
    goal: tuple[int, int],
) -> list[tuple[int, int]] | None:
    """A* on an 8-connected grid of (col, row) cells; None if unreachable."""

    def idx(cell: tuple[int, int]) -> int:
        return cell[1] * size + cell[0]

    if blocked[idx(start)] or blocked[idx(goal)]:
        return None
    if start == goal:
        return [start]

    def heuristic(cell: tuple[int, int]) -> float:
        return math.hypot(cell[0] - goal[0], cell[1] - goal[1])

    open_heap: list[tuple[float, tuple[int, int]]] = [(heuristic(start), start)]
    g_score: dict[tuple[int, int], float] = {start: 0.0}
    came_from: dict[tuple[int, int], tuple[int, int]] = {}
    closed: set[tuple[int, int]] = set()

    neighbors = [
        (1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)),
        (-1, 1, math.sqrt(2)), (-1, -1, math.sqrt(2)),
    ]

    while open_heap:
        _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            path.reverse()
            return path
        closed.add(current)
        cx, cy = current
        for dx, dy, cost in neighbors:
            nx, ny = cx + dx, cy + dy
            if nx < 0 or nx >= size or ny < 0 or ny >= size:
                continue
            if blocked[ny * size + nx]:
                continue
            tentative = g_score[current] + cost
            neighbor = (nx, ny)
            if tentative < g_score.get(neighbor, float("inf")):
                g_score[neighbor] = tentative
                came_from[neighbor] = current
                heapq.heappush(open_heap, (tentative + heuristic(neighbor), neighbor))
    return None


def line_of_sight(
    blocked: list[bool],
    size: int,
    a: tuple[int, int],
    b: tuple[int, int],
) -> bool:
    """Bresenham check whether the straight cell line a->b is free."""
    x0, y0 = a
    x1, y1 = b
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        if blocked[y0 * size + x0]:
            return False
        if (x0, y0) == (x1, y1):
            return True
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def simplify_path(
    path: list[tuple[int, int]],
    blocked: list[bool],
    size: int,
) -> list[tuple[int, int]]:
    """Drop intermediate cells that are reachable by straight lines."""
    if len(path) <= 2:
        return path
    result = [path[0]]
    anchor = 0
    for i in range(2, len(path)):
        if not line_of_sight(blocked, size, path[anchor], path[i]):
            result.append(path[i - 1])
            anchor = i - 1
    result.append(path[-1])
    return result


def clear_disk(
    blocked: list[bool],
    size: int,
    col: int,
    row: int,
    radius_cells: int,
) -> None:
    """Mark a circular footprint around a cell as free (robot / goal pose)."""
    if radius_cells <= 0:
        blocked[row * size + col] = False
        return
    r2 = radius_cells * radius_cells
    for dr in range(-radius_cells, radius_cells + 1):
        for dc in range(-radius_cells, radius_cells + 1):
            if dr * dr + dc * dc > r2:
                continue
            rr, cc = row + dr, col + dc
            if 0 <= rr < size and 0 <= cc < size:
                blocked[rr * size + cc] = False


def nearest_free_cell(
    blocked: list[bool],
    size: int,
    cell: tuple[int, int],
    max_radius: int = 40,
) -> tuple[int, int] | None:
    """BFS spiral: closest unblocked grid cell to ``cell``."""
    from collections import deque

    if not blocked[cell[1] * size + cell[0]]:
        return cell
    seen = {cell}
    queue: deque[tuple[int, int]] = deque([cell])
    while queue:
        col, row = queue.popleft()
        if not blocked[row * size + col]:
            return (col, row)
        if abs(col - cell[0]) > max_radius or abs(row - cell[1]) > max_radius:
            continue
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nc = (col + dc, row + dr)
            if 0 <= nc[0] < size and 0 <= nc[1] < size and nc not in seen:
                seen.add(nc)
                queue.append(nc)
    return None


def plan_path(
    grid: bytes,
    size_px: int,
    size_m: float,
    start_m: tuple[float, float],
    goal_m: tuple[float, float],
    robot_radius_m: float,
    downsample: int = 4,
    debug_log_path: str | None = None,
) -> list[tuple[float, float]] | None:
    """Plan waypoints (meters) from start to goal; None if no path exists.

    After obstacle inflation the robot footprint and goal pose are carved
    free — clearing only the centre cell traps the robot when walls are
    nearby (all neighbours stay blocked).
    """
    blocked, coarse = downsample_grid(grid, size_px, downsample)
    cell_m = size_m / coarse
    # int() not ceil(): 0.25 m radius at 0.1 m cells -> 2 cells (r=3 seals corridors)
    radius_cells = max(1, int(robot_radius_m / cell_m))
    blocked = inflate(blocked, coarse, radius_cells)

    def to_cell(p: tuple[float, float]) -> tuple[int, int]:
        col = min(coarse - 1, max(0, int(p[0] / cell_m)))
        row = min(coarse - 1, max(0, int(p[1] / cell_m)))
        return (col, row)

    start = to_cell(start_m)
    goal = to_cell(goal_m)
    clear_disk(blocked, coarse, start[0], start[1], radius_cells)
    clear_disk(blocked, coarse, goal[0], goal[1], radius_cells)

    goal_cell = nearest_free_cell(blocked, coarse, goal) or goal
    cells = astar(blocked, coarse, start, goal_cell)
    if cells is None:
        # #region agent log
        if debug_log_path:
            try:
                import json
                import time

                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "sessionId": "f2dd0e",
                                "hypothesisId": "A",
                                "location": "planner.py:plan_path",
                                "message": "path planning failed",
                                "data": {
                                    "start_m": start_m,
                                    "goal_m": goal_m,
                                    "start_cell": start,
                                    "goal_cell": goal,
                                    "goal_cell_snapped": goal_cell,
                                    "radius_cells": radius_cells,
                                    "start_blocked": blocked[start[1] * coarse + start[0]],
                                    "goal_blocked": blocked[goal[1] * coarse + goal[0]],
                                },
                                "timestamp": int(time.time() * 1000),
                            }
                        )
                        + "\n"
                    )
            except OSError:
                pass
        # #endregion
        return None
    cells = simplify_path(cells, blocked, coarse)
    waypoints = [((c + 0.5) * cell_m, (r + 0.5) * cell_m) for c, r in cells]
    # Use the exact goal position instead of the goal cell center
    waypoints[-1] = goal_m
    return waypoints
