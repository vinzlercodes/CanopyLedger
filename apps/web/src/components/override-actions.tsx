"use client";

import { useActionState } from "react";
import Link from "next/link";

import { submitOverrideAction, type OverrideActionState } from "@/lib/api/governance-actions";

export function OverrideActions({ decisionId, currency, returnPath }: { readonly decisionId: string; readonly currency: string; readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(submitOverrideAction, {} as OverrideActionState);
  const overrideHref = state.overrideId ? `${returnPath.replace(/\/cockpit$/, "/approvals")}/overrides/${encodeURIComponent(state.overrideId)}` : undefined;
  return <section className="override-actions"><h3>Request dual-control override</h3><p>Creates an immutable request; a separate eligible approver must approve it.</p><form action={formAction} className="approval-actions"><input name="decisionId" type="hidden" value={decisionId} /><input name="returnPath" type="hidden" value={returnPath} /><label>Proposed exposure cap<input inputMode="decimal" name="amount" required /></label><label>Currency<input name="currency" required value={currency} readOnly /></label><label>Policy basis<input name="policyBasis" required /></label><label>Expiry<input name="expiresAt" required type="datetime-local" /></label><label>Reason<textarea disabled={pending} name="reason" required rows={2} /></label><div><button disabled={pending} name="action" type="submit" value="request">Request override</button></div>{state.error && <p className="action-error" role="alert">{state.error}</p>}{state.message && <p className="action-success" role="status">{state.message}</p>}{state.overrideId && <p className="muted">Override ID: <code>{state.overrideId}</code>{overrideHref && <> · <Link href={overrideHref}>Open override review</Link></>}</p>}</form></section>;
}
