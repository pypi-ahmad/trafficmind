# Data Model

TrafficMind uses SQLAlchemy async ORM with Alembic migrations. The schema is designed for operational traffic monitoring — cameras, video streams, detection events, violation records, plate reads, evidence packaging, model/config provenance, alert routing, and case exports.

## Entity Overview

```
Camera ──┬── CameraStream
         ├── Zone
         ├── DetectionEvent ──┬── PlateRead ──── WatchlistAlert
         │                    ├── ViolationEvent ──┬── EvidenceManifest
         │                    ├── EvidenceManifest │   └── WorkflowRun
         │                    └── WorkflowRun      └── OperationalAlert
         └── OperationalAlert
                   ├── AlertDeliveryAttempt
                   └── AlertAuditEvent

WatchlistEntry ──── WatchlistAlert
AlertPolicy ──── AlertPolicyRoute ──── AlertRoutingTarget
CaseExport ──── CaseExportAuditEvent
CrossCameraEntity ──── ReIdSighting ──── ReIdMatch
ModelRegistryEntry ──── DetectionEvent / PlateRead / ViolationEvent / EvidenceManifest
```

## Provenance Foundation

`ModelRegistryEntry` is a lightweight immutable registry row for runtime model or config bundles. It is used to track the exact detector, tracker, OCR engine/config, rules bundle, or evidence-builder bundle that produced a stored record.

Each row includes:

- `task_type` to identify the pipeline stage
- `model_family` and `version_name` for the logical bundle identity
- `config_hash` for deduplication of identical configs
- `config_bundle` for thresholds and backend settings
- `is_active` for the currently preferred entry in a scope
- `notes` and `entry_metadata` for operator/admin annotations

## Core Domain

### ModelRegistryEntry

Versioned model/config bundle used for audit-friendly provenance.

| Field | Type | Notes |
|---|---|---|
| `task_type` | `ModelRegistryTaskType` | detection_model, tracking_config, ocr_model, rules_config, evidence_config |
| `model_family` | `str` | Backend family or logical bundle name |
| `version_name` | `str` | Specific version label or runtime bundle name |
| `config_hash` | `str` | Stable hash of task type, family, version, and config bundle |
| `config_bundle` | `JSON` | Thresholds, runtime settings, rule config, or evidence config |
| `is_active` | `bool` | Active/inactive flag for the current preferred bundle |
| `notes` | `str?` | Human annotation |
| `entry_metadata` | `JSON?` | Source tags and operational metadata |

### Camera

Physical roadside camera or intersection viewpoint.

| Field | Type | Notes |
|---|---|---|
| `camera_code` | `str` | Unique human-readable identifier |
| `name` | `str` | Display name |
| `location_name` | `str` | Location description (used for junction grouping) |
| `approach` | `str?` | Direction of approach (northbound, eastbound, etc.) |
| `timezone` | `str` | IANA timezone |
| `status` | `CameraStatus` | provisioning, active, maintenance, disabled |
| `latitude`, `longitude` | `float?` | GPS coordinates |
| `calibration_config` | `JSON?` | Camera calibration and configuration metadata |
| `calibration_updated_at` | `datetime?` | Last calibration update timestamp |
| `notes` | `str?` | Operator notes |

### CameraStream

Concrete ingest source for a camera (RTSP feed, uploaded video, file, or test source).

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `FK → Camera` | Parent camera |
| `name` | `str` | Unique per camera (e.g., "primary", "substream") |
| `stream_kind` | `StreamKind` | primary, substream, auxiliary |
| `source_type` | `SourceType` | rtsp, upload, file, test |
| `source_uri` | `str` | Connection URI |
| `source_config` | `JSON?` | Stream-specific configuration |
| `status` | `StreamStatus` | offline, connecting, live, error, disabled |
| `is_enabled` | `bool` | Whether the stream should be processed |
| `resolution_width`, `resolution_height` | `int?` | Frame dimensions |
| `fps_hint` | `float?` | Expected frame rate |
| `last_heartbeat_at` | `datetime?` | Last runtime signal |
| `last_error` | `str?` | Most recent error message |

### Zone

