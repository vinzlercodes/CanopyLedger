import Link from "next/link";
import type { ReactNode } from "react";

import { AuthorityBadge } from "@/components/authority-badge";
import { ContextPicker } from "@/components/context-picker";
import { Icon } from "@/components/icon";
import { MobileNavigation } from "@/components/mobile-navigation";
import { buildWorkspaceHref, type WorkspaceSlug } from "@/lib/context";
import { workspaceNavigation } from "@/lib/navigation";

type AppShellProps = {
  readonly children: ReactNode;
  readonly facilityId?: string;
  readonly snapshotId?: string;
  readonly status: "working" | "frozen" | "unavailable";
  readonly activeWorkspace?: WorkspaceSlug;
};

export function AppShell({ children, facilityId, snapshotId, status, activeWorkspace = "cockpit" }: AppShellProps) {
  const context = { facilityId, snapshotId };
  return (
    <div className="application-frame">
      <a className="skip-link" href="#main-content">Skip to workspace</a>
      <aside aria-label="Primary navigation" className="sidebar">
        <Link className="brand" href="/">
          <span aria-hidden="true" className="brand-mark">C</span>
          <span>
            <strong>CanopyLedger</strong>
            <small>Coffee trade-finance governance</small>
          </span>
        </Link>
        <nav className="main-nav">
          {workspaceNavigation.map((item) => (
            <Link aria-current={activeWorkspace === item.workspace ? "page" : undefined} className={activeWorkspace === item.workspace ? "nav-link nav-link--current" : "nav-link"} href={buildWorkspaceHref(context, item.workspace)} key={item.label}>
              <Icon name={item.icon} />
              {item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-footer">
          <Icon name="lock" />
          <span>FastAPI authorizes every request. The web app only presents governed state.</span>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <MobileNavigation activeWorkspace={activeWorkspace} context={context} />
          <ContextPicker facilityId={facilityId} snapshotId={snapshotId} />
          <div className="context-status">
            <span>Authority</span>
            <AuthorityBadge kind={status} />
          </div>
          <div className="actor">
            <span className="actor-avatar" aria-hidden="true">CL</span>
            <span>
              <strong>Governed session</strong>
              <small>Identity forwarded server-side</small>
            </span>
          </div>
        </header>
        <main className="main-content" id="main-content">{children}</main>
        <footer className="app-footer">CanopyLedger v1 · all timestamps remain source-bound</footer>
      </div>
    </div>
  );
}
