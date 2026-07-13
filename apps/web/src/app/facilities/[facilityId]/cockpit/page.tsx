import { WorkspacePage } from "@/components/workspace-page";

export default async function FacilityCockpitPage({ params }: { readonly params: Promise<{ facilityId: string }> }) {
  const { facilityId } = await params;
  return <WorkspacePage facilityId={facilityId} />;
}
