"""__TITLE__: a desktop widget (made by `bromigos ext new widget`; docs/extensions.md).

The widgets find it in the extensions' folder, rescan every 2 s, and run it isolated:
an exception shows in its panel and never reaches the desktop. tick() samples (every
`interval` seconds), draw() paints with cairo and the widgets' draw helpers, region()
gives every part a hover hint. Render it without a window:
    bromigos-widgets render __IDENT__ OUT.png
"""
import os
import time

import draw as D
from panels import Panel

LAYOUT = {"width": 380, "height": 132}


class __CAMEL__Panel(Panel):
    name, title = "__IDENT__", "__UPPER__"
    width, height = 380, 132
    interval = 2.0
    # what the widget gallery shows (bromigOS's docs/plugins.md, "What the gallery shows")
    description = "The load average over 1, 5 and 15 minutes"
    category, reads = "system", "the load average"
    min_size, max_size = (360, 120), (720, 240)    # the sizes edit mode lets it take

    def __init__(self, cfg=None):
        super().__init__(cfg)
        self.load = (0.0, 0.0, 0.0)

    def tick(self):
        self.load = os.getloadavg()

    def draw(self, cr, w, h):
        cpus = os.cpu_count() or 1
        top = D.frame(cr, w, h, self.title, time.strftime("%H:%M"))
        self.region(0, 0, w, 34, "__TITLE__: a starter widget (bromigos ext new widget). "
                                 "It shows the load average; edit widget.py in your extension.")
        x = 16
        for label, v in zip(("1 MIN", "5 MIN", "15 MIN"), self.load):
            D.label(cr, x, top, label, "dim")
            D.seg7(cr, x, top + 18, 34, f"{v:4.2f}", D.level(v / cpus * 100, 70, 90))
            self.region(x, top, 112, 60, f"Load average over {label.lower()}: {v:.2f} "
                                         f"runnable tasks on {cpus} CPUs")
            x += 118


PANEL = __CAMEL__Panel
