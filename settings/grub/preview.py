#!/usr/bin/env python3
"""Preview a boot-menu theme without booting a machine: GRUB itself draws it in a QEMU VM
with no window (-display none), and QEMU's monitor saves the screen (docs/boot.md).

  preview.py --theme DIR --out DIR [--mode 1024x768 --mode 1920x1080 …] [--menu installed|snapshots|medium]
             [--firmware uefi|bios] [--at 4] [--keys down,down]

UEFI: a standalone GRUB (grub-mkstandalone) on a folder QEMU shows as a FAT disk, OVMF's
standard VGA driver set to each mode. BIOS: grub-mkrescue's BIOS image, VBE. The menus are
samples of what grub-mkconfig, grub-btrfs (with bromigOS's titles) and the ISO write, and
nothing they boot does anything. Each shot is <out>/<menu>-<firmware>-<mode>.png, taken
`--at` seconds after GRUB starts (the timeout meter part way through its count).
"""

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

from PIL import Image

OVMF_CODE = "/usr/share/edk2/x64/OVMF_CODE.4m.fd"
OVMF_VARS = "/usr/share/edk2/x64/OVMF_VARS.4m.fd"

NOOP = "{ echo 'preview: nothing boots here'; sleep 2 }"

MENUS = {
    # what grub-mkconfig writes on an installed bromigOS (10_linux, named by the boot theme's
    # GRUB_DISTRIBUTOR, grub-btrfs, 30_uefi-firmware)
    "installed": f"""
menuentry 'bromigOS Linux' --class bromigos --class gnu-linux --class gnu --class os {NOOP}
submenu 'Advanced options for bromigOS Linux' {{
    menuentry 'bromigOS Linux, with Linux linux' --class bromigos --class gnu-linux --class gnu --class os {NOOP}
}}
submenu 'Roll back to a snapshot' --class rollback --id 'bromigos-rollback' {{
    menuentry '10/09 00:28 · before bromigos update' --class snapshot-pre {NOOP}
}}
if [ "$grub_platform" = efi ]; then
menuentry 'UEFI Firmware Settings' --id 'uefi-firmware' {NOOP}
fi
""",
    # grub-btrfs's submenu, its titles as bromigOS rewrites them
    "snapshots": f"""
menuentry 'ROLL BACK · boot the system as it was, newest first' --class info {{ echo }}
submenu '10/09 00:31 · after bromigos update' --class snapshot-post --class snapshots {NOOP}
submenu '10/09 00:28 · before bromigos update' --class snapshot-pre --class snapshots {NOOP}
submenu '10/09 00:00 · timeline' --class snapshot --class snapshots {NOOP}
submenu '10/08 23:12 · after linux mesa bromigos-core' --class snapshot-post --class snapshots {NOOP}
submenu '10/08 23:11 · before pacman -Syu' --class snapshot-pre --class snapshots {NOOP}
submenu '10/08 22:00 · timeline' --class snapshot --class snapshots {NOOP}
submenu '10/08 19:29 · after bromigos update' --class snapshot-post --class snapshots {NOOP}
submenu '10/08 19:27 · before bromigos update' --class snapshot-pre --class snapshots {NOOP}
""",
    # the ISO's channels (iso/profile/grub/grub.cfg)
    "medium": f"""
menuentry 'Start bromigOS (try it live)' --class live --class os {NOOP}
menuentry 'Install bromigOS' --class install {NOOP}
menuentry 'Start with safe graphics (nomodeset)' --class safe {NOOP}
menuentry 'Memory test (Memtest86+)' --class memtest {NOOP}
menuentry 'Boot from disk' --class disk {NOOP}
menuentry 'Start with the screen reader (speech)' --class speech {NOOP}
menuentry 'UEFI shell' --class shell {NOOP}
menuentry 'UEFI firmware settings' --class efi {NOOP}
menuentry 'Shut down' --class shutdown {NOOP}
menuentry 'Restart' --class restart {NOOP}
""",
}


def qmp(sock_path, *cmds):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(sock_path)
    f = s.makefile("rw")
    f.readline()
    for c in ({"execute": "qmp_capabilities"}, *cmds):
        f.write(json.dumps(c) + "\n")
        f.flush()
        while True:
            line = f.readline()
            if not line:
                break
            msg = json.loads(line)
            if "return" in msg or "error" in msg:
                break
    s.close()


def preview_cfg(theme_dir, mode, menu, timeout):
    fonts = sorted(f for f in os.listdir(theme_dir) if f.endswith(".pf2"))
    lines = [
        # tell the harness GRUB is up (the serial port), then draw on the screen
        "insmod serial", "serial --unit=0 --speed=115200", "terminal_output serial", "echo BROMIGOS-PREVIEW-READY",
        "insmod all_video", "insmod gfxterm", "insmod gfxmenu", "insmod png", "insmod font",
        *[f"loadfont /boot/grub/themes/bromigos/{f}" for f in fonts],
        f"set gfxmode={mode}",
        "set gfxpayload=keep",
        "terminal_output gfxterm",
        "set theme=/boot/grub/themes/bromigos/theme.txt",
        "export theme",
        f"set timeout={timeout}",
        "set timeout_style=menu",
        "set default=0",
        MENUS[menu],
    ]
    return "\n".join(lines) + "\n"


