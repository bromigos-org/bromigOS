#version 330 core
// The faint surface shell: the hull's triangles, instanced per ship.
layout(location = 0) in vec3 a_p;
layout(location = 1) in float a_part;
#include common
#include ship
out vec4 v_col;
out vec2 v_px;
flat out vec4 v_clip;
void main() {
    int i = gl_InstanceID;
    vec3 s = project(ship_world(a_p, i), 2.0);
    gl_Position = to_clip(s.xy);
    v_px = s.xy;
    v_clip = clip_of(2.0);
    vec4 c = ship_colour(int(a_part + 0.5), i);
    v_col = vec4(c.rgb, 0.07 * u_sl[i].x * u_so[i].w * depth_fade(s.z, 2.0) * u_fade);
}
