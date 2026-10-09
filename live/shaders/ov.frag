#version 330 core
// Overlay composite (premultiplied alpha): backdrop, an optional frozen frame
// of the screen with the intercept tear, optional rain + floor grid
// (screensaver), then the emissive gadgets with plates and bloom.
in vec2 v_uv;
out vec4 o;

uniform sampler2D u_emit;
uniform sampler2D u_bloom;
uniform sampler2D u_frozen;
uniform vec2 u_res;
uniform float u_time;
uniform float u_backdrop;       // void opacity over the desktop
uniform float u_frozen_amt;     // 0..1 the captured frame
uniform float u_tear;           // 0..1 scanline tearing + green bleed
uniform vec4 u_tear_band;       // y0, y1 px (band limit), on, -
uniform float u_glow;
uniform float u_fade;           // whole overlay
uniform vec4 u_rain_rect;
uniform vec4 u_rain;
uniform vec4 u_burst[6];
uniform vec4 u_grid;            // on, horizon y, vanish x, rx level
uniform vec4 u_edge;            // edge pulse: strength, colour kind, -, -
uniform vec4 u_vignette;        // centre x, y, radius, strength (radial dim for menus)
uniform float u_tear_style;     // the intercept's static: 0 scanline tears (the Wick), 1 ripple, 2 swell

// The tear's grade of the captured screen, written as the Wick's green: another theme's
// (its [intercept] static colour, else its primary) at the same brightness (glkit.theme_consts).
const vec3 TEAR = vec3(0.25, 1.25, 0.2);

#include rain
#include space

vec3 own_grid(vec2 px) {
    float dy = px.y - u_grid.y;
    if (dy < 1.0) return vec3(0.0);
    float w = 0.9 * dy;
    float u = (px.x - u_grid.z) / w;
    float dpx = abs(u - floor(u + 0.5)) * w;
    float lane = clamp(1.1 - dpx, 0.0, 1.0);
    float z = 140.0 / dy;
    float fz = fract(z * 2.0 - u_time * 0.35);
    float rowpx = min(fz, 1.0 - fz) * 0.5 * dy * dy / 140.0;
    float row = clamp(1.1 - rowpx, 0.0, 1.0);
    float fade = smoothstep(0.0, 120.0, dy);
    vec3 c = DIM * (lane * 0.55 + row * 0.45) * fade;
    // throughput pulses on a few lanes
    float k = floor(u + 0.5);
    float h = hash1(k * 3.17);
    if (h < u_grid.w) {
        float s = fract(u_time * (0.12 + 0.3 * u_grid.w) + hash1(k * 11.1));
        float lw = log(dy), wp = mix(log(3.0), log(u_res.y - u_grid.y), s);
        float x = wp - lw;
        float tail = x > 0.0 ? exp(-x * 9.0) : exp(-x * x * 900.0);
        c += SOFT * tail * (lane + exp(-dpx * dpx / 18.0) * 0.45);
    }
    // horizon glow
    c += PHOS * exp(-dy / 6.0) * 0.25;
    return c;
}

