"use client";

import { useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import * as THREE from "three";

interface ParticleFieldProps {
  /** 0–1, from the active AgentProfile. Drives drift speed and brightness. */
  energy: number;
  color: string;
  reducedMotion: boolean;
}

const COUNT = 900;

/**
 * Ambient dust orbiting the core. One draw call, no per-particle React state.
 * Positions are generated once and rotated as a whole — animating 900 vertices
 * individually on the CPU would be the "layout thrashing" of WebGL.
 */
export function ParticleField({ energy, color, reducedMotion }: ParticleFieldProps) {
  const points = useRef<THREE.Points>(null);
  const current = useRef({ energy });

  const { positions, scales } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3);
    const scales = new Float32Array(COUNT);
    for (let i = 0; i < COUNT; i++) {
      // Spherical shell with a biased radius — denser near the core.
      const r = 1.9 + Math.pow(Math.random(), 0.6) * 5.2;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = r * Math.cos(phi) * 0.62; // flattened — reads as a disc
      positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
      scales[i] = Math.random();
    }
    return { positions, scales };
  }, []);

  const geometry = useMemo(() => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geo.setAttribute("aScale", new THREE.BufferAttribute(scales, 1));
    return geo;
  }, [positions, scales]);

  const uniforms = useMemo(
    () => ({
      uColor: { value: new THREE.Color(color) },
      uOpacity: { value: 0.5 },
      uSize: { value: 2.4 },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const target = useMemo(() => new THREE.Color(), []);

  useFrame((state, rawDelta) => {
    const dt = Math.min(rawDelta, 1 / 20);
    current.current.energy = THREE.MathUtils.damp(
      current.current.energy, energy, 1.8, dt,
    );
    const e = current.current.energy;

    target.set(color);
    (uniforms.uColor.value as THREE.Color).lerp(target, 1 - Math.exp(-2 * dt));
    uniforms.uOpacity.value = 0.16 + e * 0.34;

    if (points.current && !reducedMotion) {
      points.current.rotation.y += dt * (0.02 + e * 0.12);
      points.current.rotation.x =
        Math.sin(state.clock.elapsedTime * 0.12) * 0.09;
    }
  });

  return (
    <points ref={points} geometry={geometry}>
      <shaderMaterial
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
        uniforms={uniforms}
        vertexShader={/* glsl */ `
          attribute float aScale;
          uniform float uSize;
          varying float vScale;
          void main() {
            vScale = aScale;
            vec4 mv = modelViewMatrix * vec4(position, 1.0);
            // Perspective-correct point size, clamped so near particles
            // don't blow out into squares.
            gl_PointSize = min(uSize * (0.4 + aScale) * (14.0 / -mv.z), 6.0);
            gl_Position = projectionMatrix * mv;
          }
        `}
        fragmentShader={/* glsl */ `
          uniform vec3 uColor;
          uniform float uOpacity;
          varying float vScale;
          void main() {
            // Round, soft-edged point. Discarding outside the disc avoids
            // the default square sprite.
            vec2 uv = gl_PointCoord - 0.5;
            float d = length(uv);
            if (d > 0.5) discard;
            float falloff = smoothstep(0.5, 0.0, d);
            gl_FragColor = vec4(uColor, falloff * uOpacity * (0.35 + vScale * 0.65));
          }
        `}
      />
    </points>
  );
}
