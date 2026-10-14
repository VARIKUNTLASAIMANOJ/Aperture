"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { GlassPanel } from "@/components/ui/GlassPanel";
import {
  IconAlert, IconCheck, IconClock, IconLock, IconMail, IconShield,
} from "@/components/ui/Icons";
import { api } from "@/lib/api";
import { openBlob, saveBlob } from "@/lib/download";
import type { StageRow, StagesResponse } from "@/lib/types";

/**
 * §4 — the Selection / Offer / Appointment / Onboarding progression.
 *
 * Statuses AND available actions both come from GET /stages, which is derived
 * from core.lifecycle on the server. The UI never decides for itself whether a
 * button should be enabled: if it did, the rule would exist in two places and
 * eventually disagree with the one the API actually enforces.
 */

const STATUS_TONE: Record<string, string> = {
  SELECTED: "border-signal/30 bg-signal/10 text-signal",
  RELEASED: "border-signal/30 bg-signal/10 text-signal",
  VIEWED: "border-signal/30 bg-signal/10 text-signal",
  ACCEPTED: "border-settled/30 bg-settled/10 text-settled",
  DECLINED: "border-alarm/30 bg-alarm/10 text-alarm",
  EXPIRED: "border-alarm/30 bg-alarm/10 text-alarm",
  ELIGIBLE: "border-hold/30 bg-hold/10 text-hold",
  DRAFT: "border-line-strong bg-fill-strong text-fg-muted",
  NOT_CREATED: "border-line bg-fill text-fg-faint",
  NOT_ELIGIBLE: "border-line bg-fill text-fg-faint",
  NOT_STARTED: "border-line bg-fill text-fg-faint",
  IN_PROGRESS: "border-settled/30 bg-settled/10 text-settled",
  COMPLETED: "border-settled/30 bg-settled/10 text-settled",
  PENDING: "border-line bg-fill text-fg-faint",
};

/** Human labels — §4's example wording, not raw enum names. */
const STATUS_LABEL: Record<string, string> = {
  NOT_CREATED: "Not created",
  NOT_ELIGIBLE: "Pending",
  ELIGIBLE: "Ready to release",
  DRAFT: "Drafted — not released",
  RELEASED: "Released",
  VIEWED: "Viewed by candidate",
  ACCEPTED: "Accepted",
  DECLINED: "Declined",
  EXPIRED: "Expired",
  NOT_STARTED: "Not started",
  IN_PROGRESS: "In progress",
  COMPLETED: "Completed",
  SELECTED: "Selected",
  PENDING: "Pending",
};

const STAGE_ICON: Record<string, React.ReactNode> = {
  Selection: <IconCheck className="h-3.5 w-3.5" />,
  "Offer Letter": <IconMail className="h-3.5 w-3.5" />,
  "Appointment Letter": <IconShield className="h-3.5 w-3.5" />,
  Onboarding: <IconClock className="h-3.5 w-3.5" />,
};

const ACTION_LABEL: Record<string, string> = {
  RELEASE_OFFER: "Release Offer Letter",
  VIEW_OFFER: "View Offer Letter",
  DOWNLOAD_OFFER: "Download PDF",
  RELEASE_APPOINTMENT: "Release Appointment Letter",
  VIEW_APPOINTMENT: "View Appointment Letter",
  DOWNLOAD_APPOINTMENT: "Download PDF",
  START_ONBOARDING: "Start Onboarding",
};

interface Props {
  threadId: string;
  operator?: string;
  onChanged?: () => void;
}

