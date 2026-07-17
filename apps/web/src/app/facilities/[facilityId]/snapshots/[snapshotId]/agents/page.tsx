import { headers } from "next/headers";

import { AppShell } from "@/components/app-shell";
import { GovernedAgents } from "@/components/governed-agents";
import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";
import { loadContext } from "@/lib/api/load-context";

export default async function GovernedAgentsPage({
  params,
}: {
  readonly params: Promise<{ facilityId: string; snapshotId: string }>;
}) {
  const { facilityId, snapshotId } = await params;
  const context = await loadContext({ facilityId, snapshotId });
  const returnPath = `/facilities/${encodeURIComponent(facilityId)}/snapshots/${encodeURIComponent(snapshotId)}/agents`;
  if (context.kind !== "snapshot") {
    return <AppShell activeWorkspace="agents" facilityId={facilityId} snapshotId={snapshotId} status="unavailable"><section className="unavailable-panel panel" role="alert"><span className="eyebrow">Authoritative state unavailable</span><h1>{context.kind === "unavailable" ? context.title : "Snapshot context is unavailable"}</h1><p>{context.kind === "unavailable" ? context.detail : "Select an immutable snapshot that you are authorized to view."}</p></section></AppShell>;
  }
  try {
    const client = createApiClient((await headers()).get("authorization"));
    const [runs, capabilities] = await Promise.all([
      client.listAgentRuns(facilityId, snapshotId),
      client.listAgentCapabilities(),
    ]);
    return <AppShell activeWorkspace="agents" facilityId={facilityId} snapshotId={snapshotId} status="frozen"><GovernedAgents capabilities={requireSuccess(capabilities).items} facilityId={facilityId} returnPath={returnPath} runs={requireSuccess(runs).items} snapshotId={snapshotId} /></AppShell>;
  } catch (error) {
    const detail = error instanceof ApiProblem ? error.message : "The agent trace service is unavailable.";
    return <AppShell activeWorkspace="agents" facilityId={facilityId} snapshotId={snapshotId} status="unavailable"><section className="unavailable-panel panel" role="alert"><span className="eyebrow">Trace unavailable</span><h1>Governed agent history is unavailable</h1><p>{detail}</p></section></AppShell>;
  }
}
