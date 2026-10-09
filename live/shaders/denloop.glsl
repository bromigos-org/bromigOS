// Decorative, seamless loops over the clean plate (live/plate.py removed the
// baked versions, so nothing is doubled). DECORATION, not data: constant pace,
// tied to no metric. The data pulses on the floor (floor_pulses) stay on top.
//
// Every motion is a function of a loop phase in [0,1) computed on the CPU in
// double precision, so each loop closes exactly: at phase 1 every term equals
// its phase-0 value.
//
// Needs rain.glsl (palette, hash1, hash2) included first.

uniform vec4 u_loop;         // streak phase, grid phase, steam phase, streak period (s)
uniform vec4 u_sk[16];       // streaks: x0, y, x1, thickness (px)
uniform vec4 u_sk2[16];      // amp, seed, anchored-left (1/0), on
uniform float u_rows[18];    // floor rows y (px), nearest first (plate.ROWS, scaled)
uniform vec4 u_rowfx;        // on, rack x (fade), horizon y, amp
uniform vec4 u_steam;        // rim centre x, rim y, rim half width, on
uniform vec4 u_steam2;       // plume height (px), intensity, loop period (s), scale

const float TAU_ = 6.28318530718;
const vec3 STREAK = vec3(0.60, 1.0, 0.66);
const vec3 ROWC = vec3(0.084, 0.159, 0.105);
const vec3 STEAMC = vec3(0.78, 1.0, 0.74);

// ------------------------------------------------------------------ streaks
vec3 den_streaks(vec2 px) {
    vec3 acc = vec3(0.0);
    float th = u_loop.x * TAU_;
    float frames = floor(u_loop.w * 12.0 + 0.5);          // shimmer at 12 steps/s, integral per loop
    float fi = floor(u_loop.x * frames);
    for (int i = 0; i < 16; i++) {
        vec4 a = u_sk[i];
        vec4 b = u_sk2[i];
        if (b.w < 0.5) continue;
        float dy0 = px.y - a.y;
        if (abs(dy0) > 14.0) continue;
        float s = b.y;
        float n1 = 1.0 + floor(hash1(s * 3.1) * 2.0);
        float n2 = 1.0 + floor(hash1(s * 5.7) * 2.0);
        float n3 = 1.0 + floor(hash1(s * 7.9) * 3.0);
        float drift = (b.z > 0.5 ? 0.0 : 1.0) * (6.0 + 14.0 * hash1(s * 1.3)) * sin(th * n1 + s * 6.0);
        float len = (a.z - a.x) * (1.0 + 0.22 * sin(th * n2 + s * 2.3));
        float fade = 0.35 + 0.65 * pow(0.5 + 0.5 * sin(th * n3 + s * 4.1), 1.5);
        // glitch shimmer: on a few frames per loop the bar slips sideways and brightens
        float g = step(0.965, hash1(fi * 7.31 + s * 91.7));
        float slip = g * (hash1(fi + s) - 0.5) * 36.0;
        float vy = g * (hash1(fi * 2.1 + s) - 0.5) * 4.0;
        float x0 = a.x + drift + slip;
        float u = px.x - x0;
        if (u < 0.0 || u > len) continue;
        float dy = dy0 - vy;
        float t = max(a.w * 0.6, 0.6);                        // thinner than the baked bar
        float core = clamp(t + 0.5 - abs(dy), 0.0, 1.0);
        float halo = exp(-dy * dy / (t * t * 6.0 + 2.0)) * 0.22;
        float dashw = 3.0 + 7.0 * hash1(s * 11.0);
        float dash = step(0.32, hash1(floor(u / dashw) + s * 17.0));
        float tail = smoothstep(len, len * 0.55, u) * smoothstep(0.0, 6.0, u + (b.z > 0.5 ? 6.0 : 0.0));
        acc += STREAK * b.x * 0.6 * fade * (1.0 + 0.35 * g) * tail * (core * dash + halo);
    }
    return acc;
}

