import type { AuditEntry, Candidate } from "./types";

/**
 * Derives dashboard figures from the two read endpoints the backend exposes:
 * GET /onboarding/candidates and GET /onboarding/audit/all.
 *
 * Deliberately does NOT use `kanban_column`. The backend's
 * `_derive_kanban_column` maps ERROR to "COMPLETED" (terminal, but not
 * successful), so counting that field verbatim reports failed dispatches as
 * completed work. Everything here is computed from the underlying fields.
 */

export interface DashboardStats {
  mailsSent: number;
  awaitingApproval: number;
  dispatchFailed: number;
  inFlight: number;
  halted: number;
  totalWorkflows: number;
  offersExtended: number;
  declines: number;
  /** SENT / (SENT + FAILED). null when nothing has been attempted yet. */
  sendSuccessRate: number | null;
}

/** A thread parked at interrupt_before=["email_node"] with mail still queued. */
export function isAwaitingApproval(c: Candidate): boolean {
  return (
    c.approval_status === "NEEDS_APPROVAL" &&
    c.email_queue_summary.some((e) => e.status === "PENDING")
  );
}

export function hasFailedDispatch(c: Candidate): boolean {
  return c.email_queue_summary.some((e) => e.status === "FAILED");
}

export function sentCount(c: Candidate): number {
  return c.email_queue_summary.filter((e) => e.status === "SENT").length;
}

export function computeStats(candidates: Candidate[]): DashboardStats {
  let mailsSent = 0;
  let dispatchFailed = 0;
  let awaitingApproval = 0;
  let halted = 0;
  let inFlight = 0;
  let offersExtended = 0;
  let declines = 0;

  for (const c of candidates) {
    for (const e of c.email_queue_summary) {
      if (e.status === "SENT") mailsSent++;
      if (e.status === "FAILED") dispatchFailed++;
    }

    if (c.selection_status === "SELECTED") offersExtended++;
    if (c.selection_status === "REJECTED") declines++;

    const awaiting = isAwaitingApproval(c);
    if (awaiting) awaitingApproval++;

    if (c.node_status === "ERROR") {
      halted++;
    } else if (!awaiting && c.node_status !== "COMPLETE") {
      inFlight++;
    }
  }

  const attempted = mailsSent + dispatchFailed;

  return {
    mailsSent,
    awaitingApproval,
    dispatchFailed,
    inFlight,
    halted,
    totalWorkflows: candidates.length,
    offersExtended,
    declines,
    sendSuccessRate: attempted === 0 ? null : mailsSent / attempted,
  };
}

/** Threads needing a human decision, most recently started first. */
export function approvalQueue(candidates: Candidate[]): Candidate[] {
  return candidates.filter(isAwaitingApproval);
}

/** Threads that stopped on an error — the other thing an operator must act on. */
export function attentionQueue(candidates: Candidate[]): Candidate[] {
  return candidates.filter(
    (c) => c.node_status === "ERROR" || hasFailedDispatch(c),
  );
}

/** One outbound email, flattened out of the candidate roster. */
export interface MailRow {
  threadId: string;
  index: number;
  candidateName: string;
  roleTitle: string;
  department: string;
  template: string;
  recipient: string;
  status: string;
  messageId: string | null;
  /** When this letter reached its current status. Null if not derivable. */
  timestamp: string | null;
  /** What the timestamp actually marks, so the UI never mislabels it. */
  timestampKind: "sent" | "failed" | "cancelled" | "queued" | "scheduled" | null;
  /** MANUAL | AUTO | null */
  dispatchMode: string | null;
  /** Target instant while SCHEDULED. */
  scheduledFor: string | null;
}

/** What the letter IS, independent of whether it went out. */
export function mailKind(template: string): "Offer" | "Rejection" | "Notice" {
  if (template === "offer_letter") return "Offer";
  if (template === "rejection_notice") return "Rejection";
  return "Notice";
}

/**
 * What HAPPENED to it. Kept separate from kind so neither implies the other.
 *
 * `mode` distinguishes a scheduled auto-send from a manual one: a failed
 * auto-send is a different operational problem from a failed manual send —
 * the first fired unattended and nobody was watching.
 */
export function mailStatusLabel(status: string, mode?: string | null): string {
  const auto = mode === "AUTO";
  switch (status) {
    case "SENT": return auto ? "Auto-sent" : "Sent";
    case "PENDING": return "Awaiting approval";
    case "SCHEDULED": return "Pending to send";
    case "FAILED": return auto ? "Failed auto-send" : "Failed";
    case "CANCELLED": return "Cancelled";
    default: return status || "Unknown";
  }
}

/**
 * Latest timestamp per (thread, audit event).
 *
 * `EmailQueueItem` carries no timestamp — the backend never records when a
 * letter was queued or dispatched. The audit trail does, and its events map
 * cleanly onto the queue statuses, so dates are derived from there rather than
 * invented. This resolves at THREAD granularity: two letters in one thread
 * share a dispatch timestamp, which is accurate, since email_node sends them
 * in a single pass.
 */
