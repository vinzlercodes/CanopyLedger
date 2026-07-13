import assert from "node:assert/strict";
import test from "node:test";

import { buildContextHref, buildWorkspaceHref, parseContext } from "../src/lib/context";

test("buildContextHref creates a frozen snapshot cockpit route", () => {
  assert.equal(
    buildContextHref({ facilityId: "fac_123", snapshotId: "snp_456" }),
    "/facilities/fac_123/snapshots/snp_456/cockpit",
  );
});

test("buildContextHref creates a working-facility route without a snapshot", () => {
  assert.equal(buildContextHref({ facilityId: "fac_123" }), "/facilities/fac_123/cockpit");
});

test("parseContext rejects a snapshot without a facility boundary", () => {
  assert.deepEqual(parseContext({ snapshot: "snp_456" }), {
    facilityId: undefined,
    snapshotId: undefined,
    issue: "A facility must be selected before an immutable snapshot can be opened.",
  });
});

test("buildWorkspaceHref keeps every governed workspace inside frozen context", () => {
  assert.equal(
    buildWorkspaceHref({ facilityId: "fac_123", snapshotId: "snp_456" }, "risk/hedge"),
    "/facilities/fac_123/snapshots/snp_456/risk/hedge",
  );
});