export function StageTable({
  threadId,
  operator = "hr-console@company.com",
  onChanged,
}: Props) {
  const [data, setData] = useState<StagesResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.stages(threadId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the stages.");
    }
  }, [threadId]);

  useEffect(() => { void load(); }, [load]);

  const act = async (action: string) => {
    setBusy(action);
    setError(null);
    setFlash(null);
    try {
      if (action === "RELEASE_OFFER") {
        const r = await api.releaseOffer(threadId, operator);
        setFlash(`Offer Letter ${r.document_number} released to the candidate.`);
      } else if (action === "RELEASE_APPOINTMENT") {
        const r = await api.releaseAppointment(threadId, operator);
        setFlash(`Appointment Letter ${r.document_number} released. Onboarding can begin.`);
      } else if (action.startsWith("VIEW_") || action.startsWith("DOWNLOAD_")) {
        // This used to open /thread/{id}/document/{kind}, a route that was
        // never built — every View and Download on this table 404'd.
        const kind = action.includes("APPOINTMENT") ? "appointment" : "offer";
        const { blob, filename } = await api.documentPdf({ threadId, kind });
        if (action.startsWith("VIEW_")) openBlob(blob);
        else saveBlob(blob, filename);
        setBusy(null);
        return;
      }
      await load();
      onChanged?.();
    } catch (e) {
      // The API returns {message, rule}; surface the rule so a refusal
      // explains WHICH business rule blocked it rather than just failing.
      const anyErr = e as { detail?: { message?: string; rule?: string }; message?: string };
      const d = anyErr?.detail;
      setError(d?.message ? `${d.rule ? d.rule + ": " : ""}${d.message}` : (anyErr.message ?? "Action failed."));
    } finally {
      setBusy(null);
    }
  };

  if (error && !data) {
    return (
      <GlassPanel className="p-4">
        <p role="alert" className="text-[13px] text-alarm">{error}</p>
      </GlassPanel>
    );
  }
  if (!data) {
    return <GlassPanel className="h-[188px] animate-pulse"><span /></GlassPanel>;
  }

  return (
    <GlassPanel className="overflow-hidden">
      <header className="flex items-baseline justify-between gap-3 border-b border-line-soft px-4 py-3">
        <h2 className="text-lead font-semibold text-fg">
          Employment progression
        </h2>
        <span className="truncate text-[11px] text-fg-muted">
          {data.candidate_name}{data.designation ? ` · ${data.designation}` : ""}
        </span>
      </header>

      {flash && (
        <p
          role="status"
          className="flex items-center gap-2 border-b border-settled/20 bg-settled/[0.07] px-4 py-2.5 text-[13px] text-settled"
        >
          <IconCheck className="h-4 w-4 shrink-0" />
          {flash}
        </p>
      )}
      {error && (
        <p
          role="alert"
          className="flex items-start gap-2 border-b border-alarm/20 bg-alarm/[0.07] px-4 py-2.5 text-[13px] text-fg-muted"
        >
          <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
          {error}
        </p>
      )}

      <ul className="divide-y divide-line-soft">
        {data.stages.map((row: StageRow, i) => {
          const primary = row.actions.find((a) => a.startsWith("RELEASE_") || a === "START_ONBOARDING");
          const secondary = row.actions.filter((a) => a !== primary);
          const done = ["ACCEPTED", "RELEASED", "VIEWED", "SELECTED", "COMPLETED", "IN_PROGRESS"]
            .includes(row.status);

          return (
            <li key={row.stage} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
              {/* Rail: filled once the stage is reached, so the sequence is
                  readable at a glance (§4 "make the workflow visually obvious"). */}
              <span className="flex w-[168px] shrink-0 items-center gap-2">
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${
                    done ? "border-settled/40 bg-settled/15 text-settled"
                         : "border-line bg-fill text-fg-faint"
                  }`}
                  aria-hidden="true"
                >
                  {STAGE_ICON[row.stage] ?? <span className="text-[10px]">{i + 1}</span>}
                </span>
                <span className="truncate text-[13px] font-medium text-fg">{row.stage}</span>
              </span>

              <span
                className={`shrink-0 rounded-full border px-2.5 py-0.5 text-micro font-medium ${
                  STATUS_TONE[row.status] ?? STATUS_TONE.PENDING
                }`}
              >
                {STATUS_LABEL[row.status] ?? row.status}
              </span>

              <span className="min-w-0 flex-1">
                {/* Rule 5/§11: when an action is unavailable, say why rather
                    than showing a dead button. */}
                {!row.actions.length && row.blocked_reason && (
                  <span className="flex items-center gap-1.5 text-[11px] leading-snug text-fg-faint">
                    <IconLock className="h-3 w-3 shrink-0" />
                    {row.blocked_reason}
                  </span>
                )}
              </span>

              <span className="flex shrink-0 flex-wrap items-center gap-2">
                {secondary.map((a) => (
                  <Button
                    key={a}
                    variant="ghost"
                    className="!min-h-[36px] !px-3 !text-[12px]"
                    onClick={() => act(a)}
                  >
                    {ACTION_LABEL[a] ?? a}
                  </Button>
                ))}
                {primary && (
                  <Button
                    variant={primary === "RELEASE_APPOINTMENT" ? "hold" : "primary"}
                    className="!min-h-[36px] !px-3.5 !text-[12px]"
                    loading={busy === primary}
                    disabled={busy !== null}
                    onClick={() => act(primary)}
                  >
                    {ACTION_LABEL[primary] ?? primary}
                  </Button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </GlassPanel>
  );
}
