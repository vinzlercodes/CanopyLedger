import assert from "node:assert/strict";
import test from "node:test";

import { forwardedAuthorization } from "../src/lib/api/client";

test("forwards only a bearer authorization header", () => {
  assert.deepEqual(forwardedAuthorization("Bearer permitted-token"), { Authorization: "Bearer permitted-token" });
  assert.deepEqual(forwardedAuthorization("Basic credentials"), {});
  assert.deepEqual(forwardedAuthorization(null), {});
});
