"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase/client";

/** Only follow same-site paths, so ?next= can't send someone to another website. */
function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboard";
}

export function LoginForm() {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [step, setStep] = useState<"email" | "code">("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function sendCode(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.signInWithOtp({
      email,
      // Accounts are created by invitation only (Supabase dashboard → Authentication → Users).
      options: { shouldCreateUser: false },
    });
    setBusy(false);
    if (error) {
      setError(
        error.message.toLowerCase().includes("signups not allowed")
          ? "There's no SecurePitch account for this email. Ask your club admin to invite you."
          : `Couldn't send the code: ${error.message}`,
      );
      return;
    }
    setStep("code");
  }

  async function verifyCode(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const { error } = await createClient().auth.verifyOtp({ email, token: code, type: "email" });
    setBusy(false);
    if (error) {
      setError("That code is wrong or has expired. Check the latest email or send a new code.");
      return;
    }
    router.replace(next);
    router.refresh();
  }

  if (step === "email") {
    return (
      <form onSubmit={sendCode} className="flex flex-col gap-4">
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
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy || !email}>
          {busy ? "Sending…" : "Email me a sign-in code"}
        </Button>
      </form>
    );
  }

  return (
    <form onSubmit={verifyCode} className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        We sent a code to <span className="font-medium text-foreground">{email}</span>.
      </p>
      <div className="flex flex-col gap-2">
        <Label htmlFor="code">Sign-in code</Label>
        <Input
          id="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6,10}"
          maxLength={10}
          required
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          className="tracking-[0.3em] text-lg"
        />
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" disabled={busy || code.length < 6}>
        {busy ? "Checking…" : "Sign in"}
      </Button>
      <div className="flex justify-between text-sm">
        <button
          type="button"
          className="text-muted-foreground underline-offset-4 hover:underline"
          onClick={() => {
            setStep("email");
            setCode("");
            setError(null);
          }}
        >
          Use a different email
        </button>
        <button
          type="button"
          className="text-muted-foreground underline-offset-4 hover:underline"
          disabled={busy}
          onClick={() => sendCode()}
        >
          Send a new code
        </button>
      </div>
    </form>
  );
}
