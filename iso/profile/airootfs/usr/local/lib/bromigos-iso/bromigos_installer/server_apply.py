#!/usr/bin/env python3
"""bromigOS Server's setup in the new system (docs/server.md, "What the installer sets up"),
after archinstall and before the first start: bromigos-iso-install runs it with the
installers' answers, whose "server" part is server.plan()'s.

  server_apply.py --answers FILE --target /mnt --user NAME     as root, in the live system
  server_apply.py --answers FILE --target DIR --user NAME --dry-run
                                    files written under DIR, commands listed, nothing run (tests)

What it does, in order, saying each in a ::server line (the installers' details):

  packages     what the medium didn't carry: from Arch's mirrors when there's a network,
               else listed in /etc/bromigos/server/pending-packages for the first update
  settings     /etc/bromigos/server.toml (bromigos-server setup applies it, when installed)
  network      a NetworkManager profile: the port, DHCP or the fixed address, Wake-on-LAN,
               a VLAN or a bond
  sign-in      sshd: keys only unless a password was chosen, MaxAuthTries, AllowGroups; the
               admin's keys; on a Lab node the lab account (its key only, passwordless sudo);
               root locked
  firewall     bromigos-server's rule sets when it's installed, else its table in /etc/nftables.conf
  hardening    the sysctl list, journald's limits, AppArmor on the kernel line
  kernel       linux-lts first in the boot menu, linux as the spare (GRUB_TOP_LEVEL)
  data disks   btrfs (single or RAID1) at /srv/data, in fstab, scrubbed monthly; hourly
               snapshots on Storage; SMB and NFS shares
  services     each role's and service's units enabled (those the system has); Tailscale and
               WireGuard installed and left off unless chosen
  updates      the update timer moved into the window; the mode in server.toml
  health       the role's checks in /etc/bromigos/server/health.d/
  find my lab  the mDNS announcement (_bromigos-lab._tcp)
  unlock       with the security chip: systemd's initramfs and a first-start enrolment
               (systemd-cryptenroll --tpm2-device=auto), the passphrase kept as the spare
"""
import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
from bromigos_installer import server  # noqa: E402

LAN4 = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"]  # privacy: allow (the private ranges themselves: what "the local network" means)
LAN6 = ["fc00::/7", "fe80::/10"]
ARCH_MIRROR = "https://geo.mirror.pkgbuild.com/$repo/os/$arch"
PKG_SERVER = ("/usr/lib/bromigos/server/bromigos-server", "/usr/lib/bromigos/bin/bromigos-server", "/usr/bin/bromigos-server")

HEALTH = {   # a role's own checks: exit 0 is healthy (bromigos-server runs /etc/bromigos/server/health.d/*.sh)
    "k3s": """# Lab node: once the lab has joined it, the cluster's agent runs
if systemctl list-unit-files k3s-agent.service k3s.service >/dev/null 2>&1 && \\
   systemctl list-unit-files k3s-agent.service k3s.service | grep -q enabled; then
    systemctl is-active --quiet k3s-agent.service || systemctl is-active --quiet k3s.service
fi
""",
    "arrays": """# Storage: the data pool is mounted and no disk in it has errors
if grep -q ' /srv/data ' /proc/mounts; then
    btrfs device stats --check /srv/data >/dev/null
fi
""",
    "shares": """# Storage: the shares' services run when they're on
for u in smb.service nfs-server.service; do
    if systemctl is-enabled --quiet "$u" 2>/dev/null; then systemctl is-active --quiet "$u" || exit 1; fi
done
""",
    "apps": """# Home services and Game server: every app this server runs is up
failed=$(systemctl list-units --plain --no-legend --state=failed 'bromigos-app-*' 2>/dev/null | wc -l)
[ "$failed" -eq 0 ]
""",
    "wings": """# Game server with the lab's panel: Docker's engine runs, and Wings once it's installed
systemctl is-active --quiet docker.service || exit 1
if systemctl list-unit-files wings.service >/dev/null 2>&1 && systemctl is-enabled --quiet wings.service 2>/dev/null; then
    systemctl is-active --quiet wings.service
fi
""",
    "disks": """# Every server: no disk says it's failing (smartd's own verdict)
command -v smartctl >/dev/null || exit 0
for d in $(lsblk -dnpo NAME,TYPE | awk '$2 == "disk" { print $1 }'); do
    smartctl -H "$d" 2>/dev/null | grep -qE 'FAILED|FAILING' && exit 1
done
exit 0
""",
}


def say(text):
    print(f"::server {text}", flush=True)


