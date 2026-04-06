"""TrafficMind multi-camera re-identification service package."""

from services.reid.config import ReIdSettings, get_reid_settings
from services.reid.interface import (
    CandidateMatcher,
    EmbeddingExtractor,
    EmbeddingExtractorRegistry,
    MatchConfirmer,
    SimilarityIndex,
)
from services.reid.linking import canonical_pair_key, plan_entity_link
from services.reid.schemas import (
    AppearanceDescriptor,
    CrossCameraEntity,
    EntityLinkAction,
    EntityLinkPlan,
    MatchDecision,
    ReIdCandidate,
    ReIdConfidenceBand,
    ReIdMatchStatus,
    ReIdSubjectType,
    Sighting,
    SimilaritySearchRequest,
    SimilaritySearchResult,
)

__all__ = [
    "AppearanceDescriptor",
    "CandidateMatcher",
    "canonical_pair_key",
    "CrossCameraEntity",
    "EmbeddingExtractor",
    "EmbeddingExtractorRegistry",
    "EntityLinkAction",
    "EntityLinkPlan",
    "MatchConfirmer",
    "MatchDecision",
    "plan_entity_link",
    "ReIdCandidate",
    "ReIdConfidenceBand",
    "ReIdMatchStatus",
    "ReIdSettings",
    "ReIdSubjectType",
    "Sighting",
    "SimilarityIndex",
    "SimilaritySearchRequest",
    "SimilaritySearchResult",
    "get_reid_settings",
]
