#version 330 core
// A world's water and effects pass (live/world.py). Reads the scene behind the water
// (u_back: every layer and actor shallower than the water plane) and writes the frame
// up to the water: the water itself (a mirror with ripples, or a split view into the
// deep), then the effects the world declares, each compiled in only when used:
//   FX_RAIN       rain streaks and rings on the water (its signal: CPU in Mire)
//   FX_MIST       low mist over the water
//   FX_LINE       a fishing line from a rod tip, slack or taut (paper fills in Mire)
//   FX_BEAM       a lighthouse beam turning (lab health in Tidewell)
//   FX_SPRAY      spray bursts (a breach, a catch)
//   FX_RAYS       light shafts down from the surface (split worlds): the moon's or the day's
//                 light, moved by the swell, flickering with the storm's lightning
//   WATER_SPLIT   the surface as a moving line with the deep below (Tidewell)
// Layers and actors in front of the water are drawn after this pass.
in vec2 v_uv;
out vec4 o;
uniform sampler2D u_back;
uniform sampler2D u_water;
uniform vec2 u_res;
uniform float u_time;
uniform float u_scale;          // screen px per plate px
uniform vec4 u_wview;           // the water layer's uv offset x, y, zoom
uniform vec4 u_line;            // surface y px, -, reflectivity, base ripple
uniform vec4 u_grade;
uniform float u_flash;
uniform vec3 u_lift;
uniform vec4 u_swell;           // amplitude px, wavelength px, phase, crest light
uniform vec4 u_rain;            // rain 0..1, -, -, -
uniform vec4 u_mist;            // strength 0..1, band y0, band y1, drift phase
uniform vec3 u_mistcol;
uniform vec4 u_wake[12];        // x, y px, strength, -
uniform vec4 u_spray[6];        // x, y px, t0, strength
uniform vec4 u_ring[8];         // ripple rings: x, y px, t0, strength (a Sleeper rising, going under)
uniform vec4 u_bubble[8];       // bubbles: x, y px, t0, strength
uniform vec4 u_fline;           // tip x, y, end x, y px
uniform vec4 u_fline2;          // sag px, on, -, -
uniform vec3 u_flinecol;
uniform vec4 u_beam;            // lamp x, y px, angle, on
uniform vec4 u_beam2;           // reach px, -, -, -
uniform vec3 u_beamcol;
uniform vec4 u_caus;            // caustics gain, -, -, -
uniform vec4 u_rays;            // gain, slant (px across per px down), reach px, x they gather under (-1 everywhere)
uniform vec3 u_rayscol;
#include world_common

float surface(float x) {
#ifdef WATER_SPLIT
    float k = 6.2831853 / max(u_swell.y, 1.0);
    return u_line.x + u_swell.x * (0.6 * sin(x * k + u_swell.z) + 0.3 * sin(x * k * 2.3 - u_swell.z * 1.7 + 1.3)
                                    + 0.1 * sin(x * k * 5.1 + u_swell.z * 2.9));
#else
    return u_line.x;
#endif
}

// ripples on a mirror: a slow shimmer, rain rings, the wakes of wading things
vec2 ripples(vec2 px, float depth) {
    float persp = clamp(depth / (u_res.y * 0.35), 0.08, 1.0);
    vec2 n = vec2(sin(px.x * 0.031 / persp + u_time * 0.9 + sin(px.y * 0.25 / persp)),
                  sin(px.y * 0.6 / persp - u_time * 1.7)) * u_line.w * persp;
#ifdef FX_RAIN
    if (u_rain.x > 0.01) {
        vec2 q = vec2(px.x, px.y * 3.2) / (70.0 * u_scale * (0.4 + persp));
        vec2 id = floor(q);
        for (int j = -1; j <= 1; j++) for (int i = -1; i <= 1; i++) {
            vec2 c = id + vec2(i, j);
            float h = w_hash2(c);
            if (h > u_rain.x * 0.9) continue;
            vec2 ctr = c + w_hash22(c);
            float ph = fract(u_time * (0.7 + h) + h * 9.0);
            vec2 dv = q - ctr;
            float d = length(dv);
            float ring = exp(-pow((d - ph * 0.6) * 18.0, 2.0)) * (1.0 - ph);
            n += normalize(dv + 1e-4) * ring * 2.2;
        }
    }
#endif
    for (int k = 0; k < 8; k++) {                 // event rings: they spread and settle over 4 s
        float age = u_time - u_ring[k].z;
        if (u_ring[k].w <= 0.0 || age < 0.0 || age > 4.0) continue;
        vec2 dv = (px - u_ring[k].xy) * vec2(1.0, 3.2);
        float d = length(dv) / u_scale;
        float r0 = age * 70.0;
        float ring = exp(-pow(d - r0, 2.0) / 60.0) + 0.6 * exp(-pow(d - r0 * 0.6, 2.0) / 40.0);
        n += normalize(dv + 1e-4) * ring * u_ring[k].w * 3.5 * (1.0 - age / 4.0);
    }
    for (int k = 0; k < 12; k++) {
        if (u_wake[k].z <= 0.0) continue;
        vec2 dv = (px - u_wake[k].xy) * vec2(1.0, 3.0);
        float d = length(dv);
        if (d > 260.0 * u_scale) continue;
        float r = sin(d * 0.22 / u_scale - u_time * 3.4) * exp(-d / (90.0 * u_scale));
        n += normalize(dv + 1e-4) * r * u_wake[k].z * 1.6;
    }
    return n;
}

