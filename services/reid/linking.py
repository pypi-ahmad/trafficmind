"""Conservative entity-link planning for confirmed re-id matches."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from services.reid.schemas import (
    EntityLinkAction,
    EntityLinkPlan,
    MatchDecision,
    ReIdMatchStatus,
    Sighting,
)


def canonical_pair_key(sighting_a_id: uuid.UUID, sighting_b_id: uuid.UUID) -> str:
    """Return a stable canonical key for an unordered sighting pair."""

    first, second = sorted((str(sighting_a_id), str(sighting_b_id)))
    return f"{first}:{second}"


def plan_entity_link(
    sighting_a: Sighting,
    sighting_b: Sighting,
    decision: MatchDecision,
    *,
    entity_id_factory: Callable[[], uuid.UUID] | None = None,
) -> EntityLinkPlan:
    """Return a conservative plan for updating cross-camera entity links."""

    if decision.new_status is not ReIdMatchStatus.CONFIRMED:
        return EntityLinkPlan(
            action=EntityLinkAction.NO_LINK,
            sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
            reason="candidate was not confirmed",
        )

    if sighting_a.subject_type != sighting_b.subject_type:
        return EntityLinkPlan(
            action=EntityLinkAction.REQUIRES_MANUAL_REVIEW,
            sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
            reason="candidate links different subject types",
        )

    if sighting_a.camera_id == sighting_b.camera_id:
        return EntityLinkPlan(
            action=EntityLinkAction.REQUIRES_MANUAL_REVIEW,
            sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
            reason="candidate links sightings from the same camera",
        )

    if sighting_a.entity_id and sighting_b.entity_id:
        if sighting_a.entity_id == sighting_b.entity_id:
            return EntityLinkPlan(
                action=EntityLinkAction.ALREADY_LINKED,
                entity_id=sighting_a.entity_id,
                sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
                reason="both sightings already belong to the same entity",
            )
        return EntityLinkPlan(
            action=EntityLinkAction.REQUIRES_MANUAL_REVIEW,
            sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
            conflicting_entity_ids=[sighting_a.entity_id, sighting_b.entity_id],
            reason="confirmed candidate bridges two existing entities",
        )

    if sighting_a.entity_id or sighting_b.entity_id:
        existing_entity_id = sighting_a.entity_id or sighting_b.entity_id
        return EntityLinkPlan(
            action=EntityLinkAction.ATTACH_TO_ENTITY,
            entity_id=existing_entity_id,
            sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
            reason="attach the unlinked sighting to the existing entity",
        )

    factory = entity_id_factory or uuid.uuid4
    return EntityLinkPlan(
        action=EntityLinkAction.CREATE_NEW_ENTITY,
        entity_id=factory(),
        sighting_ids=[sighting_a.sighting_id, sighting_b.sighting_id],
        reason="create a new cross-camera entity for the confirmed match",
    )