// Upload and tagging: what the browser sends, what the coach sees, and engine error handling.
import { afterEach, describe, expect, it, vi } from "vitest";

import { callEngine, EngineError, engineFailure } from "@/lib/engine";
import {
  checkStatementFile,
  looksLikePdf,
  MAX_STATEMENT_BYTES,
  readAcknowledgedChecks,
  readStatementForm,
} from "@/lib/statement-upload";
import {
  type Batch,
  categoriesFor,
  counterpartyLabel,
  failedCheckNames,
  formatKes,
  formatWhen,
  setTag,
  summarize,
  tagBatch,
  tagPayload,
  type Transaction,
} from "@/lib/tagging";

function tx(id: string, dir: "in" | "out", amount: number, fee = 0): Transaction {
  return {
    tx: id,
    ts: "2026-10-17T07:15:00+03:00",
    dir,
    amount_cents: amount,
    fee_cents: fee,
    kind: dir === "in" ? "p2p_in" : "p2p_out",
    details: "synthetic",
    match: null,
  };
}

const FARES = ["SJB0000001", "SJB0000002", "SJB0000003"].map((id) => tx(id, "out", 25000, 700));
const GIFT = tx("SJA0000003", "in", 400000);
const AIRTIME = tx("SJD0000005", "out", 10000);
const ALL = [...FARES, GIFT, AIRTIME];
const BATCH: Batch = {
  day: "2026-10-17",
  amount_cents: 25000,
  size: 3,
  verified: 3,
  fixture_code: "MD4-2026-10-17",
  txs: FARES.map((t) => t.tx),
};

describe("tagging", () => {
  it("offers only club income for money in, and spending categories for money out", () => {
    expect(categoriesFor("in")).toEqual(["income"]);
    expect(categoriesFor("out")).not.toContain("income");
    expect(categoriesFor("out")).toContain("transport");
  });

  it("tags and untags a whole matchday batch", () => {
    const tagged = tagBatch({}, BATCH, "transport");
    expect(Object.keys(tagged)).toEqual(BATCH.txs);
    expect(tagBatch(tagged, BATCH, null)).toEqual({});
  });

  it("totals spending with fees, and counts untagged rows as personal", () => {
    const tags = setTag(tagBatch({}, BATCH, "transport"), GIFT.tx, "income");
    expect(summarize(ALL, tags)).toEqual({
      tagged: 4,
      personal: 1,
      incomeCents: 400000,
      spentCents: 3 * (25000 + 700),
    });
  });

  it("sends only receipt numbers and categories: no amounts, no personal rows", () => {
    const tags = setTag(setTag({}, GIFT.tx, "income"), AIRTIME.tx, "meals");
    const payload = tagPayload(ALL, setTag(tags, AIRTIME.tx, null));
    expect(payload).toEqual([{ tx: GIFT.tx, category: "income" }]);
    expect(JSON.stringify(payload)).not.toContain("amount");
  });

  it("never shows a hashed counterparty", () => {
    expect(counterpartyLabel("player", "P03")).toBe("Player P03");
    expect(counterpartyLabel("till", "5123456")).toBe("Till 5123456");
    expect(counterpartyLabel("person", `hmac:${"ab".repeat(32)}`)).not.toContain("hmac");
  });

  it("formats shillings and Kenyan time whatever the viewer's time zone", () => {
    expect(formatKes(642600)).toBe("KES 6,426.00");
    expect(formatWhen("2026-10-17T04:15:00Z")).toMatch(/17 Oct.*07:15/);
  });
});

describe("statement upload checks", () => {
  const pdf = (size: number, name = "statement.pdf", type = "application/pdf") => ({ size, name, type });

  it("accepts a PDF up to the limit", () => {
    expect(checkStatementFile(pdf(MAX_STATEMENT_BYTES))).toBeNull();
    expect(checkStatementFile(pdf(1000, "MPESA_Statement.PDF", ""))).toBeNull();
    expect(checkStatementFile(pdf(1000, "statement.eml", ""))).toBeNull();
  });

  it.each([
    [pdf(0), 400],
    [pdf(MAX_STATEMENT_BYTES + 1), 413],
    [pdf(1000, "statement.png", "image/png"), 415],
    [pdf(MAX_STATEMENT_BYTES + 1, "statement.eml", "message/rfc822"), 413],
  ])("refuses %j with %i", (file, status) => {
    expect(checkStatementFile(file)?.status).toBe(status);
  });

  it("checks the bytes, not the file name", () => {
    expect(looksLikePdf(new TextEncoder().encode("%PDF-1.7\n"))).toBe(true);
    expect(looksLikePdf(new TextEncoder().encode("<html>"))).toBe(false);
  });

  it("needs a password and a real PDF", async () => {
    const form = (body: string, password?: string) => {
      const f = new FormData();
      f.set("statement", new File([body], "statement.pdf", { type: "application/pdf" }));
      if (password !== undefined) f.set("password", password);
      return f;
    };
    expect(await readStatementForm(form("%PDF-1.7"))).toMatchObject({ status: 400 });
    expect(await readStatementForm(form("<html>", "123456"))).toMatchObject({ status: 415 });
    const ok = await readStatementForm(form("%PDF-1.7", "123456"));
    expect("bytes" in ok && ok.password).toBe("123456");
    expect("bytes" in ok && ok.format).toBe("pdf");
  });
});