Rule-evaluation area bound to a camera. Geometry is stored as JSON (normalized coordinates).

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `FK → Camera` | Parent camera |
| `name` | `str` | Zone identifier |
| `zone_type` | `ZoneType` | polygon, line, stop_line, crosswalk, roi, lane, restricted |
| `status` | `ZoneStatus` | draft, active, archived |
| `geometry` | `JSON` | GeoJSON-like geometry (LineString or Polygon) |
| `rules_config` | `JSON?` | Associated rule definitions |
| `sort_order` | `int` | Operator-controlled zone ordering |

### DetectionEvent

Persisted event from the deterministic hot path.

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `FK → Camera` | Source camera |
| `stream_id` | `FK → CameraStream?` | Source stream |
| `zone_id` | `FK → Zone?` | Triggering zone |
| `detector_registry_id` | `FK → ModelRegistryEntry?` | Detector model/config bundle used for the event |
| `tracker_registry_id` | `FK → ModelRegistryEntry?` | Tracking config bundle used for the event |
| `event_type` | `DetectionEventType` | detection, zone_entry, zone_exit, line_crossing, light_state |
| `status` | `DetectionEventStatus` | new, enriched, suppressed |
| `occurred_at` | `datetime` | When the event occurred |
| `frame_index` | `int?` | Source frame number |
| `track_id` | `str?` | Tracker-assigned object ID |
| `object_class` | `str` | Detected object class |
| `confidence` | `float` | Detection confidence |
| `bbox` | `JSON` | Bounding box coordinates |
| `event_payload` | `JSON?` | Event-specific metadata |
| `image_uri`, `video_uri` | `str?` | Evidence asset references |

### ViolationEvent

Reviewable incident derived from deterministic rule evaluation.

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `FK → Camera` | Source camera |
| `stream_id` | `FK → CameraStream?` | Source stream |
| `zone_id` | `FK → Zone?` | Triggering zone |
| `detection_event_id` | `FK → DetectionEvent?` | Linked detection |
| `plate_read_id` | `FK → PlateRead?` | Linked plate read |
| `rules_registry_id` | `FK → ModelRegistryEntry?` | Rules-engine config bundle used for the violation |
| `violation_type` | `ViolationType` | red_light, stop_line, wrong_way, pedestrian_conflict, illegal_turn, speeding, illegal_parking, no_stopping, bus_stop_violation, stalled_vehicle |
| `severity` | `ViolationSeverity` | low, medium, high, critical |
| `status` | `ViolationStatus` | open, under_review, confirmed, dismissed |
| `occurred_at` | `datetime` | When the violation occurred |
| `summary` | `str?` | Human-readable description |
| `evidence_image_uri`, `evidence_video_uri` | `str?` | Evidence references |
| `assigned_to` | `str?` | Queue owner |
| `reviewed_by` | `str?` | Final reviewer |
| `reviewed_at` | `datetime?` | Review timestamp |
| `review_note` | `str?` | Reviewer comments |
| `rule_metadata` | `JSON?` | Rule engine details |

### PlateRead

OCR result attached to a detection event.

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `FK → Camera` | Source camera |
| `stream_id` | `FK → CameraStream?` | Source stream |
| `detection_event_id` | `FK → DetectionEvent?` | Linked detection |
| `ocr_registry_id` | `FK → ModelRegistryEntry?` | OCR engine/config bundle used for the read |
| `status` | `PlateReadStatus` | observed, matched, manual_review, rejected |
| `occurred_at` | `datetime` | When the plate was read |
| `plate_text` | `str` | Raw OCR output |
| `normalized_plate_text` | `str` | Normalized for search |
| `confidence` | `float` | OCR confidence |
| `country_code`, `region_code` | `str?` | Plate origin |
| `bbox` | `JSON` | Plate bounding box |
| `crop_image_uri`, `source_frame_uri` | `str?` | Evidence references |
| `ocr_metadata` | `JSON?` | OCR engine details |

## Evidence & Workflows

### EvidenceManifest

Structured evidence package for a violation or detection event.

