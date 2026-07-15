import { headers } from "next/headers";

import type {
  ApprovalQueueResponse,
  CollateralWorkspaceResponse,
  ClimateTraceabilityProjectionResponse,
  CreditEarlyWarningProjectionResponse,
  DecisionOverrideQueueResponse,
  DecisionPackResponse,
  EvidenceReviewQueueResponse,
  GovernanceTimelineResponse,
  HedgeLabProjectionResponse,
  ScenarioLabProjectionResponse,
} from "../../../../../typescript/generated/index";

import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";
import { loadContext, type LoadedContext } from "@/lib/api/load-context";
import type { WorkspaceSlug } from "@/lib/context";

export type ApprovalWorkspaceData = {
  readonly approvalQueue: ApprovalQueueResponse;
  readonly overrideQueue: DecisionOverrideQueueResponse;
  readonly timeline: GovernanceTimelineResponse;
};

export type WorkspaceData =
  | DecisionPackResponse
  | CollateralWorkspaceResponse
  | ClimateTraceabilityProjectionResponse
  | CreditEarlyWarningProjectionResponse
  | EvidenceReviewQueueResponse
  | HedgeLabProjectionResponse
  | ScenarioLabProjectionResponse
  | ApprovalWorkspaceData;

export type LoadedWorkspace = {
  readonly context: LoadedContext;
  readonly data?: WorkspaceData;
  readonly error?: { readonly title: string; readonly detail: string; readonly state: "unauthorized" | "not-found" | "failed" };
};

export async function loadWorkspace({
  facilityId,
  snapshotId,
  workspace,
  collateral,
}: {
  readonly facilityId: string;
  readonly snapshotId: string;
  readonly workspace: WorkspaceSlug;
  readonly collateral?: {
    readonly section?: "inventory" | "receivables" | "contributions" | "reserves";
    readonly cursor?: string;
  };
}): Promise<LoadedWorkspace> {
  const context = await loadContext({ facilityId, snapshotId });
  if (context.kind !== "snapshot") {
    if (context.kind === "unavailable") {
      return {
        context,
        error: {
          state: context.status === "unauthorized" || context.status === "not-found" ? context.status : "failed",
          title: context.title,
          detail: context.detail,
        },
      };
    }
    return { context };
  }

  try {
    const requestHeaders = await headers();
    const client = createApiClient(requestHeaders.get("authorization"));
    if (workspace === "approvals") {
      const [approvalQueue, overrideQueue, timeline] = await Promise.all([
        client.getApprovalQueue(),
        client.getDecisionOverrideQueue(snapshotId),
        client.getGovernanceTimeline(snapshotId),
      ]);
      return {
        context,
        data: {
          approvalQueue: requireSuccess(approvalQueue),
          overrideQueue: requireSuccess(overrideQueue),
          timeline: requireSuccess(timeline),
        },
      };
    }
    if (workspace === "analytics") {
      return { context };
    }
    const response = await {
      cockpit: () => client.getSnapshotDecisionPack(snapshotId),
      collateral: () => client.getSnapshotCollateral(snapshotId, collateral),
      evidence: () => client.getEvidenceReviewQueue(),
      "risk/hedge": () => client.getHedgeLabProjection(snapshotId),
      "risk/scenarios": () => client.getScenarioLabProjection(snapshotId),
      climate: () => client.getClimateTraceabilityProjection(snapshotId),
      credit: () => client.getCreditEarlyWarningProjection(snapshotId),
    }[workspace]();
    return { context, data: requireSuccess<WorkspaceData>(response as never) };
  } catch (error) {
    if (error instanceof ApiProblem && (error.status === 401 || error.status === 403)) {
      return { context, error: { state: "unauthorized", title: "Role access is required", detail: "This workspace only shows data after the API authorizes the forwarded session." } };
    }
    if (error instanceof ApiProblem && error.status === 404) {
      return { context, error: { state: "not-found", title: "No published workspace output is available", detail: "The selected snapshot has no visible output for this stage." } };
    }
    return { context, error: { state: "failed", title: "This governed workspace is unavailable", detail: "No value is inferred, recalculated, or shown while its authoritative projection cannot be loaded." } };
  }
}
