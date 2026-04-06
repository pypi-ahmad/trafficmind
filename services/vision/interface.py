"""Detector interface and backend registry.

Every detection backend (YOLO, RT-DETR, custom plate model, etc.) implements
the ``Detector`` protocol.  The ``DetectorRegistry`` is a simple name→factory
map so callers never import backend modules directly.
"""

from __future__ import annotations

import abc
import importlib
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from services.vision.config import VisionSettings
    from services.vision.schemas import DetectionResult


class Detector(abc.ABC):
    """Abstract detector backend.

    Lifecycle:
        1. ``__init__`` receives ``VisionSettings`` and stores config.
        2. ``load_model`` is called once to allocate GPU / load weights.
        3. ``detect`` is called per-frame and returns a ``DetectionResult``.
        4. ``unload`` frees resources (called by context managers / shutdown).

    Subclasses MUST implement ``detect``.
    ``load_model`` and ``unload`` have default no-ops for backends that
    initialise eagerly in ``__init__``.
    """

    @abc.abstractmethod
    def detect(
        self,
        image: np.ndarray,
        *,
        frame_index: int | None = None,
        timestamp: datetime | None = None,
        confidence: float | None = None,
    ) -> DetectionResult:
        """Run inference on a single BGR/RGB numpy image.

        Args:
            image: HWC numpy array (OpenCV convention).
            frame_index: Optional sequential frame number.
            timestamp: Optional source-frame timestamp supplied by the caller.
            confidence: Override per-call confidence threshold.

        Returns:
            ``DetectionResult`` with zero or more ``Detection`` objects.
        """

    def load_model(self) -> None:
        """Load model weights / allocate device memory."""

    def unload(self) -> None:
        """Release model weights / device memory."""

    def __enter__(self) -> Detector:
        self.load_model()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.unload()


class DetectorRegistry:
    """Name → detector-factory registry.

    Usage::

        DetectorRegistry.register("yolo", YoloDetector)
        detector = DetectorRegistry.create("yolo", settings)
    """

    _backends: dict[str, type[Detector]] = {}
    _lazy_backends: dict[str, str] = {
        "yolo": "services.vision.backends.yolo_detector:YoloDetector",
        "plate": "services.vision.backends.plate_detector:PlateDetector",
    }

    @classmethod
    def register(cls, name: str, backend_cls: type[Detector]) -> None:
        cls._backends[name] = backend_cls

    @classmethod
    def register_lazy(cls, name: str, import_path: str) -> None:
        cls._lazy_backends[name] = import_path

    @classmethod
    def _resolve_backend(cls, name: str) -> type[Detector]:
        if name in cls._backends:
            return cls._backends[name]
        if name not in cls._lazy_backends:
            available = ", ".join(cls.available()) or "(none)"
            msg = f"Unknown detector backend {name!r}. Available: {available}"
            raise KeyError(msg)

        module_path, _, attr_name = cls._lazy_backends[name].partition(":")
        if not module_path or not attr_name:
            msg = f"Invalid lazy backend import path for {name!r}: {cls._lazy_backends[name]!r}"
            raise ValueError(msg)

        module = importlib.import_module(module_path)
        backend_cls = getattr(module, attr_name)
        if not isinstance(backend_cls, type) or not issubclass(backend_cls, Detector):
            msg = f"Lazy backend {name!r} did not resolve to a Detector subclass."
            raise TypeError(msg)

        cls._backends[name] = backend_cls
        return backend_cls

    @classmethod
    def create(cls, name: str, settings: VisionSettings) -> Detector:
        return cls._resolve_backend(name)(settings)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(set(cls._backends) | set(cls._lazy_backends))
