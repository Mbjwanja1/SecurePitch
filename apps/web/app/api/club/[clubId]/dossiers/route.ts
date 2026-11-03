import { type NextRequest, NextResponse } from "next/server";

import { requireManager } from "@/lib/club-guard";
import { callEngine, EngineError } from "@/lib/engine";
import { readStatementForm } from "@/lib/statement-upload";

type Saved = { dossier_id: string; replaced_draft: boolean; items: number };

const MAX_TAGS = 2000;

/** Tags from the browser: receipt numbers and categories only. The engine validates them fully. */
function readTags(raw: FormDataEntryValue | null): { tx: string; category: string }[] | null {
  if (typeof raw !== "string") return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_TAGS) return null;
  const tags = value.map((t) =>
    t && typeof t.tx === "string" && typeof t.category === "string"
      ? { tx: t.tx, category: t.category }
      : null,
  );
  return tags.every((t) => t !== null) ? (tags as { tx: string; category: string }[]) : null;
}

// Save the draft dossier. The statement is sent again and re-parsed by the engine, so every
// stored amount comes from the PDF, not from the browser (ADR 0002).
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ clubId: string }> },
) {
  const { clubId } = await params;
  const guard = await requireManager(request, clubId);
  if ("response" in guard) return guard.response;

  const form = await request.formData().catch(() => null);
  if (!form) return NextResponse.json({ error: "Send the statement as a form upload." }, { status: 400 });
  const upload = await readStatementForm(form);
  if ("status" in upload) return NextResponse.json({ error: upload.message }, { status: upload.status });
  const tags = readTags(form.get("tags"));
  if (!tags) return NextResponse.json({ error: "Tag at least one club transaction." }, { status: 400 });

  try {
    const saved = await callEngine<Saved>(`/v1/clubs/${clubId}/dossiers`, {
      actor: guard.userId,
      body: JSON.stringify({ statement_pdf: Buffer.from(upload.pdf).toString("base64"), tags }),
      contentType: "application/json",
      statementPassword: upload.password,
    });
    return NextResponse.json(
      { dossier_id: saved.dossier_id, replaced_draft: saved.replaced_draft, items: saved.items },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch (err) {
    if (err instanceof EngineError) {
      const { status, message, problems } = err.failure;
      return NextResponse.json({ error: message, problems }, { status });
    }
    throw err;
  }
}
