import { describe, expect, it } from "vitest";

import { INSTALL_STEPS, installPlatform } from "@/lib/install";

const IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1";
const IPAD_AS_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/18.0 Safari/605.1.15";
const ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36";
const WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36";

describe("installPlatform", () => {
  it.each([
    ["an iPhone", IPHONE, 5, "ios"],
    ["an iPad posing as a Mac", IPAD_AS_MAC, 5, "ios"],
    ["a real Mac", IPAD_AS_MAC, 0, "desktop"],
    ["Android Chrome", ANDROID, 5, "android"],
    ["Windows Chrome", WINDOWS, 0, "desktop"],
    ["Facebook on Android", `${ANDROID} [FB_IAB/FB4A;FBAV/480.0]`, 5, "in-app"],
    ["Instagram on iPhone", `${IPHONE} Instagram 300.0`, 5, "in-app"],
    ["WhatsApp's browser", `${ANDROID} WhatsApp/2.24`, 5, "in-app"],
    ["an Android web view", ANDROID.replace("Pixel 8)", "Pixel 8; wv)"), 5, "in-app"],
  ])("recognises %s", (_label, ua, touch, expected) => {
    expect(installPlatform(ua, touch)).toBe(expected);
  });

  it("has instructions for every platform", () => {
    for (const platform of ["in-app", "ios", "android", "desktop"] as const) {
      expect(INSTALL_STEPS[platform].steps.length).toBeGreaterThan(0);
    }
  });
});
