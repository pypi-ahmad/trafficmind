export type CameraStatus = "provisioning" | "active" | "maintenance" | "disabled";
export type StreamStatus = "offline" | "connecting" | "live" | "error" | "disabled";
export type ZoneType =
  | "polygon"
  | "line"
  | "stop_line"
  | "crosswalk"
  | "roi"
  | "lane"
  | "restricted";

export type MapProviderKind = "coordinate-grid" | "maplibre";
export type FeedAvailability = "live" | "pending_backend" | "unreachable";
export type HotspotSeverity = "stable" | "watch" | "critical";
export type TimeGranularity = "hour" | "day" | "week" | "month";
export type AggregationAxis =
  | "source_kind"
  | "camera"
  | "zone"
  | "lane"
  | "event_type"
  | "violation_type"
  | "severity"
  | "object_class";
export type HotspotSourceKind =
  | "detection_event"
  | "violation_event"
  | "watchlist_alert"
  | "congestion";
export type HotspotRankingMetric = "event_count" | "weighted_score";
export type SpatialAnalyticsSource = "hotspot_analytics" | "camera_metadata";
export type SpatialMapMarkerKind = "camera" | "junction";
export type SpatialMapMarkerTone = "ok" | "watch" | "critical" | "inactive";

export interface CameraReadApi {
  id: string;
  camera_code: string;
  name: string;
  location_name: string;
  approach: string | null;
  junction_id: string | null;
  timezone: string;
  status: CameraStatus;
  latitude: number | null;
  longitude: number | null;
  notes: string | null;
  calibration_config: Record<string, unknown>;
  calibration_updated_at: string | null;
  created_at: string;
  updated_at: string;
  stream_count: number;
}

