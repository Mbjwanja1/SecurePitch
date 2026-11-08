import type { Metadata } from "next";
import Link from "next/link";

import { Brand } from "@/components/brand";
import { InstallApp } from "@/components/install-app";
import { StatementDemo } from "@/components/landing/statement-demo";
import { TamperDemo } from "@/components/landing/tamper-demo";
import { buttonVariants } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "SecurePitch · Club money on the record",
  description:
    "Turn a coach's M-Pesa statement into a sealed sponsor dossier, without exposing their personal spending.",
};

const STEPS = [
  ["Upload", "The manager uploads the month's M-Pesa statement. It's read in memory and never stored."],
  ["Tag", "They mark which payments were club money. Everything else stays private and is never saved."],
  ["Sign", "The manager and the treasurer each approve with their own passkey: a fingerprint, face or PIN."],
  ["Seal", "SecurePitch signs the whole dossier and makes a PDF with a QR code for sponsors."],
  ["Verify", "A sponsor scans the code. Every signature is checked in their own browser, with no account."],
];

const SECTION = "mx-auto w-full max-w-5xl px-4 py-12 sm:py-16";

export default function LandingPage() {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-2.5">
          <Link href="/" aria-label="SecurePitch home" className="inline-flex min-h-10 items-center">
            <Brand />
          </Link>
          <nav aria-label="Main" className="flex items-center gap-1 sm:gap-2">
            <Link href="/guide" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              Guide
            </Link>
            <Link href="/login" className={buttonVariants({ size: "sm" })}>
              Sign in
            </Link>
          </nav>
        </div>
      </header>

      <main>
        <section className={`${SECTION} grid items-center gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]`}>
          <div className="flex flex-col gap-5">
            <h1 className="text-5xl leading-[1.02] font-bold sm:text-7xl">
              Club money on the record. Personal spending off it.
            </h1>
            <p className="max-w-prose text-base text-muted-foreground sm:text-lg">
              Grassroots coaches run club money through their own M-Pesa lines, and sponsors can&apos;t
              trust those records. SecurePitch turns a statement into a sealed dossier that shows the
              club&apos;s money and nothing else.
            </p>
            <div className="flex flex-wrap gap-2">
              <a href="#try" className={buttonVariants({ size: "lg" })}>
                Try to break the seal
              </a>
              <Link href="/guide" className={buttonVariants({ size: "lg", variant: "outline" })}>
                How to try it
              </Link>
            </div>
          </div>
          <StatementDemo />
        </section>

        <section id="try" className="scroll-mt-16 border-y bg-card/60">
          <div className={`${SECTION} flex flex-col gap-6`}>
            <div className="flex max-w-prose flex-col gap-2">
              <h2 className="text-4xl leading-tight font-bold">Change one shilling</h2>
              <p className="text-muted-foreground">
                Once a dossier is sealed, nobody can quietly edit it: not the coach, and not us. Change
                any amount below. This is a real SHA-256 fingerprint, worked out in your browser.
              </p>
            </div>
            <TamperDemo />
          </div>
        </section>

        <section id="how" className={`${SECTION} scroll-mt-16 flex flex-col gap-6`}>
          <h2 className="text-4xl leading-tight font-bold">From statement to sponsor</h2>
          <ol className="grid gap-x-6 gap-y-5 sm:grid-cols-2 lg:grid-cols-5">
            {STEPS.map(([title, text], i) => (
              <li key={title} className="flex flex-col gap-1 border-t-2 border-primary pt-3">
                <span className="font-mono text-xs text-muted-foreground">{i + 1} of {STEPS.length}</span>
                <h3 className="text-2xl font-bold">{title}</h3>
                <p className="text-sm text-muted-foreground">{text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="install" className="scroll-mt-16 border-t bg-card/60">
          <div className={`${SECTION} grid items-start gap-6 lg:grid-cols-2`}>
            <div className="flex flex-col gap-2">
              <h2 className="text-4xl leading-tight font-bold">Keep it on your phone</h2>
              <p className="max-w-prose text-muted-foreground">
                SecurePitch installs straight from this site, with no app store. It needs a connection
                to work, because statements and ledgers are never kept on the device.
              </p>
            </div>
            <InstallApp />
          </div>
        </section>
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-muted-foreground">
          <span>Sponsors don&apos;t need an account. Open the link or QR code on the dossier.</span>
          <Link href="/guide" className="inline-block py-2 underline underline-offset-4">
            First time here? Read the guide
          </Link>
        </div>
      </footer>
    </div>
  );
}
