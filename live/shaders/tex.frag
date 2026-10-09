#version 330 core
// Blit a premultiplied texture (the shared holo renderer's output) over the deck.
in vec2 v_uv;
uniform sampler2D u_tex;
uniform float u_fade;
out vec4 o;
void main() {
    o = texture(u_tex, vec2(v_uv.x, 1.0 - v_uv.y)) * u_fade;
}
