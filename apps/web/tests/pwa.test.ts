import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import manifest from "@/app/manifest";

const WEB = path.resolve(__dirname, "..");
const m = manifest();

/** Width and height from a PNG's IHDR chunk. */
function pngSize(file: string): [number, number] {
  const b = readFileSync(file);
  expect(b.subarray(1, 4).toString("ascii")).toBe("PNG");
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

describe("web app manifest", () => {
  it("installs as a standalone app that opens on the dashboard", () => {
    expect(m).toMatchObject({
      name: "SecurePitch",
      display: "standalone",
      start_url: "/dashboard",
      scope: "/",
      theme_color: "#0a3d2a",
    });
  });

  it("has the icons browsers need, at the sizes it claims", () => {
    const icons = m.icons ?? [];
    for (const size of ["192x192", "512x512"]) {
      expect(icons.some((i) => i.sizes === size && i.purpose === "any")).toBe(true);
    }
    expect(icons.some((i) => i.purpose === "maskable")).toBe(true);
    for (const icon of icons) {
      const [w, h] = pngSize(path.join(WEB, "public", icon.src));
      expect(`${w}x${h}`).toBe(icon.sizes);
    }
    expect(pngSize(path.join(WEB, "app", "apple-icon.png"))).toEqual([180, 180]);
  });

  it("ships no service worker, so nothing financial is cached on the device", () => {
    for (const name of ["sw.js", "service-worker.js", "workbox.js"]) {
      expect(existsSync(path.join(WEB, "public", name))).toBe(false);
    }
  });
});
