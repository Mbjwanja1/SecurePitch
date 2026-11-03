"""RFC 8785 canonical JSON, with the SecurePitch rule that floats are never hashed or signed."""

import base64
import hashlib
from typing import Any

import rfc8785

MAX_SAFE_INTEGER = 2**53 - 1


class CanonicalizationError(ValueError):
    pass


def _check(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CanonicalizationError(f"{path}: integer outside JavaScript's safe range")
        return
    if isinstance(value, float):
        raise CanonicalizationError(f"{path}: floats are not allowed; use cents or basis points")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(f"{path}: object keys must be strings")
            _check(item, f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for i, item in enumerate(value):
            _check(item, f"{path}[{i}]")
        return
    raise CanonicalizationError(f"{path}: unsupported type {type(value).__name__}")


def canonicalize(value: Any) -> bytes:
    """Serialise a JSON-compatible value to canonical UTF-8 bytes."""
    _check(value, "$")
    return rfc8785.dumps(value)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
