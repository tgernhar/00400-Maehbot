"""Tests for mock vision pipeline."""

from vision.camera import MockCamera
from vision.detector import MockDetector
from vision.pipeline import VisionPipeline


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
