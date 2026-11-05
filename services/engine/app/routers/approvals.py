"""Passkey registration and passkey-signed approvals (ADR 0003).

As with the club endpoints, X-Actor-Id is the signed-in user from the web app's session (ADR 0002
rule 7). Roles are checked here and again inside approve_dossier().
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.approvals import passkeys, payload
from app.approvals.passkeys import PasskeyError, RelyingParty
from app.approvals.seal import SealError, seal
from app.crypto.signer import Signer, public_jwk
from app.security import require_internal_key
from app.supabase import Supabase, SupabaseError

router = APIRouter(prefix="/v1", dependencies=[Depends(require_internal_key)])

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SIGNER_FOR = {"draft": "manager", "submitted": "treasurer"}
_DB_ERROR_STATUS = {
    "42501": 403,
    "23505": 409,
    "23514": 422,
    "P0001": 422,
    "P0002": 404,
    "40001": 409,
}


def _deps(request: Request) -> tuple[Supabase, RelyingParty, str]:
    s = request.app.state.settings
    db: Supabase | None = getattr(request.app.state, "supabase", None)
    if db is None:
        raise HTTPException(
            503, {"code": "not_configured", "message": "Engine database settings are missing"}
        )
    rp = RelyingParty(s.webauthn_rp_id, s.webauthn_rp_name, s.webauthn_origins)
    return db, rp, s.internal_key


def _actor(x_actor_id: str) -> str:
    if not UUID_RE.match(x_actor_id or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "The actor ID must be a UUID"})
    return x_actor_id


def _db_error(exc: SupabaseError) -> HTTPException:
    return HTTPException(
        _DB_ERROR_STATUS.get(exc.code or "", 502), {"code": "database", "message": str(exc)}
    )


# Registration ---------------------------------------------------------------------------------


class RegisterOptionsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_name: str = Field(min_length=1, max_length=254)  # shown by the phone's passkey manager


class RegisterVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(max_length=1024)
    credential: dict[str, Any]


@router.post("/passkeys/register/options")
async def register_options(
    body: RegisterOptionsIn, request: Request, x_actor_id: str = Header(default="")
) -> dict[str, Any]:
    db, rp, key = _deps(request)
    actor = _actor(x_actor_id)
    existing = [p["id"] for p in await run_in_threadpool(db.passkeys, actor)]
    options, state = passkeys.registration_options(rp, key, actor, body.user_name, existing)
    return {"options": options, "state": state}


@router.post("/passkeys/register/verify")
async def register_verify(
    body: RegisterVerifyIn, request: Request, x_actor_id: str = Header(default="")
) -> dict[str, Any]:
    db, rp, key = _deps(request)
    actor = _actor(x_actor_id)
    try:
        new = passkeys.verify_registration(rp, key, actor, body.state, body.credential)
    except PasskeyError as exc:
        raise HTTPException(422, {"code": "passkey", "message": str(exc)}) from None
    try:
        await run_in_threadpool(
            db.add_passkey,
            {
                "p_actor": actor,
                "p_cred_id": new.cred_id,
                "p_public_key": new.public_key,
                "p_sign_count": new.sign_count,
                "p_transports": new.transports,
            },
        )
    except SupabaseError as exc:
        raise _db_error(exc) from None
    return {"cred_id": new.cred_id}


# Approvals ------------------------------------------------------------------------------------


async def _prepare(
    db: Supabase, dossier_id: str, actor: str
) -> tuple[dict[str, Any], dict, dict, bytes]:
    """Load the dossier, check it's this actor's turn to sign, and build the challenge."""
    if not UUID_RE.match(dossier_id):
        raise HTTPException(400, {"code": "bad_id", "message": "The dossier ID must be a UUID"})
    try:
        snapshot = await run_in_threadpool(db.approval_snapshot, dossier_id)
    except SupabaseError as exc:
        raise _db_error(exc) from None
    club_id = snapshot["dossier"]["club_id"]
    role = await run_in_threadpool(db.role_of, club_id, actor)
    if role is None:  # don't reveal that the dossier exists
        raise HTTPException(404, {"code": "not_found", "message": "Dossier not found"})
    needed = SIGNER_FOR.get(snapshot["status"])
    if needed is None:
        raise HTTPException(
            409, {"code": "not_signable", "message": "This dossier isn't waiting for a signature"}
        )
    if role != needed:
        raise HTTPException(
            403,
            {"code": "forbidden", "message": f"Only the club {needed} can sign this dossier now"},
        )
    approval, leaf_hashes = payload.build(snapshot)
    c = payload.challenge(approval)
    if snapshot["status"] == "submitted" and snapshot.get("manager_challenge") != c.hex():
        raise HTTPException(
            409,
            {
                "code": "mismatch",
                "message": "This dossier no longer matches what the manager signed",
            },
        )
    return snapshot, approval, leaf_hashes, c


def _summary(snapshot: dict[str, Any], approval: dict[str, Any], c: bytes) -> dict[str, Any]:
    """What the approver is shown before signing: the signed content, not the browser's copy."""
    return {
        "status": snapshot["status"],
        "signing_as": SIGNER_FOR[snapshot["status"]],
        "rows_total": approval["rows_total"],
        "rows_disclosed": approval["rows_disclosed"],
        "totals_cents": approval["totals_cents"],
        "integrity_score_bp": approval["integrity"]["score_bp"],
        "merkle_root": approval["merkle_root"],
        "challenge": c.hex(),
    }


class ApprovalVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential: dict[str, Any]


