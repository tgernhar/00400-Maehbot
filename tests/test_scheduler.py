"""Tests for spray timing."""

from spray.scheduler import compute_travel_ms, compute_fire_at_ms, SprayScheduler


def test_travel_ms_default_geometry():
    # 20mm at 100mm/s = 200ms
    assert compute_travel_ms(20, 100) == 200.0


def test_fire_at_ms():
    fire = compute_fire_at_ms(
        1000.0, spray_delay_ms=50, camera_to_nozzle_mm=20, mower_speed_mm_s=100
    )
    assert fire == 1000.0 + 50 + 200.0


def test_scheduler_update():
    s = SprayScheduler(0, 20, 100)
    s.update(spray_delay_ms=10)
    assert s.schedule_fire_at(0) == 10 + 200
