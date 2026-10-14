"use client";

import { AnimatePresence, motion } from "framer-motion";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  IconAlert, IconArrowRight, IconSpinner, IconX,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import {
  TIMESTAMP_VERB, formatMailDate, mailKind, mailStatusLabel, type MailRow,
} from "@/lib/dashboardData";
import { T } from "@/lib/motion";
import type { MailMessage } from "@/lib/types";
import { useReducedMotion } from "@/lib/useReducedMotion";

interface LetterViewerProps {
  row: MailRow | null;
  onClose: () => void;
}

const STATUS_STYLE: Record<string, string> = {
  SENT: "border-settled/30 bg-settled/10 text-settled",
  PENDING: "border-hold/30 bg-hold/10 text-hold",
  SCHEDULED: "border-violet/35 bg-violet/10 text-violet",
  FAILED: "border-alarm/30 bg-alarm/10 text-alarm",
  CANCELLED: "border-line-strong bg-fill text-fg-muted",
};

export function LetterViewer({ row, onClose }: LetterViewerProps) {
  const reduced = useReducedMotion();
  const [message, setMessage] = useState<MailMessage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  // Where focus came from, so it can be handed back on close.
  const restoreTo = useRef<HTMLElement | null>(null);

  const open = row !== null;

  useEffect(() => {
    if (!open || !row) return;
    restoreTo.current = document.activeElement as HTMLElement | null;

    let alive = true;
    setLoading(true);
    setError(null);
    setMessage(null);

    api
      .messages(row.threadId)
      .then((res) => {
        if (!alive) return;
        setMessage(res.messages[row.index] ?? null);
        if (!res.messages[row.index]) setError("This message is no longer in the thread.");
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : "Could not load the letter."))
      .finally(() => alive && setLoading(false));

    return () => { alive = false; };
  }, [open, row]);

  // Move focus in on open, hand it back on close.
  useEffect(() => {
    if (open) {
      const id = requestAnimationFrame(() => closeRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
    restoreTo.current?.focus?.();
  }, [open]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
        return;
      }
      // Contain Tab within the dialog: aria-modal alone does not stop the
      // browser tabbing into the page behind it.
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), iframe, [tabindex]:not([tabindex="-1"])',
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

  // Stop the page scrolling underneath while the dialog is open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  return (
    <AnimatePresence>
      {open && row && (
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
            aria-labelledby="letter-title"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 24, scale: 0.99 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduced ? { opacity: 0 } : { opacity: 0, y: 16, scale: 0.995 }}
            transition={reduced ? { duration: 0.1 } : T.panel}
            className="glass glass-lit relative flex max-h-[92dvh] w-full max-w-[760px] flex-col overflow-hidden rounded-t-2xl sm:max-h-[86dvh] sm:rounded-2xl"
          >
            <header className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 id="letter-title" className="truncate text-[15px] font-semibold text-fg">
                    {mailKind(row.template)} · {row.candidateName}
                  </h2>
                  <span
                    className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.1em] ${
                      STATUS_STYLE[row.status] ?? STATUS_STYLE.CANCELLED
                    }`}
                  >
                    {mailStatusLabel(row.status, row.dispatchMode)}
                  </span>
                </div>
                <p className="mt-1 truncate text-[12px] text-fg-muted">
                  {row.roleTitle}
                  {row.department ? ` · ${row.department}` : ""} · to{" "}
                  <span className="text-fg">{row.recipient}</span>
                </p>
              </div>

              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label="Close letter"
                className="flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-xl border border-line bg-fill text-fg-muted transition-colors duration-[--t-hover] hover:border-line-strong hover:bg-fill-strong hover:text-fg"
              >
                <IconX className="h-4 w-4" />
              </button>
            </header>

            <div className="thin-scroll min-h-0 flex-1 overflow-y-auto">
              {loading && (
                <div className="flex items-center justify-center gap-2 py-16 text-fg-muted">
                  <IconSpinner className="h-4 w-4 animate-spin" />
                  <span className="text-[13px]">Loading letter…</span>
                </div>
              )}

              {!loading && error && (
                <div
                  role="alert"
                  className="m-5 flex items-start gap-2.5 rounded-xl border border-alarm/35 bg-alarm/[0.08] p-4"
                >
                  <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
                  <p className="break-words text-[13px] leading-relaxed text-fg-muted">{error}</p>
                </div>
              )}

              {!loading && !error && message && (
                <>
                  <dl className="grid gap-x-6 gap-y-1.5 border-b border-line-soft px-5 py-3 text-[12px] sm:grid-cols-[auto_1fr]">
                    <dt className="text-fg-muted">Subject</dt>
                    <dd className="truncate font-medium text-fg">{message.subject}</dd>
                    <dt className="text-fg-muted">
                      {row.timestampKind ? TIMESTAMP_VERB[row.timestampKind] : "Date"}
                    </dt>
                    <dd className="truncate text-fg">
                      {row.timestamp ? (
                        <span title={new Date(row.timestamp).toLocaleString()}>
                          {formatMailDate(row.timestamp)}
                        </span>
                      ) : (
                        <span className="text-fg-faint">Not recorded</span>
                      )}
                    </dd>

                    <dt className="text-fg-muted">Delivery</dt>
                    <dd className="truncate text-fg">
                      {row.status === "SENT" && message.message_id ? (
                        <span className="font-mono text-[11px]">
                          {message.message_id}
                          {row.dispatchMode === "AUTO" && (
                            <span className="ml-2 font-sans text-violet">
                              sent automatically
                            </span>
                          )}
                        </span>
                      ) : row.status === "PENDING" ? (
                        "Not sent — waiting on your approval"
                      ) : row.status === "SCHEDULED" ? (
                        <span className="text-violet">
                          Not sent yet — queued for automatic delivery
                        </span>
                      ) : row.status === "CANCELLED" ? (
                        "Cancelled before dispatch — never sent"
                      ) : row.status === "FAILED" ? (
                        <span className="text-alarm">
                          {message.message_id ?? "Dispatch failed"}
                        </span>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </dl>

                  {message.html ? (
                    <div className="p-4">
                      <p className="mb-2 text-micro text-fg-faint">
                        Letter preview
                      </p>
                      {/*
                        The body is model-generated HTML. It renders inside a
                        fully sandboxed iframe — `sandbox=""` grants nothing, so
                        no scripts, no forms, no same-origin access to this app.
                        dangerouslySetInnerHTML here would be a live XSS sink.
                      */}
                      <iframe
                        title={`${mailKind(row.template)} letter for ${row.candidateName}`}
                        srcDoc={message.html}
                        sandbox=""
                        referrerPolicy="no-referrer"
                        className="h-[52vh] w-full rounded-xl border border-line bg-white"
                      />
                    </div>
                  ) : (
                    <p className="px-5 py-8 text-center text-[13px] text-fg-muted">
                      {message.render_error
                        ? `The letter could not be rendered: ${message.render_error}`
                        : "No letter body is stored for this message."}
                    </p>
                  )}
                </>
              )}
            </div>

            <footer className="flex items-center justify-between gap-3 border-t border-line px-5 py-3">
              <p className="truncate font-mono text-[10px] text-fg-faint">
                thread {row.threadId}
              </p>
              <Link
                href={`/thread/${encodeURIComponent(row.threadId)}`}
                className="inline-flex min-h-[44px] items-center gap-1.5 text-[13px] font-medium text-signal transition-opacity duration-[--t-hover] hover:opacity-80"
              >
                {row.status === "PENDING" ? "Review and decide" : "Open workflow"}
                <IconArrowRight className="h-4 w-4" />
              </Link>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
