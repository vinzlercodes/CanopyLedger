"use client";

import { useActionState } from "react";

import {
  submitDocumentIntakeAction,
  type DocumentIntakeActionState,
} from "@/lib/api/governance-actions";

export function DocumentIntake({ returnPath }: { readonly returnPath: string }) {
  const [state, formAction, pending] = useActionState(
    submitDocumentIntakeAction,
    {} as DocumentIntakeActionState,
  );
  return (
    <section className="panel document-intake" aria-labelledby="document-intake-title">
      <div>
        <span className="eyebrow">Document intelligence · candidate-only</span>
        <h2 id="document-intake-title">Ingest a known document</h2>
        <p>
          PDFs and UTF-8 text are safely classified and parsed. Extraction never approves a fact,
          changes collateral, or affects a frozen snapshot.
        </p>
      </div>
      <form action={formAction} className="approval-actions">
        <input name="returnPath" type="hidden" value={returnPath} />
        <label>
          Original document (PDF or text, 5 MiB maximum)
          <input accept="application/pdf,text/plain" disabled={pending} name="document" type="file" />
        </label>
        <button disabled={pending} type="submit">
          {pending ? "Extracting candidate facts…" : "Ingest and extract"}
        </button>
        {state.message && (
          <p className="action-success" role="status">
            {state.message}
            {state.extractionId && <> Extraction <code>{state.extractionId}</code> returned {state.candidateCount} candidate fact(s).</>}
          </p>
        )}
        {state.error && <p className="action-error" role="alert">{state.error}</p>}
      </form>
    </section>
  );
}
