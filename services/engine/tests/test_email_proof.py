"""Statements proven by the DKIM signature on Safaricom's email. All keys and mail are synthetic."""

from __future__ import annotations

import base64
import hashlib
from email.message import EmailMessage
from pathlib import Path

import dkim
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.approvals import payload
from app.ingest.email_proof import CHECK_NAME, SIGNER_DOMAIN, extract_verified_pdf
from app.ingest.parse import StatementError
from tests.fakes.statement import PASSWORD, build_statement, lionesses_month
from tests.test_approvals import CLUB, KEY, MANAGER
from tests.test_low_score_path import TAGS, engine, preview, save  # noqa: F401

SENDER = f"statements@{SIGNER_DOMAIN}"
FAKE_PDF = b"%PDF-1.5 synthetic statement\n" + b"x" * 400
PRIVATE = Path(__file__).resolve().parents[3] / "fixtures" / "private"

_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private_pem = _key.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.TraditionalOpenSSL,
    serialization.NoEncryption(),
)
_public_der = _key.public_key().public_bytes(
    serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
)
_record = b"v=DKIM1; k=rsa; p=" + base64.b64encode(_public_der)


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    monkeypatch.setattr(dkim, "get_txt", lambda name, timeout=5: _record)


def mail(pdf=FAKE_PDF, sender=SENDER, attachments=1) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "club@example.test"
    msg["Subject"] = "M-PESA Statement"
    msg.set_content("Your statement is attached.")
    for i in range(attachments):
        msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=f"s{i}.pdf")
    return msg.as_bytes(policy=msg.policy.clone(linesep="\r\n"))


def signed(raw: bytes, domain=SIGNER_DOMAIN, length=False) -> bytes:
    header = dkim.sign(
        raw,
        b"selector",
        domain.encode(),
        _private_pem,
        canonicalize=(b"simple", b"simple"),
        include_headers=[b"from", b"to", b"subject"],
        length=length,
    )
    return header + raw


def code_of(eml: bytes) -> str:
    with pytest.raises(StatementError) as err:
        extract_verified_pdf(eml)
    return err.value.code


def test_a_signed_email_gives_back_the_exact_pdf() -> None:
    assert extract_verified_pdf(signed(mail())) == FAKE_PDF


def test_line_endings_changed_by_a_download_dont_matter() -> None:
    assert extract_verified_pdf(signed(mail()).replace(b"\r\n", b"\n")) == FAKE_PDF


def test_changing_one_character_of_the_attachment_is_refused() -> None:
    eml = bytearray(signed(mail()))
    i = len(eml) // 2 + 200
    eml[i] = ord("A") if eml[i] != ord("A") else ord("B")
    assert code_of(bytes(eml)) == "email_not_verified"


@pytest.mark.parametrize(
    "eml",
    [
        pytest.param(lambda: mail(), id="unsigned"),
        pytest.param(lambda: signed(mail(), domain="example.test"), id="signed by another domain"),
        pytest.param(
            lambda: signed(mail(), domain="mail.safaricom.co.ke.example.test"),
            id="lookalike domain",
        ),
        pytest.param(lambda: signed(mail(), length=True), id="only part of the body is signed"),
        pytest.param(lambda: signed(mail(sender="x@example.test")), id="sender outside safaricom"),
        pytest.param(
            lambda: b"From: attacker@example.test\r\n" + signed(mail()), id="a second From added"
        ),
        pytest.param(lambda: b"this is not an email at all", id="garbage"),
        pytest.param(lambda: b"", id="empty"),
    ],
)
def test_emails_that_dont_prove_safaricom_sent_them_are_refused(eml) -> None:
    assert code_of(eml()) == "email_not_verified"


def test_a_signature_that_fails_its_time_checks_is_refused(monkeypatch) -> None:
    eml = signed(mail())
    monkeypatch.setattr("dkim.time.time", lambda: 1_000_000)  # long before t= says it was signed
    assert code_of(eml) == "email_not_verified"


def test_a_missing_or_unreachable_key_is_refused_not_crashed(monkeypatch) -> None:
    eml = signed(mail())
    monkeypatch.setattr(dkim, "get_txt", lambda name, timeout=5: None)
    assert code_of(eml) == "email_not_verified"

    def unreachable(name, timeout=5):
        raise dkim.DnsTimeoutError("timed out")

    monkeypatch.setattr(dkim, "get_txt", unreachable)
    assert code_of(eml) == "email_not_verified"


