import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { UUID_RE } from "@/lib/club-guard";
import { createClient } from "@/lib/supabase/server";
import { CATEGORY_LABEL, type Category, counterpartyLabel, formatKes, formatWhen } from "@/lib/tagging";

export const metadata: Metadata = { title: "Dossier · SecurePitch" };

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  submitted: "Submitted for approval",
  approved: "Approved",
  sealed: "Sealed",
  revoked: "Revoked",
};

type Dossier = {
  id: string;
  club_id: string;
  status: string;
  period_from: string;
  period_to: string;
  rows_total: number | null;
  integrity: { score_bp?: number } | null;
  clubs: { name: string } | null;
};

type Item = {
  tx: string;
  ts: string;
  amt_cents: number;
  fee_cents: number;
  dir: "in" | "out";
  category: Category;
  cp_type: string;
  cp_ref: string;
  fixture_code: string | null;
};

export default async function DossierPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID_RE.test(id)) notFound();

  // Read with the user's own session: row-level security shows only their clubs' dossiers.
  const supabase = await createClient();
  const { data } = await supabase
    .from("dossiers")
    .select("id, club_id, status, period_from, period_to, rows_total, integrity, clubs(name)")
    .eq("id", id)
    .maybeSingle();
  const dossier = data as unknown as Dossier | null;
  if (!dossier) notFound();

  const { data: itemRows, error } = await supabase
    .from("dossier_items")
    .select("tx, ts, amt_cents, fee_cents, dir, category, cp_type, cp_ref, fixture_code")
    .eq("dossier_id", id)
    .order("ts");
  const items = (itemRows ?? []) as Item[];
  const income = items.filter((i) => i.dir === "in").reduce((s, i) => s + i.amt_cents, 0);
  const spent = items
    .filter((i) => i.dir === "out")
    .reduce((s, i) => s + i.amt_cents + i.fee_cents, 0);
  const score = dossier.integrity?.score_bp;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
          ← {dossier.clubs?.name ?? "Your clubs"}
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">
          Dossier {dossier.period_from} to {dossier.period_to}
        </h1>
        <p className="text-sm text-muted-foreground">
          {STATUS_LABEL[dossier.status] ?? dossier.status}
          {score !== undefined && ` · statement integrity ${(score / 100).toFixed(0)}%`}
        </p>
      </div>

      <Card>
        <CardContent>
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">Club rows</dt>
              <dd className="font-medium tabular-nums">{items.length}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Statement rows</dt>
              <dd className="font-medium tabular-nums">{dossier.rows_total ?? "–"}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Club income</dt>
              <dd className="font-medium tabular-nums">{formatKes(income)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Club spending (with fees)</dt>
              <dd className="font-medium tabular-nums">{formatKes(spent)}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      {dossier.status === "draft" && (
        <Card>
          <CardHeader>
            <CardTitle>Next: approvals</CardTitle>
            <CardDescription>
              This draft holds only the rows you tagged; the rest of the statement was not
              stored. To change the tags, upload the statement again: saving replaces this
              draft. Submitting with your passkey comes next.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              href={`/club/${dossier.club_id}/statements/new`}
              className="text-sm font-medium underline-offset-4 hover:underline"
            >
              Upload the statement again
            </Link>
          </CardContent>
        </Card>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold tracking-tight">Ledger</h2>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            Couldn&apos;t load the ledger. Refresh the page.
          </p>
        ) : (
          <ul className="flex flex-col divide-y rounded-xl border">
            {items.map((i) => (
              <li key={i.tx} className="flex items-start justify-between gap-3 p-3 text-sm">
                <div className="min-w-0">
                  <p className="font-medium">
                    {CATEGORY_LABEL[i.category] ?? i.category} ·{" "}
                    {counterpartyLabel(i.cp_type, i.cp_ref)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatWhen(i.ts)} · {i.tx}
                    {i.fixture_code && ` · ${i.fixture_code}`}
                  </p>
                </div>
                <div className="text-right tabular-nums">
                  <p className={i.dir === "in" ? "text-emerald-700 dark:text-emerald-400" : ""}>
                    {i.dir === "in" ? "+" : "−"}
                    {formatKes(i.amt_cents)}
                  </p>
                  {i.fee_cents > 0 && (
                    <p className="text-xs text-muted-foreground">fee {formatKes(i.fee_cents)}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
