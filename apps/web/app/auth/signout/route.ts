import { type NextRequest, NextResponse } from "next/server";

import { isSameOrigin } from "@/lib/safe-redirect";
import { createClient } from "@/lib/supabase/server";

export async function POST(request: NextRequest) {
  // Refuse cross-site form posts, so another website can't sign our users out.
  if (
    !isSameOrigin(
      request.headers.get("origin"),
      request.headers.get("sec-fetch-site"),
      request.nextUrl.origin,
    )
  ) {
    return NextResponse.json({ error: "Cross-site request refused" }, { status: 403 });
  }

  const supabase = await createClient();
  await supabase.auth.signOut();
  // 303 so the browser follows with GET after the form POST.
  return NextResponse.redirect(new URL("/login", request.url), { status: 303 });
}
