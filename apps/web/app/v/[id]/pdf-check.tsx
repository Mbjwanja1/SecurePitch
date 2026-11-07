"use client";

import { useState } from "react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { MAX_PDF_BYTES, hashFile, sameHash } from "@/lib/pdf-hash";

type State =
  | { kind: "idle" }
  | { kind: "hashing" }
  | { kind: "match" }
  | { kind: "mismatch" }
  | { kind: "error"; message: string };

// "Check a PDF you received": the file is hashed in this browser and never uploaded.
export function PdfCheck({ expected }: { expected: string | null }) {
  const [state, setState] = useState<State>({ kind: "idle" });

  async function onPick(file: File | undefined) {
    if (!file || !expected) return;
    if (file.size > MAX_PDF_BYTES) {
      setState({
        kind: "error",
        message: "That file is too large to be a SecurePitch dossier.",
      });
      return;
    }
    setState({ kind: "hashing" });
    try {
      const actual = await hashFile(file);
      setState({ kind: sameHash(actual, expected) ? "match" : "mismatch" });
    } catch {
      setState({
        kind: "error",
        message: "Couldn't read that file. Try again.",
      });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Check a PDF you received</CardTitle>
        <CardDescription>
          Choose the dossier PDF you were given. It is checked in your browser
          and never uploaded.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {!expected ? (
          <p>
            This dossier has no sealed PDF on record yet, so there is nothing to
            compare with.
          </p>
        ) : (
          <>
            <label className="flex flex-col gap-1">
              <span className="font-medium">Dossier PDF</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(e) => void onPick(e.target.files?.[0])}
                className="text-sm"
              />
            </label>
            <div aria-live="polite">
              {state.kind === "hashing" && <p>Checking the file…</p>}
              {state.kind === "match" && (
                <p className="font-semibold text-emerald-700 dark:text-emerald-400">
                  ✓ This is the sealed PDF. It has not been changed.
                </p>
              )}
              {state.kind === "mismatch" && (
                <p role="alert" className="font-semibold text-destructive">
                  ✗ This PDF is not the one SecurePitch sealed. Don&apos;t rely
                  on it.
                </p>
              )}
              {state.kind === "error" && (
                <p role="alert" className="text-destructive">
                  {state.message}
                </p>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
