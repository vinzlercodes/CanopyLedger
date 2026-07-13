import { GovernedWorkspace } from "@/components/governed-workspace";
import { loadWorkspace } from "@/lib/api/load-workspace";

const collateralSections = new Set(["inventory", "receivables", "contributions", "reserves"]);

export default async function CollateralPage({
  params,
  searchParams,
}: {
  readonly params: Promise<{ facilityId: string; snapshotId: string }>;
  readonly searchParams: Promise<{ section?: string; cursor?: string }>;
}) {
  const { facilityId, snapshotId } = await params;
  const query = await searchParams;
  const section = collateralSections.has(query.section ?? "") ? query.section as "inventory" | "receivables" | "contributions" | "reserves" : undefined;
  return <GovernedWorkspace facilityId={facilityId} loaded={await loadWorkspace({ facilityId, snapshotId, workspace: "collateral", collateral: { section, cursor: query.cursor } })} snapshotId={snapshotId} workspace="collateral" />;
}
