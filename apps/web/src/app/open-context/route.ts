import { NextResponse, type NextRequest } from "next/server";

import { buildContextHref, parseContext } from "@/lib/context";

export function GET(request: NextRequest): NextResponse {
  const context = parseContext({
    facility: request.nextUrl.searchParams.get("facility") ?? undefined,
    snapshot: request.nextUrl.searchParams.get("snapshot") ?? undefined,
  });
  return new NextResponse(null, {
    status: 307,
    headers: { location: buildContextHref(context) },
  });
}
