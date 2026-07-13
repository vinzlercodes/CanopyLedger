"use client";

import { useActionState } from "react";

import { submitSupersessionAction, type ActionState } from "@/lib/api/governance-actions";

export function SupersessionActions({ candidateFactId, approvedFactIds, returnPath }: { readonly candidateFactId: string; readonly approvedFactIds: readonly string[]; readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(submitSupersessionAction, {} as ActionState);
  if (approvedFactIds.length === 0) return null;
  return <form action={formAction} className="approval-actions"><input name="candidateFactId" type="hidden" value={candidateFactId} /><input name="returnPath" type="hidden" value={returnPath} /><label>Active approved fact to supersede<select disabled={pending} name="approvedFactId" required>{approvedFactIds.map((id) => <option key={id} value={id}>{id}</option>)}</select></label><div><button disabled={pending} type="submit">Approve correction and supersede</button></div>{state.error && <p className="action-error" role="alert">{state.error}</p>}{state.message && <p className="action-success" role="status">{state.message}</p>}</form>;
}
