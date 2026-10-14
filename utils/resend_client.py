"""
Resend email client — replaces all SMTP logic.

Resend SDK docs: https://resend.com/docs/send-with-python
Install:  pip install resend
"""

from __future__ import annotations

import os

import resend

DEFAULT_FROM = "HR Onboarding <hr@yourdomain.com>"


def send_email(to_email: str, subject: str, html_body: str) -> str:
    """
    Send a transactional HTML email via Resend.
    Returns the Resend message ID (e.g. "3d90e5a2-...").
    Raises on API error — caller should catch and mark item as FAILED.

    Env is read per-call rather than at import: this module is imported (via
    core.graph) before api/main.py runs load_dotenv(), so module-level capture
    would freeze an empty key regardless of what .env contains.
    """
    api_key      = os.environ.get("RESEND_API_KEY", "")
    from_address = os.environ.get("RESEND_FROM", DEFAULT_FROM)

    if not api_key:
        raise EnvironmentError(
            "RESEND_API_KEY env var is not set. "
            "Get your key at https://resend.com/api-keys"
        )

    # Fail here rather than burning an API call that Resend will 403. The
    # placeholder domain is never verifiable, and the provider's own error
    # ("domain is not verified") does not hint that the value is a leftover
    # default rather than a real domain awaiting DNS records.
    if "yourdomain.com" in from_address:
        raise EnvironmentError(
            f"RESEND_FROM is still the placeholder ({from_address!r}). "
            "Set it to an address on a domain you have verified at "
            "https://resend.com/domains — or, for testing without a domain, "
            "use 'onboarding@resend.dev', which can only deliver to the "
            "email address that owns the Resend account."
        )

    resend.api_key = api_key

    params: resend.Emails.SendParams = {
        "from":    from_address,
        "to":      [to_email],
        "subject": subject,
        "html":    html_body,
    }

    response = resend.Emails.send(params)
    return response["id"]