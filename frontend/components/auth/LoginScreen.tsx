"use client";

import { useEffect, useRef, useState } from "react";

import { LogoMark } from "@/components/brand/Logo";
import { AgentScene } from "@/components/scene/AgentScene";
import { AGENT_PROFILES } from "@/lib/agentState";
import { Button } from "@/components/ui/Button";
import { TextField } from "@/components/ui/Field";
import { IconAlert, IconLock } from "@/components/ui/Icons";
import { NetworkError, api } from "@/lib/api";
import { setSession } from "@/lib/session";

/**
 * Operator sign-in.
 *
 * Deliberately says nothing about which half of a failed login was wrong —
 * the backend returns one message for both, and repeating it here keeps that
 * property instead of undoing it in the UI.
 */
export function LoginScreen({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState("hr");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);

  // The username is prefilled, so the password is where the operator wants to
  // land — not the first field in the DOM.
  useEffect(() => { passwordRef.current?.focus(); }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.login(username.trim(), password);
      setSession({ token: r.token, username: r.username, expiresAt: r.expires_at });
      setPassword("");
      onSignedIn();
    } catch (err) {
      setError(
        err instanceof NetworkError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Could not sign in.",
      );
      setPassword("");
      passwordRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  return (
    // The scene lives here and nowhere else. It is a brand moment on the one
    // screen with nothing to read past it; on the onboarding flow it competed
    // with a nine-field form. `data-theme="dark"` is local — the console is
    // light, but a WebGL object needs a dark ground to read against.
    // No `bg-void` here, deliberately. AgentScene renders at `-z-10`; giving
    // this wrapper both `relative` and a background makes it a stacking
    // context, and the canvas then paints *behind* that background and
    // disappears. The page ground comes from <body> instead.
    <div data-theme="dark" className="relative min-h-dvh overflow-hidden">
      <AgentScene profile={AGENT_PROFILES.attentive} />

      {/* Split, not centred. The canvas is fixed and full-bleed, so a card in
          the middle of the viewport sits exactly on top of the object and
          hides the only thing it was brought back for. Brand on the left,
          form on the right — which is also how most products do this. */}
      <div className="relative mx-auto grid min-h-dvh w-full max-w-[1100px] items-center gap-10 px-5 py-10 lg:grid-cols-2 lg:gap-16">
        <div className="hidden lg:block">
          {/* Feathered scrim under the copy only, so the headline clears
              4.5:1 when particles drift behind it. */}
          <div className="relative">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute -inset-x-10 -inset-y-12"
              // Near-opaque at the centre: the object's brightest band runs
              // straight through this copy, and the muted paragraph colour
              // has nothing like the headline's margin. A scrim that only
              // half-covers is worse than none — it looks like a smudge and
              // still fails contrast.
              style={{
                background:
                  "radial-gradient(74% 64% at 32% 50%, rgba(7,9,12,0.95) 25%, rgba(7,9,12,0.78) 55%, transparent 85%)",
              }}
            />
            <div className="relative">
              <h2 className="text-balance text-[34px] font-semibold leading-[1.1] tracking-[-0.025em] text-fg">
                Offer to onboarding,<br />without the chasing.
              </h2>
              <p className="mt-4 max-w-[38ch] text-pretty text-base leading-relaxed text-fg-muted">
                Payroll computed in Python, letters generated from templates,
                and nothing sent to a candidate without your approval.
              </p>
            </div>
          </div>
        </div>

        <div className="surface mx-auto w-full max-w-[380px] rounded-card p-6 sm:p-7 lg:mx-0">
        <div className="flex items-center gap-2.5">
          <LogoMark className="h-9 w-9 shrink-0 text-fg" interactive={false} />
          <div className="leading-tight">
            <h1 className="text-lead font-semibold text-fg">
              Aperture
            </h1>
            <p className="text-micro text-fg-faint">
              Onboarding Control
            </p>
          </div>
        </div>

        <p className="mt-4 flex items-start gap-2 text-base leading-relaxed text-fg-muted">
          <IconLock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fg-faint" />
          This console can release offer and appointment letters. Sign in to
          continue.
        </p>

        <form onSubmit={submit} className="mt-5 space-y-4">
          <TextField
            label="Username"
            value={username}
            onChange={setUsername}
          />

          {/* Not the project's TextField: that one has no ref or type="password". */}
          <div className="space-y-1.5">
            <label
              htmlFor="hr-password"
              className="block text-body font-medium text-fg-muted"
            >
              Password
            </label>
            <input
              id="hr-password"
              ref={passwordRef}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? "login-error" : undefined}
              className="min-h-[44px] w-full rounded-lg border border-line bg-fill px-3 text-base text-fg outline-none transition-colors duration-[--t-hover] placeholder:text-fg-faint focus:border-signal/60 focus:bg-fill-strong"
            />
          </div>

          {error && (
            <p
              id="login-error"
              role="alert"
              className="flex items-start gap-2 rounded-lg border border-alarm/30 bg-alarm/[0.08] px-3 py-2 text-body leading-snug text-fg-muted"
            >
              <IconAlert className="mt-0.5 h-4 w-4 shrink-0 text-alarm" />
              {error}
            </p>
          )}

          <Button
            type="submit"
            variant="primary"
            className="w-full"
            loading={busy}
            disabled={busy || !password}
          >
            Sign in
          </Button>
        </form>

        <p className="mt-4 text-body leading-relaxed text-fg-faint">
          No password set? The API prints a generated one to its console on
          startup — look for the <code className="font-mono">[auth]</code> lines.
        </p>
      </div>
      </div>
    </div>
  );
}
