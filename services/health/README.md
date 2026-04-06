# Health

Stateless health assessment for cameras and streams.

## Entry Point

`HealthAssessor` in [assessor.py](assessor.py) — receives pre-loaded runtime data (job states, metrics, timestamps) and produces typed health reports. It never queries the database directly.

## Health Signals

11 signals defined in `HealthSignal`:

- `STREAM_ERROR` — stream reported an error state
- `STALE_HEARTBEAT` — last heartbeat exceeds threshold
- `LIVE_WITHOUT_HEARTBEAT` — stream marked live but no heartbeat received
- `RECONNECTING` — stream is in reconnection loop (warning and critical thresholds)
- `HIGH_DECODE_FAILURE_RATE` — frame decode failures above threshold
- `HIGH_FRAME_DROP_RATE` — frame drops from backpressure above threshold
- `LOW_FPS` — actual FPS below expected minimum
- `DETECTOR_NO_OUTPUT` — detection pipeline producing no outputs (threshold-gated)
- `OCR_FAILURE_RATE_HIGH` — placeholder, gated until OCR failure counts are wired

## Output Types

- `StreamHealthReport` — per-stream health with alerts and state basis
- `CameraHealthReport` — worst-case aggregate across a camera's streams
- `HealthDashboard` — aggregate counts and per-camera details for API rendering

## Configuration

All thresholds are tuneable via `HealthThresholds`.

## Limitations

- `OCR_FAILURE_RATE_HIGH` and `DETECTOR_NO_OUTPUT` are defined but gated behind placeholder flags until their upstream data sources are integrated.
