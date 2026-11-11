"""Build the battery backup or the rack in Blender from its written spec
(SPEC.md), export a GLB, and write the parts file the hologram bake reads,
with each part's boxes computed from that part's own objects.

    blender -b --factory-startup --python build.py -- ups|rack OUT.glb OUT.parts.json TEMPLATE.json

Every object is named `<part id>:<feature>`. TEMPLATE.json is the shipped
parts file (ids, labels, hints, binds, explode, distance): only the boxes,
the turn and the bake settings change.
"""
import json
import math
import sys

import bmesh
import bpy

ARGS = sys.argv[sys.argv.index("--") + 1:]
WHAT, OUT_GLB, OUT_PARTS, TEMPLATE = ARGS[:4]
U = 0.04445          # 1U
FACE = 0.4826        # 19-inch faceplate width


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def finish(o, name):
    o.name = name
    o.data.name = name
    return o


def box(name, x, y, z, sx, sy, sz, rot_z=0.0, rot_y=0.0, rot_x=0.0):
    """A box centred at (x, y, z), sizes (sx, sy, sz), Blender axes."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(x, y, z), rotation=(rot_x, rot_y, rot_z))
    o = bpy.context.active_object
    o.scale = (sx, sy, sz)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return finish(o, name)


def rounded_box(name, x, y, z, sx, sy, sz, r_vertical=0.0, segments=3, chamfer_top=0.0):
    """A box with rounded vertical edges and an optional chamfer on the top edges (bmesh bevels)."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=bm.verts)
    if r_vertical:
        vert = [e for e in bm.edges if abs(e.verts[0].co.z - e.verts[1].co.z) > sz * 0.5]
        bmesh.ops.bevel(bm, geom=vert, offset=r_vertical, segments=segments, profile=0.5, affect="EDGES")
    if chamfer_top:
        top = [e for e in bm.edges
               if e.verts[0].co.z > sz / 2 - 1e-6 and e.verts[1].co.z > sz / 2 - 1e-6]
        bmesh.ops.bevel(bm, geom=top, offset=chamfer_top, segments=1, profile=0.5, affect="EDGES")
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(o)
    o.location = (x, y, z)
    return o


def cylinder(name, x, y, z, r, depth, axis="y", n=32):
    rot = {"x": (0, math.pi / 2, 0), "y": (math.pi / 2, 0, 0), "z": (0, 0, 0)}[axis]
    bpy.ops.mesh.primitive_cylinder_add(vertices=n, radius=r, depth=depth, location=(x, y, z), rotation=rot)
    return finish(bpy.context.active_object, name)


def torus(name, x, y, z, major, minor, axis="y", major_n=32, minor_n=6):
    rot = {"x": (0, math.pi / 2, 0), "y": (math.pi / 2, 0, 0), "z": (0, 0, 0)}[axis]
    bpy.ops.mesh.primitive_torus_add(major_radius=major, minor_radius=minor, major_segments=major_n,
                                     minor_segments=minor_n, location=(x, y, z), rotation=rot)
    return finish(bpy.context.active_object, name)


