import { type NextRequest, NextResponse } from "next/server";

import { requireManager } from "@/lib/club-guard";
import { callEngine, EngineError } from "@/lib/engine";
import { readStatementForm } from "@/lib/statement-upload";

// Parse a statement for tagging. The rows go back to the coach's browser only; nothing is stored.
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

  try {
    const parsed = await callEngine(`/v1/clubs/${clubId}/statements/parse`, {
      actor: guard.userId,
      body: upload.pdf,
      contentType: "application/pdf",
      statementPassword: upload.password,
    });
    return NextResponse.json(parsed, { headers: { "Cache-Control": "no-store" } });
  } catch (err) {
    if (err instanceof EngineError) {
      return NextResponse.json({ error: err.failure.message }, { status: err.failure.status });
    }
    throw err;
  }
}
