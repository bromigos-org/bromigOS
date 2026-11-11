// The desktop hologram renderer's GLSL (vector holo/shaders.py), ported to three.js
// ShaderMaterials. All light is additive and premultiplied in linear HDR, then bloomed
// and tone-mapped in one composite pass. The fat-line geometry shader becomes an
// instanced quad per edge, expanded in screen space in the vertex shader.

export const MAXP = 24;

// ------------------------------------------------------------------ fat lines
// position.x: 0 at the edge's start, 1 at its end; position.y: -1 / +1 across it.
export const LINE_VS = /* glsl */ `
#define MAXP ${MAXP}
attribute vec3 aA;
attribute vec3 aB;
#ifdef FREE
attribute vec4 aColA;
attribute vec4 aColB;
#else
attribute float aPart;
uniform mat4 uPmat[MAXP];
uniform vec4 uPcol[MAXP];
uniform float uPw[MAXP];
#endif
uniform vec2 uPx;
uniform float uWidth;
#ifdef DEPTHFADE
uniform float uCenterDepth;  // view depth of the chart's centre
uniform float uFadeR;        // depth over which far things dim to 28%
#endif
varying vec4 vCol;
varying float vD;
varying float vLy;
varying float vHw;
void main() {
  bool atB = position.x > 0.5;
#ifdef FREE
  mat4 M = projectionMatrix * viewMatrix * modelMatrix;
  vCol = atB ? aColB : aColA;
  float pw = 1.0;
  vLy = -10.0;
#else
  int p = int(aPart + 0.5);
  mat4 M = projectionMatrix * viewMatrix * modelMatrix * uPmat[p];
  vCol = uPcol[p];
  float pw = uPw[p];
  vLy = atB ? aB.y : aA.y;
#endif
  vec4 a = M * vec4(aA, 1.0);
  vec4 b = M * vec4(aB, 1.0);
#ifdef DEPTHFADE
  float vz = -(viewMatrix * modelMatrix * vec4(atB ? aB : aA, 1.0)).z;
  vCol.a *= mix(1.0, 0.28, smoothstep(-1.0, 1.0, (vz - uCenterDepth) / uFadeR));
#endif
  if (a.w < 0.01 || b.w < 0.01 || vCol.a < 0.003) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    vD = 0.0; vHw = 0.0;
    return;
  }
  vec2 h = uPx * 0.5;
  vec2 sa = a.xy / a.w * h;
  vec2 sb = b.xy / b.w * h;
  vec2 d = sb - sa;
  float L = length(d);
  vec2 dir = L > 1e-4 ? d / L : vec2(1.0, 0.0);
  vec2 n = vec2(-dir.y, dir.x);
  float hw = uWidth * pw * 0.5 + 1.0;
  vec2 off = n * hw / h;
  vec2 ext = dir * 0.5 / h;
  vHw = hw - 1.0;
  vD = position.y * hw;
  vec4 c = atB ? b : a;
  vec2 ndc = (atB ? sb : sa) / h + (atB ? ext : -ext) + off * position.y;
  gl_Position = vec4(ndc * c.w, c.z, c.w);
}
`;

export const LINE_FS = /* glsl */ `
uniform vec4 uScan;   // x: local y of the scan plane, y: half-width, z: strength
uniform float uGain;  // overall brightness (the hidden-line pass uses less)
varying vec4 vCol;
varying float vD;
varying float vLy;
varying float vHw;
void main() {
  float cov = clamp(vHw + 0.5 - abs(vD), 0.0, 1.0);
  float core = exp(-abs(vD) / max(vHw, 0.5));
  float q = (vLy - uScan.x) / uScan.y;
  float s = uScan.z * exp(-q * q);
  float k = cov * vCol.a * uGain * (0.75 + 0.5 * core + 2.5 * s);
  gl_FragColor = vec4(vCol.rgb * k, k);
}
`;

// ------------------------------------------------------------------ the surface
export const FILL_VS = /* glsl */ `
#define MAXP ${MAXP}
attribute float aPart;
uniform mat4 uPmat[MAXP];
uniform vec4 uPcol[MAXP];
varying vec3 vW;
varying vec3 vN;
varying vec4 vCol;
varying float vLy;
void main() {
  int p = int(aPart + 0.5);
  vec4 w = modelMatrix * (uPmat[p] * vec4(position, 1.0));
  vW = w.xyz;
  vN = mat3(modelMatrix) * mat3(uPmat[p]) * normal;
  vCol = uPcol[p];
  vLy = position.y;
  gl_Position = projectionMatrix * viewMatrix * w;
}
`;

// depth + a faint fresnel shell, topographic slices, the scan band
export const FILL_FS = /* glsl */ `
uniform vec4 uScan;
uniform float uFill;    // shell strength
uniform float uSlices;  // topographic slices per unit height
varying vec3 vW;
varying vec3 vN;
varying vec4 vCol;
varying float vLy;
void main() {
  vec3 V = normalize(cameraPosition - vW);
  vec3 N = vN / max(length(vN), 1e-5);
  float fres = pow(clamp(1.0 - abs(dot(N, V)), 0.0, 1.0), 2.2);
  float q = (vLy - uScan.x) / uScan.y;
  float s = uScan.z * exp(-q * q);
  float x = vLy * uSlices;
  float f = fract(x);
  float w = max(fwidth(x), 1e-4);
  float slice = uSlices > 0.5 ? 1.0 - smoothstep(0.0, w * 1.3, min(f, 1.0 - f)) : 0.0;
  float k = vCol.a * (uFill * (0.035 + 0.5 * fres) + 0.05 * slice * uFill + 1.1 * s);
  gl_FragColor = vec4(vCol.rgb * k, k * 0.6);
}
`;