vec3 water(vec2 px, vec3 c) {
#ifdef WATER_SPLIT
    float surf = surface(px.x);
    float depth = px.y - surf;
    // the moving surface: a bright meniscus, a crest light that grows with the swell
    float men = exp(-depth * depth / (2.5 * u_scale * u_scale));
    if (depth > 0.0) {
        vec2 wob = vec2(sin(px.y * 0.05 + u_time * 1.1 + u_swell.z), 0.0) * (2.0 + u_swell.x * 0.15) * u_scale;
        vec3 under = texture(u_back, (px + wob) / u_res * vec2(1.0, -1.0) + vec2(0.0, 1.0)).rgb;
        // the painted water moves with the surface only near it; the deep stays put
        vec2 wuv = (vec2(px.x, px.y - (surf - u_line.x) * exp(-depth / (50.0 * u_scale))) / u_res - 0.5) / u_wview.z + 0.5 + u_wview.xy;
        vec4 wt = texture(u_water, wuv);
        vec3 deep = wt.rgb * u_grade.rgb;
        c = mix(under, deep / max(wt.a, 1e-3), wt.a);
        float ca = pow(abs(sin(px.x * 0.021 / u_scale + sin(px.y * 0.033 / u_scale + u_time * 0.7) * 2.0 + u_swell.z * 0.8)
                         * sin(px.y * 0.027 / u_scale - u_time * 0.6 + sin(px.x * 0.013 / u_scale) * 2.0)), 7.0);
        c += THEME_CYAN * ca * exp(-depth / (170.0 * u_scale)) * u_caus.x * u_grade.rgb;
#ifdef FX_RAYS
        float lx = (px.x + depth * u_rays.y) / u_scale;
        float sh = w_noise(vec2(lx * 0.006, u_swell.z * 0.04)) * 0.65 + w_noise(vec2(lx * 0.017, u_swell.z * 0.07 + 3.0)) * 0.35;
        sh = pow(clamp(sh * 1.35 - 0.3, 0.0, 1.0), 2.5);
        float gather = u_rays.w < 0.0 ? 1.0 : exp(-pow((px.x - depth * u_rays.y - u_rays.w) / (700.0 * u_scale), 2.0)) * 1.8;
        c += u_rayscol * sh * exp(-depth / max(u_rays.z, 1.0)) * u_rays.x * gather * (1.0 + u_flash * 7.0);
#endif
    } else {
        // the sea surface just above the line catches the swell's crests
        float above = -depth;
        c += THEME_SOFT * exp(-above / (6.0 * u_scale)) * u_swell.w * 0.25 * u_grade.rgb;
    }
    c += THEME_SOFT * men * 0.45 * u_grade.rgb;
    return c;
#else
    vec2 wuv = (px / u_res - 0.5) / u_wview.z + 0.5 + u_wview.xy;
    vec4 wt = texture(u_water, wuv);
    if (wt.a < 0.002) return c;
    float depth = px.y - u_line.x;
    vec2 n = ripples(px, max(depth, 1.0));
    vec2 rp = vec2(px.x + n.x * 3.0 * u_scale, 2.0 * u_line.x - px.y + n.y * 5.0 * u_scale);
    vec3 refl = texture(u_back, rp / u_res * vec2(1.0, -1.0) + vec2(0.0, 1.0)).rgb;
    float fres = mix(1.0, 0.55, clamp(depth / (u_res.y * 0.4), 0.0, 1.0));
    vec3 tint = wt.rgb / max(wt.a, 1e-3) * u_grade.rgb;
    vec3 w = tint + refl * u_line.z * fres;
    w += THEME_DIM * max(n.y, 0.0) * 0.015 * u_grade.rgb;      // glints where the rings tilt
    return mix(c, w, wt.a);
#endif
}

