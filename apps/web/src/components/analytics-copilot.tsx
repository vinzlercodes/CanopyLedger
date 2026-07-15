"use client";

import { useActionState } from "react";

import {
  askAnalyticsQuestionAction,
  type AnalyticsActionState,
} from "@/lib/api/analytics-actions";

const approvedQuestions = [
  "Show snapshot summary",
  "Which inventory lots contribute most to reserves?",
  "Which receivables were excluded due to age?",
  "What is hedge ratio by delivery month?",
  "Which scenario produces lowest IRC?",
  "Why did availability decline between snapshots?",
  "Which approved facts changed since previous decision?",
] as const;

export function AnalyticsCopilot({
  facilityId,
  snapshotId,
  returnPath,
}: {
  readonly facilityId: string;
  readonly snapshotId: string;
  readonly returnPath: string;
}) {
  const [state, formAction, pending] = useActionState(
    askAnalyticsQuestionAction,
    {} as AnalyticsActionState,
  );
  const answer = state.answer;

  return (
    <div className="workspace-page">
      <section className="workspace-heading">
        <div>
          <span className="eyebrow">M8 · governed analytical reads</span>
          <h1>Analytics Copilot</h1>
          <p>
            Questions compile to a fixed read plan. This workspace never sends SQL from the
            browser, calculates capacity, approves evidence, or changes a decision.
          </p>
        </div>
      </section>
      <section className="panel document-intake" aria-labelledby="analytics-question-title">
        <div>
          <span className="eyebrow">Approved template question</span>
          <h2 id="analytics-question-title">Ask about this frozen snapshot</h2>
          <p>
            Ambiguous questions, cross-facility scope, and disallowed query plans are refused by
            the API and shown here without fallback.
          </p>
        </div>
        <form action={formAction} className="approval-actions">
          <input name="facilityId" type="hidden" value={facilityId} />
          <input name="snapshotId" type="hidden" value={snapshotId} />
          <input name="returnPath" type="hidden" value={returnPath} />
          <label>
            Question
            <select defaultValue={approvedQuestions[0]} disabled={pending} name="question">
              {approvedQuestions.map((question) => (
                <option key={question} value={question}>
                  {question}
                </option>
              ))}
            </select>
          </label>
          <label>
            Comparison snapshot (only comparison templates)
            <input disabled={pending} name="comparisonSnapshotId" placeholder="snp_…" />
          </label>
          <button disabled={pending} type="submit">
            {pending ? "Running governed read…" : "Run approved read"}
          </button>
          {state.error && <p className="action-error" role="alert">{state.error}</p>}
        </form>
      </section>
      {answer && (
        <section className="panel data-table-panel" aria-labelledby="analytics-answer-title">
          <div className="table-heading">
            <div>
              <span className="eyebrow">Structured answer · read-only</span>
              <h2 id="analytics-answer-title">{answer.plan.template_id.replaceAll("_", " ")}</h2>
            </div>
            <code>{answer.query_run_id}</code>
          </div>
          <dl>
            <div><dt>Scope</dt><dd>{Object.entries(answer.scope).map(([key, value]) => `${key}: ${value}`).join(" · ")}</dd></div>
            <div><dt>Data cutoff</dt><dd>{answer.data_cutoff}</dd></div>
            <div><dt>Views</dt><dd>{answer.referenced_views.join(", ")}</dd></div>
            <div><dt>Query digest</dt><dd><code>{answer.query_digest}</code></dd></div>
          </dl>
          <pre className="projection-json">{JSON.stringify(answer.result, null, 2)}</pre>
          <details className="lineage">
            <summary>Lineage, assumptions, and warnings</summary>
            <dl>
              <div><dt>Lineage</dt><dd>{answer.lineage.join(", ") || "No source digests were returned."}</dd></div>
              <div><dt>Assumptions</dt><dd>{answer.assumptions.join(" ")}</dd></div>
              <div><dt>Units</dt><dd>{Object.entries(answer.units).map(([key, value]) => `${key}: ${value}`).join(" · ")}</dd></div>
              <div><dt>Warnings</dt><dd>{answer.warnings.join(", ") || "None returned."}</dd></div>
            </dl>
          </details>
        </section>
      )}
    </div>
  );
}
