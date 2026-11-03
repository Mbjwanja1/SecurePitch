"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { checkStatementFile } from "@/lib/statement-upload";
import {
  type Batch,
  type Category,
  CATEGORY_LABEL,
  categoriesFor,
  formatKes,
  formatWhen,
  type ParsedStatement,
  setTag,
  summarize,
  tagBatch,
  tagPayload,
  type Tags,
  type Transaction,
} from "@/lib/tagging";

const CHECK_LABEL: Record<string, string> = {
  balance_chain: "Balances add up row by row",
  summary_match: "Totals match the statement's own summary",
  never_resaved: "Never re-saved or edited after M-Pesa produced it",
  no_annotations_or_forms: "No added notes or form fields",
  producer_baseline: "Produced the way genuine M-Pesa statements are",
};

type Filter = "all" | "out" | "in" | "tagged";
const FILTER_LABEL: Record<Filter, string> = {
  all: "All",
  out: "Money out",
  in: "Money in",
  tagged: "Tagged",
};

// The statement file and password stay in this page's memory only: they're sent again when the
// draft is saved (the engine re-reads the statement) and are gone when the page closes.
export function StatementTagger({ clubId }: { clubId: string }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [password, setPassword] = useState("");
  const [parsed, setParsed] = useState<ParsedStatement | null>(null);
  const [tags, setTags] = useState<Tags>({});
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);

  const summary = useMemo(
    () => (parsed ? summarize(parsed.transactions, tags) : null),
    [parsed, tags],
  );

  function form(extra?: Record<string, string>): FormData {
    const data = new FormData();
    data.set("statement", file as File);
    data.set("password", password);
    for (const [k, v] of Object.entries(extra ?? {})) data.set(k, v);
    return data;
  }

  async function post(path: string, body: FormData) {
    const response = await fetch(`/api/club/${clubId}/${path}`, { method: "POST", body });
    const json = await response.json().catch(() => ({}));
    return { ok: response.ok, json };
  }

  async function upload(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    const problem = checkStatementFile(file);
    if (problem) return setError(problem.message);
    setBusy(true);
    setError(null);
    try {
      const { ok, json } = await post("statements/parse", form());
      if (!ok) return setError(json.error ?? "The statement couldn't be read.");
      setParsed(json as ParsedStatement);
      setTags({});
    } catch {
      setError("Couldn't reach SecurePitch. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    if (!parsed) return;
    setBusy(true);
    setError(null);
    setProblems([]);
    try {
      const body = form({ tags: JSON.stringify(tagPayload(parsed.transactions, tags)) });
      const { ok, json } = await post("dossiers", body);
      if (!ok) {
        setError(json.error ?? "The draft couldn't be saved.");
        setProblems(Array.isArray(json.problems) ? json.problems : []);
        return;
      }
      router.push(`/dossiers/${json.dossier_id}`);
    } catch {
      setError("Couldn't reach SecurePitch. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  function startOver() {
    setParsed(null);
    setTags({});
    setFile(null);
    setPassword("");
    setError(null);
    setProblems([]);
  }

  if (!parsed || !summary) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Your M-Pesa statement</CardTitle>
          <CardDescription>
            Request a statement for the month in the M-Pesa app, then choose the PDF and enter
            the password from the SMS. The file is read in memory and never stored; only the
            rows you tag as club rows are saved.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={upload} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="statement">Statement PDF</Label>
              <Input
                id="statement"
                type="file"
                accept="application/pdf,.pdf"
                required
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="statement-password">Statement password</Label>
              <Input
                id="statement-password"
                type="password"
                autoComplete="off"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy || !file || !password}>
              {busy ? "Reading statement…" : "Read statement"}
            </Button>
          </form>
        </CardContent>
      </Card>
    );
  }

  const visible = parsed.transactions.filter((t) =>
    filter === "all" ? true : filter === "tagged" ? Boolean(tags[t.tx]) : t.dir === filter,
  );

  return (
    <div className="flex flex-col gap-6">
      <StatementSummary parsed={parsed} />

      {parsed.batches.length > 0 && (
        <section className="flex flex-col gap-3">
          <h2 className="text-lg font-semibold tracking-tight">Matchday payments</h2>
          {parsed.batches.map((b) => (
            <BatchCard
              key={`${b.day}-${b.amount_cents}`}
              batch={b}
              tagged={b.txs.every((tx) => tags[tx] === "transport")}
              onTag={(category) => setTags((t) => tagBatch(t, b, category))}
            />
          ))}
        </section>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold tracking-tight">Transactions</h2>
          <div className="flex flex-wrap gap-1" role="group" aria-label="Show">
            {(Object.keys(FILTER_LABEL) as Filter[]).map((f) => (
              <Button
                key={f}
                type="button"
                size="sm"
                variant={filter === f ? "secondary" : "ghost"}
                aria-pressed={filter === f}
                onClick={() => setFilter(f)}
              >
                {FILTER_LABEL[f]}
              </Button>
            ))}
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          Choose a category for each club transaction. Anything left as Personal stays on this
          page and is never saved.
        </p>
        {visible.length === 0 ? (
          <p className="text-sm text-muted-foreground">No transactions here.</p>
        ) : (
          <ul className="flex flex-col divide-y rounded-xl border">
            {visible.map((t) => (
              <TransactionRow
                key={t.tx}
                t={t}
                category={tags[t.tx] ?? null}
                onChange={(c) => setTags((all) => setTag(all, t.tx, c))}
              />
            ))}
          </ul>
        )}
      </section>

      <Card className="sticky bottom-4">
        <CardContent className="flex flex-col gap-3">
          <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
            <Stat label="Club rows" value={String(summary.tagged)} />
            <Stat label="Kept personal" value={String(summary.personal)} />
            <Stat label="Club income" value={formatKes(summary.incomeCents)} />
            <Stat label="Club spending (with fees)" value={formatKes(summary.spentCents)} />
          </dl>
          {error && (
            <div role="alert" className="text-sm text-destructive">
              <p>{error}</p>
              {problems.length > 0 && (
                <ul className="mt-1 list-disc pl-5">
                  {problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={save} disabled={busy || summary.tagged === 0}>
              {busy ? "Saving…" : "Save draft dossier"}
            </Button>
            <Button type="button" variant="ghost" onClick={startOver} disabled={busy}>
              Use a different statement
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </div>
  );
}

function StatementSummary({ parsed }: { parsed: ParsedStatement }) {
  const failed = Object.entries(parsed.integrity.checks).filter(([, c]) => !c.passed);
  const period =
    parsed.period.from && parsed.period.to
      ? `${parsed.period.from} to ${parsed.period.to}`
      : "Period not found";
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          Statement integrity {(parsed.integrity.score_bp / 100).toFixed(0)}%
        </CardTitle>
        <CardDescription>
          {period} · {parsed.rows_total} rows · {parsed.roster_size} players on the roster
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col gap-1 text-sm">
          {Object.entries(parsed.integrity.checks).map(([name, c]) => (
            <li key={name} className={c.passed ? "" : "text-destructive"}>
              {c.passed ? "✓" : "✗"} {CHECK_LABEL[name] ?? name}
              {!c.passed && c.detail ? ` (${c.detail})` : ""}
            </li>
          ))}
        </ul>
        {failed.length > 0 && (
          <p className="mt-3 text-sm text-muted-foreground">
            Sponsors see this score on the dossier. If you didn&apos;t change the file, download
            the statement again from M-Pesa and upload the new copy.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function BatchCard({
  batch,
  tagged,
  onTag,
}: {
  batch: Batch;
  tagged: boolean;
  onTag: (category: Category | null) => void;
}) {
  const day = new Intl.DateTimeFormat("en-KE", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "Africa/Nairobi",
  }).format(new Date(`${batch.day}T12:00:00+03:00`));
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>
          {day} · {batch.size} × {formatKes(batch.amount_cents)}
        </CardTitle>
        <CardDescription>
          {batch.verified} of {batch.size} matched to the roster by number and name
          {batch.fixture_code ? ` · fixture ${batch.fixture_code}` : " · no fixture on this day"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {tagged ? (
          <Button type="button" variant="outline" size="sm" onClick={() => onTag(null)}>
            Untag these {batch.size}
          </Button>
        ) : (
          <Button type="button" size="sm" onClick={() => onTag("transport")}>
            Tag all {batch.size} as transport
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

const MATCH_LABEL = {
  verified: "roster match",
  number_only: "number matches, name differs",
  ambiguous: "number shared by several players",
  unmatched: null,
} as const;

function TransactionRow({
  t,
  category,
  onChange,
}: {
  t: Transaction;
  category: Category | null;
  onChange: (c: Category | null) => void;
}) {
  const id = `category-${t.tx}`;
  const match = t.match ? MATCH_LABEL[t.match.status] : null;
  return (
    <li className={`flex flex-col gap-2 p-3 sm:flex-row sm:items-center ${category ? "bg-muted/40" : ""}`}>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium" title={t.details}>
          {t.details}
        </p>
        <p className="text-xs text-muted-foreground">
          {formatWhen(t.ts)} · {t.tx}
          {match && ` · ${t.match?.player_code ? `${t.match.player_code}, ` : ""}${match}`}
        </p>
      </div>
      <div className="flex items-center justify-between gap-3 sm:justify-end">
        <div className="text-right text-sm tabular-nums">
          <p className={t.dir === "in" ? "text-emerald-700 dark:text-emerald-400" : ""}>
            {t.dir === "in" ? "+" : "−"}
            {formatKes(t.amount_cents)}
          </p>
          {t.fee_cents > 0 && (
            <p className="text-xs text-muted-foreground">fee {formatKes(t.fee_cents)}</p>
          )}
        </div>
        <label htmlFor={id} className="sr-only">
          Category for {t.tx}
        </label>
        <select
          id={id}
          value={category ?? ""}
          onChange={(e) => onChange((e.target.value || null) as Category | null)}
          className="h-8 w-44 rounded-lg border border-input bg-background px-2 text-sm"
        >
          <option value="">Personal</option>
          {categoriesFor(t.dir).map((c) => (
            <option key={c} value={c}>
              {CATEGORY_LABEL[c]}
            </option>
          ))}
        </select>
      </div>
    </li>
  );
}
