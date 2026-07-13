import { AppShell } from "@/components/app-shell";
import { FoundationContent } from "@/components/foundation-content";
import { loadContext } from "@/lib/api/load-context";

export async function WorkspacePage({
  facilityId,
  snapshotId,
}: {
  readonly facilityId?: string;
  readonly snapshotId?: string;
}) {
  const context = await loadContext({ facilityId, snapshotId });
  const status = context.kind === "snapshot" ? "frozen" : context.kind === "working" ? "working" : "unavailable";
  return (
    <AppShell facilityId={facilityId} snapshotId={snapshotId} status={status}>
      <FoundationContent context={context} />
    </AppShell>
  );
}
