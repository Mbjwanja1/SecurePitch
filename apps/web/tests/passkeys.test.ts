// Passkey screens: error wording, the signing fingerprint, and the JSON relay to the engine.
import { afterEach, describe, expect, it, vi } from "vitest";

import { MAX_JSON_BYTES, readSmallJson, relayJson } from "@/lib/engine";
import { fingerprint, passkeyErrorMessage, postJson } from "@/lib/passkey-client";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("passkey prompt errors", () => {
  it.each([
    ["NotAllowedError", "cancelled"],
    ["InvalidStateError", "already has a passkey"],
    ["SecurityError", "own address"],
    ["SomethingNew", "didn't work"],
  ])("%s is explained in plain words", (name, words) => {
    expect(passkeyErrorMessage(Object.assign(new Error("x"), { name }))).toContain(words);
  });

  it("copes with things that aren't errors", () => {
    expect(passkeyErrorMessage(undefined)).toContain("didn't work");
  });
});

describe("signing fingerprint", () => {
  it("shows the first 16 hex digits of the challenge in groups of four", () => {
    expect(fingerprint("a1b2c3d4e5f60718" + "0".repeat(48))).toBe("A1B2 C3D4 E5F6 0718");
  });
});

describe("postJson", () => {
  it("unwraps errors from our route handlers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "Add a passkey before signing" }), { status: 409 }),
      ),
    );
    expect(await postJson("/api/x", {})).toEqual({
      ok: false,
      error: "Add a passkey before signing",
      problems: undefined,
    });
  });

  it("explains a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const r = await postJson("/api/x", {});
    expect(r.ok).toBe(false);
    expect(!r.ok && r.error).toContain("connection");
  });
});

describe("readSmallJson", () => {
  const req = (body: string) => new Request("http://localhost/api", { method: "POST", body });

  it("accepts a small JSON object", async () => {
    expect(await readSmallJson(req('{"credential": {"id": "abc"}}'))).toEqual({
      credential: { id: "abc" },
    });
  });

  it.each([
    ["not JSON", "{"],
    ["an array", "[1]"],
    ["a string", '"x"'],
    ["empty", ""],
    ["too big", JSON.stringify({ x: "a".repeat(MAX_JSON_BYTES) })],
  ])("refuses %s", async (_, body) => {
    expect(await readSmallJson(req(body))).toBeNull();
  });
});

describe("relayJson", () => {
  it("passes the user as X-Actor-Id and relays engine refusals with their status", async () => {
    vi.stubEnv("ENGINE_URL", "http://engine.test");
    vi.stubEnv("ENGINE_INTERNAL_KEY", "k".repeat(40));
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: { code: "forbidden", message: "Only the club treasurer can sign this dossier now" } }),
        { status: 403 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const r = await relayJson("/v1/dossiers/d/approval/options", "user-7", {});
    expect(r.status).toBe(403);
    expect(await r.json()).toMatchObject({ error: "Only the club treasurer can sign this dossier now" });
    expect(fetchMock.mock.calls[0][1].headers).toMatchObject({ "X-Actor-Id": "user-7" });
    expect(fetchMock.mock.calls[0][1].headers).not.toHaveProperty("X-Statement-Password");
  });

  it("never caches", async () => {
    vi.stubEnv("ENGINE_URL", "http://engine.test");
    vi.stubEnv("ENGINE_INTERNAL_KEY", "k".repeat(40));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: 1 }))));
    const r = await relayJson("/v1/x", "u", {});
    expect(r.headers.get("cache-control")).toBe("no-store");
  });
});
