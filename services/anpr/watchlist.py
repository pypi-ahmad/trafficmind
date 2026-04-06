"""Watchlist management service.

Handles CRUD operations for watchlist entries and provides a fast
check for whether a given normalized plate is on the watchlist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from apps.api.app.db.enums import (
    PlateReadStatus,
    WatchlistAlertStatus,
    WatchlistEntryStatus,
    WatchlistReason,
)
from apps.api.app.db.models import PlateRead, WatchlistAlert, WatchlistEntry
from services.ocr.normalizer import normalize_plate_text

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


def _normalize_watchlist_plate_text(
    plate_text: str,
    country_code: str | None,
) -> tuple[str, str, str | None]:
    normalized_country_code = country_code.upper() if country_code else None
    normalized_plate_text = normalize_plate_text(plate_text, country_code=normalized_country_code)
    if not normalized_plate_text:
        msg = "Plate text is empty after normalization"
        raise ValueError(msg)
    return normalized_plate_text, plate_text.strip(), normalized_country_code


async def _watchlist_entry_exists(
    session: AsyncSession,
    *,
    normalized_plate_text: str,
    reason: WatchlistReason,
    exclude_entry_id: uuid.UUID | None = None,
) -> bool:
    query = select(WatchlistEntry.id).where(
        WatchlistEntry.normalized_plate_text == normalized_plate_text,
        WatchlistEntry.reason == reason,
    )
    if exclude_entry_id is not None:
        query = query.where(WatchlistEntry.id != exclude_entry_id)
    return await session.scalar(query) is not None


async def create_watchlist_entry(
    session: AsyncSession,
    *,
    plate_text: str,
    reason: WatchlistReason,
    description: str | None = None,
    added_by: str | None = None,
    expires_at: datetime | None = None,
    alert_enabled: bool = True,
    country_code: str | None = None,
    notes: str | None = None,
) -> WatchlistEntry:
    """Create a new watchlist entry, normalizing the plate text."""
    normalized, plate_text_display, normalized_country_code = _normalize_watchlist_plate_text(
        plate_text,
        country_code,
    )
    if await _watchlist_entry_exists(
        session,
        normalized_plate_text=normalized,
        reason=reason,
    ):
        msg = "A watchlist entry for this normalized plate and reason already exists"
        raise ValueError(msg)

    entry = WatchlistEntry(
        normalized_plate_text=normalized,
        plate_text_display=plate_text_display,
        reason=reason,
        status=WatchlistEntryStatus.ACTIVE,
        description=description,
        added_by=added_by,
        expires_at=expires_at,
        alert_enabled=alert_enabled,
        country_code=normalized_country_code,
        notes=notes,
    )
    session.add(entry)
    await session.flush()
    return entry


async def update_watchlist_entry(
    session: AsyncSession,
    entry_id: uuid.UUID,
    *,
    plate_text: str | None = None,
    country_code: str | None = ...,  # type: ignore[assignment]
    reason: WatchlistReason | None = None,
    status: WatchlistEntryStatus | None = None,
    description: str | None = ...,  # type: ignore[assignment]
    expires_at: datetime | None = ...,  # type: ignore[assignment]
    alert_enabled: bool | None = None,
    notes: str | None = ...,  # type: ignore[assignment]
) -> WatchlistEntry | None:
    """Update fields on an existing watchlist entry.

    Uses sentinel ``...`` for nullable fields to distinguish "not provided"
    from "set to None".
    """
    result = await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    )
    entry = result.scalars().first()
    if entry is None:
        return None

    target_plate_text = plate_text if plate_text is not None else entry.plate_text_display
    target_country_code = entry.country_code if country_code is ... else country_code
    target_reason = reason if reason is not None else entry.reason

    should_recompute_plate = plate_text is not None or country_code is not ...
    if should_recompute_plate:
        normalized_plate_text, plate_text_display, normalized_country_code = _normalize_watchlist_plate_text(
            target_plate_text,
            target_country_code,
        )
    else:
        normalized_plate_text = entry.normalized_plate_text
        plate_text_display = entry.plate_text_display
        normalized_country_code = entry.country_code

    if should_recompute_plate or reason is not None:
        if await _watchlist_entry_exists(
            session,
            normalized_plate_text=normalized_plate_text,
            reason=target_reason,
            exclude_entry_id=entry.id,
        ):
            msg = "A watchlist entry for this normalized plate and reason already exists"
            raise ValueError(msg)

    if should_recompute_plate:
        entry.normalized_plate_text = normalized_plate_text
        entry.plate_text_display = plate_text_display
        entry.country_code = normalized_country_code

    if reason is not None:
        entry.reason = reason
    if status is not None:
        entry.status = status
    if description is not ...:
        entry.description = description
    if expires_at is not ...:
        entry.expires_at = expires_at
    if alert_enabled is not None:
        entry.alert_enabled = alert_enabled
    if notes is not ...:
        entry.notes = notes

    await session.flush()
    await session.refresh(entry)
    return entry


async def get_watchlist_entry(
    session: AsyncSession,
    entry_id: uuid.UUID,
) -> WatchlistEntry | None:
    """Fetch a single watchlist entry by ID."""
    result = await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    )
    return result.scalars().first()


async def list_watchlist_entries(
    session: AsyncSession,
    *,
    status: WatchlistEntryStatus | None = None,
    reason: WatchlistReason | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[WatchlistEntry], int]:
    """List watchlist entries with optional status/reason filter."""
    base = select(WatchlistEntry)
    count_q = select(func.count()).select_from(WatchlistEntry)

    if status is not None:
        base = base.where(WatchlistEntry.status == status)
        count_q = count_q.where(WatchlistEntry.status == status)

    if reason is not None:
        base = base.where(WatchlistEntry.reason == reason)
        count_q = count_q.where(WatchlistEntry.reason == reason)

    base = base.order_by(WatchlistEntry.created_at.desc())
    total = (await session.scalar(count_q)) or 0
    items_q = base.limit(limit).offset(offset)
    result = await session.execute(items_q)
    items = list(result.scalars().all())
    return items, total


async def delete_watchlist_entry(
    session: AsyncSession,
    entry_id: uuid.UUID,
) -> bool:
    """Delete a watchlist entry. Returns True if deleted, False if not found."""
    result = await session.execute(
        select(WatchlistEntry).where(WatchlistEntry.id == entry_id)
    )
    entry = result.scalars().first()
    if entry is None:
        return False
    await session.delete(entry)
    await session.flush()
    return True


async def check_watchlist(
    session: AsyncSession,
    normalized_plate_text: str,
) -> list[WatchlistEntry]:
    """Check if a plate is on the active watchlist.

    Returns all active, non-expired entries matching the normalized plate.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(WatchlistEntry).where(
            WatchlistEntry.normalized_plate_text == normalized_plate_text,
            WatchlistEntry.status == WatchlistEntryStatus.ACTIVE,
            (WatchlistEntry.expires_at.is_(None)) | (WatchlistEntry.expires_at > now),
        )
    )
    return list(result.scalars().all())


