#version 330 core
// A screen-space quad: u_rect = x, y, w, h in px (origin top-left).
uniform vec2 u_res;
uniform vec4 u_rect;
out vec2 v_uv;
void main() {
    const vec2 c[6] = vec2[6](vec2(0,0), vec2(1,0), vec2(1,1), vec2(0,0), vec2(1,1), vec2(0,1));
    vec2 k = c[gl_VertexID];
    vec2 px = u_rect.xy + k * u_rect.zw;
    v_uv = k;
    gl_Position = vec4(px.x / u_res.x * 2.0 - 1.0, 1.0 - px.y / u_res.y * 2.0, 0.0, 1.0);
}