| Field | Type | Notes |
|---|---|---|
| `subject_kind` | `EvidenceSubjectKind` | detection_event, violation_event |
| `subject_id` | `UUID` | ID of the subject record |
| `manifest_key` | `str` | Stable identity key |
| `build_revision` | `int` | Rebuild counter |
| `camera_id` | `FK → Camera` | Source camera |
| `evidence_registry_id` | `FK → ModelRegistryEntry?` | Evidence-builder and privacy-policy bundle used for packaging |
| `occurred_at` | `datetime?` | Event occurrence time |
| `event_frame_index` | `int?` | Key frame number |
| `storage_namespace` | `str` | Storage bucket identifier |
| `manifest_uri` | `str?` | URI to the full manifest |
| `manifest_data` | `JSON?` | Embedded manifest content |

### WorkflowRun

Cold-path workflow execution record.

| Field | Type | Notes |
|---|---|---|
| `camera_id` | `FK → Camera?` | Associated camera |
| `detection_event_id` | `FK → DetectionEvent?` | Linked detection |
| `violation_event_id` | `FK → ViolationEvent?` | Linked violation |
| `workflow_type` | `WorkflowType` | triage, review, report, assist |
| `status` | `WorkflowStatus` | queued, running, succeeded, failed, cancelled |
| `priority` | `int` | Execution priority |
| `requested_by` | `str?` | Who requested execution |
| `started_at`, `completed_at` | `datetime?` | Workflow runtime window |
| `input_payload` | `JSON?` | Workflow input |
| `result_payload` | `JSON?` | Workflow output |
| `error_message` | `str?` | Failure details |

## Operational Alerts

### AlertRoutingTarget

Configured delivery destination.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Target identifier |
| `channel` | `AlertRoutingChannel` | email, webhook, sms, slack, teams |
| `destination` | `str` | Delivery address or URL |
| `is_enabled` | `bool` | Active/inactive toggle |
| `target_config` | `JSON?` | Channel-specific settings |

### AlertPolicy

Routing policy for a source/condition pair.

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | Policy identifier |
| `description` | `str?` | Human-readable routing policy description |
| `source_kind` | `OperationalAlertSourceKind` | What produces the signal |
| `condition_key` | `str` | Signal condition to match |
| `min_severity` | `OperationalAlertSeverity` | Minimum severity threshold |
| `dedup_window_seconds` | `int` | Window for deduplication |
| `cooldown_seconds` | `int` | Minimum time between route plans |
| `is_enabled` | `bool` | Active/inactive toggle |
| `policy_metadata` | `JSON?` | Policy-specific routing metadata |

### AlertPolicyRoute

One escalation level within a policy.

| Field | Type | Notes |
|---|---|---|
| `policy_id` | `FK → AlertPolicy` | Parent policy |
| `routing_target_id` | `FK → AlertRoutingTarget` | Delivery target |
| `escalation_level` | `int` | Escalation level (0 = immediate) |
| `delay_seconds` | `int` | Delay before delivery at this level |
| `route_config` | `JSON?` | Route-specific metadata |

### OperationalAlert

Persisted alert instance.

| Field | Type | Notes |
|---|---|---|
| `policy_id` | `FK → AlertPolicy?` | Matched routing policy |
| `source_kind` | `OperationalAlertSourceKind` | Signal source type |
| `condition_key` | `str` | Signal condition that triggered the alert |
| `severity` | `OperationalAlertSeverity` | info, low, medium, high, critical |
| `status` | `OperationalAlertStatus` | new, acknowledged, escalated, resolved, suppressed |
| `watchlist_alert_id`, `workflow_run_id` | `FK?` | Optional links to source records |
| `title` | `str` | Alert title |
| `summary` | `str?` | Alert details |
| `dedup_key` | `str?` | Deduplication identifier |
| `occurred_at`, `first_seen_at`, `last_seen_at` | `datetime` | Event timing and repetition window |
| `occurrence_count` | `int` | Number of matched signal occurrences |
| `escalation_level` | `int` | Current escalation level |
| `camera_id`, `stream_id`, `detection_event_id`, `violation_event_id` | `FK?` | Source record links |
| `source_payload`, `alert_metadata` | `JSON?` | Signal payload and derived metadata |

