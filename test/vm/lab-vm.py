#!/usr/bin/env python3
"""A headless Debian guest for provisioning tests, owned by vm-keeper.py."""
import hashlib
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import urllib.request

HERE = Path(__file__).resolve().parent
DIR = Path(os.environ["BROMIGOS_VM_DIR"])
PORT = os.environ["BROMIGOS_VM_PORT"]
KEY = DIR / "id_ed25519"
SSH = ["ssh", "-F", "/dev/null", "-i", str(KEY), "-p", PORT, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=3", "tester@127.0.0.1"]


def wait_ssh():
    for _ in range(120):
        if subprocess.run(SSH + ["true"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
        time.sleep(2)
    raise RuntimeError("Guest SSH did not start; inspect its console.log")


def owns_process(args, disk):
    drive = b'file=' + str(disk).encode() + b','
    return bool(args and Path(os.fsdecode(args[0])).name.startswith('qemu-system-') and any(arg.startswith(drive) for arg in args))


def main():
    command = sys.argv[1]
    if command == "up":
        DIR.mkdir(parents=True, exist_ok=True)
        image = DIR / "debian-12-genericcloud-amd64.qcow2"
        url = "https://cloud.debian.org/images/cloud/bookworm/latest/"
        # A separately trusted digest permits reproducible cached-image runs.
        # It never disables checking the image bytes.
        expected = os.environ.get('BROMIGOS_PROVISION_IMAGE_SHA512')
        if expected:
            import re
            if not re.fullmatch(r'[0-9a-f]{128}', expected): raise RuntimeError('Invalid trusted image digest')
        else:
            checksums = subprocess.check_output(["curl", "-fsSL", "--retry", "3", "--retry-all-errors", "--connect-timeout", "10", "--max-time", "60", url + "SHA512SUMS"], text=True)
            expected = next(row.split()[0] for row in checksums.splitlines() if row.split()[1] == image.name)
        if os.environ.get("BROMIGOS_PROVISION_IMAGE") and not image.exists():
            import shutil
            shutil.copyfile(os.environ["BROMIGOS_PROVISION_IMAGE"], image)
        if not image.exists():
            subprocess.run(["curl", "-fsSL", "--connect-timeout", "10", "--max-time", "600", "-o", str(image), url + image.name], check=True)
        with image.open("rb") as stream:
            if hashlib.file_digest(stream, "sha512").hexdigest() != expected:
                raise RuntimeError("Debian cloud image checksum differs")
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "provision-test", "-f", str(KEY)], check=True)
        subprocess.run(["qemu-img", "create", "-q", "-f", "qcow2", "-b", str(image), "-F", "qcow2", str(DIR / "vm.qcow2"), os.environ.get('BROMIGOS_VM_DISK_GIB', '120') + 'G'], check=True)
        (DIR / "meta-data").write_text("instance-id: provision-test\nlocal-hostname: provision-test\n")
        (DIR / "user-data").write_text("#cloud-config\nusers:\n  - name: tester\n    sudo: ALL=(ALL) NOPASSWD:ALL\n    shell: /bin/bash\n    ssh_authorized_keys:\n      - " + KEY.with_suffix(".pub").read_text().strip() + "\n")
        subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-o", str(DIR / "seed.iso"), "-V", "cidata", "-J", "-r",
                        str(DIR / "user-data"), str(DIR / "meta-data")], check=True)
        subprocess.run([str(HERE / "vm-keeper.py"), "--ready", str(DIR / "qmp.sock"), "--log", str(DIR / "keeper.log"), "--",
                        "qemu-system-x86_64", "-enable-kvm", "-machine", "q35", "-cpu", "host", "-m", os.environ.get("BROMIGOS_VM_MEM", "4096"),
                        "-smp", os.environ.get('BROMIGOS_VM_CPUS', '2'), "-drive", f"file={DIR}/vm.qcow2,if=virtio", "-drive", f"file={DIR}/seed.iso,if=virtio,format=raw",
                        "-nic", f"user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:{PORT}-:22", "-display", "none",
                        "-qmp", f"unix:{DIR}/qmp.sock,server,nowait", "-serial", f"file:{DIR}/console.log", "-pidfile", str(DIR / "qemu.pid")], check=True)
        wait_ssh()
        print("Debian test guest ready")
    elif command == "ssh":
        return subprocess.run(SSH + sys.argv[2:]).returncode
    elif command == "reboot":
        subprocess.run(SSH + ["sudo systemctl reboot"], check=False)
        time.sleep(10)
        wait_ssh()
    elif command == "destroy":
        pidfile = DIR / "qemu.pid"
        if pidfile.exists():
            import signal
            pid = int(pidfile.read_text())
            try:
                args = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            except FileNotFoundError:
                args = []
            owned = owns_process(args, DIR / 'vm.qcow2')
            try:
                if owned: os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(30):
                if not owned: break
                try: os.kill(pid, 0)
                except ProcessLookupError: break
                time.sleep(0.5)
            else:
                os.kill(pid, signal.SIGKILL)
        for name in ("vm.qcow2", "debian-12-genericcloud-amd64.qcow2", "seed.iso", "id_ed25519", "id_ed25519.pub", "user-data", "meta-data"):
            (DIR / name).unlink(missing_ok=True)
    else:
        raise RuntimeError("Choose up, ssh, reboot or destroy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
