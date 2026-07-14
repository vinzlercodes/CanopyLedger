import { NextResponse, type NextRequest } from "next/server";

import { demoAuthorizationForSession, demoSessionCookieName } from "@/lib/demo-session";

export function proxy(request: NextRequest): NextResponse {
  const headers = new Headers(request.headers);
  if (request.headers.has("authorization")) return NextResponse.next({ request: { headers } });

  const session = request.cookies.get(demoSessionCookieName)?.value;
  const authorization = demoAuthorizationForSession(session);
  if (authorization === null) return NextResponse.next({ request: { headers } });

  headers.set("authorization", authorization);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
