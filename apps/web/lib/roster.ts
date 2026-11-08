// Roster import: checks a player the way the engine does, and reads a pasted or uploaded CSV.
// Phone numbers are only ever sent to the engine, which keeps keyed hashes and never stores them.

export const MAX_PLAYERS = 200;

export type PlayerInput = {
  full_name: string;
  phone: string;
  fkf_id: string | null;
  is_minor: boolean;
  consent_by: string;
  consent_at: string;
};

type One = { ok: true; player: PlayerInput } | { ok: false; error: string };
type Many = { ok: true; players: PlayerInput[] } | { ok: false; error: string };

const str = (v: unknown) => (typeof v === "string" ? v.trim() : "");

// The same rule as the engine's normalise_phone (services/engine/app/roster/keys.py). The engine
// stays the authority: this only catches mistakes before Save.
const KENYAN_MOBILE = /^(?:\+?254|0)?[17]\d{8}$/;
const cleanPhone = (phone: string) => phone.replace(/[\s\-().]/g, "");

/** The nine digits that identify a number, however it was typed (0712..., +254712..., 712...). */
export function phoneId(phone: string): string {
  return cleanPhone(phone).replace(/^\+?254/, "").replace(/^0/, "");
}

export function duplicateOf(existing: PlayerInput[], phone: string): PlayerInput | undefined {
  const id = phoneId(phone);
  return existing.find((p) => phoneId(p.phone) === id);
}

// Accepts what a person types (YYYY-MM-DD) and exactly what this code produces from it, because the browser and then the route both check the same player.
const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})(?:T00:00:00\+03:00)?$/;
// Nairobi is UTC+3, so today's date there can already be "tomorrow" in UTC.
const NAIROBI_AHEAD_MS = 3 * 60 * 60 * 1000;

function consentDate(raw: string): { ok: true; at: string } | { ok: false; error: string } {
  const m = DATE_ONLY.exec(raw);
  const d = m && new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  if (
    !m ||
    !d ||
    d.getUTCFullYear() !== +m[1] ||
    d.getUTCMonth() !== +m[2] - 1 ||
    d.getUTCDate() !== +m[3]
  ) {
    return { ok: false, error: "Enter the consent date as YYYY-MM-DD." };
  }
  if (d.getTime() > Date.now() + NAIROBI_AHEAD_MS) {
    return { ok: false, error: "The consent date can't be in the future." };
  }
  return { ok: true, at: `${m[1]}-${m[2]}-${m[3]}T00:00:00+03:00` };
}

export function validatePlayer(raw: unknown): One {
  if (!raw || typeof raw !== "object") return { ok: false, error: "Not a player." };
  const r = raw as Record<string, unknown>;
  const full_name = str(r.full_name);
  const phone = str(r.phone);
  const fkf_id = str(r.fkf_id);
  const consent_by = str(r.consent_by);

  if (full_name.length < 2 || full_name.length > 120) {
    return { ok: false, error: "The name must be 2 to 120 characters." };
  }
  if (!phone || phone.length > 32 || !KENYAN_MOBILE.test(cleanPhone(phone))) {
    return { ok: false, error: "Enter a Kenyan mobile number: 07..., 01..., 2547... or +2547..." };
  }
  if (fkf_id.length > 40) return { ok: false, error: "The FKF number is too long." };
  if (consent_by.length < 2 || consent_by.length > 120) {
    return { ok: false, error: "Say who gave consent: the player, or a parent if under 18." };
  }
  const when = consentDate(str(r.consent_at));
  if (!when.ok) return { ok: false, error: when.error };

  const m = r.is_minor;
  const is_minor =
    m === true || (typeof m === "string" && ["true", "yes", "y", "1"].includes(m.trim().toLowerCase()));

  // Only these fields ever go to the engine.
  return {
    ok: true,
    player: { full_name, phone, fkf_id: fkf_id || null, is_minor, consent_by, consent_at: when.at },
  };
}

export function validatePlayers(raw: unknown): Many {
  if (!Array.isArray(raw) || raw.length === 0) return { ok: false, error: "Add at least one player." };
  if (raw.length > MAX_PLAYERS) {
    return { ok: false, error: `A roster can have up to ${MAX_PLAYERS} players at a time.` };
  }
  const players: PlayerInput[] = [];
  for (let i = 0; i < raw.length; i++) {
    const r = validatePlayer(raw[i]);
    if (!r.ok) return { ok: false, error: `Player ${i + 1}: ${r.error}` };
    const dup = duplicateOf(players, r.player.phone);
    if (dup) return { ok: false, error: `Player ${i + 1}: same phone number as ${dup.full_name}.` };
    players.push(r.player);
  }
  return { ok: true, players };
}

/** Show only the last three digits, so the screen never displays a full number. */
export function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  return digits.length < 3 ? "***" : `*** *** ${digits.slice(-3)}`;
}

function splitCsvLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (quoted) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else quoted = false;
      } else cur += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") {
      out.push(cur);
      cur = "";
    } else cur += c;
  }
  out.push(cur);
  return out;
}

const HEADERS: Record<string, string> = {
  name: "full_name",
  full_name: "full_name",
  phone: "phone",
  phone_number: "phone",
  fkf: "fkf_id",
  fkf_id: "fkf_id",
  is_minor: "is_minor",
  minor: "is_minor",
  under_18: "is_minor",
  consent_by: "consent_by",
  consent_at: "consent_at",
};

// "Full Name", "Phone Number" and "Is Minor" (as exported from Excel or Sheets) all work.
const headerKey = (h: string) => h.trim().toLowerCase().replace(/[\s-]+/g, "_");

export function parseRosterCsv(text: string): { players: PlayerInput[]; errors: string[] } {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/);
  const players: PlayerInput[] = [];
  const first = lines.findIndex((l) => l.trim() !== "");
  if (first === -1) return { players, errors: ["The file is empty."] };

  const columns = splitCsvLine(lines[first]).map((h) => HEADERS[headerKey(h)] ?? "");
  // is_minor is required: without it every player would silently count as an adult.
  const missing = ["full_name", "phone", "is_minor", "consent_by", "consent_at"].filter(
    (c) => !columns.includes(c),
  );
  if (missing.length > 0) return { players, errors: [`Missing columns: ${missing.join(", ")}.`] };

  const errors: string[] = [];
  for (let i = first + 1; i < lines.length; i++) {
    if (!lines[i].trim()) continue;
    const cells = splitCsvLine(lines[i]);
    const raw: Record<string, string> = {};
    columns.forEach((c, k) => {
      if (c) raw[c] = cells[k] ?? "";
    });
    const r = validatePlayer(raw);
    if (!r.ok) {
      errors.push(`Row ${i + 1}: ${r.error}`);
      continue;
    }
    const dup = duplicateOf(players, r.player.phone);
    if (dup) errors.push(`Row ${i + 1}: same phone number as ${dup.full_name}.`);
    else players.push(r.player);
  }
  return { players, errors };
}
