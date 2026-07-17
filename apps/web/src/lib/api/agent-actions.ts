"use server";

import { randomUUID } from "node:crypto";

import type { AgentRunResponse } from "../../../../../typescript/generated/index";
import { headers } from "next/headers";
import { revalidatePath } from "next/cache";

import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";

export type AgentActionState = {
  readonly run?: AgentRunResponse;
  readonly error?: string;
};

export async function startAgentRunAction(
  _: AgentActionState,
  formData: FormData,
): Promise<AgentActionState> {
  const facilityId = String(formData.get("facilityId") ?? "");
  const snapshotId = String(formData.get("snapshotId") ?? "");
  const agentRole = String(formData.get("agentRole") ?? "");
  const goal = String(formData.get("goal") ?? "").trim();
  const returnPath = String(formData.get("returnPath") ?? "/");
  if (!facilityId || !snapshotId || !agentRole || !goal) {
    return { error: "A facility, frozen snapshot, bounded role, and goal are required." };
  }

  try {
    const client = createApiClient((await headers()).get("authorization"));
    const run = requireSuccess(
      await client.startAgentRun(facilityId, snapshotId, {
        run_id: `agr_${randomUUID()}`,
        agent_role: agentRole as "facility_orchestrator" | "decision_pack_assistant",
        goal,
      }),
    );
    revalidatePath(returnPath);
    return { run };
  } catch (error) {
    return {
      error:
        error instanceof ApiProblem
          ? error.message
          : "The governed agent run could not be started.",
    };
  }
}