### AlertDeliveryAttempt

Planned or actual delivery record.

| Field | Type | Notes |
|---|---|---|
| `alert_id` | `FK → OperationalAlert` | Parent alert |
| `policy_id` | `FK → AlertPolicy?` | Source policy |
| `routing_target_id` | `FK → AlertRoutingTarget?` | Delivery target |
| `escalation_level` | `int` | Delivery level |
| `delivery_state` | `AlertDeliveryState` | planned, sent, failed, skipped |
| `channel` | `AlertRoutingChannel` | Delivery channel |
| `destination` | `str` | Resolved delivery destination |
| `scheduled_for`, `attempted_at` | `datetime?` | Planned and actual delivery times |
| `error_message` | `str?` | Delivery failure details |
| `delivery_payload` | `JSON?` | Provider-specific delivery metadata |

### AlertAuditEvent

Status and routing audit trail.

| Field | Type | Notes |
|---|---|---|
| `alert_id` | `FK → OperationalAlert` | Parent alert |
| `policy_id` | `FK → AlertPolicy?` | Source policy |
| `event_type` | `AlertAuditEventType` | created, deduplicated, routed, escalated, acknowledged, resolved, suppressed |
| `status_after` | `OperationalAlertStatus?` | Alert state after the event |
| `actor` | `str?` | Who triggered the audit event |
| `note` | `str?` | Human-readable audit note |
| `event_payload` | `JSON?` | Event-specific metadata |

## Watchlist & ANPR

### WatchlistEntry

Flagged plate number.

| Field | Type | Notes |
|---|---|---|
| `normalized_plate_text` | `str` | Normalized plate text used for matching |
| `plate_text_display` | `str` | Operator-facing display text |
| `reason` | `WatchlistReason` | stolen, wanted, bolo, vip, investigation, other |
| `status` | `WatchlistEntryStatus` | active, expired, disabled |
| `description` | `str?` | Context for the entry |
| `added_by` | `str?` | Who created the watchlist entry |
| `alert_enabled` | `bool` | Whether matches trigger alerts |
| `expires_at` | `datetime?` | Auto-expiry timestamp |
| `country_code` | `str?` | Optional country qualifier |
| `notes` | `str?` | Operator notes |

### WatchlistAlert

Alert generated when a plate read matches a watchlist entry.

| Field | Type | Notes |
|---|---|---|
| `plate_read_id` | `FK → PlateRead` | Triggering read |
| `watchlist_entry_id` | `FK → WatchlistEntry?` | Matched entry |
| `camera_id` | `FK → Camera` | Where the match occurred |
| `status` | `WatchlistAlertStatus` | open, acknowledged, resolved |
| `plate_text`, `normalized_plate_text` | `str` | Snapshot of matched text |
| `reason` | `WatchlistReason` | Snapshot of watchlist reason |

## Re-Identification

### CrossCameraEntity

Confirmed identity across cameras.

| Field | Type | Notes |
|---|---|---|
| `subject_type` | `ReIdSubjectType` | vehicle, person |
| `first_seen_at`, `last_seen_at` | `datetime?` | Entity lifetime across linked sightings |
| `representative_image_uri` | `str?` | Best available snapshot for the entity |
| `notes` | `str?` | Operator notes |
| `reid_metadata` | `JSON?` | Entity-level metadata |

### ReIdSighting

Single per-track observation on one camera.

| Field | Type | Notes |
|---|---|---|
| `entity_id` | `FK → CrossCameraEntity?` | Linked entity |
| `camera_id` | `FK → Camera` | Source camera |
| `representative_detection_event_id` | `FK → DetectionEvent?` | Representative persisted event |
| `track_id` | `str` | Tracker ID |
| `subject_type` | `ReIdSubjectType` | vehicle, person |
| `embedding_vector` | `JSON?` | Feature embedding |
| `embedding_model` | `str?` | Embedding model identifier |
| `first_seen_at`, `last_seen_at` | `datetime` | Observation window |
| `bbox_snapshot` | `JSON?` | Representative bounding box |
| `image_uri` | `str?` | Representative crop or frame URI |
| `reid_metadata` | `JSON?` | Sighting-level metadata |

