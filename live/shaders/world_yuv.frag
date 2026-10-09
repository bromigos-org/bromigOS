#version 330 core
// A video loop's NV12 frame to premultiplied RGBA (live/videoloop.py). Stacked alpha:
// the colour is the top half, its alpha the luma of the bottom half.
in vec2 v_uv;
out vec4 o;
uniform sampler2D u_y;
uniform sampler2D u_uv;
uniform float u_stacked;     // 1: colour on top, alpha below
uniform float u_bt709;       // 1: BT.709, 0: BT.601 (limited range)
uniform sampler2D u_mask;    // a feathered edge (<loop>-mask.png: a patch, or a piece cut from a loop), when u_has_mask
uniform float u_has_mask;
uniform float u_luma;        // 1: glow art on black (an additive actor): coverage is its brightness
void main() {
    vec2 uv = v_uv;          // the target's row 0 takes the frame's top, like every texture uploaded from an image
    vec2 cuv = u_stacked > 0.5 ? vec2(uv.x, uv.y * 0.5) : uv;
    float y = (texture(u_y, cuv).r - 16.0 / 255.0) * (255.0 / 219.0);
    vec2 c = (texture(u_uv, cuv).rg - 0.5) * (255.0 / 224.0);
    vec3 rgb = u_bt709 > 0.5
        ? vec3(y + 1.5748 * c.y, y - 0.1873 * c.x - 0.4681 * c.y, y + 1.8556 * c.x)
        : vec3(y + 1.402 * c.y, y - 0.344 * c.x - 0.714 * c.y, y + 1.772 * c.x);
    float a = 1.0;
    if (u_stacked > 0.5) a = clamp((texture(u_y, vec2(uv.x, 0.5 + uv.y * 0.5)).r - 16.0 / 255.0) * (255.0 / 219.0), 0.0, 1.0);
    if (u_has_mask > 0.5) a *= texture(u_mask, uv).r;
    rgb = clamp(rgb, 0.0, 1.0);
    if (u_luma > 0.5) {
        // the black around the creature is coverage 0, so nothing (fog, lift, the water's
        // tint) can light up its frame; a small floor drops the encoder's near-black noise
        float m = max(rgb.r, max(rgb.g, rgb.b));
        float k = smoothstep(0.025, 0.09, m) * a;   // a: the feathered mask, when it has one
        o = vec4(rgb * k, m * k);
        return;
    }
    o = vec4(rgb * a, a);
}
