// Which install instructions fit this device. iPhones can't be prompted by a site, and in-app
// browsers (WhatsApp, Facebook, Instagram) can't install or reliably use passkeys at all.

export type InstallPlatform = "in-app" | "ios" | "android" | "desktop";

const IN_APP = /\b(FBAN|FBAV|FB_IAB|Instagram|WhatsApp|Line\/|Snapchat|TikTok|MicroMessenger)\b|; wv\)/i;

export function installPlatform(userAgent: string, maxTouchPoints = 0): InstallPlatform {
  if (IN_APP.test(userAgent)) return "in-app";
  // iPads report themselves as a Mac, but no Mac has a multi-touch screen.
  if (/iPad|iPhone|iPod/.test(userAgent) || (/Macintosh/.test(userAgent) && maxTouchPoints > 1)) {
    return "ios";
  }
  return /Android/i.test(userAgent) ? "android" : "desktop";
}

export const INSTALL_STEPS: Record<InstallPlatform, { title: string; steps: string[] }> = {
  "in-app": {
    title: "Open this in your browser first",
    steps: [
      "This page opened inside another app, which can't install SecurePitch or use passkeys.",
      "Copy the link below and open it in Chrome or Safari.",
    ],
  },
  ios: {
    title: "Add SecurePitch to your iPhone",
    steps: [
      "Open this page in Safari.",
      "Tap the Share button at the bottom of the screen.",
      "Scroll down and tap Add to Home Screen, then Add.",
    ],
  },
  android: {
    title: "Add SecurePitch to your phone",
    steps: ["Tap the ⋮ menu at the top right of Chrome.", "Tap Install app or Add to Home screen."],
  },
  desktop: {
    title: "Install SecurePitch on this computer",
    steps: [
      "Use Chrome or Edge, and look for the install icon at the right of the address bar.",
      "Or open the browser menu and choose Install SecurePitch.",
    ],
  },
};
