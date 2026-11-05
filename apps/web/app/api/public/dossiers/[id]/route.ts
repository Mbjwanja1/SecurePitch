import { createClient } from "@supabase/supabase-js";
import { NextResponse } from "next/server";

import { supabaseKey, supabaseUrl } from "@/lib/env";

// Public: a sponsor's browser reads a sealed dossier here, without logging in. The database
// function public.public_dossier() returns only sealed or revoked dossiers, and only these fields.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  if (!UUID.test(id))
    return NextResponse.json({ error: "not found" }, { status: 404 });

  const supabase = createClient(supabaseUrl(), supabaseKey(), {
    auth: { persistSession: false, autoRefreshToken: false },
  });
  const { data, error } = await supabase.rpc("public_dossier", { p_id: id });

  if (error)
    return NextResponse.json({ error: "unavailable" }, { status: 503 });
  if (!data) return NextResponse.json({ error: "not found" }, { status: 404 });

  return NextResponse.json(data, { headers: { "Cache-Control": "no-store" } });
}
