"""Tests for the ANPR persistence, search, and watchlist layer."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from apps.api.app.db.base import Base
from apps.api.app.db.enums import (
    CameraStatus,
    DetectionEventType,
    PlateReadStatus,
    WatchlistEntryStatus,
    WatchlistReason,
)
from apps.api.app.db.models import Camera, DetectionEvent, PlateRead
from apps.api.app.db.session import get_db_session
from apps.api.app.main import create_app
from services.anpr.search import get_plate_read, search_plates
from services.anpr.watchlist import (
    check_watchlist,
    create_watchlist_entry,
    delete_watchlist_entry,
    get_watchlist_entry,
    list_watchlist_entries,
    update_watchlist_entry,
)
from services.ocr.normalizer import normalize_plate_text

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False), engine


async def _seed_camera(session) -> Camera:
    camera = Camera(
        camera_code=f"CAM-{uuid.uuid4().hex[:6]}",
        name="Test Camera",
        location_name="Test Location",
        status=CameraStatus.ACTIVE,
        calibration_config={},
    )
    session.add(camera)
    await session.flush()
    return camera


async def _seed_plate_read(
    session,
    camera: Camera,
    plate_text: str,
    *,
    occurred_at: datetime | None = None,
    confidence: float = 0.92,
    country_code: str | None = None,
    region_code: str | None = None,
    status: PlateReadStatus = PlateReadStatus.OBSERVED,
    detection_event_id: uuid.UUID | None = None,
    crop_image_uri: str | None = None,
    source_frame_uri: str | None = None,
) -> PlateRead:
    occurred = occurred_at or datetime.now(timezone.utc)
    normalized = normalize_plate_text(plate_text, country_code=country_code)
    pr = PlateRead(
        camera_id=camera.id,
        status=status,
        occurred_at=occurred,
        plate_text=plate_text,
        normalized_plate_text=normalized,
        confidence=confidence,
        country_code=country_code,
        region_code=region_code,
        detection_event_id=detection_event_id,
        bbox={"x1": 0, "y1": 0, "x2": 100, "y2": 50},
        crop_image_uri=crop_image_uri,
        source_frame_uri=source_frame_uri,
        ocr_metadata={},
    )
    session.add(pr)
    await session.flush()
    return pr


async def _seed_detection_event(
    session,
    camera: Camera,
    *,
    track_id: str | None = None,
    occurred_at: datetime | None = None,
) -> DetectionEvent:
    event = DetectionEvent(
        camera_id=camera.id,
        event_type=DetectionEventType.DETECTION,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        track_id=track_id,
        object_class="car",
        confidence=0.97,
        bbox={"x1": 10, "y1": 20, "x2": 100, "y2": 80},
        event_payload={},
    )
    session.add(event)
    await session.flush()
    return event


# ---------------------------------------------------------------------------
# Normalizer edge-case tests
# ---------------------------------------------------------------------------


class TestNormalizerEdgeCases:
    def test_unicode_fullwidth_becomes_ascii(self):
        assert normalize_plate_text("ＡＢＣ１２３４") == "ABC1234"

    def test_arabic_digits_normalized(self):
        # Arabic-Indic digits U+0660..U+0669
        assert normalize_plate_text("٣٢١٠") == "3210"

    def test_hyphens_dots_stripped(self):
        assert normalize_plate_text("AB-12.34") == "AB1234"

    def test_whitespace_stripped(self):
        assert normalize_plate_text("  AB  1234  ") == "AB1234"

    def test_empty_string_returns_empty(self):
        assert normalize_plate_text("") == ""

    def test_only_punctuation_returns_empty(self):
        assert normalize_plate_text("---...") == ""

    def test_mixed_case_uppercased(self):
        assert normalize_plate_text("abc1234") == "ABC1234"

    def test_country_formatter_passthrough(self):
        # SA formatter is a passthrough
        assert normalize_plate_text("abc1234", country_code="SA") == "ABC1234"


# ---------------------------------------------------------------------------
# Service-layer: plate search
# ---------------------------------------------------------------------------


class TestPlateSearch:
    @pytest.mark.asyncio
    async def test_exact_search_by_normalized_plate(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(session, cam, "ABC 1234")
            await _seed_plate_read(session, cam, "XYZ 9999")
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(session, plate_text="ABC1234")
            assert total == 1
            assert items[0].normalized_plate_text == "ABC1234"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_partial_search_raw_text(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(session, cam, "ABC 1234")
            await _seed_plate_read(session, cam, "ABC 5678")
            await _seed_plate_read(session, cam, "XYZ 9999")
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(
                session, plate_text="ABC", normalized=False, partial=True,
            )
            assert total == 2
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_by_camera_id(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam1 = await _seed_camera(session)
            cam2 = await _seed_camera(session)
            await _seed_plate_read(session, cam1, "AAA1111")
            await _seed_plate_read(session, cam2, "BBB2222")
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(session, camera_id=cam1.id)
            assert total == 1
            assert items[0].normalized_plate_text == "AAA1111"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_by_time_range(self):
        factory, engine = await _make_session_factory()
        now = datetime.now(timezone.utc)
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(session, cam, "OLD1111", occurred_at=now - timedelta(hours=2))
            await _seed_plate_read(session, cam, "NEW2222", occurred_at=now)
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(
                session, occurred_after=now - timedelta(hours=1),
            )
            assert total == 1
            assert items[0].normalized_plate_text == "NEW2222"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_by_min_confidence(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(session, cam, "LOW1111", confidence=0.3)
            await _seed_plate_read(session, cam, "HIGH2222", confidence=0.95)
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(session, min_confidence=0.8)
            assert total == 1
            assert items[0].normalized_plate_text == "HIGH2222"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_by_detection_event_track_and_region(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            event1 = await _seed_detection_event(session, cam, track_id="track-1")
            event2 = await _seed_detection_event(session, cam, track_id="track-2")
            await _seed_plate_read(
                session,
                cam,
                "TRK1111",
                detection_event_id=event1.id,
                region_code="riy",
            )
            await _seed_plate_read(
                session,
                cam,
                "TRK2222",
                detection_event_id=event2.id,
                region_code="dxb",
            )
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(
                session,
                track_id="track-1",
                region_code="RIY",
            )
            assert total == 1
            assert items[0].detection_event_id == event1.id

            items, total = await search_plates(
                session,
                detection_event_id=event2.id,
            )
            assert total == 1
            assert items[0].normalized_plate_text == "TRK2222"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_by_has_evidence(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(
                session,
                cam,
                "EVD1111",
                crop_image_uri="/crops/1.jpg",
            )
            await _seed_plate_read(session, cam, "EVD2222")
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(session, has_evidence=True)
            assert total == 1
            assert items[0].normalized_plate_text == "EVD1111"

            items, total = await search_plates(session, has_evidence=False)
            assert total == 1
            assert items[0].normalized_plate_text == "EVD2222"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_pagination(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            for i in range(5):
                await _seed_plate_read(
                    session, cam, f"PG{i:04d}",
                    occurred_at=datetime.now(timezone.utc) + timedelta(seconds=i),
                )
            await session.commit()

        async with factory() as session:
            items, total = await search_plates(session, limit=2, offset=0)
            assert total == 5
            assert len(items) == 2

            items2, _ = await search_plates(session, limit=2, offset=2)
            assert len(items2) == 2
            # Items are ordered desc by occurred_at, so pages should not overlap
            assert items[0].id != items2[0].id
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_plate_read_by_id(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            pr = await _seed_plate_read(session, cam, "FIND1234")
            await session.commit()
            pr_id = pr.id

        async with factory() as session:
            found = await get_plate_read(session, pr_id)
            assert found is not None
            assert found.normalized_plate_text == "FIND1234"

            missing = await get_plate_read(session, uuid.uuid4())
            assert missing is None
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_empty_normalized_query_returns_nothing(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(session, cam, "ABC1234")
            await session.commit()

        async with factory() as session:
            # "---" normalizes to "", should return empty
            items, total = await search_plates(session, plate_text="---")
            assert total == 0
            assert items == []
        await engine.dispose()


# ---------------------------------------------------------------------------
# Service-layer: watchlist
# ---------------------------------------------------------------------------


class TestWatchlistService:
    @pytest.mark.asyncio
    async def test_create_and_retrieve_entry(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            entry = await create_watchlist_entry(
                session, plate_text="ABC 1234", reason=WatchlistReason.STOLEN,
            )
            await session.commit()
            assert entry.normalized_plate_text == "ABC1234"
            assert entry.plate_text_display == "ABC 1234"

        async with factory() as session:
            found = await get_watchlist_entry(session, entry.id)
            assert found is not None
            assert found.reason == WatchlistReason.STOLEN
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_entry_empty_plate_raises(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            with pytest.raises(ValueError, match="empty after normalization"):
                await create_watchlist_entry(
                    session, plate_text="---", reason=WatchlistReason.STOLEN,
                )
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_update_entry(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            entry = await create_watchlist_entry(
                session, plate_text="UPD1234", reason=WatchlistReason.BOLO,
            )
            await session.commit()
            eid = entry.id

        async with factory() as session:
            updated = await update_watchlist_entry(
                session, eid,
                status=WatchlistEntryStatus.DISABLED,
                notes="Resolved",
            )
            await session.commit()
            assert updated is not None
            assert updated.status == WatchlistEntryStatus.DISABLED
            assert updated.notes == "Resolved"

        async with factory() as session:
            missing = await update_watchlist_entry(session, uuid.uuid4())
            assert missing is None
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_update_entry_can_change_plate_text_and_country_code(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            entry = await create_watchlist_entry(
                session,
                plate_text="abc 1234",
                reason=WatchlistReason.BOLO,
            )
            await session.commit()

        async with factory() as session:
            updated = await update_watchlist_entry(
                session,
                entry.id,
                plate_text="xyz 999",
                country_code="sa",
            )
            await session.commit()
            assert updated is not None
            assert updated.plate_text_display == "xyz 999"
            assert updated.normalized_plate_text == "XYZ999"
            assert updated.country_code == "SA"
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_duplicate_watchlist_entry_rejected(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            await create_watchlist_entry(
                session,
                plate_text="DUP 1234",
                reason=WatchlistReason.STOLEN,
            )

            with pytest.raises(ValueError, match="already exists"):
                await create_watchlist_entry(
                    session,
                    plate_text="dup-1234",
                    reason=WatchlistReason.STOLEN,
                )
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_delete_entry(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            entry = await create_watchlist_entry(
                session, plate_text="DEL1234", reason=WatchlistReason.WANTED,
            )
            await session.commit()
            eid = entry.id

        async with factory() as session:
            assert await delete_watchlist_entry(session, eid) is True
            await session.commit()

        async with factory() as session:
            assert await get_watchlist_entry(session, eid) is None
            assert await delete_watchlist_entry(session, uuid.uuid4()) is False
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_list_entries_with_filters(self):
        factory, engine = await _make_session_factory()
        async with factory() as session:
            await create_watchlist_entry(
                session, plate_text="LST1111", reason=WatchlistReason.STOLEN,
            )
            await create_watchlist_entry(
                session, plate_text="LST2222", reason=WatchlistReason.VIP,
            )
            e3 = await create_watchlist_entry(
                session, plate_text="LST3333", reason=WatchlistReason.STOLEN,
            )
            e3.status = WatchlistEntryStatus.DISABLED
            await session.commit()

        async with factory() as session:
            items, total = await list_watchlist_entries(session)
            assert total == 3

            items, total = await list_watchlist_entries(
                session, reason=WatchlistReason.STOLEN,
            )
            assert total == 2

            items, total = await list_watchlist_entries(
                session, status=WatchlistEntryStatus.ACTIVE,
            )
            assert total == 2
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_check_watchlist_active_non_expired(self):
        factory, engine = await _make_session_factory()
        now = datetime.now(timezone.utc)

        async with factory() as session:
            await create_watchlist_entry(
                session, plate_text="CHK1111", reason=WatchlistReason.STOLEN,
            )
            await create_watchlist_entry(
                session, plate_text="CHK1111", reason=WatchlistReason.BOLO,
                expires_at=now - timedelta(hours=1),  # expired
            )
            e3 = await create_watchlist_entry(
                session, plate_text="CHK1111", reason=WatchlistReason.INVESTIGATION,
            )
            e3.status = WatchlistEntryStatus.DISABLED
            await session.commit()

        async with factory() as session:
            matches = await check_watchlist(session, "CHK1111")
            # Only the first entry is active + non-expired
            assert len(matches) == 1
            assert matches[0].reason == WatchlistReason.STOLEN

            no_match = await check_watchlist(session, "NONEXIST")
            assert len(no_match) == 0
        await engine.dispose()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


async def _make_test_client():
    factory, engine = await _make_session_factory()
    app = create_app()

    async def override_get_db_session() -> AsyncIterator[object]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_get_db_session
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")
    return client, factory, engine


class TestPlateSearchAPI:
    @pytest.mark.asyncio
    async def test_search_plates_endpoint(self):
        client, factory, engine = await _make_test_client()

        # Seed data directly
        async with factory() as session:
            cam = await _seed_camera(session)
            await _seed_plate_read(session, cam, "API1234")
            await _seed_plate_read(session, cam, "API5678")
            await session.commit()

        async with client:
            resp = await client.get("/api/v1/plates/", params={"plate_text": "API1234"})
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["items"][0]["normalized_plate_text"] == "API1234"

            resp = await client.get(
                "/api/v1/plates/",
                params={"plate_text": "API", "partial": "true", "normalized": "false"},
            )
            assert resp.status_code == 200
            assert resp.json()["total"] == 2

            # All plates
            resp = await client.get("/api/v1/plates/")
            assert resp.status_code == 200
            assert resp.json()["total"] == 2

            resp = await client.get(
                "/api/v1/plates/",
                params={"occurred_after": "not-a-date"},
            )
            assert resp.status_code == 422
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_plate_read_endpoint(self):
        client, factory, engine = await _make_test_client()

        async with factory() as session:
            cam = await _seed_camera(session)
            pr = await _seed_plate_read(session, cam, "GET1111")
            await session.commit()
            pr_id = str(pr.id)

        async with client:
            resp = await client.get(f"/api/v1/plates/{pr_id}")
            assert resp.status_code == 200
            assert resp.json()["normalized_plate_text"] == "GET1111"

            # 404 for non-existent
            fake = "00000000-0000-0000-0000-000000000000"
            resp = await client.get(f"/api/v1/plates/{fake}")
            assert resp.status_code == 404
        await engine.dispose()


class TestWatchlistAPI:
    @pytest.mark.asyncio
    async def test_watchlist_requires_manage_permission(self):
        client, factory, engine = await _make_test_client()

        async with client:
            resp = await client.post(
                "/api/v1/watchlist/",
                json={"plate_text": "WL 403", "reason": "stolen"},
            )
            assert resp.status_code == 403
            assert "manage_watchlists" in resp.json()["detail"]
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_watchlist_crud_flow(self):
        client, factory, engine = await _make_test_client()

        async with client:
            # Create
            resp = await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={
                    "plate_text": "WL 1234",
                    "reason": "stolen",
                    "description": "Reported stolen",
                    "added_by": "officer1",
                },
            )
            assert resp.status_code == 201
            entry = resp.json()
            assert entry["normalized_plate_text"] == "WL1234"
            assert entry["reason"] == "stolen"
            entry_id = entry["id"]

            # Read
            resp = await client.get(
                f"/api/v1/watchlist/{entry_id}",
                params={"access_role": "supervisor"},
            )
            assert resp.status_code == 200
            assert resp.json()["id"] == entry_id

            # List
            resp = await client.get("/api/v1/watchlist/", params={"access_role": "supervisor"})
            assert resp.status_code == 200
            assert resp.json()["total"] == 1

            # Update
            resp = await client.patch(
                f"/api/v1/watchlist/{entry_id}",
                params={"access_role": "supervisor"},
                json={"status": "disabled", "notes": "Resolved"},
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "disabled"
            assert resp.json()["notes"] == "Resolved"

            # Delete
            resp = await client.delete(
                f"/api/v1/watchlist/{entry_id}",
                params={"access_role": "supervisor"},
            )
            assert resp.status_code == 204

            # Verify gone
            resp = await client.get(
                f"/api/v1/watchlist/{entry_id}",
                params={"access_role": "supervisor"},
            )
            assert resp.status_code == 404
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_create_watchlist_entry_empty_plate_rejected(self):
        client, factory, engine = await _make_test_client()

        async with client:
            resp = await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "---", "reason": "stolen"},
            )
            assert resp.status_code == 422
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_check_endpoint(self):
        client, factory, engine = await _make_test_client()

        async with client:
            # Add entry
            await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "CHK9999", "reason": "wanted"},
            )

            # Check — match
            resp = await client.get(
                "/api/v1/watchlist/check",
                params={"plate_text": "CHK 9999", "access_role": "supervisor"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["matched"] is True
            assert body["normalized_plate_text"] == "CHK9999"
            assert len(body["entries"]) == 1

            # Check — no match
            resp = await client.get(
                "/api/v1/watchlist/check",
                params={"plate_text": "NOMATCH", "access_role": "supervisor"},
            )
            assert resp.status_code == 200
            assert resp.json()["matched"] is False
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_watchlist_list_with_filters(self):
        client, factory, engine = await _make_test_client()

        async with client:
            await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "FLT1111", "reason": "stolen"},
            )
            await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "FLT2222", "reason": "vip"},
            )

            resp = await client.get(
                "/api/v1/watchlist/",
                params={"reason": "stolen", "access_role": "supervisor"},
            )
            assert resp.status_code == 200
            assert resp.json()["total"] == 1

            resp = await client.get(
                "/api/v1/watchlist/",
                params={"status": "active", "access_role": "supervisor"},
            )
            assert resp.status_code == 200
            assert resp.json()["total"] == 2
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_duplicate_watchlist_create_returns_conflict(self):
        client, factory, engine = await _make_test_client()

        async with client:
            resp = await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "dup 0001", "reason": "wanted"},
            )
            assert resp.status_code == 201

            resp = await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "DUP-0001", "reason": "wanted"},
            )
            assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_watchlist_update_can_change_plate_text(self):
        client, factory, engine = await _make_test_client()

        async with client:
            resp = await client.post(
                "/api/v1/watchlist/",
                params={"access_role": "supervisor"},
                json={"plate_text": "old 123", "reason": "bolo"},
            )
            assert resp.status_code == 201
            entry_id = resp.json()["id"]

            resp = await client.patch(
                f"/api/v1/watchlist/{entry_id}",
                params={"access_role": "supervisor"},
                json={"plate_text": "new 999", "country_code": "ae"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["plate_text_display"] == "new 999"
            assert body["normalized_plate_text"] == "NEW999"
            assert body["country_code"] == "AE"
        await engine.dispose()
