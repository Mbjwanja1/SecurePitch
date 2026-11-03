// RFC 8785 canonical JSON (docs/CRYPTO_SPEC.md section 2), with the SecurePitch rule that
// floats and unsafe integers are rejected rather than encoded.
import serialize from "canonicalize";

import type { Bytes } from "./encoding";

export class CanonicalizationError extends Error {}

function check(value: unknown, path: string): void {
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isInteger(value)) {
      throw new CanonicalizationError(`${path}: floats are not allowed; use cents or basis points`);
    }
    if (!Number.isSafeInteger(value)) {
      throw new CanonicalizationError(`${path}: integer outside JavaScript's safe range`);
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, i) => check(item, `${path}[${i}]`));
    return;
  }
  if (typeof value === "object") {
    for (const [key, item] of Object.entries(value)) check(item, `${path}.${key}`);
    return;
  }
  throw new CanonicalizationError(`${path}: unsupported type ${typeof value}`);
}

export function canonicalString(value: unknown): string {
  check(value, "$");
  const out = serialize(value);
  if (out === undefined) throw new CanonicalizationError("$: value cannot be serialised");
  return out;
}

export function canonicalize(value: unknown): Bytes {
  return new TextEncoder().encode(canonicalString(value));
}
