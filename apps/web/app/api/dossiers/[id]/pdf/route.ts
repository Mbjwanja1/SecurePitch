import { type NextRequest, NextResponse } from "next/server";

import { requireUser, UUID_RE } from "@/lib/club-guard";
import { EngineError, getEngineFile, relayJson } from "@/lib/engine";

// The sealed dossier PDF. The engine checks club membership, and checks the stored file against
// its recorded SHA-256 before handing it out.
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  if (!UUID_RE.test(id)) return NextResponse.json({ error: "Dossier not found" }, { status: 404 });
  try {
    const pdf = await getEngineFile(`/v1/dossiers/${id}/pdf`, guard.userId);
    return new NextResponse(pdf, {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="securepitch-dossier-${id}.pdf"`,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
      },
    });
  } catch (err) {
    if (err instanceof EngineError) {
      return NextResponse.json({ error: err.failure.message }, { status: err.failure.status });
    }
    throw err;
  }
}

// Make the PDF for a sealed dossier that has none yet (manager or treasurer).
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  if (!UUID_RE.test(id)) return NextResponse.json({ error: "Dossier not found" }, { status: 404 });
  return relayJson(`/v1/dossiers/${id}/pdf`, guard.userId, {});
}
