import { createHmac, timingSafeEqual } from "node:crypto";

export const demoSessionCookieName = "canopyledger_demo_session";

export type DemoRole = "analyst" | "approver";

const bearerByRole: Readonly<Record<DemoRole, string>> = {
  analyst: "Bearer analyst-demo-token",
  approver: "Bearer approver-demo-token",
};

function sessionSecret(value = process.env.CANOPYLEDGER_DEMO_SESSION_SECRET): string {
  return value || "canopyledger-local-demo-session-v1";
}

function signature(role: DemoRole, secret: string): string {
  return createHmac("sha256", secret).update(`canopyledger-demo-session:${role}`).digest("base64url");
}

export function isDemoAuthenticationEnabled(value = process.env.CANOPYLEDGER_DEMO_AUTH_ENABLED): boolean {
  return value === "true";
}

export function signedDemoSession(role: DemoRole, secret = sessionSecret()): string {
  return `${role}.${signature(role, secret)}`;
}

export function demoRoleFromSession(value: string | undefined, secret = sessionSecret()): DemoRole | undefined {
  const [role, receivedSignature, ...rest] = value?.split(".") ?? [];
  if (rest.length !== 0 || (role !== "analyst" && role !== "approver") || receivedSignature === undefined) return undefined;
  const expectedSignature = signature(role, secret);
  const received = Buffer.from(receivedSignature);
  const expected = Buffer.from(expectedSignature);
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) return undefined;
  return role;
}

export function demoAuthorizationForSession(
  value: string | undefined,
  enabled = isDemoAuthenticationEnabled(),
  secret = sessionSecret(),
): string | null {
  if (!enabled) return null;
  const role = demoRoleFromSession(value, secret);
  return role === undefined ? null : bearerByRole[role];
}

export function safeReturnPath(value: string | undefined): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/";
}
