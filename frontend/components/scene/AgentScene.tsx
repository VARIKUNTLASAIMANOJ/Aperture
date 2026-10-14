"use client";

import { Canvas } from "@react-three/fiber";
import { useEffect, useRef, useState } from "react";

import type { AgentProfile } from "@/lib/agentState";
import { useReducedMotion } from "@/lib/useReducedMotion";
import { AgentCore } from "./AgentCore";
import { ParticleField } from "./ParticleField";
import { SceneRig } from "./SceneRig";

interface AgentSceneProps {
  profile: AgentProfile;
}

/**
 * Fixed WebGL layer. Sits behind every HTML overlay and never intercepts
 * pointer events, so the canvas can span the viewport without stealing
 * clicks or focus from the form.
 */
export function AgentScene({ profile }: AgentSceneProps) {
  const pointer = useRef({ x: 0, y: 0 });
  const reducedMotion = useReducedMotion();
  const [visible, setVisible] = useState(true);
  const [failed, setFailed] = useState(false);

  // Pointer tracked on window, not the canvas: the canvas is pointer-events:none
  // and the cursor spends most of its time over the glass panels on top.
  useEffect(() => {
    if (reducedMotion) return;
    const onMove = (e: PointerEvent) => {
      pointer.current.x = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.current.y = -((e.clientY / window.innerHeight) * 2 - 1);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [reducedMotion]);

  // threejs stack guideline "Pause Render Loop on Tab Hidden": continuous
  // rendering in a background tab burns CPU/GPU and battery for nothing.
  // R3F's equivalent of setAnimationLoop(null) is frameloop="never".
  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  if (failed) {
    // No WebGL (or context lost). The UI must stay fully usable — the 3D layer
    // is atmosphere, never the only carrier of information.
    return (
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 -z-10"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 42%, rgba(34,211,238,0.10), transparent 70%), radial-gradient(40% 40% at 78% 78%, rgba(8,145,178,0.08), transparent 70%)",
        }}
      />
    );
  }

  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 -z-10"
      data-testid="agent-canvas"
    >
      <Canvas
        // dpr capped at 2: retina displays would otherwise render 3× the
        // fragments for no perceptible gain on a soft-edged object.
        dpr={[1, 2]}
        camera={{ position: [0, 0, 5.4], fov: 42 }}
        frameloop={visible ? "always" : "never"}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        onCreated={({ gl }) => {
          gl.domElement.addEventListener("webglcontextlost", () => setFailed(true));
        }}
        fallback={null}
      >
        <SceneRig>
          <AgentCore
            profile={profile}
            pointer={pointer}
            reducedMotion={reducedMotion}
          />
          <ParticleField
            energy={profile.energy}
            color={profile.rim}
            reducedMotion={reducedMotion}
          />
        </SceneRig>
      </Canvas>
    </div>
  );
}
