// Shared by the world shaders (live/world.py): hashes, value noise, the clock's grade
// and the underwater fog. Coordinates are screen pixels, origin top-left.
// w_hwrap: the sine hashes only work on small numbers (see hwrap in rain.glsl). It folds
// the input back into +-1024, so a hash fed with the time keeps working after days of uptime.
float w_hwrap(float n) { return n - 1024.0 * trunc(n / 1024.0); }
vec2 w_hwrap(vec2 p) { return p - 1024.0 * trunc(p / 1024.0); }
float w_hash1(float n) { return fract(sin(w_hwrap(n) * 127.1) * 43758.5453); }
float w_hash2(vec2 p) { return fract(sin(dot(w_hwrap(p), vec2(127.1, 311.7))) * 43758.5453); }
vec2 w_hash22(vec2 p) {
    vec2 q = w_hwrap(p);
    return fract(sin(vec2(dot(q, vec2(127.1, 311.7)), dot(q, vec2(269.5, 183.3)))) * 43758.5453);   // w_hwrap(p) above
}
float w_noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(w_hash2(i), w_hash2(i + vec2(1, 0)), u.x), mix(w_hash2(i + vec2(0, 1)), w_hash2(i + vec2(1, 1)), u.x), u.y);
}
float w_fbm(vec2 p) {
    float a = 0.5, s = 0.0;
    for (int i = 0; i < 3; i++) { s += a * w_noise(p); p = p * 2.03 + 17.1; a *= 0.5; }
    return s;
}
