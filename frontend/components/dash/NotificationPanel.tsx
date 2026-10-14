"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { GlassPanel } from "@/components/ui/GlassPanel";
import { IconArrowRight, IconCheck, IconShield } from "@/components/ui/Icons";
import { api } from "@/lib/api";
import type { HrNotification } from "@/lib/types";

/**
 * §3 — "Appointment Letter Ready".
 *
 * Reuses the existing polling/derivation pattern rather than adding a second
 * notification architecture: the backend derives these from state, so a
 * notification cannot fire before acceptance, cannot fire twice, and cannot go
 * stale after the appointment is released. There is nothing to mark as read.
 */
export function NotificationPanel({ pollMs = 20_000 }: { pollMs?: number }) {
  const [items, setItems] = useState<HrNotification[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.notifications();
      setItems(r.notifications);
    } catch {
      /* the masthead already reports backend reachability */
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), pollMs);
    return () => clearInterval(id);
  }, [load, pollMs]);

  // Empty is the common, healthy case — don't occupy the grid with a panel
  // that says "nothing", but do keep a quiet confirmation once loaded.
  if (loaded && items.length === 0) {
    return (
      <GlassPanel className="flex items-center gap-2.5 px-4 py-3">
        <IconCheck className="h-4 w-4 shrink-0 text-settled" />
        <p className="text-[13px] text-fg-muted">
          No candidates are waiting on an Appointment Letter.
        </p>
      </GlassPanel>
    );
  }
  if (!loaded) return <GlassPanel className="h-[74px] animate-pulse"><span /></GlassPanel>;

  return (
    <GlassPanel className="overflow-hidden border-hold/30 bg-hold/[0.05]">
      <header className="flex items-center justify-between gap-3 border-b border-hold/20 px-4 py-2.5">
        <h2 className="flex items-center gap-2 text-lead font-semibold text-hold">
          <IconShield className="h-3.5 w-3.5" />
          Action required
        </h2>
        <span
          className="rounded-full bg-hold px-2 py-0.5 font-mono text-[11px] font-semibold tabular-nums text-on-primary"
          aria-label={`${items.length} candidates awaiting an Appointment Letter`}
        >
          {items.length}
        </span>
      </header>

      <ul className="divide-y divide-line-soft">
        {items.map((n) => (
          <li key={n.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-[13px] font-semibold text-fg">{n.title}</p>
              <p className="mt-0.5 text-[12px] leading-snug text-fg-muted">{n.body}</p>
            </div>
            {/* Direct action into the appointment workflow, per §3. */}
            <Link
              href={`/thread/${encodeURIComponent(n.thread_id)}`}
              className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-xl bg-hold px-4 text-[13px] font-semibold text-on-primary transition-colors duration-[--t-hover] hover:bg-hold/90"
            >
              {n.action_label}
              <IconArrowRight className="h-4 w-4" />
            </Link>
          </li>
        ))}
      </ul>
    </GlassPanel>
  );
}
