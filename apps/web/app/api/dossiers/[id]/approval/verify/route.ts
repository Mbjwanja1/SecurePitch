import { type NextRequest, NextResponse } from "next/server";

import { requireUser, UUID_RE } from "@/lib/club-guard";
import { readSmallJson, relayJson } from "@/lib/engine";

// Send the passkey signature to the engine, which verifies it against the dossier as it is now
// and records the approval (ADR 0003).
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  if (!UUID_RE.test(id)) return NextResponse.json({ error: "Dossier not found" }, { status: 404 });
  const body = await readSmallJson(request);
  if (!body?.credential || typeof body.credential !== "object") {
    return NextResponse.json({ error: "That passkey response wasn't complete." }, { status: 400 });
  }
  return relayJson(`/v1/dossiers/${id}/approval/verify`, guard.userId, { credential: body.credential });
}
