import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CanonicalValueError,
  canonicalDecimal,
  canonicalJson,
  canonicalTimestamp,
  domainDigest,
  type SetRule,
} from "../src/canonical.ts";

type JsonVector = {
  id: string;
  value: unknown;
  set_rules: SetRule[];
  expected_utf8: string;
};

type DecimalVector = { id: string; value: string; scale: number; expected: string };
type TimestampVector = { id: string; value: string; expected: string };
type DigestVector = {
  id: string;
  artifact: string;
  version: number;
  payload_utf8: string;
  expected: string;
};
type RejectionVector = {
  id: string;
  operation: "json" | "decimal" | "timestamp";
  value: unknown;
  set_rules?: SetRule[];
  scale?: number;
  error: string;
};
type VectorCorpus = {
  json: JsonVector[];
  decimals: DecimalVector[];
  timestamps: TimestampVector[];
  digests: DigestVector[];
  rejections: RejectionVector[];
};

const corpus = JSON.parse(
  readFileSync(new URL("../../canonical-vectors/v1.json", import.meta.url), "utf8"),
) as VectorCorpus;

for (const vector of corpus.json) {
  test(`canonical JSON: ${vector.id}`, () => {
    assert.equal(canonicalJson(vector.value, vector.set_rules), vector.expected_utf8);
  });
}

for (const vector of corpus.decimals) {
  test(`canonical decimal: ${vector.id}`, () => {
    assert.equal(canonicalDecimal(vector.value, vector.scale), vector.expected);
  });
}

for (const vector of corpus.timestamps) {
  test(`canonical timestamp: ${vector.id}`, () => {
    assert.equal(canonicalTimestamp(vector.value), vector.expected);
  });
}

for (const vector of corpus.digests) {
  test(`domain digest: ${vector.id}`, () => {
    assert.equal(
      domainDigest(vector.artifact, vector.version, Buffer.from(vector.payload_utf8)),
      vector.expected,
    );
  });
}

for (const vector of corpus.rejections) {
  test(`canonical rejection: ${vector.id}`, () => {
    assert.throws(
      () => {
        if (vector.operation === "json") {
          canonicalJson(vector.value, vector.set_rules ?? []);
        } else if (vector.operation === "decimal") {
          canonicalDecimal(String(vector.value), vector.scale ?? -1);
        } else {
          canonicalTimestamp(String(vector.value));
        }
      },
      (error: unknown) =>
        error instanceof CanonicalValueError && error.message.includes(vector.error),
    );
  });
}
