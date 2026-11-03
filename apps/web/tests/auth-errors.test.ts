import { describe, expect, it } from "vitest";

import { signInErrorMessage } from "@/lib/auth-errors";

describe("signInErrorMessage", () => {
  it("returns null when there is no error", () => {
    expect(signInErrorMessage(null)).toBeNull();
  });

  it.each([
    ["invalid_credentials", "don't match"],
    ["email_not_confirmed", "hasn't been activated"],
    ["user_banned", "disabled"],
    ["over_request_rate_limit", "Too many sign-in attempts"],
  ])("explains %s", (code, phrase) => {
    expect(signInErrorMessage({ code, message: "raw" })).toContain(phrase);
  });

  it("treats HTTP 429 without a code as rate limiting", () => {
    expect(signInErrorMessage({ status: 429, message: "raw" })).toContain("Too many");
  });

  it("never says which part was wrong (no account enumeration)", () => {
    const msg = signInErrorMessage({ code: "invalid_credentials" })!;
    expect(msg).not.toMatch(/no account|not found|unknown email/i);
  });

  it("falls back to the raw message with a next step", () => {
    expect(signInErrorMessage({ message: "fetch failed" })).toMatch(/fetch failed.*try again/);
  });
});
