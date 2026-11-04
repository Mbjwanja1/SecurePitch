import { type NextRequest, NextResponse } from "next/server";

import { requireUser, UUID_RE } from "@/lib/club-guard";
import { relayJson } from "@/lib/engine";

// Ask the engine for the challenge to sign: SHA-256 of the dossier's approval payload, built
// from the database (CRYPTO_SPEC section 6). It also checks it's this user's turn to sign.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  if (!UUID_RE.test(id)) return NextResponse.json({ error: "Dossier not found" }, { status: 404 });
  return relayJson(`/v1/dossiers/${id}/approval/options`, guard.userId, {});
}
