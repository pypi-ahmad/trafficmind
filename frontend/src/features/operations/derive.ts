import type {
  ApiResult,
  CameraDetailApi,
  CameraEventCountApi,
  CameraListResponse,
  CameraViolationCountApi,
  CoordinatePoint,
  CameraMapItem,
  CameraReadApi,
  CameraStatus,
  DetectionEventReadApi,
  DetectionEventSearchResult,
  FeedAvailability,
  FeedStatus,
  FeedSummaryModel,
  HotspotSummary,
  HotspotAnalyticsRequestApi,
  HotspotAnalyticsResponseApi,
  HotspotHeatmapPointApi,
  HotspotRankingRowApi,
  HotspotSeverity,
  HotspotSourceKind,
  JunctionSummary,
  LocationIncidentSummary,
  MapProviderConfig,
  SpatialAnalyticsConfig,
  SpatialAnalyticsSummary,
  SpatialMapMarker,
  SpatialMapMarkerTone,
  SpatialOperationsModel,
  EventSummaryTotalsApi,
  ViolationSummaryTotalsApi,
  ViolationEventReadApi,
  ViolationSearchResult,
} from "@/features/operations/types";

type DashboardSelection = {
  cameraId?: string | null;
  junctionId?: string | null;
};

const CAMERA_STATUSES: CameraStatus[] = ["active", "provisioning", "maintenance", "disabled"];

export function getSingleParam(
  value: string | string[] | undefined,
): string | null {
  if (Array.isArray(value)) {
    return value[0] ?? null;
  }
  return value ?? null;
}

export function buildDashboardHref(selection: DashboardSelection = {}): string {
  const params = new URLSearchParams();
  if (selection.cameraId) {
    params.set("cameraId", selection.cameraId);
  }
  if (selection.junctionId) {
    params.set("junctionId", selection.junctionId);
  }
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

export function buildCameraDetailHref(cameraId: string, selection: DashboardSelection = {}): string {
  const params = new URLSearchParams();
  if (selection.junctionId) {
    params.set("junctionId", selection.junctionId);
  }
  const query = params.toString();
  return query ? `/cameras/${cameraId}?${query}` : `/cameras/${cameraId}`;
}

export function buildEventFeedHref(selection: DashboardSelection = {}): string {
  const params = new URLSearchParams();
  if (selection.cameraId) {
    params.set("cameraId", selection.cameraId);
  }
  if (selection.junctionId) {
    params.set("junctionId", selection.junctionId);
  }
  const query = params.toString();
  return query ? `/events?${query}` : "/events";
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "") || "junction";
}

function hasCoordinates(camera: CameraReadApi): boolean {
  return camera.latitude !== null && camera.longitude !== null;
}

function averageCoordinates(cameras: CameraMapItem[]) {
  const withCoordinates = cameras.filter((camera) => camera.coordinates !== null);
  if (withCoordinates.length === 0) {
    return null;
  }

  const latitude =
    withCoordinates.reduce((sum, camera) => sum + (camera.coordinates?.latitude ?? 0), 0) /
    withCoordinates.length;
  const longitude =
    withCoordinates.reduce((sum, camera) => sum + (camera.coordinates?.longitude ?? 0), 0) /
    withCoordinates.length;

  return { latitude, longitude };
}

function toEventFeedStatus(
  result: ApiResult<DetectionEventSearchResult>,
): FeedStatus {
  if (result.ok && result.data && Array.isArray(result.data.items)) {
    return {
      availability: "live",
      statusCode: result.status,
      note:
        result.data.total > 0
          ? `${result.data.total} detection events available from the backend.`
          : "Events feed is live but no detection events have been recorded yet.",
      totalCount: result.data.total,
    };
  }

  if (result.status === 501) {
    return {
      availability: "pending_backend",
      statusCode: result.status,
      note: result.error ?? "Events endpoint is scaffolded but not implemented yet.",
      totalCount: null,
    };
  }

  return {
    availability: "unreachable",
    statusCode: result.status,
    note: result.error ?? "Events endpoint is currently unreachable.",
    totalCount: null,
  };
}

