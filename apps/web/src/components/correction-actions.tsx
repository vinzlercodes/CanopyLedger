"use client";

import Link from "next/link";
import { useActionState } from "react";

import { submitCorrectionAction, type CorrectionActionState } from "@/lib/api/governance-actions";

type BaseCandidate = {
  readonly fact_type: string;
  readonly subject_id: string;
  readonly period: string;
  readonly document_version_id: string;
  readonly document_byte_digest: string;
  readonly page_region: string;
  readonly value: Record<string, unknown>;
  readonly raw_value: string;
  readonly normalized_value: string;
};

export function CorrectionActions({ baseCandidate, returnPath }: { readonly baseCandidate: BaseCandidate; readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(submitCorrectionAction, {} as CorrectionActionState);
  const detailHref = state.candidateFactId ? `${returnPath}/${encodeURIComponent(state.candidateFactId)}` : undefined;
  return <section className="override-actions"><h3>Record correction candidate</h3><p>A correction remains candidate evidence until a human explicitly supersedes the active approved fact.</p><form action={formAction} className="approval-actions"><input name="returnPath" type="hidden" value={returnPath} /><input name="baseCandidate" type="hidden" value={JSON.stringify(baseCandidate)} /><label>Corrected raw value<input defaultValue={baseCandidate.raw_value} disabled={pending} name="rawValue" required /></label><label>Corrected normalized value<input defaultValue={baseCandidate.normalized_value} disabled={pending} name="normalizedValue" required /></label><label>Corrected value JSON<textarea defaultValue={JSON.stringify(baseCandidate.value, null, 2)} disabled={pending} name="value" required rows={4} /></label><div><button disabled={pending} type="submit">Create correction candidate</button></div>{state.error && <p className="action-error" role="alert">{state.error}</p>}{state.message && <p className="action-success" role="status">{state.message}</p>}{detailHref && <Link href={detailHref}>Open correction review</Link>}</form></section>;
}
