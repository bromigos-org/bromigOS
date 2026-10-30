"""Steam and Proton (bromigos game setup, proton, check) against a fake Steam in a throwaway
home: VDF fixtures for good and bad compatibility settings, whole and broken runtimes, a
fake /etc and /proc. Nothing reaches the real Steam, its config, pacman or systemd."""
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from cmdtest import CmdTest, DESKTOP, FIXTURES, REPO

sys.path.insert(0, os.path.join(DESKTOP, "lib"))
import bromigos_gamefix as F  # noqa: E402
import bromigos_steam as S  # noqa: E402

STEAM_FX = os.path.join(FIXTURES, "steam")


def fx(name):
    with open(os.path.join(STEAM_FX, name)) as f:
        return f.read()


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def acf(appid, name, installdir, flags=4):
    return (f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n'
            f'\t"StateFlags"\t\t"{flags}"\n\t"installdir"\t\t"{installdir}"\n}}\n')


def make_steam(home, *, config="config-good.vdf", runtime="whole", flags=4, ge=True):
    """A Steam root in ~/.local/share/Steam with a second library in ~/Games, where Steam
    Linux Runtime 4 lives (whole, broken or absent), and GE-Proton99-1 in
    compatibilitytools.d, which requires it. Returns (root, second library)."""
    root = os.path.join(home, ".local", "share", "Steam")
    lib2 = os.path.join(home, "Games", "SteamLibrary")
    write(os.path.join(root, "config", "config.vdf"), fx(config))
    write(os.path.join(root, "steamapps", "libraryfolders.vdf"),
          f'"libraryfolders"\n{{\n\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t\t"apps"\n\t\t{{\n\t\t}}\n\t}}\n'
          f'\t"1"\n\t{{\n\t\t"path"\t\t"{lib2}"\n\t\t"apps"\n\t\t{{\n\t\t\t"4183110"\t\t"0"\n\t\t}}\n\t}}\n}}\n')
    os.makedirs(os.path.join(lib2, "steamapps", "common"), exist_ok=True)
    if runtime != "absent":
        write(os.path.join(lib2, "steamapps", "appmanifest_4183110.acf"),
              acf("4183110", "Steam Linux Runtime 4.0", "SteamLinuxRuntime_4", flags))
        rt = os.path.join(lib2, "steamapps", "common", "SteamLinuxRuntime_4")
        os.makedirs(os.path.join(rt, "pressure-vessel"))
        write(os.path.join(rt, "VERSIONS.txt"), "x\n")
        if runtime == "whole":
            write(os.path.join(rt, "toolmanifest.vdf"), fx("toolmanifest-runtime.vdf"))
            write(os.path.join(rt, "_v2-entry-point"), "#!/bin/sh\n")
            write(os.path.join(rt, "run"), "#!/bin/sh\n")
            write(os.path.join(rt, "pressure-vessel", "bin", "pressure-vessel-wrap"), "")
        write(os.path.join(lib2, "steamapps", "downloading", "4183110", "part"), "")
        os.makedirs(os.path.join(lib2, "steamapps", "temp", "4183110"))
    if ge:
        tool = os.path.join(root, "compatibilitytools.d", "GE-Proton99-1")
        write(os.path.join(tool, "compatibilitytool.vdf"), fx("compatibilitytool.vdf"))
        write(os.path.join(tool, "toolmanifest.vdf"), fx("toolmanifest-proton.vdf"))
        write(os.path.join(tool, "proton"), "#!/usr/bin/env python3\n")
    return root, lib2


def tool(root, name, folder=None, base=None):
    """A compatibility tool of the user's own (or, with base, a package's) named `name`."""
    d = os.path.join(base or os.path.join(root, "compatibilitytools.d"), folder or name)
    write(os.path.join(d, "compatibilitytool.vdf"), fx("compatibilitytool.vdf").replace("GE-Proton99-1", name))
    write(os.path.join(d, "toolmanifest.vdf"), fx("toolmanifest-proton.vdf"))
    write(os.path.join(d, "proton"), "#!/usr/bin/env python3\n")
    return d


TKG_OLD = "TKG-proton-experimental.bleeding.edge.7.0.36747.20230303"


def stale_machine(home, fsroot):
    """What a real install had collected: games set to TKG builds and a "Proton-GE" that are
    gone, an older GE-Proton as the default, and old builds no game uses. Beside
    make_steam's GE-Proton99-1: 99-3 (newest), 98-1 (a game's), 97-1 and a TKG build
    (unused), Luxtorpeda (another kind of tool), a package's GE-Proton96-1 and a linked
    GE-Proton95-1 (never touched)."""
    root, lib2 = make_steam(home, config="config-stale.vdf")
    for n in ("GE-Proton99-3", "GE-Proton98-1", "GE-Proton97-1", TKG_OLD, "Luxtorpeda"):
        tool(root, n)
    tool(root, "GE-Proton96-1", base=os.path.join(fsroot, "usr/share/steam/compatibilitytools.d"))
    os.symlink(tool(root, "GE-Proton95-1", base=os.path.join(home, "elsewhere")),
               os.path.join(root, "compatibilitytools.d", "GE-Proton95-1"))
    return root, lib2


