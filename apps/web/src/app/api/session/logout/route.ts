import { NextResponse, type NextRequest } from "next/server";

import { demoSessionCookieName, safeReturnPath } from "@/lib/demo-session";

export async function POST(request: NextRequest): Promise<NextResponse> {
  const origin = request.headers.get("origin");
  let requestOrigin: string;
  try {
    if (origin === null) return new NextResponse(null, { status: 403 });
    const parsedOrigin = new URL(origin);
    if ((parsedOrigin.protocol !== "http:" && parsedOrigin.protocol !== "https:") || parsedOrigin.host !== request.headers.get("host")) return new NextResponse(null, { status: 403 });
    requestOrigin = parsedOrigin.origin;
  } catch {
    return new NextResponse(null, { status: 403 });
  }

  const formData = await request.formData();
  const response = NextResponse.redirect(new URL(safeReturnPath(String(formData.get("returnTo") ?? "")), requestOrigin), 303);
  response.cookies.set(demoSessionCookieName, "", { httpOnly: true, sameSite: "lax", path: "/", maxAge: 0 });
  return response;
}
