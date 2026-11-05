// Calls to the Python engine, from route handlers only. ENGINE_URL and ENGINE_INTERNAL_KEY have
// no NEXT_PUBLIC_ prefix, so they never reach the browser (docs/adr/0002, rule 7: the actor is
// the signed-in user from the session, never from the request body).

export type EngineFailure = { status: number; message: string; problems?: string[] };

export class EngineError extends Error {
  constructor(readonly failure: EngineFailure) {
    super(failure.message);
  }
}

const GENERIC = "The statement service isn't available right now. Try again in a minute.";

// Engine statuses whose messages are written for the coach (bad password, bad tags, a draft
// that's already submitted). Anything else (a wrong internal key, a crash) gets the generic
// message, so configuration details never reach the browser.
const USER_FACING = new Set([400, 403, 409, 413, 415, 422]);

/** Turn an engine error response into something safe to show the coach. */
export function engineFailure(status: number, body: unknown): EngineFailure {
  if (!USER_FACING.has(status)) return { status: 502, message: GENERIC };
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return { status, message: detail };
  if (Array.isArray(detail)) return { status, message: "The request wasn't in the expected format." };
  if (detail && typeof detail === "object") {
    const d = detail as { code?: string; message?: string; problems?: unknown };
    if (Array.isArray(d.problems)) {
      return {
        status,
        message: "Some tags need fixing.",
        problems: d.problems.filter((p): p is string => typeof p === "string"),
      };
    }
    if (typeof d.message === "string") return { status, message: d.message };
  }
  return { status, message: "The statement couldn't be processed." };
}

type Call = {
  actor: string;
  body: BodyInit;
  contentType: string;
  statementPassword?: string;
};

export async function callEngine<T>(path: string, call: Call): Promise<T> {
  const base = process.env.ENGINE_URL;
  const key = process.env.ENGINE_INTERNAL_KEY;
  if (!base || !key) throw new EngineError({ status: 503, message: GENERIC });

  const headers: Record<string, string> = {
    "Content-Type": call.contentType,
    "X-Internal-Key": key,
    "X-Actor-Id": call.actor,
  };
  if (call.statementPassword !== undefined) headers["X-Statement-Password"] = call.statementPassword;

  let response: Response;
  try {
    response = await fetch(new URL(path, base), {
      method: "POST",
      headers,
      body: call.body,
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    throw new EngineError({ status: 502, message: GENERIC });
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new EngineError(engineFailure(response.status, body));
  return body as T;
}
