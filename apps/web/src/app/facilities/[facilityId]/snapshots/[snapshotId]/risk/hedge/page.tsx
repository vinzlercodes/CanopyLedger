import { GovernedWorkspace } from "@/components/governed-workspace";
import { loadWorkspace } from "@/lib/api/load-workspace";

export default async function HedgeLabPage({ params }: { readonly params: Promise<{ facilityId: string; snapshotId: string }> }) {
  const { facilityId, snapshotId } = await params;
  return <GovernedWorkspace facilityId={facilityId} loaded={await loadWorkspace({ facilityId, snapshotId, workspace: "risk/hedge" })} snapshotId={snapshotId} workspace="risk/hedge" />;
}
