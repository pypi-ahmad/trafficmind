from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services.evidence.service import build_violation_evidence_manifest

from tests.fixtures.sample_data import load_json_fixture, make_sqlite_session_factory, seed_evidence_incident


@pytest.mark.asyncio
async def test_violation_evidence_manifest_sample_data() -> None:
    fixture = load_json_fixture("critical_logic/evidence.json")
    session_factory, engine = await make_sqlite_session_factory()

    async with session_factory() as session:
        violation_id, _ = await seed_evidence_incident(
            session,
            occurred_at=datetime(2026, 4, 5, 14, 30, tzinfo=timezone.utc),
        )
        await session.commit()

    async with session_factory() as session:
        manifest = await build_violation_evidence_manifest(session, violation_id, storage_namespace="review")
        await session.commit()

        assert manifest.manifest.selection_policy.selection_reason == fixture["selection_reason"]
        assert [item.frame_index for item in manifest.manifest.timeline.selected_frames] == fixture["expected_selected_frames"]
        assert [asset.asset_kind.value for asset in manifest.manifest.assets] == fixture["expected_asset_kinds"]
        assert manifest.manifest.timeline.clip_window.start_frame_index == fixture["expected_clip_window"]["start_frame_index"]
        assert manifest.manifest.timeline.clip_window.end_frame_index == fixture["expected_clip_window"]["end_frame_index"]

    await engine.dispose()