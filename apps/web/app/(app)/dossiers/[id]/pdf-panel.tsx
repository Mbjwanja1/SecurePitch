"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { postJson } from "@/lib/passkey-client";

// Shown on a sealed dossier with no PDF yet: sealed before PDFs existed, or rendering failed
// when it was sealed. The seal itself is unaffected either way.
export function PdfPanel({ dossierId }: { dossierId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function make() {
    setBusy(true);
    setError(null);
    const r = await postJson(`/api/dossiers/${dossierId}/pdf`, {});
    if (!r.ok) {
      setBusy(false);
      return setError(r.error);
    }
    router.refresh(); // stay busy until the page shows the download link
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted-foreground">This dossier doesn&apos;t have its PDF yet.</p>
      <Button type="button" onClick={make} disabled={busy} className="self-start">
        {busy ? "Making the PDF…" : "Make the sealed PDF"}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
