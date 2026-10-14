"use client";

import { useId } from "react";

/**
 * Product mark.
 *
 * Geometry: a rounded hexagonal aperture (containment — the human-gated
 * boundary the whole product is about) enclosing an abstract agent glyph — a
 * head node above a shoulder arc, with a single ascending path leaving the
 * frame to read as dispatch.
 *
 * Everything is built on a 32×32 grid with whole/half-unit coordinates so the
 * geometry stays crisp at 20px and at 200px. Strokes use `vector-effect:
 * non-scaling-stroke` so weight stays optically constant as the mark scales.
 *
 * Colour adapts: it inherits `currentColor` for the frame and uses a
 * cyan→violet gradient for the glyph, both defined against tokens so light and
 * dark surfaces are handled without swapping assets.
 */

interface LogoMarkProps {
  className?: string;
  /**
   * Kept for call-site intent only. The `logo-mark` class is applied either
   * way, because it also carries the light-mode token adaptation — the hover
   * rules are scoped to `a:hover` / `button:hover` / `.group\/logo:hover`, so a
   * mark that is not inside an interactive element never triggers them anyway.
   */
  interactive?: boolean;
}

export function LogoMark({ className = "h-8 w-8" }: LogoMarkProps) {
  // useId keeps gradient/filter ids unique — duplicate ids across two mounted
  // instances make the second one inherit the first one's paint server.
  const uid = useId().replace(/:/g, "");
  const grad = `lg-grad-${uid}`;
  const glow = `lg-glow-${uid}`;

  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`logo-mark ${className}`}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id={grad} x1="6" y1="4" x2="26" y2="28" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="rgb(var(--c-signal))" />
          <stop offset="55%" stopColor="rgb(var(--c-signal))" />
          <stop offset="100%" stopColor="rgb(var(--c-violet))" />
        </linearGradient>

        {/* Glow lives in the SVG so it tracks the glyph outline exactly; a CSS
            box-shadow would halo the bounding box instead. */}
        <filter id={glow} x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="1.6" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {/* Aperture. Flat-top hexagon, 2px corner radius via rounded joins. */}
      <path
        d="M16 2.5 L27 8.75 V21.25 L16 27.5 L5 21.25 V8.75 Z"
        stroke="currentColor"
        strokeOpacity="0.32"
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        className="logo-frame"
      />

      {/* Agent glyph — head node + shoulder arc. */}
      <g
        stroke={`url(#${grad})`}
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
        className="logo-glyph"
        filter={`url(#${glow})`}
      >
        <circle cx="16" cy="12.5" r="2.75" />
        <path d="M10.5 21.5 a5.5 5.5 0 0 1 11 0" />
      </g>

      {/* Dispatch path — the one element that breaks the frame. */}
      <path
        d="M21.5 21.5 H25.5"
        stroke={`url(#${grad})`}
        strokeWidth="1.75"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
        className="logo-spark"
      />
      <circle cx="27.4" cy="21.5" r="1.15" fill="rgb(var(--c-violet))" className="logo-node" />
    </svg>
  );
}

interface LogoProps {
  className?: string;
  /** Hides the wordmark on narrow layouts while keeping the accessible name. */
  compact?: boolean;
  subtitle?: React.ReactNode;
}

export function Logo({ className = "", compact = false, subtitle }: LogoProps) {
  return (
    <span className={`group/logo flex items-center gap-2.5 ${className}`}>
      <LogoMark className="h-8 w-8 shrink-0 text-fg" />
      <span className={compact ? "sr-only" : "min-w-0 leading-tight"}>
        <span className="block truncate text-[14px] font-semibold tracking-[-0.01em] text-fg">
          Aperture
        </span>
        {subtitle ?? (
          <span className="block whitespace-nowrap text-[10px] uppercase tracking-[0.16em] text-fg-faint">
            Onboarding Agent
          </span>
        )}
      </span>
    </span>
  );
}