function toViolationFeedStatus(
  result: ApiResult<ViolationSearchResult>,
): FeedStatus {
  if (result.ok && result.data && Array.isArray(result.data.items)) {
    return {
      availability: "live",
      statusCode: result.status,
      note:
        result.data.total > 0
          ? `${result.data.total} violation events available from the backend.`
          : "Violations feed is live but no violation events have been recorded yet.",
      totalCount: result.data.total,
    };
  }

  if (result.status === 501) {
    return {
      availability: "pending_backend",
      statusCode: result.status,
      note: result.error ?? "Violations endpoint is scaffolded but not implemented yet.",
      totalCount: null,
    };
  }

  return {
    availability: "unreachable",
    statusCode: result.status,
    note: result.error ?? "Violations endpoint is currently unreachable.",
    totalCount: null,
  };
}

function toSpatialAnalyticsStatus(
  result: ApiResult<HotspotAnalyticsResponseApi>,
  request: HotspotAnalyticsRequestApi,
): SpatialAnalyticsSummary {
  if (result.ok && result.data) {
    return {
      availability: "live",
      note:
        result.data.total_events > 0
          ? "Recent location summaries are coming from persisted violations and watchlist alerts through the hotspot analytics API."
          : "Hotspot analytics is reachable, but there are no persisted operational incidents in the current time window.",
      source: "hotspot_analytics",
      rankingMetric: result.data.ranking_metric,
      totalEvents: result.data.total_events,
      periodStart: request.period_start,
      periodEnd: request.period_end,
      methodology: result.data.methodology,
      warnings: result.data.warnings,
    };
  }

  if (result.status === 404 || result.status === 501) {
    return {
      availability: "pending_backend",
      note: result.error ?? "Hotspot analytics is scaffolded but not available yet.",
      source: "camera_metadata",
      rankingMetric: null,
      totalEvents: 0,
      periodStart: request.period_start,
      periodEnd: request.period_end,
      methodology: [],
      warnings: [],
    };
  }

  return {
    availability: "unreachable",
    note: result.error ?? "Hotspot analytics is currently unreachable, so the dashboard is falling back to camera metadata only.",
    source: "camera_metadata",
    rankingMetric: null,
    totalEvents: 0,
    periodStart: request.period_start,
    periodEnd: request.period_end,
    methodology: [],
    warnings: [],
  };
}

function formatSourceKind(sourceKind: HotspotSourceKind | null): string {
  switch (sourceKind) {
    case "watchlist_alert":
      return "Watchlist alerts";
    case "violation_event":
      return "Violations";
    case "detection_event":
      return "Detections";
    case "congestion":
      return "Congestion";
    default:
      return "Operational activity";
  }
}

function formatTrendLabel(delta: number | null | undefined): string | null {
  if (delta === null || delta === undefined || delta === 0) {
    return null;
  }

  return delta > 0 ? `Up ${delta} vs previous window` : `Down ${Math.abs(delta)} vs previous window`;
}

function deriveAnalyticsSeverity(row: HotspotRankingRowApi, maxCount: number): HotspotSeverity {
  if (row.source_kind === "watchlist_alert") {
    return "critical";
  }
  if (row.event_count === 0) {
    return "stable";
  }
  if (row.event_count >= Math.max(10, maxCount) || (row.count_delta ?? 0) >= 5) {
    return "critical";
  }
  return "watch";
}

function aggregateIncidentPoints(
  heatmap: HotspotHeatmapPointApi[],
  camerasById: Map<string, CameraMapItem>,
): Map<string, { count: number; sourceKinds: Set<HotspotSourceKind>; cameraIds: Set<string> }> {
  const grouped = new Map<string, { count: number; sourceKinds: Set<HotspotSourceKind>; cameraIds: Set<string> }>();

  for (const point of heatmap) {
    if (!point.camera_id) {
      continue;
    }

    const camera = camerasById.get(point.camera_id);
    if (!camera) {
      continue;
    }

    const current = grouped.get(camera.junctionId) ?? {
      count: 0,
      sourceKinds: new Set<HotspotSourceKind>(),
      cameraIds: new Set<string>(),
    };

    current.count += point.event_count;
    current.cameraIds.add(camera.id);
    if (point.source_kind) {
      current.sourceKinds.add(point.source_kind);
    }

    grouped.set(camera.junctionId, current);
  }

  return grouped;
}

