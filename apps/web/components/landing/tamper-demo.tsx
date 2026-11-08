"use client";

import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { sha256, toHex } from "@/lib/crypto/encoding";

const ORIGINAL = [
  { label: "Kit · Till 5123456", amount: 12000 },
  { label: "Transport · Player P01", amount: 250 },
  { label: "Transport · Player P02", amount: 250 },
];

const fingerprint = (hex: string) => hex.slice(0, 16).toUpperCase().match(/.{4}/g)?.join(" ") ?? "";

async function hashRows(amounts: number[]): Promise<string> {
  const text = JSON.stringify(ORIGINAL.map((r, i) => [r.label, amounts[i]]));
  return toHex(await sha256(new TextEncoder().encode(text)));
}

// A real SHA-256 of these rows, computed in the visitor's browser: the principle behind the seal.
export function TamperDemo() {
  const originals = useMemo(() => ORIGINAL.map((r) => r.amount), []);
  const [amounts, setAmounts] = useState(originals);
  const [sealed, setSealed] = useState("");
  const [current, setCurrent] = useState("");

  useEffect(() => {
    void hashRows(originals).then(setSealed);
  }, [originals]);

  useEffect(() => {
    let live = true;
    void hashRows(amounts).then((h) => {
      if (live) setCurrent(h);
    });
    return () => {
      live = false;
    };
  }, [amounts]);

  const intact = amounts.every((a, i) => a === originals[i]);
  const Icon = intact ? ShieldCheck : ShieldAlert;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="flex flex-col divide-y rounded-xl border bg-card">
        {ORIGINAL.map((r, i) => (
          <label key={r.label} className="flex items-center justify-between gap-3 p-3 text-sm">
            <span className="min-w-0 font-medium">{r.label}</span>
            <span className="flex shrink-0 items-center gap-1.5 text-muted-foreground">
              KES
              <input
                type="number"
                inputMode="numeric"
                min={0}
                value={amounts[i]}
                aria-label={`Amount for ${r.label}`}
                onChange={(e) => {
                  const value = Number(e.target.value) || 0;
                  setAmounts((all) => all.map((a, k) => (k === i ? value : a)));
                }}
                className="h-11 w-28 rounded-lg border border-input bg-background px-2 text-right text-base text-foreground tabular-nums lg:h-9 lg:text-sm"
              />
            </span>
          </label>
        ))}
      </div>

      <div
        aria-live="polite"
        className={
          intact
            ? "flex flex-col justify-between gap-4 rounded-xl border-t-4 border-seal bg-pitch p-5 text-pitch-foreground transition-colors duration-300"
            : "flex flex-col justify-between gap-4 rounded-xl border border-destructive/40 bg-destructive/10 p-5 transition-colors duration-300"
        }
      >
        <div className="flex items-center gap-3">
          <Icon aria-hidden className={`size-8 shrink-0 ${intact ? "text-seal" : "text-destructive"}`} />
          <p className={`font-heading text-4xl leading-none font-bold ${intact ? "" : "text-destructive"}`}>
            {intact ? "Seal intact" : "Seal broken"}
          </p>
        </div>
        <dl className="flex flex-col gap-1 text-sm">
          <div className="flex flex-wrap justify-between gap-x-3">
            <dt className={intact ? "text-pitch-foreground/75" : "text-muted-foreground"}>Sealed fingerprint</dt>
            <dd className="font-mono">{fingerprint(sealed)}</dd>
          </div>
          <div className="flex flex-wrap justify-between gap-x-3">
            <dt className={intact ? "text-pitch-foreground/75" : "text-muted-foreground"}>This ledger now</dt>
            <dd className="font-mono">{fingerprint(current)}</dd>
          </div>
        </dl>
        {!intact && (
          <Button type="button" variant="outline" className="sm:self-start" onClick={() => setAmounts(originals)}>
            Put it back
          </Button>
        )}
      </div>
    </div>
  );
}
