/**
 * Where to send someone after sign-in, given an untrusted ?next= value.
 *
 * Browsers "fix up" URLs before following them: they strip tabs and newlines and treat "\"
 * as "/", so strings like "/\evil.com" or "/<tab>/evil.com" look like local paths but lead
 * off-site. Instead of pattern-matching those tricks, resolve the value exactly as the
 * browser will and accept it only if it stays on our own origin.
 */
export function safeNext(next: string | null, origin: string, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/")) return fallback;
  let url: URL;
  try {
    url = new URL(next, origin);
  } catch {
    return fallback;
  }
  if (url.origin !== new URL(origin).origin) return fallback;
  return url.pathname + url.search + url.hash; // the already-resolved, same-site form
}

/**
 * True when a state-changing request (like sign-out) came from one of our own pages.
 * Browsers always send Origin on POST; Sec-Fetch-Site is the fallback. Requests with
 * neither (old browsers, scripts) are refused.
 */
export function isSameOrigin(
  originHeader: string | null,
  secFetchSite: string | null,
  appOrigin: string,
): boolean {
  if (originHeader) return originHeader === appOrigin;
  return secFetchSite === "same-origin";
}
