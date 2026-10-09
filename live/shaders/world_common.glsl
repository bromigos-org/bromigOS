// Shared by the world shaders (live/world.py): hashes, value noise, the clock's grade
// and the underwater fog. Coordinates are screen pixels, origin top-left.
float w_hash1(float n) { return fract(sin(n * 127.1) * 43758.5453); }
float w_hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
vec2 w_hash22(vec2 p) {
    return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453);
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
