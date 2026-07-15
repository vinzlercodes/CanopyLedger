import { AnalyticsCopilot } from "@/components/analytics-copilot";
import { AppShell } from "@/components/app-shell";
import { loadContext } from "@/lib/api/load-context";

export default async function AnalyticsPage({
  params,
}: {
  readonly params: Promise<{ facilityId: string; snapshotId: string }>;
}) {
  const { facilityId, snapshotId } = await params;
  const context = await loadContext({ facilityId, snapshotId });
  const status = context.kind === "snapshot" ? "frozen" : "unavailable";
  const returnPath = `/facilities/${encodeURIComponent(facilityId)}/snapshots/${encodeURIComponent(snapshotId)}/analytics`;

  return (
    <AppShell activeWorkspace="analytics" facilityId={facilityId} snapshotId={snapshotId} status={status}>
      {context.kind === "snapshot" ? (
        <AnalyticsCopilot facilityId={facilityId} returnPath={returnPath} snapshotId={snapshotId} />
      ) : (
        <section className="unavailable-panel panel" role="alert">
          <span className="eyebrow">Authoritative state unavailable</span>
          <h1>{context.kind === "unavailable" ? context.title : "Snapshot context is unavailable"}</h1>
          <p>{context.kind === "unavailable" ? context.detail : "Select an immutable snapshot that you are authorized to view."}</p>
        </section>
      )}
    </AppShell>
  );
}
