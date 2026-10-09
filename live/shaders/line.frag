#version 330 core
in vec4 v_col;
in float v_dist;
in float v_hw;
in float v_along;
in float v_dash;
in vec2 v_px;
flat in vec4 v_clip;
out vec4 o;
void main() {
    // Coverage of a line of width 2*hw (min 1px) against a 1px pixel footprint.
    float w = max(v_hw, 0.5);
    float a = clamp(w + 0.5 - abs(v_dist), 0.0, 1.0);
    if (v_hw < 0.5) a *= v_hw * 2.0;
    if (v_dash > 0.0) a *= step(0.45, fract(v_along / v_dash));
    a *= v_col.a;
    if (v_clip.z > v_clip.x) {
        float d = min(min(v_px.x - v_clip.x, v_clip.z - v_px.x), min(v_px.y - v_clip.y, v_clip.w - v_px.y));
        a *= clamp(d / 10.0, 0.0, 1.0);
    }
    o = vec4(v_col.rgb * a, 0.0);
}
