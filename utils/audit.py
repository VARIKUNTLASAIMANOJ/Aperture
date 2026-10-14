"""
Audit log helpers. Every agent node calls `emit_audit()` before returning state.
Entries are appended (never mutated) via the Annotated[list, operator.add] reducer.
"""

from datetime import datetime, timezone

from core.state import AuditEntry


def emit_audit(
    node: str,
    event: str,
    payload_summary: str,
    actor: str = "SYSTEM",
) -> list[AuditEntry]:
    """
    Returns a single-item list so it can be spread into the state dict
    using the append reducer pattern:
        state_patch = {"audit_log": emit_audit(...)}
    """
    entry: AuditEntry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": node,
        "event": event,
        "actor": actor,
        "payload_summary": payload_summary,
    }
    return [entry]