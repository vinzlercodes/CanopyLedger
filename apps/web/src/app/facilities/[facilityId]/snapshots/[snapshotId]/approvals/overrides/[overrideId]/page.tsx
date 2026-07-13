import { headers } from "next/headers";

import { OverrideReviewDetail } from "@/components/override-review-detail";
import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";
import { loadContext } from "@/lib/api/load-context";

export default async function OverrideReviewPage({ params }: { readonly params: Promise<{ facilityId: string; snapshotId: string; overrideId: string }> }) {
  const { facilityId, snapshotId, overrideId } = await params;
  const context = await loadContext({ facilityId, snapshotId });
  if (context.kind !== "snapshot") return <OverrideReviewDetail context={context} facilityId={facilityId} snapshotId={snapshotId} error="The immutable snapshot context is unavailable." />;
  try {
    const client = createApiClient((await headers()).get("authorization"));
    const override = requireSuccess(await client.getDecisionOverride(overrideId));
    return <OverrideReviewDetail context={context} facilityId={facilityId} override={override} snapshotId={snapshotId} />;
  } catch (error) {
    const detail = error instanceof ApiProblem ? error.message : "The override detail could not be loaded.";
    return <OverrideReviewDetail context={context} facilityId={facilityId} snapshotId={snapshotId} error={detail} />;
  }
}
