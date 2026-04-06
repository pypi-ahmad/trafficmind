# packages/shared_types

Canonical type definitions that cross service and application boundaries.

## What belongs here

Types in this package must satisfy **all** of these criteria:

1. **Cross-cutting** — used by two or more independent layers (API, workflow service, deterministic CV services, frontend contracts).
2. **Stable** — the shape changes infrequently and affects multiple consumers when it does.
3. **Leaf-level** — no imports from `apps/` or `services/`; only stdlib, Pydantic, and other `shared_types` modules.

### Current modules

| Module | Contents | Consumers |
|---|---|---|
| `enums.py` | Domain StrEnums: zone, detection-event, violation, rule, re-id, source-kind, workflow type/status | API ORM, rules, tracking, streams, workflow, reid |
| `geometry.py` | `BBox`, `Point2D`, `ObjectCategory`, `LineSegment`, `PolygonZone` | Vision, tracking, OCR, rules, signals, flow, motion, dwell, evaluation |
| `scene.py` | Signal-phase/state types, `SceneContext` | Signals, rules, streams |
| `events.py` | `Explanation`, `ViolationRecord`, `PreViolationRecord`, `RuleEvaluationResult` | Rules, streams, API persistence |

## What does NOT belong here

- **Service internals** — rule configs, tracking state machines, OCR domain hints, evidence manifests, hotspot analytics. These are owned by their service.
- **API-only infrastructure** — `CameraStatus`, `StreamKind`, `AlertRoutingChannel`, `CaseExportFormat`. These live in `apps/api/app/db/enums.py`.
- **Workflow output schemas** — polymorphic result types like `IncidentTriageOutput` or `DailySummaryOutput`. These are owned by the workflow service.
- **Frontend-only UI models** — `SpatialOperationsModel`, `MapProviderConfig`, etc. These live in `frontend/src/features/`.

## Re-export pattern

Downstream modules re-export shared types for backward compatibility:

```python
# In services/tracking/schemas.py
from packages.shared_types.geometry import BBox, LineSegment, ObjectCategory, Point2D, PolygonZone

__all__ = ["BBox", "LineSegment", "ObjectCategory", "Point2D", "PolygonZone"]
```

This means existing code that imports `from services.tracking.schemas import BBox` continues to work. New code should prefer importing from `packages.shared_types` directly.

## Adding new shared types

Before adding a type here, answer:

1. Is it imported by multiple independent services today (not just one service and its tests)?
2. Would a shape change in one service silently break another if they had separate definitions?
3. Does it have zero imports from `apps/` or `services/`?

If all three are yes, add it. Otherwise, keep it in the owning service.
