"""Prove a statement came from Safaricom, using the DKIM signature on the email that delivered it.

Safaricom signs the whole email, attachment included, so a valid signature means the PDF is byte
for byte what Safaricom sent. Everything happens in memory, and only the PDF is passed on: the
email's addresses and other headers are never stored or logged.
"""

from __future__ import annotations

import email
import email.policy
import re

import dkim

from app.ingest.parse import StatementError

SIGNER_DOMAIN = "safaricom.co.ke"
CHECK_NAME = "issued_by_safaricom"  # recorded in the signed integrity checks when proven

_NOT_VERIFIED = (
    "We couldn't confirm this email came from Safaricom. Download the original email again, "
    "or upload the PDF statement instead."
)


def _refuse() -> StatementError:
    return StatementError("email_not_verified", _NOT_VERIFIED)


def _signed_by_safaricom(raw: bytes) -> bool:
    """True if a signature from Safaricom's domain verifies and covers the sender and whole body."""
    checker = dkim.DKIM(raw, minkey=1024)
    count = sum(name.lower() == b"dkim-signature" for name, _ in checker.headers)
    for index in range(count):
        # Looked up here, not bound as a default, so that tests can replace the DNS query.
        if not checker.verify(index, dnsfunc=dkim.get_txt):
            continue
        tags = checker.signature_fields
        signed_headers = tags[b"h"].lower().replace(b" ", b"").split(b":")
        if (
            tags[b"d"].decode("ascii").lower() == SIGNER_DOMAIN
            and b"l" not in tags  # l= would leave anything after that length unsigned
            and b"from" in signed_headers
        ):
            return True
    return False


def extract_verified_pdf(eml: bytes) -> bytes:
    """Return the statement PDF from a Safaricom-signed email, or refuse."""
    raw = re.sub(rb"\r?\n", b"\r\n", eml)
    try:
        if not _signed_by_safaricom(raw):
            raise _refuse()
        message = email.message_from_bytes(raw, policy=email.policy.default)
        senders = message.get_all("From") or []
        addresses = senders[0].addresses if len(senders) == 1 else ()
        if len(addresses) != 1 or addresses[0].domain.lower() != SIGNER_DOMAIN:
            raise _refuse()
        attachments = [p.get_content() for p in message.iter_attachments()]
    except StatementError:
        raise
    except Exception:  # noqa: BLE001 - malformed mail and DNS failures raise many types
        raise _refuse() from None
    pdfs = [a for a in attachments if isinstance(a, bytes) and a.startswith(b"%PDF-")]
    if len(pdfs) != 1:
        raise StatementError(
            "no_statement_in_email", "That email doesn't contain one statement PDF."
        )
    return pdfs[0]
