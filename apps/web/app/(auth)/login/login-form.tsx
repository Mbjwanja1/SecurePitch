"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { signInErrorMessage } from "@/lib/auth-errors";
import { safeNext } from "@/lib/safe-redirect";
import { createClient } from "@/lib/supabase/client";

// Email + password sign-in. Accounts are created by a club admin (tools/onboard_member.py);
// there is no public sign-up. Emailed sign-in codes return once we have an email provider.
export function LoginForm() {
  const router = useRouter();
  const rawNext = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.signInWithPassword({ email, password });
    if (error) {
      setBusy(false);
      setError(signInErrorMessage(error));
      setPassword("");
      return;
    }
    router.replace(safeNext(rawNext, window.location.origin));
    router.refresh();
  }

  return (
    <form onSubmit={signIn} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="email">Email</Label>
        <Input
          id="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value.trim())}
          placeholder="coach@example.com"
        />
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" disabled={busy || !email || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
      <p className="text-sm text-muted-foreground">
        Forgot your password? Ask your club admin to reset it.
      </p>
    </form>
  );
}
