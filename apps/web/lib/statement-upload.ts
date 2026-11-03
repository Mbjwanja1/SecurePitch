// Checks on an uploaded statement, shared by the browser (early feedback) and the route
// handlers (the real check). The engine checks again.

// Vercel refuses request bodies over 4.5 MB. A month's M-Pesa statement is usually well under 1 MB.
export const MAX_STATEMENT_BYTES = 4 * 1024 * 1024;
export const MAX_PASSWORD_LENGTH = 64;

export type UploadProblem = { status: number; message: string };

export function checkStatementFile(file: { size: number; name: string; type: string }): UploadProblem | null {
  if (file.size === 0) return { status: 400, message: "That file is empty." };
  if (file.size > MAX_STATEMENT_BYTES) {
    return { status: 413, message: "Statements are limited to 4 MB. Download one month at a time." };
  }
  if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
    return { status: 415, message: "Choose the PDF statement M-Pesa sent you." };
  }
  return null;
}

/** True when the bytes start like a PDF ("%PDF-"), whatever the file name says. */
export function looksLikePdf(bytes: Uint8Array): boolean {
  const magic = [0x25, 0x50, 0x44, 0x46, 0x2d];
  return bytes.length >= magic.length && magic.every((b, i) => bytes[i] === b);
}

/**
 * Read the statement and its password from a multipart form. The bytes and password are only
 * passed on to the engine; nothing is written to disk or logged.
 */
export async function readStatementForm(
  form: FormData,
): Promise<{ pdf: Uint8Array<ArrayBuffer>; password: string } | UploadProblem> {
  const file = form.get("statement");
  const password = form.get("password");
  if (!(file instanceof File)) return { status: 400, message: "Choose your statement PDF." };
  if (typeof password !== "string" || password.length === 0) {
    return { status: 400, message: "Enter the statement password (from the M-Pesa SMS)." };
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return { status: 400, message: "That password is too long." };
  }
  const problem = checkStatementFile(file);
  if (problem) return problem;
  const pdf = new Uint8Array(await file.arrayBuffer());
  if (!looksLikePdf(pdf)) return { status: 415, message: "That file isn't a PDF." };
  return { pdf, password };
}
