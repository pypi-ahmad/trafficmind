"""TrafficMind vision service — model-backed object detection for traffic scenes."""

from services.vision.config import VisionSettings
from services.vision.interface import Detector, DetectorRegistry
from services.vision.schemas import BBox, Detection, DetectionResult

__all__ = [
    "BBox",
    "Detection",
    "DetectionResult",
    "Detector",
    "DetectorRegistry",
    "VisionSettings",
]
