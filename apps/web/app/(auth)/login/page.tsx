import type { Metadata } from "next";
import { Suspense } from "react";

import { Brand } from "@/components/brand";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in · SecurePitch" };

const FACTS = [
  "Statements are read in memory and never stored.",
  "Only the rows you tag as club money are kept.",
  "Two officials approve each dossier with their own passkeys.",
  "Sponsors check every signature themselves.",
];

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh lg:grid-cols-2">
      <section className="hidden flex-col justify-between gap-12 border-t-4 border-seal bg-pitch p-12 text-pitch-foreground lg:flex">
        <Brand inverted />
        <div className="flex flex-col gap-8">
          <p className="max-w-lg font-heading text-6xl leading-[1.02] font-bold text-balance">
            Club money on the record. Personal spending off it.
          </p>
          <ul className="flex max-w-md flex-col gap-2.5 text-pitch-foreground/85">
            {FACTS.map((fact) => (
              <li key={fact}>{fact}</li>
            ))}
          </ul>
        </div>
        <p className="text-sm text-pitch-foreground/70">
          Sponsors don&apos;t need an account. Open the link or QR code on the dossier.
        </p>
      </section>

      <section className="flex flex-col justify-center gap-8 px-4 py-10 sm:px-8">
        <div className="mx-auto flex w-full max-w-sm flex-col gap-8">
          <Brand className="lg:hidden" />
          <div className="flex flex-col gap-1">
            <h1 className="text-4xl leading-tight font-bold">Sign in</h1>
            <p className="text-sm text-muted-foreground">
              For club managers, treasurers and captains.
            </p>
          </div>
          <Suspense>
            <LoginForm />
          </Suspense>
        </div>
      </section>
    </main>
  );
}
