import { cookies } from "next/headers";
import Link from "next/link";

import { demoRoleFromSession, demoSessionCookieName, isDemoAuthenticationEnabled, type DemoRole } from "@/lib/demo-session";

export async function AuthControls() {
  const enabled = isDemoAuthenticationEnabled();
  const role: DemoRole | undefined = enabled
    ? demoRoleFromSession((await cookies()).get(demoSessionCookieName)?.value)
    : undefined;

  if (!enabled) {
    return <div className="actor"><span className="actor-avatar" aria-hidden="true">CL</span><span><strong>Governed session</strong><Link href="/sign-in">Sign in</Link></span></div>;
  }

  if (role === undefined) {
    return <div className="actor"><span className="actor-avatar" aria-hidden="true">?</span><span><strong>Session required</strong><Link href="/sign-in">Sign in locally</Link></span></div>;
  }

  return (
    <div className="actor">
      <span className="actor-avatar" aria-hidden="true">{role === "analyst" ? "AN" : "AP"}</span>
      <span><strong>Demo {role}</strong><small>Identity forwarded server-side</small></span>
      <form action="/api/session/logout" method="post"><input name="returnTo" type="hidden" value="/" /><button className="text-action" type="submit">Sign out</button></form>
    </div>
  );
}
