"use client";

import { useActionState } from "react";

import { submitApprovalAction, type ActionState } from "@/lib/api/governance-actions";

export function ApprovalActions({ approvalRequestId, returnPath }: { readonly approvalRequestId: string; readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(submitApprovalAction, {} as ActionState);
  return <form action={formAction} className="approval-actions"><input name="approvalRequestId" type="hidden" value={approvalRequestId} /><input name="returnPath" type="hidden" value={returnPath} /><label>Decision reason<textarea disabled={pending} name="reason" required rows={2} /></label><div><button disabled={pending} name="action" type="submit" value="approve">Approve</button><button className="danger-action" disabled={pending} name="action" type="submit" value="reject">Reject</button></div>{state.error && <p className="action-error" role="alert">{state.error}</p>}{state.message && <p className="action-success" role="status">{state.message}</p>}</form>;
}
