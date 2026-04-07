"""API tests for the benchmark and evaluation summary foundation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.app.core.config import get_settings
from apps.api.app.main import create_app
from services.evaluation.artifacts import build_fixture_report_artifact, write_report_artifact
from services.evaluation.schemas import EvaluationArtifactSourceKind


@pytest.fixture
async def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    artifact_dir = tmp_path / "evaluation-artifacts"
    monkeypatch.setenv("TRAFFICMIND_EVALUATION_ARTIFACT_DIR", str(artifact_dir))
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_evaluation_summary_exposes_fixture_backed_metrics_and_placeholders(
    client: AsyncClient,
) -> None:
    response = await client.get("/api/v1/analytics/evaluation")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) == 1
    source = payload["sources"][0]
    assert source["metadata"]["source_kind"] == "fixture_suite"
    assert source["report"]["detection_reports"][0]["name"] == "mixed_vehicle_person_detection"
    assert source["report"]["tracking_reports"][0]["id_switch_count"] == 1
    assert source["fixture_suite"]["ocr_cases"][0]["samples"][0]["expected_normalized_text"] == "ABC1234"
    placeholder_keys = {item["key"] for item in payload["placeholders"]}
    assert "manual_review_summaries" in placeholder_keys
    assert "stored_report_artifacts" in placeholder_keys
    assert "workflow_evaluation_summaries" in placeholder_keys
    assert payload["manual_review_summaries"] == []


@pytest.mark.asyncio
async def test_evaluation_summary_loads_stored_artifacts_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = tmp_path / "evaluation-artifacts"
    fixture_path = Path("e:/Github/trafficmind/tests/fixtures/evaluation/benchmark_suite.json")
    artifact = build_fixture_report_artifact(
        fixture_path,
        artifact_label="nightly-sanities",
        camera_labels=["CAM-EVAL-001"],
        model_version_names=["yolo26x.pt"],
        manual_review_summary="One OCR mismatch was manually reviewed and accepted as a difficult crop.",
        workflow_summary="Daily summary generation stayed stable on the same fixture pack.",
        notes=["Stored from a local nightly regression run."],
    ).model_copy(
        update={
            "metadata": build_fixture_report_artifact(
                fixture_path,
                artifact_label="nightly-sanities",
                camera_labels=["CAM-EVAL-001"],
                model_version_names=["yolo26x.pt"],
                manual_review_summary="One OCR mismatch was manually reviewed and accepted as a difficult crop.",
                workflow_summary="Daily summary generation stayed stable on the same fixture pack.",
                notes=["Stored from a local nightly regression run."],
            ).metadata.model_copy(update={"source_kind": EvaluationArtifactSourceKind.STORED_REPORT})
        }
    )
    write_report_artifact(artifact_dir / "nightly-sanities.json", artifact)

    monkeypatch.setenv("TRAFFICMIND_EVALUATION_ARTIFACT_DIR", str(artifact_dir))
    get_settings.cache_clear()
    app = create_app()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/analytics/evaluation")

    get_settings.cache_clear()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["sources"]) == 2
    stored_sources = [item for item in payload["sources"] if item["metadata"]["source_kind"] == "stored_report"]
    assert len(stored_sources) == 1
    stored = stored_sources[0]
    assert stored["metadata"]["artifact_label"] == "nightly-sanities"
    assert stored["metadata"]["model_version_names"] == ["yolo26x.pt"]
    assert stored["metadata"]["camera_labels"] == ["CAM-EVAL-001"]
    assert payload["manual_review_summaries"][0]["manual_review_summary"].startswith("One OCR mismatch")
    assert payload["manual_review_summaries"][0]["workflow_summary"].startswith("Daily summary")
