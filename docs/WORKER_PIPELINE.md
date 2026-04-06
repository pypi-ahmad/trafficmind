# Worker Pipeline

The **worker pipeline** is the first real end-to-end processing path in TrafficMind's hot path. It connects a frame source to the full inference stack and persists results to the database in a single deterministic loop.

## Pipeline stages

```
frame/video source
  → detection  (YOLO)
  → tracking   (IoU / ByteTrack / Centroid)
  → OCR        (PaddleOCR, optional)
  → signals    (HSV classifier, optional)
  → rules      (zone-based evaluators)
  → persistence (DetectionEvent, PlateRead, ViolationEvent → DB)
```

Each stage is controlled by `PipelineFlags`. Disable any stage that isn't needed for the current job.

## Modules

| File | Responsibility |
|---|---|
| `services/streams/worker_pipeline.py` | Integrated runner: `run_worker_pipeline()` + CLI |
| `services/streams/pipeline.py` | `FramePipeline` — composable per-frame inference |
| `services/streams/persist.py` | `persist_frame_result()` — writes frame artifacts to DB |
| `services/streams/frame_source.py` | `FrameSource` ABC + `OpenCvSource`, `TestPatternSource` |
| `services/streams/schemas.py` | `JobSpec`, `PipelineFlags`, `SourceKind` |

## Usage

### Programmatic

```python
from services.streams.worker_pipeline import run_worker_pipeline
from services.streams.schemas import PipelineFlags, SourceKind

summary = await run_worker_pipeline(
    source_kind=SourceKind.FILE,
    source_uri="intersection_clip.mp4",
    database_url="sqlite+aiosqlite:///trafficmind.db",
    zone_configs=[stop_line_zone, crosswalk_zone],
    max_frames=500,
    flags=PipelineFlags(detection=True, tracking=True, ocr=True, rules=True),
)

print(f"Processed {summary.frames_processed} frames, "
      f"{summary.total_violations} violations, "
      f"{summary.persistence.detection_events} detection rows")
```

### CLI

```bash
# Synthetic test pattern (no GPU, no model files)
python -m services.streams.worker_pipeline --source-kind test --max-frames 30

# Video file
python -m services.streams.worker_pipeline \
  --source-uri video.mp4 \
  --database-url "sqlite+aiosqlite:///trafficmind.db" \
  --max-frames 500 --enable-ocr

# RTSP stream
python -m services.streams.worker_pipeline \
  --source-kind rtsp \
  --source-uri "rtsp://192.168.1.100:554/stream" \
  --database-url "postgresql+asyncpg://user:pass@localhost/trafficmind"
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--source-kind` | `test` | `test`, `file`, or `rtsp` |
| `--source-uri` | `test://pattern` | Path or URI for the frame source |
| `--database-url` | `sqlite+aiosqlite:///trafficmind.db` | Async SQLAlchemy URL |
| `--camera-code` | `WORKER-001` | Camera code (creates Camera row if needed) |
| `--max-frames` | `30` | Stop after N frames |
| `--frame-step` | `1` | Process every Nth frame |
| `--log-every` | `10` | Log progress every N frames (0 = off) |
| `--disable-detection` | off | Skip detection stage |
| `--disable-tracking` | off | Skip tracking stage |
| `--enable-ocr` | off | Run PaddleOCR on detected plates |

## Testing

The integrated test suite:

```bash
python -m pytest tests/smoke/test_worker_pipeline.py -v
```

Tests use stub backends (`_PipelineDetector`, `_PipelineTracker`, `_PipelineOcrEngine`) that produce a canned 5-frame trajectory. No GPU or model files needed.

| Test | Verifies |
|---|---|
| `test_full_pipeline_processes_and_persists` | Summary metrics: frame counts, detection/track/plate/violation totals, DB row counts |
| `test_pipeline_db_rows_are_correct` | Actual DB rows: Camera, CameraStream, DetectionEvent, PlateRead, ViolationEvent field values and FK linkage |
| `test_pipeline_without_zones_produces_no_violations` | No zones → no violations, no plates when OCR disabled |
| `test_pipeline_summary_consistency` | Internal consistency of summary vs DB counts |

## Design decisions

1. **No LangGraph** — the hot path is fully deterministic. Workflows consume persisted events after the fact.
2. **No orchestration layer** — a single `async` function, not a job queue. Queue/concurrency comes later.
3. **Factory overrides** — detector, tracker, and OCR engine accept factory callables so tests can inject stubs without touching the import graph.
4. **Auto-bootstrap** — creates Camera + CameraStream FK targets and DB schema on startup for local dev convenience.

## What this does NOT cover (yet)

- Multi-camera / multi-stream concurrency (see `StreamOrchestrator`)
- RTSP reconnection and health monitoring
- Model hot-reload or version switching at runtime
- Evidence snapshot capture and storage
- Frame-level metric export (Prometheus / OpenTelemetry)
- GPU batching or async inference
