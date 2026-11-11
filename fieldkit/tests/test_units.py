"""The stick service never pulls NetworkManager in on an installed system (docs/fieldkit.md,
"Your settings on the stick"), and no other unit bromigOS ships does (docs/install.md).

systemd starts what a unit wants even when the unit's own conditions fail. So a medium-only
unit that wants NetworkManager, enabled by its package, starts NetworkManager at every boot of
every install with that package, beside the iwd or systemd-networkd that `bromigos install`
left in charge. Only the media's own overlay (iso/*/airootfs, which an install takes away) may
enable the stick service and make it wait for NetworkManager."""
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UNIT = "bromigos-fieldkit-stick.service"
PACKAGED = REPO / "fieldkit/share/systemd" / UNIT
PKGBUILD = REPO / "packaging/bromigos-fieldkit-tools/PKGBUILD"
MEDIUM_UNITS = REPO / "iso/profile/airootfs/etc/systemd/system"
BUILD = REPO / "iso/build-in-container.sh"

# what only a live medium has (an install removes it): the media's overlays, and the build that
# writes Field Kit's (it enables NetworkManager there: Field Kit's one network stack)
MEDIA = ("iso/profile/airootfs/", "iso/fieldkit/airootfs/", "iso/build-in-container.sh")
# what doesn't ship: tests, their fixtures, docs, and package builds' work folders
SKIP_DIRS = {".git", "target", "node_modules", "__pycache__", "tests", "test"}
NM = r"NetworkManager(-wait-online)?\.service"
# the dependencies that start the unit they name (After= and PartOf= don't)
PULLS = re.compile(rf"^[ \t]*(Wants|Requires|Requisite|BindsTo|Upholds)[ \t]*=.*\b{NM}", re.M)
LINKS = re.compile(rf"\.(wants|requires|upholds)/+{NM}")


def unit(path):
    """A unit file's settings: {section: {key: [values]}}, comments and blank lines left out."""
    out, section = {}, None
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = out.setdefault(line[1:-1], {})
            continue
        key, _, value = line.partition("=")
        section.setdefault(key.strip(), []).append(value.strip())
    return out


def words(values):
    return {w for v in values for w in v.split()}


