import assert from "node:assert/strict";
import test from "node:test";

import { MOBILE_NAVIGATION_ID, workspaceNavigation } from "../src/lib/navigation";

test("workspace navigation has a stable mobile-dialog target and covers every governed workspace", () => {
  assert.equal(MOBILE_NAVIGATION_ID, "workspace-navigation");
  assert.deepEqual(
    workspaceNavigation.map((item) => item.workspace),
    ["cockpit", "collateral", "evidence", "risk/hedge", "risk/scenarios", "climate", "credit", "analytics", "agents", "approvals"],
  );
});
