#version 330 core
// The live background: wallpaper base plate + Drift-script glyph rain + floor
// throughput pulses + scanner sweep + the emissive gadget layer and its bloom.
// No scanlines, no vignette, no chromatic aberration: only line glow.
in vec2 v_uv;
out vec4 o;

uniform sampler2D u_under;
uniform sampler2D u_emit;
uniform sampler2D u_bloom;
uniform sampler2D u_schem;
uniform vec2 u_res;
uniform float u_time;
uniform float u_has_under;
uniform float u_under_bright;
uniform float u_glow;
uniform vec4 u_rain_rect;       // x y w h (px)
uniform vec4 u_rain;            // density, speed, brightness, on
uniform vec4 u_burst[6];        // x px, t0, strength, colour kind
uniform vec4 u_floor;           // horizon y, vanish x, lane slope, lane offset
uniform vec4 u_floor2;          // max x, draw grid, on, -
uniform vec4 u_net;             // rx level, tx level (0..1, smoothed), rx phase, tx phase (integrated speed, wraps at 4096)
uniform vec4 u_sweep;           // beam x px, active, direction, schematic on
uniform vec4 u_scan;            // -, -, held amount, pinned amount
uniform vec4 u_scan2;           // beam speed px/s, -, -, -
uniform vec4 u_schem_rect;      // where the schematic texture sits (px)
uniform float u_wipe;           // workspace wipe progress (<0 off)
uniform float u_dark;           // 1 = no wallpaper underlay (screensaver void)
// the den's own screens, made live
uniform vec4 u_den;             // on, emblem angle, static burst, -
uniform vec4 u_wave_rect;
uniform float u_wave[48];       // network envelope history, 0..1, newest last
uniform vec4 u_emb_rect;
uniform vec4 u_big_rect;
uniform vec4 u_meter0;
uniform vec4 u_meter1;
uniform vec2 u_meter_v;         // needle values 0..1
uniform vec3 u_meter_face;
uniform sampler2D u_ring;
uniform sampler2D u_flame;

#include rain
#include space
#include denloop

vec3 floor_pulses(vec2 px) {
    if (u_floor2.z < 0.5) return vec3(0.0);
    float dy = px.y - u_floor.x;
    if (dy < 2.0 || px.x > u_floor2.x + 40.0) return vec3(0.0);
    float xfade = smoothstep(u_floor2.x + 40.0, u_floor2.x - 60.0, px.x);
    float w = u_floor.z * dy;                    // lane spacing at this row
    float u = (px.x - u_floor.y) / w - u_floor.w;
    float k = floor(u + 0.5);
    float dpx = abs(u - k) * w;                  // px from the lane line
    float line = clamp(1.1 - dpx, 0.0, 1.0);
    float halo = exp(-dpx * dpx / 18.0);
    vec3 acc = vec3(0.0);
    float lw = log(dy);
    float lnear = log(540.0), lfar = log(3.0);
    // download: toward the viewer, phosphor; upload: toward the horizon, amber
    for (int dir = 0; dir < 2; dir++) {
        float lvl = dir == 0 ? u_net.x : u_net.y;
        float h = hash1(k * 3.17 + float(dir) * 41.0);
        float on = smoothstep(h - 0.06, h + 0.02, lvl);   // a lane fades in/out as traffic crosses its level
        if (on <= 0.0) continue;
        // lane speed: quarter steps 0.75..1.5 so the phase's wrap at 4096 stays seamless
        float lane_spd = 0.75 + 0.25 * floor(hash1(k * 5.3 + float(dir)) * 4.0);
        float s = fract((dir == 0 ? u_net.z : u_net.w) * lane_spd + hash1(k * 11.1 + float(dir) * 7.0));
        float wp = dir == 0 ? mix(lfar, lnear, s) : mix(lnear, lfar, s);
        float x = (lw - wp) * (dir == 0 ? -1.0 : 1.0);   // >0 = behind the pulse
        float tail = x > 0.0 ? exp(-x * 9.0) : exp(-x * x * 900.0);
        float p = tail * (line + halo * 0.45) * on;
        acc += (dir == 0 ? SOFT : AMBER) * p * 1.2;
    }
    if (u_floor2.y > 0.5) {                      // own grid when no wallpaper grid
        float rowf = fract(log(dy) * 6.0 - u_time * 0.05);
        float rl = clamp(1.0 - abs(rowf - 0.5) * 2.0 * 6.0 * (dy / 60.0), 0.0, 1.0);
        acc += DIM * (line * 0.35 + rl * 0.15) * smoothstep(0.0, 60.0, dy);
    }
    return acc * xfade;
}