@router.post("/dossiers/{dossier_id}/approval/options")
async def approval_options(
    dossier_id: str, request: Request, x_actor_id: str = Header(default="")
) -> dict[str, Any]:
    db, rp, _ = _deps(request)
    actor = _actor(x_actor_id)
    snapshot, approval, _, c = await _prepare(db, dossier_id, actor)
    creds = await run_in_threadpool(db.passkeys, actor)
    if not creds:
        raise HTTPException(409, {"code": "no_passkey", "message": "Add a passkey before signing"})
    return {
        "options": passkeys.approval_options(rp, c, [p["id"] for p in creds]),
        "summary": _summary(snapshot, approval, c),
    }


@router.post("/dossiers/{dossier_id}/approval/verify")
async def approval_verify(
    dossier_id: str, body: ApprovalVerifyIn, request: Request, x_actor_id: str = Header(default="")
) -> dict[str, Any]:
    db, rp, _ = _deps(request)
    actor = _actor(x_actor_id)
    # Rebuilt from the database now, not taken from the options call: the assertion must sign
    # the dossier as it is at this moment, and approve_dossier() re-checks that under a lock.
    snapshot, _, leaf_hashes, c = await _prepare(db, dossier_id, actor)
    cred_id = body.credential.get("id")
    cred = next(
        (p for p in await run_in_threadpool(db.passkeys, actor) if p["id"] == cred_id), None
    )
    if cred is None:
        raise HTTPException(
            403, {"code": "passkey", "message": "That passkey isn't registered to you"}
        )
    try:
        a = passkeys.verify_approval(rp, c, body.credential, cred["public_key"], cred["sign_count"])
    except PasskeyError as exc:
        raise HTTPException(422, {"code": "passkey", "message": str(exc)}) from None
    try:
        result = await run_in_threadpool(
            db.approve_dossier,
            {
                "p_dossier": dossier_id,
                "p_actor": actor,
                "p_fingerprint": snapshot["fingerprint"],
                "p_challenge": c.hex(),
                "p_leaf_hashes": leaf_hashes if snapshot["status"] == "draft" else None,
                "p_cred_id": a.cred_id,
                "p_authenticator_data": a.authenticator_data,
                "p_client_data_json": a.client_data_json,
                "p_signature": a.signature,
                "p_sign_count": a.new_sign_count,
            },
        )
    except SupabaseError as exc:
        raise _db_error(exc) from None
    out = {**result, "challenge": c.hex()}
    if result.get("status") == "approved":
        # Seal straight away. If that fails the approval still stands: the dossier stays
        # approved and either approver can retry with POST /seal.
        try:
            out |= await _seal(request, db, rp, dossier_id)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
            out["seal_error"] = detail.get("message", "Sealing failed")
    return out


# Sealing --------------------------------------------------------------------------------------


async def _seal(
    request: Request,
    db: Supabase,
    rp: RelyingParty,
    dossier_id: str,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seal an approved dossier. `snapshot` is a seal_snapshot() result the caller already has."""
    signer: Signer | None = getattr(request.app.state, "signer", None)
    if signer is None:
        raise HTTPException(
            503, {"code": "not_configured", "message": "The platform signing key isn't configured"}
        )
    try:
        if snapshot is None:
            snapshot = await run_in_threadpool(db.seal_snapshot, dossier_id)
        sealed = await run_in_threadpool(seal, snapshot, rp, signer)
        await run_in_threadpool(
            db.seal_dossier,
            {
                "p_dossier": dossier_id,
                "p_merkle_root": sealed.merkle_root,
                "p_payload": sealed.payload,
                "p_kid": sealed.kid,
                "p_signature": sealed.signature,
                "p_pdf_path": None,  # the sealed PDF with its QR code comes in a later step
                "p_pdf_sha256": None,
            },
        )
    except SealError as exc:
        raise HTTPException(422, {"code": "seal", "message": str(exc)}) from None
    except SupabaseError as exc:
        raise _db_error(exc) from None
    return {"status": "sealed", "kid": sealed.kid, "sealed_at": sealed.payload["sealed_at"]}


@router.post("/dossiers/{dossier_id}/seal")
async def seal_now(
    dossier_id: str, request: Request, x_actor_id: str = Header(default="")
) -> dict[str, Any]:
    """Retry sealing an approved dossier (sealing normally happens when the treasurer signs)."""
    db, rp, _ = _deps(request)
    actor = _actor(x_actor_id)
    if not UUID_RE.match(dossier_id):
        raise HTTPException(400, {"code": "bad_id", "message": "The dossier ID must be a UUID"})
    try:
        # One read: seal_snapshot() is approval_snapshot() plus the stored signatures.
        snapshot = await run_in_threadpool(db.seal_snapshot, dossier_id)
    except SupabaseError as exc:
        raise _db_error(exc) from None
    role = await run_in_threadpool(db.role_of, snapshot["dossier"]["club_id"], actor)
    if role is None:
        raise HTTPException(404, {"code": "not_found", "message": "Dossier not found"})
    if role not in ("manager", "treasurer"):
        raise HTTPException(
            403, {"code": "forbidden", "message": "Only the manager or treasurer can seal"}
        )
    if snapshot["status"] != "approved":
        raise HTTPException(
            409, {"code": "not_sealable", "message": "Only an approved dossier can be sealed"}
        )
    return await _seal(request, db, rp, dossier_id, snapshot)


@router.get("/keys")
async def keys(request: Request) -> dict[str, Any]:
    """The platform's public key(s) as JWK, published by the web app at
    /.well-known/securepitch-keys.json (CRYPTO_SPEC section 5)."""
    signer: Signer | None = getattr(request.app.state, "signer", None)
    if signer is None:
        return {"keys": []}
    der = await run_in_threadpool(signer.public_key_der)
    return {"keys": [public_jwk(signer.kid, der)]}
