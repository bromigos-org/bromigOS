#version 330 core
in vec2 v_uv;
in vec4 v_col;
in vec2 v_px;
flat in vec4 v_clip;
uniform sampler2D u_atlas;
out vec4 o;
void main() {
    float a = texture(u_atlas, v_uv).a * v_col.a;
    if (v_clip.z > v_clip.x) {
        float d = min(min(v_px.x - v_clip.x, v_clip.z - v_px.x), min(v_px.y - v_clip.y, v_clip.w - v_px.y));
        a *= clamp(d / 10.0, 0.0, 1.0);
    }
    o = vec4(v_col.rgb * a, 0.0);
}
