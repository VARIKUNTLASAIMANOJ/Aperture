"use client";

import { motion, type HTMLMotionProps } from "framer-motion";

import { T } from "@/lib/motion";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { IconSpinner } from "./Icons";

type Variant = "primary" | "ghost" | "hold" | "danger";

interface ButtonProps extends Omit<HTMLMotionProps<"button">, "children"> {
  variant?: Variant;
  loading?: boolean;
  children: React.ReactNode;
}

/**
 * min-h-[44px] is not decorative: ui-ux-pro-max priority 2 (CRITICAL) requires
 * a 44×44px minimum touch target. Every interactive control in this app clears
 * it, including the icon-only ones.
 */
const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-signal text-on-primary font-semibold hover:bg-signal/90 " +
    "shadow-[0_0_0_1px_rgba(34,211,238,0.4),0_8px_30px_-8px_rgba(34,211,238,0.5)]",
  ghost:
    "bg-fill text-fg border border-line hover:bg-fill-strong hover:border-line-strong",
  hold:
    "bg-hold text-on-primary font-semibold hover:bg-hold/90 " +
    "shadow-[0_0_0_1px_rgba(245,158,11,0.4),0_8px_30px_-8px_rgba(245,158,11,0.5)]",
  danger:
    "bg-alarm/12 text-alarm border border-alarm/35 hover:bg-alarm/20 hover:border-alarm/55",
};

export function Button({
  variant = "primary",
  loading = false,
  disabled,
  children,
  className = "",
  ...rest
}: ButtonProps) {
  const reduced = useReducedMotion();
  const isDisabled = disabled || loading;

  return (
    <motion.button
      {...rest}
      disabled={isDisabled}
      // Scale feedback is suppressed under reduced-motion; the colour change
      // still confirms the press, so feedback is never lost entirely.
      whileHover={reduced || isDisabled ? undefined : { scale: 1.02 }}
      whileTap={reduced || isDisabled ? undefined : { scale: 0.975 }}
      transition={T.tap}
      className={`relative inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2
        rounded-xl px-5 text-sm transition-colors duration-[--t-hover] ease-swift
        disabled:cursor-not-allowed disabled:opacity-45
        ${VARIANTS[variant]} ${className}`}
    >
      {loading && <IconSpinner className="h-4 w-4 animate-spin" />}
      {children}
    </motion.button>
  );
}
