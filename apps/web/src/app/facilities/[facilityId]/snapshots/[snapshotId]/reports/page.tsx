import { ReportViewer } from "@/components/report-viewer";
import { loadReports } from "@/lib/api/load-reports";

export default async function ReportsPage({ params }: { readonly params: Promise<{ facilityId: string; snapshotId: string }> }) {
  const { facilityId, snapshotId } = await params;
  return <ReportViewer facilityId={facilityId} loaded={await loadReports({ facilityId, snapshotId })} snapshotId={snapshotId} />;
}