#ifdef FX_RAIN
vec3 rain(vec2 px) {
    if (u_rain.x <= 0.01) return vec3(0.0);
    vec3 acc = vec3(0.0);
    for (int L = 0; L < 2; L++) {
        float sc = (L == 0 ? 1.0 : 0.6) * u_scale;
        vec2 cell = vec2(14.0, 120.0) * sc;
        vec2 q = vec2(px.x + px.y * 0.08, px.y) / cell + vec2(0.0, -u_time * (L == 0 ? 7.5 : 5.0));
        vec2 id = floor(q);
        float h = w_hash2(id + float(L) * 31.0);
        if (h > u_rain.x * (L == 0 ? 0.55 : 0.8)) continue;
        vec2 f = fract(q);
        float x = w_hash1(h * 91.0);
        float d = abs(f.x - x) * cell.x;
        float len = 0.35 + 0.3 * w_hash1(h * 17.0);
        float y = f.y - w_hash1(h * 53.0) * (1.0 - len);
        float on = step(0.0, y) * step(y, len);
        acc += THEME_SOFT * exp(-d * d / (0.5 * sc)) * on * (L == 0 ? 0.16 : 0.09);
    }
    return acc * u_grade.rgb * 1.6;
}
#endif

#ifdef FX_MIST
vec3 mist(vec2 px, vec3 c) {
    if (u_mist.x <= 0.0 || px.y < u_mist.y || px.y > u_mist.z + 120.0 * u_scale) return c;
    float mid = mix(u_mist.y, u_mist.z, 0.6);
    float prof = smoothstep(u_mist.y, mid, px.y) * (1.0 - smoothstep(mid, u_mist.z + 120.0 * u_scale, px.y));
    vec2 q = vec2(px.x * 0.0028, px.y * 0.009) / u_scale + vec2(u_mist.w, 0.0);
    float m = w_fbm(q) * 1.3 - 0.25;
    float a = clamp(m, 0.0, 1.0) * prof * u_mist.x;
    return mix(c, u_mistcol * u_grade.rgb, a * 0.75);
}
#endif

#ifdef FX_LINE
vec3 fishing_line(vec2 px) {
    if (u_fline2.y < 0.5) return vec3(0.0);
    vec2 a = u_fline.xy, b = u_fline.zw;
    vec2 m = (a + b) * 0.5 + vec2(0.0, u_fline2.x);
    float best = 1e9;
    vec2 prev = a;
    for (int i = 1; i <= 8; i++) {
        float t = float(i) / 8.0;
        vec2 p = mix(mix(a, m, t), mix(m, b, t), t);
        vec2 pa = px - prev, ba = p - prev;
        float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0);
        best = min(best, length(pa - ba * h));
        prev = p;
    }
    return u_flinecol * u_grade.rgb * exp(-best * best / (0.45 * u_scale)) * 0.55;
}
#endif

#ifdef FX_BEAM
vec3 beam(vec2 px) {
    if (u_beam.w < 0.5) return vec3(0.0);
    float s = sin(u_beam.z), co = cos(u_beam.z);
    vec2 dir = normalize(vec2(s, 0.035 + 0.02 * co));
    vec2 v = px - u_beam.xy;
    float along = dot(v, dir);
    float reach = u_beam2.x * abs(s) + 1.0;
    vec3 acc = vec3(0.0);
    if (along > 0.0 && along < reach) {
        float perp = abs(v.x * dir.y - v.y * dir.x);
        float width = (5.0 + along * 0.075) * u_scale;
        float fall = pow(1.0 - along / reach, 1.5);
        acc += u_beamcol * exp(-perp * perp / (width * width)) * fall * (0.22 + 0.25 * abs(s));
    }
    float r = length(v) / u_scale;
    float face = pow(max(co, 0.0), 10.0);
    acc += u_beamcol * (exp(-r * r / 60.0) * 1.2 + exp(-r / 45.0) * 0.35 * (0.4 + face * 2.5));
    return acc;
}
#endif

#ifdef FX_SPRAY
vec3 spray(vec2 px) {
    vec3 acc = vec3(0.0);
    for (int k = 0; k < 6; k++) {
        float age = u_time - u_spray[k].z;
        if (u_spray[k].w <= 0.0 || age < 0.0 || age > 1.8) continue;
        vec2 o0 = u_spray[k].xy;
        if (length(px - o0) > 520.0 * u_scale) continue;
        for (int i = 0; i < 22; i++) {
            float h1 = w_hash1(float(i) * 3.7 + float(k) * 17.0 + floor(u_spray[k].z));
            float h2 = w_hash1(float(i) * 9.1 + float(k) * 5.0 + floor(u_spray[k].z));
            float ang = -1.5708 + (h1 - 0.5) * 1.9;
            float sp = (140.0 + 300.0 * h2) * u_spray[k].w * u_scale;
            vec2 p = o0 + vec2(cos(ang), sin(ang)) * sp * age + vec2(0.0, 520.0 * u_scale) * age * age;
            float d = length(px - p) / u_scale;
            acc += THEME_WHITE * exp(-d * d / (2.0 + 2.0 * h1)) * (1.0 - age / 1.8);
        }
        float ring = abs(length((px - o0) * vec2(1.0, 4.0)) / u_scale - age * 160.0);
        acc += THEME_SOFT * exp(-ring * ring / 30.0) * (1.0 - age / 1.8) * 0.4 * u_spray[k].w;
    }
    return acc * u_grade.rgb;
}
#endif

