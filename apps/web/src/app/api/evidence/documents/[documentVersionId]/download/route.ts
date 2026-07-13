import { headers } from "next/headers";

const bearerToken = /^Bearer\s+[^\s]+$/i;

export async function GET(
  _request: Request,
  { params }: { readonly params: Promise<{ documentVersionId: string }> },
): Promise<Response> {
  const authorization = (await headers()).get("authorization");
  if (authorization === null || !bearerToken.test(authorization)) {
    return new Response(null, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const { documentVersionId } = await params;
  const upstream = await fetch(
    `${process.env.CANOPYLEDGER_API_BASE_URL ?? "http://127.0.0.1:8000"}/api/v1/evidence/documents/${encodeURIComponent(documentVersionId)}/download`,
    { headers: { Authorization: authorization }, cache: "no-store" },
  );
  if (!upstream.ok) {
    return new Response(null, { status: upstream.status, headers: { "Cache-Control": "no-store" } });
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Disposition": upstream.headers.get("content-disposition") ?? "attachment",
      "Content-Security-Policy": "sandbox",
      "Content-Type": "application/octet-stream",
      "X-Content-Type-Options": "nosniff",
    },
  });
}
