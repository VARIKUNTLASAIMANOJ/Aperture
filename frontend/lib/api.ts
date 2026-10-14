/**
 * Backend client for the FastAPI onboarding service.
 *
 * NEXT_PUBLIC_ prefix is required: this runs in the browser.
 * (ui-ux-pro-max --stack nextjs: "Use NEXT_PUBLIC prefix ... Don't: Server
 * vars exposed to client".) Only the base URL is public — no secret ever
 * reaches this layer; every credential stays in the Python service.
 */

import { authHeader, clearSession, getSession } from "./session";
import type { StateOption } from "./form";
import type {
  AuditEntry,
  ReportMetrics,
  SalaryBreakup,
  Candidate,
  CandidateDocument,
  CandidateStatus,
  HrNotification,
  MailMessagesResponse,
  OnboardingStateResponse,
  StagesResponse,
  TriggerRequest,
  TriggerResponse,
  VoiceCallsResponse,
  VoiceStatus,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000";

/** Thrown for any non-2xx response, carrying the backend's `detail` if present. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Thrown on 401 so the UI can send the operator to the login screen. */
export class UnauthorizedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnauthorizedError";
  }
}

/** Distinguishes "server said no" from "server unreachable" for the UI. */
export class NetworkError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NetworkError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        // Attached centrally rather than per call: a request that forgets it
        // gets a 401 that looks like a bug rather than a missing header.
        ...authHeader(),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new NetworkError(
      `Cannot reach the onboarding service at ${API_BASE}. Is the FastAPI server running?`,
    );
  }

  if (res.status === 401) {
    // The token is gone or expired. Drop it so the app renders the login
    // screen instead of looping on requests that will keep failing.
    clearSession();
    let reason = "Your session has expired. Sign in again.";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") reason = body.detail;
    } catch {
      /* keep the default */
    }
    throw new UnauthorizedError(reason);
  }

  if (!res.ok) {
    let detail: unknown;
    let message = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? body;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        // FastAPI 422 validation array → readable single line
        message = detail
          .map((d: { loc?: unknown[]; msg?: string }) => {
            const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
            return field ? `${field}: ${d.msg}` : d.msg;
          })
          .filter(Boolean)
          .join(" · ");
      }
    } catch {
      /* non-JSON error body — keep the status line */
    }
    throw new ApiError(message, res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () =>
    request<{ status: string; graph_ready: boolean }>("/health"),

  // ── Operator session ─────────────────────────────────────────────────────

  login: (username: string, password: string) =>
    request<{ token: string; username: string; expires_at: number;
              auth_enabled: boolean }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  me: () => request<{ username: string; auth_enabled: boolean }>("/auth/me"),

  logout: () => request<{ ok: boolean }>("/auth/logout", { method: "POST" }),

  trigger: (payload: TriggerRequest) =>
    request<TriggerResponse>("/onboarding/trigger", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getState: (threadId: string) =>
    request<OnboardingStateResponse>(
      `/onboarding/${encodeURIComponent(threadId)}/state`,
    ),

  /**
   * `sendAt` (ISO-8601) hands the queue to the auto-send scheduler instead of
   * dispatching now. Omit it for immediate dispatch.
   */
  approve: (
    threadId: string,
    approvedBy: string,
    notes?: string,
    sendAt?: string | null,
  ) =>
    request<{
      message: string;
      thread_id: string;
      scheduled_for?: string;
      scheduled_count?: number;
    }>(`/onboarding/${encodeURIComponent(threadId)}/approve`, {
      method: "POST",
      body: JSON.stringify({
        approved_by: approvedBy,
        notes: notes ?? null,
        send_at: sendAt ?? null,
      }),
    }),

  rejectApproval: (threadId: string, rejectedBy: string, reason: string) =>
    request<{ message: string; thread_id: string }>(
      `/onboarding/${encodeURIComponent(threadId)}/reject-approval`,
      {
        method: "POST",
        body: JSON.stringify({ rejected_by: rejectedBy, reason }),
      },
    ),

  /**
   * Rendered letter bodies for one thread. Fetched on demand rather than
   * bundled into /candidates — full HTML on every roster row would bloat the
   * list payload for data that is only occasionally opened.
   */
  messages: (threadId: string) =>
    request<MailMessagesResponse>(
      `/onboarding/${encodeURIComponent(threadId)}/messages`,
    ),

  audit: (threadId: string) =>
    request<{ thread_id: string; audit_log: AuditEntry[] }>(
      `/onboarding/${encodeURIComponent(threadId)}/audit`,
    ),

  candidates: () => request<Candidate[]>("/onboarding/candidates"),

  // ── Reference data for the onboarding form ───────────────────────────────
  // Through `request` like everything else: these moved behind operator auth,
  // and a raw fetch() here sent no Authorization header, so the state dropdown
  // sat on "Loading…" and the salary preview reported "Sign in to continue."

  /**
   * Fetch a letter as a PDF and hand it to the browser.
   *
   * A plain <a href> cannot carry the Authorization header, and putting the
   * session in the URL would leak it into history and server logs. Fetching
   * to a blob keeps the credential in the header where it belongs; the
   * candidate variant passes its thread token in the query because that is
   * how the whole candidate surface authenticates — they have no account.
   */
  documentPdf: async (
    opts: { threadId: string; kind: "offer" | "appointment"; token?: string },
  ): Promise<{ blob: Blob; filename: string }> => {
    const { threadId, kind, token } = opts;
    const path = token
      ? `/candidate/${encodeURIComponent(threadId)}/${kind}/document.pdf?token=${encodeURIComponent(token)}`
      : `/onboarding/${encodeURIComponent(threadId)}/${kind}/document.pdf`;

    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {   // allow-raw-fetch: binary body
        headers: token ? {} : authHeader(),
      });
    } catch {
      throw new NetworkError(
        `Cannot reach the onboarding service at ${API_BASE}.`,
      );
    }

    if (res.status === 401) { clearSession(); throw new UnauthorizedError("Your session has expired."); }
    if (!res.ok) {
      let message = `${res.status} ${res.statusText}`;
      try {
        const body = await res.json();
        if (typeof body?.detail === "string") message = body.detail;
        else if (typeof body?.detail?.message === "string") message = body.detail.message;
      } catch { /* non-JSON error body */ }
      throw new ApiError(message, res.status);
    }

    // The server already chose a filename that keeps the document number
    // intact; honour it rather than inventing a second naming scheme.
    const disposition = res.headers.get("content-disposition") ?? "";
    const match = /filename="([^"]+)"/.exec(disposition);
    return {
      blob: await res.blob(),
      filename: match?.[1] ?? `${kind}-letter.pdf`,
    };
  },

  // ── Reporting ────────────────────────────────────────────────────────────

  metrics: () => request<ReportMetrics>("/reports/metrics"),

  candidatesCsv: async (status?: string): Promise<{ blob: Blob; filename: string }> => {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/reports/candidates.csv${q}`, {  // allow-raw-fetch: binary body
        headers: authHeader(),
      });
    } catch {
      throw new NetworkError(`Cannot reach the onboarding service at ${API_BASE}.`);
    }
    if (res.status === 401) { clearSession(); throw new UnauthorizedError("Your session has expired."); }
    if (!res.ok) throw new ApiError(`${res.status} ${res.statusText}`, res.status);
    const match = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "");
    return { blob: await res.blob(), filename: match?.[1] ?? "candidates.csv" };
  },

  metaLocations: () =>
    request<{ states: StateOption[] }>("/meta/locations"),

  ctcPreview: (body: {
    total_ctc: number; state_code: string; city: string;
    tax_regime: string; employment_type?: string | null;
  }) =>
    request<SalaryBreakup>("/meta/ctc-preview", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  // ── Voice follow-up ──────────────────────────────────────────────────────

  voiceCalls: (limit = 100) =>
    request<VoiceCallsResponse>(`/voice/calls?limit=${limit}`),

  voiceStatus: () => request<VoiceStatus>("/voice/status"),

  // ── Two-stage documentation (§1–§5) ───────────────────────────────────────

  stages: (threadId: string) =>
    request<StagesResponse>(`/onboarding/${encodeURIComponent(threadId)}/stages`),

  notifications: () =>
    request<{ notifications: HrNotification[]; unread_count: number }>(
      "/onboarding/notifications",
    ),

  releaseOffer: (threadId: string, releasedBy: string, notes?: string) =>
    request<{ thread_id: string; offer_status: string; document_number: string }>(
      `/onboarding/${encodeURIComponent(threadId)}/offer/release`,
      { method: "POST", body: JSON.stringify({ released_by: releasedBy, notes: notes ?? null }) },
    ),

  /** Re-send a bounced letter, optionally against a corrected address. */
  retryDispatch: (threadId: string, retriedBy: string, correctedEmail?: string) =>
    request<{ thread_id: string; retried: number; offer_status: string;
              message: string }>(
      `/onboarding/${encodeURIComponent(threadId)}/dispatch/retry`,
      {
        method: "POST",
        body: JSON.stringify({
          retried_by: retriedBy,
          corrected_email: correctedEmail || null,
        }),
      },
    ),

  releaseAppointment: (threadId: string, releasedBy: string, notes?: string) =>
    request<{ thread_id: string; appointment_status: string; document_number: string }>(
      `/onboarding/${encodeURIComponent(threadId)}/appointment/release`,
      { method: "POST", body: JSON.stringify({ released_by: releasedBy, notes: notes ?? null }) },
    ),

  // ── Candidate side — every call carries the signed token ─────────────────

  candidateStatus: (threadId: string, token: string) =>
    request<CandidateStatus>(
      `/candidate/${encodeURIComponent(threadId)}/status?token=${encodeURIComponent(token)}`,
    ),

  candidateOfferDocument: (threadId: string, token: string) =>
    request<CandidateDocument>(
      `/candidate/${encodeURIComponent(threadId)}/offer/document?token=${encodeURIComponent(token)}`,
    ),

  candidateAppointmentDocument: (threadId: string, token: string) =>
    request<CandidateDocument>(
      `/candidate/${encodeURIComponent(threadId)}/appointment/document?token=${encodeURIComponent(token)}`,
    ),

  acceptOffer: (threadId: string, token: string) =>
    request<{ offer_status: string; message: string }>(
      `/candidate/${encodeURIComponent(threadId)}/offer/accept?token=${encodeURIComponent(token)}`,
      { method: "POST", body: JSON.stringify({ reason: null }) },
    ),

  declineOffer: (threadId: string, token: string, reason?: string) =>
    request<{ offer_status: string; message: string }>(
      `/candidate/${encodeURIComponent(threadId)}/offer/decline?token=${encodeURIComponent(token)}`,
      { method: "POST", body: JSON.stringify({ reason: reason ?? null }) },
    ),

  allAudit: () => request<{ audit_log: AuditEntry[] }>("/onboarding/audit/all"),

  /**
   * EventSource cannot set an Authorization header, so the session rides in
   * the query string for this one endpoint — the server accepts it there only
   * for the stream. It is a bearer token in a URL, which means it can land in
   * server logs; the alternative is either an unauthenticated stream or
   * abandoning SSE, and of the three this is the one with a bounded blast
   * radius (read-only, 12-hour expiry).
   */
  streamUrl: (threadId: string) => {
    const s = getSession();
    const q = s ? `?session=${encodeURIComponent(s.token)}` : "";
    return `${API_BASE}/onboarding/${encodeURIComponent(threadId)}/stream${q}`;
  },
};
