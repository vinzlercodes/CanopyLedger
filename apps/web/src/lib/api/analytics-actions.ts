"use server";

import type { AnalyticsAnswerResponse } from "../../../../../typescript/generated/index";
import { headers } from "next/headers";
import { revalidatePath } from "next/cache";

import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";

export type AnalyticsActionState = {
  readonly answer?: AnalyticsAnswerResponse;
  readonly error?: string;
};

export async function askAnalyticsQuestionAction(
  _: AnalyticsActionState,
  formData: FormData,
): Promise<AnalyticsActionState> {
  const facilityId = String(formData.get("facilityId") ?? "");
  const snapshotId = String(formData.get("snapshotId") ?? "");
  const comparisonSnapshotId = String(formData.get("comparisonSnapshotId") ?? "").trim();
  const question = String(formData.get("question") ?? "").trim();
  const returnPath = String(formData.get("returnPath") ?? "/");
  if (!facilityId || !snapshotId || !question) {
    return { error: "A facility, immutable snapshot, and approved question are required." };
  }

  try {
    const client = createApiClient((await headers()).get("authorization"));
    const answer = requireSuccess(
      await client.askAnalyticsQuestion(facilityId, {
        question,
        snapshot_id: snapshotId,
        comparison_snapshot_id: comparisonSnapshotId || undefined,
      }),
    );
    revalidatePath(returnPath);
    return { answer };
  } catch (error) {
    return {
      error:
        error instanceof ApiProblem
          ? error.message
          : "The governed analytics service could not answer this question.",
    };
  }
}
