import { describe, expect, it } from "vitest";

import { hashFile, sameHash } from "../lib/pdf-hash";

// SHA-256 of the three bytes "abc" (a standard test value).
const ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

describe("hashFile", () => {
  it("hashes a file's bytes", async () => {
    expect(await hashFile(new Blob(["abc"]))).toBe(ABC);
  });

  it("gives a different hash when one byte changes", async () => {
    const changed = await hashFile(new Blob(["abd"]));
    expect(changed).not.toBe(ABC);
    expect(sameHash(changed, ABC)).toBe(false);
  });
});

describe("sameHash", () => {
  it("matches the sealed fingerprint", () => {
    expect(sameHash(ABC, ABC)).toBe(true);
  });

  it("ignores case and spaces in the stored value", () => {
    expect(sameHash(ABC, `  ${ABC.toUpperCase()} `)).toBe(true);
  });
});
