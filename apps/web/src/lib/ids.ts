import { randomUUID } from "node:crypto";

export function makeCommandResourceId(prefix: string): string {
  return `${prefix}_${randomUUID()}`;
}