def shipped(root):
    """Every file this checkout ships, relative to ROOT: git's own list where there is one,
    else a walk; never the media's overlays, the tests, the docs or a package build's src/ and
    pkg/."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
        paths = [p for p in r.stdout.decode().split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        paths = []
        for d, dirs, files in os.walk(root):
            rel = os.path.relpath(d, root)
            parts = Path(rel).parts
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS
                       and not (len(parts) == 2 and parts[0] == "packaging" and x in ("src", "pkg"))]
            paths += [os.path.normpath(os.path.join(rel, f)) for f in files]
    keep = []
    for p in paths:
        if p.startswith(MEDIA) or p.endswith(".md") or SKIP_DIRS & set(Path(p).parts[:-1]):
            continue
        keep.append(p)
    return keep


def pulls_network_manager(root):
    """Each shipped place that would start NetworkManager: a unit (or a unit written by code)
    that wants or requires it, a link in a .wants folder, a package that makes such a link."""
    bad = []
    for rel in shipped(root):
        path = os.path.join(root, rel)
        if os.path.islink(path):
            if LINKS.search(rel):
                bad.append(f"{rel}: a link that enables NetworkManager")
            continue
        try:
            if os.path.getsize(path) > 2 << 20:
                continue
            data = Path(path).read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        for m in PULLS.finditer(text):
            bad.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: {m.group(0).strip()}")
        for m in LINKS.finditer(text):
            bad.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1}: links NetworkManager into {m.group(0)}")
    return bad


class PackagedUnit(unittest.TestCase):
    def test_wants_no_network_manager(self):
        u = unit(PACKAGED)["Unit"]
        for key in ("Wants", "Requires", "Requisite", "BindsTo", "Upholds", "After"):
            self.assertFalse({w for w in words(u.get(key, [])) if "NetworkManager" in w},
                             f"{PACKAGED.name}: {key}= names NetworkManager; that belongs in the media's drop-in")

    def test_still_medium_only(self):
        u = unit(PACKAGED)["Unit"]
        self.assertIn("/run/archiso", u["ConditionPathExists"])
        self.assertIn("|/etc/bromigos-fieldkit/medium", u["ConditionPathExists"])
        self.assertEqual(u["ConditionKernelCommandLine"], ["|bromigos.fieldkit"])
        self.assertEqual(unit(PACKAGED)["Service"]["ExecStart"], ["/usr/lib/bromigos/fieldkit/fieldkit-engine stick-boot"])

    def test_package_does_not_enable_it(self):
        code = [ln for ln in PKGBUILD.read_text().splitlines() if not ln.lstrip().startswith("#")]
        self.assertFalse([ln for ln in code if ".wants" in ln],
                         "the package must not enable the stick service: an installed system would start it")
        self.assertTrue([ln for ln in code if "share/systemd/*.service" in ln], "the unit itself still ships")


class Media(unittest.TestCase):
    def test_the_full_medium_enables_it(self):
        link = MEDIUM_UNITS / "multi-user.target.wants" / UNIT
        self.assertTrue(link.is_symlink(), f"{link} is the medium's switch for the stick service")
        self.assertEqual(os.readlink(link), f"/usr/lib/systemd/system/{UNIT}")

    def test_the_drop_in_waits_for_network_manager(self):
        u = unit(MEDIUM_UNITS / f"{UNIT}.d" / "network.conf")["Unit"]
        self.assertIn("NetworkManager.service", words(u["Wants"]))
        self.assertIn("NetworkManager.service", words(u["After"]))

    def test_field_kit_gets_both(self):
        text = BUILD.read_text()
        fieldkit = text[text.index("if [[ $edition == fieldkit ]]; then"):text.index("heading=\"BROMIGOS // FIELD KIT\"")]
        self.assertIn(f"airootfs/etc/systemd/system/{UNIT}.d", fieldkit)
        self.assertIn(f"airootfs/etc/systemd/system/multi-user.target.wants/{UNIT}", fieldkit)


class NothingShippedStartsNetworkManager(unittest.TestCase):
    def test_this_checkout(self):
        self.assertEqual(pulls_network_manager(str(REPO)), [])

    def test_it_finds_them(self):
        """The scan itself: a unit, a unit in code, a package's link and a .wants link are found;
        the media's overlay, a test's fixture and After= alone are not."""
        with tempfile.TemporaryDirectory(prefix="fk-units-") as root:
            def put(rel, text):
                p = Path(root, rel)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text)
            put("fieldkit/share/systemd/a.service", "[Unit]\nAfter=NetworkManager.service\nWants=NetworkManager.service\n")
            put("server/lib/write.py", 'UNIT = """[Unit]\nRequires=foo.service NetworkManager-wait-online.service\n"""\n')
            put("packaging/x/PKGBUILD", 'ln -s /usr/lib/systemd/system/NetworkManager.service "$pkgdir/etc/systemd/system/multi-user.target.wants/NetworkManager.service"\n')
            put("server/systemd/fine.service", "[Unit]\nAfter=NetworkManager.service\nWants=network-online.target\n")
            put("iso/profile/airootfs/etc/systemd/system/x.service.d/network.conf", "[Unit]\nWants=NetworkManager.service\n")
            put("lib/tests/fixture.service", "[Unit]\nWants=NetworkManager.service\n")
            os.makedirs(Path(root, "server/systemd/multi-user.target.wants"))
            os.symlink("/usr/lib/systemd/system/NetworkManager.service", Path(root, "server/systemd/multi-user.target.wants/NetworkManager.service"))
            bad = pulls_network_manager(root)
        where = sorted(b.split(":")[0] for b in bad)
        self.assertEqual(where, ["fieldkit/share/systemd/a.service", "packaging/x/PKGBUILD",
                                 "server/lib/write.py", "server/systemd/multi-user.target.wants/NetworkManager.service"], bad)


if __name__ == "__main__":
    unittest.main()