float rbox(vec2 p, vec2 b, float r) {
    vec2 q = abs(p) - b + r;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

// The den's own shades of the Wick's green (another theme: retinted, glkit.theme_consts)
const vec3 GLASS = vec3(0.012, 0.05, 0.012);         // a den screen's dark glass
const vec3 GLASS_LIT = vec3(0.03, 0.13, 0.025);      // ... and its lit phosphor
const vec3 PLATE_PANEL = vec3(0.0, 0.035, 0.0);      // the deep panel under the gadgets
const vec3 METER_INK = vec3(0.04, 0.12, 0.04);       // a meter's scale
const vec3 METER_NEEDLE = vec3(0.02, 0.05, 0.02);    // ... and its needle

// CRT glass for a den screen: coverage (feathered) and a lit phosphor base.
float glass(vec2 px, vec4 rect, out vec2 uv, out vec3 base) {
    vec2 c = rect.xy + rect.zw * 0.5;
    float d = rbox(px - c, rect.zw * 0.5, min(rect.z, rect.w) * 0.12);
    uv = (px - rect.xy) / rect.zw;
    vec2 q = uv * 2.0 - 1.0;
    float v = clamp(1.0 - dot(q * q, vec2(0.45, 0.55)), 0.0, 1.0);
    base = GLASS + GLASS_LIT * v * v;
    base *= 0.9 + 0.1 * hash2(floor(px * 0.5) + floor(u_time * 20.0) * (1.0 - u_calm));   // calm: still grain
    return smoothstep(2.0, -4.0, d);
}

vec3 den(vec2 px, vec3 c) {
    vec2 uv; vec3 g;
    // waveform scope: the real network envelope on the den's oscilloscope
    float m = glass(px, u_wave_rect, uv, g);
    if (m > 0.0) {
        float f = uv.x * 47.0;
        int i = int(floor(f));
        float env = mix(u_wave[i], u_wave[min(i + 1, 47)], fract(f));
        float amp = (0.03 + env * 0.4) * u_wave_rect.w;
        float carrier = sin(px.x * 0.62 + u_time * 11.0) * 0.6 + sin(px.x * 1.73 - u_time * 17.0) * 0.4;
        float y = u_wave_rect.y + u_wave_rect.w * 0.5 + amp * carrier;
        float dy = px.y - y;
        float tr = exp(-dy * dy / 1.6) + exp(-dy * dy / 30.0) * 0.25;
        float mid = exp(-pow(px.y - (u_wave_rect.y + u_wave_rect.w * 0.5), 2.0) / 0.5) * 0.12;
        float grid = (1.0 - step(0.06, fract(uv.x * 8.0))) * 0.05 + (1.0 - step(0.08, fract(uv.y * 6.0))) * 0.05;
        vec3 sc = g + SOFT * tr * 0.95 + PHOS * (mid + grid);
        c = mix(c, sc, m);
    }
    // the burn-in on the den's monitor: ring turning against the clock
    m = glass(px, u_emb_rect, uv, g);
    if (m > 0.0) {
        float asp = u_emb_rect.z / u_emb_rect.w;
        vec2 p = (uv - 0.5) * vec2(asp, 1.0) / 0.86;
        float ca = cos(-u_den.y), sa = sin(-u_den.y);
        vec2 rp = vec2(ca * p.x - sa * p.y, sa * p.x + ca * p.y);
        vec4 ring = length(rp) < 0.5 ? texture(u_ring, rp + 0.5) : vec4(0.0);
        vec4 fl = (abs(p.x) < 0.5 && abs(p.y) < 0.5) ? texture(u_flame, p + 0.5) : vec4(0.0);
        vec4 e = fl + ring * (1.0 - fl.a);
        float flick = mix(0.9 + 0.1 * sin(u_time * 61.0) * hash1(floor(u_time * 9.0)), 0.95, u_calm);
        float nz = hash2(floor(px * vec2(0.7, 1.0)) + fract(u_time) * 97.0 * (1.0 - u_calm));
        vec3 sc = g * (1.0 - e.a) + e.rgb * 0.85 * flick;
        sc += PHOS * nz * (0.05 + u_den.z * 0.5);
        c = mix(c, sc, m);
    }
    // the big monitor gets a fresh glass; the relay map is drawn on it (emissive)
    m = glass(px, u_big_rect, uv, g);
    if (m > 0.0) c = mix(c, g * 0.8, m);
    // two analog meters: CPU and GPU load
    for (int k = 0; k < 2; k++) {
        vec4 r = k == 0 ? u_meter0 : u_meter1;
        float d = rbox(px - (r.xy + r.zw * 0.5), r.zw * 0.5, 3.0);
        float mm = smoothstep(1.0, -2.0, d);
        if (mm <= 0.0) continue;
        vec2 q = (px - r.xy) / r.zw;
        vec3 face = u_meter_face * (1.05 - q.y * 0.25);
        vec2 piv = vec2(r.x + r.z * 0.5, r.y + r.w * 1.25);
        vec2 dv = px - piv;
        float ang = atan(dv.x, -dv.y);
        float rad = length(dv);
        float R = r.w * 1.02;
        // scale arc + ticks
        float arc = exp(-pow(rad - R, 2.0) / 0.5) * step(abs(ang), 0.62);
        float tk = step(abs(fract(ang / 0.124 + 0.5) - 0.5), 0.09) * step(abs(rad - R + 2.5), 2.5) * step(abs(ang), 0.63);
        float red = step(0.37, ang) * (arc + tk);
        vec3 ink = METER_INK;
        face = mix(face, ink, clamp(arc + tk, 0.0, 1.0) * 0.85);
        face = mix(face, vec3(0.55, 0.18, 0.15), clamp(red, 0.0, 1.0) * 0.8);
        // needle
        float na = mix(-0.6, 0.6, (k == 0 ? u_meter_v.x : u_meter_v.y));
        vec2 nd = vec2(sin(na), -cos(na));
        float along = dot(dv, nd);
        float off = abs(dv.x * nd.y - dv.y * nd.x);
        float needle = clamp(1.0 - off, 0.0, 1.0) * step(0.0, along) * step(along, R + 3.0);
        face = mix(face, METER_NEEDLE, needle * 0.95);
        c = mix(c, face, mm);
    }
    return c;
}

void main() {
    vec2 px = vec2(v_uv.x * u_res.x, (1.0 - v_uv.y) * u_res.y);
    vec2 tuv = vec2(v_uv.x, 1.0 - v_uv.y);
    vec4 emit = texture(u_emit, v_uv);
    float plate = emit.a;
    vec3 base = VOID;
    float lum = 0.0;
    if (u_has_under > 0.5) {
        vec3 w = texture(u_under, tuv).rgb;
        lum = dot(w, vec3(0.3, 0.59, 0.11));
        base = w * u_under_bright;
    }
    // plates: deep panel green under the gadgets, for contrast
    base = mix(base, PLATE_PANEL, plate);
    float lum_mask = 1.0 - smoothstep(0.06, 0.16, lum);
    vec3 c = base;
    if (u_den.x > 0.5 && u_has_under > 0.5) c = den(px, c);
    c = den_loops(px, c);
    float sky = lum_mask * (1.0 - plate * 0.85) * step(px.y, u_space_rect.y + u_space_rect.w);
    vec3 drift = SOFT * stars(px) * 0.55 * u_space.x + traffic(px) + relay_beam(px);
    c += health_tint(drift * sky + rain(px, lum_mask) * (1.0 - plate * 0.85));
    c += floor_pulses(px);
    // scanner sweep: a quick phosphor beam; what it reveals persists (phosphor
    // afterglow: full for u_scan.x s, then fades over u_scan.y s) so the values
    // can be read. Pin (u_scan.w) / hold (u_scan.z) keep the schematic up.
    float dxs = (u_sweep.x - px.x) * u_sweep.z;           // >0 behind the beam
    if (u_sweep.y > 0.5) {
        float beam = exp(-dxs * dxs / 18.0) * 0.55 + exp(-dxs * dxs / 2400.0) * 0.08;
        float trail = dxs > 0.0 ? exp(-dxs / 520.0) : 0.0;
        c += SOFT * beam * smoothstep(30.0, 60.0, px.y);
        c += PHOS * 0.035 * trail * smoothstep(30.0, 60.0, px.y);
    }
    if (u_sweep.w > 0.5 && (u_sweep.y > 0.5 || u_scan.w > 0.0 || u_scan.z > 0.0)) {
        vec2 sp = (px - u_schem_rect.xy) / u_schem_rect.zw;
        if (sp.x >= 0.0 && sp.y >= 0.0 && sp.x <= 1.0 && sp.y <= 1.0) {
            vec4 s = texture(u_schem, sp);
            float vis = 0.0;
            if (u_sweep.y > 0.5) {
                float trail = dxs > 0.0 ? exp(-dxs / 520.0) : 0.0;   // the original short reveal (~0.5 s)
                vis = clamp(trail * 1.15 + exp(-dxs * dxs / 3000.0), 0.0, 1.0);
                vis = max(vis, u_scan.z * step(0.0, dxs));   // held: stays up behind the beam
            } else {
                vis = u_scan.z;                              // held after the beam left the screen
            }
            vis = clamp(max(vis, u_scan.w), 0.0, 1.0);
            c = mix(c, c * 0.35, s.a * vis * 0.65);         // x-ray: darken what's under the drawing (original, subtle)
            c += s.rgb * vis;
        }
    }
    if (u_wipe >= 0.0 && u_wipe <= 1.0) {
        float wy = mix(30.0, u_res.y, u_wipe);
        float d = wy - px.y;
        c += SOFT * (exp(-d * d / 6.0) * 0.5 + (d > 0.0 ? exp(-d / 90.0) * 0.06 : 0.0)) * (1.0 - u_wipe);
    }
    vec3 bloom = texture(u_bloom, v_uv).rgb;
    c += emit.rgb + bloom * u_glow;
    o = vec4(c, 1.0);
}
