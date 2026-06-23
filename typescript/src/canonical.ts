import { createHash } from "node:crypto";

export class CanonicalValueError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "CanonicalValueError";
  }
}

export type SetRule = {
  readonly path: readonly string[];
  readonly sort_keys: readonly string[];
};

type NormalizedValue = null | boolean | number | bigint | string | NormalizedValue[] | NormalizedMap;
type NormalizedMap = { readonly [key: string]: NormalizedValue };

export function canonicalDecimal(value: string, scale: number): string {
  if (!Number.isSafeInteger(scale) || scale < 0) {
    throw new CanonicalValueError("scale must be non-negative");
  }
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (match === null) {
    throw new CanonicalValueError("decimal must use fixed-point notation");
  }
  const sign = match[1] ?? "";
  const integerDigits = match[2] ?? "0";
  const fractionalDigits = match[3] ?? "";
  const isZero = [...integerDigits, ...fractionalDigits].every((digit) => digit === "0");
  if (sign === "-" && isZero) {
    throw new CanonicalValueError("negative zero is forbidden");
  }
  const discarded = fractionalDigits.slice(scale);
  if ([...discarded].some((digit) => digit !== "0")) {
    throw new CanonicalValueError("decimal exceeds declared scale");
  }
  const normalizedInteger = integerDigits.replace(/^0+(?=\d)/, "");
  if (scale === 0) {
    return `${sign}${normalizedInteger}`;
  }
  const normalizedFraction = fractionalDigits.slice(0, scale).padEnd(scale, "0");
  return `${sign}${normalizedInteger}.${normalizedFraction}`;
}

export function canonicalTimestamp(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(
    value,
  );
  if (match === null) {
    throw new CanonicalValueError("timestamp must be timezone-aware RFC 3339");
  }
  const [year, month, day, hour, minute, second] = match
    .slice(1, 7)
    .map((part) => Number(part));
  if (
    year === undefined ||
    month === undefined ||
    day === undefined ||
    hour === undefined ||
    minute === undefined ||
    second === undefined
  ) {
    throw new CanonicalValueError("timestamp components are incomplete");
  }
  const localMilliseconds = Date.UTC(year, month - 1, day, hour, minute, second);
  const local = new Date(localMilliseconds);
  if (
    local.getUTCFullYear() !== year ||
    local.getUTCMonth() !== month - 1 ||
    local.getUTCDate() !== day ||
    local.getUTCHours() !== hour ||
    local.getUTCMinutes() !== minute ||
    local.getUTCSeconds() !== second
  ) {
    throw new CanonicalValueError("timestamp contains an invalid calendar value");
  }
  const zone = match[8];
  if (zone === undefined) {
    throw new CanonicalValueError("timestamp must be timezone-aware RFC 3339");
  }
  let offsetMinutes = 0;
  if (zone !== "Z") {
    const offsetHours = Number(zone.slice(1, 3));
    const offsetMinutePart = Number(zone.slice(4, 6));
    if (offsetHours > 23 || offsetMinutePart > 59) {
      throw new CanonicalValueError("timestamp contains an invalid UTC offset");
    }
    offsetMinutes = (offsetHours * 60 + offsetMinutePart) * (zone[0] === "+" ? 1 : -1);
  }
  const utc = new Date(localMilliseconds - offsetMinutes * 60_000);
  const fractional = (match[7] ?? "").padEnd(6, "0");
  return `${utc.toISOString().slice(0, 19)}.${fractional}Z`;
}

export function canonicalJson(value: unknown, setRules: readonly SetRule[] = []): string {
  const rules = new Map<string, SetRule>();
  for (const rule of setRules) {
    const key = rulePath(rule.path);
    if (rules.has(key)) {
      throw new CanonicalValueError("duplicate canonical set rule path");
    }
    rules.set(key, rule);
  }
  return render(normalize(value, [], rules));
}

export function domainDigest(
  artifact: string,
  version: number,
  payload: Uint8Array,
): string {
  if (!/^[a-z_]+$/.test(artifact)) {
    throw new CanonicalValueError("artifact must use lowercase ASCII letters and underscores");
  }
  if (!Number.isSafeInteger(version) || version < 1) {
    throw new CanonicalValueError("version must be positive");
  }
  const prefix = Buffer.from(`canopyledger:${artifact}:v${version}\0`, "utf8");
  const digest = createHash("sha256").update(prefix).update(payload).digest("hex");
  return `sha256:${digest}`;
}

function normalize(
  value: unknown,
  path: readonly string[],
  rules: ReadonlyMap<string, SetRule>,
): NormalizedValue {
  if (value === null || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isInteger(value)) {
      throw new CanonicalValueError("binary floating-point values are forbidden");
    }
    if (!Number.isSafeInteger(value)) {
      throw new CanonicalValueError("integer exceeds interoperable JSON range");
    }
    return value;
  }
  if (typeof value === "bigint") {
    const limit = 9_007_199_254_740_991n;
    if (value > limit || value < -limit) {
      throw new CanonicalValueError("integer exceeds interoperable JSON range");
    }
    return value;
  }
  if (typeof value === "string") {
    return value.normalize("NFC");
  }
  if (Array.isArray(value)) {
    const normalized = value.map((item) => normalize(item, path, rules));
    const rule = rules.get(rulePath(path));
    if (rule !== undefined) {
      for (const member of normalized) {
        compareSetMembers(member, member, rule);
      }
      normalized.sort((left, right) => compareSetMembers(left, right, rule));
    }
    return normalized;
  }
  if (typeof value === "object") {
    const source = value as Record<string, unknown>;
    const entries = Object.entries(source).map(([key, item]) => {
      const normalizedKey = key.normalize("NFC");
      return [normalizedKey, normalize(item, [...path, normalizedKey], rules)] as const;
    });
    entries.sort(([left], [right]) => utf16Compare(left, right));
    return Object.fromEntries(entries);
  }
  throw new CanonicalValueError(`unsupported canonical value type: ${typeof value}`);
}

function render(value: NormalizedValue): string {
  if (value === null) {
    return "null";
  }
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "bigint") {
    return String(value);
  }
  if (typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(render).join(",")}]`;
  }
  return `{${Object.entries(value)
    .sort(([left], [right]) => utf16Compare(left, right))
    .map(([key, item]) => `${JSON.stringify(key)}:${render(item)}`)
    .join(",")}}`;
}

function compareSetMembers(left: NormalizedValue, right: NormalizedValue, rule: SetRule): number {
  if (!isNormalizedMap(left) || !isNormalizedMap(right)) {
    throw new CanonicalValueError("declared set members must be objects");
  }
  for (const key of rule.sort_keys) {
    if (!(key in left) || !(key in right)) {
      throw new CanonicalValueError(`declared set sort key is missing: ${key}`);
    }
    const comparison = Buffer.compare(Buffer.from(render(left[key]!)), Buffer.from(render(right[key]!)));
    if (comparison !== 0) {
      return comparison;
    }
  }
  return 0;
}

function isNormalizedMap(value: NormalizedValue): value is NormalizedMap {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function rulePath(path: readonly string[]): string {
  return JSON.stringify(path);
}

function utf16Compare(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}