function threadEventTimes(audit: AuditEntry[]): Map<string, Record<string, string>> {
  const byThread = new Map<string, Record<string, string>>();
  for (const e of audit) {
    if (!e.thread_id) continue;
    const bucket = byThread.get(e.thread_id) ?? {};
    // Keep the most recent occurrence of each event.
    if (!bucket[e.event] || bucket[e.event] < e.timestamp) bucket[e.event] = e.timestamp;
    byThread.set(e.thread_id, bucket);
  }
  return byThread;
}

function resolveTimestamp(
  status: string,
  template: string,
  events: Record<string, string> | undefined,
): { timestamp: string | null; kind: MailRow["timestampKind"] } {
  if (!events) return { timestamp: null, kind: null };

  const queued =
    template === "rejection_notice"
      ? events.REJECTION_EMAIL_QUEUED
      : events.OFFER_LETTER_GENERATED;

  switch (status) {
    case "SENT":
      return { timestamp: events.EMAILS_DISPATCHED ?? queued ?? null, kind: "sent" };
    case "FAILED":
      return { timestamp: events.EMAILS_DISPATCHED ?? queued ?? null, kind: "failed" };
    case "CANCELLED":
      return { timestamp: events.DISPATCH_REJECTED ?? queued ?? null, kind: "cancelled" };
    case "PENDING":
      return { timestamp: queued ?? null, kind: "queued" };
    default:
      return { timestamp: queued ?? null, kind: queued ? "queued" : null };
  }
}

/** Verb for the date, so "Sent 16 Aug" never appears on a letter that wasn't. */
export const TIMESTAMP_VERB: Record<NonNullable<MailRow["timestampKind"]>, string> = {
  sent: "Sent",
  failed: "Attempted",
  cancelled: "Cancelled",
  queued: "Queued",
  scheduled: "Sends",
};

export function mailLog(candidates: Candidate[], audit: AuditEntry[] = []): MailRow[] {
  const times = threadEventTimes(audit);
  const rows: MailRow[] = [];

  for (const c of candidates) {
    const events = times.get(c.thread_id);
    c.email_queue_summary.forEach((e, index) => {
      const status = e.status ?? "";
      const template = e.template ?? "";
      const mode = e.dispatch_mode ?? null;
      const scheduledFor = e.scheduled_for ?? null;

      // Precedence matters. `sent_at` is recorded by email_node at the actual
      // moment of dispatch, so it beats anything derived from the audit trail.
      // A SCHEDULED item has not happened yet, so it is dated by its target.
      let timestamp: string | null;
      let kind: MailRow["timestampKind"];
      if (status === "SCHEDULED" && scheduledFor) {
        timestamp = scheduledFor;
        kind = "scheduled";
      } else if (e.sent_at) {
        timestamp = e.sent_at;
        kind = status === "FAILED" ? "failed" : "sent";
      } else {
        const derived = resolveTimestamp(status, template, events);
        timestamp = derived.timestamp;
        kind = derived.kind;
      }

      rows.push({
        threadId: c.thread_id,
        index,
        candidateName: c.candidate_name || "Unnamed",
        roleTitle: c.role_title || "",
        department: c.department || "",
        template,
        recipient: e.recipient ?? "",
        status,
        messageId: e.message_id ?? null,
        timestamp,
        timestampKind: kind,
        dispatchMode: mode,
        scheduledFor,
      });
    });
  }

  // Most recent first, in every filter — filtering is a subset of this one
  // ordering, so each tab inherits it. Undated rows sink to the bottom rather
  // than pretending to be either newest or oldest.
  return rows.sort((a, b) => {
    if (a.timestamp && b.timestamp) return a.timestamp < b.timestamp ? 1 : -1;
    if (a.timestamp) return -1;
    if (b.timestamp) return 1;
    return a.candidateName.localeCompare(b.candidateName);
  });
}

/** Compact absolute date. The year is dropped unless it differs from now. */
export function formatMailDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const sameYear = d.getFullYear() === new Date().getFullYear();
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function recentActivity(log: AuditEntry[], limit = 12): AuditEntry[] {
  // /onboarding/audit/all already sorts by timestamp desc; re-sorting here
  // keeps the component correct if that ever changes.
  return [...log]
    .sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1))
    .slice(0, limit);
}

/** Compact relative time. Absolute timestamp stays available via `title`. */
export function relativeTime(iso: string, now = Date.now()): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const secs = Math.max(0, Math.round((now - then) / 1000));
  if (secs < 45) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

/** Short, human label for where a thread currently sits. */
export function stageLabel(c: Candidate): string {
  if (c.node_status === "ERROR") return "Halted";
  if (isAwaitingApproval(c)) return "Awaiting approval";
  switch (c.current_node) {
    case "triage_node":
      return "Triage";
    case "financial_node":
      return "Payroll";
    case "contract_node":
      return "Drafting";
    case "email_node":
      return sentCount(c) > 0 ? "Dispatched" : "Dispatch";
    case "INIT":
      return "Starting";
    default:
      return c.node_status === "COMPLETE" ? "Complete" : "Running";
  }
}
