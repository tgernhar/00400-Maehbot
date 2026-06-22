"""Tests for mock vision pipeline."""

from vision.camera import MockCamera
from vision.detector import Detector, MockDetector
from vision.pipeline import VisionPipeline
from maehbot.types import Detection, Frame


class EmptyDetector(Detector):
    def detect(self, frame: Frame) -> list[Detection]:
        return []


def test_mock_detection_pipeline():
    camera = MockCamera()
    detector = MockDetector()
    results: list = []

    def on_det(frame, detections):
        results.extend(detections)

    pipeline = VisionPipeline(camera, detector, on_det)
    pipeline.start()
    for _ in range(5):
        pipeline.process_one()
    pipeline.stop()

    assert len(results) > 0
    assert results[0].class_id == "clover"
    assert results[0].confidence >= 0.75


def test_pipeline_invokes_callback_without_detections():
    camera = MockCamera()
    detector = EmptyDetector()
    calls = 0

    def on_det(_frame, detections):
        nonlocal calls
        calls += 1
        assert detections == []

    pipeline = VisionPipeline(camera, detector, on_det)
    pipeline.start()
    assert pipeline.process_one()
    pipeline.stop()
    assert calls == 1
