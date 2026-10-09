#version 330 core
in vec2 v_uv;
uniform sampler2D u_src;
uniform vec2 u_dir;          // texel step * direction
uniform float u_gain;
out vec4 o;
void main() {
    const float w[5] = float[5](0.227027, 0.1945946, 0.1216216, 0.054054, 0.016216);
    vec3 c = texture(u_src, v_uv).rgb * w[0];
    for (int i = 1; i < 5; i++) {
        c += texture(u_src, v_uv + u_dir * float(i) * 1.5).rgb * w[i];
        c += texture(u_src, v_uv - u_dir * float(i) * 1.5).rgb * w[i];
    }
    o = vec4(c * u_gain, 1.0);
}
