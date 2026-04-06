"""Small local demo for the OCR / ANPR pipeline.

Runs the plate-OCR pipeline against a synthetic plate image to exercise
the full contract: engine → normalize → PlateOcrResult → persistence dict.

Uses a stub OCR engine so it works without PaddleOCR installed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from services.ocr.config import OcrSettings
from services.ocr.interface import OcrEngine, OcrEngineRegistry
from services.ocr.pipeline import read_plate
from services.ocr.schemas import OcrContext, OcrDomain, OcrResult
from services.vision.schemas import BBox


class StubPlateEngine(OcrEngine):
    """Fake engine that returns a hard-coded plate string — for demos/tests."""

    def __init__(self, settings: OcrSettings) -> None:
        self._settings = settings

    def recognize(
        self,
        image: np.ndarray,
        *,
        context: OcrContext | None = None,
    ) -> list[OcrResult]:
        if context is None:
            context = OcrContext(domain=OcrDomain.GENERIC)
        return [
            OcrResult(
                recognized_text="ABC 1234",
                confidence=0.92,
                bbox=BBox(x1=10, y1=5, x2=120, y2=35),
                domain=context.domain,
            ),
            OcrResult(
                recognized_text="???",
                confidence=0.15,
                bbox=BBox(x1=0, y1=0, x2=30, y2=10),
                domain=context.domain,
            ),
        ]


def main() -> None:
    # Register stub so the pipeline can find it
    OcrEngineRegistry.register("stub", StubPlateEngine)

    settings = OcrSettings(backend="stub", confidence_threshold=0.5, default_country_code="SA")

    # Synthetic 200x60 grey image (simulates a plate crop)
    fake_crop = np.full((60, 200, 3), 180, dtype=np.uint8)

    result = read_plate(
        fake_crop,
        settings=settings,
        frame_index=42,
        timestamp=datetime(2026, 4, 4, 14, 30, 0, tzinfo=timezone.utc),
        crop_image_path="/crops/frame42_plate.jpg",
    )

    if result is None:
        print("No plate recognized.")
        return

    print("--- Plate OCR Result ---")
    print(f"  raw_text        : {result.raw_text!r}")
    print(f"  normalized_text : {result.normalized_text!r}")
    print(f"  confidence      : {result.confidence}")
    print(f"  country_code    : {result.country_code}")
    print(f"  region_code     : {result.region_code}")
    print(f"  bbox            : {result.bbox}")
    print(f"  frame_index     : {result.frame_index}")
    print(f"  timestamp       : {result.timestamp}")
    print()

    print("--- PlateRead ORM dict ---")
    orm_dict = result.to_plate_read_dict()
    for key, value in sorted(orm_dict.items()):
        print(f"  {key:30s}: {value!r}")

    # Also show the full pipeline with bbox-based crop
    print("\n--- Pipeline with bbox crop from full frame ---")
    full_frame = np.full((480, 640, 3), 120, dtype=np.uint8)
    result2 = read_plate(
        full_frame,
        bbox=BBox(x1=100, y1=200, x2=300, y2=260),
        settings=settings,
        frame_index=99,
        timestamp=datetime(2026, 4, 4, 14, 31, 0, tzinfo=timezone.utc),
    )
    if result2:
        print(f"  normalized: {result2.normalized_text!r}  conf: {result2.confidence}")


if __name__ == "__main__":
    main()
