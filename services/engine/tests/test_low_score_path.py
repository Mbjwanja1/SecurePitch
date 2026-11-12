"""What happens to a statement that fails integrity checks, from upload through to the seal.

Failed sums stop at upload. Any other failed check is a warning: the manager must acknowledge it
to save, both signers are shown it, and the dossier can then be sealed with its lower score.
"""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.crypto.signer import LocalSigner
from app.dossier import render
from app.main import create_app
from tests.fakes.statement import (
    PASSWORD,
    build_statement,
    lionesses_month,
    removed_row,
    summary_of,
    tampered_amount,
)
from tests.test_approvals import CLUB, DOSSIER, KEY, MANAGER, TREASURER, options, register, verify
from tests.test_matching import PEPPER_B64
from tests.test_seal import FAKE_PDF, SealDB

TAGS = [{"tx": "SJD0000001", "category": "meals"}]
WARNINGS = ["never_resaved", "producer_baseline"]


class PathDB(SealDB):
    """The fake database, extended so a saved draft is what the signers then read."""

    def __init__(self) -> None:
        super().__init__()
        self.created: list[dict] = []

    def roster(self, club_id):
        return []

    def fixtures(self, club_id):
        return []

    def create_draft_dossier(self, p):
        self.created.append(p)
        self.content = {
            "dossier": {
                "id": DOSSIER,
                "club_id": p["p_club"],
                "club_name": "Synthetic FC",
                "period_from": p["p_period_from"],
                "period_to": p["p_period_to"],
                "source_sha256": p["p_source_sha256"],
                "rows_total": p["p_rows_total"],
                "integrity": p["p_integrity"],
            },
            "items": [i | {"receipt_sha256": None} for i in p["p_items"]],
            "planned_spends": [],
        }
        return {"dossier_id": DOSSIER, "replaced_draft": False}


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    monkeypatch.setenv("ROSTER_PEPPER", PEPPER_B64)
    monkeypatch.setattr(render, "render_pdf", lambda context: FAKE_PDF)
    app = create_app()
    app.state.supabase = PathDB()
    app.state.signer = LocalSigner.generate("local-test")
    return TestClient(app), app.state.supabase


def resaved(pdf: bytes) -> bytes:
    """A second %%EOF, as an editor's incremental save leaves. The sums are untouched."""
    return pdf + b"\n%%EOF\n"


def preview(client, pdf: bytes):
    return client.post(
        f"/v1/clubs/{CLUB}/statements/parse",
        content=pdf,
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": MANAGER,
            "X-Statement-Password": PASSWORD,
            "Content-Type": "application/pdf",
        },
    )


def save(client, pdf: bytes, acknowledged: list[str] | None = None):
    body = {"statement_pdf": base64.b64encode(pdf).decode(), "tags": TAGS}
    if acknowledged is not None:
        body["acknowledged_checks"] = acknowledged
    return client.post(
        f"/v1/clubs/{CLUB}/dossiers",
        json=body,
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": MANAGER,
            "X-Statement-Password": PASSWORD,
        },
    )


@pytest.mark.parametrize(
    ("tamper", "reason"),
    [
        (tampered_amount, "balances don't add up"),
        (removed_row, "balances don't add up"),
    ],
)
def test_a_statement_whose_balances_dont_add_up_is_refused(engine, tamper, reason) -> None:
    client, db = engine
    pdf = build_statement(tamper(lionesses_month()))
    for r in (preview(client, pdf), save(client, pdf, WARNINGS)):
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "integrity_failed"
        assert reason in r.json()["detail"]["message"]
    assert db.created == []


def test_a_statement_whose_totals_dont_match_its_summary_is_refused(engine) -> None:
    client, db = engine
    month = lionesses_month()
    summary = summary_of(month)
    paid_in, paid_out = summary["TOTAL"]
    wrong = {**summary, "TOTAL": (paid_in + 100, paid_out)}
    r = preview(client, build_statement(month, summary=wrong))
    assert r.status_code == 422
    assert "totals don't match" in r.json()["detail"]["message"]
    assert "transactions" not in r.json()  # no rows reach the browser
    assert db.created == []


def test_acknowledging_cannot_rescue_a_statement_that_doesnt_add_up(engine) -> None:
    client, db = engine
    pdf = build_statement(tampered_amount(lionesses_month()))
    r = save(client, pdf, ["balance_chain", "summary_match", *WARNINGS])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "integrity_failed"
    assert db.created == []


@pytest.mark.parametrize(
    "acknowledged", [None, [], ["producer_baseline"], ["some_other_check", "never_resaved"]]
)
def test_every_warning_must_be_acknowledged_to_save(engine, acknowledged) -> None:
    client, db = engine
    r = save(client, resaved(build_statement(lionesses_month())), acknowledged)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "needs_acknowledgement"
    assert db.created == []


def test_a_clean_statement_needs_no_acknowledgement(engine) -> None:
    client, db = engine
    r = save(client, build_statement(lionesses_month(), producer="OpenPDF 1.3.30"))
    assert r.status_code == 200, r.text
    assert r.json()["integrity_score_bp"] == 10000
    assert db.created[0]["p_integrity"]["acknowledged"] == []


def test_a_low_score_statement_can_be_saved_signed_and_sealed_with_its_warnings_shown(
    engine,
) -> None:
    client, db = engine
    pdf = resaved(build_statement(lionesses_month()))

    # Upload: the manager sees the failures, and no rows are withheld for a warning.
    shown = preview(client, pdf)
    assert shown.status_code == 200, shown.text
    assert shown.json()["integrity"]["score_bp"] == 7500

    # Save: only an acknowledged warning gets through, and the acknowledgement is recorded.
    r = save(client, pdf, WARNINGS)
    assert r.status_code == 200, r.text
    stored = db.created[0]["p_integrity"]
    assert stored["score_bp"] == 7500
    assert sorted(stored["acknowledged"]) == WARNINGS

    # Signing: each signer is told which checks failed, not just a percentage.
    manager, treasurer = register(client, MANAGER), register(client, TREASURER)
    first = options(client, MANAGER)
    failed = first.json()["summary"]["failed_checks"]
    assert sorted(c["check"] for c in failed) == WARNINGS
    assert all(c["acknowledged"] and c["detail"] for c in failed)
    assert verify(client, MANAGER, manager.sign(first.json()["options"])).status_code == 200

    second = options(client, TREASURER)
    assert second.json()["summary"]["signing_as"] == "treasurer"
    assert second.json()["summary"]["failed_checks"] == failed
    assert second.json()["summary"]["integrity_score_bp"] == 7500

    # Seal: the lower score and the failed checks go into the signed record for the sponsor.
    done = verify(client, TREASURER, treasurer.sign(second.json()["options"]))
    assert done.status_code == 200 and done.json()["status"] == "sealed", done.text
    sealed = db.sealed["p_payload"]["integrity"]
    assert sealed["score_bp"] == 7500
    assert sealed["checks"]["never_resaved"] is False
    assert sealed["checks"]["producer_baseline"] is False
    assert sealed["checks"]["balance_chain"] is True
    assert "acknowledged" not in sealed  # the signed format is unchanged
