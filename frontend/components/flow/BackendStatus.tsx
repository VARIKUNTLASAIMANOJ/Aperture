"use client";

import { useEffect, useState } from "react";

import { API_BASE, api } from "@/lib/api";

type Status = "checking" | "ready" | "degraded" | "offline";

const COPY: Record<Status, { label: string; dot: string; text: string }> = {
  checking: { label: "Connecting", dot: "bg-fg-faint", text: "text-fg-faint" },
  ready: { label: "Agent online", dot: "bg-settled", text: "text-fg-muted" },
  degraded: { label: "Graph not ready", dot: "bg-hold", text: "text-hold" },
  offline: { label: "Backend offline", dot: "bg-alarm", text: "text-alarm" },
};

/**
 * Live reachability of the FastAPI service.
 *
 * Worth its own indicator because the failure it catches is silent otherwise:
 * with the Python service down, every form step still works perfectly and the
 * user only discovers the problem at the final submit, after entering
 * everything. Better to say so up front.
 */
export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    let alive = true;

    const check = async () => {
      try {
        const res = await api.health();
        if (!alive) return;
        setStatus(res.graph_ready ? "ready" : "degraded");
      } catch {
        if (alive) setStatus("offline");
      }
    };

    void check();
    const id = setInterval(check, 20_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const c = COPY[status];

  return (
    <div
      className="flex shrink-0 items-center gap-2 whitespace-nowrap rounded-full border border-line bg-fill px-3 py-1.5 backdrop-blur-sm"
      title={API_BASE}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot}`} aria-hidden="true" />
      <span
        className={`text-[10px] font-medium ${c.text}`}
        role="status"
      >
        {c.label}
      </span>
    </div>
  );
}
