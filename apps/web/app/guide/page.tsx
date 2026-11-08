import { Download, ExternalLink, KeyRound } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Brand } from "@/components/brand";
import { InstallApp } from "@/components/install-app";
import { buttonVariants } from "@/components/ui/button";

export const metadata: Metadata = { title: "How to try SecurePitch" };

// A sealed dossier made for first-time visitors. Set once it's sealed on this domain.
const DEMO_DOSSIER_ID: string | null = null;

const TRY_STEPS: [string, React.ReactNode][] = [
  [
    "Sign in as the manager",
    "Use the test manager account you were given. All the data in the test club is made up.",
  ],
  [
    "Add a passkey",
    <>
      Open <strong>Passkeys</strong> at the top of the page and add one. It uses this device&apos;s
      fingerprint, face or PIN. Open this site in Chrome or Safari, as passkeys may not work in a
      browser inside another app.
    </>,
  ],
  [
    "Upload the sample statement",
    <>
      Download it with the button above, choose <strong>Upload a statement</strong>, and enter the password{" "}
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono">123456</code>.
    </>,
  ],
  [
    "Tag the club payments",
    "Tap the button that tags the matchday payments, choose a category for any others, and save the draft. Anything left as Personal is never stored.",
  ],
  ["Sign it", "Open the draft, choose Review and sign, and confirm with your passkey."],
  [
    "Sign as the treasurer",
    "Sign out, sign in as the test treasurer, add a passkey for that account, and sign. The dossier seals straight away.",
  ],
  [
    "Download the PDF and verify it",
    "Download the sealed PDF, scan its QR code or open the sponsor page, and upload the PDF to the check on that page.",
  ],
];

export default function GuidePage() {
  return (
    <div className="min-h-dvh">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-2.5">
          <Link href="/" aria-label="SecurePitch home" className="inline-flex min-h-10 items-center">
            <Brand />
          </Link>
          <Link href="/login" className={buttonVariants({ size: "sm" })}>
            Sign in
          </Link>
        </div>
      </header>

      <main className="mx-auto flex max-w-3xl flex-col gap-10 px-4 py-8 sm:py-12">
        <div className="flex flex-col gap-2">
          <h1 className="text-4xl leading-tight font-bold sm:text-5xl">How to try SecurePitch</h1>
          <p className="max-w-prose text-muted-foreground">
            A coach&apos;s M-Pesa statement goes in. A sealed dossier that shows a sponsor the club&apos;s
            money, and nothing personal, comes out. There are two ways to see it.
          </p>
        </div>

        <section className="flex flex-col gap-3">
          <h2 className="text-3xl font-bold">See the sponsor&apos;s side</h2>
          <p className="text-muted-foreground">
            No account needed. This is what a sponsor gets: every signature is checked in your own
            browser.
          </p>
          {DEMO_DOSSIER_ID ? (
            <Link href={`/v/${DEMO_DOSSIER_ID}`} className={`${buttonVariants()} sm:self-start`}>
              <ExternalLink aria-hidden />
              Open a sealed dossier
            </Link>
          ) : (
            <p className="text-sm text-muted-foreground">
              The link to a sample dossier is in the access details you received.
            </p>
          )}
        </section>

        <section className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h2 className="text-3xl font-bold">Run the whole journey</h2>
            <p className="text-muted-foreground">
              About five minutes, on a phone or laptop that supports passkeys.
            </p>
          </div>
          <a
            href="/demo/synthetic-statement.pdf"
            download
            className={`${buttonVariants({ variant: "outline" })} sm:self-start`}
          >
            <Download aria-hidden />
            Download the sample statement
          </a>
          <ol className="flex flex-col divide-y rounded-xl border bg-card">
            {TRY_STEPS.map(([title, text], i) => (
              <li key={title} className="flex gap-3 p-4 text-sm">
                <span
                  aria-hidden
                  className="grid size-6 shrink-0 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
                >
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <h3 className="font-sans text-sm font-semibold">{title}</h3>
                  <p className="text-muted-foreground">{text}</p>
                </div>
              </li>
            ))}
          </ol>
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <KeyRound aria-hidden className="mt-0.5 size-4 shrink-0" />
            Two people sign every dossier, so both test accounts are needed to reach the seal.
          </p>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-3xl font-bold">Install the app</h2>
          <InstallApp />
        </section>
      </main>
    </div>
  );
}