export const DEPTH_FS = /* glsl */ `
void main() { gl_FragColor = vec4(0.0); }
`;

// ------------------------------------------------------------------ the projection table
export const DISC_VS = /* glsl */ `
varying vec2 vXY;
void main() {
  vXY = position.xz;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const DISC_FS = /* glsl */ `
uniform vec3 uCol;
uniform float uTime;
uniform float uR;
uniform float uPower;
varying vec2 vXY;
const float PI = 3.14159265;
float ring(float r, float at, float w) { float q = (r - at) / w; return exp(-q * q); }
void main() {
  float r = length(vXY) / uR;
  if (r > 1.25) discard;
  float a = atan(vXY.y, vXY.x);
  float glow = exp(-r * r * 3.0) * 0.55;
  float rings = ring(r, 1.0, 0.012) * 1.4 + ring(r, 0.82, 0.008) * 0.8 + ring(r, 0.45, 0.01) * 0.5;
  float seg = step(0.5, fract((a + uTime * 0.21) * 12.0 / PI));
  float band = seg * smoothstep(0.88, 0.9, r) * (1.0 - smoothstep(0.95, 0.97, r)) * 0.55;
  float ticks = step(0.92, fract(a * 60.0 / PI)) * smoothstep(1.03, 1.04, r) * (1.0 - smoothstep(1.1, 1.11, r)) * 0.7;
  float sweep = pow(max(0.0, cos(a - uTime * 0.9)), 24.0) * smoothstep(1.0, 0.1, r) * 0.35;
  float k = (glow + rings + band + ticks + sweep) * uPower;
  gl_FragColor = vec4(uCol * k, k * 0.5);
}
`;

// position: x, z on the unit circle; y = 0 (base) or 1 (top)
export const CONE_VS = /* glsl */ `
uniform float uR0;
uniform float uR1;
uniform float uH;
varying float vT;
varying float vA;
void main() {
  float r = mix(uR0, uR1, position.y);
  vec3 p = vec3(position.x * r, position.y * uH, position.z * r);
  vT = position.y;
  vA = atan(position.z, position.x);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}
`;

export const CONE_FS = /* glsl */ `
uniform vec3 uCol;
uniform float uTime;
uniform float uPower;
varying float vT;
varying float vA;
void main() {
  float fall = pow(clamp(1.0 - vT, 0.0, 1.0), 1.7);
  float streak = pow(clamp(0.5 + 0.5 * sin(vA * 28.0 + uTime * 0.5), 0.0, 1.0), 6.0);
  float flick = 0.85 + 0.15 * sin(uTime * 7.0 + vA * 3.0);
  float k = fall * (0.035 + 0.11 * streak) * flick * uPower;
  gl_FragColor = vec4(uCol * k, k * 0.4);
}
`;

// ------------------------------------------------------------------ post: bloom + composite
export const POST_VS = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}
`;

export const DOWN_FS = /* glsl */ `
uniform sampler2D uTex;
uniform vec2 uTexel;
varying vec2 vUv;
void main() {
  vec4 c = texture2D(uTex, vUv + uTexel * vec2(-1.0, -1.0)) + texture2D(uTex, vUv + uTexel * vec2(1.0, -1.0))
         + texture2D(uTex, vUv + uTexel * vec2(-1.0, 1.0)) + texture2D(uTex, vUv + uTexel * vec2(1.0, 1.0));
  gl_FragColor = c * 0.25;
}
`;

export const BLUR_FS = /* glsl */ `
uniform sampler2D uTex;
uniform vec2 uDir;
varying vec2 vUv;
void main() {
  float w0 = 0.227027, w1 = 0.1945946, w2 = 0.1216216, w3 = 0.054054, w4 = 0.016216;
  vec4 c = texture2D(uTex, vUv) * w0;
  c += (texture2D(uTex, vUv + uDir * 1.6) + texture2D(uTex, vUv - uDir * 1.6)) * w1;
  c += (texture2D(uTex, vUv + uDir * 3.2) + texture2D(uTex, vUv - uDir * 3.2)) * w2;
  c += (texture2D(uTex, vUv + uDir * 4.8) + texture2D(uTex, vUv - uDir * 4.8)) * w3;
  c += (texture2D(uTex, vUv + uDir * 6.4) + texture2D(uTex, vUv - uDir * 6.4)) * w4;
  gl_FragColor = c;
}
`;

export const COMP_FS = /* glsl */ `
uniform sampler2D uScene;
uniform sampler2D uBloom;
uniform float uBloomK;
uniform float uFade;
uniform vec2 uEdge;   // feather at the element's edges (uv units): the glow fades out, never clips
varying vec2 vUv;
void main() {
  vec2 e = smoothstep(vec2(0.0), uEdge, vUv) * smoothstep(vec2(0.0), uEdge, 1.0 - vUv);
  float edge = e.x * e.y;
  vec3 c = texture2D(uScene, vUv).rgb * mix(0.35, 1.0, edge) + texture2D(uBloom, vUv).rgb * uBloomK * edge;
  c = max(c, vec3(0.0));
  if (any(isnan(c))) c = vec3(0.0);
  c = 1.0 - exp(-c * 1.15);   // soft shoulder, never clips to flat white
  c *= uFade;
  float lum = max(c.r, max(c.g, c.b));
  gl_FragColor = vec4(c, clamp(lum, 0.0, 1.0));
}
`;
