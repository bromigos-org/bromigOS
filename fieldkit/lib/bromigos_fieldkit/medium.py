"""The Field Kit medium's own jobs at boot (docs/fieldkit.md, "Your settings on the stick" and
"Remote help"). Everything here is offline.

Settings on the stick: a `fieldkit/` folder, found at boot on
  - a partition labelled FIELDKIT (what `bromigos fieldkit make-stick` adds after the medium),
  - the Ventoy partition, beside the ISO files (label Ventoy),
  - the medium itself (read-only, when someone put it in the ISO),
first found wins. It holds:

  fieldkit/config.toml
      [ssh]
      authorized_keys = ["ssh-ed25519 AAAA… you@laptop"]   # who may sign in as root
      start = false                                         # true: SSH on at every start
      [[wifi]]
      ssid = "Workshop"
      password = "…"                                        # leave out for an open network
      [lab]
      config = "homelab.toml"                               # a file beside config.toml, the
                                                            # lab connection (bromigos lab)
  fieldkit/autorun/*.sh        run at startup in name order, as root, each with its output in
                               /run/bromigos-fieldkit/autorun.log (and autorun-<name>.log);
                               the menu says what ran and how it ended
  fieldkit/homelab.toml        (or the file [lab] names) copied to root's ~/.config/bromigos/

Remote help (`bromigos.remote=on` on the kernel's command line, the boot menu's "with remote
help", the menu's Shell › Remote help, or [ssh] start): SSH starts; with no key on the stick
a one-time password is made and shown. While it's on, the menu's status line says so, in its
warning colour, with the address to use; /run/issue.d says it on the other consoles too.
"""

import glob
import json
import os
import secrets
import socket
import subprocess
import time
import tomllib

from . import system

RUN = os.environ.get("BROMIGOS_FIELDKIT_RUN", "/run/bromigos-fieldkit")
STICK = os.path.join(RUN, "stick")
REMOTE = os.path.join(RUN, "remote.json")
AUTORUN_LOG = os.path.join(RUN, "autorun.log")
SSHD_DROPIN = "/etc/ssh/sshd_config.d/20-bromigos-remote.conf"
ROOT_HOME = os.environ.get("BROMIGOS_FIELDKIT_ROOT_HOME", "/root")
WORDS = ("amber", "beacon", "cobalt", "delta", "ember", "falcon", "glacier", "harbor", "indigo", "juniper",
         "kestrel", "lumen", "meridian", "nova", "orbit", "pylon", "quartz", "relay", "signal", "tundra",
         "umbra", "vector", "wick", "zenith")


def log(msg):
    os.makedirs(RUN, exist_ok=True)
    with open(os.path.join(RUN, "boot.log"), "a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


# ------------------------------------------------------------------ finding the settings

def candidates():
    """Where a fieldkit/ folder may be: (device or None, folder to look in)."""
    out = []
    for label in ("FIELDKIT", "Ventoy"):
        dev = f"/dev/disk/by-label/{label}"
        if os.path.exists(dev):
            out.append((os.path.realpath(dev), None))
    out.append((None, "/run/archiso/bootmnt"))
    return out


def find_settings():
    """The fieldkit/ folder's path once mounted (read-only), or None."""
    os.makedirs(STICK, exist_ok=True)
    for dev, folder in candidates():
        if dev:
            if not os.path.ismount(STICK):
                r = system.run(["mount", "-o", "ro", dev, STICK], check=False)
                if r.returncode != 0:
                    continue
            if os.path.isdir(os.path.join(STICK, "fieldkit")):
                return os.path.join(STICK, "fieldkit")
            system.run(["umount", STICK], check=False)
        elif folder and os.path.isdir(os.path.join(folder, "fieldkit")):
            return os.path.join(folder, "fieldkit")
    return None


def read_config(folder):
    path = os.path.join(folder, "config.toml")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        log(f"config.toml couldn't be read: {e}")
        return {}


# ------------------------------------------------------------------ applying them

def add_keys(keys):
    if not keys:
        return 0
    d = os.path.join(ROOT_HOME, ".ssh")
    os.makedirs(d, mode=0o700, exist_ok=True)
    path = os.path.join(d, "authorized_keys")
    have = system.read(path).splitlines() if os.path.exists(path) else []
    new = [k.strip() for k in keys if k.strip() and k.strip() not in have and k.strip().startswith(("ssh-", "ecdsa-", "sk-"))]
    with open(path, "a") as f:
        for k in new:
            f.write(k + "\n")
    os.chmod(path, 0o600)
    return len(new)


def add_wifi(networks):
    """Each network as a NetworkManager connection (system-owned, in RAM on the medium)."""
    done = 0
    for n in networks or []:
        ssid = str(n.get("ssid", "")).strip()
        if not ssid:
            continue
        name = f"fieldkit-{ssid}"
        args = ["nmcli", "connection", "add", "type", "wifi", "con-name", name, "ssid", ssid, "connection.autoconnect", "yes"]
        if n.get("password"):
            args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", str(n["password"])]
        system.run(["nmcli", "connection", "delete", name], check=False)
        if system.run(args, check=False).returncode == 0:
            done += 1
        else:
            log(f"Wi-Fi {ssid}: NetworkManager refused it")
    return done


def add_lab(folder, cfg):
    name = (cfg.get("lab") or {}).get("config") or "homelab.toml"
    src = os.path.join(folder, os.path.basename(name))
    if not os.path.isfile(src):
        return False
    dst = os.path.join(ROOT_HOME, ".config", "bromigos", "homelab.toml")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as a, open(dst, "wb") as b:
        b.write(a.read())
    os.chmod(dst, 0o600)
    return True


def autorun(folder):
    """fieldkit/autorun/*.sh in name order; returns [(name, exit code)]. Each script's output is
    kept; one that fails doesn't stop the next."""
    results = []
    scripts = sorted(glob.glob(os.path.join(folder, "autorun", "*.sh")))
    with open(AUTORUN_LOG, "a") as summary:
        for s in scripts:
            name = os.path.basename(s)
            out = os.path.join(RUN, f"autorun-{name}.log")
            with open(out, "w") as f:
                try:
                    rc = subprocess.call(["/bin/bash", s], stdout=f, stderr=subprocess.STDOUT, cwd=folder, timeout=600)
                except subprocess.TimeoutExpired:
                    rc = 124
            summary.write(f"{time.strftime('%H:%M:%S')} {name}: {'done' if rc == 0 else f'failed ({rc})'} (log: {out})\n")
            results.append((name, rc))
    return results


def boot():
    """At startup (bromigos-fieldkit-stick.service): the stick's settings applied, its scripts
    run, then remote help if it was asked for. Writes RUN/stick.json for the menu."""
    os.makedirs(RUN, exist_ok=True)
    folder = find_settings()
    doc = {"found": bool(folder), "where": folder}
    if folder:
        cfg = read_config(folder)
        ssh = cfg.get("ssh") or {}
        doc["keys"] = add_keys(ssh.get("authorized_keys") or [])
        doc["wifi"] = add_wifi(cfg.get("wifi"))
        doc["lab"] = add_lab(folder, cfg)
        doc["autorun"] = autorun(folder)
        if ssh.get("start"):
            doc["remote"] = "stick"
        log(f"settings from {folder}: {doc}")
    if "bromigos.remote=on" in system.cmdline() or doc.get("remote"):
        remote_on()
    with open(os.path.join(RUN, "stick.json"), "w") as f:
        json.dump(doc, f)
    return doc


def stick_summary():
    try:
        d = json.load(open(os.path.join(RUN, "stick.json")))
    except (OSError, ValueError):
        return ""
    if not d.get("found"):
        return ""
    bits = []
    if d.get("keys"):
        bits.append(f"{d['keys']} SSH key(s)")
    if d.get("wifi"):
        bits.append(f"{d['wifi']} Wi-Fi network(s)")
    if d.get("lab"):
        bits.append("the lab connection")
    runs = d.get("autorun") or []
    if runs:
        bad = [n for n, rc in runs if rc]
        bits.append(f"{len(runs)} startup script(s)" + (f", {len(bad)} failed" if bad else ""))
    return "stick settings: " + (", ".join(bits) if bits else "none")


# ------------------------------------------------------------------ remote help

def addresses():
    r = system.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], check=False)
    return [line.split()[3].split("/")[0] for line in r.stdout.splitlines() if len(line.split()) > 3]


