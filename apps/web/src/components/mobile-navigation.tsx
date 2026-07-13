import Link from "next/link";

import { Icon } from "@/components/icon";
import { buildWorkspaceHref, type FacilitySnapshotContext, type WorkspaceSlug } from "@/lib/context";
import { MOBILE_NAVIGATION_ID, workspaceNavigation } from "@/lib/navigation";

export function MobileNavigation({
  activeWorkspace,
  context,
}: {
  readonly activeWorkspace: WorkspaceSlug;
  readonly context: FacilitySnapshotContext;
}) {
  return (
    <details className="mobile-navigation">
      <summary
        aria-controls={MOBILE_NAVIGATION_ID}
        aria-label="Toggle workspace navigation"
        className="menu-button"
      >
        <Icon name="menu" />
        <span className="mobile-navigation__close-label">Close</span>
      </summary>
      <div aria-label="Workspace navigation" className="mobile-navigation__sheet" id={MOBILE_NAVIGATION_ID} role="region">
        <div className="mobile-navigation__header"><span className="eyebrow">Governed workspaces</span></div>
        <nav aria-label="Workspace navigation" className="mobile-navigation__links">
          {workspaceNavigation.map((item) => (
            <Link
              aria-current={activeWorkspace === item.workspace ? "page" : undefined}
              className={activeWorkspace === item.workspace ? "mobile-navigation__link mobile-navigation__link--current" : "mobile-navigation__link"}
              href={buildWorkspaceHref(context, item.workspace)}
              key={item.workspace}
            >
              <Icon name={item.icon} />
              {item.label}
            </Link>
          ))}
        </nav>
        <p className="mobile-navigation__note"><Icon name="lock" /> FastAPI authorizes every workspace request.</p>
      </div>
    </details>
  );
}
