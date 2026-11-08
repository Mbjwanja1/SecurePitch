import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UUID_RE } from "@/lib/club-guard";
import { fingerprint } from "@/lib/passkey-client";
import { createClient } from "@/lib/supabase/server";
import { CATEGORY_LABEL, type Category, formatKes, formatWhen } from "@/lib/tagging";
import { isDisplayable } from "@/lib/verify";

import { VerifyPanel } from "./verify-panel";
import { PdfCheck } from "./pdf-check";

// Public: sponsors open this from the dossier's link or QR code, without an account. Dossier
// links aren't listed anywhere, so keep them out of search engines too.
export const metadata: Metadata = {
  title: "Verify a dossier · SecurePitch",
  robots: { index: false, follow: false },
};

export default async function VerifyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID_RE.test(id)) notFound();

  // public_dossier() returns only sealed or revoked dossiers, and only their signed contents.
  const supabase = await createClient();
  const { data } = await supabase.rpc("public_dossier", { p_id: id });
  if (!data) notFound();
  if (!isDisplayable(data)) {
    return (
      <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
        <p className="text-sm font-semibold tracking-tight">SecurePitch · dossier verification</p>
        <div role="alert" className="rounded-xl border border-destructive/50 bg-destructive/10 p-4">
          <p className="font-semibold text-destructive">Not authentic</p>
          <p className="text-sm">
            This dossier&apos;s record is damaged and can&apos;t be checked. Don&apos;t rely on it.
          </p>
        </div>
      </main>
    );
  }

  const record = data;
  const p = record.payload;
  // Income first, then spending categories in a fixed order.
  const totals = Object.entries(p.totals_cents).sort(([a], [b]) =>
    a === "income" ? -1 : b === "income" ? 1 : a < b ? -1 : 1,
  );

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-8">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-semibold tracking-tight">SecurePitch · dossier verification</p>
        <h1 className="text-2xl font-semibold tracking-tight">{p.club.name}</h1>
        <p className="text-sm text-muted-foreground">
          Club finances {p.period.from} to {p.period.to} · sealed {formatWhen(p.sealed_at)}
        </p>
      </div>

      {record.status === "revoked" && (
        <div
          role="alert"
          className="rounded-xl border border-destructive/50 bg-destructive/10 p-4 text-sm"
        >
          <p className="font-semibold text-destructive">This dossier was revoked</p>
          <p>
            {record.revoked_at && `${formatWhen(record.revoked_at)}: `}
            {record.revoke_reason ?? "No reason given."} Don&apos;t rely on it.
          </p>
        </div>
      )}

      <VerifyPanel record={record} />
      <PdfCheck expected={record.pdf_sha256} />

      <Card>
        <CardHeader>
          <CardTitle>What the club declared</CardTitle>
          <CardDescription>
            Exactly what the manager and the treasurer signed. The coach kept{" "}
            {p.rows_total - p.rows_disclosed} personal transactions out of the dossier.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4 text-sm">
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Club rows</dt>
              <dd className="font-medium tabular-nums">
                {p.rows_disclosed} of {p.rows_total}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Statement integrity</dt>
              <dd className="font-medium tabular-nums">
                {(p.integrity.score_bp / 100).toFixed(0)}%
              </dd>
            </div>
            <div className="col-span-2">
              <dt className="text-muted-foreground">Ledger fingerprint</dt>
              <dd className="font-mono font-medium">{fingerprint(p.merkle_root)}</dd>
            </div>
          </dl>
          <dl className="flex flex-col divide-y rounded-xl border">
            {totals.map(([category, cents]) => (
              <div key={category} className="flex justify-between gap-3 p-3">
                <dt>
                  {CATEGORY_LABEL[category as Category] ?? category}
                  {category !== "income" && (
                    <span className="text-muted-foreground"> (with fees)</span>
                  )}
                </dt>
                <dd className="tabular-nums">{formatKes(cents)}</dd>
              </div>
            ))}
          </dl>
          {p.planned_spends.length > 0 && (
            <div className="flex flex-col gap-2">
              <p className="font-medium">Planned spending of sponsor money</p>
              <ul className="flex flex-col divide-y rounded-xl border">
                {p.planned_spends.map((s, i) => (
                  <li key={i} className="flex justify-between gap-3 p-3">
                    <span>
                      {s.purpose} · {s.supplier}
                      <span className="text-muted-foreground"> · till {s.till}</span>
                    </span>
                    <span className="tabular-nums">{formatKes(s.amt)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
