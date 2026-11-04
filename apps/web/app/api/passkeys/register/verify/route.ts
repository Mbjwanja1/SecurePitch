import { type NextRequest, NextResponse } from "next/server";

import { requireUser } from "@/lib/club-guard";
import { readSmallJson, relayJson } from "@/lib/engine";

// Finish adding a passkey: the engine verifies the browser's response and stores the public key.
export async function POST(request: NextRequest) {
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  const body = await readSmallJson(request);
  if (!body || typeof body.state !== "string" || !body.credential || typeof body.credential !== "object") {
    return NextResponse.json({ error: "That passkey response wasn't complete." }, { status: 400 });
  }
  return relayJson("/v1/passkeys/register/verify", guard.userId, {
    state: body.state,
    credential: body.credential,
  });
}
