"""Hotspot analytics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from apps.api.app.api.dependencies import DbSession
from apps.api.app.schemas.analytics import HotspotAnalyticsRequest, HotspotAnalyticsResponse
from apps.api.app.schemas.evaluation import EvaluationSummaryRead
from apps.api.app.services.evaluation import EvaluationSummaryService
from apps.api.app.services.hotspots import HotspotAnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])

_service = HotspotAnalyticsService()


@router.post("/hotspots", response_model=HotspotAnalyticsResponse)
async def hotspot_analytics(
    db_session: DbSession,
    body: HotspotAnalyticsRequest,
) -> HotspotAnalyticsResponse:
    """Aggregate persisted operational records into hotspot analytics."""
    result = await _service.build_hotspots(db_session, body)
    return HotspotAnalyticsResponse.from_result(body, result)


@router.get("/evaluation", response_model=EvaluationSummaryRead)
async def evaluation_summary(request: Request) -> EvaluationSummaryRead:
    """Return file-backed benchmark and evaluation summaries for the admin UI."""
    settings = request.app.state.settings
    service = EvaluationSummaryService(
        fixture_suite_path=settings.evaluation_fixture_suite_path,
        artifact_dir=settings.evaluation_artifact_dir,
    )
    return service.build_summary()