#version 330 core
// One layer of a world: the art (premultiplied RGBA), shifted for parallax and graded
// by the clock. The sky layer also carries the real moon, the twilight glow and the
// lightning bolt; layers marked fog are fogged under a split world's surface.
in vec2 v_uv;
out vec4 o;
uniform sampler2D u_tex;
uniform vec2 u_res;
uniform vec4 u_view;      // uv offset x, y, zoom, -
uniform vec4 u_sway;      // amplitude (uv), phase, top y px (free end), bottom y px (rooted)
uniform vec4 u_grade;     // r, g, b multiplier, twilight 0..1
uniform float u_flash;    // lightning: added light
uniform vec3 u_lift;      // daylight: ambient light added to the night-painted art
uniform vec4 u_sky;       // is sky, horizon y px, twilight colour gain, -
uniform vec3 u_twi;       // twilight colour
uniform vec4 u_moon;      // x, y px, radius px (0 = none), phase 0..1
uniform vec4 u_moon2;     // brightness, -, -, -
uniform vec4 u_bolt;      // x px, bottom y px, amount, seed
uniform vec4 u_stars;     // brightness (0 = none), density 0..1, horizon y px, fade px
uniform float u_starcell; // px per star cell
uniform float u_time;
uniform float u_calm;          // 1: reduced motion (live/motion.py): the stars hold steady
uniform vec4 u_fog;       // surface y px, fog distance px, on, how much of it reaches this layer
uniform vec3 u_fogcol;
#include world_common

vec3 moon(vec2 px) {
    if (u_moon.z <= 0.0) return vec3(0.0);
    vec2 d = (px - u_moon.xy) / u_moon.z;
    float r = length(d);
    vec3 c = vec3(0.0);
    float k = cos(6.2831853 * u_moon.w);
    if (r < 1.0) {
        float w = sqrt(max(1.0 - d.y * d.y, 0.0));
        float lit = u_moon.w < 0.5 ? smoothstep(k * w - 0.04, k * w + 0.04, d.x)
                                   : smoothstep(-k * w + 0.04, -k * w - 0.04, d.x);
        float mare = 0.82 + 0.18 * w_noise(d * 3.0 + 7.0);
        float edge = smoothstep(1.0, 0.94, r);
        c = THEME_WHITE * mare * (lit * 0.95 + 0.03) * edge;
    }
    float illum = 0.5 * (1.0 - k);
    c += THEME_SOFT * exp(-max(r - 1.0, 0.0) * 1.6) * 0.18 * illum;
    return c * u_moon2.x;
}

// A faint twinkling starfield in the sky layer, so every layer in front (canopy, trees)
// masks it; it fades into the haze above the horizon.
vec3 stars(vec2 px) {
    if (u_stars.x <= 0.0) return vec3(0.0);
    float fade = smoothstep(u_stars.z, u_stars.z - u_stars.w, px.y);
    if (fade <= 0.0) return vec3(0.0);
    vec2 q = px / u_starcell;
    vec2 id = floor(q);
    vec3 acc = vec3(0.0);
    for (int j = 0; j <= 1; j++) for (int i = 0; i <= 1; i++) {
        vec2 c = id + vec2(i, j) - 0.5;
        float h = w_hash2(c + 3.1);
        if (h > u_stars.y) continue;
        vec2 p = (c + 0.5 + (w_hash22(c) - 0.5) * 0.8) * u_starcell;
        float d2 = dot(px - p, px - p);
        float tw = mix(0.55 + 0.45 * sin(u_time * (1.1 + 2.3 * w_hash1(h * 71.0)) + h * 40.0), 0.8, u_calm);
        float mag = 0.25 + 0.75 * pow(w_hash1(h * 13.0), 3.0);
        acc += THEME_WHITE * exp(-d2 / 1.1) * tw * mag;
    }
    return acc * u_stars.x * fade;
}

vec3 bolt(vec2 px) {
    if (u_bolt.z <= 0.0 || px.y > u_bolt.y) return vec3(0.0);
    float y = px.y;
    float x = u_bolt.x;
    float seg = floor(y / 38.0);
    float f = fract(y / 38.0);
    float a = (w_hash1(seg + u_bolt.w * 13.0) - 0.5) * 70.0;
    float b = (w_hash1(seg + 1.0 + u_bolt.w * 13.0) - 0.5) * 70.0;
    float drift = (w_hash1(floor(y / 230.0) + u_bolt.w) - 0.5) * 160.0 * (y / u_bolt.y);
    x += mix(a, b, f) + drift;
    float d = abs(px.x - x);
    return THEME_WHITE * (exp(-d * d / 2.5) + exp(-d / 40.0) * 0.18) * u_bolt.z;
}

void main() {
    vec2 tuv = vec2(v_uv.x, 1.0 - v_uv.y);
    vec2 px = tuv * u_res;
    vec2 uv = (tuv - 0.5) / u_view.z + 0.5 + u_view.xy;
    if (u_sway.x > 0.0) {                         // rooted at the bottom, swaying more toward the top
        float free = smoothstep(u_sway.w, u_sway.z, px.y);
        uv.x += u_sway.x * free * (sin(u_sway.y + px.x * 0.004 + px.y * 0.003) * 0.7 + sin(u_sway.y * 1.7 + px.x * 0.011) * 0.3);
    }
    vec4 s = texture(u_tex, uv);
    vec3 c = (s.rgb * u_grade.rgb + u_lift * s.a) * (1.0 + u_flash);
    float a = s.a;
    if (u_sky.x > 0.5) {
        float hz = exp(-abs(px.y - u_sky.y) / (u_res.y * 0.18));
        c += u_twi * u_grade.a * hz * u_sky.z * a;
        vec3 m = moon(px) + bolt(px) + stars(px);
        c += m * a;
    }
    if (u_fog.z > 0.5 && px.y > u_fog.x) {
        float f = 1.0 - exp(-(px.y - u_fog.x) / u_fog.y);
        c = mix(c, u_fogcol * a, f * u_fog.w);
    }
    o = vec4(c, a);
}
