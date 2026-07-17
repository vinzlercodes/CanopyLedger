"use client";

import { useActionState } from "react";

import type { AgentCapabilityResponse, AgentRunResponse } from "../../../../typescript/generated/index";

import { startAgentRunAction, type AgentActionState } from "@/lib/api/agent-actions";

function Trace({ run }: { readonly run: AgentRunResponse }) {
  return (
    <article className="panel audit-timeline">
      <div>
        <span className="eyebrow">{run.status.replaceAll("_", " ")}</span>
        <h2>{String(run.agent_role).replaceAll("_", " ")}</h2>
        <p>Planner: {run.planner_type} · {run.planner_version}</p>
      </div>
      <ol>
        {run.trace.map((event) => (
          <li key={`${event.sequence}-${event.event_type}`}>
            <div>
              <strong>{event.event_type.replaceAll("_", " ")}</strong>
              <span>{event.occurred_at} · {event.detail}</span>
            </div>
          </li>
        ))}
      </ol>
      <details className="lineage">
        <summary>Typed tool calls and run digest</summary>
        <dl>
          <div><dt>Digest</dt><dd><code>{run.digest}</code></dd></div>
          <div><dt>Task plan</dt><dd>{run.task_plan?.planned_capabilities.join(", ") ?? "Unavailable"}</dd></div>
          <div><dt>Calls</dt><dd>{run.tool_calls.map((call) => `${call.capability}: ${call.authorization}`).join(" · ")}</dd></div>
          <div><dt>Results</dt><dd>{run.tool_results.map((result) => `${result.output_schema}: ${result.status}`).join(" · ") || "None"}</dd></div>
          <div><dt>Human handoffs</dt><dd>{run.handoffs.map((handoff) => handoff.approval_request_id).join(", ") || "None"}</dd></div>
        </dl>
      </details>
    </article>
  );
}

export function GovernedAgents({
  facilityId,
  snapshotId,
  returnPath,
  runs,
  capabilities,
}: {
  readonly facilityId: string;
  readonly snapshotId: string;
  readonly returnPath: string;
  readonly runs: readonly AgentRunResponse[];
  readonly capabilities: readonly AgentCapabilityResponse[];
}) {
  const [state, formAction, pending] = useActionState(startAgentRunAction, {} as AgentActionState);
  const visibleRuns = state.run ? [state.run, ...runs.filter((run) => run.resource_id !== state.run?.resource_id)] : runs;
  return (
    <div className="workspace-page">
      <section className="workspace-heading">
        <div>
          <span className="eyebrow">M9 · bounded orchestration</span>
          <h1>Governed Agents</h1>
          <p>Agents only orchestrate typed, registry-approved tools. They cannot calculate CBB or IRC, alter policy, approve a facility, promote evidence, or treat prompt text as permission.</p>
        </div>
      </section>
      <section className="panel document-intake">
        <div>
          <span className="eyebrow">Deterministic replay planner</span>
          <h2>Start a bounded snapshot review</h2>
          <p>Every authorization decision, tool result digest, refusal, retry, and human handoff is retained in the trace timeline.</p>
        </div>
        <form action={formAction} className="approval-actions">
          <input name="facilityId" type="hidden" value={facilityId} />
          <input name="snapshotId" type="hidden" value={snapshotId} />
          <input name="returnPath" type="hidden" value={returnPath} />
          <label>Agent role
            <select defaultValue="facility_orchestrator" disabled={pending} name="agentRole">
              <option value="facility_orchestrator">Facility orchestrator</option>
              <option value="decision_pack_assistant">Decision-pack assistant</option>
            </select>
          </label>
          <label>Bounded goal
            <select defaultValue="Review the frozen snapshot and explain the published scenario stage." disabled={pending} name="goal">
              <option>Review the frozen snapshot.</option>
              <option>Review the frozen snapshot and explain the published scenario stage.</option>
              <option>Review the frozen snapshot and explain the published hedge stage.</option>
            </select>
          </label>
          <button disabled={pending} type="submit">{pending ? "Running governed plan…" : "Run bounded review"}</button>
          {state.error && <p className="action-error" role="alert">{state.error}</p>}
        </form>
      </section>
      <section className="panel data-table-panel">
        <div><span className="eyebrow">Code-owned capability registry</span><h2>Permitted typed tools</h2><p>Absence from this registry is a hard denial; the planner and prompt text cannot add a tool.</p></div>
        <div className="table-scroll"><table><thead><tr><th>Tool</th><th>Risk</th><th>Input schema</th><th>Human gate</th></tr></thead><tbody>{capabilities.map((capability) => <tr key={capability.name}><td>{capability.name}</td><td>{capability.risk_level}</td><td>{capability.input_fields.join(", ")}</td><td>{capability.requires_human_approval ? "Routes human action only" : "No"}</td></tr>)}</tbody></table></div>
      </section>
      <section className="panel audit-timeline">
        <div><span className="eyebrow">Immutable trace timeline</span><h2>Runs for this frozen snapshot</h2></div>
        {visibleRuns.length === 0 ? <p className="empty-state">No governed agent runs have been recorded for this snapshot.</p> : visibleRuns.map((run) => <Trace key={run.resource_id} run={run} />)}
      </section>
    </div>
  );
}
