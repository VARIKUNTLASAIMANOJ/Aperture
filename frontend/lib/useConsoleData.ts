"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { NetworkError, api } from "@/lib/api";
import type { AuditEntry, Candidate } from "@/lib/types";

const POLL_MS = 15_000;
/** Past this age the readout is labelled stale rather than presented as live. */
const STALE_AFTER_MS = 45_000;

/**
 * The roster + audit trail, shared by every console view.
 *
 * Lifted out of DashboardView when the single page became four routes: each
 * one needs the same two calls, and duplicating the fetch/poll/stale logic per
 * view is how they drift into disagreeing about what "live" means.
 */
export function useConsoleData() {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const alive = useRef(true);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    try {
      const [c, a] = await Promise.all([api.candidates(), api.allAudit()]);
      if (!alive.current) return;
      setCandidates(c);
      setAudit(a.audit_log);
      setLoadedAt(Date.now());
      setError(null);
    } catch (e) {
      if (!alive.current) return;
      setError(
        e instanceof NetworkError || e instanceof Error
          ? e.message
          : "Could not load console data.",
      );
    } finally {
      if (alive.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    const poll = setInterval(() => void load(), POLL_MS);
    // Drives the "updated Xs ago" label without refetching.
    const tick = setInterval(() => setNow(Date.now()), 5_000);
    return () => {
      alive.current = false;
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [load]);

  const stale = loadedAt !== null && now - loadedAt > STALE_AFTER_MS;

  return {
    candidates, audit, loading, refreshing, error, loadedAt, now, stale,
    live: loadedAt !== null && !stale && !error,
    reload: load,
  };
}
