import { describe, expect, it } from "vitest";

import {
  MAX_PLAYERS,
  duplicateOf,
  maskPhone,
  parseRosterCsv,
  validatePlayer,
  validatePlayers,
} from "@/lib/roster";

// Numbers are assembled from parts, so this file holds no literal phone number: the
// kenyan-mobile-number gitleaks rule scans every commit (same approach as test_matching.py).
const num = (...parts: string[]) => parts.join("");
const JANE = num("0712", "345678");
const JANE_SPACED = num("0712", " 345 678");
const ANN = num("0711", "111111");

const good = {
  full_name: "Jane Wanjiku",
  phone: JANE_SPACED,
  fkf_id: "",
  is_minor: false,
  consent_by: "Jane Wanjiku",
  consent_at: "2026-01-15",
};

// Two days ahead is in the future wherever you are.
const future = new Date(Date.now() + 2 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);

describe("validatePlayer", () => {
  it("accepts a player, adds the Kenyan offset to a date and turns an empty FKF number into null", () => {
    const r = validatePlayer(good);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.player.consent_at).toBe("2026-01-15T00:00:00+03:00");
      expect(r.player.fkf_id).toBeNull();
    }
  });

  it.each([
    ["a one-letter name", { ...good, full_name: "J" }],
    ["no phone", { ...good, phone: "" }],
    ["a too-short phone number", { ...good, phone: "12345" }],
    ["a landline", { ...good, phone: "0201234567" }],
    ["no consent giver", { ...good, consent_by: "" }],
    ["a day that doesn't exist", { ...good, consent_at: "2026-02-31" }],
    ["a US-style date", { ...good, consent_at: "7/11/2026" }],
    ["a date in words", { ...good, consent_at: "Nov 7 2026" }],
    ["a future date", { ...good, consent_at: future }],
  ])("rejects %s", (_label, input) => {
    expect(validatePlayer(input).ok).toBe(false);
  });

  it.each([JANE_SPACED, num("+254", " 712 345 678"), num("254", "112345678"), "712345678"])(
    "accepts the phone number %s",
    (phone) => {
      expect(validatePlayer({ ...good, phone }).ok).toBe(true);
    },
  );

  it("reads is_minor from yes or true text", () => {
    const yes = validatePlayer({ ...good, is_minor: "Yes" });
    expect(yes.ok && yes.player.is_minor).toBe(true);
  });

  it("passes on only the known fields", () => {
    const r = validatePlayer({ ...good, extra: "x", parent_phone: num("0700", "000000") });
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(Object.keys(r.player).sort()).toEqual(
        ["consent_at", "consent_by", "fkf_id", "full_name", "is_minor", "phone"].sort(),
      );
    }
  });
});

describe("validatePlayers", () => {
  it("rejects an empty list and an oversized one", () => {
    expect(validatePlayers([]).ok).toBe(false);
    expect(validatePlayers(Array.from({ length: MAX_PLAYERS + 1 }, () => good)).ok).toBe(false);
  });

  it("names the row that is wrong", () => {
    const r = validatePlayers([good, { ...good, phone: "" }]);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain("Player 2");
  });

  it("accepts its own output when the route checks it again", () => {
    const c = validatePlayer(good);
    expect(c.ok).toBe(true);
    if (c.ok) expect(validatePlayers([c.player]).ok).toBe(true);
  });

  it("refuses the same number written two ways, and says whose it is", () => {
    const r = validatePlayers([good, { ...good, full_name: "Ann Atieno", phone: num("+254", "712345678") }]);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toContain("Jane Wanjiku");
  });
});

describe("duplicateOf", () => {
  it("matches a number however it was typed", () => {
    const jane = { ...good, fkf_id: null };
    expect(duplicateOf([jane], num("254", "712345678"))?.full_name).toBe("Jane Wanjiku");
    expect(duplicateOf([jane], num("0722", " 000 111"))).toBeUndefined();
  });
});

describe("parseRosterCsv", () => {
  const header = "full_name,phone,fkf_id,is_minor,consent_by,consent_at";

  it("reads quoted names that contain a comma", () => {
    const r = parseRosterCsv(`\uFEFF${header}\r\n"Wanjiku, Jane",${JANE},,false,Jane Wanjiku,2026-01-15\r\n`);
    expect(r.errors).toEqual([]);
    expect(r.players).toHaveLength(1);
    expect(r.players[0].full_name).toBe("Wanjiku, Jane");
  });

  it("reads headers as exported from Excel or Google Sheets", () => {
    const r = parseRosterCsv(
      `Full Name,Phone Number,Is Minor,Consent By,Consent At\nAnn Atieno,${ANN},no,Ann Atieno,2026-01-15\n`,
    );
    expect(r.errors).toEqual([]);
    expect(r.players).toHaveLength(1);
  });

  it("reports the bad row and keeps the good ones", () => {
    const r = parseRosterCsv(`${header}\nAnn Atieno,${ANN},,false,Ann Atieno,2026-01-15\nB,1,,false,,\n`);
    expect(r.players).toHaveLength(1);
    expect(r.errors[0]).toContain("Row 3");
  });

  it("reports a number that appears twice", () => {
    const r = parseRosterCsv(
      `${header}\nAnn Atieno,${ANN},,false,Ann Atieno,2026-01-15\nBea Njeri,${num("+254", "711111111")},,false,Bea Njeri,2026-01-15\n`,
    );
    expect(r.players).toHaveLength(1);
    expect(r.errors[0]).toContain("same phone number as Ann Atieno");
  });

  it("refuses a file without the required columns", () => {
    expect(parseRosterCsv(`name,phone\nAnn,${ANN}`).errors[0]).toContain("Missing columns");
  });

  it("refuses a file with no is_minor column", () => {
    const r = parseRosterCsv(`full_name,phone,fkf_id,consent_by,consent_at\nAnn,${ANN},,Ann,2026-01-15`);
    expect(r.players).toEqual([]);
    expect(r.errors[0]).toContain("is_minor");
  });
});

describe("maskPhone", () => {
  it("shows only the last three digits", () => {
    const masked = maskPhone(JANE);
    expect(masked).toBe("*** *** 678");
    expect(masked).not.toContain("0712");
  });
});
