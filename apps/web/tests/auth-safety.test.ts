// Regression tests for the PR 5 review: open redirects, sign-out CSRF and cookie loss.
import { NextResponse } from "next/server";
import { describe, expect, it } from "vitest";

import { isSameOrigin, safeNext } from "@/lib/safe-redirect";
import { redirectKeepingCookies } from "@/lib/supabase/middleware";

const ORIGIN = "https://securepitch.vercel.app";
const B = "\\";

describe("safeNext: where to go after sign-in", () => {
  it.each([
    ["/dashboard", "/dashboard"],
    ["/dossiers/42?tab=review#top", "/dossiers/42?tab=review#top"],
    ["/%2F%2Fevil.com", "/%2F%2Fevil.com"], // encoded slashes stay a local path
  ])("keeps the same-site path %j", (next, expected) => {
    expect(safeNext(next, ORIGIN)).toBe(expected);
  });

  it.each([
    `/${B}evil.com`, // browsers treat "\" as "/"
    `/${B}${B}evil.com`,
    `/${B}evil.com/dashboard`,
    "/\t/evil.com", // browsers strip tabs and newlines
    "/\n/evil.com",
    "//evil.com",
    "https://evil.com",
    "javascript:alert(1)",
    "dashboard",
    "",
    null,
  ])("falls back to /dashboard for %j", (next) => {
    expect(safeNext(next, ORIGIN)).toBe("/dashboard");
  });

  it("never returns anything that resolves off-site", () => {
    const tricks = [`/${B}evil.com`, "/\t/evil.com", "//evil.com", `/${B}/evil.com`, "/\r/evil.com"];
    for (const t of tricks) {
      expect(new URL(safeNext(t, ORIGIN), ORIGIN).origin).toBe(ORIGIN);
    }
  });
});

describe("isSameOrigin: sign-out CSRF guard", () => {
  it("accepts our own origin", () => expect(isSameOrigin(ORIGIN, null, ORIGIN)).toBe(true));
  it("refuses another site", () => expect(isSameOrigin("https://evil.com", null, ORIGIN)).toBe(false));
  it("falls back to Sec-Fetch-Site", () => {
    expect(isSameOrigin(null, "same-origin", ORIGIN)).toBe(true);
    expect(isSameOrigin(null, "cross-site", ORIGIN)).toBe(false);
  });
  it("refuses requests with no origin information", () =>
    expect(isSameOrigin(null, null, ORIGIN)).toBe(false));
});

describe("redirectKeepingCookies: refreshed sessions survive redirects", () => {
  it("copies refreshed auth cookies onto the redirect", () => {
    const passThrough = NextResponse.next();
    passThrough.cookies.set("sb-access-token", "refreshed", { httpOnly: true, path: "/" });
    passThrough.cookies.set("sb-refresh-token", "rotated", { httpOnly: true, path: "/" });

    const redirect = redirectKeepingCookies(passThrough, new URL("/dashboard", ORIGIN));

    expect(redirect.status).toBe(307);
    expect(redirect.headers.get("location")).toBe(`${ORIGIN}/dashboard`);
    expect(redirect.cookies.get("sb-access-token")?.value).toBe("refreshed");
    expect(redirect.cookies.get("sb-refresh-token")?.value).toBe("rotated");
    expect(redirect.cookies.get("sb-access-token")?.httpOnly).toBe(true);
  });
});