describe("engine errors shown to the coach", () => {
  it("passes on messages written for the coach", () => {
    expect(
      engineFailure(422, { detail: { code: "wrong_password", message: "The statement password is wrong." } }),
    ).toEqual({ status: 422, message: "The statement password is wrong." });
    expect(
      engineFailure(429, { detail: { code: "rate_limited", message: "Too many statement uploads. Try again in about 5 minutes." } }).message,
    ).toBe("Too many statement uploads. Try again in about 5 minutes.");
    expect(
      engineFailure(422, { detail: { code: "bad_tags", problems: ["SZZ9999999: not in this statement"] } }),
    ).toMatchObject({ problems: ["SZZ9999999: not in this statement"] });
  });

  it.each([401, 500, 503])("hides configuration and crash details (%i)", (status) => {
    const f = engineFailure(status, { detail: "Missing or invalid X-Internal-Key" });
    expect(f.status).toBe(502);
    expect(f.message).not.toContain("Internal-Key");
  });
});

describe("callEngine", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("sends the internal key, the actor and the statement password as headers", async () => {
    vi.stubEnv("ENGINE_URL", "http://engine.test");
    vi.stubEnv("ENGINE_INTERNAL_KEY", "k".repeat(40));
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);

    await callEngine("/v1/clubs/c/statements/parse", {
      actor: "user-1",
      body: "%PDF-",
      contentType: "application/pdf",
      statementPassword: "123456",
    });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://engine.test/v1/clubs/c/statements/parse");
    expect(init.headers).toMatchObject({
      "X-Internal-Key": "k".repeat(40),
      "X-Actor-Id": "user-1",
      "X-Statement-Password": "123456",
    });
  });

  it("fails safely when the engine isn't configured or reachable", async () => {
    vi.stubEnv("ENGINE_URL", "");
    await expect(
      callEngine("/x", { actor: "u", body: "", contentType: "application/json" }),
    ).rejects.toBeInstanceOf(EngineError);
    vi.stubEnv("ENGINE_URL", "http://engine.test");
    vi.stubEnv("ENGINE_INTERNAL_KEY", "k".repeat(40));
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    await expect(
      callEngine("/x", { actor: "u", body: "", contentType: "application/json" }),
    ).rejects.toMatchObject({ failure: { status: 502 } });
  });
});

describe("statement warnings", () => {
  const check = (passed: boolean) => ({ passed, weight_bp: 500, detail: "" });

  it("lists only the checks that failed", () => {
    const integrity = { score_bp: 9500, checks: { balance_chain: check(true), producer_baseline: check(false) } };
    expect(failedCheckNames({ integrity })).toEqual(["producer_baseline"]);
  });

  it.each([
    [null, []],
    ["not json", []],
    ['{"a":1}', []],
    ['["producer_baseline",7,"BAD NAME"]', ["producer_baseline"]],
  ])("reads acknowledgements from %s", (raw, expected) => {
    expect(readAcknowledgedChecks(raw)).toEqual(expected);
  });

  it("caps how many acknowledgements are forwarded", () => {
    expect(readAcknowledgedChecks(JSON.stringify(Array(50).fill("a_check")))).toHaveLength(10);
  });
});

describe("statement emails", () => {
  it("points a too-large email to the PDF route instead", () => {
    const big = { size: MAX_STATEMENT_BYTES + 1, name: "statement.eml", type: "message/rfc822" };
    expect(checkStatementFile(big)?.message).toMatch(/Upload the PDF statement/);
  });

  it("passes an .eml to the engine to verify, without treating it as a PDF", async () => {
    const f = new FormData();
    f.set("statement", new File(["From: a@b.example\r\n\r\nhi"], "statement.eml", { type: "" }));
    f.set("password", "123456");
    const ok = await readStatementForm(f);
    expect("bytes" in ok && ok.format).toBe("email");
  });

  it("still refuses a non-PDF that only claims to be a PDF", async () => {
    const f = new FormData();
    f.set("statement", new File(["From: a@b.example"], "statement.pdf", { type: "application/pdf" }));
    f.set("password", "123456");
    expect(await readStatementForm(f)).toMatchObject({ status: 415 });
  });
});
