"""The gate must refuse unauthenticated or oversized requests without reading their bodies."""

import asyncio
from typing import Any

import pytest

from app.middleware import RequestGate

KEY = "test-key-that-is-long-enough-for-the-engine-1234"
LIMIT = 1024


class Recorder:
    """Inner app that records whether it was reached and reads the whole body."""

    def __init__(self) -> None:
        self.reached = False
        self.body = b""

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.reached = True
        more = True
        while more:
            message = await receive()
            self.body += message.get("body", b"")
            more = message.get("more_body", False)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def run(
    gate: RequestGate,
    path: str,
    headers: dict[str, str],
    chunks: list[bytes],
) -> tuple[int, int]:
    """Send a request through the gate. Returns (status, number of body chunks it pulled)."""
    pulled = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal pulled
        pulled += 1
        i = pulled - 1
        return {"type": "http.request", "body": chunks[i], "more_body": i + 1 < len(chunks)}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(gate(scope, receive, send))
    return sent[0]["status"], pulled


def make_gate(key: str = KEY) -> tuple[RequestGate, Recorder]:
    inner = Recorder()
    gate = RequestGate(inner, internal_key=key, public_paths={"/health"}, max_body_bytes=LIMIT)
    return gate, inner


def test_unauthenticated_upload_is_refused_without_reading_the_body() -> None:
    gate, inner = make_gate()
    big = [b"x" * 512] * 100  # 50 KB, far over the limit
    status, pulled = run(gate, "/v1/parse", {"content-length": str(512 * 100)}, big)
    assert status == 401
    assert pulled == 0
    assert not inner.reached


def test_wrong_key_is_refused_without_reading_the_body() -> None:
    gate, inner = make_gate()
    status, pulled = run(gate, "/v1/parse", {"x-internal-key": "wrong"}, [b"data"])
    assert (status, pulled, inner.reached) == (401, 0, False)


def test_fails_closed_when_no_key_is_configured() -> None:
    gate, inner = make_gate(key="")
    status, pulled = run(gate, "/v1/parse", {"x-internal-key": ""}, [b"data"])
    assert (status, pulled, inner.reached) == (503, 0, False)


def test_declared_oversized_body_is_refused_before_reading() -> None:
    gate, inner = make_gate()
    headers = {"x-internal-key": KEY, "content-length": str(LIMIT + 1)}
    status, pulled = run(gate, "/v1/parse", headers, [b"x" * (LIMIT + 1)])
    assert (status, pulled, inner.reached) == (413, 0, False)


def test_streamed_body_without_length_stops_at_the_limit() -> None:
    gate, _ = make_gate()
    chunks = [b"x" * 300] * 20  # 6 KB streamed, no Content-Length
    status, pulled = run(gate, "/v1/parse", {"x-internal-key": KEY}, chunks)
    assert status == 413
    assert pulled == 4  # stopped as soon as the running total passed 1 KB


def test_invalid_content_length_is_rejected() -> None:
    gate, _ = make_gate()
    status, _ = run(gate, "/v1/parse", {"x-internal-key": KEY, "content-length": "-5"}, [b""])
    assert status == 400


@pytest.mark.parametrize("size", [0, LIMIT])
def test_authenticated_request_within_limit_passes(size: int) -> None:
    gate, inner = make_gate()
    headers = {"x-internal-key": KEY, "content-length": str(size)}
    status, _ = run(gate, "/v1/parse", headers, [b"x" * size])
    assert status == 200
    assert inner.body == b"x" * size


@pytest.mark.parametrize("path", ["/health", "/health/"])
def test_public_path_needs_no_key(path: str) -> None:
    gate, inner = make_gate()
    status, _ = run(gate, path, {}, [b""])
    assert status == 200 and inner.reached


def test_trailing_slash_does_not_make_protected_paths_public() -> None:
    gate, inner = make_gate()
    status, _ = run(gate, "/v1/parse/", {}, [b""])
    assert (status, inner.reached) == (401, False)


@pytest.mark.parametrize("value", [" 512", "512 ", "\t512\t"])
def test_content_length_whitespace_is_accepted(value: str) -> None:
    gate, inner = make_gate()
    headers = {"x-internal-key": KEY, "content-length": value}
    status, _ = run(gate, "/v1/parse", headers, [b"x" * 512])
    assert status == 200 and inner.reached


def test_body_too_large_is_not_an_ordinary_exception() -> None:
    # FastAPI turns any Exception raised during body parsing into a 400; this must escape it.
    from app.middleware import _BodyTooLarge

    assert not issubclass(_BodyTooLarge, Exception)
