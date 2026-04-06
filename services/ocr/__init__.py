"""TrafficMind OCR / ANPR service package."""

from services.ocr.config import OcrSettings
from services.ocr.interface import OcrEngine, OcrEngineRegistry
from services.ocr.normalizer import normalize_plate_text, register_country_formatter
from services.ocr.pipeline import read_plate, run_ocr
from services.ocr.schemas import OcrContext, OcrDomain, OcrResult, PlateOcrResult

__all__ = [
    "OcrContext",
    "OcrDomain",
    "OcrEngine",
    "OcrEngineRegistry",
    "OcrResult",
    "OcrSettings",
    "PlateOcrResult",
    "normalize_plate_text",
    "read_plate",
    "register_country_formatter",
    "run_ocr",
]
