import assert from "node:assert/strict";
import test from "node:test";

import { finalDecisionPresentation } from "../src/lib/final-decision";

test("final decision presentation keeps approval and rejection outcomes distinct", () => {
  assert.deepEqual(finalDecisionPresentation(null), {
    badge: "Unavailable",
    heading: "Awaiting independent approval",
    detail: "Approval cannot be implied from capacity or evidence.",
    kind: "unavailable",
  });
  assert.deepEqual(finalDecisionPresentation({ status: "APPROVED" }), {
    badge: "Approved final decision",
    heading: "Approved final decision",
    detail: "An authorized independent approver recorded this final decision.",
    kind: "final",
  });
  assert.deepEqual(finalDecisionPresentation({ status: "REJECTED" }), {
    badge: "Rejected final decision",
    heading: "Rejected final decision",
    detail: "An authorized independent approver rejected this recommendation.",
    kind: "final",
  });
});