def build_root(work, theme_dir, mode, menu, timeout, firmware):
    root = os.path.join(work, "root")
    if os.path.isdir(root):
        shutil.rmtree(root)
    shutil.copytree(theme_dir, os.path.join(root, "boot", "grub", "themes", "bromigos"))
    cfg = preview_cfg(theme_dir, mode, menu, timeout)
    if firmware == "uefi":
        with open(os.path.join(root, "preview.cfg"), "w") as f:
            f.write(cfg)
        embed = os.path.join(work, "embed.cfg")
        with open(embed, "w") as f:
            f.write("search --no-floppy --file --set=root /preview.cfg\nconfigfile /preview.cfg\n")
        os.makedirs(os.path.join(root, "EFI", "BOOT"), exist_ok=True)
        mods = "part_msdos part_gpt fat search search_fs_file configfile normal echo test sleep " \
               "all_video gfxterm gfxmenu png jpeg font serial"
        subprocess.run(["grub-mkstandalone", "-O", "x86_64-efi", "--modules", mods, "--locales=", "--themes=",
                        "--fonts=", "-o", os.path.join(root, "EFI", "BOOT", "BOOTX64.EFI"),
                        f"boot/grub/grub.cfg={embed}"], check=True, capture_output=True)
        return root
    # BIOS: a hybrid image from grub-mkrescue (i386-pc only), the theme on it
    with open(os.path.join(root, "boot", "grub", "grub.cfg"), "w") as f:
        f.write(cfg.replace("insmod all_video", "insmod all_video\ninsmod vbe"))
    iso = os.path.join(work, "preview.iso")
    subprocess.run(["grub-mkrescue", "-d", "/usr/lib/grub/i386-pc", "-o", iso, root], check=True, capture_output=True)
    return iso


def shoot(work, target, firmware, mode, out_png, at, keys, device="VGA"):
    # the monitor's socket by a relative name: a socket's path may not be longer than 107
    os.chdir(work)
    sock = "qmp.sock"
    pid = os.path.join(work, "qemu.pid")
    serial = os.path.join(work, "serial.log")
    for p in (sock, pid, serial):
        if os.path.exists(p):
            os.unlink(p)
    w, h = (int(v) for v in mode.split("x"))
    args = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-m", "512",
            "-vga", "none", "-device", f"{device},xres={w},yres={h},edid=on",
            "-display", "none", "-qmp", f"unix:{sock},server,nowait", "-serial", f"file:{serial}",
            "-daemonize", "-pidfile", pid]
    if firmware == "uefi":
        vars_ = os.path.join(work, "vars.fd")
        shutil.copyfile(OVMF_VARS, vars_)
        args += ["-drive", f"if=pflash,format=raw,readonly=on,file={OVMF_CODE}",
                 "-drive", f"if=pflash,format=raw,file={vars_}",
                 "-drive", f"file=fat:{target},format=raw,if=virtio,readonly=on"]
    else:
        args += ["-drive", f"file={target},media=cdrom,readonly=on,if=ide", "-boot", "d"]
    subprocess.run(args, check=True)
    try:
        # GRUB says when it's up; the shot is `at` seconds after
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                with open(serial, "rb") as f:
                    if b"BROMIGOS-PREVIEW-READY" in f.read():
                        break
            except FileNotFoundError:
                pass
            time.sleep(0.2)
        else:
            raise SystemExit(f"preview: GRUB didn't start in 60 s ({mode})")
        time.sleep(at)
        for k in [k for k in (keys or "").split(",") if k]:
            qmp(sock, {"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": k}]}})
            time.sleep(0.4)
        if keys:
            time.sleep(1)
        ppm = out_png[:-4] + ".ppm"
        qmp(sock, {"execute": "screendump", "arguments": {"filename": ppm}})
        time.sleep(0.5)
        Image.open(ppm).save(out_png)
        os.unlink(ppm)
    finally:
        with open(pid) as f:
            os.kill(int(f.read().strip()), 15)
        time.sleep(0.5)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--theme", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", action="append", help="WxH (repeatable; default 800x600, 1024x768, 1280x800, 1920x1080, 2560x1440)")
    ap.add_argument("--menu", default="installed", choices=sorted(MENUS))
    ap.add_argument("--firmware", default="uefi", choices=("uefi", "bios"))
    ap.add_argument("--at", type=float, default=3.5, help="seconds after GRUB starts to take the shot")
    ap.add_argument("--timeout", type=int, default=12)
    ap.add_argument("--keys", help="QMP keys to press before the shot, e.g. down,down")
    ap.add_argument("--name", help="the shots' name prefix (default MENU-FIRMWARE)")
    ap.add_argument("--auto", action="store_true",
                    help="GRUB_GFXMODE=auto: the screen offers --mode as its preferred one, GRUB picks")
    ap.add_argument("--device", default="VGA", help="QEMU's display device (VGA, virtio-vga, bochs-display)")
    args = ap.parse_args(argv)
    args.out = os.path.abspath(args.out)
    args.theme = os.path.abspath(args.theme)
    modes = args.mode or ["800x600", "1024x768", "1280x800", "1920x1080", "2560x1440"]
    os.makedirs(args.out, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bromigos-grub-preview-") as work:
        for mode in modes:
            target = build_root(work, args.theme, "auto" if args.auto else mode, args.menu, args.timeout, args.firmware)
            png = os.path.join(args.out, f"{args.name or args.menu + '-' + args.firmware}-{mode}.png")
            shoot(work, target, args.firmware, mode, png, args.at, args.keys, args.device)
            print(png, "%dx%d" % Image.open(png).size)


if __name__ == "__main__":
    sys.exit(main())