function mapMarkerToneFromCamera(camera: CameraMapItem, incidentCount: number): SpatialMapMarkerTone {
  if (camera.status === "disabled") {
    return "critical";
  }
  if (camera.status === "maintenance") {
    return "watch";
  }
  if (incidentCount >= 5) {
    return "critical";
  }
  if (incidentCount > 0 || camera.status === "provisioning") {
    return "watch";
  }
  return camera.status === "active" ? "ok" : "inactive";
}

function mapMarkerToneFromJunction(junction: JunctionSummary, incidentCount: number): SpatialMapMarkerTone {
  if (incidentCount >= 5 || junction.activeCameraCount === 0) {
    return "critical";
  }
  if (incidentCount > 0 || junction.activeCameraCount < junction.cameraCount) {
    return "watch";
  }
  return "ok";
}

function deriveMetadataHotspots(
  junctions: JunctionSummary[],
  cameras: CameraMapItem[],
): HotspotSummary[] {
  const hotspots: HotspotSummary[] = [];

  for (const junction of junctions) {
    const attentionCount = junction.cameraCount - junction.activeCameraCount;
    if (attentionCount > 0) {
      hotspots.push({
        id: `junction-status-${junction.id}`,
        title: `${junction.name} needs attention`,
        description: `${attentionCount} of ${junction.cameraCount} cameras are not in active status.`,
        severity: attentionCount > 1 ? "critical" : "watch",
        metricLabel: "Non-active cameras",
        metricValue: `${attentionCount}`,
        source: "camera_metadata",
        trendLabel: null,
        cameraIds: junction.cameraIds,
        junctionId: junction.id,
        dashboardHref: junction.dashboardHref,
        eventFeedHref: junction.eventFeedHref,
        cameraDetailHref: junction.cameraCount === 1 ? buildSingleCameraDetailHref(junction.cameraIds, junction.id) : null,
      });
    }

    if (junction.cameraCount > 1 && junction.mappedCameraCount < junction.cameraCount) {
      hotspots.push({
        id: `junction-coverage-${junction.id}`,
        title: `${junction.name} has partial map coverage`,
        description: `${junction.cameraCount - junction.mappedCameraCount} cameras are missing coordinates, so the map view is incomplete.`,
        severity: "watch",
        metricLabel: "Unmapped cameras",
        metricValue: `${junction.cameraCount - junction.mappedCameraCount}`,
        source: "camera_metadata",
        trendLabel: null,
        cameraIds: junction.cameraIds,
        junctionId: junction.id,
        dashboardHref: junction.dashboardHref,
        eventFeedHref: junction.eventFeedHref,
        cameraDetailHref: null,
      });
    }
  }

  const unmappedSingles = cameras.filter((camera) => camera.coordinates === null);
  for (const camera of unmappedSingles.slice(0, 3)) {
    hotspots.push({
      id: `camera-coordinate-${camera.id}`,
      title: `${camera.name} is not geocoded`,
      description: "This camera cannot appear on a precise basemap until latitude and longitude are saved in the backend.",
      severity: "watch",
      metricLabel: "Coordinate status",
      metricValue: "Missing",
      source: "camera_metadata",
      trendLabel: null,
      cameraIds: [camera.id],
      junctionId: camera.junctionId,
      dashboardHref: camera.dashboardHref,
      eventFeedHref: camera.eventFeedHref,
      cameraDetailHref: camera.detailHref,
    });
  }

  if (hotspots.length === 0 && cameras.length > 0) {
    hotspots.push({
      id: "network-stable",
      title: "Camera network looks stable",
      description: "All current cameras are active and mapped, so this view is ready for richer spatial overlays.",
      severity: "stable",
      metricLabel: "Mapped active cameras",
      metricValue: `${cameras.filter((camera) => camera.status === "active" && camera.coordinates).length}`,
      source: "camera_metadata",
      trendLabel: null,
      cameraIds: cameras.map((camera) => camera.id),
      junctionId: null,
      dashboardHref: "/",
      eventFeedHref: "/events",
      cameraDetailHref: null,
    });
  }

  return hotspots;
}

