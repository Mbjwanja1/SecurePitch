import { type NextRequest, NextResponse } from "next/server";

import { isSameOrigin } from "@/lib/safe-redirect";
import { createClient } from "@/lib/supabase/server";

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export type Role = "manager" | "treasurer" | "captain";

/** The signed-in user's role in a club, read with their own session (row-level security). */
export async function roleIn(clubId: string): Promise<{ userId: string; role: Role | null } | null> {
  if (!UUID_RE.test(clubId)) return null;
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) return null;
  const { data } = await supabase
    .from("club_members")
    .select("role")
    .eq("club_id", clubId)
    .eq("user_id", user.id)
    .maybeSingle();
  return { userId: user.id, role: (data?.role as Role | undefined) ?? null };
}

function crossSite(request: NextRequest): NextResponse | null {
  return isSameOrigin(
    request.headers.get("origin"),
    request.headers.get("sec-fetch-site"),
    request.nextUrl.origin,
  )
    ? null
    : NextResponse.json({ error: "Cross-site request refused" }, { status: 403 });
}

/**
 * For route handlers that act for the signed-in user (passkeys, approvals): refuse cross-site
 * posts and signed-out users. The engine decides what this user may do with a dossier.
 */
export async function requireUser(
  request: NextRequest,
): Promise<{ userId: string; email: string } | { response: NextResponse }> {
  const refused = crossSite(request);
  if (refused) return { response: refused };
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return { response: NextResponse.json({ error: "Sign in again to continue." }, { status: 401 }) };
  }
  return { userId: user.id, email: user.email ?? user.id };
}

/**
 * For route handlers that act for a club's manager: refuse cross-site posts, signed-out users
 * and anyone who isn't the manager. Returns the user ID to send to the engine as X-Actor-Id.
 * The engine checks the role again (ADR 0002, rule 5).
 */
export async function requireManager(
  request: NextRequest,
  clubId: string,
): Promise<{ userId: string } | { response: NextResponse }> {
  const refused = crossSite(request);
  if (refused) return { response: refused };
  const access = await roleIn(clubId);
  if (!access) {
    return { response: NextResponse.json({ error: "Sign in again to continue." }, { status: 401 }) };
  }
  if (access.role !== "manager") {
    return {
      response: NextResponse.json(
        { error: "Only the club manager can upload statements." },
        { status: 403 },
      ),
    };
  }
  return { userId: access.userId };
}
