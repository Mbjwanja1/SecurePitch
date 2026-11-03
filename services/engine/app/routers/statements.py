"""POST /v1/statements/parse: parse an M-Pesa statement in memory and return its rows.

The PDF is the raw request body (Content-Type: application/pdf) and the password travels in the
X-Statement-Password header. Raw bytes rather than a multipart upload, because multipart files
larger than 1 MB are spooled to a temporary file on disk. Nothing is stored or logged; the
response goes back to the coach's own browser through the web app.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from app.ingest.models import Kind, ParsedStatement, Row
from app.ingest.parse import StatementError, parse_statement
from app.security import require_internal_key

router = APIRouter()

_ERROR_STATUS = {
    "wrong_password": 422,
    "not_a_pdf": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
}


def _row_json(r: Row) -> dict[str, Any]:
    cp = r.counterparty
    return {
        "tx": r.tx,
        "ts": r.ts.isoformat(),
        "dir": r.direction,
        "amount_cents": r.amount_cents,
        "fee_cents": r.fee_cents,
        "balance_cents": r.balance_cents,
        "kind": r.kind.value,
        "details": r.details,
        "counterparty": {
            "type": cp.type,
            "mask_key": cp.mask_key,
            "name": cp.name,
            "number": cp.number,
            "account": cp.account,
        },
    }


def _statement_json(p: ParsedStatement) -> dict[str, Any]:
    transactions = [r for r in p.rows if r.kind is not Kind.CHARGE or r.fee_of is None]
    return {
        "source_sha256": p.source_sha256,
        "pages": p.pages,
        "period": {
            "from": p.period_from.isoformat() if p.period_from else None,
            "to": p.period_to.isoformat() if p.period_to else None,
        },
        "rows_total": len(p.rows),
        "verification_code": p.verification_code,
        "integrity": {
            "score_bp": p.integrity.score_bp,
            "checks": {
                name: {"passed": c.passed, "weight_bp": c.weight_bp, "detail": c.detail}
                for name, c in p.integrity.checks.items()
            },
        },
        # Charges are folded into their transaction's fee_cents; unattached ones stay as rows.
        "transactions": [_row_json(r) for r in transactions],
    }


@router.post("/v1/statements/parse", dependencies=[Depends(require_internal_key)])
async def parse(
    request: Request,
    x_statement_password: str = Header(default=""),
) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send the PDF as application/pdf"
        )
    body = await request.body()  # bounded by RequestGate's size limit
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The request body is empty")
    try:
        parsed = await run_in_threadpool(parse_statement, body, x_statement_password)
    except StatementError as exc:
        raise HTTPException(
            _ERROR_STATUS.get(exc.code, 422),
            {"code": exc.code, "message": exc.message},
        ) from None
    finally:
        del body
    return _statement_json(parsed)