function buildSingleCameraDetailHref(cameraIds: string[], junctionId: string): string | null {
  const cameraId = cameraIds[0];
  return cameraId ? buildCameraDetailHref(cameraId, { junctionId }) : null;
}

export function toCameraMapItems(cameras: CameraReadApi[]): CameraMapItem[] {
  return cameras.map((camera) => {
    const junctionId = camera.junction_id ?? slugify(camera.location_name);
    const hasExplicitJunction = camera.junction_id !== null;
    return {
      id: camera.id,
      code: camera.camera_code,
      name: camera.name,
      locationName: camera.location_name,
      approach: camera.approach,
      status: camera.status,
      coordinates:
        hasCoordinates(camera) && camera.latitude !== null && camera.longitude !== null
          ? { latitude: camera.latitude, longitude: camera.longitude }
          : null,
      timezone: camera.timezone,
      notes: camera.notes,
      streamCount: camera.stream_count,
      updatedAt: camera.updated_at,
      detailHref: buildCameraDetailHref(camera.id, { junctionId }),
      dashboardHref: buildDashboardHref({ cameraId: camera.id, junctionId }),
      eventFeedHref: buildEventFeedHref({ cameraId: camera.id, junctionId }),
      junctionId,
      hasExplicitJunction,
    };
  });
}

export function groupCamerasIntoJunctions(cameras: CameraMapItem[]): JunctionSummary[] {
  const groups = new Map<string, CameraMapItem[]>();

  for (const camera of cameras) {
    const existing = groups.get(camera.junctionId) ?? [];
    existing.push(camera);
    groups.set(camera.junctionId, existing);
  }

  return [...groups.entries()]
    .map(([junctionId, groupedCameras]) => {
      const statusCounts = CAMERA_STATUSES.reduce<Record<CameraStatus, number>>(
        (counts, status) => ({ ...counts, [status]: 0 }),
        {
          active: 0,
          provisioning: 0,
          maintenance: 0,
          disabled: 0,
        },
      );

      for (const camera of groupedCameras) {
        statusCounts[camera.status] += 1;
      }

      const name = groupedCameras[0]?.locationName ?? "Unassigned junction";
      const hasEntity = groupedCameras.some((camera) => camera.hasExplicitJunction);
      return {
        id: junctionId,
        name,
        groupingSource: hasEntity ? "junction_entity" : "location_name",
        coordinates: averageCoordinates(groupedCameras),
        cameraIds: groupedCameras.map((camera) => camera.id),
        cameras: groupedCameras,
        cameraCount: groupedCameras.length,
        mappedCameraCount: groupedCameras.filter((camera) => camera.coordinates !== null).length,
        activeCameraCount: groupedCameras.filter((camera) => camera.status === "active").length,
        statusCounts,
        dashboardHref: buildDashboardHref({ junctionId }),
        eventFeedHref: buildEventFeedHref({ junctionId }),
      } satisfies JunctionSummary;
    })
    .sort((left, right) => right.cameraCount - left.cameraCount || left.name.localeCompare(right.name));
}

