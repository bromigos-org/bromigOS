"""INSTALL: the live desktop's "Install bromigOS" icon, a panel of its own (the live user's
plugin folder; customize_airootfs.sh puts it there, docs/iso.md). A click anywhere on it
opens the installer. Only on the live medium: an installed system never has it."""
import subprocess

import draw as D
import panels


class InstallPanel(panels.Panel):
    name, title = "install", "INSTALL"
    description = "Put bromigOS on this computer's disk"
    category, reads = "system", "nothing: it opens the installer"
    min_size, max_size = (300, 150), (520, 220)

    def draw(self, cr, w, h):
        top = D.frame(cr, w, h, "INSTALL", "LIVE")
        D.text(cr, 18, top + 4, "Install bromigOS", size=17, color="phosphor", weight="bold", glow=True)
        D.text(cr, 18, top + 34, "On its own or beside Windows. Nothing changes",
               size=10, color="soft", width=w - 36, wrap=True)
        D.text(cr, 18, top + 50, "until you've checked a summary.", size=10, color="soft")
        D.brackets(cr, 10, top - 2, w - 20, h - top - 6, 10, "phosphor", 1.5, 0.6)
        self.region(0, 0, w, h, "Install bromigOS: opens the installer, which asks a few questions and shows a "
                                "summary before anything on the disk changes", self.open)

    def open(self, *_):
        subprocess.Popen(["/usr/local/bin/bromigos-installer"], start_new_session=True)


PANEL = InstallPanel
LAYOUT = {"width": 340, "height": 150, "visible": True}
