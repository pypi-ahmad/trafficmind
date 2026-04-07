import { EvaluationDashboard } from "@/features/evaluation/components/evaluation-dashboard";
import { fetchEvaluationSummary } from "@/features/evaluation/api";
import { buildEvaluationDashboardModel, coerceTaskType, getSingleParam } from "@/features/evaluation/derive";
import { fetchAccessPolicy } from "@/features/evidence/api";
import { coerceEvidenceAccessRole } from "@/features/evidence/types";

export const metadata = { title: "Evaluation | TrafficMind" };
export const dynamic = "force-dynamic";

type EvaluationPageProps = {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
};

export default async function EvaluationPage({ searchParams }: EvaluationPageProps) {
  const params = await searchParams;
  const accessRole = coerceEvidenceAccessRole(getSingleParam(params.accessRole));

  const [result, accessPolicyResult] = await Promise.all([
    fetchEvaluationSummary(),
    fetchAccessPolicy(accessRole),
  ]);

  const model = buildEvaluationDashboardModel(result, {
    taskType: coerceTaskType(getSingleParam(params.taskType)),
    scenario: getSingleParam(params.scenario),
    modelVersion: getSingleParam(params.modelVersion),
    camera: getSingleParam(params.camera),
    dateAfter: getSingleParam(params.dateAfter),
    dateBefore: getSingleParam(params.dateBefore),
  });

  return (
    <EvaluationDashboard
      model={model}
      accessPolicy={accessPolicyResult.ok ? accessPolicyResult.data : null}
      accessRole={accessRole}
      accessPolicyError={accessPolicyResult.error}
    />
  );
}