export function deriveHotspots(
  junctions: JunctionSummary[],
  cameras: CameraMapItem[],
  analytics: SpatialAnalyticsSummary,
  analyticsPayload: HotspotAnalyticsResponseApi | null,
): HotspotSummary[] {
  const metadataHotspots = deriveMetadataHotspots(junctions, cameras);

  if (analytics.availability !== "live" || !analyticsPayload || analyticsPayload.ranking.length === 0) {
    return metadataHotspots.slice(0, 6);
  }

  const maxCount = analyticsPayload.ranking[0]?.event_count ?? 0;
  const liveHotspots = analyticsPayload.ranking.slice(0, 4).map((row) => {
    const cameraId = row.camera_id;
    const linkedCamera = cameraId ? cameras.find((camera) => camera.id === cameraId) ?? null : null;
    const junctionId = linkedCamera?.junctionId ?? (row.location_name ? slugify(row.location_name) : null);
    const sourceLabel = formatSourceKind(row.source_kind);
    const locationLabel = row.location_name ?? linkedCamera?.locationName ?? row.camera_name ?? "Unassigned location";

    return {
      id: `live-hotspot-${row.rank}-${cameraId ?? "location"}-${row.source_kind ?? "activity"}`,
      title: `${locationLabel} · ${sourceLabel}`,
      description: `${row.event_count} persisted ${sourceLabel.toLowerCase()} recorded in the current spatial operations window.`,
      severity: deriveAnalyticsSeverity(row, maxCount),
      metricLabel: analytics.rankingMetric === "weighted_score" ? "Weighted score" : "Incident count",
      metricValue:
        analytics.rankingMetric === "weighted_score"
          ? row.weighted_score.toFixed(1)
          : `${row.event_count}`,
      source: "hotspot_analytics",
      trendLabel: formatTrendLabel(row.count_delta),
      cameraIds: cameraId ? [cameraId] : [],
      junctionId,
      dashboardHref: buildDashboardHref({ cameraId: cameraId ?? undefined, junctionId: junctionId ?? undefined }),
      eventFeedHref: buildEventFeedHref({ cameraId: cameraId ?? undefined, junctionId: junctionId ?? undefined }),
      cameraDetailHref: cameraId ? buildCameraDetailHref(cameraId, { junctionId }) : null,
    } satisfies HotspotSummary;
  });

  return [...liveHotspots, ...metadataHotspots].slice(0, 6);
}

