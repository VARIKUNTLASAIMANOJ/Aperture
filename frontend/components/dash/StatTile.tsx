"use client";

import { motion } from "framer-motion";

import { T } from "@/lib/motion";
import { useReducedMotion } from "@/lib/useReducedMotion";

export type Tone = "neutral" | "signal" | "hold" | "settled" | "alarm";

const TONE: Record<Tone, { value: string; icon: string; glow: string }> = {
  neutral: { value: "text-fg", icon: "text-fg-muted", glow: "" },
  signal: { value: "text-signal", icon: "text-signal", glow: "rgba(34,211,238,0.18)" },
  hold: { value: "text-hold", icon: "text-hold", glow: "rgba(245,158,11,0.18)" },
  settled: { value: "text-settled", icon: "text-settled", glow: "rgba(52,211,153,0.18)" },
  alarm: { value: "text-alarm", icon: "text-alarm", glow: "rgba(248,113,113,0.18)" },
};

interface StatTileProps {
  label: string;
  value: number | string;
  /** Short clarification of what the number actually counts. */
  caption: string;
  tone?: Tone;
  icon: React.ReactNode;
  index?: number;
  /** Renders the tile as a button when the figure is actionable. */
  onClick?: () => void;
}

export function StatTile({
  label, value, caption, tone = "neutral", icon, index = 0, onClick,
}: StatTileProps) {
  const reduced = useReducedMotion();
  const t = TONE[tone];
  const interactive = !!onClick;

  const body = (
    <>
      {t.glow && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -right-6 -top-8 h-24 w-24 rounded-full blur-2xl"
          style={{ background: t.glow }}
        />
      )}

      <div className="relative flex items-start justify-between gap-3">
        <p className="text-[10px] font-medium uppercase tracking-[0.15em] text-fg-muted">
          {label}
        </p>
        <span className={`shrink-0 ${t.icon}`}>{icon}</span>
      </div>

      <p
        className={`relative mt-2 font-mono text-[30px] font-semibold leading-none tabular-nums ${t.value}`}
      >
        {value}
      </p>

      <p className="relative mt-1.5 text-[11px] leading-snug text-fg-faint">
        {caption}
      </p>
    </>
  );

  const shell =
    "glass glass-lit relative min-h-[112px] w-full overflow-hidden rounded-xl p-4 text-left " +
    "transition-colors duration-[--t-hover] ease-swift";

  return (
    <motion.div
      initial={reduced ? { opacity: 0 } : { opacity: 0, y: 14, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={
        reduced
          ? { duration: 0.12 }
          : { ...T.panel, delay: 0.04 * index }
      }
    >
      {interactive ? (
        <button
          type="button"
          onClick={onClick}
          className={`${shell} cursor-pointer hover:border-line-strong hover:bg-fill-strong`}
        >
          {body}
        </button>
      ) : (
        <div className={shell}>{body}</div>
      )}
    </motion.div>
  );
}
