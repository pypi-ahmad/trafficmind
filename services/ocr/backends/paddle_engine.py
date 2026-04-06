"""PaddleOCR-backed OCR engine scaffold.

This backend delegates to PaddleOCR for text recognition.  When
``paddleocr`` is not installed it raises a clear error on
``load_model()``.  The scaffold is designed so that replacing it with
a fine-tuned PaddleOCR model (or a different engine entirely) requires
no changes outside this file.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from services.ocr.config import OcrSettings
from services.ocr.interface import OcrEngine
from services.ocr.schemas import OcrContext, OcrDomain, OcrResult
from services.vision.schemas import BBox

logger = logging.getLogger(__name__)


class PaddleOcrEngine(OcrEngine):
    """OCR engine backed by PaddlePaddle / PaddleOCR.

    Call ``load_model()`` (or use as a context manager) before
    ``recognize()``.  The engine is **not** thread-safe — instantiate
    one per worker.
    """

    def __init__(self, settings: OcrSettings) -> None:
        self._settings = settings
        self._engine: Any | None = None

    def load_model(self) -> None:
        if self._engine is not None:
            return

        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]
        except ImportError as exc:
            msg = (
                "PaddleOCR is not installed.  Install it with:\n"
                "  pip install paddlepaddle paddleocr"
            )
            raise ImportError(msg) from exc

        resolved_use_gpu = self._settings.resolve_use_gpu()
        if self._settings.use_gpu and not resolved_use_gpu:
            logger.warning(
                "OCR GPU was requested, but the installed Paddle runtime has no CUDA support; falling back to CPU."
            )

        kwargs: dict[str, Any] = {
            "use_angle_cls": True,
            "lang": self._settings.language,
            "use_gpu": resolved_use_gpu,
            "show_log": False,
        }
        if self._settings.model_dir is not None:
            kwargs["det_model_dir"] = str(self._settings.model_dir / "det")
            kwargs["rec_model_dir"] = str(self._settings.model_dir / "rec")
            kwargs["cls_model_dir"] = str(self._settings.model_dir / "cls")

        self._engine = PaddleOCR(**kwargs)
        logger.info("PaddleOCR engine loaded (gpu=%s)", resolved_use_gpu)

    def unload(self) -> None:
        self._engine = None

    def recognize(
        self,
        image: np.ndarray,
        *,
        context: OcrContext | None = None,
    ) -> list[OcrResult]:
        if self._engine is None:
            msg = "PaddleOCR engine not loaded — call load_model() first."
            raise RuntimeError(msg)

        if context is None:
            context = OcrContext(domain=OcrDomain.GENERIC)

        raw_results = self._engine.ocr(image, cls=True)
        if not raw_results or not raw_results[0]:
            return []

        ocr_results: list[OcrResult] = []
        for line in raw_results[0]:
            box_coords, (text, conf) = line
            if conf < self._settings.confidence_threshold:
                continue

            bbox = self._paddle_box_to_bbox(box_coords)
            ocr_results.append(
                OcrResult(
                    recognized_text=text,
                    confidence=round(conf, 4),
                    bbox=bbox,
                    domain=context.domain,
                    raw_metadata={
                        "paddle_box": box_coords,
                        "language": self._settings.language,
                        "country_code": context.country_code,
                        "region_code": context.region_code,
                        "language_hints": list(context.language_hints),
                    },
                )
            )

        ocr_results.sort(key=lambda r: r.confidence, reverse=True)
        return ocr_results

    @staticmethod
    def _paddle_box_to_bbox(box: list[list[float]]) -> BBox:
        """Convert PaddleOCR's 4-point polygon to axis-aligned BBox."""
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        return BBox(x1=min(xs), y1=min(ys), x2=max(xs), y2=max(ys))
