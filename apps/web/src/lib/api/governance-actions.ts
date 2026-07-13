"use server";

import { headers } from "next/headers";
import { revalidatePath } from "next/cache";

import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";
import { makeCommandResourceId } from "@/lib/ids";

export type ActionState = { readonly message?: string; readonly error?: string };
export type OverrideActionState = ActionState & { readonly overrideId?: string };
export type CorrectionActionState = ActionState & { readonly candidateFactId?: string };

export async function submitApprovalAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const approvalRequestId = String(formData.get("approvalRequestId") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  const action = String(formData.get("action") ?? "");
  const returnPath = String(formData.get("returnPath") ?? "/");
  if (!approvalRequestId || !reason || (action !== "approve" && action !== "reject")) return { error: "A reason and a valid approval action are required." };

  try {
    const client = createApiClient((await headers()).get("authorization"));
    const body = { approval_action_id: makeCommandResourceId("apa"), final_decision_id: makeCommandResourceId("fdc"), reason };
    const response = action === "approve"
      ? await client.approveApprovalRequest(approvalRequestId, body)
      : await client.rejectApprovalRequest(approvalRequestId, body);
    requireSuccess(response as never);
    revalidatePath(returnPath);
    return { message: action === "approve" ? "Approval recorded by the governed API." : "Rejection recorded by the governed API." };
  } catch (error) {
    return { error: error instanceof ApiProblem ? error.message : "The governed API could not record this action." };
  }
}

export async function submitEvidenceAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const candidateFactId = String(formData.get("candidateFactId") ?? "");
  const reason = String(formData.get("reason") ?? "").trim();
  const action = String(formData.get("action") ?? "");
  const returnPath = String(formData.get("returnPath") ?? "/");
  if (!candidateFactId || (action !== "approve" && action !== "reject")) return { error: "A valid evidence action is required." };
  if (action === "reject" && !reason) return { error: "A rejection reason is required." };

  try {
    const client = createApiClient((await headers()).get("authorization"));
    const response = action === "approve"
      ? await client.approveCandidateFact(candidateFactId)
      : await client.rejectCandidateFact(candidateFactId, { reason });
    requireSuccess(response as never);
    revalidatePath(returnPath);
    return { message: action === "approve" ? "Evidence fact approved by the governed API." : "Evidence fact rejected by the governed API." };
  } catch (error) {
    return { error: error instanceof ApiProblem ? error.message : "The governed API could not record this evidence action." };
  }
}

export async function submitOverrideAction(_: OverrideActionState, formData: FormData): Promise<OverrideActionState> {
  const action = String(formData.get("action") ?? "");
  const returnPath = String(formData.get("returnPath") ?? "/");
  const reason = String(formData.get("reason") ?? "").trim();
  if (!reason) return { error: "A reason is required for every override action." };

  try {
    const client = createApiClient((await headers()).get("authorization"));
    if (action === "request") {
      const decisionId = String(formData.get("decisionId") ?? "");
      const amount = String(formData.get("amount") ?? "").trim();
      const currency = String(formData.get("currency") ?? "").trim();
      const policyBasis = String(formData.get("policyBasis") ?? "").trim();
      const expiresAt = String(formData.get("expiresAt") ?? "");
      const expires = new Date(expiresAt);
      if (!decisionId || !amount || !currency || !policyBasis || Number.isNaN(expires.getTime())) return { error: "Proposed cap, policy basis, and expiry are required." };
      const response = await client.createDecisionOverride(decisionId, {
        override_id: makeCommandResourceId("ovr"),
        proposed_exposure_cap: { amount, currency },
        reason,
        policy_basis: policyBasis,
        expires_at: expires.toISOString(),
        requires_dual_control: true,
      });
      const created = requireSuccess(response);
      revalidatePath(returnPath);
      return { message: "Dual-control override request recorded by the governed API.", overrideId: created.resource_id };
    }
    if (action === "approve") {
      const overrideId = String(formData.get("overrideId") ?? "");
      if (!overrideId) return { error: "An override ID is required." };
      requireSuccess(await client.approveDecisionOverride(overrideId, { approval_action_id: makeCommandResourceId("apa"), reason }));
      revalidatePath(returnPath);
      return { message: "Override approval recorded. The API enforces dual control.", overrideId };
    }
    return { error: "A valid override action is required." };
  } catch (error) {
    return { error: error instanceof ApiProblem ? error.message : "The governed API could not record this override action." };
  }
}

export async function submitCorrectionAction(_: CorrectionActionState, formData: FormData): Promise<CorrectionActionState> {
  const returnPath = String(formData.get("returnPath") ?? "/");
  try {
    const base = JSON.parse(String(formData.get("baseCandidate") ?? "{}")) as Record<string, unknown>;
    const rawValue = String(formData.get("rawValue") ?? "").trim();
    const normalizedValue = String(formData.get("normalizedValue") ?? "").trim();
    const value = JSON.parse(String(formData.get("value") ?? "{}")) as Record<string, unknown>;
    if (!rawValue || !normalizedValue || value === null || Array.isArray(value)) return { error: "Raw value, normalized value, and a JSON object are required." };
    const client = createApiClient((await headers()).get("authorization"));
    const candidate = requireSuccess(await client.createCandidateFact({
      fact_type: String(base.fact_type ?? ""),
      subject_id: String(base.subject_id ?? ""),
      period: String(base.period ?? ""),
      value,
      document_version_id: String(base.document_version_id ?? ""),
      document_byte_digest: String(base.document_byte_digest ?? ""),
      page_region: String(base.page_region ?? ""),
      extraction_method: "human_correction",
      extractor_version: "1",
      raw_value: rawValue,
      normalized_value: normalizedValue,
    }));
    revalidatePath(returnPath);
    return { message: "Correction candidate created. It is not approved evidence until a human reviews it.", candidateFactId: candidate.candidate_fact_id };
  } catch (error) {
    return { error: error instanceof ApiProblem ? error.message : "The correction candidate could not be created." };
  }
}

export async function submitSupersessionAction(_: ActionState, formData: FormData): Promise<ActionState> {
  const approvedFactId = String(formData.get("approvedFactId") ?? "");
  const candidateFactId = String(formData.get("candidateFactId") ?? "");
  const returnPath = String(formData.get("returnPath") ?? "/");
  if (!approvedFactId || !candidateFactId) return { error: "The approved fact and replacement candidate are required." };
  try {
    const client = createApiClient((await headers()).get("authorization"));
    requireSuccess(await client.supersedeApprovedFact(approvedFactId, { candidate_fact_id: candidateFactId }));
    revalidatePath(returnPath);
    return { message: "Supersession recorded by the governed API." };
  } catch (error) {
    return { error: error instanceof ApiProblem ? error.message : "The governed API could not supersede this fact." };
  }
}
