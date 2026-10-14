"""
Signed candidate access tokens.

The application has no user accounts, so a candidate is identified by a token
carried in their emailed link. The token is an HMAC over (thread_id, purpose,
expiry) — the server RE-DERIVES the signature and compares in constant time,
so a token cannot be forged or edited to point at another candidate's thread.

This is what makes Rule 5 ("the candidate must not see the Appointment Letter
until HR releases it") an actual access control rather than an unguessable URL:
knowing a thread_id is not enough, and an offer token cannot be replayed
against the appointment endpoint because `purpose` is inside the signature.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

# Purposes are part of the signed payload so a token minted for one action
# cannot be reused for another.
PURPOSE_OFFER = "offer"
PURPOSE_APPOINTMENT = "appointment"

DEFAULT_TTL_DAYS = 30


def _secret() -> bytes:
    """
    Reuses the PII encryption key material rather than introducing a second
    secret to manage. Read lazily — api/main.py loads .env after import.
    """
    raw = os.environ.get("CANDIDATE_TOKEN_SECRET") or os.environ.get("PII_ENCRYPTION_KEY_B64")
    if not raw:
        raise EnvironmentError(
            "Set CANDIDATE_TOKEN_SECRET (or PII_ENCRYPTION_KEY_B64) — candidate "
            "links cannot be signed without it."
        )
    return raw.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _sign(thread_id: str, purpose: str, expires_at: int) -> str:
    msg = f"{thread_id}|{purpose}|{expires_at}".encode()
    return _b64(hmac.new(_secret(), msg, hashlib.sha256).digest())


def issue_token(thread_id: str, purpose: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    """Returns `<expiry>.<signature>` — opaque to the candidate."""
    expires_at = int(time.time()) + ttl_days * 86400
    return f"{expires_at}.{_sign(thread_id, purpose, expires_at)}"


class TokenError(Exception):
    """Raised for malformed, expired, mismatched or forged tokens."""


def verify_token(token: str, thread_id: str, purpose: str) -> None:
    """Raises TokenError unless the token is valid for exactly this thread and purpose."""
    if not token or "." not in token:
        raise TokenError("Malformed access link.")

    raw_expiry, _, signature = token.partition(".")
    try:
        expires_at = int(raw_expiry)
    except ValueError:
        raise TokenError("Malformed access link.") from None

    if expires_at < int(time.time()):
        raise TokenError("This link has expired. Ask HR to send a new one.")

    expected = _sign(thread_id, purpose, expires_at)
    # compare_digest: constant time, so a wrong signature leaks no information
    # about how much of it was correct.
    if not hmac.compare_digest(expected, signature):
        raise TokenError("This link is not valid for this candidate.")


def mask_pan(pan: str) -> str:
    """ABCDE1234F → XXXXX1234F. Enough to confirm, useless if leaked."""
    return f"XXXXX{pan[5:]}" if pan and len(pan) == 10 else "—"


def mask_aadhaar(aadhaar: str) -> str:
    """12 digits → XXXX XXXX 9012 — the UIDAI-recommended display form."""
    return f"XXXX XXXX {aadhaar[-4:]}" if aadhaar and len(aadhaar) == 12 else "—"


def mask_account(number: str) -> str:
    return f"{'X' * max(0, len(number) - 4)}{number[-4:]}" if number else "—"
