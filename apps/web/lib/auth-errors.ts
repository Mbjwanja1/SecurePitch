// Turn Supabase Auth errors into messages a coach or treasurer can act on.
type AuthErrorLike = { message?: string; code?: string; status?: number } | null | undefined;

export function signInErrorMessage(error: AuthErrorLike): string | null {
  if (!error) return null;
  switch (error.code) {
    case "invalid_credentials":
      return "That email and password don't match. Check them, or ask your club admin to reset your password.";
    case "email_not_confirmed":
      return "This account hasn't been activated yet. Ask your club admin to confirm it.";
    case "user_banned":
      return "This account has been disabled. Ask your club admin.";
    case "over_request_rate_limit":
      return "Too many sign-in attempts. Wait a minute, then try again.";
  }
  if (error.status === 429) return "Too many sign-in attempts. Wait a minute, then try again.";
  return `Couldn't sign in: ${error.message ?? "unknown error"}. Check your connection and try again.`;
}
