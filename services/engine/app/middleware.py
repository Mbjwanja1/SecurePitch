"""Request gate that runs before FastAPI touches the request body.

FastAPI parses form and file bodies *before* it runs dependencies such as
require_internal_key, so on its own an unauthenticated client could make the engine read a
large upload into memory or the RAM-backed /tmp before being refused. This raw ASGI
middleware is the outermost layer: it checks the key and the body size first, and stops
reading as soon as a streamed body passes the limit.
"""

import hmac
import json
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class _BodyTooLarge(BaseException):  # noqa: N818 - control-flow signal, not an error type
    """Raised inside the app while it reads the body.

    BaseException, not Exception: FastAPI wraps any Exception raised during body parsing into
    "400 There was an error parsing the body", which would hide this 413.
    """


class RequestGate:
    def __init__(
        self,
        app: ASGIApp,
        *,
        internal_key: str,
        public_paths: Iterable[str],
        max_body_bytes: int,
    ) -> None:
        self.app = app
        self.key = internal_key.encode()
        self.public_paths = frozenset(_normalise(p) for p in public_paths)
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope["headers"])

        if _normalise(scope["path"]) not in self.public_paths:
            if not self.key:
                # Fail closed: a missing key in config must never mean "no auth".
                await _reject(send, 503, "Engine key is not configured")
                return
            supplied = headers.get(b"x-internal-key")
            if supplied is None or not hmac.compare_digest(supplied, self.key):
                await _reject(send, 401, "Missing or invalid X-Internal-Key")
                return

        declared = headers.get(b"content-length")
        if declared is not None:
            declared = declared.strip()  # HTTP allows optional whitespace around header values
            if not declared.isdigit():
                await _reject(send, 400, "Invalid Content-Length")
                return
            if int(declared) > self.max_body_bytes:
                await _reject(send, 413, "Request body too large")
                return

        # Bodies sent without a Content-Length (chunked) are counted as they stream in.
        received = 0
        response_started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise _BodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except _BodyTooLarge:
            if not response_started:
                await _reject(send, 413, "Request body too large")


def _normalise(path: str) -> str:
    """Treat /health and /health/ as the same path; the root stays "/"."""
    return path.rstrip("/") or "/"


async def _reject(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
