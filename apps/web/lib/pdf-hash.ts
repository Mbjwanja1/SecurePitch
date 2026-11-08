// The sponsor drops the PDF they were given; its SHA-256 is compared with the sealed fingerprint.
// Runs entirely in the browser: the file is never uploaded.
import { sha256, toHex } from "./crypto/encoding";

export const MAX_PDF_BYTES = 25 * 1024 * 1024;

const HEX64 = /^[0-9a-f]{64}$/;

export async function hashFile(file: Blob): Promise<string> {
  return toHex(await sha256(new Uint8Array(await file.arrayBuffer())));
}

/** True only when `expected` is a real SHA-256 and `actual` equals it. A blank or garbled stored value never matches. */
export function sameHash(actual: string, expected: string): boolean {
  const a = actual.trim().toLowerCase();
  const e = expected.trim().toLowerCase();
  return HEX64.test(e) && a === e;
}
