"use client";

import { motion, type HTMLMotionProps } from "framer-motion";

interface GlassPanelProps extends HTMLMotionProps<"div"> {
  children: React.ReactNode;
  /**
   * Opt back into the frosted treatment. Only for surfaces that genuinely sit
   * over the WebGL scene — the onboarding hero and modal panels — where the
   * blur separates the card from moving content behind it.
   */
  glass?: boolean;
  /** Specular top edge. Meaningful only with `glass`. */
  lit?: boolean;
}

/**
 * The console's panel surface.
 *
 * Now flat and opaque by default. The frosted version gave every panel the
 * same weight — metrics, queues, correspondence and calls were visually
 * indistinguishable, so nothing on the page could read as primary — and it
 * put a backdrop-filter on a dozen simultaneous surfaces.
 *
 * The name is kept because roughly thirty call sites use it and renaming
 * would be churn for its own sake; `glass` is now an opt-in rather than the
 * default, and the two places that still want it ask for it.
 */
export function GlassPanel({
  children,
  glass = false,
  lit = true,
  className = "",
  ...rest
}: GlassPanelProps) {
  const surface = glass
    ? `glass ${lit ? "glass-lit" : ""} rounded-2xl`
    : "surface rounded-card";

  return (
    <motion.div {...rest} className={`${surface} ${className}`}>
      {children}
    </motion.div>
  );
}
