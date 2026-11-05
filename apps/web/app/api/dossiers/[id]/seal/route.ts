import { type NextRequest, NextResponse } from "next/server";

import { requireUser, UUID_RE } from "@/lib/club-guard";
import { relayJson } from "@/lib/engine";

// Retry sealing an approved dossier. Sealing normally happens as soon as the treasurer signs;
// this is for when that step failed (for example, the signing key was unavailable).
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  if (!UUID_RE.test(id)) return NextResponse.json({ error: "Dossier not found" }, { status: 404 });
  return relayJson(`/v1/dossiers/${id}/seal`, guard.userId, {});
}
