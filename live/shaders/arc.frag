#version 330 core
in vec2 v_p;
in vec4 v_r;
in vec4 v_s;
in vec4 v_col;
in vec4 v_ex;
in vec2 v_half;
in vec2 v_px;
flat in vec4 v_clip;
#include common
out vec4 o;
const float TAU = 6.28318530718;
void main() {
    float cc = clip_cover(v_px, v_clip);
    if (cc <= 0.0) discard;
    int kind = int(v_ex.y + 0.5);
    if (kind == 3) {                      // plate: coverage into alpha only
        vec2 d = abs(v_p) - v_half;
        float a = clamp(0.5 - max(d.x, d.y), 0.0, 1.0) * v_col.a;
        o = vec4(0.0, 0.0, 0.0, a * cc);
        return;
    }
    float r = length(v_p);
    if (kind == 2) {                      // soft glow dot / halo
        float k = r / max(v_r.y, 1.0);
        float core = clamp(v_r.y * 0.45 + 0.5 - r, 0.0, 1.0);
        float a = (exp(-k * k * 2.2) * 0.55 + core) * v_col.a;
        o = vec4(v_col.rgb * a * cc, 0.0);
        return;
    }
    // angle clockwise from 12 o'clock, minus the ring's spin
    float ang = atan(v_p.x, -v_p.y) - (v_s.z * u_time + v_s.w);
    ang = mod(ang, TAU);
    float a0 = mod(v_r.z, TAU);
    float span = v_r.w - v_r.z;
    float rv = reveal(v_ex.x, 0.6);
    span *= rv;
    float rel = mod(ang - a0, TAU);
    float cov = clamp(r - v_r.x + 0.5, 0.0, 1.0) * clamp(v_r.y - r + 0.5, 0.0, 1.0);
    if (span < TAU - 1e-3) {
        float px_in = min(rel, span - rel) * r;      // px inside the arc ends
        if (rel > span) px_in = -min(rel - span, TAU - rel) * r;
        cov *= clamp(px_in + 0.5, 0.0, 1.0);
    }
    if (v_s.x > 0.5) {                     // segmented: gaps between cells
        float segw = TAU / v_s.x;
        float f = fract(ang / segw);
        float half_cell = (1.0 - v_s.y) * 0.5 * segw * r;
        float dpx = abs(f - 0.5) * segw * r;
        cov *= clamp(half_cell - dpx + 0.5, 0.0, 1.0);
    }
    if (v_ex.w > 0.0) cov *= mix(1.0, smoothstep(0.0, 1.0, rel / max(span, 1e-3)), v_ex.w);  // comet tail
    float a = cov * v_col.a;
    if (kind == 1) { o = vec4(0.0, 0.0, 0.0, a * cc); return; }   // disc plate
    o = vec4(v_col.rgb * a * cc, 0.0);
}
