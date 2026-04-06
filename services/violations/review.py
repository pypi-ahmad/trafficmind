"""Minimal explicit review actions for violation incidents."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.db.enums import ViolationStatus
from apps.api.app.db.models import ViolationEvent
from apps.api.app.services.errors import NotFoundError


async def apply_violation_review_action(
    session: AsyncSession,
    violation_id,
    *,
    actor: str,
    action: str,
    note: str | None,
) -> ViolationEvent:
    violation = await session.scalar(select(ViolationEvent).where(ViolationEvent.id == violation_id))
    if violation is None:
        raise NotFoundError("Violation event not found.")

    violation.status = (
        ViolationStatus.CONFIRMED if action == "approve" else ViolationStatus.DISMISSED
    )
    violation.reviewed_by = actor
    violation.reviewed_at = datetime.now(UTC)
    violation.review_note = note
    if violation.assigned_to is None:
        violation.assigned_to = actor

    await session.flush()
    await session.refresh(violation)
    return violation
