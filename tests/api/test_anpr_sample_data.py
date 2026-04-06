from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.anpr.search import search_plates
from services.ocr.normalizer import normalize_plate_text

from tests.fixtures.sample_data import (
    load_json_fixture,
    make_sqlite_session_factory,
    seed_camera,
    seed_detection_event,
    seed_plate_read,
)


def test_plate_normalization_sample_data() -> None:
    fixture = load_json_fixture("critical_logic/anpr.json")
    for case in fixture["normalization_cases"]:
        assert normalize_plate_text(case["raw_text"], country_code=case.get("country_code")) == case["expected"]


@pytest.mark.asyncio
async def test_plate_search_sample_data() -> None:
    fixture = load_json_fixture("critical_logic/anpr.json")
    session_factory, engine = await make_sqlite_session_factory()
    occurred_at = datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        camera = await seed_camera(session)
        for record in fixture["search_records"]:
            detection_event_id = None
            if record.get("track_id"):
                detection_event = await seed_detection_event(
                    session,
                    camera,
                    track_id=record["track_id"],
                    occurred_at=occurred_at,
                )
                detection_event_id = detection_event.id
            await seed_plate_read(
                session,
                camera,
                record["plate_text"],
                occurred_at=occurred_at,
                country_code=record.get("country_code"),
                region_code=record.get("region_code"),
                detection_event_id=detection_event_id,
            )
        await session.commit()

    async with session_factory() as session:
        for query in fixture["search_queries"]:
            _items, total = await search_plates(session, **query["params"])
            assert total == query["expected_total"], query["name"]

    await engine.dispose()