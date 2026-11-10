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
  start) grep -vx "$2" "$FAKE/down" > "$FAKE/down.new"; mv "$FAKE/down.new" "$FAKE/down" ;;
  show) echo not-found ;;
  is-enabled) echo enabled ;;
esac
exit 0
''',
    # the real rsync; with $FAKE/write-during-copy, a file changes on the system disk as the copy ends
    "rsync": r'''#!/bin/sh
/usr/bin/rsync "$@"; rc=$?
case " $* " in *" --dry-run "*) exit $rc ;; esac
if [ -e "$FAKE/write-during-copy" ]; then
  rm "$FAKE/write-during-copy"
  echo "a row written while the copy ran" >> "$BROMIGOS_ROOT/srv/apps/photos/postgres/rows"
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

    def journal(self):
        return json.loads((self.root / "var/lib/bromigos/lab/app-data.json").read_text())

    def leftover(self):
        return sorted(p for p in (self.root / "srv").iterdir() if p.name.startswith("apps.on-system-disk-"))

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

    def test_a_packaged_apps_data_is_named_as_not_on_the_data_disks(self):
        # Vaultwarden is a package, not a container: its data is the package's, in /var/lib on the
        # system disk, before and after a move. The status says so rather than let "on the data
        # disks" be read as all of it
        self.server()
        (self.root / "var/lib/vaultwarden").mkdir(parents=True)
        line = "not on the data disks: passwords (Vaultwarden) keeps its data in /var/lib/vaultwarden, on the system disk"
        d = self.app_data()
        self.assertEqual(d["elsewhere"], [{"path": "/var/lib/vaultwarden", "what": "passwords (Vaultwarden)"}])
        self.assertEqual(d["words"][-1], line)
        self.assertEqual(self.lab("move").returncode, 0)
        d = self.app_data()
        self.assertEqual((d["where"], d["words"][0], d["words"][-1]), ("pool", "on the data disks (/srv/apps, their apps subvolume)", line))
        self.assertTrue((self.root / "var/lib/vaultwarden").is_dir())
        # no data disks: everything is on the system disk, and there's nothing to point out
        (self.fake / "mounts").write_text(f"/ {ROOT_UUID} /@\n/srv {ROOT_UUID} /@srv\n")
        (self.root / "etc/fstab").write_text(FSTAB.split("# bromigOS Server's data disks")[0])
        self.config("[health]\nminutes = 0\n")
        self.assertEqual(self.app_data()["elsewhere"], [])

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
        self.assertEqual([l for l in fstab[len(FSTAB):].splitlines() if not l.startswith("#")], [APPS_LINE])
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


if __name__ == "__main__":
    unittest.main()
