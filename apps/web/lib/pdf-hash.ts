// The sponsor drops the PDF they were given; its SHA-256 is compared with the sealed fingerprint.
// Runs entirely in the browser: the file is never uploaded.
import { sha256, toHex } from "./crypto/encoding";

export const MAX_PDF_BYTES = 25 * 1024 * 1024;

export async function hashFile(file: Blob): Promise<string> {
  return toHex(await sha256(new Uint8Array(await file.arrayBuffer())));
}

export function sameHash(actual: string, expected: string): boolean {
  return actual === expected.trim().toLowerCase();
}