export function deriveIncidentSummaries(
  junctions: JunctionSummary[],
  cameras: CameraMapItem[],
  eventsStatus: FeedStatus,
  violationsStatus: FeedStatus,
  analytics: SpatialAnalyticsSummary,
  analyticsPayload: HotspotAnalyticsResponseApi | null,
  recentEvents: DetectionEventReadApi[],
  recentViolations: ViolationEventReadApi[],
): LocationIncidentSummary[] {
  if (analytics.availability === "live" && analyticsPayload) {
    const camerasById = new Map(cameras.map((camera) => [camera.id, camera]));
    const incidentsByJunction = aggregateIncidentPoints(analyticsPayload.heatmap, camerasById);

    if (incidentsByJunction.size === 0) {
      return junctions.slice(0, 5).map((junction) => ({
        id: `incident-${junction.id}`,
        title: junction.name,
        locationName: junction.name,
        locationType: "junction",
        incidentCount: 0,
        availability: "live",
        note: "Hotspot analytics is live, but no persisted violations or watchlist alerts were found for this window.",
        source: "hotspot_analytics",
        trendLabel: null,
        cameraIds: junction.cameraIds,
        junctionId: junction.id,
        dashboardHref: junction.dashboardHref,
        eventFeedHref: junction.eventFeedHref,
        cameraDetailHref: junction.cameraCount === 1 ? buildSingleCameraDetailHref(junction.cameraIds, junction.id) : null,
      }));
    }

    const liveSummaries: LocationIncidentSummary[] = [];

    for (const junction of junctions) {
      const aggregate = incidentsByJunction.get(junction.id);
      if (!aggregate) {
        continue;
      }

      const sourceKinds = [...aggregate.sourceKinds].map((sourceKind) => formatSourceKind(sourceKind)).join(" + ");
      const cameraIds = [...aggregate.cameraIds];
      const singleCameraId = aggregate.cameraIds.size === 1 ? cameraIds[0] ?? null : null;

      liveSummaries.push({
        id: `incident-${junction.id}`,
        title: junction.name,
        locationName: junction.name,
        locationType: "junction",
        incidentCount: aggregate.count,
        availability: "live",
        note: sourceKinds
          ? `${sourceKinds} recorded across ${aggregate.cameraIds.size} camera${aggregate.cameraIds.size === 1 ? "" : "s"} in the current analytics window.`
          : "Persisted operational incidents recorded in the current analytics window.",
        source: "hotspot_analytics",
        trendLabel: null,
        cameraIds,
        junctionId: junction.id,
        dashboardHref: buildDashboardHref({ cameraId: singleCameraId ?? undefined, junctionId: junction.id }),
        eventFeedHref: buildEventFeedHref({ cameraId: singleCameraId ?? undefined, junctionId: junction.id }),
        cameraDetailHref: singleCameraId ? buildCameraDetailHref(singleCameraId, { junctionId: junction.id }) : null,
      });
    }

    return liveSummaries
      .sort((left, right) => (right.incidentCount ?? 0) - (left.incidentCount ?? 0) || left.title.localeCompare(right.title))
      .slice(0, 5);
  }

  const availability: FeedAvailability =
    eventsStatus.availability === "live" || violationsStatus.availability === "live"
      ? "live"
      : eventsStatus.availability === "pending_backend" || violationsStatus.availability === "pending_backend"
        ? "pending_backend"
        : "unreachable";

  // When feeds are live, aggregate real event/violation counts per camera → junction
  if (availability === "live") {
    const camerasById = new Map(cameras.map((camera) => [camera.id, camera]));
    const countsByJunction = new Map<string, number>();

    for (const event of recentEvents) {
      const camera = camerasById.get(event.camera_id);
      if (camera) {
        countsByJunction.set(camera.junctionId, (countsByJunction.get(camera.junctionId) ?? 0) + 1);
      }
    }
    for (const violation of recentViolations) {
      const camera = camerasById.get(violation.camera_id);
      if (camera) {
        countsByJunction.set(camera.junctionId, (countsByJunction.get(camera.junctionId) ?? 0) + 1);
      }
    }

    const totalEvents = eventsStatus.totalCount ?? 0;
    const totalViolations = violationsStatus.totalCount ?? 0;
    const feedNote =
      totalEvents + totalViolations > 0
        ? `Live feeds: ${totalEvents} events and ${totalViolations} violations from the backend.`
        : "Event and violation feeds are live but no incidents have been recorded yet.";

    return junctions
      .map((junction) => ({
        id: `incident-${junction.id}`,
        title: junction.name,
        locationName: junction.name,
        locationType: "junction" as const,
        incidentCount: countsByJunction.get(junction.id) ?? 0,
        availability: "live" as const,
        note: feedNote,
        source: "camera_metadata" as const,
        trendLabel: null,
        cameraIds: junction.cameraIds,
        junctionId: junction.id,
        dashboardHref: junction.dashboardHref,
        eventFeedHref: junction.eventFeedHref,
        cameraDetailHref: junction.cameraCount === 1 ? buildSingleCameraDetailHref(junction.cameraIds, junction.id) : null,
      }))
      .sort((left, right) => (right.incidentCount ?? 0) - (left.incidentCount ?? 0) || left.title.localeCompare(right.title))
      .slice(0, 5);
  }

  const note =
    availability === "pending_backend"
      ? "Top incident counts are waiting on the /events and /violations APIs. Location cards are scaffolded from current junction grouping only."
      : "Incident feeds are currently unreachable, so this section is showing placeholders only.";

  return junctions.slice(0, 5).map((junction) => ({
    id: `incident-${junction.id}`,
    title: junction.name,
    locationName: junction.name,
    locationType: "junction",
    incidentCount: null,
    availability,
    note,
    source: "camera_metadata",
    trendLabel: null,
    cameraIds: junction.cameraIds,
    junctionId: junction.id,
    dashboardHref: junction.dashboardHref,
    eventFeedHref: junction.eventFeedHref,
    cameraDetailHref: junction.cameraCount === 1 ? buildSingleCameraDetailHref(junction.cameraIds, junction.id) : null,
  }));
}

export function buildHotspotOverviewRequest(args: {
  now: Date;
  config: SpatialAnalyticsConfig;
}): HotspotAnalyticsRequestApi {
  const periodEnd = args.now;
  const periodStart = new Date(periodEnd.getTime() - args.config.lookbackDays * 24 * 60 * 60 * 1000);

  return {
    period_start: periodStart.toISOString(),
    period_end: periodEnd.toISOString(),
    granularity: "day",
    group_by: ["camera", "source_kind"],
    compare_previous: true,
    source_kinds: ["violation_event", "watchlist_alert"],
    top_n: args.config.topN,
  };
}

