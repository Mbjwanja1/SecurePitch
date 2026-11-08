import type { MetadataRoute } from "next";

// Makes SecurePitch installable (Add to Home Screen). Served at /manifest.webmanifest.
//
// Deliberately no service worker: nothing is cached on the device, so a lost or shared phone
// never holds statements, ledgers or dossiers offline. Browsers no longer require one to
// install a site. Passkeys keep working in the installed app: they belong to the domain, and
// the app opens on the same domain.
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "SecurePitch",
    short_name: "SecurePitch",
    description: "Verified sponsor dossiers for community football clubs.",
    start_url: "/dashboard",
    scope: "/",
    display: "standalone",
    background_color: "#ffffff",
    theme_color: "#0a3d2a",
    lang: "en",
    categories: ["finance", "sports"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      {
        src: "/icons/icon-maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
  };
}
