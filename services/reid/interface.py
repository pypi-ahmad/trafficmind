"""Re-identification service interfaces.

The re-id subsystem is built around four pluggable interfaces:

1. ``EmbeddingExtractor`` — produces an appearance descriptor from an image
   crop of a tracked object.
2. ``SimilarityIndex`` — indexes sighting embeddings and answers top-K
   nearest-neighbour queries.
3. ``CandidateMatcher`` — takes similarity results and applies rules /
   heuristics to produce ``ReIdCandidate`` proposals.
4. ``MatchConfirmer`` — decides whether candidates should be confirmed,
   rejected, or left for human review.

Each interface is an ABC so backends can be swapped (in-memory, FAISS,
ONNX, external vector DB, manual review queue, etc.).
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

import numpy as np

from services.reid.schemas import (
    AppearanceDescriptor,
    MatchDecision,
    ReIdCandidate,
    Sighting,
    SimilaritySearchRequest,
    SimilaritySearchResult,
)

if TYPE_CHECKING:
    from services.reid.config import ReIdSettings


# ---------------------------------------------------------------------------
# 1) Embedding extraction
# ---------------------------------------------------------------------------


class EmbeddingExtractor(abc.ABC):
    """Produces an ``AppearanceDescriptor`` from an image crop."""

    @abc.abstractmethod
    def extract(self, crop: np.ndarray) -> AppearanceDescriptor:
        """Extract an appearance embedding from a BGR crop array.

        Args:
            crop: HWC numpy array of the object crop.

        Returns:
            ``AppearanceDescriptor`` with the embedding vector.

        Raises:
            ValueError: If the crop is too small or invalid.
        """

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Return the canonical model identifier."""

    @property
    @abc.abstractmethod
    def dimension(self) -> int:
        """Return the embedding vector dimension."""


# ---------------------------------------------------------------------------
# 2) Similarity index
# ---------------------------------------------------------------------------


class SimilarityIndex(abc.ABC):
    """Vector index for fast nearest-neighbour search over sighting embeddings."""

    @abc.abstractmethod
    def add(self, sighting: Sighting) -> None:
        """Add a sighting (with embedding) to the index.

        If the sighting has no embedding, this is a silent no-op.
        """

    @abc.abstractmethod
    def search(self, request: SimilaritySearchRequest) -> list[SimilaritySearchResult]:
        """Return the top-K most similar sightings.

        Results are ordered by descending similarity.
        """

    @abc.abstractmethod
    def remove(self, sighting_id: "str | __import__('uuid').UUID") -> bool:
        """Remove a sighting from the index.  Returns True if it was found."""

    @abc.abstractmethod
    def count(self) -> int:
        """Return the number of indexed sightings."""

    @abc.abstractmethod
    def clear(self) -> None:
        """Remove all entries."""


# ---------------------------------------------------------------------------
# 3) Candidate matcher
# ---------------------------------------------------------------------------


class CandidateMatcher(abc.ABC):
    """Turns raw similarity results into structured ``ReIdCandidate`` proposals."""

    @abc.abstractmethod
    def propose(
        self,
        query_sighting: Sighting,
        search_results: list[SimilaritySearchResult],
        *,
        settings: ReIdSettings | None = None,
    ) -> list[ReIdCandidate]:
        """Produce candidate matches from a similarity search.

        Implementations may apply spatio-temporal filters, camera-topology
        constraints, or other heuristics before emitting candidates.
        """


# ---------------------------------------------------------------------------
# 4) Match confirmer
# ---------------------------------------------------------------------------


class MatchConfirmer(abc.ABC):
    """Decides whether proposed candidates should be confirmed or rejected."""

    @abc.abstractmethod
    def decide(
        self,
        candidate: ReIdCandidate,
        *,
        settings: ReIdSettings | None = None,
    ) -> MatchDecision:
        """Evaluate a single candidate and make a confirmation decision.

        Implementations may auto-confirm high-confidence matches or defer
        low-confidence ones to a human review queue.
        """


# ---------------------------------------------------------------------------
# Registry (mirrors vision / tracking pattern)
# ---------------------------------------------------------------------------


class EmbeddingExtractorRegistry:
    """Name → extractor-factory registry."""

    _backends: dict[str, type[EmbeddingExtractor]] = {}

    @classmethod
    def register(cls, name: str, backend_cls: type[EmbeddingExtractor]) -> None:
        cls._backends[name] = backend_cls

    @classmethod
    def create(cls, name: str, settings: ReIdSettings) -> EmbeddingExtractor:
        if name not in cls._backends:
            msg = f"Unknown embedding backend: {name!r}.  Available: {sorted(cls._backends)}"
            raise KeyError(msg)
        return cls._backends[name](settings)  # type: ignore[call-arg]

    @classmethod
    def available(cls) -> list[str]:
        return sorted(cls._backends)