@pytest.mark.parametrize(
    "eml",
    [
        pytest.param(lambda: signed(mail(attachments=0)), id="no attachment"),
        pytest.param(lambda: signed(mail(attachments=2)), id="two statements"),
        pytest.param(lambda: signed(mail(pdf=b"not a pdf")), id="attachment is not a PDF"),
    ],
)
def test_the_email_must_hold_exactly_one_statement(eml) -> None:
    assert code_of(eml()) == "no_statement_in_email"


# ---- through the engine ---------------------------------------------------------------------


def statement_email(**kw) -> bytes:
    return signed(mail(pdf=build_statement(lionesses_month(), **kw)))


def preview_email(client, eml: bytes):
    return client.post(
        f"/v1/clubs/{CLUB}/statements/parse",
        content=eml,
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": MANAGER,
            "X-Statement-Password": PASSWORD,
            "Content-Type": "message/rfc822",
        },
    )


def save_email(client, body: dict):
    return client.post(
        f"/v1/clubs/{CLUB}/dossiers",
        json={"tags": TAGS, "acknowledged_checks": ["producer_baseline"], **body},
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": MANAGER,
            "X-Statement-Password": PASSWORD,
        },
    )


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_an_email_preview_says_it_was_issued_by_safaricom(engine) -> None:  # noqa: F811
    client, _ = engine
    r = preview_email(client, statement_email())
    assert r.status_code == 200, r.text
    assert r.json()["integrity"]["checks"][CHECK_NAME]["passed"] is True
    assert r.json()["integrity"]["score_bp"] == 9500  # proof is reported, it doesn't add points


def test_a_saved_email_puts_the_proof_in_what_the_signers_sign(engine) -> None:  # noqa: F811
    client, db = engine
    pdf = build_statement(lionesses_month())
    r = save_email(client, {"statement_email": b64(signed(mail(pdf=pdf)))})
    assert r.status_code == 200, r.text
    stored = db.created[0]
    assert stored["p_source_sha256"] == hashlib.sha256(pdf).hexdigest()
    assert stored["p_integrity"]["checks"][CHECK_NAME]["passed"] is True
    signed_payload, _ = payload.build(db.approval_snapshot(db.content["dossier"]["id"]))
    assert signed_payload["integrity"]["checks"][CHECK_NAME] is True


def test_a_plain_pdf_records_no_proof(engine) -> None:  # noqa: F811
    client, db = engine
    pdf = build_statement(lionesses_month())
    assert CHECK_NAME not in preview(client, pdf).json()["integrity"]["checks"]
    assert save(client, pdf, ["producer_baseline"]).status_code == 200
    assert CHECK_NAME not in db.created[0]["p_integrity"]["checks"]


def test_a_tampered_email_is_refused_at_preview_and_save(engine) -> None:  # noqa: F811
    client, db = engine
    eml = bytearray(statement_email())
    i = len(eml) // 2 + 200
    eml[i] = ord("A") if eml[i] != ord("A") else ord("B")
    for r in (
        preview_email(client, bytes(eml)),
        save_email(client, {"statement_email": b64(bytes(eml))}),
    ):
        assert r.status_code == 422 and r.json()["detail"]["code"] == "email_not_verified"
    assert db.created == []


@pytest.mark.parametrize(
    "fields", [{}, {"statement_pdf": "QQ==", "statement_email": "QQ=="}], ids=["neither", "both"]
)
def test_exactly_one_statement_source_is_required(engine, fields) -> None:  # noqa: F811
    client, db = engine
    assert save_email(client, fields).status_code == 422
    assert db.created == []


def test_a_proven_email_still_has_to_add_up(engine, monkeypatch) -> None:  # noqa: F811
    from tests.fakes.statement import tampered_amount

    client, db = engine
    eml = signed(mail(pdf=build_statement(tampered_amount(lionesses_month()))))
    r = preview_email(client, eml)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "integrity_failed"


@pytest.mark.skipif(not list(PRIVATE.glob("*.eml")), reason="no real email in fixtures/private/")
def test_real_statement_email_verifies(monkeypatch) -> None:
    monkeypatch.undo()  # the real DNS record, not the fake one
    raw = next(PRIVATE.glob("*.eml")).read_bytes()
    assert extract_verified_pdf(raw).startswith(b"%PDF-")
