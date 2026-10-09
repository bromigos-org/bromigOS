"""Where the sky's ships may show on the den: the open sky left of the den's wall and the
space seen through the den's window on the right, nothing else.

Fitted by hand to the shared v1 plate (2560x1440; every approved den variant is
composited onto it, so one fit serves them all), like the den screens in scene.DEN:

  OPEN_SKY  left of the den's wall, above the floor; the bottom fades out over 40 px
            toward the horizon.
  WINDOW    the window's glass: inside its frame (rounded bottom-right corner), above
            the desk, with the two monitors and the cabinet that stand in front of its
            lower-left corner cut out.

The mask is drawn with Cairo at half resolution, softened by a few pixels so hulls slide
behind the frame instead of being cut by a jagged edge, and sampled by space.glsl
traffic() (u_shipmask). Ships fly straight through: one that crosses behind the wall
disappears and can come back into view in the window.
"""
import numpy as np

OPEN_SKY = [(0, 34), (995, 34), (995, 926), (0, 926)]
HORIZON_FADE = (886, 926)                  # y range over which the open sky fades out
# where paths are aimed through (x, y, w, h): lanes alternate between the open sky and the
# window's glass, so both keep their share of traffic
FOCUS = [(0, 60, 995, 820), (1230, 50, 1130, 600)]
WINDOW = [(1205, 34), (2384, 34), (2384, 828), (2378, 858), (2362, 880), (2338, 893), (2306, 898),
          (1702, 898), (1650, 884), (1628, 740), (1432, 738), (1420, 648), (1205, 642)]


def build(w, h, fitted):
    """(mask, mw, mh): an (mh, mw, 3) uint8 mask at half the screen's size (the GPU's linear
    sampler upscales it). fitted=False (not a den variant): the whole upper sky."""
    import cairo
    hw, hh = max(1, w // 2), max(1, h // 2)
    surf = cairo.ImageSurface(cairo.FORMAT_A8, hw, hh)
    cr = cairo.Context(surf)
    cr.scale(hw / 2560.0, hh / 1440.0)
    cr.set_source_rgba(1, 1, 1, 1)
    polys = [OPEN_SKY, WINDOW] if fitted else [[(0, 34), (2400, 34), (2400, 926), (0, 926)]]
    for poly in polys:
        cr.move_to(*poly[0])
        for p in poly[1:]:
            cr.line_to(*p)
        cr.close_path()
        cr.fill()
    surf.flush()
    stride = surf.get_stride()
    a = np.frombuffer(surf.get_data(), np.uint8).reshape(hh, stride)[:, :hw].astype(np.float32) / 255.0
    if fitted:                                # fade the open sky into the floor's haze
        y0, y1 = (int(v * hh / 1440.0) for v in HORIZON_FADE)
        xs = int(995 * hw / 2560.0) + 2
        ramp = np.linspace(1.0, 0.0, max(y1 - y0, 1))[:, None]
        a[y0:y1, :xs] *= ramp
        a[y1:int(930 * hh / 1440.0), :xs] = 0.0
    for axis in (0, 1):                       # a 3-tap box blur twice: a soft 2-3 px edge
        for _ in range(2):
            a = (np.roll(a, 1, axis) + a + np.roll(a, -1, axis)) / 3.0
    a8 = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    return np.ascontiguousarray(np.repeat(a8[:, :, None], 3, axis=2)), hw, hh
