"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "./api";
import type { StreamEvent } from "./types";

export interface StreamState {
  events: StreamEvent[];
  latest: StreamEvent | null;
  connected: boolean;
  /** True once the graph reports no pending nodes (reached END). */
  finished: boolean;
  error: string | null;
}

const INITIAL: StreamState = {
  events: [],
  latest: null,
  connected: false,
  finished: false,
  error: null,
};

/**
 * Subscribes to GET /onboarding/{id}/stream.
 *
 * That endpoint is a read-only checkpoint poller — connecting does NOT advance
 * the graph past its HITL interrupt. (It used to: an earlier version resumed
 * the thread on connect, which silently consumed the approval gate. Keep this
 * a pure observer.)
 *
 * EventSource auto-reconnects on transport drop, so the only reconnect logic
 * needed here is closing on terminal events to stop it looping forever.
 */
export function useOnboardingStream(threadId: string | null): StreamState {
  const [state, setState] = useState<StreamState>(INITIAL);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!threadId) {
      setState(INITIAL);
      return;
    }

    setState({ ...INITIAL });
    const es = new EventSource(api.streamUrl(threadId));
    sourceRef.current = es;

    es.onopen = () => {
      setState((s) => ({ ...s, connected: true, error: null }));
    };

    es.onmessage = (raw) => {
      let evt: StreamEvent;
      try {
        evt = JSON.parse(raw.data) as StreamEvent;
      } catch {
        return; // keep-alive comments never reach onmessage, but be safe
      }

      setState((s) => {
        const next: StreamState = {
          ...s,
          connected: true,
          events: [...s.events, evt],
          latest: evt.event === "state_update" ? evt : s.latest,
        };

        if (evt.event === "error" || evt.event === "not_found") {
          next.error = evt.message ?? "Stream reported an error.";
        }
        if (
          evt.event === "done" ||
          evt.event === "not_found" ||
          evt.event === "stream_timeout"
        ) {
          next.finished = evt.event === "done";
          // Terminal: close so EventSource doesn't reconnect in a loop.
          es.close();
          next.connected = false;
        }
        return next;
      });
    };

    es.onerror = () => {
      // Fires on transient drops too; EventSource retries on its own. Only
      // surface it as a hard failure once the socket is actually closed.
      if (es.readyState === EventSource.CLOSED) {
        setState((s) => ({
          ...s,
          connected: false,
          error: s.finished ? null : "Lost connection to the agent stream.",
        }));
      } else {
        setState((s) => ({ ...s, connected: false }));
      }
    };

    return () => {
      es.close();
      sourceRef.current = null;
    };
  }, [threadId]);

  return state;
}
