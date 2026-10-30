#!/usr/bin/env python3
"""Field Kit's VM test harness (docs/fieldkit.md, "Testing it"): QEMU, headless, with no
network unless asked, driven through the serial console, its screen saved through QEMU's
monitor. Never a window, never the host's network or disks.

  iso/fieldkit/test.py up --iso ISO [--firmware uefi|bios] [--disk FILE [--disk-size 24G]]
                          [--attach FILE …] [--net] [--mem MiB] [--boot cd|disk] [--name N]
                          [--direct [--entry TITLE] [--append PARAMS]]
                          --direct: the medium's kernel and initramfs started by QEMU itself, with
                          the kernel line of its GRUB menu's entry TITLE (default "Start Field
                          Kit") and the console on the serial port too: how a medium that isn't a
                          test build is tested as built (iso/fieldkit/ci-test.sh)
  iso/fieldkit/test.py run [--name N] [--timeout S] -- COMMAND…   a command as root, over the
                          serial console; prints its output, exits with its status
  iso/fieldkit/test.py login [--name N] [--user U --password P]   wait for the serial login and
                          sign in (default root, no password: the medium)
  iso/fieldkit/test.py keys [--name N] KEY…  QMP send-key, e.g. down ret, ctrl-alt-f2, a b c
  iso/fieldkit/test.py type [--name N] TEXT  types TEXT (letters, digits, space, -._/)
  iso/fieldkit/test.py shot [--name N] NAME  the screen as shots/NAME.png
  iso/fieldkit/test.py wait-serial [--name N] TEXT [--timeout S]   until the serial log says TEXT
  iso/fieldkit/test.py down [--name N]

The VM runs through test/vm/vm-keeper.py like every test VM (it stops with whoever started
it). Its folder: $BROMIGOS_FIELDKIT_TEST_DIR (default ~/.cache/bromigos-fieldkit-test/vm)/NAME. A test
medium (iso/build.sh --test-key) has the kernel's console on the serial port too, which this
harness signs in on; any other medium is started with --direct. The serial log is
NAME/serial.log. BROMIGOS_FIELDKIT_HOST_RULES=0 skips the workstation's memory rules (CI's own
machine, iso/fieldkit/ci-test.sh).
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "bromigos-fieldkit-test")
BASE = os.environ.get("BROMIGOS_FIELDKIT_TEST_DIR", os.path.join(CACHE, "vm"))
SHOTS = os.environ.get("BROMIGOS_FIELDKIT_SHOTS", os.path.join(CACHE, "shots"))
OVMF_CODE = "/usr/share/edk2/x64/OVMF_CODE.4m.fd"
OVMF_VARS = "/usr/share/edk2/x64/OVMF_VARS.4m.fd"


def vmdir(name):
    d = os.path.join(BASE, name)
    os.makedirs(d, exist_ok=True)
    return d


def qmp(name, *cmds):
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.path.join(vmdir(name), "qmp.sock"))
    f = s.makefile("rw")
    f.readline()
    out = []
    for c in ({"execute": "qmp_capabilities"},) + cmds:
        f.write(json.dumps(c) + "\n")
        f.flush()
        while True:
            line = json.loads(f.readline())
            if "return" in line or "error" in line:
                out.append(line)
                break
    s.close()
    return out


def memory_ok(mem):
    """The host's rules for test VMs: at least 14 GiB available, every QEMU together at most 10 GiB."""
    avail = int(subprocess.run(["free", "-g"], capture_output=True, text=True).stdout.split("\n")[1].split()[6])
    total = 0
    for pid in subprocess.run(["pgrep", "qemu-system"], capture_output=True, text=True).stdout.split():
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            total += int(argv[argv.index(b"-m") + 1].decode().rstrip("MmGg") or 0)
        except (OSError, ValueError, IndexError):
            continue
    return avail >= 14 and total + mem <= 10240, avail, total