class Vdf(unittest.TestCase):
    def test_nested_blocks_escapes_comments_and_first_of_repeated_keys(self):
        doc = S.parse(fx("config-good.vdf"))
        steam = doc.block("InstallConfigStore", "Software", "valve", "STEAM")   # any case
        self.assertEqual(steam.get("BaseInstallFolder_1"), "C:\\Games\\Steam")
        m = S.mapping_entries(steam.block("CompatToolMapping"))
        self.assertEqual(m["0"], {"name": "proton_experimental", "config": "", "priority": "75"})
        self.assertEqual(m["1091500"]["name"], "GE-Proton99-1")
        tools = S.parse(fx("compatibilitytool.vdf")).block("compatibilitytools", "compat_tools")
        self.assertEqual([k for k, _ in tools.items()], ["GE-Proton99-1"])       # the // comment skipped
        dup = S.parse('"a"\n{\n\t"k"\t"first"\n\t"k"\t"second"\n}\n')
        self.assertEqual(dup.block("a").get("k"), "first")
        for bad in ('"a" { "k" "v"', '"a" }', '"a" { "k" "unclosed }'):
            with self.assertRaises(S.VdfError):
                S.parse(bad)

    def test_a_change_rewrites_one_value_and_never_adds_a_second_key(self):
        text = fx("config-bad.vdf")
        zero = S.parse(text).block("InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", "0")
        new = S.set_value(text, zero, "priority", "75")
        self.assertEqual(new, fx("config-good.vdf"))      # "0" back to 75, the game's 250 kept
        self.assertEqual(new.count('"priority"'), 2)
        # set again: still one key in "0" (the vdf library's VDFDict appends a duplicate)
        again = S.set_value(new, S.parse(new).block(
            "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", "0"), "priority", "75")
        self.assertEqual(again, new)
        # a missing key goes in as the block's last line, in its indentation
        added = S.set_value(new, S.parse(new).block(
            "InstallConfigStore", "Software", "Valve", "Steam", "CompatToolMapping", "0"), "note", 'a "b" \\c')
        self.assertIn('\t\t\t\t\t\t"note"\t\t"a \\"b\\" \\\\c"\n\t\t\t\t\t}', added)
        self.assertEqual(S.parse(added).block("InstallConfigStore", "Software", "Valve", "Steam",
                                              "CompatToolMapping", "0").get("note"), 'a "b" \\c')

    def test_published_checksum_lines(self):
        h = "ab" * 64
        self.assertEqual(S.published_sha512(f"{h}  GE-Proton99-1.tar.gz\n", "GE-Proton99-1.tar.gz"), h)
        self.assertEqual(S.published_sha512(f"{h} *GE-Proton99-1.tar.gz", "GE-Proton99-1.tar.gz"), h)
        with self.assertRaises(ValueError):
            S.published_sha512(f"{h}  other.tar.gz\n", "GE-Proton99-1.tar.gz")


