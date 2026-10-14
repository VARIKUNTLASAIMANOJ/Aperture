"use client";

import { motion } from "framer-motion";

import { T } from "@/lib/motion";
import { useReducedMotion } from "@/lib/useReducedMotion";

interface StepProgressProps {
  steps: { id: string; label: string }[];
  activeIndex: number;
  /** Steps the user may jump back to. */
  onJump?: (index: number) => void;
}

/**
 * ux-guidelines "Progress Indicators" — Don't: "No indication of progress".
 *
 * Rendered as an ordered list so assistive tech announces position and count,
 * with the current step marked aria-current. The visual rail is decorative
 * and hidden from the accessibility tree.
 */
export function StepProgress({ steps, activeIndex, onJump }: StepProgressProps) {
  const reduced = useReducedMotion();
  const pct = steps.length > 1 ? activeIndex / (steps.length - 1) : 0;

  return (
    <nav aria-label="Onboarding progress">
      <p className="sr-only" aria-live="polite">
        Step {activeIndex + 1} of {steps.length}: {steps[activeIndex]?.label}
      </p>

      <ol className="flex items-center gap-1.5">
        {steps.map((step, i) => {
          const done = i < activeIndex;
          const active = i === activeIndex;
          const reachable = i < activeIndex && !!onJump;

          return (
            <li key={step.id} className="flex min-w-0 flex-1 items-center">
              <button
                type="button"
                disabled={!reachable}
                aria-current={active ? "step" : undefined}
                onClick={reachable ? () => onJump?.(i) : undefined}
                // 44px target preserved via padding even though the visible
                // rail is 3px tall.
                className={`group relative flex min-h-[44px] w-full flex-col justify-center gap-1.5 px-0.5
                  ${reachable ? "cursor-pointer" : "cursor-default"}`}
              >
                <span className="relative block h-[3px] w-full overflow-hidden rounded-full bg-fill-strong">
                  <motion.span
                    className={`absolute inset-y-0 left-0 rounded-full ${
                      done ? "bg-signal/70" : "bg-signal"
                    }`}
                    initial={false}
                    animate={{ width: done ? "100%" : active ? "45%" : "0%" }}
                    transition={reduced ? { duration: 0.05 } : T.panel}
                  />
                </span>
                <span
                  className={`truncate text-micro font-medium transition-colors duration-[--t-hover]
                    ${active ? "text-fg" : done ? "text-fg-muted group-hover:text-fg" : "text-fg-faint"}`}
                >
                  {step.label}
                </span>
              </button>
            </li>
          );
        })}
      </ol>

      <span className="sr-only">{Math.round(pct * 100)}% complete</span>
    </nav>
  );
}
