"use client";

import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { IconAlert, IconCheck, IconSend } from "@/components/ui/Icons";
import { api } from "@/lib/api";

/**
 * Recovery for a letter that bounced.
 *
 * Shown only when the thread actually has a failed email, so it is absent on
 * every healthy workflow rather than being a permanently available button that
 * mostly errors.
 *
 * The address field is the point. Nearly every real failure here has been a
 * bad recipient ("Invalid `to` field", an unverified domain), and retrying the
 * same address just reproduces it — so the fix and the retry are one action.
 */
export function RetryDispatch({
  threadId,
  currentEmail,
  failureReason,
  operator = "hr-console@company.com",
  onRetried,
}: {
  threadId: string;
  currentEmail?: string;
  failureReason?: string | null;
  operator?: string;
  onRetried?: () => void;
}) {
  const [email, setEmail] = useState(currentEmail ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const retry = async () => {
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const changed = email.trim() && email.trim() !== (currentEmail ?? "");
      const r = await api.retryDispatch(
        threadId, operator, changed ? email.trim() : undefined,
      );
      setDone(r.message);
      onRetried?.();
    } catch (e) {
      const anyErr = e as { detail?: { message?: string }; message?: string };
      setError(anyErr?.detail?.message ?? anyErr.message ?? "The retry failed.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div
        role="status"
        className="flex items-start gap-2.5 rounded-xl border border-settled/30 bg-settled/[0.08] p-4"
      >
        <IconCheck className="mt-0.5 h-4 w-4 shrink-0 text-settled" />
        <p className="text-[13px] leading-relaxed text-fg">{done}</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-alarm/30 bg-alarm/[0.07] p-4">
      <div className="flex items-start gap-2.5">
        <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
        <div className="min-w-0 flex-1 space-y-3">
          <div className="space-y-1">
            <p className="text-[13px] font-medium text-fg">
              This letter was not delivered
            </p>
            {failureReason && (
              <p className="break-words text-[12px] leading-relaxed text-fg-muted">
                {failureReason}
              </p>
            )}
            <p className="text-[12px] leading-relaxed text-fg-muted">
              The candidate was not contacted and nothing was released. Correct
              the address if it was wrong, then re-send.
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[220px] flex-1">
              <TextField
                label="Send to"
                type="email"
                inputMode="email"
                value={email}
                onChange={setEmail}
                placeholder="candidate@company.com"
              />
            </div>
            <Button
              variant="primary"
              className="!min-h-[44px]"
              loading={busy}
              disabled={busy || !email.trim()}
              onClick={retry}
            >
              <IconSend className="h-4 w-4" />
              Re-send
            </Button>
          </div>

          {error && (
            <p role="alert" className="text-[12px] leading-relaxed text-alarm">
              {error}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
