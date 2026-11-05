// Tagging a parsed statement: which rows are club rows, and their category. Untagged rows are
// personal: they never leave the coach's browser and the engine drops them.

export type Direction = "in" | "out";
export type MatchStatus = "verified" | "number_only" | "ambiguous" | "unmatched";

export type Transaction = {
  tx: string;
  ts: string;
  dir: Direction;
  amount_cents: number;
  fee_cents: number;
  kind: string;
  details: string;
  match: { status: MatchStatus; player_code: string | null } | null;
};

export type Batch = {
  day: string;
  amount_cents: number;
  size: number;
  verified: number;
  fixture_code: string | null;
  txs: string[];
};

export type IntegrityCheck = { passed: boolean; weight_bp: number; detail: string };

export type ParsedStatement = {
  source_sha256: string;
  period: { from: string | null; to: string | null };
  rows_total: number;
  verification_code: string | null;
  integrity: { score_bp: number; checks: Record<string, IntegrityCheck> };
  transactions: Transaction[];
  roster_size: number;
  batches: Batch[];
};

export const CATEGORY_LABEL = {
  transport: "Transport",
  allowance: "Allowance",
  meals: "Meals",
  kit: "Kit",
  ground_hire: "Ground hire",
  other: "Other club spending",
  income: "Club income",
} as const;

export type Category = keyof typeof CATEGORY_LABEL;
export type Tags = Record<string, Category>;

/** Categories a row can take: money in can only be club income, money out anything else. */
export function categoriesFor(dir: Direction): Category[] {
  return dir === "in"
    ? ["income"]
    : ["transport", "allowance", "meals", "kit", "ground_hire", "other"];
}

/** Tag (or with category null, untag) every row of a matchday batch. */
export function tagBatch(tags: Tags, batch: Batch, category: Category | null): Tags {
  const next = { ...tags };
  for (const tx of batch.txs) {
    if (category) next[tx] = category;
    else delete next[tx];
  }
  return next;
}

export function setTag(tags: Tags, tx: string, category: Category | null): Tags {
  const next = { ...tags };
  if (category) next[tx] = category;
  else delete next[tx];
  return next;
}

export type Summary = { tagged: number; personal: number; incomeCents: number; spentCents: number };

/** Totals as the dossier will show them: spending includes each transfer's M-Pesa fee. */
export function summarize(transactions: Transaction[], tags: Tags): Summary {
  const s: Summary = { tagged: 0, personal: 0, incomeCents: 0, spentCents: 0 };
  for (const t of transactions) {
    if (!tags[t.tx]) {
      s.personal += 1;
      continue;
    }
    s.tagged += 1;
    if (t.dir === "in") s.incomeCents += t.amount_cents;
    else s.spentCents += t.amount_cents + t.fee_cents;
  }
  return s;
}

/** What the engine receives: only receipt numbers and categories, never amounts. */
export function tagPayload(transactions: Transaction[], tags: Tags) {
  return transactions
    .filter((t) => tags[t.tx])
    .map((t) => ({ tx: t.tx, category: tags[t.tx] }));
}

/** How a stored ledger row's counterparty is shown. Hashed references are never displayed. */
export function counterpartyLabel(cpType: string, cpRef: string): string {
  switch (cpType) {
    case "player":
      return `Player ${cpRef}`;
    case "till":
      return `Till ${cpRef}`;
    case "paybill":
      return `Paybill ${cpRef}`;
    default:
      return "Someone not on the roster";
  }
}

const KES = new Intl.NumberFormat("en-KE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatKes(cents: number): string {
  return `KES ${KES.format(cents / 100)}`;
}

/** "2026-10-17T07:15:00+03:00" -> "17 Oct, 07:15", in Kenyan time whatever the viewer's zone. */
export function formatWhen(iso: string): string {
  return new Intl.DateTimeFormat("en-KE", {
    timeZone: "Africa/Nairobi",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}
