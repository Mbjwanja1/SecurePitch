"use client";

import { Check as CheckIcon, LoaderCircle, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PublicJwk } from "@/lib/crypto/ecdsa";
import { formatWhen } from "@/lib/tagging";
import { type Check, type PublicRecord, type Verification, verifyDossier } from "@/lib/verify";

type State =
  | { kind: "checking" }
  | { kind: "done"; v: Verification }
  | { kind: "error"; message: string };

const ROLE_LABEL: Record<string, string> = { manager: "Manager", treasurer: "Treasurer" };

// Runs in the sponsor's own browser: the server only supplies the record and the public keys.
export function VerifyPanel({ record }: { record: PublicRecord }) {
  const [state, setState] = useState<State>({ kind: "checking" });

  useEffect(() => {
    let live = true;
    (async () => {
      let keys: PublicJwk[];
      try {
        const r = await fetch("/.well-known/securepitch-keys.json");
        if (!r.ok) throw new Error(`keys: ${r.status}`);
        const body = (await r.json()) as { keys?: unknown };
        if (!Array.isArray(body.keys)) throw new Error("keys: not a key set");
        keys = body.keys as PublicJwk[];
      } catch {
        if (live) {
          setState({ kind: "error", message: "Couldn't fetch SecurePitch's public keys. Try again." });
        }
        return;
      }
      try {
        // Passkeys are bound to the site they were made on, which is this one.
        const rp = { rpId: window.location.hostname, origins: [window.location.origin] };
        const v = await verifyDossier(record, keys, rp);
        if (live) setState({ kind: "done", v });
      } catch {
        // verifyDossier fails checks rather than throwing; this is a last resort.
        if (live) {
          setState({ kind: "error", message: "Couldn't check this dossier's signatures in this browser." });
        }
      }
    })();
    return () => {
      live = false;
    };
  }, [record]);

  if (state.kind !== "done") {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {state.kind === "checking" && (
              <LoaderCircle aria-hidden className="size-5 animate-spin text-muted-foreground" />
            )}
            {state.kind === "checking" ? "Checking signatures…" : "Couldn't check"}
          </CardTitle>
          {state.kind === "error" && (
            <CardDescription role="alert">{state.message}</CardDescription>
          )}
        </CardHeader>
      </Card>
    );
  }

  const { v } = state;
  const approvals = Array.isArray(record.payload?.approvals) ? record.payload.approvals : [];
  const signedAt = new Map(approvals.map((a) => [String(a?.role), a?.signed_at]));
  const devKey = typeof record.payload?.kid === "string" && record.payload.kid.startsWith("local-");
  const trusted = v.authentic && v.status === "sealed";
  const title = !v.authentic
    ? "Not authentic"
    : v.status === "revoked"
      ? "Authentic, but revoked"
      : "Verified";

  const Icon = trusted ? ShieldCheck : ShieldAlert;

  return (
    <section
      aria-live="polite"
      className={
        trusted
          ? "overflow-hidden rounded-xl border-t-4 border-seal bg-pitch text-pitch-foreground"
          : "overflow-hidden rounded-xl border border-destructive/40 bg-destructive/10"
      }
    >
      <div className="flex items-start gap-3 p-4 sm:p-6">
        <Icon
          aria-hidden
          className={`mt-1 size-8 shrink-0 ${trusted ? "text-seal" : "text-destructive"}`}
        />
        <div className="min-w-0">
          <h2
            className={`text-4xl leading-none font-bold sm:text-5xl ${trusted ? "" : "text-destructive"}`}
          >
            {title}
          </h2>
          <p className={`mt-2 max-w-prose text-sm ${trusted ? "text-pitch-foreground/85" : ""}`}>
            {v.authentic
              ? "Checked in your browser: nothing in this dossier has changed since the club's manager and treasurer signed it."
              : "Don't rely on this dossier: at least one signature doesn't hold."}
          </p>
        </div>
      </div>
      <div className="bg-card text-card-foreground">
        <ul className="flex flex-col divide-y text-sm">
          <Row label="SecurePitch seal" check={v.seal}>
            {devKey && v.seal.ok && " Development key: not production-signed."}
          </Row>
          {v.approvals.map(({ role, check }) => (
            <Row key={role} label={ROLE_LABEL[role] ?? role} check={check}>
              {check.ok && signedAt.get(role) && ` ${formatWhen(signedAt.get(role)!)}.`}
            </Row>
          ))}
          {!v.record.ok && <Row label="Dossier" check={v.record} />}
        </ul>
      </div>
    </section>
  );
}

function Row({
  label,
  check,
  children,
}: {
  label: string;
  check: Check;
  children?: React.ReactNode;
}) {
  return (
    <li className="flex gap-3 p-3 sm:px-6">
      {check.ok ? (
        <CheckIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-success" />
      ) : (
        <X aria-hidden className="mt-0.5 size-4 shrink-0 text-destructive" />
      )}
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <span className="font-medium">{label}</span>
        <span className="sr-only">{check.ok ? " (valid)" : " (failed)"}</span>: {check.detail}
        <span className="text-muted-foreground">{children}</span>
      </span>
    </li>
  );
}
