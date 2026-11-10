"""Where the apps keep their data (`bromigos lab app-data`, docs/server.md): the status in each
case, and the move of a server's app data from its system disk to its data disks, in a
stand-in root. findmnt, mount, umount, btrfs, chattr and systemctl are stand-ins that keep a
list of what's mounted and what's running; rsync and du are the real ones, on the stand-in
root's own files. No root, nothing on this machine changes."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from bromigos_homelab import appdata

POOL_UUID, ROOT_UUID = "22222222-data", "11111111-root"
FSTAB = (f"# /dev/vda2\nUUID={ROOT_UUID}  /  btrfs  rw,subvol=/@  0 0\n"
         f"UUID={ROOT_UUID}  /srv  btrfs  rw,subvol=/@srv  0 0\n"
         "# bromigOS Server's data disks (the installer): /dev/vdb, /dev/vdc\n"
         f"UUID={POOL_UUID}  /srv/data  btrfs  compress=zstd,noatime,nofail,x-systemd.device-timeout=30s  0 0\n")
APPS_LINE = f"UUID={POOL_UUID}  /srv/apps  btrfs  subvol=/apps,compress=zstd,noatime,nofail,x-systemd.device-timeout=30s  0 0"
MEDIA_LINE, BACKUPS_LINE = (APPS_LINE.replace("apps", name) for name in ("media", "backups"))
VAULT_LINE = ("not on the data disks: passwords (Vaultwarden) keeps its data in /var/lib/vaultwarden, on the system disk; "
              "sudo bromigos lab app-data move puts it with the other apps' data")

STUBS = {
    # what's mounted: $FAKE/mounts, lines "MOUNT-POINT UUID ROOT-IN-THE-FILESYSTEM"
    "findmnt": r'''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
col = a[a.index("-o") + 1]
mode = "--target" if "--target" in a else "--mountpoint"
root = os.environ["BROMIGOS_ROOT"].rstrip("/")
path = a[a.index(mode) + 1]
path = "/" + path[len(root):].strip("/") if path.startswith(root) else path
try:
    rows = [l.split() for l in open(os.environ["FAKE"] + "/mounts") if l.strip()]
except OSError:
    rows = []
if mode == "--mountpoint":
    hit = [r for r in rows if r[0] == path]
else:
    hit = sorted((r for r in rows if path == r[0] or path.startswith(r[0].rstrip("/") + "/")), key=lambda r: len(r[0]))
if not hit:
    sys.exit(1)
print({"TARGET": hit[-1][0], "UUID": hit[-1][1], "FSROOT": hit[-1][2]}[col])
''',
    # mount PATH: as fstab says; fails while $FAKE/mount-fails is there
    "mount": r'''#!/usr/bin/env python3
import os, re, sys
fake, root = os.environ["FAKE"], os.environ["BROMIGOS_ROOT"].rstrip("/")
path = "/" + sys.argv[1][len(root):].strip("/")
open(fake + "/log", "a").write(f"mount {path}\n")
if os.path.exists(fake + "/mount-fails"):
    sys.exit("mount: wrong fs type, bad option, bad superblock")
row = next(l.split() for l in open(root + "/etc/fstab") if l.split()[1:2] == [path] and not l.startswith("#"))
sub = re.search(r"subvol=([^,]+)", row[3])
open(fake + "/mounts", "a").write(f"{path} {row[0].removeprefix('UUID=')} {sub.group(1) if sub else '/'}\n")
''',
    "umount": r'''#!/usr/bin/env python3
import os, sys
fake, root = os.environ["FAKE"], os.environ["BROMIGOS_ROOT"].rstrip("/")
path = "/" + sys.argv[1][len(root):].strip("/")
open(fake + "/log", "a").write(f"umount {path}\n")
rows = [l for l in open(fake + "/mounts") if l.split()[0] != path]
open(fake + "/mounts", "w").write("".join(rows))
''',
    # btrfs subvolume show|create PATH: a folder is a subvolume unless $FAKE/plain-folder is there
    "btrfs": r'''#!/bin/sh
echo "btrfs $*" | sed "s|$BROMIGOS_ROOT||g" >> "$FAKE/log"
case "$2" in
  show) [ -d "$3" ] && [ ! -e "$FAKE/plain-folder" ] ;;
  create) mkdir "$3" ;;
esac
''',
    "chattr": "#!/bin/sh\necho \"chattr $*\" | sed \"s|$BROMIGOS_ROOT||g\" >> \"$FAKE/log\"\n",
    "sync": "#!/bin/sh\nexit 0\n",
    "podman": "#!/bin/sh\necho '[]'\n",
    # a unit is running unless it's named in $FAKE/down; stop and start keep that list
    "systemctl": r'''#!/bin/sh
echo "systemctl $*" >> "$FAKE/log"
touch "$FAKE/down"
case "$1" in
  is-active) if grep -qx "$2" "$FAKE/down"; then echo inactive; exit 3; fi; echo active ;;
  stop) echo "$2" >> "$FAKE/down"
        # its processes go with it
        for d in "$BROMIGOS_ROOT"/proc/*/; do grep -q "/$2\$" "$d/cgroup" 2>/dev/null && rm -rf "$d"; done ;;
  start) if [ "$2" = vaultwarden.service ] && [ -e "$FAKE/vault-does-not-start" ]; then echo "Job for $2 failed" >&2; exit 1; fi
         grep -vx "$2" "$FAKE/down" > "$FAKE/down.new"; mv "$FAKE/down.new" "$FAKE/down"
         # Vaultwarden makes its database where it believes its vault is, as soon as it starts
         if [ "$2" = vaultwarden.service ] && [ -e "$FAKE/vault-starts-on-the-old-folder" ]; then
           [ -e "$BROMIGOS_ROOT/var/lib/vaultwarden/db.sqlite3" ] || echo "an empty vault" > "$BROMIGOS_ROOT/var/lib/vaultwarden/db.sqlite3"
         fi ;;
  show) echo not-found ;;
  is-enabled) echo enabled ;;
esac
exit 0
''',
    # the real rsync; with $FAKE/write-during-copy, a file changes on the system disk as the copy ends
    "rsync": r'''#!/bin/sh
echo "rsync" >> "$FAKE/log"
/usr/bin/rsync "$@"; rc=$?
case " $* " in *" --dry-run "*) exit $rc ;; esac
if [ -e "$FAKE/write-during-copy" ]; then
  to=$(cat "$FAKE/write-during-copy"); rm "$FAKE/write-during-copy"
  echo "a row written while the copy ran" >> "$BROMIGOS_ROOT/${to:-srv/apps/photos/postgres/rows}"
fi
exit $rc
''',
}


@unittest.skipUnless(shutil.which("rsync"), "rsync isn't installed")
class AppData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="bromigos-appdata-test-")
        t = Path(self.tmp.name)
        self.root, self.fake, self.bin = t / "root", t / "fake", t / "bin"
        for d in (self.root / "etc/bromigos", self.root / "srv/data", self.fake, self.bin):
            d.mkdir(parents=True)
        for name, text in STUBS.items():
            p = self.bin / name
            p.write_text(text)
            p.chmod(0o755)
        (self.root / "etc/fstab").write_text(FSTAB)
        # the stand-ins first on PATH, so nothing here can reach this machine's mount or systemctl
        env = mock.patch.dict(os.environ, {"PATH": f"{self.bin}:/usr/bin:/bin", "FAKE": str(self.fake),
                                           "BROMIGOS_ROOT": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(self.tmp.cleanup)
        settle = mock.patch.object(appdata, "SETTLE", 0)        # no waiting for a stand-in Vaultwarden
        settle.start()
        self.addCleanup(settle.stop)

    def config(self, text):
        (self.root / "etc/bromigos/server.toml").write_text(text)

    def lab(self, *args):
        """bromigos lab app-data ARGS: its exit status and what it printed."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = appdata.main(list(args))
        return types.SimpleNamespace(returncode=rc, stdout=out.getvalue(), stderr=err.getvalue())

    def log(self):
        p = self.fake / "log"
        return p.read_text() if p.exists() else ""

    # ---- a server as the installer left it before /srv/apps went on the data disks
    def server(self, apps=True, layout="raid1"):
        self.config('[health]\nminutes = 0\n[storage]\ndisks = ["/dev/vdb", "/dev/vdc"]\n'
                    f'layout = "{layout}"\nmount = "/srv/data"\n')
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n/srv/data {POOL_UUID} /\n")
        (self.root / "srv/data/apps").mkdir()                   # the pool's apps subvolume, empty
        if not apps:
            return
        db = self.root / "srv/apps/photos/postgres"
        db.mkdir(parents=True)
        (db / "rows").write_text("every photo's row\n")
        lib = self.root / "srv/apps/photos/library"
        lib.mkdir()
        (lib / "IMG_0001.jpg").write_bytes(os.urandom(4096))
        os.link(lib / "IMG_0001.jpg", lib / "IMG_0001-link.jpg")
        (lib / "private").mkdir(mode=0o700)
        (self.root / "srv/apps/documents").mkdir(mode=0o750)
        (self.root / "srv/apps/documents/scans.db").write_text("the household's papers\n")
        q = self.root / "etc/containers/systemd"
        q.mkdir(parents=True)
        (q / "immich-server.container").write_text("[Container]\nImage=x\nVolume=/srv/apps/photos/library:/data:Z\n")
        (q / "immich-database.container").write_text("[Container]\nImage=x\nVolume=/srv/apps/photos/postgres:/var/lib/postgresql/data:Z\n")
        (q / "whoami.container").write_text("[Container]\nImage=x\nPublishPort=8080:80\n")      # theirs: no app data
        (q / "bromigos-lab.network").write_text("[Network]\n")

    def tree(self, top):
        """{relative path: (mode, content or None for a folder)} under top."""
        out = {}
        for d, dirs, files in os.walk(top):
            for n in dirs + files:
                p = os.path.join(d, n)
                st = os.lstat(p)
                out[os.path.relpath(p, top)] = (oct(st.st_mode), Path(p).read_bytes() if os.path.isfile(p) else None)
        return out

    def app_data(self):
        r = self.lab("status", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def journal(self, name="app-data"):
        return json.loads((self.root / f"var/lib/bromigos/lab/{name}.json").read_text())

    def leftover(self, name="apps", under="srv"):
        return sorted(p for p in (self.root / under).iterdir() if p.name.startswith(f"{name}.on-system-disk-"))

    def media(self):
        """A media library and a backups folder as the lab's engine made them before they went on
        the data disks: folders on the system disk, a media app and a download app using one."""
        (self.root / "srv/media/movies").mkdir(parents=True)
        (self.root / "srv/media/movies/a-film.mkv").write_bytes(os.urandom(2048))
        (self.root / "srv/media/downloads").mkdir()
        (self.root / "srv/backups/data/laptop").mkdir(parents=True)
        (self.root / "srv/backups/data/laptop/config").write_text("a laptop's backup\n")
        q = self.root / "etc/containers/systemd"
        q.mkdir(parents=True, exist_ok=True)
        (q / "jellyfin.container").write_text("[Container]\nImage=x\nVolume=/srv/apps/jellyfin/config:/config:Z\nVolume=/srv/media:/media\n")
        (q / "qbittorrent.container").write_text("[Container]\nImage=x\nVolume=/srv/media/downloads:/downloads\n")

    def folder(self, path):
        return next(f for f in self.app_data()["folders"] if f["path"] == path)

    def vault(self):
        """Vaultwarden as the engine set it up before the vault had a folder under /srv/apps: the
        package's own folder on the system disk, the service running."""
        v = self.root / "var/lib/vaultwarden"
        (v / "attachments").mkdir(parents=True)
        v.chmod(0o750)
        (v / "db.sqlite3").write_text("the household's passwords\n")
        (v / "rsa_key.pem").write_text("its signing key\n")
        (v / "rsa_key.pem").chmod(0o600)
        (v / "attachments/passport.enc").write_bytes(os.urandom(1024))
        return v

    # ---- the status
    def test_no_data_disks_the_system_disk_is_where_it_belongs(self):
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")
        (self.root / "etc/fstab").write_text(FSTAB.split("# bromigOS Server's data disks")[0])
        d = self.app_data()
        self.assertEqual((d["state"], d["where"], d["pool"]), ("ok", "system", ""))
        self.assertEqual(self.lab("status").stdout, "App data: on the system disk (/srv/apps); this machine has no data disks\n")
        self.assertEqual(d["words"], ["on the system disk (/srv/apps); this machine has no data disks"])
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Nothing to move", r.stdout)

    def test_data_disks_and_the_apps_on_the_system_disk_is_said_plainly(self):
        self.server()
        d = self.app_data()
        self.assertEqual((d["state"], d["where"], d["pool"], d["raid1"]), ("not-on-pool", "system", "/srv/data", True))
        self.assertEqual(self.lab("status").stdout,
                         "App data: on the system disk, not the data disks: one copy, not two\n"
                         "          sudo bromigos lab app-data move puts it on the data disks (--dry-run shows what it would do)\n")
        # one data disk: no promise of two copies was made, and none is implied
        self.config('[storage]\ndisks = ["/dev/vdb"]\nlayout = "single"\nmount = "/srv/data"\n')
        self.assertIn("not on the disks chosen for data", self.lab().stdout)

    def test_the_passwords_vault_in_the_packages_folder_is_named_with_the_command_that_moves_it(self):
        # Vaultwarden is a package: a server set up before its vault had a folder under /srv/apps
        # has it in /var/lib, on the system disk. The status says so rather than let "on the data
        # disks" be read as all of it, and names the one command
        self.server()
        self.vault()
        d = self.app_data()
        self.assertEqual(d["elsewhere"], [{"path": "/var/lib/vaultwarden", "what": "passwords (Vaultwarden)"}])
        self.assertEqual(d["words"][-1], VAULT_LINE)
        # the package's folder with nothing in it is no vault: a server whose vault is under /srv/apps has one
        shutil.rmtree(self.root / "var/lib/vaultwarden")
        (self.root / "var/lib/vaultwarden").mkdir()
        self.assertEqual(self.app_data()["elsewhere"], [])
        # no data disks: everything is on the system disk, and there's nothing to point out or to move
        self.vault()
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")
        (self.root / "etc/fstab").write_text(FSTAB.split("# bromigOS Server's data disks")[0])
        self.config("[health]\nminutes = 0\n")
        self.assertEqual(self.app_data()["elsewhere"], [])
        before = self.tree(self.root / "var/lib/vaultwarden")
        r = self.lab("move")
        self.assertEqual((r.returncode, self.log().count("systemctl stop")), (0, 0), r.stderr)
        self.assertIn("Nothing to move", r.stdout)
        self.assertEqual(self.tree(self.root / "var/lib/vaultwarden"), before)

    def test_a_pool_made_by_hand_counts_by_its_fstab_line(self):
        self.server()
        self.config("[health]\nminutes = 0\n")                  # no [storage]: an older server.toml
        self.assertEqual(self.app_data()["state"], "not-on-pool")

    def test_the_data_disks_away_the_move_waits_for_them(self):
        # not moved yet, and the data disks aren't mounted: the apps run on, on the system disk
        self.server()
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")
        d = self.app_data()
        self.assertEqual((d["state"], d["pool_mounted"]), ("not-on-pool", False))
        self.assertEqual(d["words"][1], "the data disks aren't mounted now (/srv/data); once they are, "
                                        "sudo bromigos lab app-data move puts it on them")
        before = self.tree(self.root / "srv")
        for args in (("move",), ("move", "--dry-run")):
            r = self.lab(*args)
            self.assertEqual(r.returncode, 1)
            self.assertIn("the data disks aren't mounted", r.stderr)
        self.assertEqual((self.root / "etc/fstab").read_text(), FSTAB)
        self.assertEqual(self.tree(self.root / "srv"), before)
        self.assertEqual(self.log().count("systemctl stop"), 0)

    def test_a_server_whose_apps_are_on_the_data_disks_says_when_they_are_away(self):
        self.server(apps=False)
        (self.root / "etc/fstab").write_text(FSTAB + APPS_LINE + "\n")
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")
        d = self.app_data()
        self.assertEqual((d["state"], d["where"]), ("pool-away", "system"))
        self.assertEqual(d["words"], ["on the data disks, which aren't mounted (/srv/data): the apps can't start until they are"])
        # the pool back, its apps subvolume still not mounted: the same, and never a move
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n/srv/data {POOL_UUID} /\n")
        self.assertEqual(self.app_data()["state"], "pool-away")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("fstab mounts the data disks' apps subvolume at /srv/apps, and it isn't mounted", r.stderr)
        self.assertEqual(self.log().count("systemctl stop"), 0)

    def test_a_move_under_way_is_said_as_that(self):
        import fcntl
        self.server()
        state = self.root / "var/lib/bromigos/lab"
        state.mkdir(parents=True)
        (state / "app-data.json").write_text(json.dumps({"state": "copying", "source": "/srv/apps", "destination": "/srv/data/apps"}))
        with open(state / "app-data.json.lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            d = self.app_data()
            self.assertEqual((d["state"], d["running"], d["words"]), ("moving", True, ["moving to the data disks now (copying)"]))
            r = self.lab("move")
            self.assertEqual(r.returncode, 1)
            self.assertIn("running already", r.stderr)
        d = self.app_data()
        self.assertEqual((d["state"], d["running"]), ("moving", False))
        self.assertIn("didn't finish (copying)", d["words"][0])

    # ---- the move
    def test_dry_run_says_everything_and_changes_nothing(self):
        self.server()
        before = self.tree(self.root / "srv"), self.tree(self.root / "etc")
        r = self.lab("move", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        for words in ("would move to the data disks (/srv/data/apps,", "1. stop the apps: immich-database.service, immich-server.service",
                      "2. copy /srv/apps to /srv/data/apps", "3. compare every file with its copy, by checksum",
                      "4. keep the old copy as /srv/apps.on-system-disk-", APPS_LINE, "5. start the apps again",
                      "Nothing was changed."):
            self.assertIn(words, r.stdout)
        self.assertNotIn("whoami", r.stdout)
        self.assertEqual((self.tree(self.root / "srv"), self.tree(self.root / "etc")), before)
        self.assertFalse((self.root / "var/lib/bromigos/lab/app-data.json").exists())
        for verb in ("systemctl stop", "mount ", "chattr", "btrfs subvolume create"):
            self.assertNotIn(verb, self.log())

    def test_the_move_copies_compares_keeps_the_old_copy_and_mounts_the_pool(self):
        self.server()
        (self.fake / "down").write_text("immich-database.service\n")      # one app was stopped already: it stays stopped
        before = self.tree(self.root / "srv/apps")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        # every file, its mode and its hard link, on the data disks
        self.assertEqual(self.tree(self.root / "srv/data/apps"), before)
        lib = self.root / "srv/data/apps/photos/library"
        self.assertEqual(os.stat(lib / "IMG_0001.jpg").st_ino, os.stat(lib / "IMG_0001-link.jpg").st_ino)
        # the old copy kept whole, by a name that says what it is
        (left,) = self.leftover()
        self.assertEqual(self.tree(left), before)
        self.assertEqual(self.journal()["leftover"], f"/srv/{left.name}")
        # /srv/apps is the pool's apps subvolume now, at every start: the pool's own device and options
        fstab = (self.root / "etc/fstab").read_text()
        self.assertTrue(fstab.startswith(FSTAB), fstab)
        # (and the media library's and the backups' folders, which nothing uses yet: each its own subvolume)
        self.assertEqual([l for l in fstab[len(FSTAB):].splitlines() if not l.startswith("#")], [APPS_LINE, MEDIA_LINE, BACKUPS_LINE])
        self.assertEqual((self.root / "etc/fstab.before-app-data-move").read_text(), FSTAB)
        self.assertIn(f"/srv/apps {POOL_UUID} /apps", (self.fake / "mounts").read_text())
        self.assertEqual(os.listdir(self.root / "srv/apps"), [])                 # the mount point: empty, and kept so
        d = self.app_data()
        self.assertEqual((d["state"], d["where"], d["move"], d["leftover"]), ("ok", "pool", "done", f"/srv/{left.name}"))
        # the apps stopped before anything was read, and only those that were running start again, after the mount
        log = self.log().splitlines()
        stop, mount = log.index("systemctl stop immich-server.service"), log.index("mount /srv/apps")
        self.assertLess(log.index("systemctl stop immich-database.service"), mount)
        self.assertLess(stop, mount)
        self.assertLess(log.index("chattr +i /srv/apps"), mount)
        self.assertLess(mount, log.index("systemctl start immich-server.service"))
        self.assertNotIn("systemctl start immich-database.service", log)
        self.assertFalse([l for l in log if "whoami" in l])
        self.assertEqual(self.lab("status").stdout,
                         "App data: on the data disks (/srv/apps, their apps subvolume)\n"
                         f"          the old copy is kept at /srv/{left.name}; sudo bromigos lab app-data remove-old deletes it\n")
        # again: nothing to do, and nothing done
        (self.fake / "log").write_text("")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Nothing to move", r.stdout)
        self.assertNotIn("systemctl stop", self.log())
        # then the old copy goes, when asked
        r = self.lab("remove-old")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.leftover(), [])
        self.assertEqual(self.tree(self.root / "srv/data/apps"), before)
        self.assertEqual(self.app_data()["leftover"], "")
        self.assertIn("no old copy", self.lab("remove-old").stdout)

    def test_a_write_during_the_copy_stops_it_with_nothing_switched_and_the_next_run_finishes(self):
        self.server()
        (self.fake / "write-during-copy").write_text("")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("1 files differ from their copies", r.stderr)
        self.assertIn("The apps are running again, on the system disk as before", r.stderr)
        self.assertEqual((self.root / "etc/fstab").read_text(), FSTAB)
        self.assertEqual(self.leftover(), [])
        self.assertNotIn("mount /srv/apps", self.log())
        self.assertEqual((self.fake / "down").read_text(), "")                  # both apps started again
        self.assertEqual(self.journal()["state"], "failed")
        self.assertEqual(self.app_data()["state"], "not-on-pool")
        # the next run carries on from the copy that's there, and ends with the newest rows;
        # a photo deleted in between leaves the copy too
        os.unlink(self.root / "srv/apps/photos/library/IMG_0001-link.jpg")
        before = self.tree(self.root / "srv/apps")
        self.assertIn(b"a row written while the copy ran", before["photos/postgres/rows"][1])
        self.assertTrue((self.root / "srv/data/apps/photos/library/IMG_0001-link.jpg").exists())
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("carrying on from the copy already there", r.stdout)
        self.assertEqual(self.tree(self.root / "srv/data/apps"), before)
        self.assertEqual(self.app_data()["where"], "pool")

    def test_a_mount_that_fails_is_put_back_as_it_was(self):
        self.server()
        (self.fake / "mount-fails").write_text("")
        before = self.tree(self.root / "srv/apps")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("couldn't mount the data disks' apps subvolume at /srv/apps", r.stderr)
        self.assertIn("It was put back: the apps are running again, on the system disk as before", r.stderr)
        self.assertEqual(self.tree(self.root / "srv/apps"), before)
        self.assertEqual(self.leftover(), [])
        self.assertEqual((self.root / "etc/fstab").read_text(), FSTAB)
        self.assertEqual((self.fake / "down").read_text(), "")
        self.assertEqual(self.app_data()["state"], "not-on-pool")

    def test_a_move_cut_off_while_switching_carries_on(self):
        # the power went after fstab got its line and before the old folder was moved aside; the
        # server started again, so the pool's apps subvolume is mounted over the old folder
        self.server()
        before = self.tree(self.root / "srv/apps")
        shutil.copytree(self.root / "srv/apps", self.root / "srv/data/apps", dirs_exist_ok=True, symlinks=True)
        (self.root / "etc/fstab").write_text(FSTAB + APPS_LINE + "\n")
        (self.fake / "mounts").write_text((self.fake / "mounts").read_text() + f"/srv/apps {POOL_UUID} /apps\n")
        state = self.root / "var/lib/bromigos/lab"
        state.mkdir(parents=True)
        (state / "app-data.json").write_text(json.dumps({
            "state": "switching", "source": "/srv/apps", "pool": "/srv/data", "destination": "/srv/data/apps",
            "leftover": "/srv/apps.on-system-disk-2026-11-09", "fstab": APPS_LINE, "units": ["immich-server.service"]}))
        self.assertEqual(self.app_data()["state"], "moving")
        self.assertIn("a move to the data disks didn't finish (switching)", self.lab("status").stdout)
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.log().splitlines()
        self.assertLess(log.index("systemctl stop immich-server.service"), log.index("umount /srv/apps"))
        self.assertLess(log.index("umount /srv/apps"), log.index("mount /srv/apps"))
        self.assertEqual(self.tree(self.root / "srv/apps.on-system-disk-2026-11-09"), before)
        self.assertEqual((self.root / "etc/fstab").read_text().count("/srv/apps  btrfs"), 1)
        d = self.app_data()
        self.assertEqual((d["state"], d["where"], d["leftover"]), ("ok", "pool", "/srv/apps.on-system-disk-2026-11-09"))

    def test_cut_off_before_the_switch_took_the_apps_ran_on_and_the_copy_is_made_again(self):
        # the record says "switching", but nothing of it happened: no fstab line, the old folder
        # still where the apps look. They ran on it after the restart, so the copy on the data
        # disks is behind. It is made again and compared again before anything is switched
        self.server()
        shutil.copytree(self.root / "srv/apps", self.root / "srv/data/apps", dirs_exist_ok=True, symlinks=True)
        state = self.root / "var/lib/bromigos/lab"
        state.mkdir(parents=True)
        (state / "app-data.json").write_text(json.dumps({
            "state": "switching", "source": "/srv/apps", "pool": "/srv/data", "destination": "/srv/data/apps",
            "leftover": "/srv/apps.on-system-disk-2026-11-09", "fstab": APPS_LINE, "units": ["immich-server.service"]}))
        with open(self.root / "srv/apps/photos/postgres/rows", "a") as f:
            f.write("a row written after the restart\n")
        before = self.tree(self.root / "srv/apps")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("comparing every file with its copy", r.stdout)
        self.assertEqual(self.tree(self.root / "srv/data/apps"), before)
        self.assertIn(b"a row written after the restart", (self.root / "srv/data/apps/photos/postgres/rows").read_bytes())
        self.assertEqual(self.app_data()["where"], "pool")

    def test_a_cut_off_move_waits_for_the_data_disks(self):
        self.server()
        state = self.root / "var/lib/bromigos/lab"
        state.mkdir(parents=True)
        (state / "app-data.json").write_text(json.dumps({
            "state": "switching", "source": "/srv/apps", "pool": "/srv/data", "destination": "/srv/data/apps",
            "leftover": "/srv/apps.on-system-disk-2026-11-09", "fstab": APPS_LINE, "units": ["immich-server.service"]}))
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")       # the data disks are away
        before = self.tree(self.root / "srv")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the data disks aren't mounted (/srv/data)", r.stderr)
        self.assertEqual(self.tree(self.root / "srv"), before)
        self.assertEqual(self.log().count("systemctl stop"), 0)

    def test_files_already_in_the_pools_apps_folder_are_never_overwritten(self):
        self.server()
        (self.root / "srv/data/apps/theirs.txt").write_text("someone's own file\n")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("/srv/data/apps already has files in it (theirs.txt)", r.stderr)
        self.assertNotIn("systemctl stop", self.log())
        self.assertEqual((self.root / "srv/data/apps/theirs.txt").read_text(), "someone's own file\n")

    def test_a_host_service_is_stopped_by_its_unit_and_waits_for_the_data_disks_from_then_on(self):
        self.server()
        proc = self.root / "proc/4242"
        (proc / "fd").mkdir(parents=True)
        os.symlink("/srv/apps/file-sync", proc / "cwd")
        (proc / "cgroup").write_text("0::/system.slice/system-syncthing.slice/syncthing@syncthing.service\n")
        r = self.lab("move", "--dry-run")
        self.assertIn("1. stop the apps: immich-database.service, immich-server.service, syncthing@syncthing.service", r.stdout)
        # moved, it starts after the data disks from then on (a container's unit gets that from Quadlet)
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        drop = self.root / "etc/systemd/system/syncthing@syncthing.service.d/50-bromigos-app-data.conf"
        self.assertIn("[Unit]\nRequiresMountsFor=/srv/apps\n", drop.read_text())
        self.assertFalse((self.root / "etc/systemd/system/immich-server.service.d").exists())
        log = self.log().splitlines()
        self.assertLess(log.index("systemctl stop syncthing@syncthing.service"), log.index("mount /srv/apps"))
        self.assertLess(log.index("mount /srv/apps"), log.index("systemctl start syncthing@syncthing.service"))

    def test_a_stray_shell_stops_the_move(self):
        self.server()
        # someone's shell, in the folder: not a service to stop, so nothing is touched
        shell = self.root / "proc/4343"
        (shell / "fd").mkdir(parents=True)
        os.symlink("/srv/apps/photos", shell / "cwd")
        (shell / "cgroup").write_text("0::/user.slice/user-1000.slice/session-3.scope\n")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("In the way: process 4343 (/srv/apps/photos) is using /srv/apps", r.stdout)
        self.assertNotIn("systemctl stop", self.log())
        self.assertEqual((self.root / "etc/fstab").read_text(), FSTAB)
        # nor is a service of someone's own session: stopping the system's unit of that name wouldn't stop it
        (shell / "cgroup").write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/syncthing.service\n")
        r = self.lab("move", "--dry-run")
        self.assertEqual(r.returncode, 1)
        self.assertIn("In the way: process 4343", r.stdout)

    def test_no_app_yet_the_pool_is_mounted_for_the_first_one(self):
        self.server(apps=False)
        d = self.app_data()
        self.assertEqual((d["state"], d["has_data"]), ("not-on-pool", False))
        self.assertIn("App data: no app has data yet, and the next one's would go on the system disk, not the data disks\n"
                      "          sudo bromigos lab app-data move sets /srv/apps on the data disks", self.lab("status").stdout)
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no app has data yet", r.stdout)
        self.assertEqual(self.leftover(), [])
        self.assertIn(APPS_LINE, (self.root / "etc/fstab").read_text())
        d = self.app_data()
        self.assertEqual((d["state"], d["where"], d["leftover"]), ("ok", "pool", ""))

    def test_a_plain_folder_named_apps_becomes_a_subvolume(self):
        self.server()
        (self.fake / "plain-folder").write_text("")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("btrfs subvolume create /srv/data/apps", self.log())

    def test_the_copy_must_fit_with_room_to_spare(self):
        self.server()
        real = shutil.disk_usage
        need = appdata.tree_bytes("/srv/apps")
        for free, fits in ((need, False), (int(need * 1.05) + 1024 ** 3 - 1, False), (int(need * 1.05) + 1024 ** 3, True)):
            with mock.patch.object(appdata.shutil, "disk_usage", lambda p, free=free: real(p)._replace(free=free)):
                self.assertEqual(appdata.app_data_plan(appdata.app_data_doc())["fits"], fits, free)
                r = self.lab("move", "--dry-run")
                self.assertEqual((r.returncode, "It doesn't fit" in r.stdout), (0 if fits else 1, not fits))
        with mock.patch.object(appdata.shutil, "disk_usage", lambda p: real(p)._replace(free=need)):
            r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not enough room on the data disks; nothing was changed", r.stderr)
        self.assertNotIn("systemctl stop", self.log())

    def test_without_rsync_nothing_is_started(self):
        self.server()
        real = shutil.which
        with mock.patch.object(appdata.shutil, "which", lambda name, *a, **k: None if name == "rsync" else real(name, *a, **k)):
            r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("rsync isn't installed", r.stderr)
        self.assertNotIn("systemctl stop", self.log())

    def test_move_and_remove_old_need_root_on_a_real_machine(self):
        with mock.patch.dict(os.environ, {"BROMIGOS_ROOT": "/"}), mock.patch.object(appdata.os, "geteuid", lambda: 1000):
            for verb in ("move", "remove-old"):
                r = self.lab(verb)
                self.assertEqual(r.returncode, 1)
                self.assertIn(f"needs root: sudo bromigos lab app-data {verb}", r.stderr)

    # ---- the media library and the backups folder: on the data disks the same way
    def test_a_media_library_and_backups_on_the_system_disk_are_said_plainly(self):
        self.server()
        d = self.app_data()
        # nothing in them yet: nothing to say, and the folders are still known
        self.assertEqual([(f["path"], f["state"], f["has_data"]) for f in d["folders"]],
                         [("/srv/media", "not-on-pool", False), ("/srv/backups", "not-on-pool", False)])
        self.assertEqual(len(d["words"]), 2)
        self.media()
        d = self.app_data()
        self.assertEqual([(f["state"], f["where"], f["has_data"]) for f in d["folders"]], [("not-on-pool", "system", True)] * 2)
        self.assertEqual(d["words"][2:], [
            "the media library (/srv/media): on the system disk, not the data disks; sudo bromigos lab app-data move puts it on them",
            "the backups other machines keep here (/srv/backups): on the system disk, not the data disks; "
            "sudo bromigos lab app-data move puts it on them"])
        # no data disks: both belong on the system disk, and there's nothing to list
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")
        (self.root / "etc/fstab").write_text(FSTAB.split("# bromigOS Server's data disks")[0])
        self.config("[health]\nminutes = 0\n")
        d = self.app_data()
        self.assertEqual((d["folders"], len(d["words"])), ([], 1))

    def test_the_move_takes_the_media_library_and_the_backups_the_same_way(self):
        self.server()
        self.media()
        media, backups = self.tree(self.root / "srv/media"), self.tree(self.root / "srv/backups")
        r = self.lab("move", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        for words in ("the media library (", "would move to the data disks (/srv/data/media,", "1. stop the apps: jellyfin.service, qbittorrent.service",
                      "2. copy /srv/media to /srv/data/media", "mount the data disks' media subvolume at /srv/media:", MEDIA_LINE,
                      "the backups other machines keep here (", "2. copy /srv/backups to /srv/data/backups", BACKUPS_LINE):
            self.assertIn(words, r.stdout)
        self.assertEqual((self.root / "etc/fstab").read_text(), FSTAB)
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        # every file on the data disks, each folder in a subvolume of its own; the old copies kept by name
        self.assertEqual(self.tree(self.root / "srv/data/media"), media)
        self.assertEqual(self.tree(self.root / "srv/data/backups"), backups)
        (old_media,), (old_backups,) = self.leftover("media"), self.leftover("backups")
        self.assertEqual((self.tree(old_media), self.tree(old_backups)), (media, backups))
        self.assertIn("btrfs subvolume create /srv/data/media", self.log())
        fstab = (self.root / "etc/fstab").read_text()
        self.assertEqual([l for l in fstab[len(FSTAB):].splitlines() if not l.startswith("#")], [APPS_LINE, MEDIA_LINE, BACKUPS_LINE])
        mounts = (self.fake / "mounts").read_text()
        self.assertIn(f"/srv/media {POOL_UUID} /media", mounts)
        self.assertIn(f"/srv/backups {POOL_UUID} /backups", mounts)
        # each has a record of its own, and the status has nothing left to ask for
        self.assertEqual((self.journal("app-data-media")["state"], self.journal("app-data-backups")["state"]), ("done", "done"))
        d = self.app_data()
        self.assertEqual([(f["state"], f["where"]) for f in d["folders"]], [("ok", "pool")] * 2)
        self.assertEqual(d["words"][2:], [
            f"the media library: the old copy is kept at /srv/{old_media.name}; sudo bromigos lab app-data remove-old deletes it",
            f"the backups other machines keep here: the old copy is kept at /srv/{old_backups.name}; "
            "sudo bromigos lab app-data remove-old deletes it"])
        # the apps that use the library stopped before it was read, and started after its mount;
        # jellyfin keeps its settings under /srv/apps too, so it stopped for that move as well
        log = self.log().splitlines()
        mount = log.index("mount /srv/media")
        self.assertLess(max(i for i, l in enumerate(log[:mount]) if l == "systemctl stop qbittorrent.service"), mount)
        self.assertLess(log.index("chattr +i /srv/media"), mount)
        self.assertLess(mount, max(i for i, l in enumerate(log) if l == "systemctl start qbittorrent.service"))
        self.assertEqual((self.fake / "down").read_text(), "")
        # the old copies go together, when asked, and only they
        r = self.lab("remove-old")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.leftover() + self.leftover("media") + self.leftover("backups"), [])
        self.assertEqual(self.tree(self.root / "srv/data/media"), media)

    def test_a_media_library_on_a_nas_share_is_left_where_its_owner_put_it(self):
        self.server()
        self.media()
        unit = self.root / "etc/systemd/system/srv-media.mount"
        unit.parent.mkdir(parents=True)
        unit.write_text("[Mount]\nWhat=nas.example:/volume1/media\nWhere=/srv/media\nType=nfs\n")
        f = self.folder("/srv/media")
        self.assertEqual((f["state"], f["where"]), ("ok", "elsewhere"))
        self.assertFalse([w for w in self.app_data()["words"] if "media" in w])
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("/srv/media", (self.root / "etc/fstab").read_text())
        self.assertNotIn("mount /srv/media", self.log())
        self.assertEqual(self.leftover("media"), [])

    def test_a_media_mount_that_fails_is_put_back_and_the_apps_move_stands(self):
        self.server()
        self.media()
        media = self.tree(self.root / "srv/media")
        # the apps' data moves first and stays moved; the media library's mount fails after it
        (self.bin / "mount").write_text(STUBS["mount"].replace(
            'if os.path.exists(fake + "/mount-fails"):', 'if path == "/srv/media":'))
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("couldn't mount the data disks' media subvolume at /srv/media", r.stderr)
        self.assertIn("It was put back", r.stderr)
        self.assertEqual(self.tree(self.root / "srv/media"), media)
        self.assertEqual(self.leftover("media"), [])
        fstab = (self.root / "etc/fstab").read_text()
        self.assertEqual([l for l in fstab[len(FSTAB):].splitlines() if not l.startswith("#")], [APPS_LINE])
        self.assertIn("# the apps' data, on the data disks", fstab)           # the apps' own comment stays over its line
        self.assertNotIn("media", fstab)
        self.assertEqual((self.fake / "down").read_text(), "")
        d = self.app_data()
        self.assertEqual((d["state"], d["where"], self.folder("/srv/media")["state"], self.folder("/srv/backups")["state"]),
                         ("ok", "pool", "not-on-pool", "not-on-pool"))          # the backups weren't reached

    def test_files_already_in_the_pools_backups_folder_are_never_overwritten(self):
        # the installer always made a backups subvolume: someone may have put their own backups in it
        self.server(apps=False)
        self.media()
        (self.root / "srv/data/backups").mkdir()
        (self.root / "srv/data/backups/theirs.restic").write_text("someone's own backup\n")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("/srv/data/backups already has files in it (theirs.restic)", r.stderr)
        self.assertEqual((self.root / "srv/data/backups/theirs.restic").read_text(), "someone's own backup\n")
        self.assertNotIn("/srv/backups", (self.root / "etc/fstab").read_text())
        self.assertEqual(self.folder("/srv/backups")["state"], "not-on-pool")

    def test_a_media_library_on_the_data_disks_says_when_they_are_away(self):
        self.server(apps=False)
        (self.root / "etc/fstab").write_text(FSTAB + APPS_LINE + "\n" + MEDIA_LINE + "\n" + BACKUPS_LINE + "\n")
        (self.fake / "mounts").write_text((self.fake / "mounts").read_text() + f"/srv/apps {POOL_UUID} /apps\n/srv/backups {POOL_UUID} /backups\n")
        d = self.app_data()
        self.assertEqual([(f["state"], f["where"]) for f in d["folders"]], [("pool-away", "system"), ("ok", "pool")])
        self.assertEqual(d["words"][1:], ["the media library (/srv/media): on the data disks, which aren't mounted (/srv/data)"])
        r = self.lab("move")
        self.assertEqual(r.returncode, 1)
        self.assertIn("fstab mounts the data disks' media subvolume at /srv/media, and it isn't mounted", r.stderr)

    # ---- the passwords vault: from the package's folder to the apps'
    def on_pool(self):
        """The server after its apps' data went on the data disks: /srv/apps is their subvolume."""
        self.server(apps=False)
        (self.root / "etc/fstab").write_text(FSTAB + "\n".join((APPS_LINE, MEDIA_LINE, BACKUPS_LINE)) + "\n")
        (self.fake / "mounts").write_text((self.fake / "mounts").read_text() + "".join(
            f"/srv/{n} {POOL_UUID} /{n}\n" for n in ("apps", "media", "backups")))
        (self.root / "srv/apps").mkdir()

    def test_the_move_takes_the_vault_last_and_tells_vaultwarden_where_it_is(self):
        self.server()
        old = self.vault()
        before = self.tree(old)
        r = self.lab("move", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the passwords vault (/var/lib/vaultwarden) would move to /srv/apps/passwords once the apps' data is on the data disks", r.stdout)
        self.assertEqual(self.tree(old), before)
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        for words in ("1. stop Vaultwarden (vaultwarden.service)", "2. copy /var/lib/vaultwarden to /srv/apps/passwords",
                      "the passwords vault is with the other apps' data now (/srv/apps/passwords), and Vaultwarden is running again"):
            self.assertIn(words, r.stdout)
        # every file, mode and all, under /srv/apps; the old folder kept by name, and an empty one
        # where it was (the package's unit starts in it)
        new = self.root / "srv/apps/passwords"
        self.assertEqual(self.tree(new), before)
        self.assertEqual(os.stat(new).st_mode & 0o777, 0o750)
        (left,) = self.leftover("vaultwarden", "var/lib")
        self.assertEqual(self.tree(left), before)
        self.assertEqual((os.listdir(old), os.stat(old).st_mode & 0o777), ([], 0o750))
        # the service is told by a file read after the package's own, may write there, and waits for the data disks
        self.assertEqual((self.root / "etc/bromigos/lab/passwords.env").read_text().splitlines()[-1], "DATA_FOLDER=/srv/apps/passwords")
        drop = (self.root / "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").read_text()
        for line in ("RequiresMountsFor=/srv/apps/passwords", "ReadWritePaths=/srv/apps/passwords",
                     "EnvironmentFile=/etc/bromigos/lab/passwords.env"):
            self.assertIn(line + "\n", drop)
        # stopped before a file was read, after the apps' own move; started once everything pointed at the new folder
        log = self.log().splitlines()
        stop, start = log.index("systemctl stop vaultwarden.service"), log.index("systemctl start vaultwarden.service")
        self.assertLess(log.index("mount /srv/apps"), stop)
        self.assertLess(stop, max(i for i, l in enumerate(log) if l == "systemctl daemon-reload"))
        self.assertLess(max(i for i, l in enumerate(log[:start]) if l == "systemctl daemon-reload"), start)
        self.assertNotIn("vaultwarden.service", (self.fake / "down").read_text())
        d = self.app_data()
        self.assertEqual((d["elsewhere"], d["vault"]), ([], {"move": "done", "leftover": f"/var/lib/{left.name}"}))
        self.assertEqual(d["words"][-1], f"the passwords vault's old copy is kept at /var/lib/{left.name}; "
                                         "sudo bromigos lab app-data remove-old deletes it")
        # again: nothing to do. Then the old copies go, the vault's with the apps'
        (self.fake / "log").write_text("")
        r = self.lab("move")
        self.assertEqual((r.returncode, self.log().count("systemctl stop")), (0, 0))
        self.assertIn("Nothing to move", r.stdout)
        self.assertEqual(self.lab("remove-old").returncode, 0)
        self.assertEqual(self.leftover("vaultwarden", "var/lib") + self.leftover(), [])
        self.assertEqual(self.tree(new), before)

    def test_a_vault_that_was_stopped_stays_stopped(self):
        self.on_pool()
        self.vault()
        (self.fake / "down").write_text("vaultwarden.service\n")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("systemctl start vaultwarden.service", self.log())
        self.assertNotIn("running again", r.stdout)
        self.assertTrue((self.root / "srv/apps/passwords/db.sqlite3").exists())

    def test_vaultwarden_starting_on_the_old_folder_puts_everything_back(self):
        # the worst case: the service comes up on an empty folder, and the household sees no passwords
        self.on_pool()
        old = self.vault()
        before = self.tree(old)
        (self.fake / "vault-starts-on-the-old-folder").write_text("")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("Vaultwarden started on /var/lib/vaultwarden again, not on /srv/apps/passwords", r.stderr)
        self.assertIn("It was put back: Vaultwarden is running again, on /var/lib/vaultwarden as before", r.stderr)
        self.assertEqual(self.tree(old), before)                               # the vault, whole, where it was
        self.assertEqual(self.leftover("vaultwarden", "var/lib"), [])
        self.assertFalse((self.root / "etc/bromigos/lab/passwords.env").exists())
        self.assertFalse((self.root / "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").exists())
        # the empty vault it made is set aside by name, never deleted
        (aside,) = [p for p in (self.root / "var/lib").iterdir() if p.name.startswith("vaultwarden.started-empty-")]
        self.assertEqual((aside / "db.sqlite3").read_text(), "an empty vault\n")
        self.assertEqual(self.log().splitlines()[-1], "systemctl start vaultwarden.service")
        self.assertNotIn("vaultwarden.service", (self.fake / "down").read_text())
        d = self.app_data()
        self.assertEqual((d["vault"]["move"], d["elsewhere"][0]["path"]), ("failed", "/var/lib/vaultwarden"))
        self.assertIn("a move of it didn't finish, and sudo bromigos lab app-data move carries on", d["words"][-1])
        # put right, the next run carries on from the copy and ends with the vault under /srv/apps
        os.unlink(self.fake / "vault-starts-on-the-old-folder")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("carrying on from the copy already there", r.stdout)
        self.assertEqual(self.tree(self.root / "srv/apps/passwords"), before)

    def test_vaultwarden_not_starting_puts_everything_back(self):
        self.on_pool()
        old = self.vault()
        before = self.tree(old)
        (self.fake / "vault-does-not-start").write_text("")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("Vaultwarden didn't start on its new folder", r.stderr)
        self.assertEqual(self.tree(old), before)
        self.assertFalse((self.root / "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").exists())

    def test_a_write_to_the_vault_during_the_copy_stops_it_with_nothing_switched(self):
        self.on_pool()
        old = self.vault()
        (self.fake / "write-during-copy").write_text("var/lib/vaultwarden/db.sqlite3")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("1 files differ from their copies", r.stderr)
        self.assertIn("Vaultwarden is running again, on /var/lib/vaultwarden as before; nothing of its was changed", r.stderr)
        self.assertIn("a row written while the copy ran", (old / "db.sqlite3").read_text())
        self.assertFalse((self.root / "etc/bromigos/lab/passwords.env").exists())
        self.assertEqual(self.leftover("vaultwarden", "var/lib"), [])
        self.assertNotIn("vaultwarden.service", (self.fake / "down").read_text())

    def test_a_vault_already_under_the_apps_folder_is_never_overwritten(self):
        self.on_pool()
        old = self.vault()
        before = self.tree(old)
        (self.root / "srv/apps/passwords").mkdir()
        (self.root / "srv/apps/passwords/db.sqlite3").write_text("another vault\n")
        r = self.lab("move")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("/srv/apps/passwords already has files in it", r.stderr)
        self.assertEqual(self.log().count("systemctl stop"), 0)
        self.assertEqual((self.tree(old), (self.root / "srv/apps/passwords/db.sqlite3").read_text()), (before, "another vault\n"))

    def test_a_vault_move_cut_off_while_switching_carries_on(self):
        # the power went after the old folder was set aside and before Vaultwarden started
        self.on_pool()
        old = self.vault()
        before = self.tree(old)
        shutil.copytree(old, self.root / "srv/apps/passwords", symlinks=True)
        os.rename(old, self.root / "var/lib/vaultwarden.on-system-disk-2026-11-01")
        (self.root / "etc/systemd/system/vaultwarden.service.d").mkdir(parents=True)
        (self.root / "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").write_text(appdata.VAULT_DROPIN_TEXT)
        state = self.root / "var/lib/bromigos/lab"
        state.mkdir(parents=True)
        (state / "app-data-vaultwarden.json").write_text(json.dumps({
            "state": "switching", "source": "/var/lib/vaultwarden", "destination": "/srv/apps/passwords",
            "leftover": "/var/lib/vaultwarden.on-system-disk-2026-11-01", "was_running": True}))
        self.assertIn("it would carry on", self.lab("move", "--dry-run").stdout)
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("rsync", self.log())
        self.assertEqual((os.listdir(old), self.tree(self.root / "srv/apps/passwords")), ([], before))
        self.assertTrue((self.root / "etc/bromigos/lab/passwords.env").exists())
        log = self.log().splitlines()
        self.assertLess(log.index("systemctl daemon-reload"), log.index("systemctl start vaultwarden.service"))
        self.assertEqual(self.app_data()["vault"]["move"], "done")

    def test_cut_off_before_the_old_folder_was_set_aside_the_new_one_is_never_copied_over(self):
        # the power went right after Vaultwarden was pointed at the new folder. The server started
        # again, Vaultwarden ran on the new folder, and someone saved a password there. The old
        # folder still holds the vault as it was: carrying on must not copy it over the newer one
        self.on_pool()
        old = self.vault()
        before = self.tree(old)
        new = self.root / "srv/apps/passwords"
        shutil.copytree(old, new, symlinks=True)
        (new / "db.sqlite3").write_text("the household's passwords, and one saved since\n")
        (self.root / "etc/systemd/system/vaultwarden.service.d").mkdir(parents=True)
        (self.root / "etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf").write_text(appdata.VAULT_DROPIN_TEXT)
        state = self.root / "var/lib/bromigos/lab"
        state.mkdir(parents=True)
        (state / "app-data-vaultwarden.json").write_text(json.dumps({
            "state": "switching", "source": "/var/lib/vaultwarden", "destination": "/srv/apps/passwords",
            "leftover": "/var/lib/vaultwarden.on-system-disk-2026-11-01", "was_running": True}))
        d = self.app_data()
        self.assertEqual(d["elsewhere"], [])                    # the service uses the new folder: that is where the vault is
        self.assertEqual(d["words"][-1], "passwords (Vaultwarden): a move of its vault to /srv/apps/passwords didn't finish; "
                                         "sudo bromigos lab app-data move carries on")
        r = self.lab("move")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("rsync", self.log())
        self.assertEqual((new / "db.sqlite3").read_text(), "the household's passwords, and one saved since\n")
        self.assertEqual(self.tree(self.root / "var/lib/vaultwarden.on-system-disk-2026-11-01"), before)
        self.assertEqual(os.listdir(old), [])


if __name__ == "__main__":
    unittest.main()
