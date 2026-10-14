"""
The `require_operator` dependency, in its own module so both api.main and
api.recruitment can depend on it without importing each other.

Applied at ROUTER level rather than per-endpoint. Listing every protected path
by hand is how one gets missed, and the one that gets missed is never the
harmless one — `api/recruitment.py` holds both release endpoints.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.auth import AuthError, auth_enabled, verify_session

# auto_error=False so a missing header reaches our own handler and produces a
# consistent body, rather than FastAPI's bare 403.
_bearer = HTTPBearer(auto_error=False, description="Operator session token")


async def require_operator(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Returns the operator's username, or raises 401."""
    if not auth_enabled():
        return "auth-disabled"

    token = creds.credentials if creds else ""
    if not token:
        # Fallback for EventSource, which cannot set headers: the SSE stream
        # endpoint is a GET the browser opens directly.
        token = request.query_params.get("session", "")

    try:
        return verify_session(token)
    except AuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


#: Convenience for `dependencies=[...]` on a router or endpoint.
OperatorRequired = Depends(require_operator)
