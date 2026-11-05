"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { postJson } from "@/lib/passkey-client";

// Shown on an approved dossier that isn't sealed yet: sealing normally follows the treasurer's
// signature at once, so this only appears if that step failed.
export function SealPanel({ dossierId }: { dossierId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function seal() {
    setBusy(true);
    setError(null);
    const r = await postJson(`/api/dossiers/${dossierId}/seal`, {});
    if (!r.ok) {
      setBusy(false);
      return setError(r.error);
    }
    router.refresh(); // stay busy until the sealed page replaces this panel
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Approved, not sealed yet</CardTitle>
        <CardDescription>
          Both passkey signatures are in. Sealing adds SecurePitch&apos;s signature so sponsors
          can verify the dossier. Nothing in it can change.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <Button type="button" onClick={seal} disabled={busy} className="self-start">
          {busy ? "Sealing…" : "Seal the dossier"}
        </Button>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
