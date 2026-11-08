import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import { supabaseKey, supabaseUrl } from "@/lib/env";

// Pages that need a signed-in club member. Everything else (login, the public verifier at /v,
// attestation links at /a) stays reachable without an account.
const PROTECTED_PREFIXES = ["/dashboard", "/club", "/statements", "/dossiers", "/settings"];

/**
 * Redirect while keeping any cookies already set on `from`. When getUser() refreshes an
 * expired session, Supabase writes the new tokens onto the pass-through response; a fresh
 * NextResponse.redirect() would drop them and sign the user out.
 */
export function redirectKeepingCookies(from: NextResponse, url: URL): NextResponse {
  const redirect = NextResponse.redirect(url);
  for (const cookie of from.cookies.getAll()) redirect.cookies.set(cookie);
  return redirect;
}

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(supabaseUrl(), supabaseKey(), {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, options),
        );
      },
    },
  });

  // getUser() validates the session with Supabase Auth and refreshes expired tokens.
  // Don't run other code between createServerClient and this call.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const path = request.nextUrl.pathname;
  const go = (pathname: string, search = "") => {
    const url = request.nextUrl.clone();
    url.pathname = pathname;
    url.search = search;
    return redirectKeepingCookies(response, url);
  };

  // Signed-in users skip the landing page; everyone else sees what SecurePitch is first.
  if (path === "/" && user) return go("/dashboard");

  const needsUser = PROTECTED_PREFIXES.some((p) => path === p || path.startsWith(`${p}/`));
  if (needsUser && !user) return go("/login", `?next=${encodeURIComponent(path)}`);
  if (path === "/login" && user) return go("/dashboard");

  return response;
}
