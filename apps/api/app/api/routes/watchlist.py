"""Watchlist CRUD and match-check endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from apps.api.app.api.access import enforce_route_permissions
from apps.api.app.api.dependencies import DbSession
from apps.api.app.db.enums import WatchlistEntryStatus, WatchlistReason
from apps.api.app.schemas.domain import (
    WatchlistCheckResult,
    WatchlistEntryCreate,
    WatchlistEntryListResult,
    WatchlistEntryRead,
    WatchlistEntryUpdate,
)
from services.access_control.policy import AccessPermission
from services.anpr.watchlist import (
    check_watchlist,
    create_watchlist_entry,
    delete_watchlist_entry,
    get_watchlist_entry,
    list_watchlist_entries,
    update_watchlist_entry,
)
from services.evidence.schemas import EvidenceAccessRole
from services.ocr.normalizer import normalize_plate_text

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.post("/", response_model=WatchlistEntryRead, status_code=status.HTTP_201_CREATED)
async def create_entry(
    db: DbSession,
    body: WatchlistEntryCreate,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for watchlist management authorization",
    ),
) -> WatchlistEntryRead:
    """Add a plate to the watchlist."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_WATCHLISTS],
        resource="watchlist",
        action="create watchlist entry",
        audit_details={"added_by": body.added_by},
    )
    try:
        entry = await create_watchlist_entry(
            db,
            plate_text=body.plate_text,
            reason=body.reason,
            description=body.description,
            added_by=body.added_by,
            expires_at=body.expires_at,
            alert_enabled=body.alert_enabled,
            country_code=body.country_code,
            notes=body.notes,
        )
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        error_status = status.HTTP_409_CONFLICT if "already exists" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=error_status, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A watchlist entry for this normalized plate and reason already exists",
        ) from exc
    return WatchlistEntryRead.model_validate(entry)


@router.get("/", response_model=WatchlistEntryListResult)
async def list_entries(
    db: DbSession,
    entry_status: WatchlistEntryStatus | None = Query(None, alias="status"),
    reason: WatchlistReason | None = Query(None),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for watchlist management authorization",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> WatchlistEntryListResult:
    """List watchlist entries with optional filters."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_WATCHLISTS],
        resource="watchlist",
        action="list watchlist entries",
    )
    items, total = await list_watchlist_entries(
        db, status=entry_status, reason=reason, limit=limit, offset=offset,
    )
    return WatchlistEntryListResult(
        items=[WatchlistEntryRead.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/check", response_model=WatchlistCheckResult)
async def check_plate(
    db: DbSession,
    plate_text: str = Query(..., description="Plate text to check against watchlist"),
    country_code: str | None = Query(None, max_length=8),
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for watchlist management authorization",
    ),
) -> WatchlistCheckResult:
    """Check if a plate is on the active watchlist."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_WATCHLISTS],
        resource="watchlist",
        action="check watchlist",
        audit_details={"country_code": country_code},
    )
    normalized = normalize_plate_text(plate_text, country_code=country_code)
    if not normalized:
        return WatchlistCheckResult(matched=False, normalized_plate_text="", entries=[])
    entries = await check_watchlist(db, normalized)
    return WatchlistCheckResult(
        matched=len(entries) > 0,
        normalized_plate_text=normalized,
        entries=[WatchlistEntryRead.model_validate(e) for e in entries],
    )


@router.get("/{entry_id}", response_model=WatchlistEntryRead)
async def get_entry(
    db: DbSession,
    entry_id: uuid.UUID,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for watchlist management authorization",
    ),
) -> WatchlistEntryRead:
    """Fetch a single watchlist entry."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_WATCHLISTS],
        resource="watchlist",
        action="get watchlist entry",
        entity_id=str(entry_id),
    )
    entry = await get_watchlist_entry(db, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist entry not found")
    return WatchlistEntryRead.model_validate(entry)


@router.patch("/{entry_id}", response_model=WatchlistEntryRead)
async def update_entry(
    db: DbSession,
    entry_id: uuid.UUID,
    body: WatchlistEntryUpdate,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for watchlist management authorization",
    ),
) -> WatchlistEntryRead:
    """Update a watchlist entry."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_WATCHLISTS],
        resource="watchlist",
        action="update watchlist entry",
        entity_id=str(entry_id),
    )
    kwargs: dict = {}
    for field_name in body.model_fields_set:
        kwargs[field_name] = getattr(body, field_name)

    try:
        entry = await update_watchlist_entry(db, entry_id, **kwargs)
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist entry not found")
        await db.commit()
    except ValueError as exc:
        await db.rollback()
        error_status = status.HTTP_409_CONFLICT if "already exists" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=error_status, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A watchlist entry for this normalized plate and reason already exists",
        ) from exc
    return WatchlistEntryRead.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    db: DbSession,
    entry_id: uuid.UUID,
    access_role: EvidenceAccessRole = Query(
        EvidenceAccessRole.OPERATOR,
        description="Caller role for watchlist management authorization",
    ),
) -> None:
    """Remove a watchlist entry."""
    enforce_route_permissions(
        role=access_role,
        required_permissions=[AccessPermission.MANAGE_WATCHLISTS],
        resource="watchlist",
        action="delete watchlist entry",
        entity_id=str(entry_id),
    )
    deleted = await delete_watchlist_entry(db, entry_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist entry not found")
    await db.commit()
