"""Internal API key check.

Once the Cloudflare tunnel is up the engine is reachable from the internet, so every route
except /health requires the X-Internal-Key header that only the web app's server knows.
"""

import hmac

from fastapi import Header, HTTPException, Request, status


def require_internal_key(
    request: Request,
    x_internal_key: str | None = Header(default=None),
) -> None:
    expected = request.app.state.settings.internal_key
    if not expected:
        # Fail closed: a missing key in config must never mean "no auth".
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Engine key is not configured")
    if x_internal_key is None or not hmac.compare_digest(x_internal_key, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid X-Internal-Key")
