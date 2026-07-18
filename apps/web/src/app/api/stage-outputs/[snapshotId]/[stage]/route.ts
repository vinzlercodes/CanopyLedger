import { headers } from "next/headers";

import { forwardedAuthorization } from "@/lib/api/client";

const snapshotIdPattern = /^snp_[0-9a-f-]+$/;
const upstreamPathByStage = {
  "hedge-liquidity": "hedge-liquidity",
  scenarios: "scenarios",
} as const;

/**
 * Same-origin read-only proxy for immutable canonical stage envelopes.
 * It retains server-side bearer forwarding and never lets browser code derive values.
 */
export async function GET(
  request: Request,
  { params }: { readonly params: Promise<{ readonly snapshotId: string; readonly stage: string }> },
): Promise<Response> {
  const { snapshotId, stage } = await params;
  if (!snapshotIdPattern.test(snapshotId) || !(stage in upstreamPathByStage)) {
    return new Response("Not found", { status: 404, headers: { "Cache-Control": "no-store" } });
  }

  const upstream = await fetch(
    `${process.env.CANOPYLEDGER_API_BASE_URL ?? "http://127.0.0.1:8000"}/api/v1/snapshots/${encodeURIComponent(snapshotId)}/${upstreamPathByStage[stage as keyof typeof upstreamPathByStage]}`,
    {
      headers: forwardedAuthorization((await headers()).get("authorization")),
      cache: "no-store",
    },
  );
  if (!upstream.ok) return new Response(null, { status: upstream.status, headers: { "Cache-Control": "no-store" } });

  const download = new URL(request.url).searchParams.get("download") === "1";
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Disposition": download
        ? `attachment; filename="${snapshotId}-${stage}.json"`
        : "inline",
      "Content-Security-Policy": "sandbox",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
