"""Signal classifier interface, HSV backend, and registry.

Architecture follows the same pattern as ``services.vision.interface``
(Detector / DetectorRegistry): an abstract base, a concrete backend, and a
name → factory map so callers never import backends directly.
"""

from __future__ import annotations

import abc
import importlib
import logging
from typing import TYPE_CHECKING

import cv2
import numpy as np

from services.signals.schemas import SignalClassification, SignalColor

if TYPE_CHECKING:
    from services.signals.config import SignalSettings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class SignalClassifier(abc.ABC):
    """Classify a traffic-light crop into a ``SignalColor``."""

    @abc.abstractmethod
    def classify(self, crop: np.ndarray) -> SignalClassification:
        """Run colour classification on a BGR crop of a traffic-light bbox.

        Args:
            crop: HWC numpy array (BGR, OpenCV convention).

        Returns:
            ``SignalClassification`` with the winning colour and confidence.
        """

    def load(self) -> None:
        """Optional resource allocation (model load, etc.)."""

    def unload(self) -> None:
        """Optional resource cleanup."""

    def __enter__(self) -> SignalClassifier:
        self.load()
        return self

    def __exit__(self, *_: object) -> None:
        self.unload()


# ---------------------------------------------------------------------------
# HSV histogram classifier — no ML model required, works out of the box
# ---------------------------------------------------------------------------


class HsvHistogramClassifier(SignalClassifier):
    """Classify traffic-light colour by HSV pixel voting.

    How it works:
      1. Convert crop to HSV.
      2. Mask out dim / desaturated pixels (likely background or housing).
      3. Count pixels in red-, yellow-, and green-hue bands.
      4. Winner-take-all with confidence = winner_ratio.

    **Limitations (be honest):**
    - Works best on crops that tightly frame the active lamp.
    - Struggles in heavy glare, night-time washout, or heavily occluded heads.
    - Does not distinguish arrow shapes or dual-aspect signals.
    - Accuracy depends on the upstream detector delivering clean bounding boxes.
    """

    def __init__(self, settings: SignalSettings) -> None:
        self._settings = settings

    def classify(self, crop: np.ndarray) -> SignalClassification:
        h, w = crop.shape[:2]
        if h < self._settings.min_crop_pixels or w < self._settings.min_crop_pixels:
            return SignalClassification(
                color=SignalColor.UNKNOWN, confidence=0.0, color_scores={},
            )

        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0]
        sat = hsv[:, :, 1]
        val = hsv[:, :, 2]

        # Mask: keep bright, saturated pixels
        bright_mask = (sat >= self._settings.hsv_saturation_floor) & (
            val >= self._settings.hsv_value_floor
        )
        if not np.any(bright_mask):
            return SignalClassification(
                color=SignalColor.UNKNOWN, confidence=0.0, color_scores={},
            )

        hue_masked = hue[bright_mask]

        # Count pixels per colour band
        red_count = 0
        for lo, hi in self._settings.hsv_red_hue_ranges:
            red_count += int(np.count_nonzero((hue_masked >= lo) & (hue_masked <= hi)))
        ylo, yhi = self._settings.hsv_yellow_hue_range
        yellow_count = int(np.count_nonzero((hue_masked >= ylo) & (hue_masked <= yhi)))
        glo, ghi = self._settings.hsv_green_hue_range
        green_count = int(np.count_nonzero((hue_masked >= glo) & (hue_masked <= ghi)))

        total = red_count + yellow_count + green_count
        if total == 0:
            return SignalClassification(
                color=SignalColor.UNKNOWN, confidence=0.0, color_scores={},
            )

        scores = {
            "red": red_count / total,
            "yellow": yellow_count / total,
            "green": green_count / total,
        }

        winner = max(scores, key=scores.get)  # type: ignore[arg-type]
        confidence = scores[winner]

        if confidence < self._settings.confidence_threshold:
            return SignalClassification(
                color=SignalColor.UNKNOWN, confidence=confidence, color_scores=scores,
            )

        return SignalClassification(
            color=SignalColor(winner),
            confidence=round(confidence, 4),
            color_scores={k: round(v, 4) for k, v in scores.items()},
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class SignalClassifierRegistry:
    """Name → classifier-factory registry."""

    _backends: dict[str, type[SignalClassifier]] = {}
    _lazy_backends: dict[str, str] = {}

    @classmethod
    def register(cls, name: str, backend_cls: type[SignalClassifier]) -> None:
        cls._backends[name] = backend_cls

    @classmethod
    def register_lazy(cls, name: str, import_path: str) -> None:
        cls._lazy_backends[name] = import_path

    @classmethod
    def _resolve_backend(cls, name: str) -> type[SignalClassifier]:
        if name in cls._backends:
            return cls._backends[name]
        if name not in cls._lazy_backends:
            available = ", ".join(cls.available()) or "(none)"
            msg = f"Unknown signal classifier backend {name!r}. Available: {available}"
            raise KeyError(msg)

        module_path, _, attr_name = cls._lazy_backends[name].partition(":")
        if not module_path or not attr_name:
            msg = f"Invalid lazy import path for {name!r}: {cls._lazy_backends[name]!r}"
            raise ValueError(msg)

        module = importlib.import_module(module_path)
        backend_cls = getattr(module, attr_name)
        if not isinstance(backend_cls, type) or not issubclass(backend_cls, SignalClassifier):
            msg = f"Lazy backend {name!r} did not resolve to a SignalClassifier subclass."
            raise TypeError(msg)

        cls._backends[name] = backend_cls
        return backend_cls

    @classmethod
    def create(cls, name: str, settings: SignalSettings) -> SignalClassifier:
        return cls._resolve_backend(name)(settings)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(set(cls._backends) | set(cls._lazy_backends))


# Register the built-in HSV backend
SignalClassifierRegistry.register("hsv_histogram", HsvHistogramClassifier)
