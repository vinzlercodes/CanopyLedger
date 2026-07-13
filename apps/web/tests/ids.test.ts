import assert from "node:assert/strict";
import test from "node:test";

import { makeCommandResourceId } from "../src/lib/ids";

test("makeCommandResourceId preserves the governed resource prefix", () => {
  assert.match(makeCommandResourceId("apa"), /^apa_[0-9a-f-]{36}$/);
  assert.match(makeCommandResourceId("fdc"), /^fdc_[0-9a-f-]{36}$/);
});