function deriveSpatialMarkerCounts(args: {
  cameras: CameraMapItem[];
  analyticsPayload: HotspotAnalyticsResponseApi | null;
}): {
  incidentCountsByCamera: Map<string, number>;
  incidentCountsByJunction: Map<string, number>;
} {
  const incidentCountsByCamera = new Map<string, number>();
  const incidentCountsByJunction = new Map<string, number>();

  if (!args.analyticsPayload) {
    return { incidentCountsByCamera, incidentCountsByJunction };
  }

  const camerasById = new Map(args.cameras.map((camera) => [camera.id, camera]));

  for (const point of args.analyticsPayload.heatmap) {
    if (!point.camera_id || point.event_count <= 0) {
      continue;
    }

    const camera = camerasById.get(point.camera_id);
    if (!camera) {
      continue;
    }

    incidentCountsByCamera.set(
      camera.id,
      (incidentCountsByCamera.get(camera.id) ?? 0) + point.event_count,
    );
    incidentCountsByJunction.set(
      camera.junctionId,
      (incidentCountsByJunction.get(camera.junctionId) ?? 0) + point.event_count,
    );
  }

  return { incidentCountsByCamera, incidentCountsByJunction };
}

export function buildSpatialMapMarkers(args: {
  cameras: CameraMapItem[];
  junctions: JunctionSummary[];
  analyticsPayload: HotspotAnalyticsResponseApi | null;
  selectedCameraId: string | null;
  selectedJunctionId: string | null;
}): SpatialMapMarker[] {
  const { incidentCountsByCamera, incidentCountsByJunction } = deriveSpatialMarkerCounts({
    cameras: args.cameras,
    analyticsPayload: args.analyticsPayload,
  });

  const junctionMarkers = args.junctions
    .filter(
      (junction) =>
        junction.coordinates !== null &&
        (junction.cameraCount > 1 || (!args.selectedCameraId && junction.id === args.selectedJunctionId)),
    )
    .map((junction) => {
      const incidentCount = incidentCountsByJunction.get(junction.id) ?? 0;
      return {
        id: `junction-${junction.id}`,
        kind: "junction",
        label: junction.name,
        detail:
          incidentCount > 0
            ? `${incidentCount} recent incidents across ${junction.cameraCount} cameras`
            : `${junction.activeCameraCount}/${junction.cameraCount} cameras active`,
        coordinates: junction.coordinates as CoordinatePoint,
        badge: incidentCount > 0 ? `${incidentCount}` : null,
        tone: mapMarkerToneFromJunction(junction, incidentCount),
        href: junction.dashboardHref,
        isSelected: junction.id === args.selectedJunctionId,
      } satisfies SpatialMapMarker;
    });

  const cameraMarkers = args.cameras
    .filter((camera) => camera.coordinates !== null)
    .map((camera) => {
      const incidentCount = incidentCountsByCamera.get(camera.id) ?? 0;
      return {
        id: `camera-${camera.id}`,
        kind: "camera",
        label: camera.code,
        detail:
          incidentCount > 0
            ? `${camera.name} · ${incidentCount} recent incidents`
            : `${camera.name} · ${camera.status}`,
        coordinates: camera.coordinates as CoordinatePoint,
        badge: incidentCount > 0 ? `${incidentCount}` : null,
        tone: mapMarkerToneFromCamera(camera, incidentCount),
        href: camera.dashboardHref,
        isSelected: camera.id === args.selectedCameraId,
      } satisfies SpatialMapMarker;
    });

  return [...junctionMarkers, ...cameraMarkers];
}

export function deriveFeedSummary(
  eventCountsResult: ApiResult<CameraEventCountApi[]>,
  violationCountsResult: ApiResult<CameraViolationCountApi[]>,
): FeedSummaryModel {
  const eventCounts =
    eventCountsResult.ok && eventCountsResult.data ? eventCountsResult.data : [];
  const violationCounts =
    violationCountsResult.ok && violationCountsResult.data ? violationCountsResult.data : [];

  return {
    eventCounts,
    violationCounts,
    totalEvents: eventCounts.reduce((sum, row) => sum + row.event_count, 0),
    totalViolations: violationCounts.reduce((sum, row) => sum + row.violation_count, 0),
  };
}

