"use client";

import { useCallback, useEffect, useState } from "react";

import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  IconAlert, IconCheck, IconClock, IconPulse, IconSearch, IconX,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import type { VoiceCall, VoiceStatus } from "@/lib/types";
import { CallTranscript } from "./CallTranscript";

/**
 * Who the agent called, what they said, and the evidence behind it.
 *
 * The outcome and the intent are deliberately two separate chips. "Nobody
 * answered" and "the candidate declined" are completely different facts, and
 * the whole point of this panel is that HR can tell them apart at a glance —
 * collapsing them into one status is how a missed call starts looking like a
 * rejection.
 */

const INTENT_LABEL: Record<string, string> = {
  ACCEPTED_INTENT: "Said yes",
  FINAL_ACCEPTANCE_INTENT: "Said yes (final)",
  DECLINED: "Declined",
  FINAL_DECLINE: "Declined (final)",
  NEEDS_TIME: "Needs time",
  FINAL_UNDECIDED: "Still undecided",
  NO_RESPONSE: "No decision",
};

const INTENT_TONE: Record<string, string> = {
  ACCEPTED_INTENT: "border-settled/30 bg-settled/10 text-settled",
  FINAL_ACCEPTANCE_INTENT: "border-settled/30 bg-settled/10 text-settled",
  DECLINED: "border-alarm/30 bg-alarm/10 text-alarm",
  FINAL_DECLINE: "border-alarm/30 bg-alarm/10 text-alarm",
  NEEDS_TIME: "border-hold/30 bg-hold/10 text-hold",
  FINAL_UNDECIDED: "border-hold/30 bg-hold/10 text-hold",
  NO_RESPONSE: "border-line-strong bg-fill-strong text-fg-muted",
};

const OUTCOME_LABEL: Record<string, string> = {
  COMPLETED: "Answered",
  NO_ANSWER: "No answer",
  BUSY: "Busy",
  CALL_FAILED: "Call failed",
  INVALID_NUMBER: "Invalid number",
  DECLINED_CONTACT: "Asked not to be contacted",
};

type Filter = "ALL" | "ANSWERED" | "ACCEPTED" | "NEEDS_TIME" | "UNREACHABLE";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "ALL", label: "All" },
  { id: "ANSWERED", label: "Answered" },
  { id: "ACCEPTED", label: "Said yes" },
  { id: "NEEDS_TIME", label: "Needs time" },
  { id: "UNREACHABLE", label: "Unreachable" },
];

function matches(c: VoiceCall, f: Filter): boolean {
  switch (f) {
    case "ANSWERED":
      return c.call_outcome === "COMPLETED";
    case "ACCEPTED":
      return c.candidate_intent === "ACCEPTED_INTENT"
          || c.candidate_intent === "FINAL_ACCEPTANCE_INTENT";
    case "NEEDS_TIME":
      return c.candidate_intent === "NEEDS_TIME";
    case "UNREACHABLE":
      return ["NO_ANSWER", "BUSY", "INVALID_NUMBER", "CALL_FAILED"]
        .includes(c.call_outcome ?? "");
    default:
      return true;
  }
}