class Apply:
    def __init__(self, doc, target, user, dry=False, online=None):
        self.doc, self.p, self.t, self.user, self.dry = doc, doc["server"], target.rstrip("/") or "/", user, dry
        self.cmds = []
        self.online = online
        self.problems = []

    # ── plumbing ────────────────────────────────────────────────────────────────────
    def path(self, p):
        return os.path.join(self.t, p.lstrip("/"))

    def write(self, p, text, mode=0o644):
        full = self.path(p)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(text)
        os.chmod(full, mode)

    def read(self, p, default=""):
        try:
            with open(self.path(p)) as f:
                return f.read()
        except OSError:
            return default

    def run(self, argv, check=False, input=None):
        """A command in the new system (arch-chroot); listed, not run, with --dry-run."""
        self.cmds.append(argv)
        if self.dry:
            return 0, ""
        full = ["arch-chroot", self.t, *argv] if self.t != "/" else argv
        r = subprocess.run(full, capture_output=True, text=True, input=input)
        if r.returncode != 0:
            msg = f"{' '.join(argv)}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['failed']}"
            self.problems.append(msg)
            if check:
                raise RuntimeError(msg)
        return r.returncode, r.stdout

    def host(self, argv, check=True):
        """A command in the live system (disks: mkfs, blkid)."""
        self.cmds.append(["(live)", *argv])
        if self.dry:
            return 0, ""
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0 and check:
            raise RuntimeError(f"{' '.join(argv)}: {(r.stderr or r.stdout).strip()}")
        return r.returncode, r.stdout

    def unit_exists(self, unit):
        base = re.sub(r"@[^.]+\.", "@.", unit)
        return any(os.path.exists(self.path(f"{d}/{u}")) for d in ("/usr/lib/systemd/system", "/etc/systemd/system")
                   for u in (unit, base))

    def has_pkg_server(self):
        return any(os.path.exists(self.path(p)) for p in PKG_SERVER)

    # ── the steps ───────────────────────────────────────────────────────────────────
    def installed(self):
        db = self.path("/var/lib/pacman/local")
        out = set()
        try:
            for d in os.listdir(db):
                m = re.match(r"^(.*)-[^-]+-[^-]+$", d)
                if m:
                    out.add(m.group(1))
        except OSError:
            pass
        return out

    def packages(self):
        """What the medium didn't carry: from the network now, else at the first update."""
        have = self.installed()
        missing = [x for x in self.p["packages"] if x not in have]
        self.pending = []
        if not missing:
            say("every package came from the USB stick")
            return
        online = self.online if self.online is not None else _online()
        arch = [x for x in missing if not x.startswith(("bromigos", "brodec", "herdr", "mehshell"))]
        if online and arch:
            say(f"downloading what the USB stick doesn't carry: {' '.join(arch)}")
            conf = ("[options]\nHoldPkg = pacman glibc\nArchitecture = auto\nSigLevel = Required DatabaseOptional\n"
                    "LocalFileSigLevel = Optional\nParallelDownloads = 5\n\n"
                    f"[core]\nServer = {ARCH_MIRROR}\n\n[extra]\nServer = {ARCH_MIRROR}\n")
            self.write("/etc/pacman.d/bromigos-server-install.conf", conf)
            # -yy: the stick's own core.db and extra.db (its subset) are newer than the mirror's,
            # so a plain -y would keep them and find none of these
            rc, _ = self.run(["pacman", "--config", "/etc/pacman.d/bromigos-server-install.conf", "-Syyu", "--needed",
                              "--noconfirm", *arch])
            if not self.dry:
                os.unlink(self.path("/etc/pacman.d/bromigos-server-install.conf"))
            if rc == 0:
                missing = [x for x in missing if x not in arch]
            else:
                say("the download didn't finish: " + (self.problems[-1] if self.problems else "pacman failed"))
        elif arch:
            say("no network now: the rest installs at the first update with one")
        self.pending = missing
        if missing:
            say(f"waiting for a network, installed at the first update: {' '.join(missing)}")
            self.write("/etc/bromigos/server/pending-packages", "\n".join(missing) + "\n")
            self.write("/etc/systemd/system/bromigos-server-pending.service", PENDING_UNIT)
            self.run(["systemctl", "enable", "bromigos-server-pending.service"])

    def settings(self):
        self.write("/etc/bromigos/server.toml", server.server_toml(self.p, getattr(self, "pending", []),
                                                                   getattr(self, "allow_known", None)))
        say("settings: /etc/bromigos/server.toml")

    def secrets(self):
        """Every typed secret and the names to generate, for the store chosen (bromigos_homelab.secretstore):
        root-only in the new system until the first start puts them in the store; never in a file the
        answers keep."""
        vals = {k: v for k, v in (self.p.get("secrets") or {}).items() if v}
        gen = list(self.p.get("generate") or [])
        cfg = self.p.get("store_config") or {"backend": "local"}
        # the choice, with no values (/etc/bromigos/secrets.toml): the lab's secret store reads it
        lines = ["# Where this server keeps its keys (bromigos lab secrets). No secret values here.",
                 f"backend = {json.dumps(cfg['backend'])}"]
        for section in ("vault", "sops"):
            if cfg.get(section):
                lines.append(f"\n[{section}]")
                lines += [f"{k} = {json.dumps(v)}" for k, v in cfg[section].items()]
        self.write("/etc/bromigos/secrets.toml", "\n".join(lines) + "\n")
        if not vals and not gen and cfg["backend"] != "openbao":
            say(f"keys: {cfg['backend']}, nothing to store yet")
            return
        path = server.secretstore().stage(self.t, self.p.get("store") or {}, vals, gen)
        self.write("/etc/systemd/system/bromigos-server-secrets.service", SECRETS_UNIT)
        self.run(["systemctl", "enable", "bromigos-server-secrets.service"])
        say(f"keys: {len(vals)} typed and {len(gen)} to make, for {(self.p.get('store') or {}).get('kind', 'local')} "
            f"({os.path.relpath(path, self.t) if path else 'staged'})")

    def network(self):
        n = self.p["network"]
        iface = n.get("interface")
        if not iface:
            say("network: no port chosen; NetworkManager connects whatever is plugged in")
            return
        d = "/etc/NetworkManager/system-connections"
        ip4 = ["[ipv4]"]
        if n["method"] == "static":
            ip4 += [f"method=manual", f"address1={n['address']}/{n['prefix']}" + (f",{n['gateway']}" if n.get("gateway") else ""),
                    "dns=" + ";".join(n.get("dns") or []) + ";"]
        else:
            ip4 += ["method=auto"]
        ip6 = ["[ipv6]", "method=auto", "addr-gen-mode=default"]
        wol = ["[ethernet]", "wake-on-lan=64" if n.get("wake_on_lan") else "wake-on-lan=1"]   # 64: magic packet, 1: off
        files = {}
        bond, vlan = n.get("bond") or [], n.get("vlan")
        top = iface
        if len(bond) >= 2:
            top = "bond0"
            files["bromigos-bond0"] = ["[connection]", "id=bromigos-bond0", "type=bond", "interface-name=bond0",
                                       "autoconnect=true", "", "[bond]", "mode=802.3ad", "miimon=100"]
            for b in bond:
                files[f"bromigos-bond0-{b}"] = ["[connection]", f"id=bromigos-bond0-{b}", "type=ethernet",
                                                f"interface-name={b}", "controller=bond0", "port-type=bond",
                                                "autoconnect=true", ""] + wol
        if vlan:
            parent = top
            if top == iface:
                files[f"bromigos-{iface}"] = ["[connection]", f"id=bromigos-{iface}", "type=ethernet", f"interface-name={iface}",
                                              "autoconnect=true", ""] + wol + ["", "[ipv4]", "method=disabled", "", "[ipv6]",
                                                                                "method=ignore"]
            name = f"{parent}.{vlan}"
            files[f"bromigos-{name}"] = ["[connection]", f"id=bromigos-{name}", "type=vlan", f"interface-name={name}",
                                         "autoconnect=true", "", "[vlan]", f"parent={parent}", f"id={vlan}", ""] + ip4 + [""] + ip6
        elif top == "bond0":
            files["bromigos-bond0"] += [""] + ip4 + [""] + ip6
        else:
            files["bromigos-server"] = ["[connection]", "id=bromigos-server", "type=ethernet", f"interface-name={iface}",
                                        "autoconnect=true", "autoconnect-priority=100", ""] + wol + [""] + ip4 + [""] + ip6
        for name, lines in files.items():
            self.write(f"{d}/{name}.nmconnection", "\n".join(lines) + "\n", 0o600)
        say(f"network: {iface}, " + (f"fixed {n['address']}/{n['prefix']}" if n["method"] == "static" else "DHCP")
            + (f", VLAN {vlan}" if vlan else "") + (f", bond of {' + '.join(bond)}" if len(bond) >= 2 else "")
            + (", Wake-on-LAN" if n.get("wake_on_lan") else ""))

    def sign_in(self):
        acc = self.p["access"]
        c = self.p.get("ssh_config") or {}
        lines = ["# bromigOS Server (the installer; docs/server.md): fewer guesses, shorter windows, only the people meant to"]
        lines.append("# sign in. Keys only unless a password was chosen (05-bromigos-server-password.conf).")
        if not self.has_pkg_server():
            lines += ["PermitRootLogin no"]
        for k in ("MaxAuthTries", "LoginGraceTime", "AllowGroups"):
            if c.get(k) is not None:
                lines.append(f"{k} {c[k]}")
        self.write("/etc/ssh/sshd_config.d/20-bromigos-server-limits.conf", "\n".join(lines) + "\n")
        pw = "/etc/ssh/sshd_config.d/05-bromigos-server-password.conf"
        ko = "/etc/ssh/sshd_config.d/01-bromigos-keys-only.conf"
        if acc["password_login"]:
            self.write(pw, "# bromigOS Server: password sign-in was chosen at install ([ssh] password = true)\n"
                           "PasswordAuthentication yes\nKbdInteractiveAuthentication no\n")
            if os.path.exists(self.path(ko)):
                os.unlink(self.path(ko))
        else:
            self.write(ko, "# bromigOS Server: keys only (docs/server.md)\nPasswordAuthentication no\n"
                           "KbdInteractiveAuthentication no\n")
            if os.path.exists(self.path(pw)):
                os.unlink(self.path(pw))
        self.run(["groupadd", "-f", "-r", "bromigos-ssh"])
        if acc["ssh"]:
            self.run(["systemctl", "enable", "sshd.service"])
        else:
            self.run(["systemctl", "disable", "sshd.service"])
        if acc["lab_account"]:
            self.run(["useradd", "-m", "-G", "bromigos-ssh", "-s", "/bin/bash", "-c", "the lab's provisioning", "lab"])
            self.run(["passwd", "-l", "lab"])
            self.write("/etc/sudoers.d/50-bromigos-lab", "# bromigOS Server, Lab node: the lab workstation's account "
                                                         "(docs/server.md): any command, no password\nlab ALL=(ALL) NOPASSWD: ALL\n",
                       0o440)
            self.write("/home/lab/.ssh/authorized_keys", "\n".join(acc["lab_keys"]) + "\n", 0o600)
            self.run(["chown", "-R", "lab:lab", "/home/lab/.ssh"])
            self.run(["chmod", "700", "/home/lab/.ssh"])
            say("the lab account: its key only, passwordless sudo (Lab node)")
        self.run(["passwd", "-l", "root"])
        say("sign-in: " + ("keys only" if not acc["password_login"] else "keys or the password")
            + ("" if acc["ssh"] else " (SSH off)") + "; root can't sign in")

    def firewall(self):
        rules = self.p.get("firewall_rules") or {}
        if self.has_pkg_server():
            # its own rule sets by name (server.toml's allow); the ones it doesn't have yet as rules in
            # /etc/bromigos/server/nftables.d/, which it loads after them
            known = [n for n in self.p["firewall"] if os.path.exists(self.path(f"/usr/share/bromigos/server/allow-{n}.nft"))]
            self.allow_known = known
            extra = ["# bromigOS Server's rule sets that bromigos-server doesn't carry yet (the installer; docs/server.md)"]
            for name in self.p["firewall"]:
                if name in known or name in ("ssh", "node-exporter"):
                    continue
                extra += [f"add rule inet bromigos-server input {r}" for r in self.rule_lines(name, rules.get(name) or {})]
            if len(extra) > 1:
                self.write("/etc/bromigos/server/nftables.d/50-installer.nft", "\n".join(extra) + "\n")
            say("firewall: bromigos-server's, with " + (", ".join(self.p["firewall"]) or "nothing extra"))
            return
        lines = ["#!/usr/bin/nft -f", "# bromigOS Server's firewall (the installer's, until bromigos-server is installed; docs/server.md):",
                 "# its own table, so Podman's, Docker's and k3s's rules sit beside it. In: replies, the loopback, ping, DHCP",
                 "# and what this server's role needs; the rest is dropped. Out and through are left alone.",
                 "table inet bromigos-server", "delete table inet bromigos-server", "table inet bromigos-server {",
                 "    set lan { type ipv4_addr; flags interval; elements = { " + ", ".join(LAN4) + " } }",
                 "    set lan6 { type ipv6_addr; flags interval; elements = { " + ", ".join(LAN6) + " } }",
                 "    chain input {", "        type filter hook input priority filter; policy drop;",
                 "        ct state established,related accept", "        ct state invalid drop", "        iif lo accept",
                 "        meta l4proto icmp accept", "        meta l4proto ipv6-icmp accept",
                 '        udp sport 67 udp dport 68 accept comment "DHCP"',
                 '        ip6 saddr fe80::/10 udp sport 547 udp dport 546 accept comment "DHCPv6"']
        for name in self.p["firewall"]:
            lines += ["        " + r for r in self.rule_lines(name, rules.get(name) or {})]
        lines += ["    }", "}"]
        self.write("/etc/nftables.conf", "\n".join(lines) + "\n", 0o755)
        self.run(["systemctl", "enable", "nftables.service"])
        say("firewall: " + ", ".join(self.p["firewall"]))

    @staticmethod
    def rule_lines(name, r):
        """A rule set's accept rules: the world's, or the local network's (the @lan and @lan6 sets)."""
        out = []
        for proto in ("tcp", "udp"):
            ports = r.get(proto) or []
            if not ports:
                continue
            ps = "{ " + ", ".join(str(x) for x in ports) + " }" if len(ports) > 1 else str(ports[0])
            if r.get("from", "lan") == "any":
                out.append(f'{proto} dport {ps} accept comment "{name}"')
            else:
                out.append(f'ip saddr @lan {proto} dport {ps} accept comment "{name}"')
                out.append(f'ip6 saddr @lan6 {proto} dport {ps} accept comment "{name}"')
        return out

    def hardening(self):
        sc = self.p.get("sysctl") or {}
        self.write("/etc/sysctl.d/90-bromigos-server.conf", "# bromigOS Server's defaults (the installer; docs/server.md)\n"
                   + "".join(f"{k} = {v}\n" for k, v in sorted(sc.items())))
        jd = self.p.get("journald") or {}
        self.write("/etc/systemd/journald.conf.d/90-bromigos-server.conf", "# bromigOS Server: logs survive restarts "
                   "but never fill the disk\n[Journal]\n" + "".join(f"{k}={v}\n" for k, v in jd.items()))
        if self.p.get("lsm"):
            self.grub_word(f"lsm={self.p['lsm']}", replace=r"lsm=\S+")
        say("hardening: sysctl, journald's limits, AppArmor")

    def grub_word(self, word, replace=None):
        g = self.read("/etc/default/grub")
        if not g:
            return
        m = re.search(r'^GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', g, re.M)
        if not m:
            g += f'\nGRUB_CMDLINE_LINUX_DEFAULT="{word}"\n'
        else:
            words = m.group(1).split()
            if replace:
                words = [w for w in words if not re.fullmatch(replace, w)]
            if word not in words:
                words.append(word)
            g = g[:m.start(1)] + " ".join(words) + g[m.end(1):]
        self.write("/etc/default/grub", g)

    def grub_set(self, key, value):
        g = self.read("/etc/default/grub")
        if not g:
            return
        line = f'{key}="{value}"' if value is not None else None
        if re.search(rf"^#?{key}=", g, re.M):
            g = re.sub(rf"^#?{key}=.*$", line or "", g, flags=re.M)
        elif line:
            g = g.rstrip("\n") + "\n" + line + "\n"
        self.write("/etc/default/grub", g)

    def kernel(self):
        k = self.p.get("kernel", "linux-lts")
        self.grub_set("GRUB_TOP_LEVEL", f"/boot/vmlinuz-{k}")
        self.grub_set("GRUB_DISABLE_SUBMENU", "y")
        have = [x for x in self.p.get("kernels", []) if os.path.exists(self.path(f"/boot/vmlinuz-{x}"))]
        say(f"kernel: {k} first in the boot menu" + (f", {self.p['kernels'][-1]} as the spare" if len(self.p.get('kernels', [])) > 1 else "")
            + ("" if k in have or self.dry else f" ({k} comes with the first update)"))

    def data_disks(self):
        st = self.p["storage"]
        disks = st.get("disks") or []
        if not disks:
            self.run(["install", "-d", "-m", "0755", "/srv/apps", "/srv/shares"])
            return
        root_disk = self.doc.get("disk")
        for d in disks:
            if d == root_disk:
                raise RuntimeError(f"{d} is the system's own disk; it can't also be a data disk")
        layout = st.get("layout", "single") if len(disks) >= 2 else "single"
        say(f"data disks: {' '.join(disks)}, " + ("two copies (RAID1)" if layout == "raid1" else "one copy") + ", at /srv/data")
        for d in disks:
            self.host(["wipefs", "-a", d])
        args = ["mkfs.btrfs", "-f", "-L", "bromigos-data"]
        if layout == "raid1":
            args += ["-d", "raid1", "-m", "raid1"]
        self.host(args + disks)
        self.host(["udevadm", "settle"], check=False)
        _, uuid = self.host(["blkid", "-s", "UUID", "-o", "value", disks[0]])
        uuid = uuid.strip() or "UUID-OF-THE-DATA-DISKS"
        fstab = self.read("/etc/fstab")
        if "/srv/data" not in fstab:
            fstab = fstab.rstrip("\n") + ("\n# bromigOS Server's data disks (the installer): " + ", ".join(disks) +
                                          f"\nUUID={uuid}  /srv/data  btrfs  compress=zstd,noatime,nofail,"
                                          "x-systemd.device-timeout=30s  0 0\n")
            self.write("/etc/fstab", fstab)
        mnt = self.path("/srv/data")
        os.makedirs(mnt, exist_ok=True)
        self.host(["mount", "-o", "compress=zstd", disks[0], mnt])
        try:
            for sub in ("shares", "apps", "backups"):
                self.host(["btrfs", "subvolume", "create", os.path.join(mnt, sub)])
            if st.get("timeline"):
                self.run(["snapper", "--no-dbus", "-c", "data", "create-config", "/srv/data"])
                self.run(["snapper", "--no-dbus", "-c", "data", "set-config", "TIMELINE_CREATE=yes", "TIMELINE_LIMIT_HOURLY=24",
                          "TIMELINE_LIMIT_DAILY=14", "TIMELINE_LIMIT_WEEKLY=8", "TIMELINE_LIMIT_MONTHLY=6",
                          "TIMELINE_LIMIT_YEARLY=0", "ALLOW_GROUPS=wheel"])
            self.shares(mnt)
        finally:
            self.host(["umount", mnt], check=False)

    def shares(self, mnt):
        st = self.p["storage"]
        if "smb" in st.get("shares", []):
            self.write("/etc/samba/smb.conf", SMB_CONF.format(user=self.user, lan=" ".join(LAN4)))
            pw = self.doc.get("password") or ""
            if pw:
                self.run(["smbpasswd", "-s", "-a", self.user], input=f"{pw}\n{pw}\n")
        if "nfs" in st.get("shares", []):
            ex = self.read("/etc/exports")
            if "/srv/data/shares" not in ex:
                opts = "(rw,sync,no_subtree_check,root_squash)"
                self.write("/etc/exports", ex.rstrip("\n") + ("\n" if ex.strip() else "") +
                           "# bromigOS Server's shares (the installer): the local network only\n/srv/data/shares " +
                           " ".join(f"{n}{opts}" for n in LAN4) + "\n")
        if st.get("shares"):
            self.run(["chown", f"{self.user}:{self.user}", "/srv/data/shares"])
            say("shares: " + ", ".join(x.upper() for x in st["shares"]) + " at /srv/data/shares, the local network only")

    def services(self):
        on, later = [], []
        units = list(self.p.get("services") or [])
        if self.p["storage"].get("disks"):
            units.append("btrfs-scrub@srv-data.timer")
        for u in dict.fromkeys(units):
            if self.dry or self.unit_exists(u):
                self.run(["systemctl", "enable", u])
                on.append(u)
            else:
                later.append(u)
        for u in self.p.get("off_services") or []:
            if not self.dry and self.unit_exists(u):
                self.run(["systemctl", "disable", u])
        if self.p.get("docker"):
            g = self.p.get("games") or {}
            dj = {"log-driver": "journald"}
            if g.get("registry_mirror"):
                dj["registry-mirrors"] = [g["registry_mirror"]]
            self.write("/etc/docker/daemon.json", json.dumps(dj, indent=2) + "\n")
        if later:
            self.write("/etc/bromigos/server/pending-units", "\n".join(later) + "\n")
        say(f"services on: {' '.join(on) or 'none'}" + (f"; with their packages: {' '.join(later)}" if later else ""))

    def updates(self):
        u = self.p["updates"]
        cal, delay = server.window_calendar(u["window"])
        dropin = (f"# bromigOS Server: updates inside the window chosen at install ({u['window']}, this server's time zone);\n"
                  f"# each server at its own moment in it, a restart still inside it\n[Timer]\nOnCalendar=\nOnCalendar={cal}\n"
                  f"RandomizedDelaySec={delay}\nPersistent=true\n")
        timers = ["bromigos-server-update.timer", "bromigos-auto-update.timer", "bromigos-update.timer"]
        for t in timers:
            self.write(f"/etc/systemd/system/{t}.d/10-window.conf", dropin)
        if u["mode"] == "off":
            for t in timers:
                if self.dry or self.unit_exists(t):
                    self.run(["systemctl", "disable", t])
        elif not self.has_pkg_server():
            for t in timers[1:]:
                if self.dry or self.unit_exists(t):
                    self.run(["systemctl", "enable", t])
                    break
        say(f"updates: {u['mode']}, {u['window']}" + (" (the snapshot, the health check and the rollback each time)"
                                                       if u["mode"] != "off" else ""))

    def health(self):
        d = "/etc/bromigos/server/health.d"
        for name in self.p.get("health") or []:
            body = HEALTH.get(name)
            if body:
                self.write(f"{d}/50-{name}.sh", "#!/bin/sh\n# bromigOS Server's health check, from the installer: exit 0 is "
                                                "healthy (docs/server.md)\n" + body, 0o755)
        say("health checks: " + ", ".join(self.p.get("health") or []))

    def find_my_lab(self):
        if not self.p["toggles"].get("mdns", True):
            return
        host = self.doc.get("hostname") or "bromigos-server"
        txt = "".join(f"    <txt-record>{k}={v}</txt-record>\n" for k, v in
                      (("role", self.p["role"]), ("os", "bromigos-server"), ("ssh", "22" if self.p["access"]["ssh"] else "off")))
        self.write("/etc/avahi/services/bromigos-server.service",
                   '<?xml version="1.0" standalone="no"?>\n<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
                   "<!-- bromigOS Server: Find my lab sees it (the installer; docs/server.md) -->\n<service-group>\n"
                   '  <name replace-wildcards="yes">%h</name>\n  <service>\n    <type>_bromigos-lab._tcp</type>\n'
                   f"    <port>22</port>\n{txt}  </service>\n" +
                   ("  <service>\n    <type>_ssh._tcp</type>\n    <port>22</port>\n  </service>\n" if self.p["access"]["ssh"] else "")
                   + "</service-group>\n")
        ns = self.read("/etc/nsswitch.conf")
        if ns and "mdns_minimal" not in ns:
            ns = re.sub(r"^(hosts:\s*.*?)(resolve|dns)", r"\1mdns_minimal [NOTFOUND=return] \2", ns, count=1, flags=re.M)
            self.write("/etc/nsswitch.conf", ns)
        say(f"find my lab: {host}.local announces itself")

    def unlock(self):
        mode = self.p.get("unlock")
        if mode != "tpm" or not self.doc.get("encrypt"):
            return
        say("unlock: the security chip opens the disk at each start (from the second start; the passphrase stays the spare)")
        # systemd's initramfs (sd-encrypt reads the TPM), the snapshot-booting overlay out (it needs the classic one);
        # Field Kit, in the boot menu, mends a server that won't start
        for conf in [self.path("/etc/mkinitcpio.conf")] + [os.path.join(self.path("/etc/mkinitcpio.conf.d"), f) for f in
                                                           (os.listdir(self.path("/etc/mkinitcpio.conf.d"))
                                                            if os.path.isdir(self.path("/etc/mkinitcpio.conf.d")) else [])]:
            try:
                text = open(conf).read()
            except OSError:
                continue
            m = re.search(r"^HOOKS=\(([^)]*)\)", text, re.M)
            if not m:
                continue
            hooks = m.group(1).split()
            new = []
            for h in hooks:
                h = {"udev": "systemd", "encrypt": "sd-encrypt", "keymap": "sd-vconsole", "consolefont": None,
                     "grub-btrfs-overlayfs": None, "usr": None, "resume": None}.get(h, h)
                if h and h not in new:
                    new.append(h)
            with open(conf, "w") as f:
                f.write(text[:m.start(1)] + " ".join(new) + text[m.end(1):])
        g = self.read("/etc/default/grub")
        m = re.search(r"cryptdevice=(?:PARTUUID|UUID)=([^:\s]+):(\S+)", g)
        luks = self.doc.get("luks_uuid") or ""
        if m:
            if not luks and not self.dry:
                src = _luks_device(self.t)
                luks = src and subprocess.run(["blkid", "-s", "UUID", "-o", "value", src], capture_output=True,
                                              text=True).stdout.strip()
            luks = luks or m.group(1)
            g = g.replace(m.group(0), f"rd.luks.name={luks}={m.group(2)} rd.luks.options=tpm2-device=auto")
            self.write("/etc/default/grub", g)
        pc = self.read("/etc/pacman.conf")
        if "41_snapshots-btrfs" not in pc:
            pc = re.sub(r"^\[options\]\s*$", "[options]\n# bromigOS Server with the security chip: no snapshot entries in "
                        "GRUB (systemd's initramfs can't boot them; Field Kit rolls back)\nNoExtract = etc/grub.d/41_snapshots-btrfs",
                        pc, count=1, flags=re.M)
            self.write("/etc/pacman.conf", pc)
        p41 = self.path("/etc/grub.d/41_snapshots-btrfs")
        if os.path.exists(p41):
            os.unlink(p41)
        self.run(["systemctl", "disable", "grub-btrfsd.service"])
        # the first start: the passphrase typed once, then the chip is enrolled (bound to Secure Boot's state, PCR 7)
        # with a one-time key the root holds (encrypted), which is wiped as soon as it's used
        if not self.dry:
            src = _luks_device(self.t)
            if src:
                key = self.path("/etc/bromigos/server/tpm-enroll.key")
                os.makedirs(os.path.dirname(key), exist_ok=True)
                with open(key, "wb", opener=lambda p, f: os.open(p, f, 0o400)) as f:
                    f.write(os.urandom(64))
                pw = self.doc.get("passphrase") or self.doc.get("password") or ""
                r = subprocess.run(["cryptsetup", "luksAddKey", "--key-slot", str(TPM_SLOT), "--key-file=-", src, key],
                                   input=pw, text=True, capture_output=True)
                if r.returncode != 0:
                    self.problems.append("the chip's first-start key wasn't added: " + r.stderr.strip())
        self.write("/etc/systemd/system/bromigos-server-tpm-enroll.service", TPM_UNIT)
        self.run(["systemctl", "enable", "bromigos-server-tpm-enroll.service"])
        self.run(["mkinitcpio", "-P"])

    def finish(self):
        if os.path.exists(self.path("/etc/default/grub")):
            self.run(["grub-mkconfig", "-o", "/boot/grub/grub.cfg"])
        if self.has_pkg_server():
            self.run(["bromigos-server", "setup"])

    def all(self):
        for step in (self.packages, self.firewall, self.settings, self.secrets, self.network, self.sign_in, self.hardening, self.kernel,
                     self.data_disks, self.services, self.updates, self.health, self.find_my_lab, self.unlock, self.finish):
            step()
        for p in self.problems:
            say(f"note: {p}")
        return 0


