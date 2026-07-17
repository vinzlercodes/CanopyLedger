import { headers } from "next/headers";

import type { DecisionPackResponse, ReportPackageResponse } from "../../../../../typescript/generated/index";

import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";
import { loadContext, type LoadedContext } from "@/lib/api/load-context";

export type LoadedReports = {
  readonly context: LoadedContext;
  readonly decisionPack?: DecisionPackResponse;
  readonly reports?: readonly ReportPackageResponse[];
  readonly error?: { readonly title: string; readonly detail: string; readonly state: "unauthorized" | "not-found" | "failed" };
};

export async function loadReports({ facilityId, snapshotId }: { readonly facilityId: string; readonly snapshotId: string }): Promise<LoadedReports> {
  const context = await loadContext({ facilityId, snapshotId });
  if (context.kind !== "snapshot") {
    if (context.kind === "unavailable") {
      return { context, error: { state: context.status === "unauthorized" || context.status === "not-found" ? context.status : "failed", title: context.title, detail: context.detail } };
    }
    return { context };
  }
  try {
    const client = createApiClient((await headers()).get("authorization"));
    const decisionPack = requireSuccess(await client.getSnapshotDecisionPack(snapshotId));
    if (decisionPack.final_decision === null || decisionPack.final_decision === undefined) return { context, decisionPack, reports: [] };
    const reports = requireSuccess(await client.listDecisionReports(decisionPack.final_decision.resource_id));
    return { context, decisionPack, reports };
  } catch (error) {
    if (error instanceof ApiProblem && (error.status === 401 || error.status === 403)) return { context, error: { state: "unauthorized", title: "Role access is required", detail: "The API must authorize the report viewer before it receives a report package." } };
    if (error instanceof ApiProblem && error.status === 404) return { context, error: { state: "not-found", title: "No immutable report package is available", detail: "The selected snapshot or decision cannot be found by the API." } };
    return { context, error: { state: "failed", title: "The report viewer is unavailable", detail: "No report values are inferred or reconstructed in the browser." } };
  }
}
