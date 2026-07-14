import type { GovernanceResourceResponse } from "../../../../typescript/generated/index";

type FinalDecision = Pick<GovernanceResourceResponse, "status"> | null | undefined;

export type FinalDecisionPresentation = {
  readonly badge: string;
  readonly detail: string;
  readonly heading: string;
  readonly kind: "final" | "unavailable";
};

export function finalDecisionPresentation(decision: FinalDecision): FinalDecisionPresentation {
  if (decision === null || decision === undefined) {
    return {
      badge: "Unavailable",
      detail: "Approval cannot be implied from capacity or evidence.",
      heading: "Awaiting independent approval",
      kind: "unavailable",
    };
  }
  if (decision.status === "APPROVED") {
    return {
      badge: "Approved final decision",
      detail: "An authorized independent approver recorded this final decision.",
      heading: "Approved final decision",
      kind: "final",
    };
  }
  if (decision.status === "REJECTED") {
    return {
      badge: "Rejected final decision",
      detail: "An authorized independent approver rejected this recommendation.",
      heading: "Rejected final decision",
      kind: "final",
    };
  }
  return {
    badge: `Final decision: ${decision.status}`,
    detail: "The API recorded a final-decision state that remains separate from the recommendation.",
    heading: "Recorded final decision",
    kind: "final",
  };
}