def remote_on():
    """SSH on for remote help: keys from the stick, or a one-time password (three words and a
    number) for root, shown on screen. Returns the state."""
    keys = os.path.join(ROOT_HOME, ".ssh", "authorized_keys")
    has_key = os.path.isfile(keys) and os.path.getsize(keys) > 0
    password = None
    lines = ["# bromigOS Field Kit: remote help is on (bromigos fieldkit remote off ends it)",
             "PermitRootLogin yes" if not has_key else "PermitRootLogin prohibit-password"]
    if not has_key:
        password = "-".join(secrets.choice(WORDS) for _ in range(3)) + f"-{secrets.randbelow(90) + 10}"
        system.run(["chpasswd"], input=f"root:{password}\n")
        lines.append("PasswordAuthentication yes")
        lines.append("KbdInteractiveAuthentication yes")
    os.makedirs(os.path.dirname(SSHD_DROPIN), exist_ok=True)
    with open(SSHD_DROPIN, "w") as f:
        f.write("\n".join(lines) + "\n")
    system.run(["systemctl", "restart", "sshd.service"], check=False)
    state = {"on": True, "since": time.strftime("%H:%M"), "password": password, "key": has_key,
             "addresses": addresses(), "host": socket.gethostname()}
    with open(REMOTE, "w") as f:
        json.dump(state, f)
    os.chmod(REMOTE, 0o600)
    note()
    return state


def remote_off():
    system.run(["systemctl", "stop", "sshd.service"], check=False)
    for p in (SSHD_DROPIN, REMOTE, "/run/issue.d/30-bromigos-remote.issue"):
        try:
            os.unlink(p)
        except OSError:
            pass
    system.run(["passwd", "-d", "root"], check=False)        # the medium's root has no password again
    return {"on": False}


def remote_state():
    try:
        with open(REMOTE) as f:
            st = json.load(f)
        st["addresses"] = addresses() or st.get("addresses", [])
        return st
    except (OSError, ValueError):
        return {"on": False}


def remote_words(st=None):
    st = st or remote_state()
    if not st.get("on"):
        return ""
    where = ", ".join(f"root@{a}" for a in st.get("addresses") or []) or "root@(no network yet)"
    how = f"password {st['password']}" if st.get("password") else "your SSH key"
    return f"REMOTE HELP ON · ssh {where} · {how} · shared session: tmux attach -t fieldkit"


def note():
    os.makedirs("/run/issue.d", exist_ok=True)
    with open("/run/issue.d/30-bromigos-remote.issue", "w") as f:
        f.write("\\e{yellow}  " + remote_words() + "\\e{reset}\n\n")
