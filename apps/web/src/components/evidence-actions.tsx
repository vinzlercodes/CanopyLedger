"use client";

import { useActionState } from "react";

import { submitEvidenceAction, type ActionState } from "@/lib/api/governance-actions";

export function EvidenceActions({ candidateFactId, returnPath }: { readonly candidateFactId: string; readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(submitEvidenceAction, {} as ActionState);
  return <form action={formAction} className="approval-actions"><input name="candidateFactId" type="hidden" value={candidateFactId} /><input name="returnPath" type="hidden" value={returnPath} /><label>Rejection reason (required only to reject)<textarea disabled={pending} name="reason" rows={2} /></label><div><button disabled={pending} name="action" type="submit" value="approve">Approve fact</button><button className="danger-action" disabled={pending} name="action" type="submit" value="reject">Reject fact</button></div>{state.error && <p className="action-error" role="alert">{state.error}</p>}{state.message && <p className="action-success" role="status">{state.message}</p>}</form>;
}
