import { headers } from "next/headers";

import { EvidenceReviewDetail } from "@/components/evidence-review-detail";
import { ApiProblem, createApiClient, requireSuccess } from "@/lib/api/client";
import { loadContext } from "@/lib/api/load-context";

export default async function EvidenceReviewPage({ params }: { readonly params: Promise<{ facilityId: string; snapshotId: string; candidateFactId: string }> }) {
  const { facilityId, snapshotId, candidateFactId } = await params;
  const context = await loadContext({ facilityId, snapshotId });
  if (context.kind !== "snapshot") return <EvidenceReviewDetail context={context} facilityId={facilityId} snapshotId={snapshotId} error="The immutable snapshot context is unavailable." />;
  try {
    const client = createApiClient((await headers()).get("authorization"));
    const packet = requireSuccess(await client.getCandidateFactReview(candidateFactId));
    try {
      const rendition = requireSuccess(await client.getEvidenceDocumentRendition(packet.document.document_version_id));
      return <EvidenceReviewDetail context={context} facilityId={facilityId} packet={packet} rendition={rendition} snapshotId={snapshotId} />;
    } catch (error) {
      const renditionError = error instanceof ApiProblem ? error.message : "The secure document rendition could not be loaded.";
      return <EvidenceReviewDetail context={context} facilityId={facilityId} packet={packet} renditionError={renditionError} snapshotId={snapshotId} />;
    }
  } catch (error) {
    const detail = error instanceof ApiProblem ? error.message : "The evidence review packet could not be loaded.";
    return <EvidenceReviewDetail context={context} facilityId={facilityId} snapshotId={snapshotId} error={detail} />;
  }
}