async def create_watchlist_alerts_for_plate_read(
    session: AsyncSession,
    plate_read: PlateRead,
    *,
    emit_alerts: bool = True,
) -> list[WatchlistAlert]:
    """Apply watchlist matching to a persisted plate read.

    The plate read is promoted to ``MATCHED`` when an active watchlist
    entry exists. When ``emit_alerts`` is enabled, one alert row is created
    per matching watchlist entry with ``alert_enabled=True``.
    """
    if not plate_read.normalized_plate_text:
        return []

    matches = await check_watchlist(session, plate_read.normalized_plate_text)
    if not matches:
        return []

    plate_read.status = PlateReadStatus.MATCHED

    existing_result = await session.execute(
        select(WatchlistAlert.watchlist_entry_id).where(WatchlistAlert.plate_read_id == plate_read.id)
    )
    existing_entry_ids = {
        entry_id
        for entry_id in existing_result.scalars().all()
        if entry_id is not None
    }

    alerts: list[WatchlistAlert] = []
    if emit_alerts:
        for entry in matches:
            if not entry.alert_enabled or entry.id in existing_entry_ids:
                continue
            alert = WatchlistAlert(
                plate_read_id=plate_read.id,
                watchlist_entry_id=entry.id,
                camera_id=plate_read.camera_id,
                status=WatchlistAlertStatus.OPEN,
                occurred_at=plate_read.occurred_at,
                normalized_plate_text=plate_read.normalized_plate_text,
                plate_text=plate_read.plate_text,
                reason=entry.reason,
                description=entry.description,
                alert_metadata={
                    "watchlist_entry_status": entry.status.value,
                    "watchlist_country_code": entry.country_code,
                },
            )
            session.add(alert)
            alerts.append(alert)

    metadata = dict(plate_read.ocr_metadata or {})
    metadata["watchlist_match_count"] = len(matches)
    metadata["watchlist_alert_count"] = len(alerts)
    plate_read.ocr_metadata = metadata

    await session.flush()
    return alerts
