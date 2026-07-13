"use client";

import { useActionState } from "react";

import { submitOverrideAction, type OverrideActionState } from "@/lib/api/governance-actions";

export function OverrideApprovalActions({ overrideId, returnPath }: { readonly overrideId: string; readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(submitOverrideAction, {} as OverrideActionState);
  return <form action={formAction} className="approval-actions"><input name="overrideId" type="hidden" value={overrideId} /><input name="returnPath" type="hidden" value={returnPath} /><label>Independent approval reason<textarea disabled={pending} name="reason" required rows={2} /></label><div><button disabled={pending} name="action" type="submit" value="approve">Record override approval</button></div>{state.error && <p className="action-error" role="alert">{state.error}</p>}{state.message && <p className="action-success" role="status">{state.message}</p>}</form>;
}
