// Browser helpers for the passkey screens.

export type JsonResult =
  | { ok: true; data: Record<string, unknown> }
  | { ok: false; error: string; problems?: string[] };

/** POST JSON to one of our own route handlers and unwrap { error } responses. */
export async function postJson(url: string, body: unknown): Promise<JsonResult> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, error: "Couldn't reach SecurePitch. Check your connection and try again." };
  }
  const json = await response.json().catch(() => ({}));
  if (!response.ok) {
    return {
      ok: false,
      error: typeof json.error === "string" ? json.error : "Something went wrong. Try again.",
      problems: Array.isArray(json.problems) ? json.problems : undefined,
    };
  }
  return { ok: true, data: json };
}

/**
 * Plain words for what the browser's passkey prompt can throw. @simplewebauthn/browser keeps
 * the DOMException name (NotAllowedError and so on) on its errors.
 */
export function passkeyErrorMessage(err: unknown): string {
  const name = err && typeof err === "object" && "name" in err ? String(err.name) : "";
  switch (name) {
    case "NotAllowedError":
    case "AbortError":
      return "The passkey prompt was cancelled or timed out. Try again when you're ready.";
    case "InvalidStateError":
      return "This device already has a passkey for your account.";
    case "SecurityError":
      return "Passkeys only work on SecurePitch's own address. Check the link you opened.";
    case "NotSupportedError":
      return "This device can't create a supported passkey. Try your phone instead.";
    default:
      return "The passkey didn't work. Try again, or use another device.";
  }
}

/** "a1b2c3d4e5f6…" -> "A1B2 C3D4 E5F6 7890": short enough for two signers to compare by eye. */
export function fingerprint(challenge: string): string {
  return (challenge.slice(0, 16).toUpperCase().match(/.{4}/g) ?? []).join(" ");
}
