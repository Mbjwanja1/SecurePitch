"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  MAX_PLAYERS,
  type PlayerInput,
  duplicateOf,
  maskPhone,
  parseRosterCsv,
  validatePlayer,
} from "@/lib/roster";

// DRAFT WORDING: replace with the consent text from docs/DPIA.md when it is ready (task J5).
const CONSENT_TEXT =
  "By adding a player you confirm that the player, or a parent or guardian if the player is under 18, " +
  "agreed that SecurePitch may keep their name and a coded form of their phone number so that club " +
  "payments can be matched to them. The phone number itself is not kept.";

type Saved = { added?: number; updated?: number; rejected?: unknown[]; error?: string };
type Result = { saved: number; problems: string[] };

// The local (Nairobi) date as YYYY-MM-DD. The UTC date is yesterday between midnight and 03:00.
const today = () => new Date().toLocaleDateString("en-CA");

const EMPTY = { full_name: "", phone: "", fkf_id: "", is_minor: false, consent_by: "" };

function reasonOf(item: unknown): string {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    const o = item as Record<string, unknown>;
    const reason = o.reason ?? o.message ?? o.error;
    if (typeof reason === "string") return reason;
  }
  return "Not saved.";
}

export function RosterForm({ clubId }: { clubId: string }) {
  const [players, setPlayers] = useState<PlayerInput[]>([]);
  const [reasons, setReasons] = useState<Map<PlayerInput, string>>(new Map());
  const [fields, setFields] = useState(EMPTY);
  const [consentAt, setConsentAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);

  // Set after the page loads, so the server and the browser can't disagree about "today".
  useEffect(() => {
    setConsentAt(today());
  }, []);

  function addPlayer() {
    setError(null);
    setResult(null);
    if (players.length >= MAX_PLAYERS) {
      setError(`A roster can have up to ${MAX_PLAYERS} players at a time.`);
      return;
    }
    const r = validatePlayer({ ...fields, consent_at: consentAt });
    if (!r.ok) {
      setError(r.error);
      return;
    }
    const dup = duplicateOf(players, r.player.phone);
    if (dup) {
      setError(`Same phone number as ${dup.full_name}.`);
      return;
    }
    setPlayers((p) => [...p, r.player]);
    setFields(EMPTY);
  }

  async function onCsv(file: File | undefined) {
    if (!file) return;
    setError(null);
    setResult(null);
    const parsed = parseRosterCsv(await file.text());
    const next = [...players];
    const found = [...parsed.errors];
    for (const p of parsed.players) {
      const dup = duplicateOf(next, p.phone);
      if (dup) found.push(`${p.full_name}: same phone number as ${dup.full_name}.`);
      else next.push(p);
    }
    if (next.length > MAX_PLAYERS) {
      next.length = MAX_PLAYERS;
      found.push(`Only the first ${MAX_PLAYERS} players were added; import the rest in a second batch.`);
    }
    setNotes(found);
    setPlayers(next);
  }

  async function save() {
    setBusy(true);
    setError(null);
    const sent = players;
    try {
      const res = await fetch(`/api/club/${clubId}/roster`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ players: sent }),
      });
      const json = (await res.json().catch(() => null)) as Saved | null;
      if (!res.ok || !json) {
        setError(json?.error ?? "Could not save the roster. Try again.");
        return;
      }

      // "row" is the 1-based position in the list we sent. Keep the rejected players on screen,
      // with their reason, and clear only the ones that saved.
      const rejected = Array.isArray(json.rejected) ? json.rejected : [];
      const bad = new Map<number, string>();
      for (const item of rejected) {
        const row = Number((item as { row?: unknown } | null)?.row);
        if (Number.isInteger(row) && row >= 1 && row <= sent.length) bad.set(row - 1, reasonOf(item));
      }
      const problems = [...bad].map(([i, why]) => `${sent[i].full_name}: ${why}`);
      const unmatched = rejected.length - bad.size;
      if (unmatched > 0) problems.push(`${unmatched} more not saved; the engine did not say which.`);

      setReasons(new Map([...bad].map(([i, why]) => [sent[i], why] as [PlayerInput, string])));
      // If a rejection can't be matched to a player, keep everyone so nobody is lost.
      setPlayers(unmatched > 0 ? sent : sent.filter((_, i) => bad.has(i)));
      setResult({ saved: (Number(json.added) || 0) + (Number(json.updated) || 0), problems });
      setNotes([]);
    } catch {
      setError("No connection. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Consent (draft wording)</CardTitle>
          <CardDescription>{CONSENT_TEXT}</CardDescription>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Add a player</CardTitle>
          <CardDescription>The phone number is never shown again once it is saved.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="full_name">Full name</Label>
            <Input
              id="full_name"
              value={fields.full_name}
              onChange={(e) => setFields({ ...fields, full_name: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="phone">Phone number</Label>
            <Input
              id="phone"
              inputMode="tel"
              autoComplete="off"
              value={fields.phone}
              onChange={(e) => setFields({ ...fields, phone: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="fkf_id">FKF licence number (optional)</Label>
            <Input
              id="fkf_id"
              value={fields.fkf_id}
              onChange={(e) => setFields({ ...fields, fkf_id: e.target.value })}
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={fields.is_minor}
              onChange={(e) => setFields({ ...fields, is_minor: e.target.checked })}
            />
            This player is under 18
          </label>
          <div className="flex flex-col gap-1">
            <Label htmlFor="consent_by">
              {fields.is_minor ? "Parent or guardian who gave consent" : "Who gave consent"}
            </Label>
            <Input
              id="consent_by"
              value={fields.consent_by}
              onChange={(e) => setFields({ ...fields, consent_by: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="consent_at">Date consent was given</Label>
            <Input
              id="consent_at"
              type="date"
              value={consentAt}
              onChange={(e) => setConsentAt(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button type="button" onClick={addPlayer}>
              Add to list
            </Button>
            <label className="text-sm">
              <span className="mr-2">or import a CSV</span>
              <input
                type="file"
                accept=".csv,text/csv"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = ""; // so choosing the same file again (after fixing it) re-runs
                  void onCsv(file);
                }}
              />
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            CSV columns: full_name, phone, fkf_id (optional), is_minor, consent_by, consent_at
            (YYYY-MM-DD). Headings such as &quot;Full Name&quot; or &quot;Phone Number&quot; also work.
          </p>
        </CardContent>
      </Card>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {notes.length > 0 && (
        <ul role="alert" className="list-disc pl-5 text-sm text-destructive">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}

      {result && (
        <div role="status" className="rounded-xl border p-4 text-sm">
          <p className="font-medium">{result.saved} players saved.</p>
          {result.problems.length > 0 && (
            <>
              <p className="mt-2">These players were not saved. They are still in the list below.</p>
              <ul className="mt-1 list-disc pl-5 text-destructive">
                {result.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}

      {players.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Ready to save: {players.length}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <ul className="flex flex-col divide-y rounded-xl border text-sm">
              {players.map((p, i) => (
                <li key={`${p.full_name}-${i}`} className="flex items-center justify-between gap-3 p-3">
                  <span>
                    {p.full_name}
                    <span className="text-muted-foreground">
                      {" "}
                      {maskPhone(p.phone)}
                      {p.is_minor ? " (under 18)" : ""}
                    </span>
                    {reasons.get(p) && <span className="block text-destructive">{reasons.get(p)}</span>}
                  </span>
                  <button
                    type="button"
                    className="text-muted-foreground hover:underline"
                    onClick={() => setPlayers((all) => all.filter((_, k) => k !== i))}
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
            <Button type="button" onClick={() => void save()} disabled={busy}>
              {busy ? "Saving..." : `Save ${players.length} players`}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
