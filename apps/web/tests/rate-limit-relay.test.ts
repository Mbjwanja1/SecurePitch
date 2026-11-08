// A 429 from the engine has to reach the browser with its Retry-After, through the route handlers.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { POST as parseStatement } from "@/app/api/club/[clubId]/statements/parse/route";
import { callEngine, EngineError, failureHeaders } from "@/lib/engine";

vi.mock("@/lib/club-guard", () => ({
  requireManager: vi.fn().mockResolvedValue({ userId: "user-1" }),
}));
vi.mock("@/lib/statement-upload", () => ({
  readStatementForm: vi.fn().mockResolvedValue({ pdf: new Uint8Array([1]), password: "x" }),
}));

const MESSAGE = "Too many statement uploads. Try again in about 10 minutes.";

function engineReplies(status: number, headers: Record<string, string> = {}) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { code: "rate_limited", message: MESSAGE } }), {
        status,
        headers,
      }),
    ),
  );
}

const failure = async () => {
  try {
    await callEngine("/x", { actor: "u", body: "", contentType: "application/json" });
  } catch (err) {
    return (err as EngineError).failure;
  }
  throw new Error("expected the call to fail");
};

beforeEach(() => {
  vi.stubEnv("ENGINE_URL", "http://engine.test");
  vi.stubEnv("ENGINE_INTERNAL_KEY", "k".repeat(40));
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("Retry-After from the engine", () => {
  it("is kept on a 429", async () => {
    engineReplies(429, { "Retry-After": "600" });
    const f = await failure();
    expect(f).toMatchObject({ status: 429, message: MESSAGE, retryAfter: "600" });
    expect(failureHeaders(f)).toEqual({ "Retry-After": "600" });
  });

  it("is dropped if it isn't a number of seconds", async () => {
    engineReplies(429, { "Retry-After": "soon\tish" });
    const f = await failure();
    expect(f.retryAfter).toBeUndefined();
    expect(failureHeaders(f)).toEqual({});
  });

  it("is ignored on other errors", async () => {
    engineReplies(422, { "Retry-After": "600" });
    expect((await failure()).retryAfter).toBeUndefined();
  });

  it("reaches the browser through the route handler", async () => {
    engineReplies(429, { "Retry-After": "600" });
    const form = new FormData();
    form.set("password", "x");
    const request = new NextRequest("http://localhost/api/club/c/statements/parse", {
      method: "POST",
      body: form,
    });
    const r = await parseStatement(request, { params: Promise.resolve({ clubId: "c" }) });
    expect(r.status).toBe(429);
    expect(r.headers.get("retry-after")).toBe("600");
    expect(await r.json()).toEqual({ error: MESSAGE });
  });
});
