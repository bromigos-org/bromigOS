#version 330 core
in vec2 v_d;
in vec2 v_px;
flat in vec4 v_c;
flat in float v_fog;
out vec4 o;
uniform vec4 u_fog;
void main() {
    float r = length(v_d);
    float k = exp(-r * r * 1.4) * 1.2 + exp(-r * 0.9) * 0.22;
    float f = 1.0;
    if (v_fog > 0.5 && u_fog.z > 0.5) f = exp(-max(v_px.y - u_fog.x, 0.0) / (u_fog.y * 3.5));
    o = vec4(v_c.rgb * k * v_c.a * f, 0.0);
}
