import type { WorkspaceSlug } from "@/lib/context";

export const MOBILE_NAVIGATION_ID = "workspace-navigation";

export const workspaceNavigation: readonly {
  readonly workspace: WorkspaceSlug;
  readonly icon: "activity" | "book" | "document" | "home" | "shield" | "spark";
  readonly label: string;
}[] = [
  { workspace: "cockpit", icon: "home", label: "Cockpit" },
  { workspace: "collateral", icon: "book", label: "Collateral" },
  { workspace: "evidence", icon: "document", label: "Evidence" },
  { workspace: "risk/hedge", icon: "activity", label: "Hedge Lab" },
  { workspace: "risk/scenarios", icon: "activity", label: "Scenario Lab" },
  { workspace: "climate", icon: "spark", label: "Climate & Traceability" },
  { workspace: "credit", icon: "activity", label: "Credit Monitoring" },
  { workspace: "analytics", icon: "spark", label: "Analytics Copilot" },
  { workspace: "agents", icon: "shield", label: "Governed Agents" },
  { workspace: "approvals", icon: "shield", label: "Approval" },
];
