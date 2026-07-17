import { headers } from "next/headers";

import { forwardedAuthorization } from "@/lib/api/client";

const artifactFormats = new Set(["HTML", "PDF"]);
const reportIds = /^rpt_[0-9a-f-]+$/;

/**
 * Same-origin artifact proxy so browser links retain the server-side bearer boundary.
 * The API remains the sole source of immutable report bytes and access control.
 */
export async function GET(
  _request: Request,
  { params }: { readonly params: Promise<{ readonly reportId: string; readonly artifactFormat: string }> },
): Promise<Response> {
  const { reportId, artifactFormat } = await params;
  if (!reportIds.test(reportId) || !artifactFormats.has(artifactFormat)) {
    return new Response("Not found", { status: 404 });
  }

  const response = await fetch(
    `${process.env.CANOPYLEDGER_API_BASE_URL ?? "http://127.0.0.1:8000"}/api/v1/reports/${reportId}/artifacts/${artifactFormat}`,
    {
      headers: forwardedAuthorization((await headers()).get("authorization")),
      cache: "no-store",
    },
  );
  const responseHeaders = new Headers();
  for (const header of ["content-type", "etag"]) {
    const value = response.headers.get(header);
    if (value !== null) responseHeaders.set(header, value);
  }
  return new Response(response.body, { status: response.status, headers: responseHeaders });
}
