import { describe, expect, it } from "vitest";

import { stepsDone } from "@/lib/dossier-progress";
import { formatPeriod } from "@/lib/tagging";

describe("formatPeriod", () => {
  it.each([
    ["2026-10-01", "2026-10-31", "October 2026"],
    ["2026-12-01", "2026-12-31", "December 2026"],
    ["2028-02-01", "2028-02-29", "February 2028"],
    ["2026-10-01", "2026-10-30", "1 Oct – 30 Oct 2026"],
    ["2026-10-05", "2026-11-02", "5 Oct – 2 Nov 2026"],
    ["2026-12-20", "2027-01-05", "20 Dec 2026 – 5 Jan 2027"],
  ])("%s to %s reads %s", (from, to, label) => {
    expect(formatPeriod(from, to)).toBe(label);
  });
});

describe("dossier progress", () => {
  it.each([
    ["draft", 0],
    ["submitted", 2],
    ["approved", 3],
    ["sealed", 4],
    ["revoked", 4],
    ["something-new", 0],
  ])("%s has %i steps done", (status, done) => {
    expect(stepsDone(status)).toBe(done);
  });
});
