"use client";

import { useEffect, useState } from "react";

import type { PublicJwk } from "@/lib/crypto/ecdsa";
import {
  type SealedPayload,
  type VerifyResult,
  verifyDossier,
} from "@/lib/crypto/verify-dossier";

type PublicDossier = {
  payload: SealedPayload;
  signature: string;
  status: "sealed" | "revoked";
  pdf_sha256?: string;
};

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "done"; dossier: PublicDossier; result: VerifyResult };

function fragmentRoot(): string | undefined {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  return params.get("r") ?? undefined;
}

function kes(cents: number): string {
  return `KES ${(cents / 100).toLocaleString("en-KE", { maximumFractionDigits: 0 })}`;
}

export function Verifier({ id }: { id: string }) {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [dRes, kRes] = await Promise.all([
          fetch(`/api/public/dossiers/${encodeURIComponent(id)}`),
          fetch("/.well-known/securepitch-keys.json"),
        ]);
        if (dRes.status === 404)
          throw new Error("No dossier with this ID was found.");
        if (!dRes.ok || !kRes.ok)
          throw new Error("The verification service is unavailable right now.");
        const dossier = (await dRes.json()) as PublicDossier;
        const { keys } = (await kRes.json()) as { keys: PublicJwk[] };
        const result = await verifyDossier({
          sealed: dossier.payload,
          signature: dossier.signature,
          keys,
          status: dossier.status,
          // The approvers signed on this same site, so its origin and host are what they signed for.
          expectedOrigin: window.location.origin,
          expectedRpId: window.location.hostname,
          fragmentRoot: fragmentRoot(),
        });
        if (!cancelled) setState({ phase: "done", dossier, result });
      } catch (e) {
        if (!cancelled) {
          setState({
            phase: "error",
            message: e instanceof Error ? e.message : "Something went wrong.",
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <main className="mx-auto max-w-2xl p-6">
      <h1 className="text-2xl font-semibold">SecurePitch dossier check</h1>

      {state.phase === "loading" && (
        <p className="mt-6">Checking signatures…</p>
      )}

      {state.phase === "error" && (
        <p
          role="alert"
          className="mt-6 rounded-lg border border-red-300 bg-red-50 p-4 text-red-800"
        >
          {state.message}
        </p>
      )}

      {state.phase === "done" && (
        <Report dossier={state.dossier} result={state.result} />
      )}
    </main>
  );
}

function Report({
  dossier,
  result,
}: {
  dossier: PublicDossier;
  result: VerifyResult;
}) {
  const p = dossier.payload;
  const club =
    (p.club as { name?: string } | undefined)?.name ?? "Unknown club";
  const period = p.period as { from?: string; to?: string } | undefined;
  const totals = (p.totals_cents ?? {}) as Record<string, number>;

  return (
    <>
      <div
        role="status"
        className={`mt-6 rounded-lg border p-4 text-lg font-medium ${
          result.ok
            ? "border-green-300 bg-green-50 text-green-900"
            : "border-red-300 bg-red-50 text-red-900"
        }`}
      >
        {result.ok
          ? "All checks passed. This dossier has not been changed since it was sealed."
          : "Do not rely on this dossier. At least one check failed."}
      </div>

      {result.localKey && (
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-amber-900">
          Sealed with a test key, not the production signing key.
        </p>
      )}

      <section className="mt-6">
        <h2 className="text-lg font-semibold">What was sealed</h2>
        <p className="mt-1">
          {club}
          {period?.from && period?.to
            ? ` · ${period.from} to ${period.to}`
            : ""}
        </p>
        <p className="text-sm text-gray-600">
          {String(p.rows_disclosed)} club rows shown of {String(p.rows_total)}{" "}
          on the statement.
        </p>
        <ul className="mt-2 text-sm">
          {Object.entries(totals).map(([category, cents]) => (
            <li key={category}>
              {category}: {kes(cents)}
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-6">
        <h2 className="text-lg font-semibold">Checks</h2>
        <ul className="mt-2 space-y-2">
          {result.checks.map((c) => (
            <li key={c.id} className="flex gap-3">
              <span
                aria-hidden
                className={c.ok ? "text-green-700" : "text-red-700"}
              >
                {c.ok ? "✓" : "✗"}
              </span>
              <span>
                <span className="sr-only">
                  {c.ok ? "Passed: " : "Failed: "}
                </span>
                {c.label}
                {c.detail && (
                  <span className="block text-sm text-gray-600">
                    {c.detail}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <p className="mt-8 text-sm text-gray-600">
        These checks show the dossier is genuine and unchanged since it was
        approved and sealed. They do not prove that the underlying payments
        happened.
      </p>
    </>
  );
}
