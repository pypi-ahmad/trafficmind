from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from apps.api.app.db.enums import ReIdMatchStatus, ReIdSubjectType
from apps.api.app.db.models import ReIdMatch, ReIdSighting
from services.reid.linking import canonical_pair_key
from tests.fixtures.sample_data import (
    make_sqlite_session_factory,
    seed_camera,
    seed_detection_event,
)


def _bbox() -> dict[str, float]:
    return {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}


@pytest.mark.asyncio
async def test_reid_sighting_can_anchor_to_detection_event():
    session_factory, engine = await make_sqlite_session_factory()
    occurred_at = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            camera = await seed_camera(session)
            detection_event = await seed_detection_event(
                session,
                camera,
                track_id="trk-001",
                occurred_at=occurred_at,
            )
            sighting = ReIdSighting(
                camera_id=camera.id,
                track_id="trk-001",
                subject_type=ReIdSubjectType.VEHICLE,
                representative_detection_event_id=detection_event.id,
                first_seen_at=occurred_at,
                last_seen_at=occurred_at + timedelta(seconds=5),
                embedding_vector=[0.1, 0.2, 0.3, 0.4],
                embedding_model="test-model",
                bbox_snapshot=_bbox(),
                reid_metadata={},
            )

            session.add(sighting)
            await session.commit()
            await session.refresh(sighting)

            assert sighting.representative_detection_event_id == detection_event.id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reid_sighting_natural_key_prevents_duplicate_ingest():
    session_factory, engine = await make_sqlite_session_factory()
    occurred_at = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            camera = await seed_camera(session)
            first = ReIdSighting(
                camera_id=camera.id,
                track_id="trk-dup",
                subject_type=ReIdSubjectType.VEHICLE,
                first_seen_at=occurred_at,
                last_seen_at=occurred_at + timedelta(seconds=5),
                embedding_vector=[0.1, 0.2, 0.3, 0.4],
                embedding_model="test-model",
                bbox_snapshot=_bbox(),
                reid_metadata={},
            )
            second = ReIdSighting(
                camera_id=camera.id,
                track_id="trk-dup",
                subject_type=ReIdSubjectType.VEHICLE,
                first_seen_at=occurred_at,
                last_seen_at=occurred_at + timedelta(seconds=10),
                embedding_vector=[0.4, 0.3, 0.2, 0.1],
                embedding_model="test-model",
                bbox_snapshot=_bbox(),
                reid_metadata={},
            )

            session.add(first)
            await session.commit()

            session.add(second)
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reid_match_pair_key_blocks_reversed_duplicates():
    session_factory, engine = await make_sqlite_session_factory()
    occurred_at = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            camera_a = await seed_camera(session, camera_code="CAM-A")
            camera_b = await seed_camera(session, camera_code="CAM-B")

            sighting_a = ReIdSighting(
                camera_id=camera_a.id,
                track_id="trk-a",
                subject_type=ReIdSubjectType.VEHICLE,
                first_seen_at=occurred_at,
                last_seen_at=occurred_at + timedelta(seconds=5),
                embedding_vector=[0.1, 0.2, 0.3, 0.4],
                embedding_model="test-model",
                bbox_snapshot=_bbox(),
                reid_metadata={},
            )
            sighting_b = ReIdSighting(
                camera_id=camera_b.id,
                track_id="trk-b",
                subject_type=ReIdSubjectType.VEHICLE,
                first_seen_at=occurred_at + timedelta(seconds=30),
                last_seen_at=occurred_at + timedelta(seconds=35),
                embedding_vector=[0.4, 0.3, 0.2, 0.1],
                embedding_model="test-model",
                bbox_snapshot=_bbox(),
                reid_metadata={},
            )
            session.add_all([sighting_a, sighting_b])
            await session.commit()
            await session.refresh(sighting_a)
            await session.refresh(sighting_b)

            pair_key = canonical_pair_key(sighting_a.id, sighting_b.id)
            first_match = ReIdMatch(
                sighting_a_id=sighting_a.id,
                sighting_b_id=sighting_b.id,
                pair_key=pair_key,
                similarity_score=0.95,
                status=ReIdMatchStatus.CANDIDATE,
                proposed_at=occurred_at,
                reid_metadata={},
            )
            session.add(first_match)
            await session.commit()

            reversed_match = ReIdMatch(
                sighting_a_id=sighting_b.id,
                sighting_b_id=sighting_a.id,
                pair_key=canonical_pair_key(sighting_b.id, sighting_a.id),
                similarity_score=0.95,
                status=ReIdMatchStatus.CANDIDATE,
                proposed_at=occurred_at,
                reid_metadata={},
            )
            session.add(reversed_match)
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()
