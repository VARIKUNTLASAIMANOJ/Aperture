"use client";

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

import type { AgentProfile } from "@/lib/agentState";
import { AGENT_FRAG, AGENT_VERT } from "./shaders";

interface AgentCoreProps {
  profile: AgentProfile;
  /** Normalised pointer, -1..1 on both axes. */
  pointer: React.MutableRefObject<{ x: number; y: number }>;
  reducedMotion: boolean;
}

/**
 * The anchor object.
 *
 * Nothing here snaps. Every visual property is damped toward the incoming
 * profile with THREE.MathUtils.damp, which is frame-rate independent — a naive
 * `lerp(a, b, 0.1)` per frame moves twice as fast on a 120Hz display as on a
 * 60Hz one, so the transition speed would depend on the user's monitor.
 */
export function AgentCore({ profile, pointer, reducedMotion }: AgentCoreProps) {
  const group = useRef<THREE.Group>(null);
  const core = useRef<THREE.Mesh>(null);
  const shell = useRef<THREE.LineSegments>(null);
  const halo = useRef<THREE.Mesh>(null);

  // Mutable animation state — damped toward `profile` every frame.
  const current = useRef({
    amp: profile.amplitude,
    freq: profile.frequency,
    faceted: profile.faceted,
    spin: profile.spin,
    pulse: profile.pulse,
    scale: profile.scale,
    shell: profile.shell,
    churn: profile.churn,
  });

  const noiseClock = useRef(0);

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uAmp: { value: profile.amplitude },
      uFreq: { value: profile.frequency },
      uFaceted: { value: profile.faceted },
      uColor: { value: new THREE.Color(profile.color) },
      uRim: { value: new THREE.Color(profile.rim) },
      uOpacity: { value: 1 },
    }),
    // Intentionally built once: values are mutated in useFrame, never
    // re-created, so React never has to re-upload the material.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const targetColor = useMemo(() => new THREE.Color(), []);
  const targetRim = useMemo(() => new THREE.Color(), []);

  const shellGeometry = useMemo(() => {
    const geo = new THREE.IcosahedronGeometry(1, 2);
    return new THREE.WireframeGeometry(geo);
  }, []);

  useFrame((state, rawDelta) => {
    // Clamp: a backgrounded tab can deliver a multi-second delta on resume,
    // which would fling every damped value past its target in one step.
    const dt = Math.min(rawDelta, 1 / 20);
    const c = current.current;

    // λ values differ per property on purpose — colour settles slower than
    // rotation so the mood change reads as a wash rather than a flash.
    c.amp = THREE.MathUtils.damp(c.amp, profile.amplitude, 3.2, dt);
    c.freq = THREE.MathUtils.damp(c.freq, profile.frequency, 2.6, dt);
    c.faceted = THREE.MathUtils.damp(c.faceted, profile.faceted, 2.4, dt);
    c.spin = THREE.MathUtils.damp(c.spin, profile.spin, 2.0, dt);
    c.pulse = THREE.MathUtils.damp(c.pulse, profile.pulse, 2.4, dt);
    c.scale = THREE.MathUtils.damp(c.scale, profile.scale, 3.0, dt);
    c.shell = THREE.MathUtils.damp(c.shell, profile.shell, 2.6, dt);
    c.churn = THREE.MathUtils.damp(c.churn, profile.churn, 2.0, dt);

    // Noise time advances by its own damped rate, so speeding up or slowing
    // down never causes a discontinuity in the field.
    noiseClock.current += dt * c.churn;

    uniforms.uTime.value = noiseClock.current;
    uniforms.uAmp.value = c.amp;
    uniforms.uFreq.value = c.freq;
    uniforms.uFaceted.value = c.faceted;

    targetColor.set(profile.color);
    targetRim.set(profile.rim);
    (uniforms.uColor.value as THREE.Color).lerp(targetColor, 1 - Math.exp(-2.2 * dt));
    (uniforms.uRim.value as THREE.Color).lerp(targetRim, 1 - Math.exp(-2.2 * dt));

    const t = state.clock.elapsedTime;

    if (group.current) {
      // Pointer parallax, damped. The object leans toward the cursor.
      const px = reducedMotion ? 0 : pointer.current.x;
      const py = reducedMotion ? 0 : pointer.current.y;

      group.current.rotation.x = THREE.MathUtils.damp(
        group.current.rotation.x, -py * 0.32, 3.4, dt,
      );
      group.current.rotation.z = THREE.MathUtils.damp(
        group.current.rotation.z, px * 0.16, 3.4, dt,
      );
      group.current.position.x = THREE.MathUtils.damp(
        group.current.position.x, px * 0.28, 3.0, dt,
      );
      group.current.position.y = THREE.MathUtils.damp(
        group.current.position.y,
        py * 0.2 + (reducedMotion ? 0 : Math.sin(t * 0.55) * 0.07),
        3.0, dt,
      );

      // Breathing. Suppressed under reduced-motion, but scale still damps to
      // its profile target so mood changes remain legible.
      const breath = reducedMotion ? 1 : 1 + Math.sin(t * 1.15) * 0.028 * c.pulse;
      const s = c.scale * breath;
      group.current.scale.setScalar(s);
    }

    if (core.current && !reducedMotion) {
      core.current.rotation.y += dt * c.spin;
    }

    if (shell.current) {
      shell.current.scale.setScalar(c.shell);
      if (!reducedMotion) {
        // Counter-rotation separates the shell from the core visually.
        shell.current.rotation.y -= dt * c.spin * 0.62;
        shell.current.rotation.x += dt * c.spin * 0.18;
      }
      const mat = shell.current.material as THREE.LineBasicMaterial;
      mat.color.copy(uniforms.uRim.value as THREE.Color);
      mat.opacity = 0.16 + c.pulse * 0.1;
    }

    if (halo.current) {
      const mat = halo.current.material as THREE.MeshBasicMaterial;
      mat.color.copy(uniforms.uRim.value as THREE.Color);
      const flicker = reducedMotion ? 0.5 : 0.5 + Math.sin(t * 1.6) * 0.5;
      mat.opacity = 0.035 + c.pulse * 0.05 * flicker;
      halo.current.scale.setScalar(c.shell * 1.5);
    }
  });

  return (
    <group ref={group}>
      <mesh ref={core}>
        <icosahedronGeometry args={[1, 5]} />
        <shaderMaterial
          vertexShader={AGENT_VERT}
          fragmentShader={AGENT_FRAG}
          uniforms={uniforms}
          transparent
        />
      </mesh>

      {/* Wireframe shell — reads as a containment field around the core. */}
      <lineSegments ref={shell} geometry={shellGeometry}>
        <lineBasicMaterial transparent opacity={0.2} depthWrite={false} />
      </lineSegments>

      {/* Soft additive halo. depthWrite off so it never occludes the core. */}
      <mesh ref={halo}>
        <sphereGeometry args={[1, 32, 32]} />
        <meshBasicMaterial
          transparent
          opacity={0.05}
          side={THREE.BackSide}
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </mesh>
    </group>
  );
}
