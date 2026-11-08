import { type NextRequest, NextResponse } from "next/server";

import { requireManager } from "@/lib/club-guard";
import { relayJson } from "@/lib/engine";
import { validatePlayers } from "@/lib/roster";

const MAX_BODY_CHARS = 256 * 1024;

// Save a club's roster. The engine turns each phone number into keyed hashes and keeps no raw number.
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ clubId: string }> },
) {
  const { clubId } = await params;
  const guard = await requireManager(request, clubId);
  if ("response" in guard) return guard.response;

  const text = await request.text().catch(() => "");
  if (!text || text.length > MAX_BODY_CHARS) {
    return NextResponse.json({ error: "Send a roster of up to 200 players." }, { status: 400 });
  }
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return NextResponse.json({ error: "The roster wasn't in the expected format." }, { status: 400 });
  }
  const checked = validatePlayers((body as { players?: unknown } | null)?.players);
  if (!checked.ok) return NextResponse.json({ error: checked.error }, { status: 400 });

  return relayJson(`/v1/clubs/${clubId}/roster`, guard.userId, { players: checked.players });
}
