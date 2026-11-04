import { NextResponse } from "next/server";

import { EngineError, getFromEngine } from "@/lib/engine";

// The platform's public signing keys as JWK (CRYPTO_SPEC section 5). Public: sponsors' browsers
// fetch this to check a dossier's seal, picking the key by the payload's "kid".
export async function GET() {
  try {
    const keys = await getFromEngine<{ keys: unknown[] }>("/v1/keys");
    return NextResponse.json(keys, {
      headers: {
        "Cache-Control": "public, max-age=300",
        "Access-Control-Allow-Origin": "*", // any verifier, including offline copies
      },
    });
  } catch (err) {
    if (err instanceof EngineError) {
      return NextResponse.json({ error: "Keys are unavailable right now" }, { status: 503 });
    }
    throw err;
  }
}
