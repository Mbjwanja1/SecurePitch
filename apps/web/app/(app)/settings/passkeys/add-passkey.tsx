"use client";

import {
  browserSupportsWebAuthn,
  type PublicKeyCredentialCreationOptionsJSON,
  startRegistration,
} from "@simplewebauthn/browser";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { passkeyErrorMessage, postJson } from "@/lib/passkey-client";

export function AddPasskey() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [supported, setSupported] = useState(true);
  // Checked after mount: the server can't know, and guessing would break hydration.
  useEffect(() => setSupported(browserSupportsWebAuthn()), []);

  async function add() {
    setBusy(true);
    setError(null);
    setAdded(false);
    try {
      const start = await postJson("/api/passkeys/register/options", {});
      if (!start.ok) return setError(start.error);
      const credential = await startRegistration({
        optionsJSON: start.data.options as PublicKeyCredentialCreationOptionsJSON,
      });
      const done = await postJson("/api/passkeys/register/verify", {
        state: start.data.state,
        credential,
      });
      if (!done.ok) return setError(done.error);
      setAdded(true);
      router.refresh();
    } catch (err) {
      setError(passkeyErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {added && <p className="text-sm">Passkey added.</p>}
      <Button type="button" onClick={add} disabled={busy || !supported} className="self-start">
        {busy ? "Waiting for your device…" : "Add a passkey on this device"}
      </Button>
      {!supported && (
        <p className="text-sm text-muted-foreground">
          This browser doesn&apos;t support passkeys. Use an up-to-date Chrome, Safari or Edge.
        </p>
      )}
    </div>
  );
}