def owner():
    """Whoever started this harness, past the shells and wrappers around it (vm-keeper.py's rule):
    the VM stops when that process does. BROMIGOS_VM_OWNER wins."""
    if os.environ.get("BROMIGOS_VM_OWNER"):
        return os.environ["BROMIGOS_VM_OWNER"]
    skip = {"sh", "bash", "zsh", "dash", "fish", "timeout", "env", "nice", "nohup", "setsid", "python3", "python"}
    pid = os.getppid()
    while pid > 1:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as f:
                argv = f.read().split(b"\0")
            with open(f"/proc/{pid}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            name = os.path.basename(argv[0].decode(errors="replace"))
        except (OSError, IndexError, ValueError):
            break
        if name not in skip:
            return str(pid)
        pid = ppid
    return str(os.getppid())


def up(a):
    d = vmdir(a.name)
    ok, avail, total = memory_ok(a.mem) if os.environ.get("BROMIGOS_FIELDKIT_HOST_RULES") != "0" else (True, 0, 0)
    if not ok:
        sys.exit(f"test.py: not now: {avail} GiB available (needs 14), test VMs use {total} MiB (+{a.mem} > 10240)")
    args = ["qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host", "-m", str(a.mem), "-smp", str(a.smp),
            "-display", "none", "-vnc", f"127.0.0.1:{a.vnc}", "-device", a.vga,
            "-qmp", f"unix:{d}/qmp.sock,server=on,wait=off",
            "-chardev", f"socket,id=ser,path={d}/serial.sock,server=on,wait=off,logfile={d}/serial.log,logappend=on",
            "-serial", "chardev:ser", "-pidfile", f"{d}/qemu.pid", "-device", "qemu-xhci", "-device", "usb-kbd"]
    if a.firmware == "uefi":
        vars_ = os.path.join(d, "OVMF_VARS.fd")
        if not os.path.exists(vars_):
            shutil.copy(OVMF_VARS, vars_)
        args += ["-drive", f"if=pflash,format=raw,readonly=on,file={OVMF_CODE}", "-drive", f"if=pflash,format=raw,file={vars_}"]
    args += ["-nic", "user,model=virtio-net-pci" if a.net else "none"]
    if a.disk:
        if not os.path.exists(a.disk) and a.disk.endswith(".qcow2"):
            subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", a.disk, a.disk_size], check=True)
        args += ["-drive", f"file={a.disk},if=virtio,format={'qcow2' if a.disk.endswith('.qcow2') else 'raw'}"]
    for i, f in enumerate(a.attach or []):
        fmt = "qcow2" if f.endswith(".qcow2") else "raw"
        args += ["-drive", f"file={f},if=none,id=usb{i},format={fmt}", "-device", f"usb-storage,drive=usb{i},removable=on"]
    if a.iso:
        # --direct: QEMU starts the kernel itself, which takes boot index 0; the medium is just a disc
        bi = "" if a.direct else ",bootindex=" + ("0" if a.boot == "cd" else "2")
        args += ["-drive", f"file={a.iso},if=none,id=medium,media=cdrom,readonly=on", "-device", f"ide-cd,drive=medium{bi}"]
    if a.boot == "disk" and a.disk:
        fmt = "qcow2" if a.disk.endswith(".qcow2") else "raw"
        args[args.index(f"file={a.disk},if=virtio,format={fmt}")] = f"file={a.disk},if=none,id=hd,format={fmt}"
        args += ["-device", "virtio-blk-pci,drive=hd,bootindex=0"]
    if a.direct:
        args += direct_boot(d, a.iso, a.entry, a.append)
    open(os.path.join(d, "serial.log"), "w").close()
    keeper = os.path.join(REPO, "test", "vm", "vm-keeper.py")
    subprocess.run([keeper, "--ready", f"{d}/qmp.sock", "--log", f"{d}/keeper.log", "--owner", owner(), "--", *args], check=True)
    time.sleep(2)
    try:
        qmp(a.name, {"execute": "query-status"})
    except OSError:
        sys.exit(f"test.py: the VM didn't stay up; {d}/keeper.log says why")
    print(f"up: {a.name} ({a.firmware}, {a.mem} MiB, {'network' if a.net else 'no network'})")


def direct_boot(d, iso, entry, append):
    """QEMU's -kernel, -initrd and -append for the medium: its kernel and initramfs, and the
    kernel line of its GRUB menu's ENTRY as built (archisosearchuuid and all), plus the serial
    console."""
    subprocess.run(["xorriso", "-osirrox", "on", "-indev", iso,
                    "-extract", "/fieldkit/boot/x86_64/vmlinuz-linux", f"{d}/vmlinuz",
                    "-extract", "/fieldkit/boot/x86_64/initramfs-linux.img", f"{d}/initramfs.img",
                    "-extract", "/boot/grub/grub.cfg", f"{d}/grub.cfg"], check=True, capture_output=True)
    for f in ("vmlinuz", "initramfs.img", "grub.cfg"):
        os.chmod(f"{d}/{f}", 0o644)
    cfg = open(f"{d}/grub.cfg").read()
    m = re.search(r'menuentry "' + re.escape(entry) + r'".*?\n\s*linux\s+\S+\s+([^\n]*)', cfg, re.S)
    if not m:
        sys.exit(f"test.py: no menu entry {entry!r} in the medium's grub.cfg")
    line = f"{m.group(1).strip()} console=tty0 console=ttyS0,115200 {append}".strip()
    open(f"{d}/cmdline", "w").write(line + "\n")
    return ["-kernel", f"{d}/vmlinuz", "-initrd", f"{d}/initramfs.img", "-append", line]


def serial(name):
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.path.join(vmdir(name), "serial.sock"))
    s.settimeout(1)
    return s


def read_until(s, pattern, timeout):
    buf, end = b"", time.time() + timeout
    while time.time() < end:
        try:
            chunk = s.recv(65536)
            if chunk:
                buf += chunk
                if re.search(pattern, buf):
                    return buf
        except socket.timeout:
            pass
    raise TimeoutError(f"no {pattern!r} after {timeout} s; last: {buf[-400:]!r}")


