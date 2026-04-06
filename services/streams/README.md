# Streams

Stream ingestion orchestration, worker lifecycle management, and runtime metrics.

## Entry Point

`StreamOrchestrator` in [orchestrator.py](orchestrator.py) — manages workers, enforces concurrency limits, and maintains the in-memory job registry.

## Components

- `StreamWorker` — async frame-processing loop with cadence control, max-FPS capping, frame dropping for live sources, heartbeat recording, and graceful stop/pause/resume
- `FramePipeline` — composable stage pipeline (detection → tracking → signals)
- `FrameSource` — pluggable frame sources: test pattern, file, RTSP, upload
- `JobSpec` / `JobState` / `JobStatus` — typed state machine with validated transitions

## Runtime Metrics

Each running worker maintains `JobMetrics`:

- frames processed / dropped / errored
- processing FPS and latency
- heartbeat timestamps
- reconnection counts

## Perception Events

`events.py` constructs structured tracked-object event batches from pipeline output for downstream rule evaluation and evidence generation. Persistence decisions are left to consumers so the database is not flooded with per-frame data.

## CLI

```bash
# test-pattern stream (no GPU needed)
python -m services.streams --source-kind test --max-frames 60 --disable-detection --disable-tracking

# local video file
python -m services.streams --source-kind file --source-uri path/to/video.mp4 --max-processing-fps 10
```

## Limitations

- Worker state is in-memory only; no persistent job recovery across restarts.
- RTSP reconnection is basic; production deployments may need more sophisticated backoff.
