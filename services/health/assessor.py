"""Health assessor — derives health signals from existing runtime data.

Every signal produced here traces back to a real counter or timestamp
already maintained by ``StreamWorker`` / ``CameraStream``.  If a data
source does not exist yet (e.g. per-OCR-call failure counts) the check
is gated behind a ``placeholder`` flag and documented as such.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from services.health.schemas import (
    AlertSeverity,
    CameraHealthReport,
    HealthAlert,
    HealthDashboard,
    HealthSignal,
    HealthStateBasis,
    HealthThresholds,
    JobMetricsSnapshot,
    StreamHealthReport,
)
from services.streams.schemas import JobMetrics, JobState

# ── Helpers ─────────────────────────────────────────────────────────────────


def _safe_rate(numerator: int, denominator: int) -> float:
    """Return percentage, clamped to [0, 100]."""
    if denominator <= 0:
        return 0.0
    return min(100.0, round(numerator / denominator * 100.0, 2))


def _heartbeat_age(heartbeat: datetime | None, now: datetime) -> float | None:
    if heartbeat is None:
        return None
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, round((now - heartbeat).total_seconds(), 2))


# ── Metric snapshot builder ────────────────────────────────────────────────


def build_metrics_snapshot(m: JobMetrics) -> JobMetricsSnapshot:
    """Project ``JobMetrics`` into an operator-friendly snapshot with rates."""
    read_attempts = m.frames_read + m.stream_read_failures
    dropped = m.frames_dropped_backpressure
    return JobMetricsSnapshot(
        read_attempts=read_attempts,
        stream_read_failures=m.stream_read_failures,
        frames_processed=m.frames_processed,
        frames_dropped=dropped,
        frames_skipped_cadence=m.frames_skipped_cadence,
        frames_failed=m.frames_failed,
        frames_read=m.frames_read,
        drop_rate_percent=_safe_rate(dropped, m.frames_read),
        decode_failure_rate_percent=_safe_rate(m.stream_read_failures, read_attempts),
        avg_inference_ms=m.avg_inference_ms,
        processing_fps=m.avg_fps,
        last_successful_inference_at=m.last_successful_inference_at,
        reconnect_count=m.reconnect_count,
    )


# ── Stream-level assessment ─────────────────────────────────────────────────


class HealthAssessor:
    """Stateless assessor — call once per evaluation cycle.

    ``assess_stream`` and ``assess_camera`` are the primary entry points.
    They accept already-loaded data (no DB/IO inside) so they are easy to
    test in isolation.
    """

    def __init__(self, thresholds: HealthThresholds | None = None) -> None:
        self._t = thresholds or HealthThresholds()

    # -- stream ---------------------------------------------------------------

    def assess_stream(
        self,
        *,
        stream_id: uuid.UUID,
        stream_name: str,
        camera_id: uuid.UUID,
        source_type: str,
        db_status: str,
        is_enabled: bool,
        last_heartbeat_at: datetime | None,
        last_error: str | None,
        fps_hint: float | None,
        job_state: JobState | None,
        now: datetime | None = None,
    ) -> StreamHealthReport:
        now = now or datetime.now(timezone.utc)
        alerts: list[HealthAlert] = []

        # Pick the freshest heartbeat between DB and job
        effective_heartbeat = last_heartbeat_at
        if job_state and job_state.last_heartbeat_at:
            if effective_heartbeat is None or job_state.last_heartbeat_at > effective_heartbeat:
                effective_heartbeat = job_state.last_heartbeat_at

        hb_age = _heartbeat_age(effective_heartbeat, now)

        # Determine online state from real runtime signals only.
        is_online, state_basis = self._state_basis(
            is_enabled=is_enabled,
            heartbeat_age_seconds=hb_age,
            job_state=job_state,
            stale_heartbeat_seconds=self._t.stale_heartbeat_seconds,
        )

        # Surface latest job diagnostics even when the job is no longer active.
        metrics: JobMetricsSnapshot | None = None
        active_job_id: uuid.UUID | None = None
        latest_job_id: uuid.UUID | None = None
        latest_job_status: str | None = None
        latest_job_error_message: str | None = None
        latest_job_started_at: datetime | None = None
        latest_job_stopped_at: datetime | None = None
        if job_state is not None:
            latest_job_id = job_state.job_id
            latest_job_status = job_state.status.value
            latest_job_error_message = job_state.error_message
            latest_job_started_at = job_state.started_at
            latest_job_stopped_at = job_state.stopped_at
            metrics = build_metrics_snapshot(job_state.metrics)
            if job_state.is_active:
                active_job_id = job_state.job_id

        # -- alert checks ----------------------------------------------------

        # 1. Stream error (from DB status)
        if db_status == "error":
            alerts.append(HealthAlert(
                signal=HealthSignal.STREAM_ERROR,
                severity=AlertSeverity.CRITICAL,
                message=f"Stream is in error state: {last_error or 'unknown'}",
                detail={"last_error": last_error},
            ))

        if (
            is_enabled
            and state_basis == HealthStateBasis.NO_RUNTIME_SIGNAL
            and db_status in {"live", "connecting"}
            and effective_heartbeat is None
        ):
            alerts.append(HealthAlert(
                signal=HealthSignal.STALE_STREAM,
                severity=AlertSeverity.WARNING,
                message="Stream is marked live/connecting but has no recent runtime heartbeat.",
                detail={"db_status": db_status, "last_heartbeat_at": effective_heartbeat},
            ))

        # 2. Stale heartbeat
        if is_enabled and hb_age is not None and hb_age > self._t.stale_heartbeat_seconds:
            alerts.append(HealthAlert(
                signal=HealthSignal.STALE_STREAM,
                severity=AlertSeverity.WARNING,
                message=f"No heartbeat for {hb_age:.0f}s (threshold {self._t.stale_heartbeat_seconds:.0f}s).",
                detail={"heartbeat_age_seconds": hb_age, "threshold_seconds": self._t.stale_heartbeat_seconds},
            ))

        # 3. Reconnecting
        if metrics and metrics.reconnect_count > 0 and job_state and job_state.is_active:
            sev = AlertSeverity.CRITICAL if metrics.reconnect_count > 5 else AlertSeverity.WARNING
            alerts.append(HealthAlert(
                signal=HealthSignal.RECONNECTING,
                severity=sev,
                message=f"Stream has reconnected {metrics.reconnect_count} time(s).",
                detail={"reconnect_count": metrics.reconnect_count},
            ))

        # Rate-based checks only after enough samples.
        if metrics and metrics.read_attempts >= self._t.min_frames_for_rate:
            # 4. Frame decode failures
            if metrics.decode_failure_rate_percent > self._t.high_decode_failure_rate_percent:
                sev = AlertSeverity.CRITICAL if metrics.decode_failure_rate_percent > 20.0 else AlertSeverity.WARNING
                alerts.append(HealthAlert(
                    signal=HealthSignal.HIGH_DECODE_FAILURE_RATE,
                    severity=sev,
                    message=(
                        f"Frame decode failure rate {metrics.decode_failure_rate_percent:.1f}% "
                        f"exceeds {self._t.high_decode_failure_rate_percent:.0f}%.") ,
                    detail={
                        "decode_failure_rate_percent": metrics.decode_failure_rate_percent,
                        "stream_read_failures": metrics.stream_read_failures,
                        "read_attempts": metrics.read_attempts,
                    },
                ))

            # 5. High frame drop rate
        if metrics and metrics.frames_read >= self._t.min_frames_for_rate:
            if metrics.drop_rate_percent > self._t.high_drop_rate_percent:
                alerts.append(HealthAlert(
                    signal=HealthSignal.HIGH_FRAME_DROP_RATE,
                    severity=AlertSeverity.WARNING,
                    message=f"Frame drop rate {metrics.drop_rate_percent:.1f}% exceeds {self._t.high_drop_rate_percent:.0f}%.",
                    detail={
                        "drop_rate_percent": metrics.drop_rate_percent,
                        "frames_dropped": metrics.frames_dropped,
                        "frames_read": metrics.frames_read,
                        "frames_skipped_cadence": metrics.frames_skipped_cadence,
                    },
                ))

        # 6. Low FPS (only when we have a baseline and active processing)
        if (
            metrics
            and fps_hint
            and fps_hint > 0
            and metrics.frames_processed >= self._t.min_frames_for_rate
        ):
            expected_fps = fps_hint * self._t.low_fps_ratio
            if 0 < metrics.processing_fps < expected_fps:
                alerts.append(HealthAlert(
                    signal=HealthSignal.LOW_FPS,
                    severity=AlertSeverity.WARNING,
                    message=f"Processing at {metrics.processing_fps:.1f} FPS, expected ≥{expected_fps:.1f} FPS ({self._t.low_fps_ratio:.0%} of {fps_hint:.0f} hint).",
                    detail={
                        "processing_fps": metrics.processing_fps,
                        "fps_hint": fps_hint,
                        "threshold_fps": expected_fps,
                    },
                ))

        # 7. Detector no-output anomaly (placeholder — sourced from real counter)
        if (
            metrics
            and metrics.frames_processed >= self._t.detector_no_output_frames
            and job_state
            and job_state.metrics.detections_total == 0
            and job_state.spec.pipeline.detection
        ):
            alerts.append(HealthAlert(
                signal=HealthSignal.DETECTOR_NO_OUTPUT,
                severity=AlertSeverity.WARNING,
                message=f"Processed {metrics.frames_processed} frames with detection enabled but zero detections.",
                detail={"frames_processed": metrics.frames_processed, "detections_total": 0},
            ))

        # 8. OCR failure rate — placeholder; no per-call failure counter wired yet.
        #    When services.ocr tracks failures we can activate this.

        return StreamHealthReport(
            stream_id=stream_id,
            stream_name=stream_name,
            camera_id=camera_id,
            source_type=source_type,
            db_status=db_status,
            is_enabled=is_enabled,
            is_online=is_online,
            state_basis=state_basis,
            last_heartbeat_at=effective_heartbeat,
            last_heartbeat_age_seconds=hb_age,
            last_error=last_error,
            alerts=alerts,
            active_job_id=active_job_id,
            latest_job_id=latest_job_id,
            latest_job_status=latest_job_status,
            latest_job_error_message=latest_job_error_message,
            latest_job_started_at=latest_job_started_at,
            latest_job_stopped_at=latest_job_stopped_at,
            metrics=metrics,
        )

    @staticmethod
    def _state_basis(
        *,
        is_enabled: bool,
        heartbeat_age_seconds: float | None,
        job_state: JobState | None,
        stale_heartbeat_seconds: float,
    ) -> tuple[bool, HealthStateBasis]:
        if not is_enabled:
            return False, HealthStateBasis.DISABLED
        if job_state and job_state.is_active:
            return True, HealthStateBasis.ACTIVE_JOB
        if heartbeat_age_seconds is not None and heartbeat_age_seconds <= stale_heartbeat_seconds:
            return True, HealthStateBasis.RECENT_HEARTBEAT
        return False, HealthStateBasis.NO_RUNTIME_SIGNAL

    # -- camera ---------------------------------------------------------------

    def assess_camera(
        self,
        *,
        camera_id: uuid.UUID,
        camera_code: str,
        camera_name: str,
        camera_status: str,
        stream_reports: list[StreamHealthReport],
    ) -> CameraHealthReport:
        # Aggregate alerts from all streams
        all_alerts: list[HealthAlert] = []
        for sr in stream_reports:
            all_alerts.extend(sr.alerts)

        # Determine overall health
        overall = self._overall_health(stream_reports, all_alerts)

        return CameraHealthReport(
            camera_id=camera_id,
            camera_code=camera_code,
            camera_name=camera_name,
            camera_status=camera_status,
            overall_health=overall,
            alerts=all_alerts,
            streams=stream_reports,
        )

    @staticmethod
    def _overall_health(
        streams: list[StreamHealthReport],
        alerts: list[HealthAlert],
    ) -> HealthSignal:
        if not streams:
            return HealthSignal.OFFLINE

        any_online = any(s.is_online for s in streams)
        all_online = all(s.is_online for s in streams if s.is_enabled)

        has_critical = any(a.severity == AlertSeverity.CRITICAL for a in alerts)
        has_warning = any(a.severity == AlertSeverity.WARNING for a in alerts)

        if not any_online:
            return HealthSignal.OFFLINE
        if has_critical or (any_online and not all_online):
            return HealthSignal.DEGRADED
        if has_warning:
            return HealthSignal.DEGRADED
        return HealthSignal.ONLINE

    # -- dashboard ------------------------------------------------------------

    def assess_dashboard(
        self,
        camera_reports: list[CameraHealthReport],
        *,
        active_jobs: int,
        now: datetime | None = None,
    ) -> HealthDashboard:
        now = now or datetime.now(timezone.utc)

        online = sum(1 for c in camera_reports if c.overall_health == HealthSignal.ONLINE)
        offline = sum(1 for c in camera_reports if c.overall_health == HealthSignal.OFFLINE)
        degraded = sum(1 for c in camera_reports if c.overall_health == HealthSignal.DEGRADED)

        total_streams = sum(len(c.streams) for c in camera_reports)
        streams_online = sum(
            sum(1 for s in c.streams if s.is_online)
            for c in camera_reports
        )

        all_alerts = [a for c in camera_reports for a in c.alerts]
        critical_count = sum(1 for a in all_alerts if a.severity == AlertSeverity.CRITICAL)
        warning_count = sum(1 for a in all_alerts if a.severity == AlertSeverity.WARNING)

        return HealthDashboard(
            assessed_at=now,
            total_cameras=len(camera_reports),
            cameras_online=online,
            cameras_offline=offline,
            cameras_degraded=degraded,
            total_streams=total_streams,
            streams_online=streams_online,
            active_jobs=active_jobs,
            critical_alerts=critical_count,
            warning_alerts=warning_count,
            cameras=camera_reports,
        )
