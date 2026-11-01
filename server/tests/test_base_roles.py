"""bromigOS Server's base (sshguard, journald, smartd, the scrub, NUT, restic, mDNS, AppArmor,
the kernel) and its roles, in a stand-in root with the stand-ins of test_server.py: the files
it ships, the role files' format, the Field Kit store, and what `role add|remove`, `backup`,
`ups`, `disk-alert`, `setup` and the health check do. No root, no network, nothing changes
on the machine running them."""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from test_server import HERE, SCRIPT, Rig, report

REPO = HERE.parent


def module():
    """bromigos-server as a module, for its small pieces (no __pycache__ left behind)."""
    sys.dont_write_bytecode = True
    loader = importlib.machinery.SourceFileLoader("bromigos_server", str(SCRIPT))
    spec = importlib.util.spec_from_loader("bromigos_server", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def store():
    """What the Field Kit stick carries for an offline install: live, edition or store."""
    sys.path.insert(0, str(REPO / "iso/fieldkit"))
    sys.dont_write_bytecode = True
    try:
        import manifest
        pkgs, _ = manifest.load()
    finally:
        sys.path.pop(0)
    return {p["name"] for p in pkgs if (p["live"] or p["edition"] or p["store"]) and not p["if_available"]}


class Files(unittest.TestCase):
    def test_hardening_sysctls(self):
        text = (HERE / "sysctl.conf").read_text()
        want = {"kernel.kptr_restrict": "2", "kernel.dmesg_restrict": "1", "kernel.unprivileged_bpf_disabled": "1",
                "net.ipv4.conf.all.accept_redirects": "0", "net.ipv4.conf.all.send_redirects": "0",
                "net.ipv4.conf.all.rp_filter": "2", "net.ipv4.tcp_syncookies": "1", "fs.protected_regular": "2"}
        got = dict(re.findall(r"^([a-z0-9_.]+) = (\S+)$", text, re.M))
        for k, v in want.items():
            self.assertEqual(got.get(k), v, k)

    def test_journal_limits(self):
        text = (HERE / "journald.conf").read_text()
        for line in ("[Journal]", "Storage=persistent", "SystemMaxUse=1G", "MaxRetentionSec=1month"):
            self.assertIn(line, text.splitlines())

    def test_ssh_limits(self):
        text = (HERE / "10-bromigos-server.conf").read_text().splitlines()
        for line in ("MaxAuthTries 3", "LoginGraceTime 30", "AllowGroups wheel bromigos-ssh"):
            self.assertIn(line, text)
        self.assertIn("g bromigos-ssh", (HERE / "bromigos-server.sysusers").read_text())

    def test_sshguard_blocks_through_nftables(self):
        conf = (HERE / "sshguard.conf").read_text()
        self.assertIn('BACKEND="/usr/lib/sshguard/sshg-fw-nft-sets"', conf)
        self.assertIn("journalctl", conf)
        dropin = (HERE / "systemd/sshguard-bromigos.conf").read_text()
        self.assertIn("BindReadOnlyPaths=/usr/share/bromigos/server/sshguard.conf:/etc/sshguard.conf", dropin)

    def test_smartd_watches_every_disk(self):
        line = (HERE / "smartd.conf").read_text().strip().splitlines()[-1]
        self.assertTrue(line.startswith("DEVICESCAN "))
        for part in ("-a", "-s (S/../.././02|L/../../6/01)", "-W 4,55,65", "-M exec /usr/lib/bromigos/server/bromigos-server-disk-alert"):
            self.assertIn(part, line)
        dropin = (HERE / "systemd/smartd-bromigos.conf").read_text()
        self.assertIn("-c /usr/share/bromigos/server/smartd.conf", dropin)
        self.assertIn("-q nodev0", dropin)

    def test_containers_update_after_the_system(self):
        text = (HERE / "systemd/podman-auto-update-bromigos.conf").read_text()
        self.assertIn("OnCalendar=\nOnCalendar=*-*-* 05:30:00", text)

    def test_backup_runs_after_the_update_window(self):
        timer = (HERE / "systemd/bromigos-server-backup.timer").read_text()
        self.assertIn("OnCalendar=*-*-* 06:00:00", timer)
        self.assertIn("bromigos-server backup run", (HERE / "systemd/bromigos-server-backup.service").read_text())
        self.assertIn("Sun", (HERE / "systemd/bromigos-server-backup-check.timer").read_text())

    def test_mdns_announcement_matches_the_labs(self):
        root = ET.parse(HERE / "bromigos-lab.service").getroot()
        self.assertEqual(root.findtext("service/type"), "_bromigos-lab._tcp")
        self.assertEqual(root.findtext("service/port"), "22")
        self.assertEqual(root.findtext("service/txt-record"), "txtvers=1")
        sys.path.insert(0, str(REPO / "homelab/lib"))
        sys.dont_write_bytecode = True
        try:
            from bromigos_homelab import announce
        finally:
            sys.path.pop(0)
        lab = announce.service_xml(22)
        self.assertIn(f">{root.findtext('name')}</name>", lab)
        self.assertIn(f"<type>{announce.SERVICE}</type>", lab)

    def test_mdns_is_let_in_from_the_local_network_only(self):
        text = (HERE / "nftables.nft").read_text()
        self.assertIn('ip saddr @lan udp dport 5353 accept', text)
        self.assertNotRegex(text, r"(?m)^\s*udp dport 5353")

    def test_shell_files_pass_shellcheck(self):
        if not shutil.which("shellcheck"):
            self.skipTest("shellcheck isn't installed")
        r = subprocess.run(["shellcheck", str(HERE / "bromigos-server-disk-alert")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


class Roles(unittest.TestCase):
    def roles(self):
        env = dict(os.environ, BROMIGOS_SERVER_ROOT=tempfile.gettempdir() + "/no-such-root", BROMIGOS_SERVER_SHARE=str(HERE))
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "roles", "--json"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "", "every role file reads cleanly")
        return json.loads(r.stdout)["roles"]

    def test_the_roles(self):
        roles = self.roles()
        self.assertEqual([r["id"] for r in roles],
                         ["lab-node", "storage", "home-services", "media", "game-server", "just-a-server", "cockpit"])
        media = next(r for r in roles if r["id"] == "media")
        self.assertEqual(media["firewall"], ["web-lan", "media"])
        self.assertIn("/etc/avahi/services/bromigos-media.service", media["files"])
        self.assertEqual({r["id"]: r["kind"] for r in roles}["cockpit"], "extra")
        game = next(r for r in roles if r["id"] == "game-server")
        wings = next(v for v in game["variants"] if v["id"] == "pelican-wings")
        self.assertEqual(wings["packages"], ["docker"])
        self.assertEqual(wings["conflicts"], ["podman-docker"])
        self.assertIn("setting:lab.pelican_panel", wings["requires"])
        self.assertFalse(wings["offline"])
        self.assertTrue(next(v for v in game["variants"] if v["default"])["offline"])
        cockpit = next(r for r in roles if r["id"] == "cockpit")
        self.assertIn("cockpit-packagekit", cockpit["conflicts"])
        self.assertNotIn("cockpit-packagekit", cockpit["packages"])

    def test_every_role_says_what_it_is_in_plain_words(self):
        for r in self.roles():
            for v in [r] + r["variants"]:
                self.assertTrue(v["title"] and v["hint"], v["id"])
                self.assertNotIn("Pterodactyl", v["hint"])
            self.assertTrue(r["summary"].endswith("."), r["id"])

    def test_offline_says_whether_the_stick_carries_it(self):
        """A role (or variant) marked offline has every package on the Field Kit stick; one
        that isn't needs at least one that the stick doesn't carry."""
        carried = store()
        for r in self.roles():
            for v in [None] + r["variants"]:
                pkgs = r["packages"] + (v["packages"] if v else [])
                offline = v["offline"] if v and v["offline"] is not None else r["offline"]
                name = r["id"] + (f"/{v['id']}" if v else "")
                if offline:
                    self.assertEqual([p for p in pkgs if p not in carried], [], name)
                else:
                    self.assertTrue([p for p in pkgs if p not in carried], name)

    def test_a_broken_role_file_is_refused(self):
        m = module()
        m.SHARE = str(HERE)
        good = tomllib.loads((HERE / "roles/storage.toml").read_text())
        self.assertEqual(m.role_problems(good, "storage.toml"), [])
        for change, word in (({"firewall": ["nope"]}, "no firewall rule set"), ({"services": ["smb"]}, "unit name"),
                             ({"colour": "red"}, "unknown key"), ({"requires": ["lab"]}, "requires"),
                             ({"files": {"/usr/x": "storage/smb.conf"}}, "under /etc"), ({"id": "Storage"}, "id")):
            bad = dict(good, **change)
            self.assertTrue(any(word in p for p in m.role_problems(bad, "storage.toml")), (change, m.role_problems(bad, "storage.toml")))

    def test_every_rule_set_loads_where_nft_can_check_it(self):
        if not (shutil.which("nft") and shutil.which("unshare")):
            self.skipTest("nft and unshare are needed")
        if subprocess.run(["unshare", "-rn", "true"], capture_output=True).returncode != 0:
            self.skipTest("no user namespaces here")
        sets = sorted(p.name[len("allow-"):-len(".nft")] for p in HERE.glob("allow-*.nft"))
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "etc/bromigos").mkdir(parents=True)
            (Path(d) / "etc/bromigos/server.toml").write_text(
                f"[firewall]\nallow = {json.dumps(sets)}\nudp = [5000]\npublic_tcp = [27015]\npublic_udp = [27015]\n")
            env = dict(os.environ, BROMIGOS_SERVER_ROOT=d, BROMIGOS_SERVER_SHARE=str(HERE))
            rules = subprocess.run([sys.executable, "-I", str(SCRIPT), "firewall", "apply", "--print"],
                                   env=env, capture_output=True, text=True, check=True).stdout
        r = subprocess.run(["unshare", "-rn", "nft", "-c", "-f", "-"], input=rules, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


class Store(unittest.TestCase):
    def test_the_base_installs_from_the_stick(self):
        """Every package bromigos-server depends on is on the stick (its own dependencies come
        with it: the store holds each package's whole closure)."""
        pkgbuild = REPO / "packaging/bromigos-server/PKGBUILD"
        names = subprocess.run(["bash", "-c", 'source "$1" >/dev/null 2>&1; printf "%s\\n" "${depends[@]}"', "_", str(pkgbuild)],
                               cwd=pkgbuild.parent, env={"startdir": str(pkgbuild.parent), "PATH": "/usr/bin:/bin"},
                               capture_output=True, text=True, check=True).stdout.split()
        carried = store()
        ours = {"bromigos-core", "bromigos-boot", "bromigos-keyring", "bromigos-fieldkit-tools", "bromigos-lab",
                "bromigos-lab-catalog", "bromigos-homelab", "bromigos-apps-terminal", "herdr", "mehshell",
                "bromigos-manual", "ttf-geist-mono", "ttf-nerd-fonts-symbols-mono", "python", "pango"}
        for n in ("sshguard", "restic", "avahi", "nss-mdns", "apparmor", "nut", "linux-lts", "smartmontools",
                  "wireguard-tools", "tailscale", "ethtool"):
            self.assertIn(n, names)
        self.assertEqual([n for n in names if n not in carried and n not in ours], [])

    def test_docker_and_cockpit_are_not_on_the_stick(self):
        carried = store()
        for n in ("docker", "cockpit", "cockpit-packagekit"):
            self.assertNotIn(n, carried)


class Apply(Rig):
    def setUp(self):
        super().setUp()
        (self.fake / "installed").write_text("podman-docker\n")

    def toml(self):
        return tomllib.loads((self.root / "etc/bromigos/server.toml").read_text())

    def test_storage_on_and_off(self):
        r = self.run_server("role", "add", "storage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("pacman -S --needed --noconfirm samba nfs-utils btrbk hdparm", self.log())
        self.assertIn(f"systemctl --root={self.root} enable smb.service nfs-server.service", self.log())
        self.assertEqual(self.toml()["roles"]["enabled"], ["storage"])
        smb = self.root / "etc/samba/smb.conf"
        self.assertIn("[global]", smb.read_text())
        rules = self.run_server("firewall", "apply", "--print").stdout
        self.assertIn("dport 445", rules)
        self.assertIn("dport 2049", rules)
        r = self.run_server("role", "remove", "storage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("disable smb.service nfs-server.service", self.log())
        self.assertFalse(smb.exists(), "an unchanged file of the role's goes with it")
        self.assertEqual(self.toml()["roles"]["enabled"], [])
        self.assertNotIn("dport 445", self.run_server("firewall", "apply", "--print").stdout)
        self.assertIn("packages stay", r.stdout)

    def test_a_file_you_changed_stays(self):
        self.run_server("role", "add", "storage")
        smb = self.root / "etc/samba/smb.conf"
        smb.write_text(smb.read_text() + "[photos]\n   path = /srv/photos\n")
        self.run_server("role", "remove", "storage")
        self.assertTrue(smb.exists())

    def test_roles_stack(self):
        self.run_server("role", "add", "storage")
        self.run_server("role", "add", "home-services")
        self.assertEqual(self.toml()["roles"]["enabled"], ["storage", "home-services"])
        d = json.loads(self.run_server("status", "--json").stdout)
        self.assertEqual(d["roles"]["titles"], ["Storage", "Home services"])
        self.assertEqual(d["firewall"]["allow"], ["smb", "nfs", "web-lan"])

    def test_wings_needs_the_labs_panel(self):
        r = self.run_server("role", "add", "game-server/pelican-wings")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pelican_panel", r.stderr)
        self.assertNotIn("pacman -S", self.log())
        self.config('[health]\nminutes = 0\n[lab]\npelican_panel = "https://panel.example"\n')
        r = self.run_server("role", "add", "game-server/pelican-wings")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.log()
        self.assertLess(log.index("pacman -R --noconfirm podman-docker"), log.index("pacman -S --needed --noconfirm docker"))
        self.assertEqual(self.toml()["roles"]["enabled"], ["game-server/pelican-wings"])
        rules = self.run_server("firewall", "apply", "--print").stdout
        self.assertIn("8080, 2022", rules)
        self.assertIn("25565", rules)
        self.assertTrue((self.root / "etc/tmpfiles.d/50-bromigos-game-server.conf").exists())

    def test_a_variant_that_fails_leaves_the_old_one_on(self):
        self.run_server("role", "add", "game-server")
        (self.fake / "unavailable").write_text("docker\n")
        self.config('[health]\nminutes = 0\n[roles]\nenabled = ["game-server"]\n[lab]\npelican_panel = "https://panel.example"\n')
        r = self.run_server("role", "add", "game-server/pelican-wings")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.toml()["roles"]["enabled"], ["game-server"])
        self.assertTrue((self.root / "etc/tmpfiles.d/50-bromigos-game-server.conf").exists())

    def test_switching_variant_replaces_it(self):
        self.config('[health]\nminutes = 0\n[lab]\npelican_panel = "https://panel.example"\n')
        self.run_server("role", "add", "game-server/pelican-wings")
        self.run_server("role", "add", "game-server")
        self.assertEqual(self.toml()["roles"]["enabled"], ["game-server"])
        self.assertIn("disable docker.service", self.log())

    def test_a_failed_install_puts_back_what_it_removed(self):
        self.config('[health]\nminutes = 0\n[lab]\npelican_panel = "https://panel.example"\n')
        (self.fake / "unavailable").write_text("docker\n")
        r = self.run_server("role", "add", "game-server/pelican-wings")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs the internet", r.stderr)
        self.assertIn("podman-docker", (self.fake / "installed").read_text())
        self.assertNotIn("[roles]", (self.root / "etc/bromigos/server.toml").read_text())

    def test_installed_packages_are_left_alone(self):
        (self.fake / "installed").write_text("caddy\n")
        self.run_server("role", "add", "home-services")
        self.assertNotIn("pacman -S", self.log())

    def test_lab_node(self):
        key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample lab@workstation"
        self.config(f'[health]\nminutes = 0\n[lab]\nssh_key = "{key}"\n')
        r = self.run_server("role", "add", "lab-node")
        self.assertEqual(r.returncode, 0, r.stderr)
        sysctl = (self.root / "etc/sysctl.d/60-bromigos-role-lab-node.conf").read_text()
        self.assertIn("fs.inotify.max_user_watches = 524288", sysctl)
        self.assertIn("net.ipv4.tcp_keepalive_time = 60", sysctl)
        self.assertIn(key, (self.root / "home/lab/.ssh/authorized_keys").read_text())
        sudo = self.root / "etc/sudoers.d/50-bromigos-lab"
        self.assertIn("lab ALL=(ALL:ALL) NOPASSWD: ALL", sudo.read_text())
        self.assertEqual(sudo.stat().st_mode & 0o777, 0o440)
        self.assertIn("6443", self.run_server("firewall", "apply", "--print").stdout)
        self.run_server("role", "remove", "lab-node")
        self.assertFalse(sudo.exists())
        self.assertFalse((self.root / "home/lab/.ssh/authorized_keys").exists())
        self.assertFalse((self.root / "etc/sysctl.d/60-bromigos-role-lab-node.conf").exists())

    def test_lab_node_refuses_a_key_that_isnt_one(self):
        self.config('[health]\nminutes = 0\n[lab]\nssh_key = "hello"\n')
        r = self.run_server("role", "add", "lab-node")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't an SSH public key", r.stderr)

    def test_unknown_role(self):
        r = self.run_server("role", "add", "minecraft")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no role 'minecraft'", r.stderr)

    def test_the_installers_picks_count_as_roles(self):
        """[roles] picked holds the installer's ids (media, home, ...): they're this package's
        roles too, and removing one takes it out of both lists."""
        self.config('[health]\nminutes = 0\n[roles]\nenabled = ["storage"]\npicked = ["storage", "media"]\n')
        d = json.loads(self.run_server("status", "--json").stdout)
        self.assertEqual(d["roles"]["enabled"], ["storage", "media"])
        self.assertEqual(d["install"]["picked"], ["storage", "media"])
        r = self.run_server("role", "remove", "media")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.toml()["roles"]["picked"], ["storage"])
        self.assertEqual(json.loads(self.run_server("status", "--json").stdout)["roles"]["enabled"], ["storage"])

    def test_media_announces_itself_and_opens_its_ports_to_the_lan(self):
        r = self.run_server("role", "add", "media")
        self.assertEqual(r.returncode, 0, r.stderr)
        svc = (self.root / "etc/avahi/services/bromigos-media.service").read_text()
        self.assertIn("<type>_bromigos-media._tcp</type>", svc)
        ET.fromstring(svc)
        rules = self.run_server("firewall", "apply", "--print").stdout
        self.assertIn("ip saddr @lan tcp dport 8096", rules)
        self.assertIn("ip saddr @lan udp dport 7359", rules)

    def test_s3_is_a_rule_set(self):
        self.run_server("firewall", "allow", "s3")
        self.assertIn("ip saddr @lan tcp dport 9000", self.run_server("firewall", "apply", "--print").stdout)

    def test_role_add_asks_the_labs_engine_for_its_items(self):
        m = module()
        calls = []
        m.ROOT, m.live = "/", lambda: True
        m.run = lambda cmd, **k: (calls.append(cmd), (0, "usage: --local --roles", "") if "--help" in cmd
                                  else (0, "added jellyfin", ""))[1]
        self.assertEqual(m.lab_provision("media"), ["the lab's engine added its items: added jellyfin"])
        self.assertIn(["bromigos", "lab", "provision", "--local", "--roles", "media", "--apply"], calls)
        m.run = lambda cmd, **k: (0, "usage: plan apply", "")
        self.assertIn("can't set up this server's apps yet", m.lab_provision("media")[0])

    def test_the_installers_choices_show_in_the_status(self):
        self.config('[health]\nminutes = 0\n[network]\ninterface = "enp1s0"\nmethod = "static"\naddress = "192.0.2.20"\n'
                    'prefix = 24\ngateway = "192.0.2.1"\nwake_on_lan = true\n[storage]\ndisks = ["/dev/sdb", "/dev/sdc"]\n'
                    'layout = "raid1"\nmount = "/srv/data"\nshares = ["smb"]\n[unlock]\nmode = "tpm"\n'
                    '[apps]\nenabled = ["jellyfin"]\n[games]\npelican_url = "https://panel.lab.example"\n'
                    '[remote]\ntailscale = false\nwireguard = false\n[packages]\npending = ["nvidia-utils"]\n')
        pend = self.root / "etc/bromigos/server/pending-packages"
        pend.parent.mkdir(parents=True, exist_ok=True)
        pend.write_text("nvidia-utils\n")
        unit = self.root / "etc/systemd/system/bromigos-server-tpm-enroll.service"
        unit.parent.mkdir(parents=True, exist_ok=True)
        unit.write_text("[Unit]\n")
        (self.fake / "units").write_text("bromigos-server-tpm-enroll.service\n")
        d = json.loads(self.run_server("status", "--json").stdout)["install"]
        self.assertEqual(d["network"]["address"], "192.0.2.20")
        self.assertEqual(d["pending_packages"], ["nvidia-utils"])
        self.assertIn("bromigos-server-tpm-enroll.service", d["first_start"])
        out = self.run_server("status").stdout
        for words in ("fixed 192.0.2.20/24", "two copies (RAID1) at /srv/data", "security chip (TPM) opens the disk",
                      "jellyfin (containers", "Pelican panel https://panel.lab.example", "Tailscale and WireGuard off",
                      "1 package(s) for a network: nvidia-utils", "First start  the security chip"):
            self.assertIn(words, out)

    def test_setup_keeps_the_installers_ssh_password_rule(self):
        f = self.root / "etc/ssh/sshd_config.d/05-bromigos-server-password.conf"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# the installer's own\nPasswordAuthentication yes\n")
        self.config("[health]\nminutes = 0\n[ssh]\npassword = false\n")
        r = self.run_server("setup")
        self.assertTrue(f.exists(), r.stdout)
        self.assertIn("the installer's own rule kept", r.stdout)
        self.config("[health]\nminutes = 0\n[ssh]\npassword = true\n")
        self.run_server("setup")
        self.assertEqual(f.read_text(), "# the installer's own\nPasswordAuthentication yes\n")

    def test_secrets_is_the_labs_store(self):
        lab = self.bin / "bromigos-lab"
        lab.write_text('#!/bin/sh\necho "bromigos-lab $*" >> "$FAKE/log"\n')
        lab.chmod(0o755)
        r = self.run_server("secrets", "rotate", "jellyfin-api-key")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("bromigos-lab secrets rotate jellyfin-api-key", self.log())

    def test_setup_applies_the_roles_the_installer_chose(self):
        self.config('[health]\nminutes = 0\n[roles]\nenabled = ["home-services", "nope"]\n')
        r = self.run_server("setup")
        self.assertIn("pacman -S --needed --noconfirm caddy", self.log())
        self.assertIn("enable caddy.service", self.log())
        self.assertIn("'nope', which isn't a role", r.stderr)


class Health(Rig):
    def update(self):
        (self.fake / "update.json").write_text(report(["bash"]))
        self.run_server("update")
        return json.loads((self.root / "var/lib/bromigos/server/update.json").read_text())

    def test_a_roles_unit_that_stopped_is_unhealthy(self):
        self.config('[health]\nminutes = 0\n[roles]\nenabled = ["storage"]\n')
        (self.fake / "down").write_text("smb.service\n")
        st = self.update()
        self.assertTrue(st["rolled_back"])
        self.assertIn("not running: smb.service", st["reason"])

    def test_units_the_lab_installs_later_count_once_they_are_there(self):
        self.config('[health]\nminutes = 0\n[roles]\nenabled = ["lab-node"]\n')
        (self.fake / "down").write_text("k3s-agent.service\n")
        self.assertEqual(self.update()["phase"], "ok")
        (self.fake / "units").write_text("k3s-agent.service\n")
        st = self.update()
        self.assertIn("not running: k3s-agent.service", st["reason"])

    def btrfs(self, errors):
        d = self.root / "sys/fs/btrfs/f00d/devinfo/1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "error_stats").write_text(f"write_errs 0\nread_errs {errors}\nflush_errs 0\ncorruption_errs 0\ngeneration_errs 0\n")

    def test_new_btrfs_errors_are_unhealthy(self):
        self.btrfs(2)
        self.assertEqual(self.update()["phase"], "ok", "errors from before the update don't count")
        (self.fake / "update.json").write_text(report(["linux"], kernel=True))
        self.run_server("update")
        self.btrfs(5)
        self.run_server("mark-boot")
        self.run_server("health")
        st = json.loads((self.root / "var/lib/bromigos/server/update.json").read_text())
        self.assertIn("3 new btrfs errors", st["reason"])
        d = json.loads(self.run_server("status", "--json").stdout)
        self.assertEqual(d["disks"]["btrfs_errors"], 5)

    def test_the_servers_own_jobs_dont_count(self):
        (self.fake / "failed").write_text("bromigos-server-backup.service loaded failed failed backup\n"
                                          "btrfs-scrub@-.service loaded failed failed scrub\n")
        self.assertEqual(self.update()["phase"], "ok")


class Setup(Rig):
    def test_boot_menu_lts_first_and_apparmor(self):
        grub = self.root / "etc/default/grub"
        grub.parent.mkdir(parents=True)
        grub.write_text('GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"\n')
        self.run_server("setup")
        text = grub.read_text()
        self.assertIn("lsm=landlock,lockdown,yama,integrity,apparmor,bpf", text)
        self.assertIn("GRUB_TOP_LEVEL=/boot/vmlinuz-linux-lts", text)
        self.assertTrue(text.startswith('GRUB_DEFAULT=0\nGRUB_CMDLINE_LINUX_DEFAULT="loglevel=3 quiet"\n'))
        self.assertIn("as it should be", self.run_server("setup").stdout)
        self.assertEqual(grub.read_text().count("# >>> bromigOS Server"), 1)
        self.config('[health]\nminutes = 0\n[boot]\nkernel = "linux"\napparmor = false\n')
        self.run_server("setup")
        text = grub.read_text()
        self.assertIn("GRUB_TOP_LEVEL=/boot/vmlinuz-linux\n", text)
        self.assertNotIn("lsm=", text)

    def test_the_block_is_valid_shell_and_adds_lsm_once(self):
        m = module()
        c = {"boot": {"kernel": "linux-lts", "apparmor": True}}
        for before in ("loglevel=3", "lsm=landlock,yama"):
            script = f'GRUB_CMDLINE_LINUX_DEFAULT="{before}"\nGRUB_CMDLINE_LINUX=""\n' + m.grub_block(c) + \
                'printf "%s|%s" "$GRUB_CMDLINE_LINUX_DEFAULT" "$GRUB_TOP_LEVEL"\n'
            out = subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=True).stdout
            self.assertEqual(out.split("|")[0].count("lsm="), 1, out)

    def test_local_names(self):
        ns = self.root / "etc/nsswitch.conf"
        ns.parent.mkdir(parents=True, exist_ok=True)
        ns.write_text("passwd: files\nhosts: mymachines resolve [!UNAVAIL=return] files myhostname dns\n")
        self.run_server("setup")
        self.assertIn("hosts: mymachines mdns_minimal [NOTFOUND=return] resolve [!UNAVAIL=return] files myhostname dns",
                      ns.read_text())
        self.run_server("setup")
        self.assertEqual(ns.read_text().count("mdns_minimal"), 1)

    def test_scrub_only_on_btrfs(self):
        m = module()
        with tempfile.TemporaryDirectory() as d:
            m.ROOT = d
            (Path(d) / "proc/self").mkdir(parents=True)
            (Path(d) / "proc/self/mountinfo").write_text("29 1 0:26 /@ / rw,relatime shared:1 - btrfs /dev/mapper/root rw\n")
            self.assertEqual(m.root_fstype(), "btrfs")
            (Path(d) / "proc/self/mountinfo").write_text("29 1 8:2 / / rw,relatime shared:1 - ext4 /dev/sda2 rw\n")
            self.assertEqual(m.root_fstype(), "ext4")

    def test_the_base_units(self):
        m = module()
        for u in ("sshguard.service", "smartd.service", "avahi-daemon.service", "apparmor.service",
                  "podman-auto-update.timer", "bromigos-server-backup.timer", "bromigos-server-backup-check.timer",
                  "bromigos-server-ups.service"):
            self.assertIn(u, m.BASE_UNITS)
        for u in m.BASE_UNITS:
            self.assertFalse(re.match(r"^(wg-quick|tailscaled|nut|cockpit)", u), u)


class Backup(Rig):
    def backup_state(self):
        return json.loads((self.root / "var/lib/bromigos/server/backup.json").read_text())

    def summary(self):
        (self.fake / "restic-backup.out").write_text(
            '{"message_type":"status","percent_done":1}\n'
            '{"message_type":"summary","snapshot_id":"1234abcd5678","total_files_processed":10,'
            '"total_bytes_processed":2048,"data_added":512}\n')

    def test_off_until_there_is_a_destination(self):
        r = self.run_server("backup", "run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("no destination", r.stdout)
        self.assertNotIn("restic", self.log())
        self.assertIn("off: no destination", self.run_server("status").stdout)

    def test_first_backup_sets_the_destination_up(self):
        self.config('[health]\nminutes = 0\n[backup]\nto = "s3:https://user:pw@s3.example/bucket/srv"\n'
                    'paths = ["/etc", "/nope"]\nenv_file = "/etc/bromigos/server/backup.env"\n')
        (self.root / "etc/bromigos/server").mkdir(parents=True)
        (self.root / "etc/bromigos/server/backup.env").write_text("AWS_ACCESS_KEY_ID=abc\n# a comment\n")
        (self.fake / "restic-cat-config.rc").write_text("10")
        self.summary()
        r = self.run_server("backup", "run")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.log()
        self.assertIn("restic init", log)
        self.assertRegex(log, r"restic backup --json --tag bromigos-server --exclude-caches .* /etc repo=s3:https://user:pw@s3.example/bucket/srv")
        self.assertNotIn("/nope", log)
        self.assertIn("id=abc", log)
        self.assertIn("restic forget --tag bromigos-server --prune --keep-daily 7 --keep-weekly 4 --keep-monthly 6", log)
        key = self.root / "etc/bromigos/server/backup.key"
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.backup_state()["run"]["snapshot"], "1234abcd")
        d = json.loads(self.run_server("status", "--json").stdout)["backup"]
        self.assertEqual(d["to"], "s3:https://s3.example/bucket/srv", "no password in the status")
        self.assertEqual(d["last"]["phase"], "ok")

    def test_a_failed_backup_says_why(self):
        self.config('[health]\nminutes = 0\n[backup]\nto = "/mnt/backup"\n')
        (self.fake / "restic-cat-config.rc").write_text("1")
        (self.fake / "restic-cat-config.err").write_text("Fatal: unable to open repository: permission denied\n")
        r = self.run_server("backup", "run")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.backup_state()["run"]["phase"], "failed")
        self.assertIn("can't be reached", self.backup_state()["run"]["reason"])
        self.assertIn("the last backup failed", self.run_server("status").stdout)

    def test_check_reads_some_data_back_when_asked(self):
        self.config('[health]\nminutes = 0\n[backup]\nto = "/mnt/backup"\n')
        self.run_server("backup", "check", "--data")
        self.assertIn("restic check --read-data-subset=5%", self.log())
        self.assertEqual(self.backup_state()["check"]["phase"], "ok")


