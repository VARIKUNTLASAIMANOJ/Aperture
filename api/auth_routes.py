"""
Login / logout / whoami.

Unauthenticated by definition — this is the only HR-side router that must be,
and it is deliberately small so that stays obvious.
"""

from __future__ import annotations

import asyncio
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_operator
from core.auth import (
    auth_enabled, configured_password_hash, issue_session, operator_username,
    verify_password,
)
from utils.audit import emit_audit

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


@router.post("/login")
async def login(req: LoginRequest):
    if not auth_enabled():
        token, expires_at = issue_session(operator_username())
        return {"token": token, "expires_at": expires_at,
                "username": operator_username(), "auth_enabled": False}

    stored = configured_password_hash()

    # Both checks run before either result is used, and the failure path is
    # identical for a wrong username and a wrong password — otherwise response
    # timing and wording tell an attacker which half they got right.
    user_ok = secrets.compare_digest(req.username, operator_username())
    pass_ok = verify_password(req.password, stored) if stored else False

    if not (user_ok and pass_ok):
        # Blunt the obvious online guessing loop. Not a substitute for rate
        # limiting at the edge, which this deployment does not have.
        await asyncio.sleep(0.5)
        raise HTTPException(status_code=401, detail="Incorrect username or password.")

    token, expires_at = issue_session(req.username)
    return {"token": token, "expires_at": expires_at,
            "username": req.username, "auth_enabled": True}


@router.get("/me")
async def me(operator: str = Depends(require_operator)):
    """Used by the dashboard to decide whether a stored token is still good."""
    return {"username": operator, "auth_enabled": auth_enabled()}


@router.post("/logout")
async def logout(operator: str = Depends(require_operator)):
    """
    Sessions are stateless HMACs, so there is nothing server-side to revoke —
    the client discards the token. Kept as an endpoint so the audit trail
    records the intent, and so switching to server-side sessions later does
    not change the frontend.
    """
    emit_audit(
        node="auth", event="OPERATOR_LOGOUT",
        payload_summary=f"{operator} signed out.", actor=f"HR_{operator}",
    )
    return {"ok": True}
