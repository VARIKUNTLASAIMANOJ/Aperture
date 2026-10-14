"use client";

import { motion } from "framer-motion";

import { IconAlert, IconCheck, IconX } from "@/components/ui/Icons";
import type { Draft, Errors } from "@/lib/form";
import { T } from "@/lib/motion";
import { useReducedMotion } from "@/lib/useReducedMotion";
import type { SelectionStatus } from "@/lib/types";

interface Props {
  draft: Draft;
  errors: Errors;
  set: <K extends keyof Draft>(k: K, v: Draft[K]) => void;
}

const OPTIONS: {
  value: Exclude<SelectionStatus, "PENDING">;
  title: string;
  body: string;
  Icon: typeof IconCheck;
  tone: string;
  ring: string;
}[] = [
  {
    value: "SELECTED",
    title: "Extend an offer",
    body: "Routes through payroll calculation and contract drafting, then pauses for your approval before anything is sent.",
    Icon: IconCheck,
    tone: "text-settled",
    ring: "border-settled/50 bg-settled/[0.07]",
  },
  {
    value: "REJECTED",
    title: "Decline the candidate",
    body: "Skips payroll entirely. Drafts an empathetic rejection notice and pauses for your approval before sending.",
    Icon: IconX,
    tone: "text-fg-muted",
    ring: "border-line-strong bg-fill-strong",
  },
];

/**
 * The branch point. Rendered as a real radiogroup: arrow keys move between
 * options, Space/Enter selects, and the selected state is exposed via
 * aria-checked rather than colour alone.
 */
export function DecisionStep({ draft, errors, set }: Props) {
  const reduced = useReducedMotion();

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const idx = OPTIONS.findIndex((o) => o.value === draft.selection_status);
    const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
    const next = (idx < 0 ? 0 : (idx + dir + OPTIONS.length) % OPTIONS.length);
    set("selection_status", OPTIONS[next].value);
  };

  return (
    <div className="space-y-4">
      <div
        role="radiogroup"
        aria-label="Selection outcome"
        aria-describedby={errors.selection_status ? "decision-error" : undefined}
        onKeyDown={onKeyDown}
        className="grid gap-3.5 sm:grid-cols-2"
      >
        {OPTIONS.map((opt, i) => {
          const active = draft.selection_status === opt.value;
          return (
            <motion.button
              key={opt.value}
              type="button"
              role="radio"
              aria-checked={active}
              tabIndex={active || (draft.selection_status === "PENDING" && i === 0) ? 0 : -1}
              onClick={() => set("selection_status", opt.value)}
              whileHover={reduced ? undefined : { y: -3 }}
              whileTap={reduced ? undefined : { scale: 0.985 }}
              transition={T.tap}
              className={`group relative flex min-h-[168px] cursor-pointer flex-col items-start gap-3 overflow-hidden
                rounded-2xl border p-5 text-left transition-colors duration-[--t-hover] ease-swift
                ${active ? opt.ring : "border-line bg-fill hover:border-line-strong hover:bg-fill-strong"}`}
            >
              {/* Sweep highlight — decorative, sits under the content. */}
              <span
                aria-hidden="true"
                className={`pointer-events-none absolute -inset-px opacity-0 transition-opacity duration-500
                  ${active ? "opacity-100" : "group-hover:opacity-60"}`}
                style={{
                  background:
                    "radial-gradient(70% 60% at 15% 0%, rgba(255,255,255,0.09), transparent 70%)",
                }}
              />

              <span
                className={`relative flex h-10 w-10 items-center justify-center rounded-xl border
                  ${active ? "border-line-strong bg-fill-strong" : "border-line bg-fill"} ${opt.tone}`}
              >
                <opt.Icon className="h-[18px] w-[18px]" />
              </span>

              <span className="relative space-y-1.5">
                <span className="block text-[15px] font-semibold text-fg">
                  {opt.title}
                </span>
                <span className="block text-[13px] leading-relaxed text-fg-muted">
                  {opt.body}
                </span>
              </span>

              {active && (
                <motion.span
                  layoutId={reduced ? undefined : "decision-underline"}
                  className="absolute inset-x-0 bottom-0 h-[2px] bg-gradient-to-r from-transparent via-signal to-transparent"
                  transition={T.panel}
                />
              )}
            </motion.button>
          );
        })}
      </div>

      {errors.selection_status && (
        <p
          id="decision-error"
          role="alert"
          className="flex items-center gap-1.5 text-xs font-medium text-alarm"
        >
          <IconAlert className="h-3.5 w-3.5 shrink-0" />
          {errors.selection_status}
        </p>
      )}
    </div>
  );
}