class Ups(Rig):
    SCAN = '[nutdev1]\n\tdriver = "usbhid-ups"\n\tport = "auto"\n\tvendorid = "051D"\n\tproductid = "0002"\n\tbus = "001"\n'

    def nut(self, name):
        return (self.root / "etc/nut" / name).read_text()

    def test_no_ups_no_nut(self):
        r = self.run_server("ups", "detect")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no UPS", r.stdout)
        self.assertFalse((self.root / "etc/nut").exists())
        self.assertNotIn("nut", self.log().replace("nut-scanner", ""))

    def test_a_ups_turns_nut_on(self):
        (self.fake / "nut-scanner").write_text(self.SCAN)
        r = self.run_server("ups", "detect")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MODE=standalone", self.nut("nut.conf"))
        self.assertIn('driver = "usbhid-ups"', self.nut("ups.conf"))
        self.assertIn("LISTEN 127.0.0.1 3493", self.nut("upsd.conf"))
        self.assertRegex(self.nut("upsmon.conf"), r"MONITOR ups@localhost 1 bromigos [0-9a-f]{32} primary")
        self.assertEqual((self.root / "etc/nut/upsd.users").stat().st_mode & 0o777, 0o640)
        self.assertIn("enable nut.target nut-driver-enumerator.service nut-server.service nut-monitor.service", self.log())
        d = json.loads(self.run_server("status", "--json").stdout)
        self.assertTrue(d["ups"]["configured"])
        self.assertNotIn(re.search(r"bromigos ([0-9a-f]{32})", self.nut("upsmon.conf")).group(1),
                         json.dumps(d), "the NUT password stays out of the status")
        first = self.nut("upsd.users")
        self.run_server("ups", "detect")
        self.assertEqual(self.nut("upsd.users"), first, "a second start keeps the same password")
        # gone again: NUT off, so a missing UPS isn't a failed unit
        (self.fake / "nut-scanner").write_text("")
        self.run_server("ups", "detect")
        self.assertIn("disable nut.target", self.log())

    def test_nut_settings_changed_by_hand_are_kept(self):
        (self.root / "etc/nut").mkdir(parents=True)
        (self.root / "etc/nut/ups.conf").write_text("maxretry = 3\n[myups]\n driver = usbhid-ups\n port = auto\n")
        (self.fake / "nut-scanner").write_text(self.SCAN)
        r = self.run_server("ups", "detect")
        self.assertIn("changed by hand", r.stdout)
        self.assertIn("[myups]", self.nut("ups.conf"))
        self.assertNotIn("enable nut", self.log())


class DiskAlert(Rig):
    def test_smartd_warning_shows_in_the_status(self):
        env = dict(os.environ, PATH=f"{self.bin}:/usr/bin:/bin", FAKE=str(self.fake), BROMIGOS_SERVER_ROOT=str(self.root),
                   BROMIGOS_SERVER_SHARE=str(HERE), SMARTD_DEVICE="/dev/sda", SMARTD_DEVICESTRING="/dev/sda [SAT]",
                   SMARTD_FAILTYPE="Temperature", SMARTD_MESSAGE="Temperature 66 Celsius reached critical limit")
        r = subprocess.run([sys.executable, "-I", str(SCRIPT), "disk-alert"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.run_server("status").stdout
        self.assertIn("/dev/sda [SAT]: Temperature 66 Celsius", out)


if __name__ == "__main__":
    unittest.main()
