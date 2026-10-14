"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useCallback, useEffect, useRef } from "react";

import {
  IconAlert, IconArrowRight, IconPulse, IconX,
} from "@/components/ui/Icons";
import { T } from "@/lib/motion";
import type { VoiceCall } from "@/lib/types";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { INTENT_LABEL, INTENT_TONE, OUTCOME_LABEL, callDate, duration } from "./VoicePanel";

/**
 * The evidence behind one call: what was said, by whom, and what the agent
 * concluded.
 *
 * Follows LetterViewer's dialog mechanics deliberately — focus capture, Tab
 * containment, Escape, scroll lock — rather than inventing a second modal with
 * its own accessibility bugs.
 */
export function CallTranscript({
  call,
  onClose,
}: {
  call: VoiceCall | null;
  onClose: () => void;
}) {
  const reduced = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const restoreTo = useRef<HTMLElement | null>(null);

  const open = call !== null;

  useEffect(() => {
    if (open) {
      restoreTo.current = document.activeElement as HTMLElement | null;
      const id = requestAnimationFrame(() => closeRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
    restoreTo.current?.focus?.();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), audio, [tabindex]:not([tabindex="-1"])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    },
    [onClose],
  );

  const verbalYes = call?.candidate_intent === "ACCEPTED_INTENT"
                 || call?.candidate_intent === "FINAL_ACCEPTANCE_INTENT";

  return (
    <AnimatePresence>
      {open && call && (
        <motion.div
          className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={reduced ? { duration: 0.1 } : T.panelExit}
          onKeyDown={onKeyDown}
        >
          <div
            className="absolute inset-0 bg-void/80 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />

          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="call-title"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: 16, scale: 0.995 }}
            transition={reduced ? { duration: 0.1 } : T.panel}
            className="glass glass-lit relative flex max-h-[92dvh] w-full max-w-[680px] flex-col overflow-hidden rounded-t-2xl sm:max-h-[86dvh] sm:rounded-2xl"
          >
            {/* ── Header ─────────────────────────────────────────────── */}
            <header className="flex items-start justify-between gap-4 border-b border-line-soft px-5 py-4">
              <div className="min-w-0">
                <p className="flex items-center gap-1.5 text-micro font-semibold text-violet">
                  <IconPulse className="h-3 w-3" />
                  {call.call_type === "FINAL" ? "Final follow-up call" : "Initial follow-up call"}
                </p>
                <h2
                  id="call-title"
                  className="mt-1 truncate text-[17px] font-semibold tracking-[-0.01em] text-fg"
                >
                  {call.candidate_name || call.candidate_id || "Candidate"}
                </h2>
                <p className="mt-0.5 truncate font-mono text-[11px] text-fg-muted">
                  {call.phone_masked}
                  {call.document_number ? ` · ${call.document_number}` : ""}
                </p>
              </div>

              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label="Close call details"
                className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-xl border border-line bg-fill text-fg-muted transition-colors duration-[--t-hover] hover:border-line-strong hover:text-fg"
              >
                <IconX className="h-4 w-4" />
              </button>
            </header>

            <div className="thin-scroll min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {/* ── Facts ────────────────────────────────────────────── */}
              <dl className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-4">
                {[
                  { k: "Outcome", v: call.call_outcome
                      ? (OUTCOME_LABEL[call.call_outcome] ?? call.call_outcome) : "—" },
                  { k: "Started", v: callDate(call.started_at) || "—" },
                  { k: "Duration", v: duration(call.duration_s) },
                  { k: "Attempt", v: call.attempt ? `#${call.attempt}` : "—" },
                ].map((f) => (
                  <div key={f.k}>
                    <dt className="text-micro text-fg-faint">
                      {f.k}
                    </dt>
                    <dd className="mt-0.5 text-[13px] text-fg">{f.v}</dd>
                  </div>
                ))}
              </dl>

              {call.candidate_intent && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  <span className="text-micro text-fg-faint">
                    Candidate said
                  </span>
                  <span
                    className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                      INTENT_TONE[call.candidate_intent] ?? INTENT_TONE.NO_RESPONSE
                    }`}
                  >
                    {INTENT_LABEL[call.candidate_intent] ?? call.candidate_intent}
                  </span>
                </div>
              )}

              {/* The confirmation HR actually needs: a verbal yes is not an
                  acceptance, and this is where that could be misread. */}
              {verbalYes && (
                <div className="mt-3 flex items-start gap-2 rounded-xl border border-hold/30 bg-hold/[0.08] p-3">
                  <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-hold" />
                  <div className="min-w-0 space-y-1.5">
                    <p className="text-[13px] font-medium text-fg">
                      Verbal intent only — the offer is not accepted
                    </p>
                    <p className="text-[12px] leading-relaxed text-fg-muted">
                      The candidate said yes on the call. The offer becomes
                      accepted only when they confirm through their portal link.
                    </p>
                    <Link
                      href={`/thread/${encodeURIComponent(call.thread_id)}`}
                      className="inline-flex min-h-[44px] items-center gap-1 text-[13px] font-medium text-signal hover:underline"
                    >
                      Open the workflow
                      <IconArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              )}

              {call.summary && (
                <section className="mt-4">
                  <h3 className="text-micro text-fg-faint">
                    Agent summary
                  </h3>
                  <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">
                    {call.summary}
                  </p>
                </section>
              )}

              {call.reason_if_declined && (
                <section className="mt-4">
                  <h3 className="text-micro text-fg-faint">
                    Reason given
                  </h3>
                  <p className="mt-1 text-[13px] leading-relaxed text-fg-muted">
                    {call.reason_if_declined}
                  </p>
                </section>
              )}

              {call.error_detail && (
                <section className="mt-4">
                  <h3 className="text-micro text-alarm">
                    Failure detail
                  </h3>
                  <p className="mt-1 break-words text-[12px] leading-relaxed text-fg-muted">
                    {call.error_detail}
                  </p>
                </section>
              )}

              {/* ── Recording ────────────────────────────────────────── */}
              <section className="mt-5">
                <h3 className="text-micro text-fg-faint">
                  Recording
                </h3>
                {call.recording_url ? (
                  <audio
                    controls
                    preload="none"
                    src={call.recording_url}
                    className="mt-2 w-full"
                  >
                    Your browser cannot play this recording.
                  </audio>
                ) : (
                  <p className="mt-1 text-[12px] leading-relaxed text-fg-faint">
                    No audio was captured for this call. Recording is off by
                    default and requires LiveKit Egress plus a storage bucket;
                    the transcript below is the record.
                  </p>
                )}
              </section>

              {/* ── Transcript ───────────────────────────────────────── */}
              <section className="mt-5">
                <h3 className="text-micro text-fg-faint">
                  Transcript
                </h3>
                {call.transcript.length === 0 ? (
                  <p className="mt-1 text-[12px] text-fg-faint">
                    No transcript — the call did not reach a conversation.
                  </p>
                ) : (
                  <ol className="mt-2 space-y-2">
                    {call.transcript.map((turn, i) => {
                      const agent = turn.role !== "user";
                      return (
                        <li
                          key={i}
                          className={`flex ${agent ? "justify-start" : "justify-end"}`}
                        >
                          <div
                            className={`max-w-[85%] rounded-xl border px-3 py-2 ${
                              agent
                                ? "border-line bg-fill"
                                : "border-signal/25 bg-signal/[0.08]"
                            }`}
                          >
                            <p className="text-micro text-fg-faint">
                              {agent ? "Agent" : "Candidate"}
                            </p>
                            <p className="mt-0.5 text-[13px] leading-relaxed text-fg">
                              {turn.text}
                            </p>
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </section>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
