"""In-memory backends for development, testing, and small deployments.

These are intentionally simple implementations.  Production deployments
should swap in FAISS, Milvus, or another optimised vector store via the
``SimilarityIndex`` ABC, and a real CNN/ViT extractor via the
``EmbeddingExtractor`` ABC.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np

from services.reid.interface import (
    CandidateMatcher,
    EmbeddingExtractor,
    MatchConfirmer,
    SimilarityIndex,
)
from services.reid.schemas import (
    AppearanceDescriptor,
    MatchDecision,
    ReIdCandidate,
    ReIdConfidenceBand,
    ReIdMatchStatus,
    ReIdSubjectType,
    Sighting,
    SimilaritySearchRequest,
    SimilaritySearchResult,
)

if TYPE_CHECKING:
    from services.reid.config import ReIdSettings


# ---------------------------------------------------------------------------
# 1) Dummy embedding extractor (random / pass-through)
# ---------------------------------------------------------------------------


class DummyEmbeddingExtractor(EmbeddingExtractor):
    """Returns a random unit-norm embedding.  Useful only for testing."""

    def __init__(self, settings: ReIdSettings | None = None) -> None:
        self._dim = settings.embedding_dimension if settings else 512
        self._model = settings.embedding_model if settings else "dummy"

    def extract(self, crop: np.ndarray) -> AppearanceDescriptor:
        if crop.size == 0:
            msg = "Empty crop supplied to embedding extractor."
            raise ValueError(msg)
        rng = np.random.default_rng()
        vec = rng.standard_normal(self._dim).astype(np.float64)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec /= norm
        return AppearanceDescriptor(
            vector=vec.tolist(),
            model_name=self._model,
            model_version="0.0-dummy",
            norm=1.0,
        )

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dim


# ---------------------------------------------------------------------------
# 2) Brute-force in-memory similarity index
# ---------------------------------------------------------------------------


class InMemorySimilarityIndex(SimilarityIndex):
    """Brute-force cosine-similarity index backed by a Python dict.

    Suitable for up to ~10 k sightings.  Beyond that, use FAISS or a
    vector database.
    """

    def __init__(self) -> None:
        self._store: dict[uuid.UUID, _IndexEntry] = {}

    def add(self, sighting: Sighting) -> None:
        if sighting.embedding is None:
            return
        vec = np.asarray(sighting.embedding.vector, dtype=np.float64)
        norm = float(np.linalg.norm(vec))
        if norm > 0:
            vec = vec / norm
        self._store[sighting.sighting_id] = _IndexEntry(
            sighting_id=sighting.sighting_id,
            camera_id=sighting.camera_id,
            subject_type=sighting.subject_type,
            entity_id=sighting.entity_id,
            vector=vec,
        )

    def search(self, request: SimilaritySearchRequest) -> list[SimilaritySearchResult]:
        query_vec = np.asarray(request.query_embedding.vector, dtype=np.float64)
        norm = float(np.linalg.norm(query_vec))
        if norm > 0:
            query_vec = query_vec / norm

        scored: list[tuple[uuid.UUID, float]] = []
        for entry in self._store.values():
            if entry.subject_type != request.subject_type:
                continue
            if request.exclude_camera_id and entry.camera_id == request.exclude_camera_id:
                continue
            if request.exclude_sighting_id and entry.sighting_id == request.exclude_sighting_id:
                continue
            sim = float(np.dot(query_vec, entry.vector))
            # clamp to [0, 1] — cosine similarity of unit vectors
            sim = max(0.0, min(1.0, sim))
            if sim >= request.min_similarity:
                scored.append((entry.sighting_id, sim))

        scored.sort(key=lambda t: t[1], reverse=True)
        return [
            SimilaritySearchResult(
                sighting_id=self._store[sid].sighting_id,
                camera_id=self._store[sid].camera_id,
                subject_type=self._store[sid].subject_type,
                entity_id=self._store[sid].entity_id,
                similarity_score=score,
            )
            for sid, score in scored[: request.top_k]
        ]

    def remove(self, sighting_id: str | uuid.UUID) -> bool:
        key = uuid.UUID(str(sighting_id))
        return self._store.pop(key, None) is not None

    def count(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()


class _IndexEntry:
    """Internal bookkeeping for an indexed sighting."""

    __slots__ = ("camera_id", "entity_id", "sighting_id", "subject_type", "vector")

    def __init__(
        self,
        sighting_id: uuid.UUID,
        camera_id: uuid.UUID,
        subject_type: ReIdSubjectType,
        entity_id: uuid.UUID | None,
        vector: np.ndarray,
    ) -> None:
        self.sighting_id = sighting_id
        self.camera_id = camera_id
        self.subject_type = subject_type
        self.entity_id = entity_id
        self.vector = vector


# ---------------------------------------------------------------------------
# 3) Threshold-based candidate matcher
# ---------------------------------------------------------------------------


class ThresholdCandidateMatcher(CandidateMatcher):
    """Emits one ``ReIdCandidate`` per search result that exceeds the minimum
    similarity, tagged with a confidence band derived from settings thresholds."""

    def __init__(self, settings: ReIdSettings | None = None) -> None:
        from services.reid.config import get_reid_settings

        self._settings = settings or get_reid_settings()

    def propose(
        self,
        query_sighting: Sighting,
        search_results: list[SimilaritySearchResult],
        *,
        settings: ReIdSettings | None = None,
    ) -> list[ReIdCandidate]:
        cfg = settings or self._settings
        if query_sighting.subject_type is ReIdSubjectType.PERSON and not cfg.person_reid_enabled:
            return []
        now = datetime.now(timezone.utc)
        candidates: list[ReIdCandidate] = []
        for result in search_results:
            if result.sighting_id == query_sighting.sighting_id:
                continue
            if result.subject_type != query_sighting.subject_type:
                continue
            if result.camera_id == query_sighting.camera_id:
                continue
            band = self._band(result.similarity_score, cfg)
            candidates.append(
                ReIdCandidate(
                    sighting_a_id=query_sighting.sighting_id,
                    sighting_b_id=result.sighting_id,
                    subject_type=query_sighting.subject_type,
                    camera_a_id=query_sighting.camera_id,
                    camera_b_id=result.camera_id,
                    entity_a_id=query_sighting.entity_id,
                    entity_b_id=result.entity_id,
                    similarity_score=result.similarity_score,
                    confidence_band=band,
                    status=ReIdMatchStatus.CANDIDATE,
                    proposed_at=now,
                )
            )
        return candidates

    @staticmethod
    def _band(score: float, cfg: ReIdSettings) -> ReIdConfidenceBand:
        if score >= cfg.high_confidence_threshold:
            return ReIdConfidenceBand.HIGH
        if score >= cfg.medium_confidence_threshold:
            return ReIdConfidenceBand.MEDIUM
        return ReIdConfidenceBand.LOW


# ---------------------------------------------------------------------------
# 4) Auto-confirm / defer confirmer
# ---------------------------------------------------------------------------


class AutoConfirmMatchConfirmer(MatchConfirmer):
    """Auto-confirms candidates above the auto-confirm threshold, rejects
    LOW-confidence matches, and leaves MEDIUM ones as CANDIDATE for human
    review."""

    def __init__(self, settings: ReIdSettings | None = None) -> None:
        from services.reid.config import get_reid_settings

        self._settings = settings or get_reid_settings()

    def decide(
        self,
        candidate: ReIdCandidate,
        *,
        settings: ReIdSettings | None = None,
    ) -> MatchDecision:
        cfg = settings or self._settings

        if candidate.subject_type is ReIdSubjectType.PERSON and not cfg.person_reid_enabled:
            return MatchDecision(
                candidate_id=candidate.candidate_id,
                new_status=ReIdMatchStatus.REJECTED,
                decided_by="auto-confirmer",
                reason="person re-id is disabled by policy",
            )

        if candidate.camera_a_id == candidate.camera_b_id:
            return MatchDecision(
                candidate_id=candidate.candidate_id,
                new_status=ReIdMatchStatus.REJECTED,
                decided_by="auto-confirmer",
                reason="same-camera associations are not valid cross-camera re-id matches",
            )

        if (
            candidate.entity_a_id is not None
            and candidate.entity_b_id is not None
            and candidate.entity_a_id != candidate.entity_b_id
        ):
            return MatchDecision(
                candidate_id=candidate.candidate_id,
                new_status=ReIdMatchStatus.CANDIDATE,
                decided_by="auto-confirmer",
                reason="candidate bridges two existing entities and requires manual review",
            )

        if candidate.similarity_score >= cfg.auto_confirm_threshold:
            return MatchDecision(
                candidate_id=candidate.candidate_id,
                new_status=ReIdMatchStatus.CONFIRMED,
                decided_by="auto-confirmer",
                reason=f"similarity {candidate.similarity_score:.3f} >= auto-confirm threshold {cfg.auto_confirm_threshold}",
            )

        if candidate.confidence_band == ReIdConfidenceBand.LOW:
            return MatchDecision(
                candidate_id=candidate.candidate_id,
                new_status=ReIdMatchStatus.REJECTED,
                decided_by="auto-confirmer",
                reason=f"LOW confidence band (similarity {candidate.similarity_score:.3f})",
            )

        # MEDIUM band — leave for human review
        return MatchDecision(
            candidate_id=candidate.candidate_id,
            new_status=ReIdMatchStatus.CANDIDATE,
            decided_by="auto-confirmer",
            reason=f"MEDIUM confidence band (similarity {candidate.similarity_score:.3f}) — needs human review",
        )
