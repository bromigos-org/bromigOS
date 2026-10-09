// Per-ship transforms for the instanced starships (gl_InstanceID = ship).
uniform vec4 u_sp[32];   // position xyz (deck space), scale
uniform vec4 u_so[32];   // yaw, pitch, roll, alpha
uniform vec4 u_sl[32];   // light levels: hull, spire, engines, running lights
uniform vec4 u_sc[32];   // status colour rgb (beacon + lights), beacon level

mat3 ship_rot(vec3 r) {
    float cy = cos(r.x), sy = sin(r.x), cp = cos(r.y), sp = sin(r.y), cr = cos(r.z), sr = sin(r.z);
    mat3 ry = mat3(cy, 0.0, -sy, 0.0, 1.0, 0.0, sy, 0.0, cy);
    mat3 rx = mat3(1.0, 0.0, 0.0, 0.0, cp, sp, 0.0, -sp, cp);
    mat3 rz = mat3(cr, sr, 0.0, -sr, cr, 0.0, 0.0, 0.0, 1.0);
    return ry * rx * rz;
}

vec3 ship_world(vec3 p, int i) {
    return u_sp[i].xyz + ship_rot(u_so[i].xyz) * (p * u_sp[i].w);
}

vec4 ship_colour(int part, int i) {
    const vec3 PHOS = vec3(0.2235, 1.0, 0.0784);
    const vec3 SOFT = vec3(0.612, 1.0, 0.541);
    const vec3 AMBER = vec3(0.831, 0.686, 0.216);
    vec4 l = u_sl[i];
    if (part == 0) return vec4(PHOS, 0.55 * l.x);                 // hull
    if (part == 1) return vec4(SOFT, 0.75 * l.y);                 // spire
    if (part == 2) return vec4(mix(PHOS, AMBER, 0.35), l.z);      // engines
    if (part == 3) return vec4(u_sc[i].rgb, l.w);                 // running lights
    return vec4(u_sc[i].rgb, u_sc[i].a);                          // beacon
}
