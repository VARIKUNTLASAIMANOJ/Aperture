"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { clearSession, getSession, onSessionChange } from "@/lib/session";
import { LoginScreen } from "./LoginScreen";

type State = "checking" | "in" | "out";

/**
 * Renders the console only for a signed-in operator.
 *
 * Wraps the HR pages rather than living inside the dashboard, so a new HR page
 * is protected by being placed inside the gate rather than by remembering to
 * add a check — the same reasoning as the router-level dependency on the API.
 *
 * The candidate portal is deliberately NOT wrapped: candidates have no login.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<State>("checking");

  const check = useCallback(async () => {
    if (!getSession()) {
      setState("out");
      return;
    }
    try {
      // A stored token can be well-formed but no longer valid — the server
      // secret may have rotated. Ask before rendering a console whose every
      // request would 401.
      await api.me();
      setState("in");
    } catch {
      clearSession();
      setState("out");
    }
  }, []);

  useEffect(() => { void check(); }, [check]);

  // Any 401 anywhere clears the session; this returns the user to the login
  // screen without each caller having to handle it.
  useEffect(() => onSessionChange((s) => setState(s ? "in" : "out")), []);

  if (state === "checking") {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <span className="sr-only">Checking your session…</span>
        <span
          aria-hidden="true"
          className="h-6 w-6 animate-spin rounded-full border-2 border-line-strong border-t-signal"
        />
      </div>
    );
  }

  if (state === "out") return <LoginScreen onSignedIn={() => setState("in")} />;

  return <>{children}</>;
}
