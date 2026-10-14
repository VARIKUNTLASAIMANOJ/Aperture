"use client";

import { useReducedMotion } from "@/lib/useReducedMotion";

/**
 * Ambient background for the dashboard.
 *
 * Deliberately CSS, not WebGL. The onboarding flow earns its 3D agent because
 * it is a single focused task; a dense operations view does not — a moving,
 * high-frequency object behind tabular data competes with the numbers and
 * costs a render loop for decoration. This keeps the same palette and depth
 * cues (void ground, cyan bloom, grain) at effectively zero cost.
 */
export function AmbientBackdrop() {
  const reduced = useReducedMotion();

  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10">
      {/* Base wash — anchors the page to the same ground as /onboard. */}
      <div
        className="absolute inset-0"
        style={{
          background:
            "radial-gradient(90% 60% at 12% -8%, rgba(34,211,238,0.10), transparent 62%)," +
            "radial-gradient(70% 50% at 96% 4%, rgba(8,145,178,0.09), transparent 60%)," +
            "radial-gradient(60% 45% at 50% 108%, rgba(52,211,153,0.05), transparent 65%)",
        }}
      />

      {/* Slow drift. Transform/opacity only — never width/height, which would
          force layout on every frame. Suppressed under reduced-motion. */}
      {!reduced && (
        <div
          className="absolute -inset-1/4 animate-drift opacity-60"
          style={{
            background:
              "radial-gradient(38% 30% at 30% 35%, rgba(34,211,238,0.07), transparent 70%)",
          }}
        />
      )}

      {/* Hairline grid — reads as an instrument surface, stays under the text. */}
      <div
        className="absolute inset-0 opacity-[0.045]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.7) 1px, transparent 1px)," +
            "linear-gradient(90deg, rgba(255,255,255,0.7) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage:
            "radial-gradient(75% 60% at 50% 30%, #000 30%, transparent 78%)",
          WebkitMaskImage:
            "radial-gradient(75% 60% at 50% 30%, #000 30%, transparent 78%)",
        }}
      />

      <div className="grain absolute inset-0" />
    </div>
  );
}
