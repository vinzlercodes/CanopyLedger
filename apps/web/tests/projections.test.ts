import assert from "node:assert/strict";
import test from "node:test";

import { projectionTables } from "../src/lib/projections";

test("projectionTables presents server-issued record arrays without changing values", () => {
  const tables = projectionTables({ collateral_valuation: { result: { inventory: [{ lot_id: "lot-1", eligible_value: "1200.00" }] } } });

  assert.deepEqual(tables, [{ title: "collateral valuation / result / inventory", columns: ["eligible_value", "lot_id"], rows: [["1200.00", "lot-1"]] }]);
});
