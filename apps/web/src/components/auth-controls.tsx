import { cookies } from "next/headers";
import Link from "next/link";

import { demoRoleFromSession, demoSessionCookieName, isDemoAuthenticationEnabled, safeReturnPath, type DemoRole } from "@/lib/demo-session";

export async function AuthControls({ returnTo = "/" }: { readonly returnTo?: string }) {
  const safeReturnTo = safeReturnPath(returnTo);
  const signInHref = `/sign-in?returnTo=${encodeURIComponent(safeReturnTo)}`;
  const enabled = isDemoAuthenticationEnabled();
  const role: DemoRole | undefined = enabled
    ? demoRoleFromSession((await cookies()).get(demoSessionCookieName)?.value)
    : undefined;

  if (!enabled) {
    return <div className="actor"><span className="actor-avatar" aria-hidden="true">CL</span><span><strong>Governed session</strong><Link href={signInHref}>Sign in</Link></span></div>;
  }

  if (role === undefined) {
    return <div className="actor"><span className="actor-avatar" aria-hidden="true">?</span><span><strong>Session required</strong><Link href={signInHref}>Sign in locally</Link></span></div>;
  }

  return (
    <div className="actor">
      <span className="actor-avatar" aria-hidden="true">{role === "analyst" ? "AN" : "AP"}</span>
      <span><strong>Demo {role}</strong><small>Identity forwarded server-side</small></span>
      <form action="/api/session/logout" method="post"><input name="returnTo" type="hidden" value={safeReturnTo} /><button className="text-action" type="submit">Sign out</button></form>
    </div>
  );
}
