"""V1 API router — aggregates all route modules."""

from __future__ import annotations

from fastapi import APIRouter

from apps.api.app.api.routes import (
    access,
    alerts,
    analytics,
    cameras,
    events,
    exports,
    health,
    jobs,
    junctions,
    model_registry,
    observability,
    plates,
    signals,
    violations,
    watchlist,
)

v1_router = APIRouter()

v1_router.include_router(access.router)
v1_router.include_router(health.router)
v1_router.include_router(cameras.router)
v1_router.include_router(cameras.stream_router)
v1_router.include_router(junctions.router)
v1_router.include_router(analytics.router)
v1_router.include_router(events.router)
v1_router.include_router(violations.router)
v1_router.include_router(jobs.router)
v1_router.include_router(plates.router)
v1_router.include_router(watchlist.router)
v1_router.include_router(observability.router)
v1_router.include_router(signals.router)
v1_router.include_router(alerts.router)
v1_router.include_router(exports.router)
v1_router.include_router(model_registry.router)
