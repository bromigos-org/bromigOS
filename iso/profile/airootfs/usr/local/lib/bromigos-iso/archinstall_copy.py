"""bromigOS's archinstall plugin (archinstall --plugin): install by copying the live system.

bromigos-iso-install loads it for an install from the medium (docs/iso.md, "How installing
works"). At archinstall's first package step the live system is copied onto the new system's
mounts (bromigos_installer.copyroot.install); every package step's list is recorded in
$BROMIGOS_COPY_STRAPPED, so the installer can keep what an install from packages has and
take the live system's own away afterwards (copyroot.py prune). archinstall's pacstrap then
installs the rest from the medium's store, skipping (--needed) what the copy brought.
"""
import inspect
import os
import sys

__archinstall__version__ = 4.5

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bromigos_installer import copyroot  # noqa: E402


def _target():
    """archinstall's own mount point: its Pacman's target, from the caller's frame; else ours."""
    for fr in inspect.stack()[1:8]:
        obj = fr.frame.f_locals.get("self")
        t = getattr(obj, "target", None)
        if t is not None and os.path.isdir(str(t)):
            return str(t)
    return os.environ.get("BROMIGOS_COPY_TARGET", "/mnt")


class Plugin:
    def __init__(self):
        self.copied = False
        self.record = os.environ.get("BROMIGOS_COPY_STRAPPED", "/run/bromigos-iso/strapped.txt")

    def on_pacstrap(self, packages):
        pkgs = [packages] if isinstance(packages, str) else list(packages)
        os.makedirs(os.path.dirname(self.record), exist_ok=True)
        with open(self.record, "a") as f:
            f.write("\n".join(pkgs) + "\n")
        if not self.copied:
            self.copied = True
            copyroot.install(_target())
        return None
