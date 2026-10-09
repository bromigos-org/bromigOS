// Shared by bg.frag and ov.frag: palette, hashes, the Drift-script glyph set
// and the rain field. Needs u_time, u_rain_rect, u_rain, u_burst.
// u_calm (1 under reduced motion, live/motion.py): the glyphs stop changing as they fall.
uniform float u_calm;        // 1: reduced motion: no flicker, twinkle or blinking (bg.frag, ov.frag)
const vec3 VOID = vec3(0.0, 0.0196, 0.0);
const vec3 PHOS = vec3(0.2235, 1.0, 0.0784);
const vec3 SOFT = vec3(0.612, 1.0, 0.541);
const vec3 DIM = vec3(0.0824, 0.608, 0.0353);
const vec3 AMBER = vec3(0.831, 0.686, 0.216);
const vec3 DANGER = vec3(1.0, 0.463, 0.435);

float hash1(float n) { return fract(sin(n * 127.1) * 43758.5453); }
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

// ---- Drift script: an original glyph set built from relay-mast strokes.
// 24 glyphs x 4 segments (x0,y0,x1,y1) in a 0..1 box; (-1) = unused.
const vec4 N = vec4(-1.0);
const vec4 G[96] = vec4[96](
    vec4(.5,0,.5,1), vec4(0,0,1,0), N, N,
    vec4(.5,0,.5,1), vec4(.2,.3,.8,.3), vec4(0,.62,1,.62), N,
    vec4(0,0,0,1), vec4(0,.5,1,0), N, N,
    vec4(1,0,1,1), vec4(0,1,1,1), vec4(.4,.5,1,.5), N,
    vec4(.5,.4,.5,1), vec4(0,.4,.5,0), vec4(.5,0,1,.4), N,
    vec4(0,0,0,1), vec4(0,0,1,0), vec4(0,.5,.6,.5), N,
    vec4(.15,0,.15,1), vec4(.85,.25,.85,1), vec4(.15,.25,.85,.25), N,
    vec4(.2,1,.8,0), vec4(0,.5,1,.5), N, N,
    vec4(.5,0,.5,1), vec4(.3,.2,.7,.2), vec4(.15,.5,.85,.5), vec4(0,.8,1,.8),
    vec4(.5,0,.5,.75), vec4(.5,.75,0,1), vec4(.6,.3,1,.3), N,
    vec4(0,0,1,0), vec4(1,0,1,.6), vec4(0,.6,1,.6), vec4(.5,.6,.5,1),
    vec4(1,0,1,1), vec4(0,.2,1,.5), vec4(0,.8,1,.5), N,
    vec4(0,0,0,1), vec4(.5,.15,1,.15), vec4(0,.75,1,.75), N,
    vec4(.5,.22,.5,1), vec4(0,1,1,1), vec4(.4,0,.6,0), N,
    vec4(0,0,1,0), vec4(1,0,0,1), vec4(.5,.5,1,.5), N,
    vec4(.5,0,.5,1), vec4(.5,0,1,.25), vec4(1,.25,.5,.5), N,
    vec4(0,.3,0,1), vec4(0,.3,1,.3), vec4(.3,.7,1,.7), N,
    vec4(.5,0,.5,1), vec4(0,.6,.5,1), vec4(1,.6,.5,1), N,
    vec4(.5,0,.5,1), vec4(.5,.4,0,.65), vec4(.5,.2,1,.45), N,
    vec4(0,0,0,1), vec4(1,.5,1,1), vec4(0,1,1,1), vec4(.5,0,.5,.35),
    vec4(.5,0,0,1), vec4(.5,0,1,1), vec4(.25,.6,.75,.6), N,
    vec4(.5,0,.5,1), vec4(0,.35,1,.35), vec4(0,.35,0,.6), N,
    vec4(0,0,.5,.45), vec4(1,0,.5,.45), vec4(.5,.45,.5,1), vec4(.2,.75,.8,.75),
    vec4(.2,0,.2,1), vec4(.8,0,.8,1), vec4(.2,.35,.8,.6), N
);

