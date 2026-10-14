"""
Operator authentication for the HR console.

The candidate side has always been guarded by signed per-thread tokens
(utils.tokens). The HR side had nothing: anyone who could reach port 8000 could
release an Offer Letter or an Appointment Letter, and with CORS open to `*`
that included any page in an operator's browser.

Design, and why:

* **Password → signed session token**, not an API key. A key baked into the
  frontend bundle is readable by anyone who opens devtools, so it would
  authenticate nothing. A login exchanges a secret the browser never stores for
  a short-lived token that it does.

* **HMAC, reusing utils.tokens' secret.** Same construction as the candidate
  links, so there is one signing secret to manage and one place to reason about
  forgery. Sessions are stateless — no table, nothing to clean up — at the cost
  of not being individually revocable; rotating the secret logs everyone out.

* **scrypt from the standard library**, not bcrypt/passlib. The password is
  compared against a derived hash so a leaked `.env` does not hand over a
  reusable credential, and it adds no dependency.

* **Bearer token, not an HttpOnly cookie.** The dashboard (:3000) and the API
  (:8000) are different origins, so a cookie would need `SameSite=None; Secure`
  and therefore HTTPS — which this does not have locally. The honest trade-off:
  a token the frontend holds is reachable by XSS in a way an HttpOnly cookie is
  not. Behind a single origin and TLS, switch to the cookie.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

SESSION_PURPOSE = "hr-session"
DEFAULT_SESSION_HOURS = 12

#: scrypt parameters. n=2**14 keeps a login under ~100ms on a laptop while
#: making an offline guess of a leaked hash expensive.
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

#: Set at startup when no HR_PASSWORD is configured, so a fresh clone is
#: locked by default instead of either refusing to boot or running wide open.
_generated_password: str | None = None


def _secret() -> bytes:
    raw = os.environ.get("CANDIDATE_TOKEN_SECRET") or os.environ.get("PII_ENCRYPTION_KEY_B64")
    if not raw:
        raise EnvironmentError(
            "Set CANDIDATE_TOKEN_SECRET (or PII_ENCRYPTION_KEY_B64) — operator "
            "sessions cannot be signed without it."
        )
    return raw.encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


# ── Passwords ───────────────────────────────────────────────────────────────

def hash_password(password: str, salt: bytes | None = None) -> str:
    """Returns `scrypt$<salt>$<hash>`, both base64."""
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${_b64(salt)}${_b64(dk)}"


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check against a `scrypt$salt$hash` string."""
    try:
        scheme, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=_unb64(salt_b64), **_SCRYPT)
    except Exception:
        return False
    return hmac.compare_digest(_b64(dk), hash_b64)


def operator_username() -> str:
    return os.environ.get("HR_USERNAME", "hr")


def configured_password_hash() -> str | None:
    """
    The hash to check against, from (in order):

      HR_PASSWORD_HASH  — preferred; the plaintext never touches the file
      HR_PASSWORD       — convenience for local work, hashed on read
      a generated one   — see bootstrap()
    """
    stored = os.environ.get("HR_PASSWORD_HASH", "").strip()
    if stored:
        return stored
    plain = os.environ.get("HR_PASSWORD", "").strip()
    if plain:
        return hash_password(plain)
    if _generated_password:
        return hash_password(_generated_password)
    return None


def bootstrap() -> str | None:
    """
    Called once at startup. If no password is configured, invent one.

    Refusing to boot would be hostile to a fresh clone; defaulting to a known
    password would be worse than no auth at all, because it would look secure.
    A random password printed once to the operator's own console is neither.
    Returns it so the caller can print it, or None if one was configured.
    """
    global _generated_password
    if os.environ.get("HR_PASSWORD_HASH") or os.environ.get("HR_PASSWORD"):
        return None
    _generated_password = secrets.token_urlsafe(12)
    return _generated_password


def auth_enabled() -> bool:
    """
    Off only by an explicit opt-out, so forgetting to configure it leaves the
    console protected rather than exposed.
    """
    return os.environ.get("HR_AUTH_ENABLED", "true").lower() not in ("0", "false", "no")


# ── Sessions ────────────────────────────────────────────────────────────────

def _sign(username: str, expires_at: int) -> str:
    msg = f"{username}|{SESSION_PURPOSE}|{expires_at}".encode()
    return _b64(hmac.new(_secret(), msg, hashlib.sha256).digest())


def issue_session(username: str, ttl_hours: int | None = None) -> tuple[str, int]:
    """Returns (`<username>.<expiry>.<signature>`, expires_at)."""
    hours = ttl_hours or int(os.environ.get("HR_SESSION_HOURS", DEFAULT_SESSION_HOURS))
    expires_at = int(time.time()) + hours * 3600
    return f"{_b64(username.encode())}.{expires_at}.{_sign(username, expires_at)}", expires_at


class AuthError(Exception):
    """Raised for a missing, malformed, expired or forged session."""


def verify_session(token: str) -> str:
    """Returns the operator's username, or raises AuthError."""
    if not token:
        raise AuthError("Sign in to continue.")

    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Malformed session.")

    raw_user, raw_expiry, signature = parts
    try:
        username = _unb64(raw_user).decode()
        expires_at = int(raw_expiry)
    except Exception:
        raise AuthError("Malformed session.") from None

    if expires_at < int(time.time()):
        raise AuthError("Your session has expired. Sign in again.")

    if not hmac.compare_digest(_sign(username, expires_at), signature):
        raise AuthError("Invalid session.")

    return username
