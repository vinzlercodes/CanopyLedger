import assert from "node:assert/strict";
import test from "node:test";

import { formatMoney } from "../src/lib/money";

test("formatMoney preserves authoritative decimal strings without Number coercion", () => {
  assert.equal(formatMoney({ amount: "100000.50", currency: "USD" }), "USD 100,000.50");
  assert.equal(
    formatMoney({ amount: "9007199254740993.000001", currency: "USD" }),
    "USD 9,007,199,254,740,993.000001",
  );
  assert.equal(formatMoney({ amount: "-42.10", currency: "USD" }), "USD -42.10");
});
