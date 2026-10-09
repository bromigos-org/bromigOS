"""When the live layer has no GPU: GL_RENDERER names a software renderer (Mesa's llvmpipe,
softpipe or swrast), which draws on the CPU.

That happens on a real machine whose graphics driver can't start. The usual cause is an
update of NVIDIA's driver: its new libraries don't match the kernel module still loaded,
until the computer restarts (docs/update.md). At full motion the background then takes a
dozen CPU cores. So, with a software renderer, the layer holds a still frame instead
(motion "still", live/motion.py), drawn again at most every STILL_MIN seconds, caps the
decks' frame rate at CAP_FPS, and says so once.

A virtual machine gets the same still frame. A software renderer is all most of them have
(virtio-gpu without 3D, the ISO's test VMs), and at full motion it took 2.2 of a test VM's
4 CPUs and still fell behind. Nothing is broken there, though, so there's no notification.

`[general] allow_software = true` lets it move at full rate on a software renderer
anywhere. `bromigos accessibility motion still` holds it still anywhere, GPU or not.
"""
import os
import shutil
import subprocess

# GL_RENDERER strings of Mesa's software renderers, lower-cased
NAMES = ("llvmpipe", "softpipe", "swrast", "software rasterizer")
CAP_FPS = 10            # the decks' and overlays' frame rate on a software renderer
STILL_MIN = 30.0        # seconds between still frames there, at least (each one loads the CPU,
                        # which changes the CPU reading the frame shows: it would redraw itself)
FLAG = "bromigos-live.software"     # in XDG_RUNTIME_DIR: the notification went out this session


def is_software(renderer):
    r = (renderer or "").lower()
    return any(n in r for n in NAMES)


_VM = None


def in_vm():
    """A virtual machine (systemd-detect-virt --vm; else the CPU's hypervisor flag).
    BROMIGOS_LIVE_VIRT=vm|none decides instead (tests)."""
    global _VM
    if _VM is None:
        forced = os.environ.get("BROMIGOS_LIVE_VIRT", "")
        _VM = forced == "vm" if forced in ("vm", "none") else _detect_vm()
    return _VM


def _detect_vm():
    exe = shutil.which("systemd-detect-virt")
    if exe:
        try:
            return subprocess.run([exe, "--vm", "--quiet"], timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        with open("/proc/cpuinfo") as f:
            return any(line.startswith("flags") and " hypervisor" in line for line in f)
    except OSError:
        return False


def limited(renderer, allow, vm):
    """(held to a still frame?, why) for a GL_RENDERER string."""
    if not is_software(renderer):
        return False, ""
    if allow:
        return False, "a software renderer, allowed full motion ([general] allow_software = true)"
    then = f"a still frame, decks at {CAP_FPS} fps ([general] allow_software = true allows full motion)"
    if vm:
        return True, f"a software renderer in a virtual machine: {then}"
    return True, ("a software renderer on a real machine: the GPU isn't available (after a graphics "
                  f"driver update, until the computer restarts); {then}")


def notify_once(runtime_dir, renderer):
    """One desktop notification a session (the flag in the runtime directory). True when it
    went out now."""
    flag = os.path.join(runtime_dir, FLAG)
    if os.path.exists(flag):
        return False
    try:
        with open(flag, "w") as f:
            f.write(renderer + "\n")
    except OSError:
        pass
    try:
        subprocess.Popen(
            ["notify-send", "-a", "bromigos", "-u", "normal", "-i", "video-display", "BACKGROUND",
             "The graphics card isn't available, so the animated background shows a still picture. "
             "If the graphics driver was just updated, restart the computer."],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        return True
    except OSError:
        return False