class Library(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = os.path.join(self.tmp, "home")
        self.enterContext(patch.object(S, "HOME", self.home))
        self.enterContext(patch.dict(os.environ, {"XDG_DATA_HOME": os.path.join(self.home, ".local/share"),
                                                  "BROMIGOS_FS_ROOT": os.path.join(self.tmp, "root")}))

    def test_libraries_runtimes_and_tools(self):
        root, lib2 = make_steam(self.home)
        self.assertEqual(S.steam_root(), root)
        self.assertEqual(S.libraries(root), [root, lib2])
        apps = S.apps(root)
        self.assertEqual(apps["4183110"].path, os.path.join(lib2, "steamapps/common/SteamLinuxRuntime_4"))
        self.assertTrue(apps["4183110"].installed and not apps["4183110"].busy)
        self.assertEqual(S.runtime_problems(apps["4183110"]), [])
        [ge] = S.custom_tools(root)
        self.assertEqual((ge.name, ge.kind, ge.requires), ("GE-Proton99-1", "user", "4183110"))

    def test_a_broken_runtime_says_what_is_missing(self):
        root, _ = make_steam(self.home, runtime="broken")
        problems = S.runtime_problems(S.apps(root)["4183110"])
        self.assertEqual(problems, ["toolmanifest.vdf is missing", "_v2-entry-point is missing",
                                    "pressure-vessel/ is empty"])

    def test_an_updating_runtime_is_busy(self):
        root, _ = make_steam(self.home, flags=4 | 2 | 1024)
        self.assertTrue(S.apps(root)["4183110"].busy)

    def test_steam_running_from_proc(self):
        proc = os.path.join(self.tmp, "root", "proc")
        write(os.path.join(proc, "100", "comm"), "kitty\n")
        self.assertIsNone(S.steam_running())
        write(os.path.join(proc, "4242", "comm"), "steam\n")
        self.assertEqual(S.steam_running(), 4242)

    def test_extract_refuses_anything_outside_the_release_folder(self):
        for name in ("GE-Proton99-1/../evil", "evil", "/abs"):
            tar = os.path.join(self.tmp, "t.tar.gz")
            with tarfile.open(tar, "w:gz") as t:
                for n, data in (("GE-Proton99-1/proton", b"x"), (name, b"y")):
                    info = tarfile.TarInfo(n)
                    info.size = len(data)
                    t.addfile(info, io.BytesIO(data))
            dest = os.path.join(self.tmp, "out")
            with self.assertRaises((ValueError, tarfile.TarError)):
                S.extract(tar, dest, "GE-Proton99-1")
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil")))


class Upkeep(unittest.TestCase):
    """What bromigOS keeps right by itself (bromigos_gamefix): the plan, and applying it."""

    def setUp(self):
        self.tmp = os.path.realpath(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = os.path.join(self.tmp, "home")
        self.fsroot = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.fsroot, "proc"))
        self.enterContext(patch.object(S, "HOME", self.home))
        self.enterContext(patch.dict(os.environ, {"XDG_DATA_HOME": os.path.join(self.home, ".local/share"),
                                                  "XDG_STATE_HOME": os.path.join(self.home, ".local/state"),
                                                  "BROMIGOS_FS_ROOT": self.fsroot}))

    def config(self, root):
        with open(S.config_path(root)) as f:
            return f.read()

    def test_the_plan_for_a_machine_with_years_of_leftovers(self):
        root, _ = stale_machine(self.home, self.fsroot)
        p = F.plan(root)
        self.assertEqual((p["newest_ge"], p["fallback_ge"]), ("GE-Proton99-3", "GE-Proton99-1"))
        self.assertEqual(p["default"], {"from": "GE-Proton99-1", "to": "GE-Proton99-3"})
        self.assertFalse(p["priority"])
        # gone TKG, "Proton-GE" and another tool: the default (now the newest GE) again;
        # Steam's own proton_9, a game's installed GE-Proton98-1 and an empty name stay
        self.assertEqual([(m["appid"], m["from"], m["to"]) for m in p["mapping"]],
                         [("100", "TKG-proton-experimental.bleeding.edge.8.0.41901.20230428", None),
                          ("200", "Proton-GE", None), ("600", "Luxtorpeda-Gone", None)])
        # unused GE and TKG builds go; the newest two, a game's, other tools, a package's and
        # a linked folder stay
        self.assertEqual(sorted(t["name"] for t in p["prune"]), ["GE-Proton97-1", TKG_OLD])
        self.assertTrue(F.changes(p))

    def test_apply_edits_only_those_entries_backs_up_and_moves_aside(self):
        root, _ = stale_machine(self.home, self.fsroot)
        before = self.config(root)
        did = F.apply(root, F.plan(root), log=lambda _l: None)
        self.assertEqual(self.config(root), fx("config-stale-fixed.vdf"), "byte for byte, the rest as Steam wrote it")
        backups = os.path.join(self.home, ".local/state/bromigos/game/backup")
        [stamp] = os.listdir(backups)
        with open(os.path.join(backups, stamp, "config.vdf")) as f:
            self.assertEqual(f.read(), before)
        compat = os.path.join(root, "compatibilitytools.d")
        self.assertEqual(sorted(os.listdir(compat)), sorted(["GE-Proton99-1", "GE-Proton99-3", "GE-Proton98-1",
                                                             "Luxtorpeda", "GE-Proton95-1"]))
        [stamp] = os.listdir(os.path.join(root, "bromigos-backup"))
        self.assertEqual(sorted(os.listdir(os.path.join(root, "bromigos-backup", stamp, "compatibilitytools.d"))),
                         sorted(["GE-Proton97-1", TKG_OLD]))
        self.assertTrue(os.path.isdir(os.path.join(self.fsroot, "usr/share/steam/compatibilitytools.d/GE-Proton96-1")))
        self.assertTrue(any("follows the default again" in d for d in did), did)
        self.assertFalse(F.changes(F.plan(root)), "a second run has nothing to do")

    def test_a_choice_of_another_tool_stays_and_its_games_get_ge(self):
        root, _ = make_steam(self.home, config="config-missing-tool.vdf")
        p = F.plan(root)
        self.assertIsNone(p["default"], "Proton Experimental chosen by the user stays")
        self.assertEqual([(m["from"], m["to"]) for m in p["mapping"]], [("GE-Proton1-1", "GE-Proton99-1")])
        F.apply(root, p, log=lambda _l: None)
        m = S.mapping_entries(S.compat_mapping(root)[2])
        self.assertEqual((m["0"]["name"], m["1091500"]["name"], m["1091500"]["priority"]),
                         ("proton_experimental", "GE-Proton99-1", "250"))

    def test_without_ge_a_missing_default_becomes_proton_experimental(self):
        root, _ = make_steam(self.home, ge=False)
        write(S.config_path(root), fx("config-good.vdf").replace('"proton_experimental"', '"Proton-GE"'))
        p = F.plan(root)
        self.assertEqual(p["default"], {"from": "Proton-GE", "to": "proton_experimental"})
        self.assertEqual([(m["from"], m["to"]) for m in p["mapping"]], [("GE-Proton99-1", None)])
        self.assertEqual(p["prune"], [], "nothing is pruned without a GE-Proton to keep")
        F.apply(root, p, log=lambda _l: None)
        self.assertEqual(S.mapping_entries(S.compat_mapping(root)[2]),
                         {"0": {"name": "proton_experimental", "config": "", "priority": "75"}})

    def test_no_default_or_no_mapping_at_all_gets_one(self):
        root, _ = make_steam(self.home)
        text = fx("config-good.vdf")
        start = text.index('\t\t\t\t"CompatToolMapping"')
        end = text.index('\t\t\t\t"BaseInstallFolder_1"')
        write(S.config_path(root), text[:start] + text[end:])
        F.apply(root, F.plan(root), log=lambda _l: None)
        out = self.config(root)
        self.assertIn('\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n\t\t\t\t\t"0"\n\t\t\t\t\t{\n'
                      '\t\t\t\t\t\t"name"\t\t"GE-Proton99-1"\n', out)
        self.assertEqual(S.mapping_entries(S.compat_mapping(root)[2])["0"],
                         {"name": "GE-Proton99-1", "config": "", "priority": "75"})
        # "0" missing from a mapping that has games: added beside them
        write(S.config_path(root), fx("config-good.vdf").replace('"0"', '"7"'))
        F.apply(root, F.plan(root), log=lambda _l: None)
        m = S.mapping_entries(S.compat_mapping(root)[2])
        self.assertEqual((m["0"]["name"], m["7"]["name"]), ("GE-Proton99-1", "proton_experimental"))

    def test_nothing_changes_while_steam_runs(self):
        root, _ = stale_machine(self.home, self.fsroot)
        write(os.path.join(self.fsroot, "proc", "4242", "comm"), "steamwebhelper\n")
        before = self.config(root)
        with self.assertRaises(F.SteamRunning):
            F.apply(root, F.plan(root), log=lambda _l: None)
        self.assertEqual(self.config(root), before)
        self.assertTrue(os.path.isdir(os.path.join(root, "compatibilitytools.d", "GE-Proton97-1")))

    def test_old_backups_go_after_two_weeks(self):
        root, lib2 = make_steam(self.home)
        for d in ("20200101-000000", "notes"):
            os.makedirs(os.path.join(lib2, "bromigos-backup", d))
        fresh = S.stamp()
        os.makedirs(os.path.join(root, "bromigos-backup", fresh))
        gone = F.expire(root)
        self.assertEqual(len(gone), 1)
        self.assertEqual(sorted(os.listdir(os.path.join(lib2, "bromigos-backup"))), ["notes"])
        self.assertEqual(os.listdir(os.path.join(root, "bromigos-backup")), [fresh])

    def test_ge_versions_compare_across_naming_schemes(self):
        order = ["Proton-6.21-GE-2", "GE-Proton7-43", "GE-Proton7-55", "GE-Proton10-25", "GE-Proton11-11-x86_64"]
        self.assertEqual(sorted(order, key=S.ge_version), order)
        self.assertTrue(S.is_ge("Proton-GE") and not S.ge_version("Proton-GE"))
        self.assertTrue(S.steam_own("proton_experimental") and not S.steam_own("proton_tkg_9"))
        self.assertTrue(S.is_tkg(TKG_OLD) and not S.is_ge(TKG_OLD))

    def test_readiness_in_plain_words(self):
        def doc(*findings, **kw):
            return dict({"steam_installed": True, "steam_root": "/s", "steam_running": False,
                         "proton": {"default": "GE-Proton99-3", "display": "GE-Proton99-3"},
                         "findings": list(findings)}, **kw)
        r = F.readiness(doc({"check": "runtime", "level": "ok", "title": "x", "auto": False}))
        self.assertEqual((r["ready"], r["headline"], r["proton"]), (True, "Games are ready", "GE-Proton99-3"))
        auto = {"check": "mapping", "level": "warn", "title": "Game 1 is set to X", "auto": True, "fixable": "mapping"}
        need = {"check": "initramfs", "level": "problem", "title": "mkinitcpio's MODULES names nvidia-open",
                "auto": False, "fixable": None}
        sddm = {"check": "login", "level": "warn", "title": "/etc/sddm.conf.d/x only repeats", "auto": False,
                "fixable": "sddm"}
        r = F.readiness(doc(auto, need, sddm, steam_running=True))
        self.assertFalse(r["ready"])
        self.assertEqual(r["headline"], "1 thing needs you")
        self.assertEqual([f["title"] for f in r["needs_you"]], [need["title"]])
        self.assertEqual([f["title"] for f in r["handled"]], [auto["title"], sddm["title"]])
        self.assertTrue(r["fixable"] and r["root"])
        self.assertIn("when Steam closes", r["detail"])
        r = F.readiness(doc(steam_installed=False, steam_root=None, proton=None))
        self.assertEqual((r["headline"], r["setup"]), ("Steam isn't installed", True))


