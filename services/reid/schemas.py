"""Typed result schemas for multi-camera re-identification.

These schemas define the contract for the re-id service layer.  They are
intentionally decoupled from SQLAlchemy models so the service remains an
importable library like ``services.tracking`` and ``services.vision``.

Key concepts
~~~~~~~~~~~~
* **Sighting** — a local track observed on one camera.
* **AppearanceDescriptor** — an embedding vector (or hash) that encodes the
  visual appearance of a tracked object.  The shape and normalisation depend
  on the embedding backend.
* **ReIdCandidate** — a proposed cross-camera match between two sightings.
* **CrossCameraEntity** — a confirmed (or manually approved) identity that
  spans multiple cameras / sightings.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums (canonical source in packages.shared_types.enums; re-exported here)
# ---------------------------------------------------------------------------
from packages.shared_types.enums import ReIdMatchStatus, ReIdSubjectType


class ReIdConfidenceBand(StrEnum):
    """Coarse confidence tier — helps downstream consumers decide how to
    present uncertain matches without relying on a single float threshold."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class AppearanceDescriptor(BaseModel):
    """Embedding vector extracted from a detection crop.

    ``vector`` is stored as a plain list[float] for serialisation safety.
    Backends that need ``numpy`` should convert on the fly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    vector: list[float] = Field(..., min_length=1)
    model_name: str = Field(
        ..., description="Identifier of the embedding model that produced this vector."
    )
    model_version: str = Field(default="unknown")
    norm: float | None = Field(
        default=None, description="L2 norm after normalisation; None if unnormalised."
    )

    @property
    def dimension(self) -> int:
        return len(self.vector)


class Sighting(BaseModel):
    """A single observation of a tracked object on one camera."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sighting_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    camera_id: uuid.UUID
    track_id: str = Field(..., description="Local per-camera track identifier.")
    subject_type: ReIdSubjectType
    entity_id: uuid.UUID | None = Field(
        default=None,
        description="Cross-camera entity id once the sighting has been linked.",
    )
    first_seen_at: datetime
    last_seen_at: datetime
    embedding: AppearanceDescriptor | None = Field(
        default=None, description="May be absent if embedding extraction failed."
    )
    bbox_snapshot: dict[str, float] | None = Field(
        default=None,
        description="Representative bbox {x1, y1, x2, y2} (e.g. best-confidence frame).",
    )
    image_uri: str | None = Field(
        default=None, description="URI to a representative crop image."
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReIdCandidate(BaseModel):
    """Proposed match between two sightings across cameras."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    sighting_a_id: uuid.UUID
    sighting_b_id: uuid.UUID
    subject_type: ReIdSubjectType
    camera_a_id: uuid.UUID
    camera_b_id: uuid.UUID
    entity_a_id: uuid.UUID | None = None
    entity_b_id: uuid.UUID | None = None
    similarity_score: float = Field(
        ..., ge=0.0, le=1.0, description="Cosine similarity or equivalent metric."
    )
    confidence_band: ReIdConfidenceBand
    status: ReIdMatchStatus = ReIdMatchStatus.CANDIDATE
    proposed_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = Field(
        default=None, description="System component or human reviewer."
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class CrossCameraEntity(BaseModel):
    """A confirmed cross-camera identity that unifies multiple sightings."""

    model_config = ConfigDict(extra="forbid")

    entity_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    subject_type: ReIdSubjectType
    sighting_ids: list[uuid.UUID] = Field(default_factory=list)
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    representative_image_uri: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Query / result helpers
# ---------------------------------------------------------------------------


class SimilaritySearchRequest(BaseModel):
    """Input to the similarity search interface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query_embedding: AppearanceDescriptor
    subject_type: ReIdSubjectType
    top_k: int = Field(default=10, ge=1, le=200)
    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)
    exclude_camera_id: uuid.UUID | None = Field(
        default=None,
        description="Exclude sightings from this camera (typically the query camera).",
    )
    exclude_sighting_id: uuid.UUID | None = Field(
        default=None,
        description="Exclude one specific sighting (typically the query sighting itself).",
    )


class SimilaritySearchResult(BaseModel):
    """Single result row from a similarity search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sighting_id: uuid.UUID
    camera_id: uuid.UUID
    subject_type: ReIdSubjectType
    entity_id: uuid.UUID | None = None
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class MatchDecision(BaseModel):
    """Output from a match confirmation step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: uuid.UUID
    new_status: ReIdMatchStatus
    decided_by: str = Field(
        ..., description="System component or reviewer that produced the decision."
    )
    reason: str | None = None


class EntityLinkAction(StrEnum):
    """Conservative next-step after a candidate is confirmed."""

    NO_LINK = "no_link"
    CREATE_NEW_ENTITY = "create_new_entity"
    ATTACH_TO_ENTITY = "attach_to_entity"
    ALREADY_LINKED = "already_linked"
    REQUIRES_MANUAL_REVIEW = "requires_manual_review"


class EntityLinkPlan(BaseModel):
    """Plan describing how a confirmed match should affect entity linkage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: EntityLinkAction
    entity_id: uuid.UUID | None = None
    sighting_ids: list[uuid.UUID] = Field(default_factory=list)
    conflicting_entity_ids: list[uuid.UUID] = Field(default_factory=list)
    reason: str | None = None