// ------------------------------------------------------------------ floor rows
vec3 den_rows(vec2 px) {
    if (u_rowfx.x < 0.5 || px.y <= u_rows[17] || px.x > u_rowfx.y + 8.0) return vec3(0.0);
    float s = -1.0, sp = 1.0;
    for (int i = 0; i < 17; i++) {
        if (px.y <= u_rows[i] && px.y > u_rows[i + 1]) {
            sp = u_rows[i] - u_rows[i + 1];
            s = float(i) + (u_rows[i] - px.y) / sp;
            break;
        }
    }
    if (s < 0.0) return vec3(0.0);
    // rows come toward the viewer: a row sits at s = k - phase; one cell per loop
    float ds = abs(fract(s + u_loop.y + 0.5) - 0.5);
    float dpx = ds * sp;
    float line = clamp(1.15 - dpx, 0.0, 1.0);
    float brk = 0.55 + 0.45 * hash1(floor(px.x / 23.0) * 1.7);
    brk *= mix(0.3, 1.0, step(0.16, hash1(floor(px.x / 61.0) * 3.3 + 0.5)));
    float hz = mix(0.55, 1.0, smoothstep(u_rowfx.z, u_rowfx.z + 80.0, px.y));
    float rack = smoothstep(u_rowfx.y + 8.0, u_rowfx.y - 14.0, px.x);
    return ROWC * u_rowfx.w * line * brk * hz * rack;
}

// ------------------------------------------------------------------ steam
float vnoise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n = i.x + i.y * 57.0 + i.z * 113.0;
    float a = mix(mix(hash1(n), hash1(n + 1.0), f.x), mix(hash1(n + 57.0), hash1(n + 58.0), f.x), f.y);
    float b = mix(mix(hash1(n + 113.0), hash1(n + 114.0), f.x), mix(hash1(n + 170.0), hash1(n + 171.0), f.x), f.y);
    return mix(a, b, f.z);
}

float fbm3(vec3 p) {
    return vnoise(p) * 0.55 + vnoise(p * 2.03 + 7.1) * 0.3 + vnoise(p * 4.1 + 3.3) * 0.15;
}

// one realisation of the plume at absolute time t (s)
float plume(vec2 q, float t) {
    vec2 p = q * vec2(2.4, 1.5) + vec2(0.0, 0.32 * t);            // rising
    vec2 w = vec2(fbm3(vec3(p * 1.15, 0.13 * t)), fbm3(vec3(p * 1.15 + 5.2, 0.13 * t + 3.0))) - 0.5;
    vec2 p2 = p + w * vec2(1.7, 0.8);                             // curl
    float n = fbm3(vec3(p2 * vec2(1.6, 1.0), 0.09 * t));
    float fil = 1.0 - abs(2.0 * n - 1.0);
    return pow(fil, 7.0);                                         // thin wisps
}

vec3 den_steam(vec2 px, out float a) {
    a = 0.0;
    if (u_steam.w < 0.5) return vec3(0.0);
    float H = u_steam2.x;
    vec2 d = px - u_steam.xy;
    if (d.y > 4.0 || d.y < -H || abs(d.x) > u_steam.z * 2.6) return vec3(0.0);
    vec2 q = d / u_steam2.w;                     // plume units (~100 px)
    float h = -q.y;                              // height above the rim
    float T = u_steam2.z;
    float ph = u_loop.z;
    float th = ph * TAU_;
    // seamless: two realisations one period apart, crossfaded across the loop
    float A = plume(q, ph * T);
    float B = plume(q, ph * T - T);
    float w = ph;
    float m = 0.12;
    float f = m + ((A - m) * (1.0 - w) + (B - m) * w) / sqrt((1.0 - w) * (1.0 - w) + w * w);
    // envelope: rises from the rim, widens, leans and sways, thins out
    float sway = (0.10 * sin(th + h * 2.2) + 0.05 * sin(2.0 * th + h * 4.0)) * h + 0.06 * h;
    float wid = (u_steam.z / u_steam2.w) * 0.55 + 0.34 * h;
    float ex = exp(-pow((q.x - sway) / wid, 2.0));
    float hmax = H / u_steam2.w;
    float ey = smoothstep(-0.02, 0.10, h) * exp(-h * 1.25) * (1.0 - smoothstep(hmax * 0.65, hmax, h));
    a = clamp(f * ex * ey * u_steam2.y, 0.0, 0.85);
    // a faint body of vapour under the wisps
    a += ex * u_steam2.y * (0.05 * ey * smoothstep(0.0, 0.5, h) + 0.16 * smoothstep(-0.02, 0.08, h) * exp(-h * 4.5));
    return STEAMC;
}

vec3 den_loops(vec2 px, vec3 c) {
    float sa;
    vec3 sc = den_steam(px, sa);
    c = c + sc * sa * (1.0 - c);
    c += den_rows(px);
    c += den_streaks(px);
    return c;
}
