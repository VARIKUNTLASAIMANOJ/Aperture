"use client";

import { useFrame, useThree } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";

/**
 * Responsive placement for the agent.
 *
 * The object must not sit behind the form panel. Glassmorphism only holds its
 * contrast floor over a reasonably even backdrop — parking a bright, moving,
 * high-frequency object directly behind body text pushes it under 4.5:1 no
 * matter how the panel is tuned. So on two-column layouts the agent is anchored
 * in the left column, beside the copy it belongs to; on single-column layouts
 * it retreats upward and shrinks, and the panel takes the foreground.
 */
export function SceneRig({ children }: { children: React.ReactNode }) {
  const group = useRef<THREE.Group>(null);
  const { size, viewport } = useThree();

  useFrame((_, rawDelta) => {
    if (!group.current) return;
    const dt = Math.min(rawDelta, 1 / 20);

    const twoColumn = size.width >= 1024;
    // Convert the CSS breakpoint into world units so the anchor tracks the
    // actual column position rather than a magic number.
    //
    // Y is lifted on desktop so the object occupies the UPPER half of the left
    // column and the headline can sit beneath it. Overlapping them and then
    // darkening the overlap just produces a muddy hole where both the object
    // and the text lose.
    const targetX = twoColumn ? -viewport.width * 0.245 : 0;
    const targetY = twoColumn ? viewport.height * 0.17 : viewport.height * 0.22;
    const targetScale = twoColumn ? 0.92 : 0.7;

    group.current.position.x = THREE.MathUtils.damp(
      group.current.position.x, targetX, 4, dt,
    );
    group.current.position.y = THREE.MathUtils.damp(
      group.current.position.y, targetY, 4, dt,
    );
    const s = THREE.MathUtils.damp(group.current.scale.x, targetScale, 4, dt);
    group.current.scale.setScalar(s);
  });

  return <group ref={group}>{children}</group>;
}
