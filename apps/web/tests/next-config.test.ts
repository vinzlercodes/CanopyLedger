import assert from "node:assert/strict";
import test from "node:test";

import nextConfig from "../next.config";

test("Next development permits only the canonical loopback browser origin", () => {
  assert.deepEqual(nextConfig.allowedDevOrigins, ["127.0.0.1"]);
});