vec3 bubbles(vec2 px) {
    vec3 acc = vec3(0.0);
    for (int k = 0; k < 8; k++) {
        float age = u_time - u_bubble[k].z;
        if (u_bubble[k].w <= 0.0 || age < 0.0 || age > 2.5) continue;
        vec2 o0 = u_bubble[k].xy;
#ifdef WATER_SPLIT
        if (o0.y > u_line.x + 20.0 * u_scale) {
            // under the surface (Tidewell): a column of small bubbles rising and wobbling from
            // the creature, round, a bright rim and a highlight, shrinking toward nothing
            if (abs(px.x - o0.x) > 90.0 * u_scale || px.y > o0.y + 20.0 * u_scale || px.y < o0.y - 420.0 * u_scale) continue;
            for (int i = 0; i < 14; i++) {
                float h1 = w_hash1(float(i) * 3.1 + float(k) * 7.0 + floor(u_bubble[k].z * 10.0));
                float h2 = w_hash1(float(i) * 7.7 + float(k) * 3.0 + floor(u_bubble[k].z * 10.0));
                float a = age - h1 * 1.2;                               // when this bubble leaves
                if (a < 0.0 || a > 1.3) continue;
                float rise = (90.0 + 120.0 * h2) * a + 40.0 * a * a;
                vec2 p = o0 + vec2((h2 - 0.5) * 50.0 + sin(a * 7.0 + h1 * 6.3) * 5.0, -rise) * u_scale;
                float r = (1.4 + 2.6 * h2) * u_scale;
                vec2 q = px - p;
                float d = length(q);
                if (d > r + 2.0 * u_scale) continue;
                float rim = exp(-pow((d - r) / (0.7 * u_scale), 2.0));
                float hi = exp(-dot(q - vec2(-0.35, -0.35) * r, q - vec2(-0.35, -0.35) * r) / (0.18 * r * r + 0.3));
                float life = smoothstep(0.0, 0.12, a) * (1.0 - smoothstep(0.9, 1.3, a));
                acc += THEME_SOFT * (rim * 0.55 + hi * 0.8 + 0.06) * life * u_bubble[k].w;
            }
            continue;
        }
#endif
        if (length((px - o0) * vec2(1.0, 3.0)) > 160.0 * u_scale) continue;
        for (int i = 0; i < 14; i++) {
            float h1 = w_hash1(float(i) * 3.1 + float(k) * 7.0 + floor(u_bubble[k].z * 10.0));
            float h2 = w_hash1(float(i) * 7.7 + float(k) * 3.0 + floor(u_bubble[k].z * 10.0));
            float tb = h1 * 2.0;                                    // when this bubble surfaces
            float a = age - tb;
            if (a < 0.0 || a > 0.45) continue;
            vec2 p = o0 + vec2((h2 - 0.5) * 120.0, (h1 - 0.5) * 22.0) * u_scale;
            float r = (2.0 + 3.0 * h2) * u_scale * (1.0 + a * 2.0);
            float d = abs(length((px - p) * vec2(1.0, 2.2)) - r);
            acc += THEME_SOFT * exp(-d * d / (0.6 * u_scale)) * (1.0 - a / 0.45) * u_bubble[k].w;
        }
    }
    return acc * u_grade.rgb;
}

void main() {
    vec2 tuv = vec2(v_uv.x, 1.0 - v_uv.y);
    vec2 px = tuv * u_res;
    vec3 c = texture(u_back, v_uv).rgb;
    c = water(px, c);
#ifdef FX_MIST
    c = mist(px, c);
#endif
#ifdef FX_LINE
    c += fishing_line(px);
#endif
#ifdef FX_BEAM
    if (px.y < surface(px.x)) c += beam(px);
#endif
#ifdef FX_SPRAY
    c += spray(px);
#endif
    c += bubbles(px);
#ifdef FX_RAIN
#ifdef WATER_SPLIT
    if (px.y < surface(px.x)) c += rain(px);              // the storm plays out on the surface
#else
    c += rain(px);
#endif
#endif
    c += THEME_WHITE * u_flash * 0.12;
    o = vec4(c, 1.0);
}
