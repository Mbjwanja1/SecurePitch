import { NextResponse } from "next/server";

// Calls to the Python engine, from route handlers only. ENGINE_URL and ENGINE_INTERNAL_KEY have
// no NEXT_PUBLIC_ prefix, so they never reach the browser (docs/adr/0002, rule 7: the actor is
// the signed-in user from the session, never from the request body).

export type EngineFailure = { status: number; message: string; problems?: string[] };

export class EngineError extends Error {
  constructor(readonly failure: EngineFailure) {
    super(failure.message);
  }
}

const GENERIC = "SecurePitch's engine isn't available right now. Try again in a minute.";

// Engine statuses whose messages are written for the coach (bad password, bad tags, a draft
// that's already submitted). Anything else (a wrong internal key, a crash) gets the generic
// message, so configuration details never reach the browser.
const USER_FACING = new Set([400, 403, 404, 409, 413, 415, 422]);

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

/** GET a public, actor-free engine resource (the platform's public keys). */
export async function getFromEngine<T>(path: string): Promise<T> {
  return request<T>(path, "GET", {});
}

export async function callEngine<T>(path: string, call: Call): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": call.contentType,
    "X-Actor-Id": call.actor,
  };
  if (call.statementPassword !== undefined) headers["X-Statement-Password"] = call.statementPassword;
  return request<T>(path, "POST", headers, call.body);
}

async function request<T>(
  path: string,
  method: "GET" | "POST",
  extraHeaders: Record<string, string>,
  body?: BodyInit,
): Promise<T> {
  const base = process.env.ENGINE_URL;
  const key = process.env.ENGINE_INTERNAL_KEY;
  if (!base || !key) throw new EngineError({ status: 503, message: GENERIC });

  const headers = { ...extraHeaders, "X-Internal-Key": key };

  let response: Response;
  try {
    response = await fetch(new URL(path, base), {
      method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    throw new EngineError({ status: 502, message: GENERIC });
  }
  const json: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new EngineError(engineFailure(response.status, json));
  return json as T;
}

/** GET a file (the sealed dossier PDF) from the engine for the signed-in user. */
export async function getEngineFile(path: string, actor: string): Promise<ArrayBuffer> {
  const base = process.env.ENGINE_URL;
  const key = process.env.ENGINE_INTERNAL_KEY;
  if (!base || !key) throw new EngineError({ status: 503, message: GENERIC });
  let response: Response;
  try {
    response = await fetch(new URL(path, base), {
      headers: { "X-Internal-Key": key, "X-Actor-Id": actor },
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    throw new EngineError({ status: 502, message: GENERIC });
  }
  if (!response.ok) {
    throw new EngineError(engineFailure(response.status, await response.json().catch(() => null)));
  }
  return response.arrayBuffer();
}

// Passkey responses are a few KB; anything much bigger isn't one.
export const MAX_JSON_BYTES = 64 * 1024;

/** Read a small JSON object body, or null if it's missing, too big or not an object. */
export async function readSmallJson(request: Request): Promise<Record<string, unknown> | null> {
  const text = await request.text().catch(() => "");
  if (!text || text.length > MAX_JSON_BYTES) return null;
  try {
    const value: unknown = JSON.parse(text);
    return value && typeof value === "object" && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** Forward a JSON call to the engine for the signed-in user and relay its answer. */
export async function relayJson(path: string, actor: string, body: unknown): Promise<NextResponse> {
  try {
    const out = await callEngine(path, {
      actor,
      body: JSON.stringify(body),
      contentType: "application/json",
    });
    return NextResponse.json(out, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    if (err instanceof EngineError) {
      const { status, message, problems } = err.failure;
      return NextResponse.json({ error: message, problems }, { status });
    }
    throw err;
  }
}
