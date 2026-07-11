"""LDRobot D500 (STL-19P / LD19 protocol) LiDAR reader.

A background thread reads 47-byte measurement packets from the serial port
(230400 baud), verifies CRC8 and keeps the latest full 360-degree scan in
1-degree bins. The coverage controller queries ``min_distance_in_sector``
for obstacle checks; a low-rate preview image (``lidar.jpg``) is rendered
for the web UI, mirroring the camera ``preview.jpg`` mechanism.

Angle convention: 0 degrees = robot front, increasing clockwise (as emitted
by the sensor). ``angle_offset_deg`` rotates the scan if the sensor is not
mounted with its connector pointing backwards.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PACKET_HEADER = 0x54
PACKET_VER_LEN = 0x2C
PACKET_SIZE = 47
POINTS_PER_PACKET = 12

# CRC8 lookup table from the LDRobot LD19 development manual
_CRC_TABLE = [
    0x00, 0x4D, 0x9A, 0xD7, 0x79, 0x34, 0xE3, 0xAE, 0xF2, 0xBF, 0x68, 0x25,
    0x8B, 0xC6, 0x11, 0x5C, 0xA9, 0xE4, 0x33, 0x7E, 0xD0, 0x9D, 0x4A, 0x07,
    0x5B, 0x16, 0xC1, 0x8C, 0x22, 0x6F, 0xB8, 0xF5, 0x1F, 0x52, 0x85, 0xC8,
    0x66, 0x2B, 0xFC, 0xB1, 0xED, 0xA0, 0x77, 0x3A, 0x94, 0xD9, 0x0E, 0x43,
    0xB6, 0xFB, 0x2C, 0x61, 0xCF, 0x82, 0x55, 0x18, 0x44, 0x09, 0xDE, 0x93,
    0x3D, 0x70, 0xA7, 0xEA, 0x3E, 0x73, 0xA4, 0xE9, 0x47, 0x0A, 0xDD, 0x90,
    0xCC, 0x81, 0x56, 0x1B, 0xB5, 0xF8, 0x2F, 0x62, 0x97, 0xDA, 0x0D, 0x40,
    0xEE, 0xA3, 0x74, 0x39, 0x65, 0x28, 0xFF, 0xB2, 0x1C, 0x51, 0x86, 0xCB,
    0x21, 0x6C, 0xBB, 0xF6, 0x58, 0x15, 0xC2, 0x8F, 0xD3, 0x9E, 0x49, 0x04,
    0xAA, 0xE7, 0x30, 0x7D, 0x88, 0xC5, 0x12, 0x5F, 0xF1, 0xBC, 0x6B, 0x26,
    0x7A, 0x37, 0xE0, 0xAD, 0x03, 0x4E, 0x99, 0xD4, 0x7C, 0x31, 0xE6, 0xAB,
    0x05, 0x48, 0x9F, 0xD2, 0x8E, 0xC3, 0x14, 0x59, 0xF7, 0xBA, 0x6D, 0x20,
    0xD5, 0x98, 0x4F, 0x02, 0xAC, 0xE1, 0x36, 0x7B, 0x27, 0x6A, 0xBD, 0xF0,
    0x5E, 0x13, 0xC4, 0x89, 0x63, 0x2E, 0xF9, 0xB4, 0x1A, 0x57, 0x80, 0xCD,
    0x91, 0xDC, 0x0B, 0x46, 0xE8, 0xA5, 0x72, 0x3F, 0xCA, 0x87, 0x50, 0x1D,
    0xB3, 0xFE, 0x29, 0x64, 0x38, 0x75, 0xA2, 0xEF, 0x41, 0x0C, 0xDB, 0x96,
    0x42, 0x0F, 0xD8, 0x95, 0x3B, 0x76, 0xA1, 0xEC, 0xB0, 0xFD, 0x2A, 0x67,
    0xC9, 0x84, 0x53, 0x1E, 0xEB, 0xA6, 0x71, 0x3C, 0x92, 0xDF, 0x08, 0x45,
    0x19, 0x54, 0x83, 0xCE, 0x60, 0x2D, 0xFA, 0xB7, 0x5D, 0x10, 0xC7, 0x8A,
    0x24, 0x69, 0xBE, 0xF3, 0xAF, 0xE2, 0x35, 0x78, 0xD6, 0x9B, 0x4C, 0x01,
    0xF4, 0xB9, 0x6E, 0x23, 0x8D, 0xC0, 0x17, 0x5A, 0x06, 0x4B, 0x9C, 0xD1,
    0x7F, 0x32, 0xE5, 0xA8,
]

MIN_VALID_DISTANCE_M = 0.02
SCAN_STALE_AFTER_S = 2.0


def _crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = _CRC_TABLE[(crc ^ byte) & 0xFF]
    return crc


def parse_packet(packet: bytes) -> list[tuple[float, float]] | None:
    """Parse one 47-byte LD19 packet into (angle_deg, distance_m) points.

    Returns None if the CRC or framing is invalid.
    """
    if len(packet) != PACKET_SIZE or packet[0] != PACKET_HEADER or packet[1] != PACKET_VER_LEN:
        return None
    if _crc8(packet[:-1]) != packet[-1]:
        return None
    start_angle = int.from_bytes(packet[4:6], "little") / 100.0
    end_angle = int.from_bytes(packet[42:44], "little") / 100.0
    span = (end_angle - start_angle) % 360.0
    step = span / (POINTS_PER_PACKET - 1) if POINTS_PER_PACKET > 1 else 0.0
    points: list[tuple[float, float]] = []
    for i in range(POINTS_PER_PACKET):
        offset = 6 + i * 3
        distance_mm = int.from_bytes(packet[offset : offset + 2], "little")
        angle = (start_angle + step * i) % 360.0
        points.append((angle, distance_mm / 1000.0))
    return points


class LidarScan:
    """Latest distances in 1-degree bins (meters, 0.0 = no echo)."""

    def __init__(self, distances: list[float], timestamp: float) -> None:
        self.distances = distances
        self.timestamp = timestamp

    def min_distance_in_sector(self, center_deg: float, width_deg: float) -> float | None:
        """Smallest valid distance within the sector, None if no echo at all."""
        half = max(0.0, width_deg) / 2.0
        best: float | None = None
        start = int(math.floor(center_deg - half))
        end = int(math.ceil(center_deg + half))
        for deg in range(start, end + 1):
            d = self.distances[deg % 360]
            if d >= MIN_VALID_DISTANCE_M and (best is None or d < best):
                best = d
        return best


class LidarReader:
    """Background serial reader with scan buffer and preview rendering."""

    def __init__(
        self,
        port: str,
        baud: int = 230400,
        angle_offset_deg: float = 0.0,
        preview_path: Path | None = None,
        preview_fps: float = 2.0,
        preview_range_m: float = 4.0,
    ) -> None:
        self.port = port
        self.baud = baud
        self.angle_offset_deg = angle_offset_deg
        self.preview_path = preview_path
        self.preview_interval_s = 1.0 / max(preview_fps, 0.1)
        self.preview_range_m = preview_range_m
        self._distances = [0.0] * 360
        self._scan_timestamp = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._serial: Any = None
        self._connected = False
        self._last_preview = 0.0
        self._front_sector_deg = 60.0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, name="lidar-reader", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        self._close_serial()

    @property
    def connected(self) -> bool:
        return self._connected and time.monotonic() - self._scan_timestamp < SCAN_STALE_AFTER_S

    def set_front_sector(self, width_deg: float) -> None:
        self._front_sector_deg = width_deg

    # -- data access -------------------------------------------------------

    def scan(self) -> LidarScan | None:
        with self._lock:
            if self._scan_timestamp == 0.0:
                return None
            return LidarScan(list(self._distances), self._scan_timestamp)

    def min_distance_in_sector(self, center_deg: float, width_deg: float) -> float | None:
        current = self.scan()
        if current is None or time.monotonic() - current.timestamp > SCAN_STALE_AFTER_S:
            return None
        return current.min_distance_in_sector(center_deg, width_deg)

    # -- worker ------------------------------------------------------------

    def _run(self) -> None:
        buffer = bytearray()
        while self._running:
            if self._serial is None and not self._open_serial():
                time.sleep(2.0)
                continue
            try:
                chunk = self._serial.read(PACKET_SIZE * 4)
            except Exception:
                logger.warning("LiDAR-Leseverbindung verloren — neuer Versuch")
                self._close_serial()
                continue
            if chunk:
                buffer.extend(chunk)
                self._consume_buffer(buffer)
            self._maybe_render_preview()

    def _consume_buffer(self, buffer: bytearray) -> None:
        while True:
            start = buffer.find(bytes([PACKET_HEADER]))
            if start < 0:
                buffer.clear()
                return
            if start > 0:
                del buffer[:start]
            if len(buffer) < PACKET_SIZE:
                return
            points = parse_packet(bytes(buffer[:PACKET_SIZE]))
            if points is None:
                del buffer[0]
                continue
            del buffer[:PACKET_SIZE]
            now = time.monotonic()
            with self._lock:
                for angle, distance in points:
                    idx = int((angle + self.angle_offset_deg) % 360.0)
                    self._distances[idx] = distance
                self._scan_timestamp = now

    def _open_serial(self) -> bool:
        try:
            import serial

            self._serial = serial.Serial(self.port, self.baud, timeout=0.2)
            self._connected = True
            logger.info("LiDAR verbunden: %s @ %s", self.port, self.baud)
            return True
        except Exception as exc:
            if self._connected or self._serial is None:
                logger.warning("LiDAR nicht erreichbar (%s): %s", self.port, exc)
            self._connected = False
            self._serial = None
            return False

    def _close_serial(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self._connected = False

    # -- preview rendering ---------------------------------------------------

    def _maybe_render_preview(self) -> None:
        if not self.preview_path:
            return
        now = time.monotonic()
        if now - self._last_preview < self.preview_interval_s:
            return
        self._last_preview = now
        scan = self.scan()
        if scan is None:
            return
        try:
            jpeg = render_scan_image(
                scan.distances,
                range_m=self.preview_range_m,
                front_sector_deg=self._front_sector_deg,
            )
            self.preview_path.write_bytes(jpeg)
        except Exception:
            logger.exception("LiDAR-Vorschaubild konnte nicht geschrieben werden")


def render_scan_image(
    distances: list[float],
    size: int = 400,
    range_m: float = 4.0,
    front_sector_deg: float = 60.0,
) -> bytes:
    """Render a top-down scan view (robot centered, front pointing up) as JPEG."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (size, size), (16, 20, 26))
    draw = ImageDraw.Draw(img)
    center = size / 2.0
    scale = (size / 2.0 - 10) / max(range_m, 0.1)

    # Range rings every meter
    ring = 1.0
    while ring <= range_m:
        r = ring * scale
        draw.ellipse(
            [center - r, center - r, center + r, center + r],
            outline=(45, 55, 70),
        )
        draw.text((center + r - 18, center + 4), f"{ring:.0f}m", fill=(90, 105, 125))
        ring += 1.0

    # Front sector wedge (0 deg = up)
    half = front_sector_deg / 2.0
    r_max = range_m * scale
    draw.pieslice(
        [center - r_max, center - r_max, center + r_max, center + r_max],
        start=-90 - half,
        end=-90 + half,
        fill=(28, 38, 34),
    )

    # Scan points: sensor angles grow clockwise, 0 deg = front/up
    for deg in range(360):
        d = distances[deg]
        if d < MIN_VALID_DISTANCE_M or d > range_m:
            continue
        rad = math.radians(deg)
        x = center + math.sin(rad) * d * scale
        y = center - math.cos(rad) * d * scale
        in_front = deg <= half or deg >= 360 - half
        color = (255, 120, 90) if in_front and d <= range_m else (120, 220, 160)
        draw.ellipse([x - 1.5, y - 1.5, x + 1.5, y + 1.5], fill=color)

    # Robot marker (triangle pointing up)
    draw.polygon(
        [(center, center - 8), (center - 6, center + 6), (center + 6, center + 6)],
        fill=(240, 240, 240),
    )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
