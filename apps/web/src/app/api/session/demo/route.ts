import { NextResponse, type NextRequest } from "next/server";

import {
  isDemoAuthenticationEnabled,
  safeReturnPath,
  signedDemoSession,
  type DemoRole,
  demoSessionCookieName,
} from "@/lib/demo-session";

function requestOrigin(request: NextRequest): string | undefined {
  const origin = request.headers.get("origin");
  if (origin === null) return undefined;
  try {
    const parsedOrigin = new URL(origin);
    if (parsedOrigin.protocol !== "http:" && parsedOrigin.protocol !== "https:") return undefined;
    return parsedOrigin.host === request.headers.get("host") ? parsedOrigin.origin : undefined;
  } catch {
    return undefined;
  }
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  if (!isDemoAuthenticationEnabled()) return new NextResponse(null, { status: 404 });
  const origin = requestOrigin(request);
  if (origin === undefined) return new NextResponse(null, { status: 403 });

  const formData = await request.formData();
  const role = formData.get("role");
  if (role !== "analyst" && role !== "approver") return new NextResponse(null, { status: 422 });

  const response = NextResponse.redirect(new URL(safeReturnPath(String(formData.get("returnTo") ?? "")), origin), 303);
  response.cookies.set(demoSessionCookieName, signedDemoSession(role satisfies DemoRole), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 8,
  });
  return response;
}
