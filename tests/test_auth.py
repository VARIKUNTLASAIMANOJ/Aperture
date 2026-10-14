"""
Operator authentication, and the guard that keeps it from rotting.

The last test is the important one: it walks every route the app exposes and
fails if any of them is reachable without a session unless it is on an explicit
public allowlist. Adding an endpoint and forgetting to protect it is the exact
mistake that left the release endpoints open, and a reviewer will not catch it
reliably — this does.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
os.environ["CANDIDATE_TOKEN_SECRET"] = "test-secret-for-auth-tests"
os.environ["HR_AUTH_ENABLED"] = "true"
os.environ["HR_USERNAME"] = "hr"
os.environ["HR_PASSWORD"] = "correct-horse-battery-staple"

from core.auth import (  # noqa: E402
    AuthError, hash_password, issue_session, verify_password, verify_session,
)

#: Routes that must stay reachable without an operator session, each with the
#: reason. Anything not listed here has to be authenticated.
PUBLIC_ROUTES = {
    "/health":                                      "liveness probe",
    "/auth/login":                                  "cannot require a session to get one",
    "/openapi.json":                                "schema",
    "/docs":                                        "schema UI",
    "/docs/oauth2-redirect":                        "schema UI",
    "/redoc":                                       "schema UI",
    # Candidate-facing: no account exists, guarded by the signed thread token.
    "/candidate/{thread_id}/status":                "signed thread token",
    "/candidate/{thread_id}/offer/document":        "signed thread token",
    "/candidate/{thread_id}/appointment/document":  "signed thread token",
    "/candidate/{thread_id}/offer/accept":          "signed thread token",
    "/candidate/{thread_id}/offer/decline":         "signed thread token",
    # PDF downloads of the same two documents, under the same token and the
    # same Rule 5 check as their HTML counterparts above.
    "/candidate/{thread_id}/offer/document.pdf":       "signed thread token",
    "/candidate/{thread_id}/appointment/document.pdf": "signed thread token",
    # The voice worker is a machine; it carries the same signed thread token.
    "/voice/calls/{call_id}/outcome":               "signed thread token",
}


# ── Password hashing ────────────────────────────────────────────────────────

def test_password_round_trips():
    stored = hash_password("s3cret-password")
    assert verify_password("s3cret-password", stored)


def test_wrong_password_rejected():
    assert not verify_password("nope", hash_password("s3cret-password"))


def test_hash_is_salted():
    """Two hashes of the same password must differ, or a rainbow table works."""
    assert hash_password("same") != hash_password("same")


def test_plaintext_is_not_recoverable_from_the_hash():
    stored = hash_password("s3cret-password")
    assert "s3cret-password" not in stored
    assert stored.startswith("scrypt$")


@pytest.mark.parametrize("garbage", ["", "notahash", "scrypt$only-two", "md5$a$b"])
def test_malformed_stored_hash_fails_closed(garbage):
    assert not verify_password("anything", garbage)


# ── Sessions ────────────────────────────────────────────────────────────────

def test_session_round_trips():
    token, _ = issue_session("hr")
    assert verify_session(token) == "hr"


def test_expired_session_rejected():
    token, _ = issue_session("hr", ttl_hours=-1)
    with pytest.raises(AuthError):
        verify_session(token)


def test_tampered_session_rejected():
    """Editing the username must invalidate the signature."""
    import base64
    token, _ = issue_session("hr")
    _, expiry, sig = token.split(".")
    forged_user = base64.urlsafe_b64encode(b"admin").decode().rstrip("=")
    with pytest.raises(AuthError):
        verify_session(f"{forged_user}.{expiry}.{sig}")


def test_extended_expiry_rejected():
    """Pushing the expiry out must invalidate the signature too."""
    token, _ = issue_session("hr")
    user, expiry, sig = token.split(".")
    with pytest.raises(AuthError):
        verify_session(f"{user}.{int(expiry) + 999999}.{sig}")


@pytest.mark.parametrize("garbage", ["", "a", "a.b", "a.b.c.d", "....."])
def test_malformed_session_rejected(garbage):
    with pytest.raises(AuthError):
        verify_session(garbage)


# ── HTTP ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    import api.main as main_mod
    # TestClient would normally run the lifespan, which needs Postgres and
    # would start the scheduler. These tests only exercise routing and auth.
    with TestClient(main_mod.app) as _c:  # noqa: F841
        pass
    return TestClient(main_mod.app)


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/auth/login",
                    json={"username": "hr", "password": "correct-horse-battery-staple"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def test_login_succeeds_with_correct_credentials(token):
    assert token


def test_login_rejects_wrong_password(client):
    r = client.post("/auth/login", json={"username": "hr", "password": "wrong"})
    assert r.status_code == 401


def test_login_rejects_unknown_user(client):
    r = client.post("/auth/login",
                    json={"username": "admin", "password": "correct-horse-battery-staple"})
    assert r.status_code == 401


def test_login_failure_does_not_say_which_half_was_wrong(client):
    """Distinct messages would confirm valid usernames."""
    a = client.post("/auth/login", json={"username": "hr", "password": "wrong"})
    b = client.post("/auth/login", json={"username": "nobody", "password": "wrong"})
    assert a.json()["detail"] == b.json()["detail"]


def test_release_endpoints_reject_anonymous_callers(client):
    """The two that actually issue employment documents."""
    for path in ("/onboarding/t1/offer/release",
                 "/onboarding/t1/appointment/release"):
        r = client.post(path, json={"released_by": "attacker"})
        assert r.status_code == 401, f"{path} is reachable without a session"


def test_release_endpoints_reject_a_forged_session(client):
    r = client.post("/onboarding/t1/offer/release",
                    json={"released_by": "attacker"},
                    headers={"Authorization": "Bearer forged.123.signature"})
    assert r.status_code == 401


def test_me_requires_a_session(client, token):
    assert client.get("/auth/me").status_code == 401
    ok = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200 and ok.json()["username"] == "hr"


def test_health_stays_public(client):
    assert client.get("/health").status_code == 200


def test_candidate_endpoints_are_not_behind_operator_auth(client):
    """
    A candidate has no login. Reaching these without a session must fail on the
    THREAD TOKEN (403), never on the operator session (401) — a 401 here would
    mean the candidate portal is locked out entirely.
    """
    r = client.get("/candidate/t1/status", params={"token": "bogus"})
    assert r.status_code != 401, "candidate endpoint must not require an operator session"


# ── The guard that matters ──────────────────────────────────────────────────

def test_every_route_is_protected_or_explicitly_public(client):
    """
    Walk every route the app exposes and call it with no credentials.

    Behavioural, not structural, and deliberately so: `include_router(...,
    dependencies=[...])` applies the dependency at inclusion time, so it does
    NOT appear on the route objects or on `original_router`. An inspection-based
    check reported the release endpoints as unprotected while they were in fact
    returning 401 — and would equally have reported a genuinely open endpoint as
    fine. Issuing the request is the only honest test.
    """
    import re

    leaked: list[str] = []
    for path, operations in client.app.openapi()["paths"].items():
        if path in PUBLIC_ROUTES:
            continue
        concrete = re.sub(r"{[^}]+}", "1", path)
        for method in operations:
            if method not in ("get", "post", "put", "delete", "patch"):
                continue
            r = client.request(
                method.upper(), concrete,
                json={} if method in ("post", "put", "patch") else None,
            )
            if r.status_code != 401:
                leaked.append(f"{method.upper()} {path} -> {r.status_code}")

    assert not leaked, (
        "These routes answered an unauthenticated request with something other "
        "than 401. Protect them, or add them to PUBLIC_ROUTES with a reason:\n  "
        + "\n  ".join(sorted(leaked))
    )


def test_public_routes_are_actually_reachable(client):
    """
    The mirror of the above: an allowlisted route must NOT demand a session.

    Without this, 'protect everything' would pass the guard above by locking
    the candidate portal out of its own endpoints.
    """
    import re

    locked: list[str] = []
    for path in PUBLIC_ROUTES:
        if path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            continue
        concrete = re.sub(r"{[^}]+}", "1", path)
        for method in ("get", "post"):
            r = client.request(method.upper(), concrete,
                               json={} if method == "post" else None)
            if r.status_code == 401:
                locked.append(f"{method.upper()} {path}")

    assert not locked, (
        "These are meant to be reachable without an operator session but "
        "returned 401:\n  " + "\n  ".join(sorted(locked))
    )


def test_the_guard_itself_catches_an_open_route(client):
    """
    Negative control. A guard that silently inspects nothing passes forever;
    this proves it fails when something really is exposed.
    """
    import re

    @client.app.get("/__test_unprotected__")
    async def _open():  # pragma: no cover - never called
        return {}

    client.app.openapi_schema = None          # force a rebuild
    try:
        leaked = []
        for path, operations in client.app.openapi()["paths"].items():
            if path in PUBLIC_ROUTES:
                continue
            concrete = re.sub(r"{[^}]+}", "1", path)
            for method in operations:
                if method != "get":
                    continue
                if client.request("GET", concrete).status_code != 401:
                    leaked.append(path)
        assert "/__test_unprotected__" in leaked
    finally:
        client.app.routes[:] = [
            r for r in client.app.routes
            if getattr(r, "path", "") != "/__test_unprotected__"
        ]
        client.app.openapi_schema = None


# ── The frontend half of the same concern ───────────────────────────────────

def test_no_component_bypasses_the_api_client():
    """
    Every browser request must go through lib/api.ts.

    `request()` is where the Authorization header is attached. A component
    calling `fetch()` directly sends none, so the moment an endpoint moves
    behind auth that call starts returning 401 — which is exactly what
    happened: CompensationStep fetched /meta/locations and /meta/ctc-preview
    raw, so after the auth pass the state dropdown sat on "Loading…" forever
    and the salary preview showed "Sign in to continue."

    The route guard above cannot catch this; it checks the server. This checks
    the only other side that can get it wrong.
    """
    import re

    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    if not os.path.isdir(root):
        pytest.skip("frontend/ not present")

    # EventSource cannot set headers; it carries the session in the query
    # string instead, and api.streamUrl is the one place that is built.
    allowed = {os.path.join("lib", "api.ts")}
    offenders = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in {"node_modules", ".next", "out", "dist"}]
        for name in filenames:
            if not name.endswith((".ts", ".tsx")):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if rel in allowed:
                continue
            with open(full, encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    if re.search(r"(?<![.\w])fetch\s*\(", line) and "// allow-raw-fetch" not in line:
                        offenders.append(f"{rel}:{lineno}: {line.strip()[:90]}")

    assert not offenders, (
        "These call fetch() directly instead of going through lib/api.ts, so "
        "they send no Authorization header and will 401 against any "
        "authenticated endpoint:\n  " + "\n  ".join(offenders)
    )
