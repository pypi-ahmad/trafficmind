"""Unit tests for HealthAssessor — pure logic, no DB or I/O."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from services.health.assessor import HealthAssessor, build_metrics_snapshot
from services.health.schemas import (
    AlertSeverity,
    HealthSignal,
    HealthStateBasis,
    HealthThresholds,
)
from services.streams.schemas import JobMetrics, JobSpec, JobState, JobStatus, PipelineFlags, SourceKind


# ── Helpers ─────────────────────────────────────────────────────────────────

NOW = datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)


def _make_job_state(
    *,
    status: JobStatus = JobStatus.RUNNING,
    metrics: JobMetrics | None = None,
    heartbeat: datetime | None = None,
    pipeline: PipelineFlags | None = None,
    stream_id: uuid.UUID | None = None,
) -> JobState:
    spec = JobSpec(
        source_kind=SourceKind.RTSP,
        source_uri="rtsp://test/stream",
        stream_id=stream_id,
        pipeline=pipeline or PipelineFlags(),
    )
    state = JobState(spec=spec, status=status)
    if metrics:
        state.metrics = metrics
    state.last_heartbeat_at = heartbeat or NOW
    state.started_at = NOW - timedelta(minutes=5)
    return state


def _stream_kwargs(
    *,
    db_status: str = "live",
    is_enabled: bool = True,
    last_heartbeat_at: datetime | None = None,
    last_error: str | None = None,
    fps_hint: float | None = 25.0,
    job_state: JobState | None = None,
) -> dict:
    return dict(
        stream_id=uuid.uuid4(),
        stream_name="primary",
        camera_id=uuid.uuid4(),
        source_type="rtsp",
        db_status=db_status,
        is_enabled=is_enabled,
        last_heartbeat_at=last_heartbeat_at,
        last_error=last_error,
        fps_hint=fps_hint,
        job_state=job_state,
        now=NOW,
    )


# ── build_metrics_snapshot ──────────────────────────────────────────────────


class TestBuildMetricsSnapshot:
    def test_empty_metrics(self):
        snap = build_metrics_snapshot(JobMetrics())
        assert snap.frames_processed == 0
        assert snap.drop_rate_percent == 0.0
        assert snap.decode_failure_rate_percent == 0.0

    def test_rates_computed(self):
        m = JobMetrics(
            frames_read=100,
            frames_processed=70,
            frames_skipped=10,
            frames_skipped_cadence=10,
            frames_dropped_backpressure=15,
            frames_failed=5,
            stream_read_failures=4,
            avg_inference_ms=12.5,
            avg_fps=20.0,
            last_successful_inference_at=NOW,
            reconnect_count=2,
        )
        snap = build_metrics_snapshot(m)
        assert snap.read_attempts == 104
        assert snap.stream_read_failures == 4
        assert snap.frames_dropped == 15
        assert snap.frames_skipped_cadence == 10
        assert snap.drop_rate_percent == 15.0
        assert snap.decode_failure_rate_percent == 3.85
        assert snap.avg_inference_ms == 12.5
        assert snap.processing_fps == 20.0
        assert snap.last_successful_inference_at == NOW
        assert snap.reconnect_count == 2

    def test_zero_frames_read(self):
        snap = build_metrics_snapshot(JobMetrics(frames_read=0, frames_failed=5))
        assert snap.decode_failure_rate_percent == 0.0

    def test_decode_failure_rate_uses_read_attempts(self):
        snap = build_metrics_snapshot(JobMetrics(frames_read=0, stream_read_failures=5))
        assert snap.read_attempts == 5
        assert snap.decode_failure_rate_percent == 100.0


# ── assess_stream ──────────────────────────────────────────────────────────


class TestAssessStreamOnline:
    def test_live_stream_without_runtime_signal_is_offline(self):
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(db_status="live"))
        assert report.is_online is False
        assert report.state_basis == HealthStateBasis.NO_RUNTIME_SIGNAL
        assert any(a.signal == HealthSignal.STALE_STREAM for a in report.alerts)

    def test_offline_stream_with_active_job_is_online(self):
        job = _make_job_state()
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(db_status="offline", job_state=job))
        assert report.is_online is True
        assert report.state_basis == HealthStateBasis.ACTIVE_JOB

    def test_disabled_stream_is_offline(self):
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(is_enabled=False))
        assert report.is_online is False
        assert report.state_basis == HealthStateBasis.DISABLED

    def test_offline_without_job_is_offline(self):
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(db_status="offline"))
        assert report.is_online is False
        assert report.state_basis == HealthStateBasis.NO_RUNTIME_SIGNAL

    def test_recent_heartbeat_without_active_job_is_online(self):
        assessor = HealthAssessor()
        report = assessor.assess_stream(
            **_stream_kwargs(db_status="offline", last_heartbeat_at=NOW - timedelta(seconds=5))
        )
        assert report.is_online is True
        assert report.state_basis == HealthStateBasis.RECENT_HEARTBEAT


class TestAssessStreamAlerts:
    def test_stream_error_produces_critical(self):
        assessor = HealthAssessor()
        report = assessor.assess_stream(
            **_stream_kwargs(db_status="error", last_error="Connection refused")
        )
        assert any(a.signal == HealthSignal.STREAM_ERROR for a in report.alerts)
        assert any(a.severity == AlertSeverity.CRITICAL for a in report.alerts)

    def test_stale_heartbeat_warning(self):
        old_hb = NOW - timedelta(seconds=60)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(last_heartbeat_at=old_hb))
        stale = [a for a in report.alerts if a.signal == HealthSignal.STALE_STREAM]
        assert len(stale) == 1
        assert stale[0].severity == AlertSeverity.WARNING

    def test_fresh_heartbeat_no_stale_alert(self):
        fresh_hb = NOW - timedelta(seconds=5)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(last_heartbeat_at=fresh_hb))
        assert not any(a.signal == HealthSignal.STALE_STREAM for a in report.alerts)

    def test_reconnecting_warning(self):
        metrics = JobMetrics(frames_read=50, frames_processed=40, reconnect_count=3)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        recon = [a for a in report.alerts if a.signal == HealthSignal.RECONNECTING]
        assert len(recon) == 1
        assert recon[0].severity == AlertSeverity.WARNING

    def test_reconnecting_critical_above_5(self):
        metrics = JobMetrics(frames_read=50, frames_processed=40, reconnect_count=8)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        recon = [a for a in report.alerts if a.signal == HealthSignal.RECONNECTING]
        assert recon[0].severity == AlertSeverity.CRITICAL

    def test_high_decode_failure_rate(self):
        metrics = JobMetrics(frames_read=100, frames_processed=90, stream_read_failures=10)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        failures = [a for a in report.alerts if a.signal == HealthSignal.HIGH_DECODE_FAILURE_RATE]
        assert len(failures) == 1

    def test_no_failure_alert_below_threshold(self):
        metrics = JobMetrics(frames_read=100, frames_processed=97, stream_read_failures=2)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert not any(a.signal == HealthSignal.HIGH_DECODE_FAILURE_RATE for a in report.alerts)

    def test_high_frame_drop_rate(self):
        metrics = JobMetrics(frames_read=100, frames_dropped_backpressure=25, frames_skipped=10)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        drops = [a for a in report.alerts if a.signal == HealthSignal.HIGH_FRAME_DROP_RATE]
        assert len(drops) == 1

    def test_cadence_skips_do_not_count_as_drops(self):
        metrics = JobMetrics(frames_read=100, frames_skipped=60, frames_skipped_cadence=60)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert not any(a.signal == HealthSignal.HIGH_FRAME_DROP_RATE for a in report.alerts)

    def test_low_fps_alert(self):
        metrics = JobMetrics(frames_read=50, frames_processed=50, avg_fps=5.0)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(fps_hint=25.0, job_state=job))
        low = [a for a in report.alerts if a.signal == HealthSignal.LOW_FPS]
        assert len(low) == 1

    def test_no_low_fps_when_above_threshold(self):
        metrics = JobMetrics(frames_read=50, frames_processed=50, avg_fps=20.0)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(fps_hint=25.0, job_state=job))
        assert not any(a.signal == HealthSignal.LOW_FPS for a in report.alerts)

    def test_no_low_fps_without_hint(self):
        metrics = JobMetrics(frames_read=50, frames_processed=50, avg_fps=1.0)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(fps_hint=None, job_state=job))
        assert not any(a.signal == HealthSignal.LOW_FPS for a in report.alerts)

    def test_detector_no_output_placeholder(self):
        metrics = JobMetrics(frames_read=300, frames_processed=300, detections_total=0)
        job = _make_job_state(metrics=metrics, pipeline=PipelineFlags(detection=True))
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        no_det = [a for a in report.alerts if a.signal == HealthSignal.DETECTOR_NO_OUTPUT]
        assert len(no_det) == 1

    def test_detector_no_output_skipped_when_detection_disabled(self):
        metrics = JobMetrics(frames_read=300, frames_processed=300, detections_total=0)
        job = _make_job_state(metrics=metrics, pipeline=PipelineFlags(detection=False))
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert not any(a.signal == HealthSignal.DETECTOR_NO_OUTPUT for a in report.alerts)

    def test_rate_checks_skipped_below_min_frames(self):
        metrics = JobMetrics(frames_read=0, stream_read_failures=4)  # 4 attempts; below threshold of 10
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert not any(a.signal == HealthSignal.HIGH_DECODE_FAILURE_RATE for a in report.alerts)


class TestAssessStreamMetrics:
    def test_active_job_populates_metrics(self):
        metrics = JobMetrics(frames_read=100, frames_processed=80, avg_fps=15.0)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert report.metrics is not None
        assert report.active_job_id == job.job_id

    def test_no_job_means_no_metrics(self):
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs())
        assert report.metrics is None
        assert report.active_job_id is None
        assert report.latest_job_id is None

    def test_stopped_job_exposes_latest_runtime_diagnostics(self):
        job = _make_job_state(status=JobStatus.STOPPED)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert report.metrics is not None
        assert report.active_job_id is None
        assert report.latest_job_id == job.job_id
        assert report.latest_job_status == JobStatus.STOPPED.value

    def test_failed_job_exposes_latest_error_message(self):
        job = _make_job_state(status=JobStatus.FAILED)
        job.error_message = "rtsp timeout"
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert report.latest_job_status == JobStatus.FAILED.value
        assert report.latest_job_error_message == "rtsp timeout"


class TestAssessStreamHeartbeat:
    def test_job_heartbeat_preferred_over_db(self):
        db_hb = NOW - timedelta(minutes=10)
        job_hb = NOW - timedelta(seconds=2)
        job = _make_job_state(heartbeat=job_hb)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(last_heartbeat_at=db_hb, job_state=job))
        assert report.last_heartbeat_at == job_hb

    def test_db_heartbeat_used_when_no_job(self):
        db_hb = NOW - timedelta(seconds=10)
        assessor = HealthAssessor()
        report = assessor.assess_stream(**_stream_kwargs(last_heartbeat_at=db_hb))
        assert report.last_heartbeat_at == db_hb
        assert report.last_heartbeat_age_seconds == 10.0


# ── assess_camera ────────────────────────────────────────────────────────────


class TestAssessCamera:
    def _make_stream_report(
        self, *, is_online: bool = True, is_enabled: bool = True, alerts=None
    ) -> dict:
        return dict(
            stream_id=uuid.uuid4(),
            stream_name="s",
            camera_id=uuid.uuid4(),
            source_type="rtsp",
            db_status="live" if is_online else "offline",
            is_enabled=is_enabled,
            is_online=is_online,
            state_basis=HealthStateBasis.RECENT_HEARTBEAT if is_online else HealthStateBasis.NO_RUNTIME_SIGNAL,
            alerts=alerts or [],
        )

    def test_all_online_no_alerts(self):
        from services.health.schemas import StreamHealthReport

        sr = StreamHealthReport(**self._make_stream_report())
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-001",
            camera_name="Test Camera",
            camera_status="active",
            stream_reports=[sr],
        )
        assert report.overall_health == HealthSignal.ONLINE

    def test_no_streams_is_offline(self):
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-002",
            camera_name="Empty Camera",
            camera_status="active",
            stream_reports=[],
        )
        assert report.overall_health == HealthSignal.OFFLINE

    def test_all_offline_is_offline(self):
        from services.health.schemas import StreamHealthReport

        sr = StreamHealthReport(**self._make_stream_report(is_online=False))
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-003",
            camera_name="Down Camera",
            camera_status="active",
            stream_reports=[sr],
        )
        assert report.overall_health == HealthSignal.OFFLINE

    def test_warning_alerts_make_degraded(self):
        from services.health.schemas import HealthAlert, StreamHealthReport

        alert = HealthAlert(
            signal=HealthSignal.LOW_FPS,
            severity=AlertSeverity.WARNING,
            message="Low FPS",
        )
        sr = StreamHealthReport(**self._make_stream_report(alerts=[alert]))
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-004",
            camera_name="Slow Camera",
            camera_status="active",
            stream_reports=[sr],
        )
        assert report.overall_health == HealthSignal.DEGRADED

    def test_critical_alerts_make_degraded(self):
        from services.health.schemas import HealthAlert, StreamHealthReport

        alert = HealthAlert(
            signal=HealthSignal.STREAM_ERROR,
            severity=AlertSeverity.CRITICAL,
            message="Error",
        )
        sr = StreamHealthReport(**self._make_stream_report(alerts=[alert]))
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-005",
            camera_name="Error Camera",
            camera_status="active",
            stream_reports=[sr],
        )
        assert report.overall_health == HealthSignal.DEGRADED

    def test_mixed_streams_degraded(self):
        from services.health.schemas import StreamHealthReport

        sr1 = StreamHealthReport(**self._make_stream_report(is_online=True))
        sr2 = StreamHealthReport(**self._make_stream_report(is_online=False))
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-006",
            camera_name="Mixed Camera",
            camera_status="active",
            stream_reports=[sr1, sr2],
        )
        assert report.overall_health == HealthSignal.DEGRADED

    def test_alerts_aggregated_from_streams(self):
        from services.health.schemas import HealthAlert, StreamHealthReport

        a1 = HealthAlert(signal=HealthSignal.LOW_FPS, severity=AlertSeverity.WARNING, message="1")
        a2 = HealthAlert(signal=HealthSignal.RECONNECTING, severity=AlertSeverity.WARNING, message="2")
        sr1 = StreamHealthReport(**self._make_stream_report(alerts=[a1]))
        sr2 = StreamHealthReport(**self._make_stream_report(alerts=[a2]))
        assessor = HealthAssessor()
        report = assessor.assess_camera(
            camera_id=uuid.uuid4(),
            camera_code="CAM-007",
            camera_name="Multi-alert Camera",
            camera_status="active",
            stream_reports=[sr1, sr2],
        )
        assert len(report.alerts) == 2


# ── assess_dashboard ────────────────────────────────────────────────────────


class TestAssessDashboard:
    def test_dashboard_counts(self):
        from services.health.schemas import CameraHealthReport, HealthAlert, StreamHealthReport

        online_cam = CameraHealthReport(
            camera_id=uuid.uuid4(),
            camera_code="CAM-A",
            camera_name="Online",
            camera_status="active",
            overall_health=HealthSignal.ONLINE,
            streams=[StreamHealthReport(
                stream_id=uuid.uuid4(), stream_name="s", camera_id=uuid.uuid4(),
                source_type="rtsp", db_status="live", is_enabled=True, is_online=True,
                state_basis=HealthStateBasis.RECENT_HEARTBEAT,
            )],
        )
        degraded_cam = CameraHealthReport(
            camera_id=uuid.uuid4(),
            camera_code="CAM-B",
            camera_name="Degraded",
            camera_status="active",
            overall_health=HealthSignal.DEGRADED,
            alerts=[HealthAlert(
                signal=HealthSignal.LOW_FPS, severity=AlertSeverity.WARNING, message="slow",
            )],
            streams=[StreamHealthReport(
                stream_id=uuid.uuid4(), stream_name="s", camera_id=uuid.uuid4(),
                source_type="rtsp", db_status="live", is_enabled=True, is_online=True,
                state_basis=HealthStateBasis.RECENT_HEARTBEAT,
            )],
        )
        offline_cam = CameraHealthReport(
            camera_id=uuid.uuid4(),
            camera_code="CAM-C",
            camera_name="Offline",
            camera_status="active",
            overall_health=HealthSignal.OFFLINE,
        )

        assessor = HealthAssessor()
        dashboard = assessor.assess_dashboard(
            [online_cam, degraded_cam, offline_cam],
            active_jobs=2,
            now=NOW,
        )

        assert dashboard.total_cameras == 3
        assert dashboard.cameras_online == 1
        assert dashboard.cameras_degraded == 1
        assert dashboard.cameras_offline == 1
        assert dashboard.total_streams == 2
        assert dashboard.streams_online == 2
        assert dashboard.active_jobs == 2
        assert dashboard.warning_alerts == 1
        assert dashboard.critical_alerts == 0
        assert dashboard.assessed_at == NOW


# ── Custom thresholds ──────────────────────────────────────────────────────


class TestCustomThresholds:
    def test_custom_stale_threshold(self):
        thresholds = HealthThresholds(stale_heartbeat_seconds=10.0)
        assessor = HealthAssessor(thresholds=thresholds)
        hb = NOW - timedelta(seconds=15)
        report = assessor.assess_stream(**_stream_kwargs(last_heartbeat_at=hb))
        assert any(a.signal == HealthSignal.STALE_STREAM for a in report.alerts)

    def test_custom_stale_threshold_no_alert_when_within(self):
        thresholds = HealthThresholds(stale_heartbeat_seconds=120.0)
        assessor = HealthAssessor(thresholds=thresholds)
        hb = NOW - timedelta(seconds=60)
        report = assessor.assess_stream(**_stream_kwargs(last_heartbeat_at=hb))
        assert not any(a.signal == HealthSignal.STALE_STREAM for a in report.alerts)

    def test_custom_drop_rate_threshold(self):
        thresholds = HealthThresholds(high_drop_rate_percent=5.0)
        metrics = JobMetrics(frames_read=100, frames_dropped_backpressure=8, frames_skipped=0)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor(thresholds=thresholds)
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert any(a.signal == HealthSignal.HIGH_FRAME_DROP_RATE for a in report.alerts)

    def test_custom_decode_failure_threshold(self):
        thresholds = HealthThresholds(high_decode_failure_rate_percent=2.0)
        metrics = JobMetrics(frames_read=100, stream_read_failures=3)
        job = _make_job_state(metrics=metrics)
        assessor = HealthAssessor(thresholds=thresholds)
        report = assessor.assess_stream(**_stream_kwargs(job_state=job))
        assert any(a.signal == HealthSignal.HIGH_DECODE_FAILURE_RATE for a in report.alerts)
