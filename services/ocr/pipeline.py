"""Plate OCR pipeline — the primary API for downstream consumers.

Usage::

    from services.ocr.pipeline import read_plate

    result = read_plate(crop_image, settings=settings, country_code="SA")
    if result is not None:
        print(result.normalized_text, result.confidence)
        row = result.to_plate_read_dict()

The pipeline:
    1. Accepts an image crop (numpy BGR) or a full frame + bbox region.
    2. Runs the configured OCR engine.
    3. Picks the best candidate above the confidence threshold.
    4. Normalises plate text.
    5. Validates length constraints.
    6. Returns a ``PlateOcrResult`` or ``None``.
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

from services.ocr.config import OcrSettings, get_ocr_settings
from services.ocr.interface import OcrEngine, OcrEngineRegistry
from services.ocr.normalizer import normalize_plate_text
from services.ocr.schemas import OcrContext, OcrDomain, OcrResult, PlateOcrResult
from services.vision.schemas import BBox

logger = logging.getLogger(__name__)


def run_ocr(
    image: np.ndarray,
    *,
    bbox: BBox | None = None,
    engine: OcrEngine | None = None,
    settings: OcrSettings | None = None,
    context: OcrContext | None = None,
) -> list[OcrResult]:
    """Run generic OCR on an image or one sub-region.

    This is the reusable foundation for future road-sign or scene-text OCR.
    Plate-specific logic lives in ``read_plate`` on top of this function.
    """
    if settings is None:
        settings = get_ocr_settings()

    base_context = context or OcrContext()
    requested_bbox = bbox or base_context.source_bbox
    crop, source_bbox = _extract_crop(image, requested_bbox)
    resolved_context = base_context.model_copy(update={"source_bbox": source_bbox})

    own_engine = engine is None
    if own_engine:
        engine = OcrEngineRegistry.create(settings.backend, settings)
        engine.load_model()

    assert engine is not None
    try:
        raw_results = engine.recognize(crop, context=resolved_context)
    finally:
        if own_engine:
            engine.unload()

    resolved_results: list[OcrResult] = []
    for result in raw_results:
        if result.confidence < settings.confidence_threshold:
            continue
        resolved_results.append(_translate_result_to_source_space(result, source_bbox))

    resolved_results.sort(key=lambda item: item.confidence, reverse=True)
    return resolved_results


def read_plate(
    image: np.ndarray,
    *,
    bbox: BBox | None = None,
    engine: OcrEngine | None = None,
    settings: OcrSettings | None = None,
    country_code: str | None = None,
    region_code: str | None = None,
    frame_index: int | None = None,
    timestamp: datetime | None = None,
    crop_image_path: str | None = None,
    source_frame_path: str | None = None,
) -> PlateOcrResult | None:
    """Run the plate-OCR pipeline on an image or crop.

    Parameters
    ----------
    image:
        Full frame (when *bbox* is given) or pre-cropped plate region.
    bbox:
        If provided, the plate region is cropped from *image* first.
    engine:
        Pre-initialised OCR engine.  When ``None``, one is created from
        *settings* (or the global default) and loaded on-the-fly.
    settings:
        OCR configuration.  Falls back to ``get_ocr_settings()``.
    country_code:
        ISO 3166-1 alpha-2 hint forwarded to the normaliser.
        Falls back to ``settings.default_country_code``.
    frame_index / timestamp / crop_image_path / source_frame_path:
        Optional context carried through to the result.

    Returns
    -------
    PlateOcrResult | None
        Structured result, or ``None`` when nothing usable was recognised.
    """
    if settings is None:
        settings = get_ocr_settings()

    country = country_code or settings.default_country_code
    context = OcrContext(
        domain=OcrDomain.PLATE,
        country_code=country,
        region_code=region_code,
        frame_index=frame_index,
        timestamp=timestamp,
        crop_image_path=crop_image_path,
        source_frame_path=source_frame_path,
        source_bbox=bbox,
    )
    ocr_results = run_ocr(
        image,
        bbox=bbox,
        engine=engine,
        settings=settings,
        context=context,
    )

    if not ocr_results:
        return None

    # Pick best candidate that passes normalisation + length check
    for candidate in ocr_results:
        normalized = normalize_plate_text(candidate.recognized_text, country_code=country)
        if not normalized:
            continue
        if len(normalized) < settings.min_plate_length:
            continue
        if len(normalized) > settings.max_plate_length:
            continue

        crop_bbox = _metadata_bbox(candidate.raw_metadata.get("crop_bbox"))
        return PlateOcrResult(
            raw_text=candidate.recognized_text,
            normalized_text=normalized,
            confidence=candidate.confidence,
            bbox=candidate.bbox or context.source_bbox,
            crop_bbox=crop_bbox,
            country_code=country,
            region_code=region_code,
            crop_image_path=crop_image_path,
            source_frame_path=source_frame_path,
            frame_index=frame_index,
            timestamp=timestamp,
            raw_metadata=candidate.raw_metadata,
        )

    return None


def _extract_crop(image: np.ndarray, bbox: BBox | None) -> tuple[np.ndarray, BBox | None]:
    """Crop a sub-region from *image* if a bbox is given."""
    if bbox is None:
        return image, None

    h, w = image.shape[:2]
    x1 = max(0, int(bbox.x1))
    y1 = max(0, int(bbox.y1))
    x2 = min(w, int(bbox.x2))
    y2 = min(h, int(bbox.y2))

    if x2 <= x1 or y2 <= y1:
        msg = "bbox does not intersect image bounds"
        raise ValueError(msg)

    resolved_bbox = BBox(x1=x1, y1=y1, x2=x2, y2=y2)
    return image[y1:y2, x1:x2], resolved_bbox


def _translate_result_to_source_space(result: OcrResult, source_bbox: BBox | None) -> OcrResult:
    """Translate crop-local OCR boxes into full-frame coordinates."""
    if source_bbox is None or result.bbox is None:
        return result

    local_bbox = result.bbox
    translated_bbox = BBox(
        x1=source_bbox.x1 + local_bbox.x1,
        y1=source_bbox.y1 + local_bbox.y1,
        x2=source_bbox.x1 + local_bbox.x2,
        y2=source_bbox.y1 + local_bbox.y2,
    )
    raw_metadata = dict(result.raw_metadata)
    raw_metadata.setdefault("crop_bbox", local_bbox.to_dict())
    raw_metadata.setdefault("source_bbox", translated_bbox.to_dict())
    return result.model_copy(update={"bbox": translated_bbox, "raw_metadata": raw_metadata})


def _metadata_bbox(value: object) -> BBox | None:
    if not isinstance(value, dict):
        return None
    required_keys = {"x1", "y1", "x2", "y2"}
    if not required_keys.issubset(value):
        return None
    return BBox(**value)