float seg_dist(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0);
    return length(pa - ba * h);
}

// distance in px from p (px inside the glyph box) to glyph g
float glyph_dist(int g, vec2 p, vec2 box) {
    float d = 1e3;
    for (int i = 0; i < 4; i++) {
        vec4 s = G[g * 4 + i];
        if (s.x < 0.0) continue;
        d = min(d, seg_dist(p, s.xy * box, s.zw * box));
    }
    return d;
}

vec3 burst_col(float k) { return k < 0.5 ? SOFT : (k < 1.5 ? AMBER : DANGER); }

vec3 rain(vec2 px, float lum_mask) {
    if (u_rain.w < 0.5) return vec3(0.0);
    vec2 r0 = u_rain_rect.xy, rs = u_rain_rect.zw;
    vec2 q = px - r0;
    if (q.x < 0.0 || q.y < 0.0 || q.x > rs.x || q.y > rs.y) return vec3(0.0);
    float edge = smoothstep(0.0, 90.0, q.x) * smoothstep(0.0, 140.0, rs.x - q.x) *
                 smoothstep(0.0, 30.0, q.y) * smoothstep(0.0, 180.0, rs.y - q.y);
    const vec2 cell = vec2(15.0, 24.0);
    vec2 ci = floor(q / cell);
    vec2 lp = q - ci * cell;
    float rows = rs.y / cell.y;
    // event bursts: a ripple running out from the event column
    float boost = 0.0; vec3 bcol = vec3(0.0);
    for (int i = 0; i < 6; i++) {
        vec4 b = u_burst[i];
        float dt = u_time - b.y;
        if (b.z <= 0.0 || dt < 0.0 || dt > 2.6) continue;
        float colx = r0.x + (ci.x + 0.5) * cell.x;
        float front = abs(colx - b.x) - dt * 650.0;
        float k = b.z * exp(-front * front / 2600.0) * exp(-dt * 1.3);
        boost += k; bcol += burst_col(b.w) * k;
    }
    vec3 acc = vec3(0.0);
    for (int k = 0; k < 2; k++) {
        float hk = hash1(ci.x * 1.37 + float(k) * 91.7);
        float on_ = step(hk, u_rain.x) + step(0.25, boost);
        if (on_ < 0.5) continue;
        float spd = (0.55 + hash1(ci.x * 7.1 + float(k) * 3.3) * 1.1) * u_rain.y * (1.0 + boost * 1.5);
        float len = 5.0 + hash1(ci.x * 3.7 + float(k)) * 17.0;
        float period = rows + len + 6.0 + hash1(ci.x + float(k) * 13.0) * 24.0;
        float head = mod(u_time * spd + hash1(ci.x * 9.3 + float(k) * 17.0) * period, period);
        float d = head - ci.y;
        if (d < 0.0 || d > len) continue;
        float b = pow(1.0 - d / len, 1.7);
        float mut = floor(u_time * (1.0 - u_calm) * (0.6 + hash2(ci) * 1.4) + hash2(ci.yx) * 9.0);
        int g = int(hash2(ci + mut * 0.731) * 24.0) % 24;
        vec2 box = vec2(8.0, 15.0);
        vec2 gp = lp - vec2(3.5, 4.5);
        float dist = glyph_dist(g, gp, box);
        float cov = clamp(1.25 - dist, 0.0, 1.0);
        float is_head = step(d, 1.0);
        float glow = exp(-dist * dist / 5.0) * 0.35 * is_head;
        vec3 c = mix(DIM, PHOS, b) ;
        c = mix(c, SOFT * 1.15, is_head * 0.8);
        acc += c * (cov * b + glow) ;
    }
    acc *= u_rain.z * (1.0 + boost * 1.6);
    acc = mix(acc, bcol * (length(acc) > 0.0 ? 1.2 : 0.0), clamp(boost, 0.0, 0.7));
    return acc * edge * lum_mask;
}

