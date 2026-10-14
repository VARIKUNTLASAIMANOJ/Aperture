import type { Transition, Variants } from "framer-motion";

/**
 * Shared motion tokens.
 *
 * ux-guidelines "Duration Timing" — Don't: "One duration copied to every
 * transition". Each token below is tied to a distinct interaction class, and
 * exits are quicker than entrances because a leaving element has already been
 * read and shouldn't hold the user up.
 */
export const EASE_SWIFT = [0.22, 1, 0.36, 1] as const;
export const EASE_SETTLE = [0.16, 1, 0.3, 1] as const;

export const T = {
  tap: { duration: 0.12, ease: EASE_SWIFT } satisfies Transition,
  hover: { duration: 0.22, ease: EASE_SWIFT } satisfies Transition,
  field: { duration: 0.3, ease: EASE_SWIFT } satisfies Transition,
  panel: { duration: 0.46, ease: EASE_SETTLE } satisfies Transition,
  panelExit: { duration: 0.26, ease: EASE_SWIFT } satisfies Transition,
  spring: { type: "spring", stiffness: 260, damping: 30, mass: 0.9 } satisfies Transition,
};

/**
 * Step transitions. `direction` lets a "back" navigation reverse the spatial
 * movement so the flow keeps a consistent sense of place.
 */
export function stepVariants(reduced: boolean): Variants {
  if (reduced) {
    // ux-guidelines "Reduced Motion": no translation, no scale. Opacity only,
    // and fast enough to read as an instant swap.
    return {
      enter: { opacity: 0 },
      center: { opacity: 1, transition: { duration: 0.12 } },
      exit: { opacity: 0, transition: { duration: 0.08 } },
    };
  }
  return {
    enter: (dir: number) => ({
      opacity: 0,
      y: dir >= 0 ? 26 : -26,
      scale: 0.985,
      filter: "blur(6px)",
    }),
    center: {
      opacity: 1,
      y: 0,
      scale: 1,
      filter: "blur(0px)",
      transition: T.panel,
    },
    exit: (dir: number) => ({
      opacity: 0,
      y: dir >= 0 ? -20 : 20,
      scale: 0.99,
      filter: "blur(4px)",
      transition: T.panelExit,
    }),
  };
}

/**
 * Staggered reveal for fields inside a step.
 *
 * `enter`/`exit` are declared explicitly (even though empty) so the wrapper can
 * be driven directly with initial/animate instead of inheriting the step's
 * variant state through three levels of nesting. Behaviourally equivalent to
 * inheriting, but it keeps the orchestration readable at the call site.
 */
export function fieldStagger(reduced: boolean): Variants {
  return {
    enter: {},
    exit: {},
    center: {
      transition: reduced
        ? {}
        : { staggerChildren: 0.05, delayChildren: 0.08 },
    },
  };
}

export function fieldItem(reduced: boolean): Variants {
  if (reduced) return { enter: { opacity: 1 }, center: { opacity: 1 } };
  return {
    enter: { opacity: 0, y: 12 },
    center: { opacity: 1, y: 0, transition: T.field },
  };
}