def archinstall(cfg, p, in_store, online):
    """archinstall's configuration for a server (answers.py): the kernels (linux-lts first, linux the
    spare) and the plan's packages the medium carries (all of them for an online install)."""
    ks = [k for k in p.get("kernels", []) if online or in_store(k)] or ["linux"]
    cfg["kernels"] = ks
    have = [x for x in p.get("packages", []) if (online or in_store(x)) and x not in p.get("kernels", [])]
    pk = set(cfg.get("packages", [])) | set(have)
    if p.get("docker"):
        pk.discard("podman-docker")          # Docker's own engine on this one (Pelican's Wings)
    cfg["packages"] = sorted(pk)
    return cfg


def _online():
    """Arch's mirror answers (NetworkManager's own check can say "unknown" or "limited" on a network
    that works, so the mirror itself is asked; "none" is believed)."""
    try:
        r = subprocess.run(["nmcli", "-t", "networking", "connectivity"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip() == "none":
            return False
    except (OSError, subprocess.TimeoutExpired):
        pass
    import socket
    for _ in range(3):
        try:
            socket.create_connection(("geo.mirror.pkgbuild.com", 443), timeout=8).close()
            return True
        except OSError:
            continue
    return False


def _luks_device(target):
    """The LUKS partition under the new root (/dev/mapper/root's), or None."""
    r = subprocess.run(["findmnt", "-no", "SOURCE", target], capture_output=True, text=True)
    src = re.sub(r"\[.*\]$", "", r.stdout.strip())
    if not src:
        return None
    r = subprocess.run(["cryptsetup", "status", os.path.basename(src)], capture_output=True, text=True)
    m = re.search(r"^\s*device:\s*(\S+)", r.stdout, re.M)
    return m.group(1) if m else None


SECRETS_UNIT = """# bromigOS Server: the keys and passwords typed at install, and the ones to make, put in the store chosen
# (the installer; docs/server.md): the lab's Vault, this server's new Vault, or this server's own
# encrypted credentials. The staging file is removed once they're stored.
[Unit]
Description=bromigOS Server: store the install's keys and passwords
Wants=network-online.target
After=network-online.target
ConditionPathExists=/var/lib/bromigos/secrets/staged.json

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 -c 'import json, subprocess; d = json.load(open("/var/lib/bromigos/secrets/staged.json")); [subprocess.run(["bromigos", "lab", "secrets", "set", n], input=v, text=True, check=True) for n, v in d["values"].items()]; [subprocess.run(["bromigos", "lab", "secrets", "generate", n], check=True) for n in d["generate"]]'
ExecStartPost=/usr/bin/shred -u /var/lib/bromigos/secrets/staged.json

[Install]
WantedBy=multi-user.target
"""

TPM_SLOT = 31          # the first start's one-time key (wiped once the chip is enrolled)

PENDING_UNIT = """# bromigOS Server: what the install couldn't get without a network (the installer; docs/server.md),
# installed once there is one, then the boot menu made again
[Unit]
Description=bromigOS Server: install the packages that waited for a network
Wants=network-online.target
After=network-online.target
ConditionPathExists=/etc/bromigos/server/pending-packages

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'pacman -Syu --needed --noconfirm $(cat /etc/bromigos/server/pending-packages) && rm -f /etc/bromigos/server/pending-packages && grub-mkconfig -o /boot/grub/grub.cfg && for u in $(cat /etc/bromigos/server/pending-units 2>/dev/null); do systemctl enable --now "$u" || true; done; rm -f /etc/bromigos/server/pending-units'
TimeoutStartSec=1h

[Install]
WantedBy=multi-user.target
"""

TPM_UNIT = """# bromigOS Server: the security chip enrolled at the first start, so the disk opens by itself from then on
# (the installer; docs/server.md). The one-time key it uses is wiped when it's done.
[Unit]
Description=bromigOS Server: let the security chip (TPM 2.0) unlock the disk
ConditionPathExists=/etc/bromigos/server/tpm-enroll.key
After=cryptsetup.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c 'dev=$(cryptsetup status root | sed -n "s/^ *device: *//p"); systemd-cryptenroll --unlock-key-file=/etc/bromigos/server/tpm-enroll.key --tpm2-device=auto --tpm2-pcrs=7 "$dev" && systemd-cryptenroll --unlock-key-file=/etc/bromigos/server/tpm-enroll.key --wipe-slot=31 "$dev" && shred -u /etc/bromigos/server/tpm-enroll.key'

[Install]
WantedBy=multi-user.target
"""

SMB_CONF = """# bromigOS Server's shared folders (the installer; docs/server.md): the local network only
[global]
   server role = standalone server
   workgroup = WORKGROUP
   hosts allow = {lan} 127.0.0.1
   hosts deny = 0.0.0.0/0
   server min protocol = SMB3
   map to guest = never
   vfs objects = fruit streams_xattr
   fruit:time machine = yes

[shares]
   path = /srv/data/shares
   read only = no
   valid users = {user}
   force user = {user}
"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", required=True)
    ap.add_argument("--target", default="/mnt")
    ap.add_argument("--user", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--online", choices=["yes", "no", "auto"], default="auto")
    a = ap.parse_args(argv)
    with open(a.answers) as f:
        doc = json.load(f)
    if not doc.get("server"):
        print("server_apply: these answers aren't bromigOS Server's", file=sys.stderr)
        return 0
    online = {"yes": True, "no": False}.get(a.online)
    ap_ = Apply(doc, a.target, a.user, a.dry_run, online)
    try:
        rc = ap_.all()
    except RuntimeError as e:
        print(f"::error Setting up the server stopped: {e}. Nothing on the data disks was kept half done; start the "
              "installer again and choose the disks again.", flush=True)
        return 1
    if a.dry_run:
        for c in ap_.cmds:
            print("+ " + " ".join(shlex.quote(x) for x in c))
    return rc


if __name__ == "__main__":
    sys.exit(main())