void main() {
    vec2 px = vec2(v_uv.x * u_res.x, (1.0 - v_uv.y) * u_res.y);
    vec4 emit = texture(u_emit, v_uv);
    float plate = emit.a;
    vec3 c = VOID * u_backdrop;
    float a = u_backdrop;
    if (u_vignette.w > 0.0) {
        float r = length(px - u_vignette.xy) / u_vignette.z;
        float k = u_vignette.w * smoothstep(1.25, 0.55, r);
        c = VOID * k; a = k;
    }
    if (u_frozen_amt > 0.0) {
        vec2 tuv = vec2(v_uv.x, 1.0 - v_uv.y);
        float crest = 0.0;
        if (u_tear > 0.0 && u_tear_style > 1.5) {
            // swell: the picture heaves on a rolling wave while broad, soft fronts of light
            // (the swell passing overhead) sweep down through it
            float ph = px.x * 0.006 - u_time * 3.2;
            tuv.y += sin(ph) * u_tear * 0.035 + sin(px.x * 0.017 + u_time * 1.7) * u_tear * 0.008;
            tuv.x += sin(px.y * 0.011 - u_time * 2.3) * u_tear * 0.012;
            for (int k = 0; k < 3; k++) {
                float fk = float(k);
                float wy = fract(u_time * 0.55 + fk / 3.0) * u_res.y * 1.3 - u_res.y * 0.15
                         + sin(px.x * 0.0035 + fk * 2.1 - u_time * 1.6) * u_res.y * 0.05;
                crest += exp(-pow((px.y - wy) / (u_res.y * 0.045), 2.0)) * 0.45;
            }
            crest *= u_tear;
        } else if (u_tear > 0.0 && u_tear_style > 0.5) {
            // ripple: rings spreading from the middle, as if something broke the surface
            vec2 cpx = px - u_res * 0.5;
            float d = length(cpx);
            float w = sin(d * 0.045 - u_time * 9.0);
            tuv += normalize(cpx + 1e-3) * vec2(1.0, -1.0) * w * u_tear * 0.014 * exp(-d / (u_res.y * 0.9));
            crest = pow(max(w, 0.0), 12.0) * u_tear * exp(-d / (u_res.y * 0.7));
        } else if (u_tear > 0.0) {
            float band = floor(px.y / (6.0 + 28.0 * hash1(floor(px.y / 37.0) + floor(u_time * 24.0))));
            float shift = (hash1(band * 1.7 + floor(u_time * 30.0)) - 0.5) * 2.0;
            shift *= step(0.45, hash1(band * 3.1 + floor(u_time * 18.0)));
            tuv.x += shift * u_tear * 0.06;
        }
        vec3 f = texture(u_frozen, tuv).rgb;
        if (u_tear > 0.0) {
            float l = dot(f, vec3(0.3, 0.59, 0.11));
            vec3 green = l * TEAR;
            f = mix(f, green, clamp(u_tear * 1.4, 0.0, 1.0));
            if (u_tear_style > 0.5) f += PHOS * 0.35 * crest;
            else f += PHOS * 0.08 * u_tear * step(0.97, hash1(floor(px.y / 2.0) + floor(u_time * 40.0)));
        }
        c = mix(c, f, u_frozen_amt);
        a = max(a, u_frozen_amt);
    }
    if (u_tear_band.z > 0.5 && px.y > u_tear_band.x && px.y < u_tear_band.y) {
        // a local interference band (notifications): bright slipped bars
        float row = floor(px.y / 3.0);
        float n = hash1(row + floor(u_time * 45.0));
        float bar = step(0.82, n) * u_tear;
        float edge = smoothstep(u_tear_band.x, u_tear_band.x + 30.0, px.y) * smoothstep(u_tear_band.y, u_tear_band.y - 30.0, px.y);
        vec3 bc = mix(SOFT, DANGER, step(0.5, hash1(row * 7.0))) * bar * edge * 0.55;
        c += bc; a = max(a, max(bc.r, max(bc.g, bc.b)));
    }
    vec3 add = vec3(0.0);
    float cover = 0.0;
    vec3 pl = planet(px, cover);
    vec3 far = SOFT * stars(px) * 0.6 * u_space.x + traffic(px);
    if (u_rain.w > 0.5) far += rain(px, 1.0) * 0.8;
    add += health_tint(far * (1.0 - cover) + relay_beam(px) * (1.0 - cover)) * (1.0 - plate * 0.9);
    c = mix(c, VOID * 0.6, cover * u_planet.w);
    add += pl * (1.0 - plate);
    if (u_grid.x > 0.5) add += own_grid(px) * (1.0 - plate);
    if (u_edge.x > 0.0) {
        float d = min(min(px.x, u_res.x - px.x), min(px.y, u_res.y - px.y));
        vec3 ec = u_edge.y < 0.5 ? SOFT : (u_edge.y < 1.5 ? AMBER : DANGER);
        add += ec * u_edge.x * (clamp(2.0 - d, 0.0, 1.0) + exp(-d / 14.0) * 0.35);
    }
    // plates: panel green under gadgets
    c = mix(c, vec3(0.0, 0.03, 0.0), plate);
    a = max(a, plate);
    add += emit.rgb + texture(u_bloom, v_uv).rgb * u_glow;
    c += add;
    a = max(a, clamp(max(add.r, max(add.g, add.b)), 0.0, 1.0));
    o = vec4(c, a) * u_fade;
}
