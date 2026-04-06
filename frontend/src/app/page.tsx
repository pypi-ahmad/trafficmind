import {
  fetchCameraDetail,
  fetchCameraList,
  fetchEventCountsByCamera,
  fetchEventsFeed,
  fetchHotspotAnalytics,
  fetchViolationCountsByCamera,
  fetchViolationsFeed,
} from "@/features/operations/api";
import { getMapProviderConfig, getSpatialAnalyticsConfig } from "@/features/operations/config";
import { OperationsDashboard } from "@/features/operations/components/operations-dashboard";
import {
  buildHotspotOverviewRequest,
  buildSpatialOperationsModel,
  getSingleParam,
} from "@/features/operations/derive";

export const dynamic = "force-dynamic";

type HomePageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function HomePage({ searchParams }: HomePageProps) {
  const params = await searchParams;
  const selectedCameraId = getSingleParam(params.cameraId);
  const selectedJunctionId = getSingleParam(params.junctionId);
  const hotspotAnalyticsRequest = buildHotspotOverviewRequest({
    now: new Date(),
    config: getSpatialAnalyticsConfig(),
  });

  const lookbackMs = getSpatialAnalyticsConfig().lookbackDays * 24 * 60 * 60 * 1000;
  const occurredAfter = new Date(Date.now() - lookbackMs).toISOString();

  const [camerasResult, eventsResult, violationsResult, hotspotAnalyticsResult, selectedCameraDetail, eventCountsResult, violationCountsResult] = await Promise.all([
    fetchCameraList(),
    fetchEventsFeed(),
    fetchViolationsFeed(),
    fetchHotspotAnalytics(hotspotAnalyticsRequest),
    selectedCameraId ? fetchCameraDetail(selectedCameraId) : Promise.resolve(null),
    fetchEventCountsByCamera({ occurredAfter }),
    fetchViolationCountsByCamera({ occurredAfter }),
  ]);

  const model = buildSpatialOperationsModel({
    camerasResult,
    eventsResult,
    violationsResult,
    hotspotAnalyticsRequest,
    hotspotAnalyticsResult,
    eventCountsResult,
    violationCountsResult,
    selectedCameraDetail,
    selectedCameraId,
    selectedJunctionId,
    provider: getMapProviderConfig(),
  });

  return <OperationsDashboard model={model} />;
}
