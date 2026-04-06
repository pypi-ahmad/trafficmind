import {
  fetchCameraDetail,
  fetchCameraList,
  fetchEventsStatus,
  fetchHotspotAnalytics,
  fetchViolationsStatus,
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

  const [camerasResult, eventsResult, violationsResult, hotspotAnalyticsResult, selectedCameraDetail] = await Promise.all([
    fetchCameraList(),
    fetchEventsStatus(),
    fetchViolationsStatus(),
    fetchHotspotAnalytics(hotspotAnalyticsRequest),
    selectedCameraId ? fetchCameraDetail(selectedCameraId) : Promise.resolve(null),
  ]);

  const model = buildSpatialOperationsModel({
    camerasResult,
    eventsResult,
    violationsResult,
    hotspotAnalyticsRequest,
    hotspotAnalyticsResult,
    selectedCameraDetail,
    selectedCameraId,
    selectedJunctionId,
    provider: getMapProviderConfig(),
  });

  return <OperationsDashboard model={model} />;
}
