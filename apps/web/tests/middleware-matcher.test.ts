// Which paths the session middleware runs on. /.well-known must stay public (sponsors' verifiers
// fetch the platform keys there): never a redirect to sign-in, and no session refresh.
import { describe, expect, it } from "vitest";

import { config } from "@/middleware";

// The matcher is a single path regex group; anchored, it decides like Next.js does for these paths.
const runs = (path: string) => config.matcher.some((m) => new RegExp(`^${m}$`).test(path));

describe("middleware matcher", () => {
  it.each(["/.well-known/securepitch-keys.json", "/_next/static/chunk.js", "/logo.svg"])(
    "skips %s",
    (path) => expect(runs(path)).toBe(false),
  );

  it.each(["/dashboard", "/dossiers/abc", "/settings/passkeys", "/api/dossiers/abc/seal", "/login"])(
    "runs on %s",
    (path) => expect(runs(path)).toBe(true),
  );
});
