import { cookies } from "next/headers";
import Link from "next/link";

import {
  demoRoleFromSession,
  demoSessionCookieName,
  isDemoAuthenticationEnabled,
  safeReturnPath,
} from "@/lib/demo-session";

export default async function SignInPage({ searchParams }: { readonly searchParams: Promise<{ readonly returnTo?: string }> }) {
  const { returnTo } = await searchParams;
  const safeReturnTo = safeReturnPath(returnTo);
  const enabled = isDemoAuthenticationEnabled();
  const role = demoRoleFromSession((await cookies()).get(demoSessionCookieName)?.value);

  return (
    <main className="sign-in-page">
      <section className="sign-in-panel panel">
        <span className="eyebrow">Local reference session</span>
        <h1>Sign in to CanopyLedger</h1>
        {enabled ? (
          <>
            <p>Choose a synthetic role for this local demonstration. The browser stores only a signed, HttpOnly role session; CanopyLedger adds the corresponding bearer header server-side.</p>
            {role && <p className="session-notice">Current local session: <strong>{role}</strong>.</p>}
            <form action="/api/session/demo" className="sign-in-actions" method="post">
              <input name="returnTo" type="hidden" value={safeReturnTo} />
              <button className="role-option" name="role" type="submit" value="analyst"><strong>Analyst access</strong><span>Inspect governed workspaces; review evidence and recommendations. Cannot record a final approval or approve own work.</span><em>Continue as analyst</em></button>
              <button className="role-option role-option--approver" name="role" type="submit" value="approver"><strong>Approver access</strong><span>Inspect governed workspaces and act on eligible approval requests. Separation, expiry, and no-self-approval checks remain enforced by FastAPI.</span><em>Continue as approver</em></button>
            </form>
            <p className="muted">This synthetic sign-in proves identity forwarding only. It does not seed facility, snapshot, or published workspace data; FastAPI must contain an authorized, published context before a frozen workspace can render.</p>
            <p className="muted">Available only when <code>CANOPYLEDGER_DEMO_AUTH_ENABLED=true</code>. It is not a production identity provider.</p>
          </>
        ) : (
          <>
            <p>Local demo sign-in is disabled. Start the web app with <code>CANOPYLEDGER_DEMO_AUTH_ENABLED=true</code> to use the synthetic analyst and approver identities.</p>
            <p className="muted">Production deployments must integrate an organization-approved identity provider and continue forwarding its server-validated identity to FastAPI.</p>
          </>
        )}
        <Link className="secondary-action" href={safeReturnTo}>Return to workspace</Link>
      </section>
    </main>
  );
}
