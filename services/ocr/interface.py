"""OCR engine interface and backend registry."""

from __future__ import annotations

import abc
import importlib
from typing import TYPE_CHECKING

import numpy as np

from services.ocr.schemas import OcrContext, OcrResult

if TYPE_CHECKING:
    from services.ocr.config import OcrSettings


class OcrEngine(abc.ABC):
    """Abstract OCR engine backend.

    Lifecycle mirrors ``Detector``:
        1. ``__init__`` receives ``OcrSettings`` and stores config.
        2. ``load_model`` allocates resources / loads weights.
        3. ``recognize`` runs OCR on an image crop.
        4. ``unload`` frees resources.

    The ``domain`` hint lets backend implementations adjust pre-processing
    or model selection (e.g. plate-specific vs. generic text).
    """

    @abc.abstractmethod
    def recognize(
        self,
        image: np.ndarray,
        *,
        context: OcrContext | None = None,
    ) -> list[OcrResult]:
        """Run OCR on *image* and return recognized text regions.

        Parameters
        ----------
        image:
            BGR uint8 image crop (OpenCV convention).
        context:
            Optional request context describing the OCR domain, locale,
            frame metadata, and source bounding box.

        Returns
        -------
        list[OcrResult]
            One entry per recognized text region, ordered by confidence
            descending.  May be empty if nothing was recognized.
        """

    def load_model(self) -> None:
        """Load model weights / warm up the engine (optional override)."""

    def unload(self) -> None:
        """Release GPU / model resources (optional override)."""

    def __enter__(self) -> OcrEngine:
        self.load_model()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.unload()


class OcrEngineRegistry:
    """Name → OCR engine backend registry."""

    _backends: dict[str, type[OcrEngine]] = {}
    _lazy_backends: dict[str, str] = {
        "paddleocr": "services.ocr.backends.paddle_engine:PaddleOcrEngine",
    }

    @classmethod
    def register(cls, name: str, backend_cls: type[OcrEngine]) -> None:
        cls._backends[name] = backend_cls

    @classmethod
    def register_lazy(cls, name: str, import_path: str) -> None:
        cls._lazy_backends[name] = import_path

    @classmethod
    def _resolve_backend(cls, name: str) -> type[OcrEngine]:
        if name in cls._backends:
            return cls._backends[name]
        if name not in cls._lazy_backends:
            available = ", ".join(cls.available()) or "(none)"
            msg = f"Unknown OCR backend {name!r}. Available: {available}"
            raise KeyError(msg)

        module_path, _, attr_name = cls._lazy_backends[name].partition(":")
        if not module_path or not attr_name:
            msg = f"Invalid lazy OCR backend path for {name!r}: {cls._lazy_backends[name]!r}"
            raise ValueError(msg)

        module = importlib.import_module(module_path)
        backend_cls = getattr(module, attr_name)
        if not isinstance(backend_cls, type) or not issubclass(backend_cls, OcrEngine):
            msg = f"Lazy OCR backend {name!r} did not resolve to an OcrEngine subclass."
            raise TypeError(msg)

        cls._backends[name] = backend_cls
        return backend_cls

    @classmethod
    def create(cls, name: str, settings: OcrSettings) -> OcrEngine:
        return cls._resolve_backend(name)(settings)

    @classmethod
    def available(cls) -> list[str]:
        return sorted(set(cls._backends) | set(cls._lazy_backends))
