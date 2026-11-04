import { type NextRequest } from "next/server";

import { requireUser } from "@/lib/club-guard";
import { relayJson } from "@/lib/engine";

// Start adding a passkey for the signed-in user. The engine returns WebAuthn options and a
// signed state token that must come back with the new credential.
export async function POST(request: NextRequest) {
  const guard = await requireUser(request);
  if ("response" in guard) return guard.response;
  return relayJson("/v1/passkeys/register/options", guard.userId, { user_name: guard.email });
}
