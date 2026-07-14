import assert from "node:assert/strict";
import test from "node:test";

import {
  demoAuthorizationForSession,
  demoRoleFromSession,
  isDemoAuthenticationEnabled,
  safeReturnPath,
  signedDemoSession,
} from "../src/lib/demo-session";

test("only an explicitly enabled and signed demo session yields a server-side bearer header", () => {
  const session = signedDemoSession("analyst", "test-secret");

  assert.equal(demoAuthorizationForSession(session, true, "test-secret"), "Bearer analyst-demo-token");
  assert.equal(demoAuthorizationForSession(session, false, "test-secret"), null);
  assert.equal(demoAuthorizationForSession("approver.invalid", true, "test-secret"), null);
});

test("recognizes the signed local role without exposing a bearer token", () => {
  const session = signedDemoSession("approver", "test-secret");

  assert.equal(demoRoleFromSession(session, "test-secret"), "approver");
  assert.equal(demoRoleFromSession(undefined, "test-secret"), undefined);
  assert.ok(!session.includes("demo-token"));
});

test("requires the exact local-demo authentication flag", () => {
  assert.equal(isDemoAuthenticationEnabled("true"), true);
  assert.equal(isDemoAuthenticationEnabled("TRUE"), false);
  assert.equal(isDemoAuthenticationEnabled(undefined), false);
});

test("only accepts an application-local post-sign-in return path", () => {
  assert.equal(safeReturnPath("/facilities/fac_1/snapshots/snp_1/cockpit"), "/facilities/fac_1/snapshots/snp_1/cockpit");
  assert.equal(safeReturnPath("https://example.com"), "/");
  assert.equal(safeReturnPath("//example.com"), "/");
  assert.equal(safeReturnPath(undefined), "/");
});