def tube(name, points, r, n=8):
    """A cable through `points` (a poly-line), as a curve with a round bevel, made a mesh."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for p, co in zip(sp.points, points):
        p.co = (*co, 1.0)
    cu.bevel_depth = r
    cu.bevel_resolution = max(1, n // 4 - 1)
    cu.use_fill_caps = True
    o = bpy.data.objects.new(name, cu)
    bpy.context.collection.objects.link(o)
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    bpy.ops.object.convert(target="MESH")
    o = bpy.context.active_object
    o.select_set(False)
    return finish(o, name)


# --------------------------------------------------------------------- UPS
def build_ups():
    W, H, D, LIFT = 0.22, 0.42, 0.36, 0.012
    front = -D / 2            # the front face's y
    zb = LIFT + H / 2
    rounded_box("battery:body", 0, 0, zb, W, D, H, r_vertical=0.012, segments=3, chamfer_top=0.004)
    for sx in (-1, 1):
        for sy in (-1, 1):
            box(f"battery:foot{sx}{sy}", sx * (W / 2 - 0.04), sy * (D / 2 - 0.04), LIFT / 2, 0.03, 0.03, LIFT)
    gap = 0.0005               # the front panel's pieces float just off the face: their boxes never hold the body's face
    bz0, bz1, bw, bproud = LIFT + 0.19, LIFT + 0.405, 0.11, 0.006
    me = rounded_box("front:bezel", 0, front - gap - bproud / 2, (bz0 + bz1) / 2, bw, bproud, bz1 - bz0, r_vertical=0.003, segments=1)
    me.rotation_euler = (0, 0, 0)
    fy = front - gap - bproud  # the bezel's face
    dz = LIFT + 0.335
    box("front:display-frame", 0, fy - 0.0015, dz, 0.076, 0.003, 0.107)
    box("front:display", 0, fy - 0.0035, dz, 0.064, 0.002, 0.095)
    cylinder("front:button", 0, fy - 0.002, LIFT + 0.255, 0.009, 0.004, axis="y", n=32)
    cylinder("front:status-light", 0.028, fy - 0.0015, LIFT + 0.255, 0.003, 0.003, axis="y", n=16)
    box("front:label-strip", 0, fy - 0.001, LIFT + 0.222, 0.06, 0.002, 0.006)
    # front grille: raised slats on the face, below the bezel
    n = 13
    for i in range(n):
        x = -0.06 + i * 0.12 / (n - 1)
        box(f"battery:grille{i}", x, front - 0.0015, LIFT + 0.10, 0.0045, 0.003, 0.13)
    # side vents near the back, both sides
    for side in (-1, 1):
        for i in range(9):
            box(f"battery:vent{side}{i}", side * (W / 2 + 0.0012), D / 2 - 0.09, LIFT + 0.05 + i * 0.012, 0.0024, 0.11, 0.005)
    # rear: outlets, input socket, fan grille
    back = D / 2
    for i in range(4):
        box(f"battery:outlet{i}", -0.06 + i * 0.04, back + 0.002, LIFT + 0.12, 0.028, 0.004, 0.034)
    box("battery:inlet", 0.06, back + 0.002, LIFT + 0.30, 0.03, 0.004, 0.022)
    torus("battery:fan-ring", -0.03, back + 0.003, LIFT + 0.30, 0.035, 0.003, axis="y", minor_n=6)
    # power cable: out of the lower left of the face, into a loose coil of three turns on the floor
    # beside the front-left corner, ending in a plug
    cr = 0.0045
    cx, cy = -W / 2 - 0.05, front + 0.11
    tube("battery:cable-lead", [(-W / 2 + 0.025, front - 0.004, LIFT + 0.03), (-W / 2 + 0.02, front - 0.02, cr),
                                (-W / 2 - 0.012, front - 0.012, cr), (cx + 0.02, cy - 0.045, cr)], cr)
    for k in range(3):
        torus(f"battery:cable-coil{k}", cx + 0.005 * k, cy - 0.004 * k, cr + k * 2 * cr * 0.9, 0.045 - 0.004 * k, cr,
              axis="z", major_n=40, minor_n=6)
    tube("battery:cable-tail", [(cx - 0.035, cy - 0.03, cr), (cx - 0.04, cy - 0.08, cr), (cx - 0.02, cy - 0.11, cr)], cr)
    box("battery:plug", cx - 0.005, cy - 0.122, 0.012, 0.03, 0.022, 0.024, rot_z=0.5)
    for k in (-1, 1):
        box(f"battery:plug-pin{k}", cx + 0.007 + 0.004 * k, cy - 0.137, 0.012 + 0.005 * k, 0.012, 0.003, 0.003, rot_z=0.5)


# -------------------------------------------------------------------- rack
def build_rack():
    W, D, H, CAST = 0.60, 0.60, 1.25, 0.10
    post, panel = 0.045, 0.035
    z0, z1 = CAST, H                               # the cabinet's floor and roof
    front, back = -D / 2, D / 2
    # cabinet
    for sx in (-1, 1):
        for sy in (-1, 1):
            box(f"frame:post{sx}{sy}", sx * (W / 2 - post / 2), sy * (D / 2 - post / 2), (z0 + z1) / 2, post, post, z1 - z0)
    box("frame:top", 0, 0, z1 - panel / 2, W, D, panel)
    box("frame:bottom", 0, 0, z0 + panel / 2, W, D, panel)
    box("frame:back", 0, back - 0.004, (z0 + z1) / 2, W - 2 * post, 0.008, z1 - z0 - 2 * panel)
    inner0, inner1 = z0 + panel, z1 - panel
    for sx in (-1, 1):
        x = sx * (W / 2 - 0.004)
        box(f"frame:side{sx}", x, 0, (z0 + z1) / 2, 0.008, D - 2 * post, z1 - z0 - 2 * panel)
        # two vent fields per side: slots standing just proud of the panel
        for f, (fa, fb) in enumerate(((inner0 + 0.10, inner0 + 0.48), (inner0 + 0.58, inner1 - 0.08))):
            n = int((fb - fa) / 0.034)
            for i in range(n):
                box(f"frame:vent{sx}{f}{i}", x + sx * 0.0052, 0.0, fa + i * 0.034, 0.0024, D - 2 * post - 0.18, 0.008)
    # rails, just inside the front posts, with a square hole mark every 1U
    rail_x = FACE / 2 + 0.012
    for sx in (-1, 1):
        box(f"frame:rail{sx}", sx * rail_x, front + post + 0.02, (inner0 + inner1) / 2, 0.018, 0.04, inner1 - inner0)
        k = 0
        z = inner0 + U / 2
        while z < inner1 - U / 2:
            box(f"frame:hole{sx}{k}", sx * rail_x, front + post - 0.0012, z, 0.008, 0.0024, 0.008)
            z += U
            k += 1
    # casters
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = sx * (W / 2 - 0.07), sy * (D / 2 - 0.07)
            box(f"frame:caster-plate{sx}{sy}", x, y, CAST - 0.006, 0.07, 0.07, 0.012)
            box(f"frame:caster-fork{sx}{sy}a", x - 0.016, y, CAST - 0.04, 0.006, 0.05, 0.056)
            box(f"frame:caster-fork{sx}{sy}b", x + 0.016, y, CAST - 0.04, 0.006, 0.05, 0.056)
            cylinder(f"frame:caster-wheel{sx}{sy}", x, y, 0.035, 0.035, 0.024, axis="x", n=32)
    # equipment: faceplates at the rails' front, chassis behind
    fp = front + post + 0.002                      # faceplates' front plane (y), just behind the rail face
    depth = 0.45

    def unit(part, name, top, units, chassis_w=0.43):
        h = units * U - 0.002
        zc = top - units * U / 2
        box(f"{part}:{name}-face", 0, fp + 0.002, zc, FACE, 0.004, h)
        box(f"{part}:{name}-chassis", 0, fp + 0.004 + depth / 2, zc, chassis_w, depth, h - 0.004)
        return zc, h

    top = inner1 - 0.02
    # patch panel and switch (2U)
    zc, h = unit("switch", "patch", top, 1)
    for i in range(24):
        box(f"switch:keystone{i}", -0.19 + i * 0.0165, fp - 0.001, zc, 0.012, 0.002, 0.012)
    top -= U
    zc, h = unit("switch", "switch", top, 1)
    for i in range(24):
        box(f"switch:port{i}", -0.20 + (i // 2) * 0.026 + (i % 2) * 0.0, fp - 0.001, zc + (0.009 if i % 2 else -0.009), 0.014, 0.002, 0.011)
    for i in range(4):
        box(f"switch:uplink{i}", 0.13 + i * 0.022, fp - 0.001, zc, 0.016, 0.002, 0.012)
    for i in range(4):
        cylinder(f"switch:led{i}", -0.225, fp - 0.0008, zc - 0.012 + i * 0.008, 0.002, 0.0016, axis="y", n=12)
    top -= U + U                                   # 1U gap
    # three 1U cluster nodes with a small gap between
    for k in range(3):
        zc, h = unit("nodes", f"node{k}", top, 1)
        for i in range(4):
            box(f"nodes:node{k}-tray{i}", -0.17 + i * 0.07, fp - 0.001, zc, 0.06, 0.002, 0.03)
        for i in range(10):
            box(f"nodes:node{k}-vent{i}", 0.13 + i * 0.008, fp - 0.001, zc, 0.004, 0.002, 0.026)
        cylinder(f"nodes:node{k}-button", 0.225, fp - 0.0015, zc, 0.004, 0.003, axis="y", n=16)
        top -= U + 0.01
    top -= U - 0.01
    # GPU server (4U): three fans
    zc, h = unit("gpu", "server", top, 4, chassis_w=0.44)
    for i, fx in enumerate((-0.135, 0.0, 0.135)):
        torus(f"gpu:fan{i}-ring", fx, fp - 0.003, zc + 0.004, 0.056, 0.004, axis="y", major_n=40, minor_n=6)
        cylinder(f"gpu:fan{i}-hub", fx, fp - 0.004, zc + 0.004, 0.018, 0.006, axis="y", n=32)
        for b in range(7):
            a = b * 2 * math.pi / 7
            r = 0.036
            box(f"gpu:fan{i}-blade{b}", fx + r * math.cos(a), fp - 0.002, zc + 0.004 + r * math.sin(a),
                0.034, 0.002, 0.014, rot_y=-(a + 0.5))
    for i in range(30):
        box(f"gpu:vent{i}", -0.2 + i * 0.0138, fp - 0.001, zc - h / 2 + 0.012, 0.006, 0.002, 0.012)
    top -= 4 * U + U
    # storage (3U): three rows of six trays
    zc, h = unit("storage", "chassis", top, 3)
    for r in range(3):
        for c in range(6):
            x = -0.19 + c * 0.076
            z = zc + (r - 1) * 0.04
            box(f"storage:tray{r}{c}", x, fp - 0.0015, z, 0.07, 0.003, 0.034)
            box(f"storage:tray{r}{c}-handle", x - 0.008, fp - 0.004, z, 0.04, 0.003, 0.006)
            cylinder(f"storage:tray{r}{c}-led", x + 0.027, fp - 0.0035, z + 0.01, 0.002, 0.002, axis="y", n=12)
    top -= 3 * U + 2 * U
    # UPS shelf (2U), near the bottom
    top = inner0 + 0.02 + 2 * U
    zc, h = unit("ups", "shelf", top, 2)
    box("ups:display", -0.12, fp - 0.0015, zc + 0.01, 0.07, 0.003, 0.035)
    for i in range(3):
        cylinder(f"ups:button{i}", -0.06 + i * 0.022, fp - 0.002, zc + 0.01, 0.006, 0.004, axis="y", n=24)
    for i in range(16):
        box(f"ups:vent{i}", 0.04 + i * 0.011, fp - 0.001, zc, 0.005, 0.002, 0.06)
    # cable bundle down the left inside, into the switch
    for k in range(3):
        x = -FACE / 2 + 0.03 + 0.012 * k
        tube(f"frame:cable{k}", [(x - 0.01, fp + 0.03, inner0 + 0.3), (x, fp + 0.03, inner1 - 0.25),
                                 (x + 0.02, fp - 0.012, inner1 - 0.07 - 0.01 * k), (x + 0.06, fp - 0.012, inner1 - 0.05 - 0.01 * k)], 0.005)


# ----------------------------------------------------------------- export
def bounds_by_part():
    """Each part's objects' bounds in glTF axes (x, y up = Blender z, z = -Blender y), and the whole."""
    dg = bpy.context.evaluated_depsgraph_get()
    parts, allv = {}, []
    for o in bpy.context.scene.objects:
        if o.type != "MESH":
            continue
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        vs = [ev.matrix_world @ v.co for v in me.vertices]
        ev.to_mesh_clear()
        g = [(v.x, v.z, -v.y) for v in vs]
        allv += g
        part = o.name.split(":")[0]
        parts.setdefault(part, []).append(g)
    lo = [min(v[i] for v in allv) for i in range(3)]
    hi = [max(v[i] for v in allv) for i in range(3)]
    return parts, lo, hi


def main():
    reset()
    {"ups": build_ups, "rack": build_rack}[WHAT]()
    parts, lo, hi = bounds_by_part()
    span = [hi[i] - lo[i] for i in range(3)]
    spec = json.load(open(TEMPLATE))
    spec = {k: v for k, v in spec.items() if k not in ("source", "requires")}
    pad = 0.0002
    rest = next(p["id"] for p in spec["parts"] if p.get("rest"))
    for p in spec["parts"]:
        p.pop("boxes", None)
        if p["id"] == rest:
            continue
        objs = parts[p["id"]]
        vs = [v for g in objs for v in g]
        b = []
        for i in range(3):
            a = (min(v[i] for v in vs) - pad - lo[i]) / span[i]
            c = (max(v[i] for v in vs) + pad - lo[i]) / span[i]
            b += [round(max(0.0, a), 5), round(min(1.0, c), 5)]
        p["boxes"] = [b]
    spec.update({"rot_y": 0, "edge_deg": 12, "max_edges": 11000, "faces": 40000})
    json.dump(spec, open(OUT_PARTS, "w"), indent=1)
    tris = 0
    for o in bpy.context.scene.objects:
        if o.type == "MESH":
            tris += sum(len(f.vertices) - 2 for f in o.data.polygons)
    bpy.ops.export_scene.gltf(filepath=OUT_GLB, export_format="GLB", export_yup=True, export_apply=True,
                              export_materials="NONE")
    print("BUILT", WHAT, "objects", len([o for o in bpy.context.scene.objects if o.type == "MESH"]), "triangles", tris,
          "size (w, h, d)", [round(s, 3) for s in span], "parts", {k: len(v) for k, v in parts.items()})


main()
