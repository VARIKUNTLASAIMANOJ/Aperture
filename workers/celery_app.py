"""
Celery Application — Background Task Workers
─────────────────────────────────────────────
Handles time-sensitive scheduled tasks:
  - Contract expiry alerts (T-30, T-15, T-7)
  - Periodic onboarding status digests
  
Run with: celery -A workers.celery_app worker --loglevel=info --beat
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import resend
from celery import Celery
from celery.schedules import crontab

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "onboarding_workers",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer      = "json",
    accept_content       = ["json"],
    result_serializer    = "json",
    timezone             = "UTC",
    enable_utc           = True,
    task_acks_late       = True,           # tasks re-queued if worker crashes
    task_reject_on_worker_lost = True,
)

# ---------------------------------------------------------------------------
# Scheduled beat tasks
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # Scan for contracts expiring in the next 30 days — run daily at 08:00 UTC
    "scan-contract-expirations-daily": {
        "task":     "workers.celery_app.scan_and_dispatch_expiry_alerts",
        "schedule": crontab(hour=8, minute=0),
    },
}


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

# Resend config
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
FROM_ADDRESS   = os.environ.get("RESEND_FROM", "HR Onboarding <hr@yourdomain.com>")


def _resend_send(to: str, subject: str, html: str) -> str:
    """Send via Resend API. Returns message_id."""
    resend.api_key = RESEND_API_KEY
    response = resend.Emails.send({
        "from":    FROM_ADDRESS,
        "to":      [to],
        "subject": subject,
        "html":    html,
    })
    return response["id"]


@celery_app.task(
    name="workers.celery_app.send_contract_expiry_alert",
    bind=True,
    max_retries=3,
    default_retry_delay=300,   # 5-min retry backoff
)
def send_contract_expiry_alert(self, candidate_id: str, days_remaining: int, email: str, name: str, role: str):
    """
    Send a contract-expiry notification via Resend at T-30, T-15, T-7.
    Retries up to 3 times with 5-minute backoff on failure.
    """
    try:
        subject = f"[Action Required] Contract Expiry in {days_remaining} Days — {name}"
        html = f"""
        <html><body style="font-family: sans-serif; color: #1a1a2e;">
            <h2>Contract Renewal Notice</h2>
            <p>Hello,</p>
            <p>This is an automated reminder that the contract for <strong>{name}</strong>
            ({role}) will expire in <strong>{days_remaining} days</strong>.</p>
            <p>Please take the appropriate action in the HR portal before the expiry date.</p>
            <p style="margin-top:24px; color:#666;">Enterprise Onboarding System</p>
        </body></html>
        """
        _resend_send(to=email, subject=subject, html=html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery_app.task(name="workers.celery_app.scan_and_dispatch_expiry_alerts")
def scan_and_dispatch_expiry_alerts():
    """
    Daily beat task: query DB for contractors whose end_date falls within
    30 days, and dispatch appropriate alerts.
    
    Production: replace the stub below with a real DB query.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(os.environ.get("SYNC_DATABASE_URL", "postgresql://postgres:postgres@localhost/onboarding_db"))
    today = date.today()

    with engine.connect() as conn:
        # Query contractors with end_dates approaching
        # (assumes a `contractors` table with end_date, email, name, role columns)
        rows = conn.execute(text("""
            SELECT candidate_id, candidate_email, candidate_name, role_title, end_date
            FROM contractor_contracts
            WHERE end_date IS NOT NULL
              AND end_date >= :today
              AND end_date <= :cutoff
              AND is_active = true
        """), {"today": today, "cutoff": today + timedelta(days=30)}).fetchall()

    for row in rows:
        days_remaining = (row.end_date - today).days
        if days_remaining in (30, 15, 7):
            send_contract_expiry_alert.delay(
                candidate_id   = row.candidate_id,
                days_remaining = days_remaining,
                email          = row.candidate_email,
                name           = row.candidate_name,
                role           = row.role_title,
            )