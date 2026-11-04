import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { createClient } from "@/lib/supabase/server";

import { AddPasskey } from "./add-passkey";

export const metadata: Metadata = { title: "Passkeys · SecurePitch" };

type Passkey = { id: string; created_at: string; transports: string[] | null };

export default async function PasskeysPage() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) redirect("/login?next=/settings/passkeys");

  // Row-level security returns only this user's own passkeys.
  const { data, error } = await supabase
    .from("webauthn_credentials")
    .select("id, created_at, transports")
    .order("created_at");
  const passkeys = (data ?? []) as Passkey[];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <Link href="/dashboard" className="text-sm text-muted-foreground hover:underline">
          ← Your clubs
        </Link>
        <h1 className="text-2xl font-semibold tracking-tight">Passkeys</h1>
        <p className="text-sm text-muted-foreground">
          Managers and treasurers sign dossiers with a passkey: your phone or laptop&apos;s
          fingerprint, face or PIN. Sponsors can check each signature themselves, so nobody,
          including SecurePitch, can approve a dossier for you.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Your passkeys</CardTitle>
          <CardDescription>
            {passkeys.length === 0
              ? "You haven't added one yet. Add one on the phone you'll sign with."
              : "Add another if you sign from more than one device."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              Couldn&apos;t load your passkeys. Refresh the page.
            </p>
          ) : (
            passkeys.length > 0 && (
              <ul className="flex flex-col divide-y rounded-xl border text-sm">
                {passkeys.map((p) => (
                  <li key={p.id} className="flex items-center justify-between gap-3 p-3">
                    <span className="font-mono text-xs">…{p.id.slice(-8)}</span>
                    <span className="text-muted-foreground">
                      added{" "}
                      {new Intl.DateTimeFormat("en-KE", {
                        dateStyle: "medium",
                        timeZone: "Africa/Nairobi",
                      }).format(new Date(p.created_at))}
                      {p.transports?.includes("internal") ? " · this device" : ""}
                    </span>
                  </li>
                ))}
              </ul>
            )
          )}
          <AddPasskey />
        </CardContent>
      </Card>
    </div>
  );
}