class Commands(CmdTest):
    def setUp(self):
        super().setUp()
        self.fsroot = os.path.join(self.tmp, "root")
        write(os.path.join(self.fsroot, "etc", "mkinitcpio.conf"),
              "MODULES=(btrfs nvidia nvidia_modeset nvidia_uvm nvidia_drm)\nHOOKS=(base udev)\n")
        os.makedirs(os.path.join(self.fsroot, "etc", "sddm.conf.d"))
        # the login screen's own settings, as bromigos-settings installs them
        write(os.path.join(self.fsroot, "usr/lib/sddm/sddm.conf.d/zz-bromigos.conf"),
              open(os.path.join(REPO, "settings/sddm/conf/zz-bromigos.conf")).read())
        os.makedirs(os.path.join(self.fsroot, "proc"))
        self.bin = os.path.join(self.tmp, "bin")
        write(os.path.join(self.bin, "systemctl"),
              '#!/bin/sh\necho "$@" >> "$BROMIGOS_FIXTURE_STATE/systemctl.calls"\n'
              'rm -f "$XDG_CONFIG_HOME"/systemd/user/*.wants/waybar.service\n')
        os.chmod(os.path.join(self.bin, "systemctl"), 0o755)
        self.env.update(BROMIGOS_FS_ROOT=self.fsroot, PATH=self.bin + ":" + self.env["PATH"])

    def hw(self, gpus, multilib=True, packages=(), hyprland_changed=False):
        with open(os.path.join(self.fx, "hw.json"), "w") as f:
            json.dump({"detection": {"gpus": gpus, "multilib": multilib},
                       "plan": {"want": {"packages": list(packages)}, "hyprland_changed": hyprland_changed}}, f)

    def check(self, *args, env=None):
        import subprocess
        r = subprocess.run([os.path.join(DESKTOP, "bin", "bromigos-game-check"), *args, "--json"],
                           env=dict(self.env, **(env or {})), capture_output=True, text=True, timeout=60)
        doc = json.loads(r.stdout)
        return r.returncode, doc, {(f["check"], f["level"]) for f in doc["findings"]}

    def steam_runs(self):
        write(os.path.join(self.fsroot, "proc", "4242", "comm"), "steam\n")

    # ---------------------------------------------------------------- check

    def test_a_healthy_machine_passes(self):
        make_steam(self.home)
        rc, doc, seen = self.check()
        self.assertEqual(rc, 0, doc)
        self.assertTrue(doc["healthy"])
        for c in ("runtime", "default", "login", "bar", "initramfs"):
            self.assertIn((c, "ok"), seen)
        self.assertFalse([f for f in doc["findings"] if f["level"] in ("warn", "problem")], doc)

    def test_everything_that_broke_games_is_found(self):
        root, lib2 = make_steam(self.home, config="config-bad.vdf", runtime="broken")
        etc = os.path.join(self.fsroot, "etc")
        write(os.path.join(etc, "sddm.conf.d", "10-old.conf.disabled"), "[General]\nDisplayServer=x11\n")
        write(os.path.join(etc, "sddm.conf.d", "20-theme.conf"), "[Theme]\nCurrent=breeze\n")
        write(os.path.join(etc, "sddm.conf.d", "30-autologin.conf"), "[Autologin]\nUser=someone\n")
        write(os.path.join(etc, "mkinitcpio.conf"), "# MODULES=(ignored)\nMODULES=(btrfs nvidia-open nvidia_drm)\n")
        wants = self.path(".config/systemd/user/graphical-session.target.wants")
        os.makedirs(wants)
        os.symlink("/usr/lib/systemd/user/waybar.service", os.path.join(wants, "waybar.service"))
        rc, doc, seen = self.check()
        self.assertEqual(rc, 1)
        self.assertFalse(doc["healthy"])
        by = {}
        for f in doc["findings"]:
            by.setdefault(f["check"], []).append(f)
        [rt] = [f for f in by["runtime"] if f["level"] == "problem"]
        self.assertIn("Steam Linux Runtime 4.0 is broken", rt["title"])
        self.assertIn("_v2-entry-point is missing", rt["detail"])
        self.assertEqual(rt["fixable"], "runtime")
        [d] = by["default"]
        self.assertEqual((d["level"], d["fixable"], d["auto"]), ("problem", "default", True))
        self.assertIn("priority 250, not 75", d["title"])
        login = {f["title"]: f["level"] for f in by["login"]}
        self.assertEqual(login, {"/etc/sddm.conf.d/10-old.conf.disabled is still read by the login screen": "problem",
                                 "/etc/sddm.conf.d/20-theme.conf changes bromigOS's login screen": "warn",
                                 "/etc/sddm.conf.d/30-autologin.conf adds login settings of its own": "info"})
        theme = next(f for f in by["login"] if "20-theme" in f["title"])
        self.assertIn("[Theme] Current=breeze (bromigOS: bromigos)", theme["detail"])
        self.assertEqual([(f["level"], f["fixable"]) for f in by["bar"]], [("problem", "bar")])
        [mk] = by["initramfs"]
        self.assertEqual(mk["level"], "problem")
        self.assertIn("Replace nvidia-open with nvidia in /etc/mkinitcpio.conf", mk["fix"])
        self.assertIn("sudo mkinitcpio -P", mk["fix"])

    def test_missing_runtime_and_a_game_set_to_a_removed_proton_are_warnings(self):
        make_steam(self.home, config="config-missing-tool.vdf", runtime="absent")
        rc, doc, seen = self.check()
        self.assertEqual(rc, 0, doc)                       # warnings: nothing stops the desktop
        by = {f["check"]: f for f in doc["findings"] if f["level"] != "ok"}
        # a Proton's runtime: Steam installs it on Play, so it's only a note
        self.assertEqual(by["required"]["level"], "info")
        self.assertIn("GE-Proton99-1 needs Steam Linux Runtime 4.0, which Steam installs on Play", by["required"]["title"])
        # the game: bromigOS gives it the newest GE-Proton (the default is the user's Proton Experimental)
        m = by["mapping"]
        self.assertEqual((m["level"], m["fixable"], m["auto"]), ("info", "mapping", True))   # not installed
        self.assertIn("A game that isn't installed (Steam app 1091500) is set to GE-Proton1-1", m["title"])
        self.assertIn("bromigOS sets it to GE-Proton99-1", m["detail"])
        self.assertIn("next time Steam closes", m["fix"])
        self.assertEqual(doc["proton"]["default"], "proton_experimental")
        self.assertIn(("default", "ok"), seen)
        # an installed game set to it is worth a line in Settings (bromigOS fixes it)
        write(os.path.join(self.home, ".local/share/Steam/steamapps/appmanifest_1091500.acf"),
              acf("1091500", "Cyberpunk 2077", "Cyberpunk 2077"))
        _, doc, _ = self.check()
        [m] = [f for f in doc["findings"] if f["check"] == "mapping"]
        self.assertEqual((m["level"], m["title"]), ("warn", "Cyberpunk 2077 is set to GE-Proton1-1, which isn't "
                                                            "installed"))

    def test_an_updating_runtime_is_left_alone(self):
        make_steam(self.home, runtime="broken", flags=4 | 1024)
        rc, doc, seen = self.check()
        self.assertEqual(rc, 0)
        self.assertIn(("runtime", "info"), seen)

    def test_fix_waits_for_steam_to_close_then_repairs_with_backups(self):
        root, lib2 = make_steam(self.home, config="config-bad.vdf", runtime="broken")
        before = fx("config-bad.vdf")
        self.steam_runs()
        rc, doc, _ = self.check("--fix")
        self.assertEqual(rc, 1)
        self.assertTrue(any("Steam is running" in d for d in doc["fixed"]), doc["fixed"])
        with open(os.path.join(root, "config", "config.vdf")) as f:
            self.assertEqual(f.read(), before, "nothing changes while Steam runs")
        self.assertTrue(os.path.isdir(os.path.join(lib2, "steamapps/common/SteamLinuxRuntime_4")))

        shutil.rmtree(os.path.join(self.fsroot, "proc", "4242"))
        rc, doc, seen = self.check("--fix")
        self.assertEqual(rc, 0, doc)
        with open(os.path.join(root, "config", "config.vdf")) as f:
            after = f.read()
        # one value changed, the rest byte for byte; the per-game 250 stays
        self.assertEqual(after, before.replace('"priority"\t\t"250"', '"priority"\t\t"75"', 1))
        backups = os.listdir(os.path.join(self.home, ".local/state/bromigos/game/backup"))
        with open(os.path.join(self.home, ".local/state/bromigos/game/backup", backups[0], "config.vdf")) as f:
            self.assertEqual(f.read(), before)
        # the runtime and its leftovers moved aside within the library, so Steam reinstalls it
        for rel in ("steamapps/common/SteamLinuxRuntime_4", "steamapps/downloading/4183110",
                    "steamapps/temp/4183110", "steamapps/appmanifest_4183110.acf"):
            self.assertFalse(os.path.exists(os.path.join(lib2, rel)), rel)
        [stamp] = os.listdir(os.path.join(lib2, "bromigos-backup"))
        self.assertTrue(os.path.isfile(os.path.join(lib2, "bromigos-backup", stamp, "steamapps/appmanifest_4183110.acf")))
        self.assertIn(("required", "info"), seen)          # now Steam installs it on Play

    def test_fix_disables_the_users_waybar_service_only(self):
        os.makedirs(self.path(".config/systemd/user/default.target.wants"))
        os.symlink("/usr/lib/systemd/user/waybar.service", self.path(".config/systemd/user/default.target.wants/waybar.service"))
        write(os.path.join(self.fsroot, "etc/sddm.conf.d/old.bak"), "")
        rc, doc, seen = self.check("--fix")
        with open(os.path.join(self.fx, "systemctl.calls")) as f:
            self.assertEqual(f.read(), "--user disable waybar.service\n")
        self.assertIn(("bar", "ok"), seen)
        self.assertIn(("steam", "info"), seen)            # no Steam here: said, not a problem
        self.assertTrue(os.path.exists(os.path.join(self.fsroot, "etc/sddm.conf.d/old.bak")), "never /etc")
        self.assertIn(("login", "ok"), seen)               # an empty file sets nothing
        self.assertEqual(rc, 0)

    def test_nvapi_on_nvidia(self):
        self.hw([{"vendor": "NVIDIA", "driver": "nvidia", "id": "10de:2f04"}])
        _, doc, seen = self.check()
        [f] = [f for f in doc["findings"] if f["check"] == "nvapi"]
        self.assertEqual(f["level"], "warn")
        self.assertIn("bromigos hw setup --user-only", f["fix"])
        write(self.path(".local/state/bromigos/hw/hyprland.lua"), '{ "PROTON_ENABLE_NVAPI", "1" }')
        _, doc, _ = self.check()
        self.assertIn("Log out and back in", [f for f in doc["findings"] if f["check"] == "nvapi"][0]["fix"])
        _, _, seen = self.check(env={"PROTON_ENABLE_NVAPI": "1"})
        self.assertIn(("nvapi", "ok"), seen)
        self.hw([{"vendor": "AMD", "driver": "amdgpu"}])
        _, _, seen = self.check()
        self.assertFalse([s for s in seen if s[0] == "nvapi"])

    # ---------------------------------------------------------------- proton

    def release(self, tag, *, corrupt=False, members=None, arch=None):
        """A recorded GitHub release in a folder (file:// addresses): one build named after
        the tag, as older releases have, or per architecture (arch: GE-Proton11-11-x86_64)."""
        top = f"{tag}-{arch}" if arch else tag
        rel = os.path.join(self.tmp, "releases")
        files = os.path.join(rel, "files")
        os.makedirs(os.path.join(rel, "tags"), exist_ok=True)
        os.makedirs(files, exist_ok=True)
        tar = os.path.join(files, f"{top}.tar.gz")
        with tarfile.open(tar, "w:gz") as t:
            for n, data in members or ((f"{top}/compatibilitytool.vdf", fx("compatibilitytool.vdf").replace("GE-Proton99-1", tag)),
                                       (f"{top}/toolmanifest.vdf", fx("toolmanifest-proton.vdf")),
                                       (f"{top}/proton", "#!/usr/bin/env python3\n")):
                b = data.encode()
                info = tarfile.TarInfo(n)
                info.size, info.mode = len(b), 0o755
                t.addfile(info, io.BytesIO(b))
        with open(tar, "rb") as f:
            h = hashlib.sha512(f.read()).hexdigest()
        if corrupt:
            h = "0" * 128
        write(os.path.join(files, f"{top}.sha512sum"), f"{h}  {top}.tar.gz\n")
        doc = {"tag_name": tag, "assets": [
            {"name": f"{top}.tar.gz", "browser_download_url": "file://" + tar, "size": os.path.getsize(tar)},
            {"name": f"{top}.sha512sum", "browser_download_url": "file://" + os.path.join(files, f"{top}.sha512sum")}]}
        if arch:                                   # the other architecture's build, never taken
            doc["assets"] += [{"name": f"{tag}-other.tar.gz", "browser_download_url": "file:///nonexistent"},
                              {"name": f"{tag}-other.sha512sum", "browser_download_url": "file:///nonexistent"}]
        for p in (os.path.join(rel, "latest"), os.path.join(rel, "tags", tag)):
            write(p, json.dumps(doc))
        self.env["BROMIGOS_PROTON_RELEASES"] = "file://" + rel

    def test_proton_install_verifies_the_checksum_and_lists_it(self):
        root, _ = make_steam(self.home)
        arch = S.machine()
        self.release("GE-Proton99-2", arch=arch)
        doc = self.cmd("game-proton", "install")
        self.assertEqual(doc["installed"], "GE-Proton99-2")
        tool = os.path.join(root, "compatibilitytools.d", f"GE-Proton99-2-{arch}")
        self.assertTrue(os.access(os.path.join(tool, "proton"), os.X_OK))
        self.assertEqual(sorted(os.listdir(os.path.join(root, "compatibilitytools.d"))),
                         ["GE-Proton99-1", f"GE-Proton99-2-{arch}"], "no partial download left behind")
        names = {t["name"]: t for t in self.cmd("game-proton")["tools"]}
        self.assertEqual(names["GE-Proton99-1"]["games"], ["1091500"])
        self.assertEqual(names["GE-Proton99-2"]["runtime"], {"appid": "4183110", "name": "Steam Linux Runtime 4.0",
                                                             "installed": True})
        self.assertIn("installed already", self.cmd("game-proton", "install", "GE-Proton99-2")["said"])

    def test_a_bad_checksum_or_archive_installs_nothing(self):
        root, _ = make_steam(self.home)
        self.release("GE-Proton99-3", corrupt=True)
        doc = self.cmd("game-proton", "install", ok=False)
        self.assertIn("doesn't match its published SHA-512", doc["error"])
        self.release("GE-Proton99-4", members=(("GE-Proton99-4/x", "y"), ("../evil", "z")))
        doc = self.cmd("game-proton", "install", "GE-Proton99-4", ok=False)
        self.assertIn("couldn't be unpacked safely", doc["error"])
        self.assertEqual(os.listdir(os.path.join(root, "compatibilitytools.d")), ["GE-Proton99-1"])
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local/share/Steam/evil")))
        doc = self.cmd("game-proton", "install", "../../etc", ok=False)
        self.assertIn("isn't a GE-Proton version", doc["error"])

    def test_proton_remove_waits_for_steam_and_keeps_tools_games_use(self):
        root, _ = make_steam(self.home)
        self.steam_runs()
        self.assertIn("Steam is running", self.cmd("game-proton", "remove", "GE-Proton99-1", ok=False)["error"])
        shutil.rmtree(os.path.join(self.fsroot, "proc", "4242"))
        self.assertIn("is set for 1 game", self.cmd("game-proton", "remove", "GE-Proton99-1", ok=False)["error"])
        self.assertIn("isn't one of your", self.cmd("game-proton", "remove", "proton_9", ok=False)["error"])
        self.cmd("game-proton", "remove", "GE-Proton99-1", "--force")
        self.assertEqual(os.listdir(os.path.join(root, "compatibilitytools.d")), [])

    def test_no_steam_yet(self):
        self.assertIn("Steam hasn't run here yet", self.cmd("game-proton", ok=False)["error"])


    # ---------------------------------------------------------------- upkeep (game maintain)

    def maintain(self, *args, ok=True):
        return self.cmd("game-maintain", *args, ok=ok,
                        env={"BROMIGOS_GAME_POLL": "0.05", "BROMIGOS_GAME_SETTLE": "0.3"})

    def tree(self, root):
        out = []
        for d, dirs, files in os.walk(root):
            out += [os.path.relpath(os.path.join(d, f), root) for f in files]
        return sorted(out)

    def test_maintain_waits_for_steam_to_exit_then_repairs(self):
        import subprocess
        root, _ = stale_machine(self.home, self.fsroot)
        before = fx("config-stale.vdf")
        self.steam_runs()
        doc = self.maintain("--no-download")
        self.assertTrue(doc["waiting"])
        self.assertEqual(doc["done"], [])
        self.assertIn("Steam is running", doc["said"])
        with open(S.config_path(root)) as f:
            self.assertEqual(f.read(), before, "nothing changes while Steam runs")
        # the service's way: --wait holds until Steam has exited and stayed closed
        env = dict(self.env, BROMIGOS_GAME_POLL="0.05", BROMIGOS_GAME_SETTLE="0.3")
        proc = subprocess.Popen([os.path.join(DESKTOP, "bin", "bromigos-game-maintain"), "--wait", "--no-download",
                                 "--json"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import time
            time.sleep(1.0)
            self.assertIsNone(proc.poll(), "still waiting while Steam runs")
            with open(S.config_path(root)) as f:
                self.assertEqual(f.read(), before)
            shutil.rmtree(os.path.join(self.fsroot, "proc", "4242"))
            out, err = proc.communicate(timeout=30)
        finally:
            if proc.poll() is None:
                proc.kill()
        doc = json.loads(out)
        self.assertTrue(doc["ok"], err)
        self.assertFalse(doc["waiting"])
        with open(S.config_path(root)) as f:
            self.assertEqual(f.read(), fx("config-stale-fixed.vdf"))
        self.assertIn("Steam is running: waiting for it to exit.", err)
        self.assertFalse(os.path.exists(os.path.join(root, "compatibilitytools.d", "GE-Proton97-1")))

    def test_maintain_installs_the_latest_ge_makes_it_default_and_prunes(self):
        root, _ = stale_machine(self.home, self.fsroot)
        self.release("GE-Proton99-4")
        doc = self.maintain("--refresh")
        self.assertTrue(any("Installed GE-Proton99-4" in d for d in doc["done"]), doc["done"])
        m = S.mapping_entries(S.compat_mapping(root)[2])
        self.assertEqual((m["0"]["name"], m["0"]["priority"]), ("GE-Proton99-4", "75"))
        self.assertEqual(m["400"]["name"], "GE-Proton98-1", "a game's own choice stays")
        # the newest and the one before it stay; 99-1 (the old default) and unused builds go
        self.assertEqual(sorted(os.listdir(os.path.join(root, "compatibilitytools.d"))),
                         sorted(["GE-Proton99-4", "GE-Proton99-3", "GE-Proton98-1", "Luxtorpeda", "GE-Proton95-1"]))
        # looked at most once an hour: with GitHub gone, a plain run doesn't even try
        shutil.rmtree(os.path.join(self.tmp, "releases"))
        doc = self.maintain()
        self.assertEqual(doc["done"], [])
        self.assertEqual(doc["said"], "Nothing to do: games are ready.")
        # --refresh tries, says so plainly, and isn't a failure
        doc = self.maintain("--refresh")
        self.assertIn("GE-Proton wasn't updated", doc["said"])

    def test_maintain_dry_run_downloads_and_changes_nothing(self):
        root, lib2 = stale_machine(self.home, self.fsroot)
        self.release("GE-Proton99-4")
        before = self.tree(root)
        doc = self.maintain("--dry-run", "--refresh")
        self.assertEqual(self.tree(root), before)
        self.assertIn("Would look for a new GE-Proton", doc["said"])
        self.assertIn("The default Proton for every game: GE-Proton99-1 → GE-Proton99-3", doc["said"])
        self.assertIn("GE-Proton97-1 isn't used by any game", doc["said"])

    def test_maintain_without_steam_says_so(self):
        doc = self.maintain()
        self.assertIsNone(doc["steam_root"])
        self.assertIn("Steam hasn't run here yet", doc["said"])

    def test_maintain_notifies_once_and_only_for_what_needs_the_person(self):
        write(os.path.join(self.bin, "notify-send"),
              '#!/bin/sh\nprintf "%s|" "$@" >> "$BROMIGOS_FIXTURE_STATE/notify.calls"; echo >> '
              '"$BROMIGOS_FIXTURE_STATE/notify.calls"\n')
        os.chmod(os.path.join(self.bin, "notify-send"), 0o755)
        calls = os.path.join(self.fx, "notify.calls")
        root, _ = make_steam(self.home, config="config-bad.vdf", runtime="broken")
        self.maintain("--no-download", "--notify")
        self.assertFalse(os.path.exists(calls), "what bromigOS repaired itself isn't announced")
        write(os.path.join(self.fsroot, "etc", "mkinitcpio.conf"), "MODULES=(nvidia-open)\n")
        self.maintain("--no-download", "--notify")
        with open(calls) as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertIn("Games need you|mkinitcpio's MODULES names nvidia-open, a package.", lines[0])
        self.assertIn("Open Settings › Playing games", lines[0])
        self.maintain("--no-download", "--notify")
        with open(calls) as f:
            self.assertEqual(len(f.read().splitlines()), 1, "told once")

    def test_check_reports_login_leftovers_then_what_the_package_removed(self):
        import subprocess
        etc = os.path.join(self.fsroot, "etc", "sddm.conf.d")
        write(os.path.join(etc, "10-wayland.conf"), "[General]\nDisplayServer=wayland\n")
        write(os.path.join(etc, "20-bromigos.conf"), "# Written by ~/.config/bromigos/sddm/install.sh. Back:\n"
              "[Theme]\nCurrent=bromigos\nCursorTheme=Bromigos-cursor\n")
        _, doc, _ = self.check()
        login = [f for f in doc["findings"] if f["check"] == "login"]
        self.assertEqual([(f["level"], f["fixable"]) for f in login], [("warn", "sddm")] * 2)
        self.assertIn("only repeats bromigOS's login settings", login[0]["title"])
        r = F.readiness(doc)
        self.assertTrue(r["root"] and not r["needs_you"])
        # the package's scriptlet (bromigos-sddm-tidy --apply) has run
        subprocess.run([sys.executable, os.path.join(REPO, "settings/sddm/bromigos-sddm-tidy"), "--apply", "--quiet"],
                       env=dict(self.env), check=True, capture_output=True)
        _, doc, seen = self.check()
        login = {f["title"]: f["level"] for f in doc["findings"] if f["check"] == "login"}
        self.assertEqual(login, {
            "Removed /etc/sddm.conf.d/10-wayland.conf: it only repeated bromigOS's login settings": "ok",
            "Removed /etc/sddm.conf.d/20-bromigos.conf: it only repeated bromigOS's login settings": "ok",
            "Nothing in /etc/sddm.conf.d overrides the login screen": "ok"})

    def test_nvapi_with_a_gpu_file_of_your_own_says_how_to_hand_it_back(self):
        self.hw([{"vendor": "NVIDIA", "driver": "nvidia", "id": "10de:2f04"}])
        write(self.path(".local/state/bromigos/hw/hyprland.lua"), "-- mine\nreturn { env = {} }\n")
        _, doc, _ = self.check()
        [f] = [f for f in doc["findings"] if f["check"] == "nvapi"]
        self.assertTrue(f["own_file"])
        self.assertIn("has changes of your own, so bromigOS leaves it alone", f["fix"])
        self.assertIn("mv ~/.local/state/bromigos/hw/hyprland.lua ~/hyprland.lua.mine && "
                      "bromigos hw setup --user-only", f["fix"])
        self.assertIn("Then log out and back in", f["fix"])

    # ---------------------------------------------------------------- setup

    def test_setup_installs_steam_with_this_machines_32_bit_drivers(self):
        self.hw([{"vendor": "NVIDIA", "name": "GB205 [GeForce RTX 5070]", "driver": "nvidia"},
                 {"vendor": "AMD", "name": "Lexa PRO [Radeon 540/540X/550/550X / RX 540X/550/550X]", "driver": "amdgpu"}],
                packages=["nvidia-open", "nvidia-utils", "libva-nvidia-driver", "lib32-nvidia-utils", "mesa",
                          "vulkan-radeon", "linux-firmware-amdgpu", "lib32-mesa", "lib32-vulkan-radeon"],
                hyprland_changed=True)
        doc = self.cmd("game-setup", "--dry-run")
        self.assertEqual(doc["packages"], ["lib32-nvidia-utils", "vulkan-radeon", "lib32-mesa", "lib32-vulkan-radeon",
                                           "steam", "gamemode", "lib32-gamemode"])
        self.assertEqual(doc["missing"], doc["packages"])        # the stand-in pacman has none of them
        self.assertEqual(doc["commands"][0], "sudo pacman -S --needed " + " ".join(doc["packages"]))
        self.assertIn("bromigos hw setup --user-only", doc["commands"])
        self.assertTrue(any(c.startswith("sudo gpasswd -a ") and c.endswith(" gamemode") for c in doc["commands"]))
        self.assertFalse(self.calls("pacman") and any(c[:1] == ["-S"] for c in self.calls("pacman")))

    def test_setup_without_multilib_says_how_to_turn_it_on(self):
        self.hw([{"vendor": "AMD", "driver": "amdgpu"}], multilib=False)
        doc = self.cmd("game-setup", "--dry-run", ok=False)
        self.assertIn("[multilib]", doc["error"])
        self.assertIn("/etc/pacman.conf", doc["error"])


if __name__ == "__main__":
    unittest.main()