### ReIdMatch

Proposed or confirmed match between two sightings.

| Field | Type | Notes |
|---|---|---|
| `sighting_a_id` | `FK → ReIdSighting` | First sighting |
| `sighting_b_id` | `FK → ReIdSighting` | Second sighting |
| `pair_key` | `str` | Unique pair identifier |
| `status` | `ReIdMatchStatus` | candidate, confirmed, rejected, expired |
| `similarity_score` | `float` | Embedding distance |

## Case Export

### CaseExport

Audit-ready export bundle.

| Field | Type | Notes |
|---|---|---|
| `subject_kind` | `CaseSubjectKind` | violation_event, detection_event, watchlist_alert, operational_alert |
| `subject_id` | `UUID` | Subject record ID |
| `export_format` | `CaseExportFormat` | json, markdown, zip_manifest |
| `status` | `CaseExportStatus` | pending, completed, failed |
| `bundle_version` | `str` | Export schema version |
| `requested_by` | `str?` | Who requested the export |
| `filename` | `str` | Generated filename |
| `bundle_data` | `JSON?` | Full export payload |
| `completeness` | `JSON?` | Explicit completeness report for missing artifacts |
| `error_message` | `str?` | Export failure details |
| `completed_at` | `datetime?` | Export completion time |

### CaseExportAuditEvent

Export lifecycle audit trail.

| Field | Type | Notes |
|---|---|---|
| `case_export_id` | `FK → CaseExport` | Parent export |
| `event_type` | `CaseExportAuditEventType` | created, completed, failed, downloaded |
| `actor` | `str?` | Who triggered the event |
| `note` | `str?` | Human-readable audit note |
| `event_payload` | `JSON?` | Event metadata |

## Deletion Strategy

- **Configuration entities** (cameras, streams, zones): cascade deletes for child streams and zones.
- **Operational records** (detections, violations, plates, workflows): protected from casual cascade deletion. Where configuration records may disappear, downstream references use `SET NULL` so evidence records remain queryable.

## Migration History

| Revision | Date | Description |
|---|---|---|
| 0001 | 2026-04-04 | Database foundation (cameras, streams, zones, detections, violations, plates, workflows) |
| 0002 | 2026-04-04 | PlateRead `ocr_metadata` JSON column |
| 0003 | 2026-04-04 | ViolationEvent `rule_metadata` JSON column |
| 0004 | 2026-04-05 | Watchlist entries |
| 0005 | 2026-04-05 | Watchlist alerts and plate text index |
| 0006 | 2026-04-05 | Evidence manifests |
| 0007 | 2026-04-05 | Re-identification tables |
| 0008 | 2026-04-06 | Alert routing foundation |
| 0009 | 2026-04-06 | Case export |

## Enum Reference

See `apps/api/app/db/enums.py` for the full list. Key enums:

- **CameraStatus**: provisioning, active, maintenance, disabled
- **StreamStatus**: offline, connecting, live, error, disabled
- **SourceType**: rtsp, upload, file, test
- **ZoneType**: polygon, line, stop_line, crosswalk, roi, lane, restricted
- **DetectionEventType**: detection, zone_entry, zone_exit, line_crossing, light_state
- **ViolationType**: red_light, stop_line, wrong_way, pedestrian_conflict, illegal_turn, speeding, illegal_parking, no_stopping, bus_stop_violation, stalled_vehicle
- **ViolationSeverity**: low, medium, high, critical
- **ViolationStatus**: open, under_review, confirmed, dismissed
- **WorkflowType**: triage, review, report, assist
- **WorkflowStatus**: queued, running, succeeded, failed, cancelled
- **OperationalAlertSeverity**: info, low, medium, high, critical
- **OperationalAlertStatus**: new, acknowledged, escalated, resolved, suppressed
- **AlertRoutingChannel**: email, webhook, sms, slack, teams
- **ReIdMatchStatus**: candidate, confirmed, rejected, expired
- **CaseExportFormat**: json, markdown, zip_manifest
