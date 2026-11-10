"use client";

import {
  type PublicKeyCredentialRequestOptionsJSON,
  startAuthentication,
} from "@simplewebauthn/browser";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { fingerprint, passkeyErrorMessage, postJson } from "@/lib/passkey-client";
import { type Category, CATEGORY_LABEL, CHECK_LABEL, formatKes } from "@/lib/tagging";

type Summary = {
  signing_as: "manager" | "treasurer";
  rows_total: number;
  rows_disclosed: number;
  totals_cents: Record<string, number>;
  integrity_score_bp: number;
  failed_checks?: { check: string; detail: string; acknowledged: boolean }[];
  challenge: string;
};

const ACTION = {
  manager: { title: "Submit for approval", button: "Submit with my passkey" },
  treasurer: { title: "Approve this dossier", button: "Approve with my passkey" },
} as const;

export function ApprovalPanel({
  dossierId,
  signingAs,
  hasPasskey,
}: {
  dossierId: string;
  signingAs: "manager" | "treasurer";
  hasPasskey: boolean;
}) {
  const router = useRouter();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [options, setOptions] = useState<PublicKeyCredentialRequestOptionsJSON | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const action = ACTION[signingAs];

  if (!hasPasskey) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{action.title}</CardTitle>
          <CardDescription>
            You sign with a passkey (your fingerprint, face or PIN).{" "}
            <Link href="/settings/passkeys" className="underline underline-offset-4">
              Add a passkey
            </Link>{" "}
            first, then come back to this page.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  // Step 1: the engine builds the challenge from the stored dossier and says what it covers.
  async function review() {
    setBusy(true);
    setError(null);
    const r = await postJson(`/api/dossiers/${dossierId}/approval/options`, {});
    setBusy(false);
    if (!r.ok) return setError(r.error);
    setSummary(r.data.summary as Summary);
    setOptions(r.data.options as PublicKeyCredentialRequestOptionsJSON);
  }

  // Step 2: the passkey signs that challenge; the engine verifies and records it.
  async function sign() {
    if (!options) return;
    setBusy(true);
    setError(null);
    try {
      const credential = await startAuthentication({ optionsJSON: options });
      const r = await postJson(`/api/dossiers/${dossierId}/approval/verify`, { credential });
      if (!r.ok) {
        setError(r.error);
        setSummary(null); // whatever went wrong, review again before the next attempt
        setOptions(null);
        setBusy(false);
        return;
      }
      // Signed: drop the used challenge and stay busy while the page reloads, so the button
      // can't start a second passkey prompt for a dossier that has already moved on.
      setOptions(null);
      router.refresh();
    } catch (err) {
      setError(passkeyErrorMessage(err));
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{action.title}</CardTitle>
        <CardDescription>
          {signingAs === "manager"
            ? "Signing locks the ledger and sends it to your treasurer to approve."
            : "Check the ledger first. Your signature is the club's independent approval."}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {summary ? (
          <>
            <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Statement rows in this dossier</dt>
                <dd className="font-medium tabular-nums">
                  {summary.rows_disclosed} of {summary.rows_total} (
                  {summary.rows_total - summary.rows_disclosed} kept personal)
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Statement integrity</dt>
                <dd className="font-medium tabular-nums">
                  {(summary.integrity_score_bp / 100).toFixed(0)}%
                </dd>
              </div>
              {Object.entries(summary.totals_cents).map(([category, cents]) => (
                <div key={category}>
                  <dt className="text-muted-foreground">
                    {CATEGORY_LABEL[category as Category] ?? category}
                  </dt>
                  <dd className="font-medium tabular-nums">{formatKes(cents)}</dd>
                </div>
              ))}
              {(summary.failed_checks ?? []).length > 0 && (
                <div className="rounded-lg border border-destructive/40 p-3 sm:col-span-2">
                  <dt className="font-medium text-destructive">Statement warnings</dt>
                  <dd>
                    <ul className="mt-1 flex flex-col gap-1">
                      {summary.failed_checks?.map((c) => (
                        <li key={c.check}>
                          ✗ {CHECK_LABEL[c.check] ?? c.check}
                          {c.detail ? ` (${c.detail})` : ""}
                          {c.acknowledged ? ". The manager confirmed this when saving." : ""}
                        </li>
                      ))}
                    </ul>
                  </dd>
                </div>
              )}
              <div className="sm:col-span-2">
                <dt className="text-muted-foreground">Fingerprint of what you&apos;re signing</dt>
                <dd className="font-mono font-medium">{fingerprint(summary.challenge)}</dd>
              </div>
            </dl>
            <div className="flex flex-wrap gap-2">
              <Button type="button" onClick={sign} disabled={busy}>
                {busy ? "Waiting for your passkey…" : action.button}
              </Button>
              <Button
                type="button"
                variant="ghost"
                disabled={busy}
                onClick={() => {
                  setSummary(null);
                  setOptions(null);
                }}
              >
                Cancel
              </Button>
            </div>
          </>
        ) : (
          <Button type="button" onClick={review} disabled={busy} className="self-start">
            {busy ? "Preparing…" : "Review and sign"}
          </Button>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
