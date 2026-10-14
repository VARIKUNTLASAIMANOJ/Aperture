/**
 * GLSL for the agent core.
 *
 * Vertex stage displaces an icosahedron along its normal by fbm simplex noise,
 * then RECOMPUTES the normal by sampling two tangent-offset neighbours. Without
 * that recompute the lighting stays glued to the undisplaced sphere and the
 * morph reads as a texture slide rather than actual geometry moving.
 *
 * Noise: Ashima Arts / Stefan Gustavson simplex (public domain / MIT).
 */

export const AGENT_VERT = /* glsl */ `
uniform float uTime;
uniform float uAmp;
uniform float uFreq;
uniform float uFaceted;

varying vec3 vNormal;
varying vec3 vViewPos;
varying float vDisp;

vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }

float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);

  vec3 i  = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);

  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);

  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;

  i = mod289(i);
  vec4 p = permute(permute(permute(
             i.z + vec4(0.0, i1.z, i2.z, 1.0))
           + i.y + vec4(0.0, i1.y, i2.y, 1.0))
           + i.x + vec4(0.0, i1.x, i2.x, 1.0));

  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;

  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);

  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);

  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);

  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);

  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));

  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;

  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);

  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x;
  p1 *= norm.y;
  p2 *= norm.z;
  p3 *= norm.w;

  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}

// Two octaves is enough at this radius; a third is invisible and costs fill.
float fbm(vec3 p) {
  float n = snoise(p);
  n += 0.5 * snoise(p * 2.03 + 11.7);
  return n / 1.5;
}

// Any vector orthogonal to v, chosen to avoid the degenerate pole case.
vec3 orthogonal(vec3 v) {
  return normalize(
    abs(v.x) > abs(v.z) ? vec3(-v.y, v.x, 0.0) : vec3(0.0, -v.z, v.y)
  );
}

float fieldAt(vec3 pos) {
  float n = fbm(pos * uFreq + vec3(0.0, 0.0, uTime));
  // uFaceted quantises the field into shelves — molten at 0, crystalline at 1.
  float stepped = floor(n * 5.0) / 5.0;
  return mix(n, stepped, uFaceted);
}

vec3 displaced(vec3 pos, vec3 nrm) {
  return pos + nrm * fieldAt(pos) * uAmp;
}

void main() {
  vec3 nrm = normalize(normal);

  vec3 tangent = orthogonal(nrm);
  vec3 bitangent = normalize(cross(nrm, tangent));
  float eps = 0.035;

  vec3 d0 = displaced(position, nrm);
  vec3 d1 = displaced(position + tangent * eps, normalize(position + tangent * eps));
  vec3 d2 = displaced(position + bitangent * eps, normalize(position + bitangent * eps));

  vec3 newNormal = normalize(cross(d1 - d0, d2 - d0));
  // Cross-product order can invert per hemisphere; force outward.
  if (dot(newNormal, nrm) < 0.0) newNormal = -newNormal;

  vDisp = fieldAt(position);
  vNormal = normalize(normalMatrix * newNormal);

  vec4 mvPosition = modelViewMatrix * vec4(d0, 1.0);
  vViewPos = mvPosition.xyz;
  gl_Position = projectionMatrix * mvPosition;
}
`;

export const AGENT_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform vec3 uRim;
uniform float uOpacity;

varying vec3 vNormal;
varying vec3 vViewPos;
varying float vDisp;

void main() {
  vec3 N = normalize(vNormal);
  vec3 V = normalize(-vViewPos);

  // Two-light rig, view-space. Keeps the object readable from every angle
  // without loading an HDR environment map over the network.
  vec3 keyDir  = normalize(vec3(0.55, 0.75, 0.6));
  vec3 fillDir = normalize(vec3(-0.7, -0.25, 0.35));

  float key  = max(dot(N, keyDir), 0.0);
  float fill = max(dot(N, fillDir), 0.0) * 0.32;

  // Fresnel rim — the halo that sells depth against the dark ground.
  float fres = pow(1.0 - max(dot(N, V), 0.0), 2.4);

  // Crests of the displacement glow hotter than troughs.
  float crest = smoothstep(0.05, 0.75, vDisp);

  vec3 base = uColor * (0.16 + key * 0.9 + fill);
  vec3 col = base + uRim * fres * 1.35 + uRim * crest * 0.3;

  gl_FragColor = vec4(col, uOpacity);
  #include <colorspace_fragment>
}
`;
