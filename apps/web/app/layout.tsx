import type { Metadata, Viewport } from "next";
import { Barlow_Condensed, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

// The sealed dossier's typefaces, so the app and the PDF read as one product.
const barlow = Barlow_Condensed({
  variable: "--font-barlow",
  subsets: ["latin"],
  weight: ["600", "700"],
});

const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "SecurePitch",
  description: "Verified sponsor dossiers for community football clubs.",
  applicationName: "SecurePitch",
  // iOS "Add to Home Screen" opens it full screen, with this name under the icon.
  appleWebApp: { capable: true, title: "SecurePitch", statusBarStyle: "default" },
  // Stop iOS turning till numbers, amounts and receipt codes into phone-call links.
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  themeColor: "#0a3d2a",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // On <html>, not <body>: the root element reads these for its own font.
    <html lang="en" className={`${barlow.variable} ${plexSans.variable} ${plexMono.variable}`}>
      <body className="antialiased">{children}</body>
    </html>
  );
}
