"use client";

import { useRef, useState } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  // Only the newest pick may set the result, so a slow earlier file can't overwrite it.
  const run = useRef(0);

  async function onPick(file: File | undefined) {
    const id = ++run.current;
    if (!file || !expected) {
      setState({ kind: "idle" });
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setState({ kind: "error", message: "That file is too large to be a SecurePitch dossier." });
      return;
    }
    setState({ kind: "hashing" });
    try {
      const actual = await hashFile(file);
      if (id === run.current) setState({ kind: sameHash(actual, expected) ? "match" : "mismatch" });
    } catch {
      if (id === run.current) setState({ kind: "error", message: "Couldn't read that file. Try again." });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Check a PDF you received</CardTitle>
        <CardDescription>
          Choose the dossier PDF you were given. It is checked in your browser and never uploaded.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {!expected ? (
          <p>This dossier has no sealed PDF on record yet, so there is nothing to compare with.</p>
        ) : (
          <>
            <label className="flex flex-col gap-1">
              <span className="font-medium">Dossier PDF</span>
              <input
                type="file"
                accept="application/pdf,.pdf"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = ""; // so choosing the same file again re-runs the check
                  void onPick(file);
                }}
                className="text-sm"
              />
            </label>
            <div aria-live="polite">
              {state.kind === "hashing" && <p>Checking the file…</p>}
              {state.kind === "match" && (
                <div className="font-semibold text-emerald-700 dark:text-emerald-400">
                  <p>✓ This is the PDF SecurePitch issued for this dossier.</p>
                  <p className="mt-1 text-sm font-normal text-muted-foreground">
                    Rely on it only if the signatures above are verified.
                  </p>
                </div>
              )}
              {state.kind === "mismatch" && (
                <p role="alert" className="font-semibold text-destructive">
                  ✗ This PDF is not the one SecurePitch issued for this dossier. Don&apos;t rely on it.
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
