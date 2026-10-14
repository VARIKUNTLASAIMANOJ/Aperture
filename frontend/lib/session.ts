/**
 * Operator session storage.
 *
 * `sessionStorage`, not `localStorage`: the token dies with the tab, which is
 * the right default for a console that can release employment documents.
 *
 * The honest caveat — a token the page can read is reachable by XSS in a way
 * an HttpOnly cookie is not. A cookie would need `SameSite=None; Secure` to
 * cross from :3000 to :8000, and therefore HTTPS, which local development
 * does not have. Behind a single origin with TLS, move this to a cookie.
 */

const KEY = "aperture.session";

export interface Session {
  token: string;
  username: string;
  expiresAt: number; // unix seconds
}

/** Notifies mounted components when the session appears or disappears. */
type Listener = (s: Session | null) => void;
const listeners = new Set<Listener>();

export function onSessionChange(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function announce(s: Session | null) {
  listeners.forEach((fn) => fn(s));
}

export function getSession(): Session | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(KEY);
    if (!raw) return null;
    const s = JSON.parse(raw) as Session;
    // Expired tokens are dropped here rather than being sent and rejected —
    // one fewer confusing 401 in the console on a stale tab.
    if (!s.token || s.expiresAt * 1000 < Date.now()) {
      sessionStorage.removeItem(KEY);
      return null;
    }
    return s;
  } catch {
    return null;
  }
}

export function setSession(s: Session): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* private mode — the session simply does not survive a reload */
  }
  announce(s);
}

export function clearSession(): void {
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* nothing to clear */
  }
  announce(null);
}

export function authHeader(): Record<string, string> {
  const s = getSession();
  return s ? { Authorization: `Bearer ${s.token}` } : {};
}
