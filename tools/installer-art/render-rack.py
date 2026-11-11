#!/usr/bin/env python3
"""The rack's renders from VECTOR's hologram gallery, offscreen (EGL; nothing opens on a
desktop), for make.py and homelab/holo/previews/:

  render-rack.py VECTOR_CHECKOUT iso OUT.png             the gallery's rack, GPU server isolated
  render-rack.py VECTOR_CHECKOUT frames OUT_DIR [N ...]  rack-NN.png for `make.py rack`: the
                                                         stage's yaw at -pi + 2pi * N / 24, no idle spin

Run it with made-up readings, a clean HOME (no user's models or lab name) and this checkout's
rack first, and for the frames on a black plate at 1280x800:

  env HOME=$(mktemp -d) BROMIGOS_HOMELAB_CONFIG=/nonexistent OFF_DEMO=1 \\
      BROMIGOS_HOLO_MODELS=$PWD/homelab/holo [OFF_BG=black.jpg OFF_W=1280 OFF_H=800] \\
      python3 tools/installer-art/render-rack.py VECTOR_CHECKOUT ...

The rack needs bromigos-homelab with a source configured to be shown; here that is taken as met.
"""
import math
import os
import sys

if len(sys.argv) < 4 or sys.argv[2] not in ("iso", "frames"):
    sys.exit(__doc__)
vec, mode, out = sys.argv[1:4]
sys.path.insert(0, os.path.join(vec, "tools"))
sys.path.insert(0, vec)
import offscreen  # noqa: E402
from holo import fmt, gallery  # noqa: E402

fmt._have = lambda capability: True
if mode == "iso":
    sys.argv = ["offscreen.py", "gallery", out, "rack", "0", "gpu"]
    offscreen.main()
else:
    yaw = [0.0]
    show = gallery.Gallery.show

    def turned(self, *a, **k):
        r = show(self, *a, **k)
        self.stage.yaw, self.stage.spin = yaw[0], 0.0
        return r
    gallery.Gallery.show = turned
    for n in [int(x) for x in sys.argv[4:]] or list(range(24)):
        yaw[0] = -math.pi + 2 * math.pi * n / 24
        sys.argv = ["offscreen.py", "gallery", os.path.join(out, f"rack-{n:02d}.png"), "rack", "0", "-", "3"]
        offscreen.main()
