"use client";

import { useEffect, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
          <CardTitle>{state.kind === "checking" ? "Checking signatures…" : "Couldn't check"}</CardTitle>
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

  return (
    <Card>
      <CardHeader>
        <CardTitle
          className={trusted ? "text-emerald-700 dark:text-emerald-400" : "text-destructive"}
        >
          {title}
        </CardTitle>
        <CardDescription>
          {v.authentic
            ? "Checked in your browser: nothing in this dossier has changed since the club's manager and treasurer signed it."
            : "Don't rely on this dossier: at least one signature doesn't hold."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="flex flex-col divide-y rounded-xl border text-sm">
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
      </CardContent>
    </Card>
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
    <li className="flex gap-3 p-3">
      <span
        aria-hidden
        className={check.ok ? "text-emerald-700 dark:text-emerald-400" : "text-destructive"}
      >
        {check.ok ? "✓" : "✗"}
      </span>
      <span>
        <span className="font-medium">{label}</span>
        <span className="sr-only">{check.ok ? " (valid)" : " (failed)"}</span>: {check.detail}
        <span className="text-muted-foreground">{children}</span>
      </span>
    </li>
  );
}
