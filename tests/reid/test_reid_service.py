"""Tests for the multi-camera re-identification service layer.

Covers schemas, in-memory backends, matching pipeline, and edge cases.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from services.reid.backends import (
    AutoConfirmMatchConfirmer,
    DummyEmbeddingExtractor,
    InMemorySimilarityIndex,
    ThresholdCandidateMatcher,
)
from services.reid.config import ReIdSettings
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
    MatchDecision,
    ReIdCandidate,
    ReIdConfidenceBand,
    ReIdMatchStatus,
    ReIdSubjectType,
    Sighting,
    SimilaritySearchRequest,
    SimilaritySearchResult,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "critical_logic"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "reid_vehicle_pair.json").read_text(encoding="utf-8"))


def _make_sighting(data: dict) -> Sighting:
    """Build a Sighting from a fixture dict."""
    emb = data.get("embedding")
    return Sighting(
        sighting_id=uuid.UUID(data["sighting_id"]),
        camera_id=uuid.UUID(data["camera_id"]),
        track_id=data["track_id"],
        subject_type=ReIdSubjectType(data["subject_type"]),
        entity_id=uuid.UUID(data["entity_id"]) if data.get("entity_id") else None,
        first_seen_at=datetime.fromisoformat(data["first_seen_at"]),
        last_seen_at=datetime.fromisoformat(data["last_seen_at"]),
        embedding=AppearanceDescriptor(**emb) if emb else None,
        bbox_snapshot=data.get("bbox_snapshot"),
    )


def _settings(**overrides: object) -> ReIdSettings:
    """Build a ReIdSettings with optional overrides."""
    defaults = {
        "embedding_model": "test-model",
        "embedding_dimension": 4,
        "high_confidence_threshold": 0.85,
        "medium_confidence_threshold": 0.70,
        "auto_confirm_threshold": 0.90,
        "candidate_ttl_seconds": 3600,
        "default_top_k": 10,
        "default_min_similarity": 0.5,
        "person_reid_enabled": False,
    }
    defaults.update(overrides)
    return ReIdSettings(**defaults)


# ===================================================================
# Schema tests
# ===================================================================


class TestAppearanceDescriptor:
    def test_dimension(self):
        ad = AppearanceDescriptor(vector=[1.0, 2.0, 3.0], model_name="m", model_version="1")
        assert ad.dimension == 3

    def test_frozen(self):
        ad = AppearanceDescriptor(vector=[1.0], model_name="m")
        with pytest.raises(Exception):
            ad.model_name = "changed"  # type: ignore[misc]

    def test_min_length_validation(self):
        with pytest.raises(Exception):
            AppearanceDescriptor(vector=[], model_name="m")


class TestSighting:
    def test_defaults(self):
        s = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        assert s.embedding is None
        assert s.metadata == {}
        assert isinstance(s.sighting_id, uuid.UUID)

    def test_with_embedding(self):
        emb = AppearanceDescriptor(vector=[0.5, 0.5], model_name="test")
        s = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            embedding=emb,
        )
        assert s.embedding is not None
        assert s.embedding.dimension == 2


class TestReIdCandidate:
    def test_status_default(self):
        c = ReIdCandidate(
            sighting_a_id=uuid.uuid4(),
            sighting_b_id=uuid.uuid4(),
            subject_type=ReIdSubjectType.VEHICLE,
            camera_a_id=uuid.uuid4(),
            camera_b_id=uuid.uuid4(),
            similarity_score=0.8,
            confidence_band=ReIdConfidenceBand.MEDIUM,
            proposed_at=datetime.now(timezone.utc),
        )
        assert c.status == ReIdMatchStatus.CANDIDATE

    def test_similarity_bounds(self):
        with pytest.raises(Exception):
            ReIdCandidate(
                sighting_a_id=uuid.uuid4(),
                sighting_b_id=uuid.uuid4(),
                subject_type=ReIdSubjectType.VEHICLE,
                camera_a_id=uuid.uuid4(),
                camera_b_id=uuid.uuid4(),
                similarity_score=1.5,
                confidence_band=ReIdConfidenceBand.HIGH,
                proposed_at=datetime.now(timezone.utc),
            )


class TestCrossCameraEntity:
    def test_defaults(self):
        e = CrossCameraEntity(subject_type=ReIdSubjectType.VEHICLE)
        assert e.sighting_ids == []
        assert isinstance(e.entity_id, uuid.UUID)


# ===================================================================
# Dummy extractor
# ===================================================================


class TestDummyEmbeddingExtractor:
    def test_extract_produces_unit_vector(self):
        ext = DummyEmbeddingExtractor(_settings())
        crop = np.zeros((64, 64, 3), dtype=np.uint8)
        desc = ext.extract(crop)
        assert desc.dimension == 4
        assert desc.model_name == "test-model"
        norm = math.sqrt(sum(v * v for v in desc.vector))
        assert abs(norm - 1.0) < 1e-6

    def test_empty_crop_raises(self):
        ext = DummyEmbeddingExtractor(_settings())
        with pytest.raises(ValueError, match="Empty crop"):
            ext.extract(np.array([]))

    def test_properties(self):
        ext = DummyEmbeddingExtractor(_settings())
        assert ext.model_name == "test-model"
        assert ext.dimension == 4


# ===================================================================
# In-memory similarity index
# ===================================================================


class TestInMemorySimilarityIndex:
    def _make_index_with_fixture(self) -> tuple[InMemorySimilarityIndex, dict]:
        fixture = _load_fixture()
        idx = InMemorySimilarityIndex()
        for s_data in fixture["sightings"] + fixture["distractors"]:
            idx.add(_make_sighting(s_data))
        return idx, fixture

    def test_add_and_count(self):
        idx, _ = self._make_index_with_fixture()
        assert idx.count() == 4  # 2 sightings + 2 distractors

    def test_add_without_embedding(self):
        idx = InMemorySimilarityIndex()
        s = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            embedding=None,
        )
        idx.add(s)
        assert idx.count() == 0  # no embedding → not indexed

    def test_search_returns_similar(self):
        idx, fixture = self._make_index_with_fixture()
        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=5,
                min_similarity=0.5,
                exclude_sighting_id=query.sighting_id,
            )
        )
        # should find the similar sighting (sighting[1]) and possibly the query itself
        sighting_ids = {r.sighting_id for r in results}
        assert uuid.UUID(fixture["sightings"][1]["sighting_id"]) in sighting_ids

    def test_search_excludes_camera(self):
        idx, fixture = self._make_index_with_fixture()
        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=10,
                min_similarity=0.0,
                exclude_camera_id=query.camera_id,
            )
        )
        # should NOT find anything from the same camera
        for r in results:
            assert r.sighting_id != query.sighting_id

    def test_search_filters_subject_type(self):
        idx, fixture = self._make_index_with_fixture()
        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=10,
                min_similarity=0.0,
            )
        )
        # person distractor should not appear
        person_id = uuid.UUID(fixture["distractors"][1]["sighting_id"])
        assert person_id not in {r.sighting_id for r in results}

    def test_search_excludes_specific_sighting(self):
        idx, fixture = self._make_index_with_fixture()
        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=10,
                min_similarity=0.0,
                exclude_sighting_id=query.sighting_id,
            )
        )
        assert query.sighting_id not in {r.sighting_id for r in results}

    def test_search_min_similarity_filter(self):
        idx, fixture = self._make_index_with_fixture()
        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=10,
                min_similarity=0.99,
            )
        )
        # only the query sighting itself should have sim >= 0.99
        for r in results:
            assert r.similarity_score >= 0.99

    def test_search_top_k_limit(self):
        idx, _ = self._make_index_with_fixture()
        query_emb = AppearanceDescriptor(vector=[0.5, 0.5, 0.5, 0.5], model_name="test")
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query_emb,
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=1,
                min_similarity=0.0,
            )
        )
        assert len(results) <= 1

    def test_remove(self):
        idx, fixture = self._make_index_with_fixture()
        sid = uuid.UUID(fixture["sightings"][0]["sighting_id"])
        assert idx.remove(sid) is True
        assert idx.count() == 3
        assert idx.remove(sid) is False  # already removed

    def test_clear(self):
        idx, _ = self._make_index_with_fixture()
        idx.clear()
        assert idx.count() == 0

    def test_results_ordered_by_similarity(self):
        idx, fixture = self._make_index_with_fixture()
        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=10,
                min_similarity=0.0,
            )
        )
        scores = [r.similarity_score for r in results]
        assert scores == sorted(scores, reverse=True)


# ===================================================================
# Threshold candidate matcher
# ===================================================================


class TestThresholdCandidateMatcher:
    def test_propose_emits_candidates(self):
        cfg = _settings()
        matcher = ThresholdCandidateMatcher(cfg)
        query = Sighting(
            sighting_id=uuid.uuid4(),
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        results = [
            SimilaritySearchResult(
                sighting_id=uuid.uuid4(),
                camera_id=uuid.uuid4(),
                subject_type=ReIdSubjectType.VEHICLE,
                similarity_score=0.92,
            ),
            SimilaritySearchResult(
                sighting_id=uuid.uuid4(),
                camera_id=uuid.uuid4(),
                subject_type=ReIdSubjectType.VEHICLE,
                similarity_score=0.75,
            ),
            SimilaritySearchResult(
                sighting_id=uuid.uuid4(),
                camera_id=uuid.uuid4(),
                subject_type=ReIdSubjectType.VEHICLE,
                similarity_score=0.55,
            ),
        ]
        candidates = matcher.propose(query, results, settings=cfg)
        assert len(candidates) == 3
        assert candidates[0].confidence_band == ReIdConfidenceBand.HIGH
        assert candidates[1].confidence_band == ReIdConfidenceBand.MEDIUM
        assert candidates[2].confidence_band == ReIdConfidenceBand.LOW
        assert candidates[0].subject_type is ReIdSubjectType.VEHICLE

    def test_propose_skips_same_camera_candidates(self):
        cfg = _settings()
        matcher = ThresholdCandidateMatcher(cfg)
        camera_id = uuid.uuid4()
        query = Sighting(
            camera_id=camera_id,
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        results = [
            SimilaritySearchResult(
                sighting_id=uuid.uuid4(),
                camera_id=camera_id,
                subject_type=ReIdSubjectType.VEHICLE,
                similarity_score=0.97,
            )
        ]
        assert matcher.propose(query, results, settings=cfg) == []

    def test_propose_blocks_person_when_policy_disabled(self):
        cfg = _settings(person_reid_enabled=False)
        matcher = ThresholdCandidateMatcher(cfg)
        query = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.PERSON,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        results = [
            SimilaritySearchResult(
                sighting_id=uuid.uuid4(),
                camera_id=uuid.uuid4(),
                subject_type=ReIdSubjectType.PERSON,
                similarity_score=0.99,
            )
        ]
        assert matcher.propose(query, results, settings=cfg) == []

    def test_propose_empty_results(self):
        matcher = ThresholdCandidateMatcher(_settings())
        query = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        assert matcher.propose(query, []) == []


# ===================================================================
# Auto-confirm match confirmer
# ===================================================================


class TestAutoConfirmMatchConfirmer:
    def _candidate(self, score: float, band: ReIdConfidenceBand) -> ReIdCandidate:
        return ReIdCandidate(
            sighting_a_id=uuid.uuid4(),
            sighting_b_id=uuid.uuid4(),
            subject_type=ReIdSubjectType.VEHICLE,
            camera_a_id=uuid.uuid4(),
            camera_b_id=uuid.uuid4(),
            similarity_score=score,
            confidence_band=band,
            proposed_at=datetime.now(timezone.utc),
        )

    def test_auto_confirm_high(self):
        cfg = _settings()
        confirmer = AutoConfirmMatchConfirmer(cfg)
        decision = confirmer.decide(self._candidate(0.95, ReIdConfidenceBand.HIGH), settings=cfg)
        assert decision.new_status == ReIdMatchStatus.CONFIRMED
        assert decision.decided_by == "auto-confirmer"

    def test_reject_low(self):
        cfg = _settings()
        confirmer = AutoConfirmMatchConfirmer(cfg)
        decision = confirmer.decide(self._candidate(0.55, ReIdConfidenceBand.LOW), settings=cfg)
        assert decision.new_status == ReIdMatchStatus.REJECTED

    def test_defer_medium(self):
        cfg = _settings()
        confirmer = AutoConfirmMatchConfirmer(cfg)
        decision = confirmer.decide(self._candidate(0.78, ReIdConfidenceBand.MEDIUM), settings=cfg)
        assert decision.new_status == ReIdMatchStatus.CANDIDATE
        assert "human review" in decision.reason.lower()

    def test_reject_person_when_policy_disabled(self):
        cfg = _settings(person_reid_enabled=False)
        confirmer = AutoConfirmMatchConfirmer(cfg)
        candidate = ReIdCandidate(
            sighting_a_id=uuid.uuid4(),
            sighting_b_id=uuid.uuid4(),
            subject_type=ReIdSubjectType.PERSON,
            camera_a_id=uuid.uuid4(),
            camera_b_id=uuid.uuid4(),
            similarity_score=0.99,
            confidence_band=ReIdConfidenceBand.HIGH,
            proposed_at=datetime.now(timezone.utc),
        )
        decision = confirmer.decide(candidate, settings=cfg)
        assert decision.new_status == ReIdMatchStatus.REJECTED
        assert "disabled by policy" in decision.reason.lower()

    def test_reject_same_camera_candidate(self):
        cfg = _settings()
        confirmer = AutoConfirmMatchConfirmer(cfg)
        camera_id = uuid.uuid4()
        candidate = ReIdCandidate(
            sighting_a_id=uuid.uuid4(),
            sighting_b_id=uuid.uuid4(),
            subject_type=ReIdSubjectType.VEHICLE,
            camera_a_id=camera_id,
            camera_b_id=camera_id,
            similarity_score=0.99,
            confidence_band=ReIdConfidenceBand.HIGH,
            proposed_at=datetime.now(timezone.utc),
        )
        decision = confirmer.decide(candidate, settings=cfg)
        assert decision.new_status == ReIdMatchStatus.REJECTED

    def test_conflicting_entities_require_manual_review(self):
        cfg = _settings()
        confirmer = AutoConfirmMatchConfirmer(cfg)
        candidate = ReIdCandidate(
            sighting_a_id=uuid.uuid4(),
            sighting_b_id=uuid.uuid4(),
            subject_type=ReIdSubjectType.VEHICLE,
            camera_a_id=uuid.uuid4(),
            camera_b_id=uuid.uuid4(),
            entity_a_id=uuid.uuid4(),
            entity_b_id=uuid.uuid4(),
            similarity_score=0.99,
            confidence_band=ReIdConfidenceBand.HIGH,
            proposed_at=datetime.now(timezone.utc),
        )
        decision = confirmer.decide(candidate, settings=cfg)
        assert decision.new_status == ReIdMatchStatus.CANDIDATE
        assert "existing entities" in decision.reason.lower()


# ===================================================================
# End-to-end pipeline (fixture-driven)
# ===================================================================


class TestReIdPipeline:
    """Integration-style test running the full propose→decide pipeline."""

    def test_fixture_vehicle_pair_matched(self):
        """Two similar vehicles from different cameras should produce a
        CONFIRMED candidate via the auto-confirm pipeline."""
        fixture = _load_fixture()
        cfg = _settings(auto_confirm_threshold=0.90, high_confidence_threshold=0.85)

        # 1. Index all sightings
        idx = InMemorySimilarityIndex()
        all_sightings: dict[uuid.UUID, Sighting] = {}
        for s_data in fixture["sightings"] + fixture["distractors"]:
            s = _make_sighting(s_data)
            all_sightings[s.sighting_id] = s
            idx.add(s)

        # 2. Query from sighting[0]
        query = all_sightings[uuid.UUID(fixture["sightings"][0]["sighting_id"])]
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=5,
                min_similarity=0.5,
                exclude_camera_id=query.camera_id,
                exclude_sighting_id=query.sighting_id,
            )
        )
        assert len(results) >= 1

        # 3. Propose candidates
        matcher = ThresholdCandidateMatcher(cfg)
        candidates = matcher.propose(query, results, settings=cfg)
        assert len(candidates) >= 1

        # The best candidate should be the matching sighting
        best = max(candidates, key=lambda c: c.similarity_score)
        assert best.sighting_b_id == uuid.UUID(fixture["sightings"][1]["sighting_id"])

        # 4. Confirm
        confirmer = AutoConfirmMatchConfirmer(cfg)
        decision = confirmer.decide(best, settings=cfg)
        # similarity between [0.5,0.5,0.5,0.5] and [0.49,0.51,0.50,0.50]
        # is very high (~0.9999) so should auto-confirm
        assert decision.new_status == ReIdMatchStatus.CONFIRMED

    def test_distractor_not_confirmed(self):
        """The distractor vehicle (opposite embedding) should not yield a HIGH match."""
        fixture = _load_fixture()
        cfg = _settings()

        idx = InMemorySimilarityIndex()
        for s_data in fixture["sightings"] + fixture["distractors"]:
            idx.add(_make_sighting(s_data))

        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=10,
                min_similarity=0.0,
                exclude_camera_id=query.camera_id,
            )
        )
        distractor_id = uuid.UUID(fixture["distractors"][0]["sighting_id"])
        distractor_result = [r for r in results if r.sighting_id == distractor_id]
        if distractor_result:
            # similarity should be very low (negative cosine → clamped to 0)
            assert distractor_result[0].similarity_score < 0.5

    def test_person_not_mixed_with_vehicle(self):
        """Person sightings should never appear in vehicle search results."""
        fixture = _load_fixture()
        idx = InMemorySimilarityIndex()
        for s_data in fixture["sightings"] + fixture["distractors"]:
            idx.add(_make_sighting(s_data))

        query = _make_sighting(fixture["sightings"][0])
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=query.embedding,  # type: ignore[arg-type]
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=100,
                min_similarity=0.0,
            )
        )
        person_id = uuid.UUID(fixture["distractors"][1]["sighting_id"])
        assert person_id not in {r.sighting_id for r in results}


# ===================================================================
# Edge cases
# ===================================================================


class TestEdgeCases:
    def test_single_sighting_search(self):
        """Searching an index with a single entry should return it."""
        idx = InMemorySimilarityIndex()
        emb = AppearanceDescriptor(vector=[1.0, 0.0, 0.0, 0.0], model_name="test")
        s = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            embedding=emb,
        )
        idx.add(s)
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=emb,
                subject_type=ReIdSubjectType.VEHICLE,
                min_similarity=0.0,
            )
        )
        assert len(results) == 1
        assert results[0].sighting_id == s.sighting_id
        assert results[0].similarity_score == pytest.approx(1.0, abs=1e-6)

    def test_zero_vector_handling(self):
        """A zero vector should still be addable and searchable without crash."""
        idx = InMemorySimilarityIndex()
        emb = AppearanceDescriptor(vector=[0.0, 0.0, 0.0, 0.0], model_name="test")
        s = Sighting(
            camera_id=uuid.uuid4(),
            track_id="t1",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
            embedding=emb,
        )
        idx.add(s)
        # should not raise
        results = idx.search(
            SimilaritySearchRequest(
                query_embedding=emb,
                subject_type=ReIdSubjectType.VEHICLE,
                min_similarity=0.0,
            )
        )
        assert isinstance(results, list)

    def test_config_defaults(self):
        cfg = _settings()
        assert cfg.person_reid_enabled is False
        assert cfg.auto_confirm_threshold == 0.90

    def test_confidence_band_enum(self):
        assert ReIdConfidenceBand.HIGH.value == "high"
        assert ReIdConfidenceBand.MEDIUM.value == "medium"
        assert ReIdConfidenceBand.LOW.value == "low"

    def test_match_status_enum(self):
        assert ReIdMatchStatus.CANDIDATE.value == "candidate"
        assert ReIdMatchStatus.EXPIRED.value == "expired"

    def test_subject_type_enum(self):
        assert ReIdSubjectType.VEHICLE.value == "vehicle"
        assert ReIdSubjectType.PERSON.value == "person"

    def test_similarity_search_request_validation(self):
        with pytest.raises(Exception):
            SimilaritySearchRequest(
                query_embedding=AppearanceDescriptor(vector=[1.0], model_name="m"),
                subject_type=ReIdSubjectType.VEHICLE,
                top_k=0,  # must be >= 1
            )

    def test_match_decision_schema(self):
        d = MatchDecision(
            candidate_id=uuid.uuid4(),
            new_status=ReIdMatchStatus.CONFIRMED,
            decided_by="test",
            reason="unit test",
        )
        assert d.decided_by == "test"


class TestEntityLinkPlanning:
    def test_canonical_pair_key_is_order_independent(self):
        first = uuid.uuid4()
        second = uuid.uuid4()
        assert canonical_pair_key(first, second) == canonical_pair_key(second, first)

    def test_plan_creates_new_entity_for_two_unlinked_sightings(self):
        sighting_a = Sighting(
            camera_id=uuid.uuid4(),
            track_id="a",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        sighting_b = Sighting(
            camera_id=uuid.uuid4(),
            track_id="b",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        decision = MatchDecision(
            candidate_id=uuid.uuid4(),
            new_status=ReIdMatchStatus.CONFIRMED,
            decided_by="test",
        )
        fixed_entity_id = uuid.uuid4()
        plan = plan_entity_link(
            sighting_a,
            sighting_b,
            decision,
            entity_id_factory=lambda: fixed_entity_id,
        )
        assert plan.action is EntityLinkAction.CREATE_NEW_ENTITY
        assert plan.entity_id == fixed_entity_id

    def test_plan_attaches_to_existing_entity(self):
        existing_entity_id = uuid.uuid4()
        sighting_a = Sighting(
            camera_id=uuid.uuid4(),
            track_id="a",
            subject_type=ReIdSubjectType.VEHICLE,
            entity_id=existing_entity_id,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        sighting_b = Sighting(
            camera_id=uuid.uuid4(),
            track_id="b",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        decision = MatchDecision(
            candidate_id=uuid.uuid4(),
            new_status=ReIdMatchStatus.CONFIRMED,
            decided_by="test",
        )
        plan = plan_entity_link(sighting_a, sighting_b, decision)
        assert plan.action is EntityLinkAction.ATTACH_TO_ENTITY
        assert plan.entity_id == existing_entity_id

    def test_plan_avoids_auto_merging_existing_entities(self):
        sighting_a = Sighting(
            camera_id=uuid.uuid4(),
            track_id="a",
            subject_type=ReIdSubjectType.VEHICLE,
            entity_id=uuid.uuid4(),
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        sighting_b = Sighting(
            camera_id=uuid.uuid4(),
            track_id="b",
            subject_type=ReIdSubjectType.VEHICLE,
            entity_id=uuid.uuid4(),
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        decision = MatchDecision(
            candidate_id=uuid.uuid4(),
            new_status=ReIdMatchStatus.CONFIRMED,
            decided_by="test",
        )
        plan = plan_entity_link(sighting_a, sighting_b, decision)
        assert plan.action is EntityLinkAction.REQUIRES_MANUAL_REVIEW
        assert len(plan.conflicting_entity_ids) == 2

    def test_plan_no_link_when_candidate_not_confirmed(self):
        sighting_a = Sighting(
            camera_id=uuid.uuid4(),
            track_id="a",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        sighting_b = Sighting(
            camera_id=uuid.uuid4(),
            track_id="b",
            subject_type=ReIdSubjectType.VEHICLE,
            first_seen_at=datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
        decision = MatchDecision(
            candidate_id=uuid.uuid4(),
            new_status=ReIdMatchStatus.CANDIDATE,
            decided_by="test",
        )
        plan = plan_entity_link(sighting_a, sighting_b, decision)
        assert plan.action is EntityLinkAction.NO_LINK


# ===================================================================
# Extractor registry
# ===================================================================


class TestEmbeddingExtractorRegistry:
    def test_register_and_create(self):
        EmbeddingExtractorRegistry._backends.clear()
        EmbeddingExtractorRegistry.register("dummy", DummyEmbeddingExtractor)
        assert "dummy" in EmbeddingExtractorRegistry.available()
        ext = EmbeddingExtractorRegistry.create("dummy", _settings())
        assert isinstance(ext, DummyEmbeddingExtractor)
        EmbeddingExtractorRegistry._backends.clear()

    def test_unknown_backend(self):
        EmbeddingExtractorRegistry._backends.clear()
        with pytest.raises(KeyError, match="Unknown embedding backend"):
            EmbeddingExtractorRegistry.create("nonexistent", _settings())
