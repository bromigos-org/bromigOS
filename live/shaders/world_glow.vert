#version 330 core
// A light: eye-lamps, a lantern, running lights. Additive, never graded (emissive).
layout(location = 0) in vec4 a0;   // x, y, rx, ry px
layout(location = 1) in vec4 a1;   // r, g, b, intensity
layout(location = 2) in vec4 a2;   // fog, -, -, -
uniform vec2 u_res;
out vec2 v_d;
out vec2 v_px;
flat out vec4 v_c;
flat out float v_fog;
void main() {
    const vec2 C[6] = vec2[6](vec2(0, 0), vec2(1, 0), vec2(1, 1), vec2(0, 0), vec2(1, 1), vec2(0, 1));
    vec2 c = C[gl_VertexID] * 2.0 - 1.0;
    vec2 p = a0.xy + c * a0.zw * 6.0;
    v_d = c * 6.0;
    v_px = p;
    v_c = a1;
    v_fog = a2.x;
    gl_Position = vec4(p.x / u_res.x * 2.0 - 1.0, 1.0 - p.y / u_res.y * 2.0, 0.0, 1.0);
}
