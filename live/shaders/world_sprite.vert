#version 330 core
// A world actor's sprite: one instance per actor (live/actors.py), anchored at its feet.
layout(location = 0) in vec4 a0;   // x, y px (bottom centre), w (signed: facing), h px
layout(location = 1) in vec4 a1;   // atlas u0, v0, u1, v1
layout(location = 2) in vec4 a2;   // rotation, alpha, cut y px (-1 none), mode (1 = reflection, 2 = flyby)
layout(location = 3) in vec4 a3;   // tint rgb, tint amount
layout(location = 4) in vec4 a4;   // reflection strength (a flyby: cloud cover), fog, brightness, emissive (1)
uniform vec2 u_res;
out vec2 v_uv;
out float v_y0;                    // the un-mirrored y px
out vec2 v_q;                      // 0..1 across the sprite
flat out vec4 v_a1, v_a2, v_a3, v_a4;
void main() {
    const vec2 C[6] = vec2[6](vec2(0, 0), vec2(1, 0), vec2(1, 1), vec2(0, 0), vec2(1, 1), vec2(0, 1));
    vec2 c = C[gl_VertexID];
    vec2 l = vec2((c.x - 0.5) * a0.z, (c.y - 1.0) * a0.w);
    float cr = cos(a2.x), sr = sin(a2.x);
    vec2 p = a0.xy + vec2(cr * l.x - sr * l.y, sr * l.x + cr * l.y);
    v_y0 = p.y;
    if (a2.w > 0.5 && a2.w < 1.5) p.y = 2.0 * a2.z - p.y;
    v_uv = mix(a1.xy, a1.zw, c);
    v_q = c;
    v_a1 = a1; v_a2 = a2; v_a3 = a3; v_a4 = a4;
    gl_Position = vec4(p.x / u_res.x * 2.0 - 1.0, 1.0 - p.y / u_res.y * 2.0, 0.0, 1.0);
}