def login(a):
    s = serial(a.name)
    s.sendall(b"\n")
    buf = b""
    end = time.time() + a.timeout
    while time.time() < end:                    # a login prompt, or any shell already signed in
        try:
            buf += s.recv(65536)
        except socket.timeout:
            pass
        if b"login: " in buf[-300:]:
            s.sendall(f"{a.user}\r".encode())
            if a.password:
                read_until(s, rb"[Pp]assword: ?", 30)
                s.sendall(f"{a.password}\r".encode())
            time.sleep(4)
            break
        if buf.strip() and time.time() > end - a.timeout + 3:
            break
    s.sendall(b"exec bash --norc --noprofile\r")
    time.sleep(2)
    # a plain bash for the harness: the login shell's own prompt and line editor stay out of it
    s.sendall(b"stty -echo cols 200; export PS1='> ' TERM=dumb SYSTEMD_PAGER= PAGER=cat SYSTEMD_COLORS=0; echo FK''READY\r")
    read_until(s, rb"FKREADY", 30)
    s.close()
    print("signed in on the serial console")


def run(a):
    s = serial(a.name)
    tag = f"FK{int(time.time() * 1000) % 10**9}"
    cmd = " ".join(a.command)
    # the command on its own lines, so a here-document in it ends where it should
    s.sendall(f"echo {tag}B; {{\n{cmd}\n}} 2>&1; echo {tag}E$?\r".encode())
    buf = read_until(s, rf"{tag}E(\d+)".encode(), a.timeout)
    s.close()
    text = buf.decode(errors="replace")
    body = text.split(f"{tag}B", 1)[-1]
    m = re.search(rf"{tag}E(\d+)", body)
    out = body[:m.start()].strip("\r\n") if m else body
    print(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out).replace("\r", ""))
    return int(m.group(1)) if m else 1


KEYMAP = {" ": "spc", "-": "minus", ".": "dot", "/": "slash", "_": "shift-minus", ":": "shift-semicolon", "=": "equal"}


def keys(name, seq):
    for k in seq:
        qmp(name, {"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": p} for p in k.split("-")]}})
        time.sleep(0.15)


def type_text(name, text):
    seq = []
    for ch in text:
        if ch.isupper():
            seq.append(f"shift-{ch.lower()}")
        elif ch in KEYMAP:
            seq.append(KEYMAP[ch])
        else:
            seq.append(ch)
    keys(name, seq)


def shot(name, label):
    os.makedirs(SHOTS, exist_ok=True)
    ppm = os.path.join(SHOTS, f"{label}.ppm")
    qmp(name, {"execute": "screendump", "arguments": {"filename": ppm}})
    time.sleep(1)
    png = ppm[:-4] + ".png"
    if shutil.which("magick"):
        subprocess.run(["magick", ppm, png], check=True)
        os.unlink(ppm)
        print(png)
    else:
        print(ppm)


def wait_serial(name, text, timeout):
    end = time.time() + timeout
    log = os.path.join(vmdir(name), "serial.log")
    while time.time() < end:
        if text in open(log, errors="replace").read():
            return 0
        time.sleep(2)
    print(f"no {text!r} in the serial log after {timeout} s", file=sys.stderr)
    return 1


def down(name):
    try:
        qmp(name, {"execute": "quit"})
    except OSError:
        pass
    print(f"down: {name}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("up")
    p.add_argument("--iso")
    p.add_argument("--firmware", choices=["uefi", "bios"], default="uefi")
    p.add_argument("--disk")
    p.add_argument("--disk-size", default="24G")
    p.add_argument("--attach", action="append")
    p.add_argument("--net", action="store_true")
    p.add_argument("--mem", type=int, default=3072)
    p.add_argument("--smp", type=int, default=2)
    p.add_argument("--boot", choices=["cd", "disk"], default="cd")
    p.add_argument("--vga", default="virtio-vga")
    p.add_argument("--vnc", default="61")
    p.add_argument("--direct", action="store_true")
    p.add_argument("--entry", default="Start Field Kit")
    p.add_argument("--append", default="")
    for v in ("run", "login", "keys", "type", "shot", "wait-serial", "down"):
        q = sub.add_parser(v)
        q.add_argument("--timeout", type=int, default=600)
        if v == "run":
            q.add_argument("command", nargs=argparse.REMAINDER)
        elif v == "keys":
            q.add_argument("keys", nargs="+")
        elif v in ("type", "shot", "wait-serial"):
            q.add_argument("text")
        elif v == "login":
            q.add_argument("--user", default="root")
            q.add_argument("--password", default="")
    for q in sub.choices.values():
        q.add_argument("--name", default="fk")
    a = ap.parse_args(argv)
    if a.verb == "up":
        up(a)
    elif a.verb == "login":
        login(a)
    elif a.verb == "run":
        if a.command[:1] == ["--"]:
            a.command = a.command[1:]
        return run(a)
    elif a.verb == "keys":
        keys(a.name, a.keys)
    elif a.verb == "type":
        type_text(a.name, a.text)
    elif a.verb == "shot":
        shot(a.name, a.text)
    elif a.verb == "wait-serial":
        return wait_serial(a.name, a.text, a.timeout)
    elif a.verb == "down":
        down(a.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