function duration(seconds: number | null): string {
  if (seconds === null || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function callDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

const POLL_MS = 20_000;

export function VoicePanel({ standalone = false }: { standalone?: boolean } = {}) {
  const [calls, setCalls] = useState<VoiceCall[]>([]);
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [filter, setFilter] = useState<Filter>("ALL");
  const [open, setOpen] = useState<VoiceCall | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([api.voiceCalls(), api.voiceStatus()]);
      setCalls(c.calls);
      setStatus(s);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load call history.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const visible = calls.filter((c) => matches(c, filter));
  const counts = Object.fromEntries(
    FILTERS.map((f) => [f.id, calls.filter((c) => matches(c, f.id)).length]),
  ) as Record<Filter, number>;

  // Why nothing has happened yet, said precisely. "No calls yet" is useless
  // when the real answer is that a credential is missing.
  const blocked: string | null = !status
    ? null
    : !status.voice_agent_enabled
      ? "Voice follow-up is switched off (VOICE_AGENT_ENABLED)."
      : !status.telephony_configured
        ? (status.telephony_problem
           ?? "No SIP trunk configured — LiveKit cannot reach the phone network.")
        : !status.deepgram_configured
          ? "No Deepgram key configured — the agent cannot hear or speak."
          : null;

  return (
    <>
      <GlassPanel className={`${standalone ? "" : "mt-3"} flex flex-col overflow-hidden`}>
        <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line-soft px-4 py-3">
          {!standalone && (
            <div className="flex items-baseline gap-2">
              <h2 className="flex items-center gap-2 text-lead font-semibold text-fg">
                <IconPulse className="h-3.5 w-3.5 text-violet" />
                Voice follow-up
              </h2>
              <span className="font-mono text-micro tabular-nums text-fg-muted">
                {calls.length}
              </span>
            </div>
          )}

          <div role="group" aria-label="Filter calls" className="flex flex-wrap gap-1.5">
            {FILTERS.map((f) => {
              const active = filter === f.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setFilter(f.id)}
                  aria-pressed={active}
                  className={`-my-1.5 inline-flex min-h-[44px] cursor-pointer items-center rounded-lg border px-2.5 text-[11px] font-medium transition-colors duration-[--t-hover] ease-swift
                    ${active
                      ? "border-violet/50 bg-violet/12 text-violet"
                      : "border-line bg-fill text-fg-muted hover:border-line-strong hover:text-fg"}`}
                >
                  {f.label}
                  <span className="ml-1.5 font-mono tabular-nums opacity-70">
                    {counts[f.id]}
                  </span>
                </button>
              );
            })}
          </div>
        </header>

        <p className="px-4 pt-2.5 text-[11px] leading-snug text-fg-faint">
          Automated calls to candidates who had not responded to their Offer
          Letter. Open one to read the transcript.{" "}
          <span className="text-hold">
            A verbal yes is not an acceptance — the candidate still has to confirm
            in the portal.
          </span>
        </p>

        {blocked && (
          <p
            role="status"
            className="mx-4 mt-2.5 flex items-start gap-2 rounded-lg border border-hold/25 bg-hold/[0.07] px-3 py-2 text-[12px] leading-snug text-fg-muted"
          >
            <IconAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-hold" />
            {blocked}
          </p>
        )}

        {error && (
          <p role="alert" className="mx-4 mt-2.5 text-[12px] text-alarm">{error}</p>
        )}

        {loading ? (
          <div className="space-y-px p-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-[52px] animate-pulse rounded-lg bg-fill" />
            ))}
          </div>
        ) : visible.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 px-4 py-10 text-center">
            <IconSearch className="h-5 w-5 text-fg-faint" />
            <p className="text-[13px] text-fg-muted">
              {calls.length === 0
                ? "No calls have been placed yet."
                : "No calls match this filter."}
            </p>
            {calls.length > 0 && filter !== "ALL" && (
              <button
                type="button"
                onClick={() => setFilter("ALL")}
                className="min-h-[44px] cursor-pointer text-[13px] font-medium text-violet hover:underline"
              >
                Show all {calls.length}
              </button>
            )}
          </div>
        ) : (
          <ul className="thin-scroll max-h-[320px] space-y-px overflow-y-auto p-2">
            {visible.map((c) => {
              const answered = c.call_outcome === "COMPLETED";
              return (
                <li key={c.call_id}>
                  <button
                    type="button"
                    onClick={() => setOpen(c)}
                    className="group flex min-h-[52px] w-full cursor-pointer items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors duration-[--t-hover] hover:bg-fill-strong"
                  >
                    <span
                      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
                        answered
                          ? "border-settled/35 bg-settled/12 text-settled"
                          : "border-line bg-fill text-fg-faint"
                      }`}
                      aria-hidden="true"
                    >
                      {answered ? <IconCheck className="h-3.5 w-3.5" />
                                : <IconX className="h-3.5 w-3.5" />}
                    </span>

                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-1.5">
                        <span className="truncate text-[13px] font-medium text-fg">
                          {c.candidate_name || c.candidate_id || "Candidate"}
                        </span>
                        {c.call_type === "FINAL" && (
                          <span className="shrink-0 rounded border border-violet/30 bg-violet/10 px-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-violet">
                            Final
                          </span>
                        )}
                      </span>
                      <span className="block truncate font-mono text-[11px] text-fg-muted">
                        {c.phone_masked}
                        {c.designation ? ` · ${c.designation}` : ""}
                      </span>
                      <span className="block truncate font-mono text-[10px] tabular-nums text-fg-faint sm:hidden">
                        {callDate(c.started_at)}
                      </span>
                    </span>

                    <span className="flex shrink-0 items-center gap-1.5">
                      {c.candidate_intent && (
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                            INTENT_TONE[c.candidate_intent] ?? INTENT_TONE.NO_RESPONSE
                          }`}
                        >
                          {INTENT_LABEL[c.candidate_intent] ?? c.candidate_intent}
                        </span>
                      )}
                      {!answered && c.call_outcome && (
                        <span className="rounded-full border border-line-strong bg-fill-strong px-2 py-0.5 text-[10px] text-fg-muted">
                          {OUTCOME_LABEL[c.call_outcome] ?? c.call_outcome}
                        </span>
                      )}
                    </span>

                    <span className="hidden shrink-0 text-right sm:block">
                      <span className="block font-mono text-[11px] tabular-nums text-fg-muted">
                        {callDate(c.started_at)}
                      </span>
                      <span className="block font-mono text-[10px] tabular-nums text-fg-faint">
                        {duration(c.duration_s)}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </GlassPanel>

      <CallTranscript call={open} onClose={() => setOpen(null)} />
    </>
  );
}

export { INTENT_LABEL, INTENT_TONE, OUTCOME_LABEL, duration, callDate };
