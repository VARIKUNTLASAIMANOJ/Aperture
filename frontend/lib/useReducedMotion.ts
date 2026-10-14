"use client";

import { useEffect, useState } from "react";

/**
 * Live prefers-reduced-motion. Re-reads on change rather than sampling once,
 * so toggling the OS setting takes effect without a reload.
 *
 * Starts `false` and corrects in an effect: reading matchMedia during render
 * would produce a server/client HTML mismatch.
 */
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
