import assert from "node:assert/strict";
import test from "node:test";
import { renderToReadableStream } from "react-dom/server";
import { createElement } from "react";

import { ReportViewer } from "../src/components/report-viewer";
import type { LoadedReports } from "../src/lib/api/load-reports";

test("report viewer labels historical packages and links only to its same-origin artifact proxy", async () => {
  const loaded = {
    context: { kind: "snapshot" },
    decisionPack: { final_decision: { status: "APPROVED" } },
    reports: [
      {
        package_kind: "HISTORICAL_AUDIT",
        report_model: {
          resource_id: "rpt_0198a000-0000-7000-8000-000000000001",
          digest: "sha256:report",
          decision_id: "fdc_0198a000-0000-7000-8000-000000000001",
          snapshot_id: "snp_0198a000-0000-7000-8000-000000000001",
          artifact_manifest: { template_version: "committee-pack-v1" },
          sections: { capacity_and_decision: {} },
        },
        artifacts: [
          {
            format: "PDF",
            digest: "sha256:pdf",
            report_model_digest: "sha256:report",
            metadata: { renderer: "canopyledger-html-v1", font_digest: "sha256:font" },
          },
        ],
      },
    ],
  } as unknown as LoadedReports;

  const stream = await renderToReadableStream(
    createElement(ReportViewer, {
      facilityId: "fac_0198a000-0000-7000-8000-000000000001",
      snapshotId: "snp_0198a000-0000-7000-8000-000000000001",
      loaded,
    }),
  );
  const html = await new Response(stream).text();

  assert.match(html, /Historical audit — not an official current decision/);
  assert.match(
    html,
    /href="\/api\/reports\/rpt_0198a000-0000-7000-8000-000000000001\/artifacts\/PDF"/,
  );
  assert.doesNotMatch(html, /href="http/);
});
