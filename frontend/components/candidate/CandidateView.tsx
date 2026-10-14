"use client";

import { useCallback, useEffect, useState } from "react";

import { LogoMark } from "@/components/brand/Logo";
import { Button } from "@/components/ui/Button";
import {
  IconAlert, IconCheck, IconClock, IconLock, IconMail, IconShield, IconSpinner, IconX,
} from "@/components/ui/Icons";
import { ApiError, api } from "@/lib/api";
import { saveBlob } from "@/lib/download";
import type { CandidateDocument, CandidateStatus } from "@/lib/types";

/**
 * §5 — the candidate's own view of their employment progress.
 *
 * Identity comes from the signed token in the link; there are no accounts, so
 * this surface deliberately has no sidebar and no console chrome.
 *
 * Laid out around the two things the reader actually came for: what the offer
 * says, and what they have to do about it. The progress rail is secondary —
 * it answers "where is this up to", which is a question they ask second.
 *
 * The Appointment Letter section renders from `status.appointment.status`,
 * which the API reports as PENDING_FROM_HR until released — the server never
 * sends the draft's number, date or body, so there is nothing here for a
 * curious candidate to read out of the payload.
 */

type Step = "done" | "current" | "todo" | "failed";

function StepMark({ state }: { state: Step }) {
  const cls = {
    done: "border-settled/40 bg-settled/15 text-settled",
    current: "border-hold/40 bg-hold/15 text-hold",
    todo: "border-line bg-fill text-fg-faint",
    failed: "border-alarm/40 bg-alarm/15 text-alarm",
  }[state];
  return (
    <span
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${cls}`}
      aria-hidden="true"
    >
      {state === "done" ? <IconCheck className="h-3.5 w-3.5" />
        : state === "failed" ? <IconX className="h-3.5 w-3.5" />
        : state === "current" ? <IconClock className="h-3.5 w-3.5" />
        : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
    </span>
  );
}

function Line({ state, label, detail }: { state: Step; label: string; detail?: string }) {
  return (
    <li className="flex items-start gap-3 py-2">
      <StepMark state={state} />
      <span className="min-w-0">
        <span className={`block text-base font-medium ${state === "todo" ? "text-fg-faint" : "text-fg"}`}>
          {label}
        </span>
        {detail && <span className="mt-0.5 block text-body leading-snug text-fg-muted">{detail}</span>}
      </span>
    </li>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-micro text-fg-faint">{label}</dt>
      <dd className="mt-0.5 truncate text-base text-fg">{value}</dd>
    </div>
  );
}

export function CandidateView({ threadId, token }: { threadId: string; token: string }) {
  const [status, setStatus] = useState<CandidateStatus | null>(null);
  const [doc, setDoc] = useState<CandidateDocument | null>(null);
  const [docKind, setDocKind] = useState<"offer" | "appointment" | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"accept" | "decline" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [confirmDecline, setConfirmDecline] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.candidateStatus(threadId, token));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "This link is not valid.");
    } finally {
      setLoading(false);
    }
  }, [threadId, token]);

  useEffect(() => { void load(); }, [load]);

  const openDoc = async (kind: "offer" | "appointment") => {
    setError(null);
    try {
      const d = kind === "offer"
        ? await api.candidateOfferDocument(threadId, token)
        : await api.candidateAppointmentDocument(threadId, token);
      setDoc(d); setDocKind(kind);
      void load();   // viewing an offer flips RELEASED → VIEWED
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That document is not available.");
    }
  };

  const [downloading, setDownloading] = useState<"offer" | "appointment" | null>(null);

  /**
   * Nobody files, signs or forwards an HTML offer letter — this used to save
   * a .html file. The PDF is rendered server-side from the same template the
   * preview shows, so the two cannot disagree.
   */
  const download = async (kind: "offer" | "appointment") => {
    setDownloading(kind);
    setError(null);
    try {
      const { blob, filename } = await api.documentPdf({ threadId, kind, token });
      saveBlob(blob, filename);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not download the letter.");
    } finally {
      setDownloading(null);
    }
  };

  const respond = async (kind: "accept" | "decline") => {
    setBusy(kind); setError(null);
    try {
      const r = kind === "accept"
        ? await api.acceptOffer(threadId, token)
        : await api.declineOffer(threadId, token);
      setFlash(r.message);
      setConfirmDecline(false);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not record your response.");
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="flex min-h-dvh items-center justify-center gap-2 text-fg-muted">
        <IconSpinner className="h-4 w-4 animate-spin" />
        <span className="text-body">Loading your employment status…</span>
      </div>
    );
  }

  if (!status) {
    return (
      <div className="flex min-h-dvh items-center justify-center px-4">
        <div className="surface max-w-[460px] rounded-card p-6 text-center">
          <IconLock className="mx-auto h-6 w-6 text-alarm" />
          <h1 className="mt-3 text-title font-semibold text-fg">Link not valid</h1>
          <p className="mt-2 text-base leading-relaxed text-fg-muted">
            {error ?? "This link may have expired. Please contact the HR team for a new one."}
          </p>
        </div>
      </div>
    );
  }

  const o = status.offer;
  const a = status.appointment;
  const offerReleased = ["RELEASED", "VIEWED", "ACCEPTED", "DECLINED", "EXPIRED"].includes(o.status);
  const accepted = o.status === "ACCEPTED";
  const declined = o.status === "DECLINED";
  const expired = o.status === "EXPIRED";
  const apptReleased = a.status === "RELEASED";
  const decisionNeeded = o.can_respond && offerReleased;

  return (
    <div className="page-wash mx-auto w-full max-w-[720px] px-4 py-6 sm:px-6 sm:py-10">
      <header className="flex items-center gap-2.5">
        <LogoMark className="h-7 w-7 shrink-0 text-fg" interactive={false} />
        <span className="text-base font-semibold tracking-[-0.01em] text-fg">Aperture</span>
      </header>

      <h1 className="mt-6 text-display font-semibold text-fg">
        {status.candidate_name}
      </h1>
      <p className="mt-1 text-base text-fg-muted">
        {[status.designation, status.department, status.work_location.city]
          .filter(Boolean).join(" · ")}
      </p>

      {flash && (
        <p role="status" className="mt-5 flex items-center gap-2 rounded-xl border border-settled/25 bg-settled/[0.08] px-4 py-3 text-base text-settled">
          <IconCheck className="h-4 w-4 shrink-0" />{flash}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-5 flex items-start gap-2 rounded-xl border border-alarm/30 bg-alarm/[0.08] px-4 py-3 text-base text-fg-muted">
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />{error}
        </p>
      )}

      {/* ── The offer itself ─────────────────────────────────────────────── */}
      <section className="surface surface-lift mt-5 overflow-hidden rounded-card">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft bg-fill/60 px-4 py-3">
          <h2 className="flex items-center gap-2 text-lead font-semibold text-fg">
            <IconMail className="h-4 w-4 text-signal" />
            Your offer
          </h2>
          {o.document_number && (
            <span className="font-mono text-micro text-fg-faint">{o.document_number}</span>
          )}
        </header>

        {!offerReleased ? (
          <p className="px-4 py-5 text-base text-fg-muted">
            Your Offer Letter has not been released yet. You will receive an
            email as soon as it is.
          </p>
        ) : (
          <>
            {/* The figure is the headline fact, so it is the largest thing on
                the page after the candidate's own name. */}
            {status.ctc && (
              <div className="border-b border-line-soft bg-signal/[0.045] px-4 py-5">
                <p className="text-micro text-fg-muted">Annual CTC</p>
                <p className="mt-1 font-mono text-[34px] font-semibold leading-none tracking-[-0.02em] text-signal">
                  {status.ctc.formatted}
                </p>
                <p className="mt-1.5 text-body text-fg-muted">{status.ctc.lpa}</p>
              </div>
            )}

            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-b border-line-soft px-4 py-4 sm:grid-cols-3">
              {status.joining_date && <Fact label="Joining date" value={status.joining_date} />}
              {status.work_location.city && (
                <Fact label="Location" value={
                  [status.work_location.city, status.work_location.state].filter(Boolean).join(", ")
                } />
              )}
              {o.expires_at && (
                <Fact label="Valid until"
                      value={new Date(o.expires_at).toLocaleDateString()} />
              )}
            </dl>

            <div className="flex flex-wrap gap-2 px-4 py-3">
              <Button variant="ghost" onClick={() => openDoc("offer")}>
                Read the full letter
              </Button>
              <Button
                variant="ghost"
                loading={downloading === "offer"}
                disabled={downloading !== null}
                onClick={() => download("offer")}
              >
                Download PDF
              </Button>
            </div>

            {decisionNeeded && (
              <div className="border-t border-line-soft bg-fill px-4 py-4">
                <p className="text-base font-medium text-fg">
                  Do you accept this offer?
                </p>
                <p className="mt-0.5 text-body leading-relaxed text-fg-muted">
                  {o.expires_at
                    ? `Please respond by ${new Date(o.expires_at).toLocaleDateString()}.`
                    : "Please record your decision below."}
                </p>

                <div className="mt-3 flex flex-wrap gap-2">
                  <Button
                    loading={busy === "accept"} disabled={busy !== null}
                    onClick={() => respond("accept")}
                  >
                    <IconCheck className="h-4 w-4" /> Accept offer
                  </Button>

                  {/* Decline is irreversible and blocks the Appointment Letter
                      permanently (Rule 4), so it asks twice. */}
                  {confirmDecline ? (
                    <>
                      <Button
                        variant="danger" loading={busy === "decline"} disabled={busy !== null}
                        onClick={() => respond("decline")}
                      >
                        Yes, decline
                      </Button>
                      <Button variant="ghost" onClick={() => setConfirmDecline(false)}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <Button variant="danger" disabled={busy !== null}
                            onClick={() => setConfirmDecline(true)}>
                      <IconX className="h-4 w-4" /> Decline
                    </Button>
                  )}
                </div>

                {confirmDecline && (
                  <p role="alert" className="mt-2.5 text-body leading-snug text-alarm">
                    Declining is final — no Appointment Letter will be issued.
                  </p>
                )}
              </div>
            )}
          </>
        )}
      </section>

      {/* ── Appointment Letter ───────────────────────────────────────────── */}
      <section className="surface mt-3 overflow-hidden rounded-card">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line-soft bg-fill/60 px-4 py-3">
          <h2 className="flex items-center gap-2 text-lead font-semibold text-fg">
            <IconShield className="h-4 w-4 text-hold" />
            Appointment Letter
          </h2>
          {apptReleased && a.document_number && (
            <span className="font-mono text-micro text-fg-faint">{a.document_number}</span>
          )}
        </header>

        {apptReleased ? (
          <div className="flex flex-wrap gap-2 px-4 py-3">
            <Button variant="ghost" onClick={() => openDoc("appointment")}>
              Read the full letter
            </Button>
            <Button
              variant="ghost"
              loading={downloading === "appointment"}
              disabled={downloading !== null}
              onClick={() => download("appointment")}
            >
              Download PDF
            </Button>
          </div>
        ) : (
          <p className="flex items-start gap-2 px-4 py-4 text-base leading-relaxed text-fg-muted">
            <IconLock className="mt-0.5 h-4 w-4 shrink-0 text-fg-faint" />
            {declined
              ? "No Appointment Letter will be issued for a declined offer."
              : accepted
                ? "Pending from HR. You will be notified by email once it is released."
                : "Available only after you accept your offer."}
          </p>
        )}
      </section>

      {/* ── Progress ─────────────────────────────────────────────────────── */}
      <section className="surface mt-3 rounded-card p-4">
        <h2 className="mb-1 text-lead font-semibold text-fg">Progress</h2>
        <ol>
          <Line state="done" label="Application" detail="Selected" />
          <Line
            state={declined || expired ? "failed" : offerReleased ? "done" : "todo"}
            label="Offer Letter"
            detail={
              declined ? "You declined this offer"
              : expired ? "This offer expired"
              : accepted ? "Released · accepted"
              : offerReleased ? "Released — awaiting your decision"
              : "Not yet released"
            }
          />
          <Line
            state={apptReleased ? "done" : accepted ? "current" : "todo"}
            label="Appointment Letter"
            detail={
              apptReleased ? `Released${a.document_number ? ` · ${a.document_number}` : ""}`
              : accepted ? "Pending from HR"
              : "Available after you accept the offer"
            }
          />
          <Line
            state={["IN_PROGRESS", "COMPLETED"].includes(status.onboarding.status) ? "done" : "todo"}
            label="Onboarding"
            detail={status.onboarding.status === "IN_PROGRESS" ? "In progress" : "Not started"}
          />
        </ol>
      </section>

      {/* ── Document preview ─────────────────────────────────────────────── */}
      {doc?.html && (
        <section className="surface mt-3 overflow-hidden rounded-card">
          <header className="flex items-center justify-between gap-3 border-b border-line-soft px-4 py-2.5">
            <h2 className="text-lead font-semibold text-fg">
              {doc.document_type === "OFFER_LETTER" ? "Offer Letter" : "Appointment Letter"}
            </h2>
            <button
              type="button"
              onClick={() => { setDoc(null); setDocKind(null); }}
              className="-my-3 min-h-[44px] cursor-pointer px-1 text-body text-fg-muted hover:text-fg"
            >
              Close
            </button>
          </header>
          {/* Sandboxed: the letter is generated HTML and must not be able to
              script against this page. */}
          <iframe
            title={`${doc.document_type} ${doc.document_number ?? ""}`}
            srcDoc={doc.html}
            sandbox=""
            referrerPolicy="no-referrer"
            className="h-[70vh] w-full bg-white"
          />
        </section>
      )}

      <p className="mt-6 text-body leading-relaxed text-fg-muted">
        Questions about this offer? Reply to the email it came from and the HR
        team will get back to you.
      </p>
    </div>
  );
}
