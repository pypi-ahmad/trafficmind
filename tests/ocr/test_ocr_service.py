"""Tests for the OCR / ANPR foundation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import CameraStatus, PlateReadStatus, WatchlistReason
from apps.api.app.db.models import Camera, WatchlistAlert
from services.anpr.watchlist import create_watchlist_entry
from services.ocr.config import OcrSettings
from services.ocr.interface import OcrEngine, OcrEngineRegistry
from services.ocr.normalizer import normalize_plate_text, register_country_formatter
from services.ocr.persistence import plate_result_to_orm_kwargs, save_plate_read
from services.ocr.pipeline import read_plate, run_ocr
from services.ocr.schemas import OcrContext, OcrDomain, OcrResult, PlateOcrResult
from services.vision.schemas import BBox

# ---------------------------------------------------------------------------
# Stub engine for unit tests (no PaddleOCR dependency)
# ---------------------------------------------------------------------------


class _StubEngine(OcrEngine):
    """Returns configurable results for tests."""

    def __init__(self, settings: OcrSettings, *, results: list[OcrResult] | None = None) -> None:
        self._settings = settings
        self._results = results or []
        self.last_context: OcrContext | None = None

    def recognize(
        self,
        image: np.ndarray,
        *,
        context: OcrContext | None = None,
    ) -> list[OcrResult]:
        self.last_context = context
        return self._results


def _make_stub_engine(
    *texts_and_confs: tuple[str, float],
    settings: OcrSettings | None = None,
) -> _StubEngine:
    settings = settings or OcrSettings(backend="stub")
    results = [
        OcrResult(
            recognized_text=text,
            confidence=conf,
            bbox=BBox(x1=0, y1=0, x2=100, y2=30),
            domain=OcrDomain.PLATE,
        )
        for text, conf in texts_and_confs
    ]
    return _StubEngine(settings, results=results)


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_ocr_result_frozen_with_metadata() -> None:
    r = OcrResult(
        recognized_text="ABC123",
        confidence=0.95,
        bbox=BBox(x1=1, y1=2, x2=3, y2=4),
        domain=OcrDomain.PLATE,
        raw_metadata={"engine": "test"},
    )
    assert r.recognized_text == "ABC123"
    assert r.domain == OcrDomain.PLATE
    assert r.raw_metadata["engine"] == "test"


def test_plate_ocr_result_to_plate_read_dict() -> None:
    ts = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    r = PlateOcrResult(
        raw_text="ABC 1234",
        normalized_text="ABC1234",
        confidence=0.91,
        bbox=BBox(x1=10, y1=5, x2=120, y2=35),
        crop_bbox=BBox(x1=2, y1=1, x2=112, y2=31),
        country_code="SA",
        region_code="RIY",
        crop_image_path="/crops/plate.jpg",
        timestamp=ts,
        raw_metadata={"engine": "stub"},
    )
    d = r.to_plate_read_dict()
    assert d["plate_text"] == "ABC 1234"
    assert d["normalized_plate_text"] == "ABC1234"
    assert d["confidence"] == 0.91
    assert d["country_code"] == "SA"
    assert d["region_code"] == "RIY"
    assert d["crop_image_uri"] == "/crops/plate.jpg"
    assert d["occurred_at"] is ts
    assert d["bbox"]["x1"] == 10
    assert d["ocr_metadata"]["engine"] == "stub"
    assert d["ocr_metadata"]["crop_bbox"]["x1"] == 2


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------


def test_normalize_strips_whitespace_and_punctuation() -> None:
    assert normalize_plate_text("  ABC - 1234  ") == "ABC1234"


def test_normalize_unicode_fullwidth() -> None:
    assert normalize_plate_text("ＡＢＣ１２３") == "ABC123"


def test_normalize_preserves_non_latin_letters() -> None:
    assert normalize_plate_text("АВС 123") == "АВС123"


def test_normalize_canonicalizes_arabic_indic_digits() -> None:
    assert normalize_plate_text("ABC١٢٣") == "ABC123"


def test_normalize_empty_after_cleaning() -> None:
    assert normalize_plate_text("---") == ""


def test_normalize_with_country_code_passthrough() -> None:
    result = normalize_plate_text("ABC1234", country_code="SA")
    assert result == "ABC1234"


def test_register_custom_country_formatter() -> None:
    register_country_formatter("XX", lambda t: t[::-1])
    assert normalize_plate_text("ABC123", country_code="XX") == "321CBA"
    # Clean up
    register_country_formatter("XX", lambda t: t)


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_ocr_settings_defaults() -> None:
    s = OcrSettings()
    assert s.backend == "paddleocr"
    assert 0.0 <= s.confidence_threshold <= 1.0
    assert s.max_plate_length > s.min_plate_length


def test_ocr_settings_gpu_can_be_disabled_explicitly() -> None:
    s = OcrSettings(use_gpu=False)
    assert s.resolve_use_gpu() is False


def test_ocr_settings_gpu_resolution_uses_paddle_cuda_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakePaddleDevice:
        @staticmethod
        def is_compiled_with_cuda() -> bool:
            return True

    class _FakePaddle:
        device = _FakePaddleDevice()

    import sys

    monkeypatch.setitem(sys.modules, "paddle", _FakePaddle())
    s = OcrSettings(use_gpu=True)
    assert s.resolve_use_gpu() is True
    assert s.resolve_device() == "gpu:0"


def test_ocr_settings_device_explicit_overrides_auto_detection() -> None:
    s = OcrSettings(device="cpu")
    assert s.resolve_device() == "cpu"
    assert s.resolve_use_gpu() is False


def test_ocr_settings_device_gpu_explicit() -> None:
    s = OcrSettings(device="gpu:1")
    assert s.resolve_device() == "gpu:1"
    assert s.resolve_use_gpu() is True


def test_ocr_settings_reject_invalid_length_bounds() -> None:
    with pytest.raises(ValueError, match="min_plate_length"):
        OcrSettings(min_plate_length=10, max_plate_length=5)


# ---------------------------------------------------------------------------
# Interface / Registry tests
# ---------------------------------------------------------------------------


def test_registry_advertises_paddleocr_without_import() -> None:
    import sys

    sys.modules.pop("services.ocr.backends.paddle_engine", None)
    assert "paddleocr" in OcrEngineRegistry.available()


def test_registry_register_and_create_custom_backend() -> None:
    OcrEngineRegistry.register("stub_test", _StubEngine)
    settings = OcrSettings(backend="stub_test")
    engine = OcrEngineRegistry.create("stub_test", settings)
    assert isinstance(engine, _StubEngine)


# ---------------------------------------------------------------------------
# Pipeline tests
# ---------------------------------------------------------------------------


def test_run_ocr_passes_context_to_engine() -> None:
    engine = _make_stub_engine(("ABC123", 0.90))
    settings = OcrSettings(backend="stub")
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    results = run_ocr(
        fake_image,
        engine=engine,
        settings=settings,
        context=OcrContext(domain=OcrDomain.PLATE, country_code="SA", region_code="RIY"),
    )

    assert len(results) == 1
    assert engine.last_context is not None
    assert engine.last_context.country_code == "SA"
    assert engine.last_context.region_code == "RIY"


def test_run_ocr_applies_final_confidence_filter() -> None:
    engine = _make_stub_engine(("ABC123", 0.49), settings=OcrSettings(backend="stub"))
    settings = OcrSettings(backend="stub", confidence_threshold=0.5)
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    results = run_ocr(fake_image, engine=engine, settings=settings)

    assert results == []


def test_run_ocr_translates_crop_bbox_to_source_space() -> None:
    engine = _make_stub_engine(("ABC123", 0.90))
    settings = OcrSettings(backend="stub")
    full_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    source_bbox = BBox(x1=100, y1=200, x2=300, y2=260)

    results = run_ocr(full_frame, bbox=source_bbox, engine=engine, settings=settings)

    assert len(results) == 1
    assert results[0].bbox == BBox(x1=100, y1=200, x2=200, y2=230)
    assert results[0].raw_metadata["crop_bbox"]["x1"] == 0


def test_run_ocr_rejects_non_intersecting_bbox() -> None:
    engine = _make_stub_engine(("ABC123", 0.90))
    settings = OcrSettings(backend="stub")
    full_frame = np.zeros((10, 10, 3), dtype=np.uint8)

    with pytest.raises(ValueError, match="bbox"):
        run_ocr(
            full_frame,
            bbox=BBox(x1=20, y1=20, x2=30, y2=30),
            engine=engine,
            settings=settings,
        )


def test_read_plate_returns_normalized_result() -> None:
    engine = _make_stub_engine(("ABC 1234", 0.92))
    settings = OcrSettings(backend="stub", default_country_code="SA")
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    result = read_plate(fake_image, engine=engine, settings=settings)

    assert result is not None
    assert result.raw_text == "ABC 1234"
    assert result.normalized_text == "ABC1234"
    assert result.confidence == 0.92
    assert result.country_code == "SA"


def test_read_plate_skips_below_min_length() -> None:
    engine = _make_stub_engine(("A", 0.95))
    settings = OcrSettings(backend="stub", min_plate_length=2)
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    result = read_plate(fake_image, engine=engine, settings=settings)
    assert result is None


def test_read_plate_skips_above_max_length() -> None:
    engine = _make_stub_engine(("ABCDEFGHIJ1234567890", 0.95))
    settings = OcrSettings(backend="stub", max_plate_length=15)
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    result = read_plate(fake_image, engine=engine, settings=settings)
    assert result is None


def test_read_plate_returns_none_for_empty_ocr() -> None:
    engine = _make_stub_engine()
    settings = OcrSettings(backend="stub")
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    result = read_plate(fake_image, engine=engine, settings=settings)
    assert result is None


def test_read_plate_with_bbox_crops_image() -> None:
    engine = _make_stub_engine(("XYZ9876", 0.88))
    settings = OcrSettings(backend="stub")
    full_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    bbox = BBox(x1=100, y1=200, x2=300, y2=260)

    result = read_plate(full_frame, bbox=bbox, engine=engine, settings=settings)

    assert result is not None
    assert result.normalized_text == "XYZ9876"
    assert result.bbox == BBox(x1=100, y1=200, x2=200, y2=230)
    assert result.crop_bbox == BBox(x1=0, y1=0, x2=100, y2=30)


def test_read_plate_picks_best_valid_candidate() -> None:
    """When the best-confidence hit fails normalisation, falls through to the next."""
    engine = _make_stub_engine(
        ("---", 0.99),       # high confidence but normalises to empty
        ("AB1234", 0.85),    # lower confidence but valid
    )
    settings = OcrSettings(backend="stub")
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    result = read_plate(fake_image, engine=engine, settings=settings)

    assert result is not None
    assert result.normalized_text == "AB1234"
    assert result.confidence == 0.85


def test_read_plate_carries_metadata_through() -> None:
    engine = _make_stub_engine(("ABC123", 0.90))
    ts = datetime(2026, 4, 4, 14, 0, 0, tzinfo=timezone.utc)
    settings = OcrSettings(backend="stub")
    fake_image = np.zeros((60, 200, 3), dtype=np.uint8)

    result = read_plate(
        fake_image,
        engine=engine,
        settings=settings,
        region_code="DXB",
        frame_index=42,
        timestamp=ts,
        crop_image_path="/crops/42.jpg",
        source_frame_path="/frames/42.jpg",
    )

    assert result is not None
    assert result.frame_index == 42
    assert result.timestamp == ts
    assert result.region_code == "DXB"
    assert result.crop_image_path == "/crops/42.jpg"
    assert result.source_frame_path == "/frames/42.jpg"


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------


def test_plate_result_to_orm_kwargs_structure() -> None:
    ts = datetime(2026, 4, 4, 12, 0, 0, tzinfo=timezone.utc)
    result = PlateOcrResult(
        raw_text="ABC 1234",
        normalized_text="ABC1234",
        confidence=0.91,
        bbox=BBox(x1=10, y1=5, x2=120, y2=35),
        country_code="SA",
        region_code="RIY",
        timestamp=ts,
        raw_metadata={"engine": "stub"},
    )
    cam_id = uuid.uuid4()
    det_id = uuid.uuid4()

    kwargs = plate_result_to_orm_kwargs(
        result, camera_id=cam_id, detection_event_id=det_id
    )

    assert kwargs["camera_id"] is cam_id
    assert kwargs["detection_event_id"] is det_id
    assert kwargs["plate_text"] == "ABC 1234"
    assert kwargs["normalized_plate_text"] == "ABC1234"
    assert kwargs["occurred_at"] is ts
    assert kwargs["region_code"] == "RIY"
    assert kwargs["ocr_metadata"]["engine"] == "stub"


def test_plate_result_to_orm_kwargs_defaults_timestamp() -> None:
    result = PlateOcrResult(
        raw_text="XY99",
        normalized_text="XY99",
        confidence=0.80,
    )
    kwargs = plate_result_to_orm_kwargs(result, camera_id=uuid.uuid4())
    assert kwargs["occurred_at"] is not None


async def _make_persistence_session_factory() -> tuple[async_sessionmaker, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def _seed_camera(session) -> Camera:
    camera = Camera(
        camera_code=f"OCR-{uuid.uuid4().hex[:8]}",
        name="OCR Camera",
        location_name="OCR Test",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    session.add(camera)
    await session.flush()
    return camera


@pytest.mark.asyncio
async def test_save_plate_read_marks_match_and_creates_watchlist_alert() -> None:
    session_factory, engine = await _make_persistence_session_factory()

    async with session_factory() as session:
        camera = await _seed_camera(session)
        await create_watchlist_entry(
            session,
            plate_text="ABC 1234",
            reason=WatchlistReason.STOLEN,
            description="Reported stolen vehicle",
        )
        result = PlateOcrResult(
            raw_text="ABC 1234",
            normalized_text="ABC1234",
            confidence=0.94,
            timestamp=datetime.now(timezone.utc),
        )

        plate_read = await save_plate_read(session, result, camera_id=camera.id)
        await session.commit()

        assert plate_read.status == PlateReadStatus.MATCHED
        assert plate_read.ocr_metadata["watchlist_match_count"] == 1
        assert plate_read.ocr_metadata["watchlist_alert_count"] == 1

        alerts = list((await session.execute(select(WatchlistAlert))).scalars().all())
        assert len(alerts) == 1
        assert alerts[0].reason == WatchlistReason.STOLEN
        assert alerts[0].normalized_plate_text == "ABC1234"

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_plate_read_respects_alert_enabled_false() -> None:
    session_factory, engine = await _make_persistence_session_factory()

    async with session_factory() as session:
        camera = await _seed_camera(session)
        await create_watchlist_entry(
            session,
            plate_text="VIP 001",
            reason=WatchlistReason.VIP,
            alert_enabled=False,
        )
        result = PlateOcrResult(
            raw_text="VIP 001",
            normalized_text="VIP001",
            confidence=0.90,
            timestamp=datetime.now(timezone.utc),
        )

        plate_read = await save_plate_read(session, result, camera_id=camera.id)
        await session.commit()

        assert plate_read.status == PlateReadStatus.MATCHED
        assert plate_read.ocr_metadata["watchlist_match_count"] == 1
        assert plate_read.ocr_metadata["watchlist_alert_count"] == 0

        alerts = list((await session.execute(select(WatchlistAlert))).scalars().all())
        assert alerts == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_plate_read_can_skip_watchlist_matching() -> None:
    session_factory, engine = await _make_persistence_session_factory()

    async with session_factory() as session:
        camera = await _seed_camera(session)
        await create_watchlist_entry(
            session,
            plate_text="OFF 123",
            reason=WatchlistReason.BOLO,
        )
        result = PlateOcrResult(
            raw_text="OFF 123",
            normalized_text="OFF123",
            confidence=0.88,
            timestamp=datetime.now(timezone.utc),
        )

        plate_read = await save_plate_read(
            session,
            result,
            camera_id=camera.id,
            match_watchlist=False,
        )
        await session.commit()

        assert plate_read.status == PlateReadStatus.OBSERVED

        alerts = list((await session.execute(select(WatchlistAlert))).scalars().all())
        assert alerts == []

    await engine.dispose()
