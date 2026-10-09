#version 330 core
// The burn-in from the brand kit: rotating ring + still flame, with the
// intercept's staged reveal (dial ticks -> lines -> text band, flame from base
// to tip with the mast opening last) and the ghost afterimage.
in vec2 v_uv;
uniform sampler2D u_ring;
uniform sampler2D u_flame;
uniform float u_has_flame;
uniform float u_angle;       // ring rotation, radians (negative = counter-clockwise)
uniform float u_ring_t;      // 0..1 staged ring reveal (1 = whole)
uniform float u_flame_t;     // 0..1 burn from base to tip (1 = whole)
uniform float u_mast_t;      // 0..1 mast cut-out opening
uniform float u_alpha;
uniform float u_ring_gain;
uniform float u_mode;        // 0 = over (final), 1 = emissive (rgb only, for bloom)
out vec4 o;
const float TAU = 6.28318530718;
const vec3 NEEDLE = vec3(0.6, 1.0, 0.55);   // the needle crossing the dial (another theme: its [intercept] needle, else soft)

float stage(float t, float a, float b) { return clamp((t - a) / (b - a), 0.0, 1.0); }

void main() {
    vec2 p = v_uv * 2.0 - 1.0;                     // -1..1, y down
    float r = length(p);
    float ang = mod(atan(p.x, -p.y), TAU);         // clockwise from 12
    // ring texture, rotated
    float ca = cos(-u_angle), sa = sin(-u_angle);
    vec2 rp = vec2(ca * p.x - sa * p.y, sa * p.x + ca * p.y);
    vec4 ring = r < 1.0 ? texture(u_ring, rp * 0.5 + 0.5) : vec4(0.0);
    if (u_ring_t < 1.0) {
        // where the texel sits on the dial, in the ring's own frame
        float ra = mod(atan(rp.x, -rp.y), TAU);
        float gap = min(ra, TAU - ra) < 0.55 ? 1.0 : 0.0;   // tuning gap at 12 (about 60 deg)
        float band = (r > 0.81 && r < 0.975) ? 1.0 : 0.0;   // text band between the two lines
        float ticks = stage(u_ring_t, 0.0, 0.35), lines = stage(u_ring_t, 0.2, 0.7), text = stage(u_ring_t, 0.45, 1.0);
        float k = band * gap > 0.5 ? ticks : (band > 0.5 ? text : lines);
        float sweep = k * TAU;                              // the needle crossing the dial
        float vis = ang <= sweep ? 1.0 : 0.0;
        ring *= vis;
        // the needle itself
        float front = abs(ang - sweep) * r;
        if (k > 0.0 && k < 1.0 && r > 0.78 && r < 1.0) ring += vec4(NEEDLE, 1.0) * clamp(0.02 - front, 0.0, 0.02) * 40.0;
    }
    ring.rgb *= u_ring_gain;
    vec4 fl = vec4(0.0);
    if (u_has_flame > 0.5) {
        fl = texture(u_flame, v_uv);
        // burn from base (bottom of the flame, ~y 0.78) to tip (~y 0.22)
        float y = 1.0 - v_uv.y;
        float front = mix(0.18, 1.05, u_flame_t);
        float burn = smoothstep(front + 0.02, front - 0.02, y);
        // the halo is not burned in: it drains (u_ring_gain handles the glow)
        float flame_mask = step(r, 0.62);
        burn = mix(1.0, burn, flame_mask);
        // the mast (centre column of the flame) opens last
        float mast = step(abs(p.x), 0.13) * step(-0.18, p.y) * step(p.y, 0.56);
        fl *= 1.0 - mast * (1.0 - u_mast_t);
        fl *= burn;
        if (u_flame_t <= 0.0) fl = vec4(0.0);
    }
    vec4 c = fl + ring * (1.0 - fl.a);
    c *= u_alpha;
    if (u_mode > 0.5) o = vec4(c.rgb, 0.0);
    else o = c;
}