export interface CameraStreamApi {
  id: string;
  camera_id: string;
  name: string;
  stream_kind: string;
  source_type: string;
  source_uri: string;
  source_config: Record<string, unknown>;
  status: StreamStatus;
  is_enabled: boolean;
  resolution_width: number | null;
  resolution_height: number | null;
  fps_hint: number | null;
  last_heartbeat_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ZoneReadApi {
  id: string;
  camera_id: string;
  name: string;
  zone_type: ZoneType;
  status: string;
  geometry: Record<string, unknown>;
  rules_config: Record<string, unknown>;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CameraDetailApi extends CameraReadApi {
  streams: CameraStreamApi[];
  zones: ZoneReadApi[];
}

export interface JunctionReadApi {
  id: string;
  name: string;
  description: string | null;
  latitude: number | null;
  longitude: number | null;
  created_at: string;
  updated_at: string;
}

export interface CameraListResponse {
  items: CameraReadApi[];
  total: number;
}

export interface PlaceholderApiResponse {
  resource: string;
  detail: string;
}

// ---------------------------------------------------------------------------
// Real event / violation feed response types
// ---------------------------------------------------------------------------

export type DetectionEventType = "detection" | "scene_classification";
export type DetectionEventStatus = "new" | "processed" | "archived";

export type ViolationTypeName =
  | "red_light"
  | "speeding"
  | "no_turn_on_red"
  | "stop_line"
  | "wrong_way"
  | "illegal_parking"
  | "no_stopping"
  | "pedestrian_conflict"
  | "bus_stop_violation"
  | "stalled_vehicle";
export type ViolationSeverity = "low" | "medium" | "high" | "critical";
export type ViolationStatus = "open" | "confirmed" | "dismissed" | "reviewed";

export interface DetectionEventReadApi {
  id: string;
  camera_id: string;
  stream_id: string | null;
  zone_id: string | null;
  event_type: DetectionEventType;
  status: DetectionEventStatus;
  occurred_at: string;
  frame_index: number | null;
  track_id: string | null;
  object_class: string;
  confidence: number;
  bbox: Record<string, unknown>;
  event_payload: Record<string, unknown>;
  image_uri: string | null;
  video_uri: string | null;
  created_at: string;
  updated_at: string;
}

export interface DetectionEventSearchResult {
  items: DetectionEventReadApi[];
  total: number;
  limit: number;
  offset: number;
}

export interface ViolationEventReadApi {
  id: string;
  camera_id: string;
  stream_id: string | null;
  zone_id: string | null;
  detection_event_id: string | null;
  plate_read_id: string | null;
  violation_type: ViolationTypeName;
  severity: ViolationSeverity;
  status: ViolationStatus;
  occurred_at: string;
  summary: string | null;
  evidence_image_uri: string | null;
  evidence_video_uri: string | null;
  assigned_to: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  rule_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ViolationSearchResult {
  items: ViolationEventReadApi[];
  total: number;
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------------------
// Feed summary (lightweight camera-level counts)
// ---------------------------------------------------------------------------

export interface CameraEventCountApi {
  camera_id: string;
  camera_name: string;
  location_name: string;
  event_count: number;
}

export interface CameraViolationCountApi {
  camera_id: string;
  camera_name: string;
  location_name: string;
  violation_count: number;
  severity_counts: Record<string, number>;
}

export interface FeedSummaryModel {
  eventCounts: CameraEventCountApi[];
  violationCounts: CameraViolationCountApi[];
  totalEvents: number;
  totalViolations: number;
}

export interface HotspotAnalyticsRequestApi {
  period_start: string;
  period_end: string;
  granularity: TimeGranularity;
  group_by: AggregationAxis[];
  compare_previous: boolean;
  source_kinds?: HotspotSourceKind[];
  camera_ids?: string[];
  zone_ids?: string[];
  event_types?: string[];
  violation_types?: string[];
  severity_levels?: string[];
  severity_weights?: Record<string, number>;
  top_n: number;
}

export interface HotspotRankingRowApi {
  rank: number;
  source_kind: HotspotSourceKind | null;
  camera_id: string | null;
  camera_name: string | null;
  location_name: string | null;
  zone_id: string | null;
  zone_name: string | null;
  lane_id: string | null;
  event_type: string | null;
  violation_type: string | null;
  severity: string | null;
  object_class: string | null;
  event_count: number;
  weighted_score: number;
  latitude: number | null;
  longitude: number | null;
  count_delta: number | null;
  pct_change: number | null;
  weighted_delta: number | null;
  weighted_pct_change: number | null;
}

export interface HotspotHeatmapPointApi {
  source_kind: HotspotSourceKind | null;
  camera_id: string | null;
  camera_name: string | null;
  location_name: string | null;
  zone_id: string | null;
  zone_name: string | null;
  lane_id: string | null;
  event_type: string | null;
  violation_type: string | null;
  severity: string | null;
  object_class: string | null;
  event_count: number;
  weighted_score: number;
  latitude: number | null;
  longitude: number | null;
}

export interface HotspotRecurringIssueApi {
  group_key: Record<string, string | null>;
  occurrences: number;
  slices_active: number;
  total_slices: number;
  recurrence_ratio: number;
  description: string;
}

export interface HotspotTrendDeltaApi {
  current_count: number;
  previous_count: number;
  count_delta: number;
  pct_change: number | null;
  current_weighted: number;
  previous_weighted: number;
  weighted_delta: number;
  weighted_pct_change: number | null;
}

export interface HotspotTrendComparisonApi {
  current_total: number;
  previous_total: number;
  delta: HotspotTrendDeltaApi;
}

export interface HotspotTimeSeriesPointApi {
  period_start: string;
  event_count: number;
  weighted_score: number;
}

export interface HotspotAnalyticsResponseApi {
  query_echo: HotspotAnalyticsRequestApi;
  total_events: number;
  ranking_metric: HotspotRankingMetric;
  ranking: HotspotRankingRowApi[];
  heatmap: HotspotHeatmapPointApi[];
  time_series: HotspotTimeSeriesPointApi[];
  recurring_issues: HotspotRecurringIssueApi[];
  trend: HotspotTrendComparisonApi | null;
  methodology: string[];
  warnings: string[];
}

export interface CoordinatePoint {
  latitude: number;
  longitude: number;
}

export interface CameraMapItem {
  id: string;
  code: string;
  name: string;
  locationName: string;
  approach: string | null;
  status: CameraStatus;
  coordinates: CoordinatePoint | null;
  timezone: string;
  notes: string | null;
  streamCount: number;
  updatedAt: string;
  detailHref: string;
  dashboardHref: string;
  eventFeedHref: string;
  junctionId: string;
  hasExplicitJunction: boolean;
}

export interface JunctionSummary {
  id: string;
  name: string;
  groupingSource: "location_name" | "junction_entity";
  coordinates: CoordinatePoint | null;
  cameraIds: string[];
  cameras: CameraMapItem[];
  cameraCount: number;
  mappedCameraCount: number;
  activeCameraCount: number;
  statusCounts: Record<CameraStatus, number>;
  dashboardHref: string;
  eventFeedHref: string;
}

export interface LocationIncidentSummary {
  id: string;
  title: string;
  locationName: string;
  locationType: "camera" | "junction";
  incidentCount: number | null;
  availability: FeedAvailability;
  note: string;
  source: SpatialAnalyticsSource;
  trendLabel: string | null;
  cameraIds: string[];
  junctionId: string;
  dashboardHref: string;
  eventFeedHref: string;
  cameraDetailHref: string | null;
}

export interface HotspotSummary {
  id: string;
  title: string;
  description: string;
  severity: HotspotSeverity;
  metricLabel: string;
  metricValue: string;
  source: SpatialAnalyticsSource;
  trendLabel: string | null;
  cameraIds: string[];
  junctionId: string | null;
  dashboardHref: string;
  eventFeedHref: string;
  cameraDetailHref: string | null;
}

export interface FeedStatus {
  availability: FeedAvailability;
  statusCode: number | null;
  note: string;
  totalCount: number | null;
}

export interface MapProviderConfig {
  provider: MapProviderKind;
  requestedProvider: string;
  styleUrl: string | null;
  token: string | null;
  note: string;
}

export interface SpatialAnalyticsConfig {
  lookbackDays: number;
  topN: number;
}

export interface SpatialAnalyticsSummary {
  availability: FeedAvailability;
  note: string;
  source: SpatialAnalyticsSource;
  rankingMetric: HotspotRankingMetric | null;
  totalEvents: number;
  periodStart: string | null;
  periodEnd: string | null;
  methodology: string[];
  warnings: string[];
}

export interface SpatialMapMarker {
  id: string;
  kind: SpatialMapMarkerKind;
  label: string;
  detail: string;
  coordinates: CoordinatePoint;
  badge: string | null;
  tone: SpatialMapMarkerTone;
  href: string;
  isSelected: boolean;
}

export interface SpatialOperationsModel {
  cameras: CameraMapItem[];
  mappedCameras: CameraMapItem[];
  junctions: JunctionSummary[];
  mapMarkers: SpatialMapMarker[];
  hotspots: HotspotSummary[];
  selectedHotspots: HotspotSummary[];
  incidentSummaries: LocationIncidentSummary[];
  selectedIncidentSummary: LocationIncidentSummary | null;
  selectedCamera: CameraMapItem | null;
  selectedCameraDetail: CameraDetailApi | null;
  selectedJunction: JunctionSummary | null;
  spatialAnalytics: SpatialAnalyticsSummary;
  provider: MapProviderConfig;
  feeds: {
    events: FeedStatus;
    violations: FeedStatus;
  };
  feedSummary: FeedSummaryModel;
  recentEvents: DetectionEventReadApi[];
  recentViolations: ViolationEventReadApi[];
}

export interface ApiResult<T> {
  ok: boolean;
  status: number | null;
  data: T | null;
  error: string | null;
}