export function buildSpatialOperationsModel(args: {
  camerasResult: ApiResult<CameraListResponse>;
  eventsResult: ApiResult<DetectionEventSearchResult>;
  violationsResult: ApiResult<ViolationSearchResult>;
  hotspotAnalyticsRequest: HotspotAnalyticsRequestApi;
  hotspotAnalyticsResult: ApiResult<HotspotAnalyticsResponseApi>;
  eventCountsResult: ApiResult<CameraEventCountApi[]>;
  violationCountsResult: ApiResult<CameraViolationCountApi[]>;
  eventSummaryTotalsResult: ApiResult<EventSummaryTotalsApi>;
  violationSummaryTotalsResult: ApiResult<ViolationSummaryTotalsApi>;
  selectedCameraDetail: ApiResult<CameraDetailApi> | null;
  selectedCameraId: string | null;
  selectedJunctionId: string | null;
  provider: MapProviderConfig;
}): SpatialOperationsModel {
  const cameras = args.camerasResult.data?.items ?? [];
  const cameraItems = toCameraMapItems(cameras);
  const junctions = groupCamerasIntoJunctions(cameraItems);
  const mappedCameras = cameraItems.filter((camera) => camera.coordinates !== null);
  const feeds = {
    events: toEventFeedStatus(args.eventsResult),
    violations: toViolationFeedStatus(args.violationsResult),
  };
  const recentEvents: DetectionEventReadApi[] =
    args.eventsResult.ok && args.eventsResult.data ? args.eventsResult.data.items : [];
  const recentViolations: ViolationEventReadApi[] =
    args.violationsResult.ok && args.violationsResult.data ? args.violationsResult.data.items : [];
  const spatialAnalytics = toSpatialAnalyticsStatus(
    args.hotspotAnalyticsResult,
    args.hotspotAnalyticsRequest,
  );
  const hotspotAnalyticsPayload = args.hotspotAnalyticsResult.ok
    ? args.hotspotAnalyticsResult.data
    : null;

  const selectedCamera =
    cameraItems.find((camera) => camera.id === args.selectedCameraId) ?? null;

  const explicitlySelectedJunction = args.selectedJunctionId
    ? junctions.find((junction) => junction.id === args.selectedJunctionId) ?? null
    : null;

  const selectedJunction = selectedCamera
    ? junctions.find((junction) => junction.id === selectedCamera.junctionId) ?? explicitlySelectedJunction
    : explicitlySelectedJunction;

  const incidentSummaries = deriveIncidentSummaries(
    junctions,
    cameraItems,
    feeds.events,
    feeds.violations,
    spatialAnalytics,
    hotspotAnalyticsPayload,
    recentEvents,
    recentViolations,
  );
  const hotspots = deriveHotspots(junctions, cameraItems, spatialAnalytics, hotspotAnalyticsPayload);
  const selectedIncidentSummary =
    incidentSummaries.find((summary) => summary.junctionId === selectedJunction?.id) ?? null;
  const selectedHotspots = hotspots.filter((hotspot) => {
    if (selectedCamera) {
      return hotspot.cameraIds.includes(selectedCamera.id);
    }
    if (selectedJunction) {
      return hotspot.junctionId === selectedJunction.id;
    }
    return false;
  });

  const feedSummary = deriveFeedSummary(args.eventCountsResult, args.violationCountsResult);

  return {
    cameras: cameraItems,
    mappedCameras,
    junctions,
    mapMarkers: buildSpatialMapMarkers({
      cameras: cameraItems,
      junctions,
      analyticsPayload: hotspotAnalyticsPayload,
      selectedCameraId: args.selectedCameraId,
      selectedJunctionId: args.selectedJunctionId,
    }),
    hotspots,
    selectedHotspots,
    incidentSummaries,
    selectedIncidentSummary,
    selectedCamera,
    selectedCameraDetail:
      args.selectedCameraDetail && args.selectedCameraDetail.ok
        ? args.selectedCameraDetail.data
        : null,
    selectedJunction,
    spatialAnalytics,
    provider: args.provider,
    feeds,
    feedSummary,
    eventSummaryTotals: args.eventSummaryTotalsResult.ok ? args.eventSummaryTotalsResult.data : null,
    violationSummaryTotals: args.violationSummaryTotalsResult.ok ? args.violationSummaryTotalsResult.data : null,
    recentEvents,
    recentViolations,
  };
}