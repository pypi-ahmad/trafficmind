# Camera Health & Observability

Operational health monitoring for cameras and stream-processing jobs.

## Design Principle

Every health signal traces to a **real data source** already maintained by the platform:

| Signal source | Where it lives | Updated by |
|---|---|---|
| Stream DB status | `CameraStream.status` | API writes, future stream sync |
| Heartbeat timestamp | `CameraStream.last_heartbeat_at` / `JobState.last_heartbeat_at` | `StreamWorker._touch_heartbeat()` |
| Frame read / decode failures | `JobMetrics.stream_read_failures` | Worker live-source `source.read()` failure path |
| Reconnect attempts | `JobMetrics.reconnect_count` | Worker reconnect loop |
| Processing failures | `JobMetrics.frames_failed` | Worker `process_frame` exception handler |
| Frame drops (backpressure) | `JobMetrics.frames_dropped_backpressure` | Worker backpressure logic |
| Processing FPS | `JobMetrics.avg_fps` | Worker sliding-window calculation |
| Inference latency | `JobMetrics.avg_inference_ms` | Worker sliding-window calculation |
| Detection count | `JobMetrics.detections_total` | Worker `_record_metrics` |
| Last successful inference | `JobMetrics.last_successful_inference_at` | Worker `_record_metrics` |

No synthetic or simulated metrics are generated.

## Health Signals

### Stream-Level Signals

| Signal | Meaning | Source |
|---|---|---|
| `online` | Stream has an active job or a recent heartbeat proving current runtime activity | `JobState.is_active` or fresh heartbeat |
| `offline` | No recent runtime signal is available for the stream | Missing active job and stale/missing heartbeat |
| `degraded` | Online but with active warnings or critical alerts | Derived from alert list |
| `stale_stream` | Last heartbeat exceeds threshold (default 30s) | `last_heartbeat_at` age |
| `low_fps` | Processing FPS is below 50% of the stream's `fps_hint` | `JobMetrics.avg_fps` vs `CameraStream.fps_hint` |
| `high_frame_drop_rate` | Backpressure-dropped frames exceed 20% of successfully read frames | `frames_dropped_backpressure / frames_read` |
| `high_decode_failure_rate` | Frame acquisition failures exceed 5% of read attempts | `stream_read_failures / (frames_read + stream_read_failures)` |
| `reconnecting` | Stream source has reconnected one or more times | `JobMetrics.reconnect_count` |
| `stream_error` | DB stream status is `error` | `CameraStream.status` |
| `detector_no_output` | *Placeholder* — detection enabled but zero detections after 200+ frames | `detections_total == 0` after threshold |
| `ocr_failure_rate_high` | *Placeholder* — not wired until OCR tracks per-call failures | — |

Intentional cadence skips are tracked separately and are **not** counted as dropped frames. This keeps operator drop-rate alarms focused on overload/backpressure instead of configured sampling.

The API also exposes `state_basis` so operators can see whether a stream is online because of an active job, a recent heartbeat, or offline because there is no runtime signal.

### Camera-Level Health

Camera health is the **worst-case aggregate** across all its streams:

| Condition | Overall health |
|---|---|
| All enabled streams online, no warnings | `online` |
| Some streams online but warnings or not all online | `degraded` |
| Any critical alert | `degraded` |
| No streams online | `offline` |

## Alert Severity

| Level | Meaning | Examples |
|---|---|---|
| `info` | Informational, no action needed | — (reserved for future use) |
| `warning` | Degraded quality, should investigate | Stale heartbeat, low FPS, high drop rate, reconnecting (≤5 times), elevated decode failures |
| `critical` | Operational failure, needs attention | Stream error, decode failure rate >20%, reconnecting >5 times |

## Configurable Thresholds

All thresholds are tuneable via `HealthThresholds`:

| Parameter | Default | Description |
|---|---|---|
| `stale_heartbeat_seconds` | 30.0 | Seconds before a heartbeat is stale |
| `low_fps_ratio` | 0.5 | FPS must be ≥ this fraction of `fps_hint` |
| `high_drop_rate_percent` | 20.0 | Frame drop rate trigger |
| `high_decode_failure_rate_percent` | 5.0 | Frame acquisition/decode failure rate trigger |
| `min_frames_for_rate` | 10 | Minimum frames before rate checks activate |
| `detector_no_output_frames` | 200 | Frames before flagging zero detections |

## API Endpoints

### Dashboard

```
GET /api/v1/observability/dashboard
GET /api/v1/observability/dashboard?status=active
```

Returns aggregate health for all cameras (optionally filtered by camera status). Dashboard-ready structure with counts for online/offline/degraded cameras, stream counts, alert tallies, and per-camera detail including per-stream health.

### Per-Camera Health

```
GET /api/v1/observability/cameras/{camera_id}/health
```

Returns health for a single camera and all its streams. 404 if camera not found.

### Per-Stream Health

```
GET /api/v1/observability/streams/{stream_id}/health
```

Returns health for a single stream including active job metrics. 404 if stream not found.

If a stream has a recent failed or stopped job, the report still exposes the latest job status and error message so operators can inspect recent runtime history without waiting for a new job to start.

## Job Metrics Snapshot

When a stream has an active job, the health report includes a `JobMetricsSnapshot`:

| Field | Source |
|---|---|
| `read_attempts` | `frames_read + stream_read_failures` |
| `stream_read_failures` | `JobMetrics.stream_read_failures` |
| `frames_processed` | `JobMetrics.frames_processed` |
| `frames_dropped` | `JobMetrics.frames_dropped_backpressure` |
| `frames_skipped_cadence` | `JobMetrics.frames_skipped_cadence` |
| `frames_failed` | `JobMetrics.frames_failed` (pipeline processing failures) |
| `frames_read` | `JobMetrics.frames_read` |
| `drop_rate_percent` | Computed: `frames_dropped / frames_read × 100` |
| `decode_failure_rate_percent` | Computed: `stream_read_failures / read_attempts × 100` |
| `avg_inference_ms` | `JobMetrics.avg_inference_ms` |
| `processing_fps` | `JobMetrics.avg_fps` |
| `last_successful_inference_at` | `JobMetrics.last_successful_inference_at` |
| `reconnect_count` | `JobMetrics.reconnect_count` |

## State Definition Notes

- Persisted `CameraStream.status` is exposed for context, but it does **not** by itself make a stream online.
- A stream marked `live` with no active job and no recent heartbeat is reported as offline with a stale/no-runtime-signal warning.
- This avoids treating administrative status as telemetry.

## Placeholder Signals

These signals are defined but not active because their data sources are not yet wired:

### `ocr_failure_rate_high`

**Blocked on:** `services/ocr/pipeline.py` does not currently track per-call success/failure counts. When it does, the assessor can compute `ocr_failures / ocr_attempts` and surface this signal.

### `detector_no_output`

**Partially wired:** If detection is enabled and `detections_total == 0` after processing `detector_no_output_frames` frames, this fires. This is a coarse anomaly indicator (e.g., camera pointed at a wall, model loading failure). It does not detect subtle accuracy degradation.

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│ CameraStream │     │  StreamWorker    │     │   HealthAssessor     │
│   (DB ORM)   │────▶│  JobState        │────▶│  assess_stream()     │
│  .status     │     │  .metrics        │     │  assess_camera()     │
│  .heartbeat  │     │  .last_heartbeat │     │  assess_dashboard()  │
└─────────────┘     └──────────────────┘     └──────────┬───────────┘
                                                        │
                                              ┌─────────▼───────────┐
                                              │  API Routes         │
                                              │  /observability/*   │
                                              └─────────────────────┘
```

The assessor is **stateless and pure** — it receives data, returns health reports. No DB queries or I/O happen inside the assessor.
