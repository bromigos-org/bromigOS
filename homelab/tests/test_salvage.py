"""The salvage scan (bromigos_homelab/salvage.py; docs/salvage.md): what an old PC can do as a
home server. Six stand-in machines (salvagefake.py: fake roots and recorded tool outputs) are
read, judged and reported; the verdicts are checked against the provisioning catalogue's own
budget logic and against the installer's meter (bromigos_installer/provision.py) for the same
hardware; a scan without administrator rights says what it couldn't read; and a saved report
holds no serial number, MAC address or hostname.

Nothing here reads the machine the tests run on: every file is under a temporary root, every
tool is a recorded output, and a real subprocess fails the test.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest
from unittest import mock

from bromigos_homelab import provcatalog as PC, salvage as S
import salvagefake as F

REPO = Path(__file__).resolve().parents[2]
INSTALLER_LIB = REPO / "iso/profile/airootfs/usr/local/lib/bromigos-iso"
_PATCHES = []
_ENV = {}


def setUpModule():
    """The checkout's catalogue (never an installed one), no display, and no real tools."""
    for k in ("WAYLAND_DISPLAY", "DISPLAY", "BROMIGOS_PROVISION_CATALOGUE", "BROMIGOS_INSTALLER_HW", "BROMIGOS_INSTALLER_FAKE"):
        _ENV[k] = os.environ.pop(k, None)
    _ENV["BROMIGOS_HOMELAB_LIB"] = os.environ.get("BROMIGOS_HOMELAB_LIB")
    os.environ["BROMIGOS_HOMELAB_LIB"] = str(REPO / "homelab/lib")
    PC._cache.clear()
    for p in (mock.patch.object(PC, "SHARE", "/nonexistent"),
              mock.patch("subprocess.run", side_effect=AssertionError("a test ran a real tool")),
              mock.patch("shutil.which", side_effect=AssertionError("a test looked for a real tool"))):
        p.start()
        _PATCHES.append(p)


def tearDownModule():
    for p in _PATCHES:
        p.stop()
    for k, v in _ENV.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    PC._cache.clear()


class Clock:
    """A clock that moves only when the scan sleeps, and a power counter that counts while it does."""

    def __init__(self, root=None, joules=0.0):
        self.now, self.root, self.joules = 100.0, root, joules

    def sleep(self, seconds):
        self.now += seconds
        counter = Path(self.root or "/nonexistent", "sys/class/powercap/intel-rapl:0/energy_uj")
        if counter.exists():
            counter.write_text(str(int(counter.read_text()) + int(self.joules * 1e6)) + "\n")

    def clock(self):
        return self.now


def scan(name, euid=0, joules=0.0, **kw):
    """(the document, the tools that were asked) for a stand-in machine."""
    with tempfile.TemporaryDirectory() as tmp:
        root, run = F.build(tmp, F.MACHINES[name] if isinstance(name, str) else name)
        c = Clock(root, joules)
        return S.scan(root=root, run=run, euid=euid, sleep=c.sleep, clock=c.clock, **kw), run


DOCS = {}


def doc(name):
    """Each machine scanned once, as root (as Field Kit runs it)."""
    if name not in DOCS:
        DOCS[name] = scan(name)[0]
    return DOCS[name]


def flat(d):
    """The report as one line, so a wrapped sentence can be looked for whole."""
    return " ".join("\n".join(S.report(d)).split())


def by_id(rows):
    return {r["id"]: r for r in rows}


class Facts(unittest.TestCase):
    def test_a_2012_desktop(self):
        m = doc("desktop-2012")["machine"]
        self.assertEqual(m["computer"], {"kind": "desktop", "model": "Example Computers Office Desktop 2012", "virtual_machine": None})
        p = m["processor"]
        self.assertEqual((p["model"], p["cores"], p["threads"], p["sockets"]), ("Intel Core i5-3470 CPU @ 3.20GHz", 4, 4, 1))
        self.assertEqual((p["level"], p["age_class"], p["age_from"]), ("x86-64-v2", "older", "instruction sets"))
        self.assertEqual(p["virtualisation"], "available (VT-x)")
        self.assertEqual(p["video"], {"source": "driver", "decode": [], "encode": [], "likely": True,
                                      "from": "Intel graphics with the i915 driver loaded"})
        self.assertEqual(m["memory"], {"total_gb": 3.8, "installed_gb": 4.0, "slots": 4, "slots_free": 2, "max_gb": 32, "type": "DDR3",
                                       "ecc": False, "source": "udev"})
        self.assertEqual(len(m["disks"]), 1)
        d = m["disks"][0]
        self.assertEqual((d["size"], d["kind"], d["rotational"], d["health"], d["holds_data"], d["medium"]),
                         ("500 GB", "HDD", True, "ok", True, False))
        self.assertEqual(m["storage"]["system"], "sda")
        self.assertEqual([x["id"] for x in m["storage"]["layouts"]], ["one-disk"])
        self.assertEqual(m["network"], [{"name": "enp2s0", "wifi": False, "connected": True, "speed_mbps": 1000, "max_mbps": 1000}])
        self.assertEqual(m["firmware"], {"boot": "BIOS", "secure_boot": None, "tpm": None})
        self.assertEqual((m["power"]["class"], m["power"]["estimate"], m["power"]["measured_w"]), ("medium", True, None))
        self.assertEqual(m["power"]["from"], ["a desktop", "no separate graphics card", "1 spinning disk"])

    def test_a_small_office_pc(self):
        m = doc("office-pc")["machine"]
        self.assertEqual((m["processor"]["level"], m["processor"]["age_class"], m["processor"]["threads"]), ("x86-64-v3", "current", 6))
        v = m["processor"]["video"]
        self.assertEqual((v["source"], v["decode"], v["encode"]),
                         ("vainfo", ["MPEG-2", "H.264", "HEVC (H.265)", "VP9"], ["H.264", "HEVC (H.265)"]))
        self.assertEqual((m["memory"]["total_gb"], m["memory"]["slots_free"], m["memory"]["type"]), (15.5, 2, "DDR4"))
        self.assertEqual((m["disks"][0]["kind"], m["disks"][0]["rotational"], m["disks"][0]["holds_data"]), ("SSD", False, False))
        self.assertEqual(m["firmware"], {"boot": "UEFI", "secure_boot": True, "tpm": "2.0"})
        self.assertEqual(m["unread"], [])

    def test_a_mini_pc(self):
        d, _ = scan("mini-pc", joules=3.0)
        m = d["machine"]
        self.assertEqual(m["computer"]["kind"], "mini PC")
        self.assertEqual(m["disks"][0]["kind"], "NVMe")
        self.assertEqual(m["network"], [{"name": "enp1s0", "wifi": False, "connected": True, "speed_mbps": 2500, "max_mbps": 2500},
                                        {"name": "wlo1", "wifi": True, "connected": False, "speed_mbps": None, "max_mbps": None}])
        self.assertIn("AV1", m["processor"]["video"]["decode"])
        self.assertEqual(m["firmware"]["secure_boot"], False)
        self.assertEqual(m["memory"]["slots_free"], 0)
        # the class is an estimate from its parts; the watts are the processor's own counter, read as root
        self.assertEqual((m["power"]["class"], m["power"]["from"][0]), ("low", "a mini PC"))
        self.assertEqual(m["power"]["measured_w"], 6.0)                 # 3 J in half a second
        self.assertIn("Idle power low: an estimate from the kind of computer and its parts", flat(d))
        self.assertIn("the processor alone drew 6 W", flat(d))

    def test_a_laptop_on_wifi(self):
        d = doc("laptop-wifi")
        m = d["machine"]
        self.assertEqual((m["computer"]["kind"], m["processor"]["cores"], m["processor"]["threads"]), ("laptop", 4, 8))
        self.assertEqual(m["network"], [{"name": "wlp2s0", "wifi": True, "connected": True, "speed_mbps": None, "max_mbps": None}])
        self.assertEqual(m["power"]["class"], "low")
        held = [c["id"] for c in d["verdict"]["cautions"]]
        self.assertIn("wifi-only", held)
        self.assertIn("laptop", held)
        self.assertIn("wired-network", [u["id"] for u in d["upgrades"]])

    def test_a_virtual_machine_says_what_it_could_not_read(self):
        d, run = scan("virtual-machine", euid=1000)
        m = d["machine"]
        self.assertEqual((m["computer"]["kind"], m["computer"]["virtual_machine"]), ("virtual machine", "yes"))
        self.assertEqual((m["processor"]["threads"], m["processor"]["cores"], m["processor"]["level"]), (2, None, "x86-64-v1"))
        self.assertEqual(m["memory"], {"total_gb": 1.9, "installed_gb": None, "slots": None, "slots_free": None, "max_gb": None,
                                       "type": None, "ecc": None, "source": None})
        self.assertEqual((m["disks"][0]["kind"], m["disks"][0]["rotational"], m["disks"][0]["health"]), ("virtual disk", False, None))
        self.assertEqual(m["graphics"], [])
        self.assertEqual((m["power"]["class"], m["power"]["from"]), (None, []))
        what = [u["what"] for u in m["unread"]]
        self.assertEqual(what, ["memory slots, memory type and ECC", "how fast the wired port eth0 is"])
        self.assertIn("administrator rights", m["unread"][0]["why"])
        self.assertEqual(d["verdict"]["cautions"][0]["id"], "virtual-machine")
        self.assertIn("COULD NOT READ", flat(d))
        self.assertIn("not estimated: a virtual machine draws its host's power", flat(d))
        self.assertEqual(d["next"]["roles"], ["base"])

    def test_a_tower_with_a_graphics_card(self):
        d = doc("tower")
        m = d["machine"]
        self.assertEqual(m["computer"], {"kind": "desktop", "model": None, "virtual_machine": None})      # "To Be Filled By O.E.M."
        self.assertEqual([(g["vendor"], g["model"], g["ready"], g["vram_gib"]) for g in m["graphics"]], [("NVIDIA", "GeForce RTX 3060", True, 12.0)])
        self.assertEqual([x["health"] for x in m["disks"]], ["ok", "ok", "failing"])
        # the failing disk is left out of the plan, so there's one data disk and no second copy
        self.assertEqual((m["storage"]["system"], m["storage"]["data"]), ("sda", ["sdb"]))
        self.assertEqual([x["id"] for x in m["storage"]["layouts"]], ["one-copy"])
        self.assertEqual(m["power"]["class"], "high")
        self.assertIn("failing-disk", [c["id"] for c in d["verdict"]["cautions"]])
        self.assertEqual(d["budget_hardware"], {"cpu": 12, "ram_gb": 31.3, "disk_gb": 8501, "gpu": "nvidia", "gpu_vram_gb": 12.0,
                                                "gpu_name": "GeForce RTX 3060"})
        self.assertEqual(by_id(d["verdict"]["items"])["ollama"]["fit"], "yes")
        self.assertEqual(by_id(d["verdict"]["items"])["vllm"]["reason"], "Model serving (vLLM) needs 16 GB of graphics memory; this card has 12 GB.")

    def test_two_good_data_disks_can_hold_two_copies(self):
        def machine():
            files, links, tools = F.tower()
            tools["smartctl"]["/dev/sdc"] = F.SMART_OK
            return files, links, tools
        plan = scan(machine)[0]["machine"]["storage"]
        self.assertEqual([x["id"] for x in plan["layouts"]], ["one-copy", "two-copies"])
        self.assertEqual([x["usable_bytes"] for x in plan["layouts"]], [8_001_574_060_032, 4_000_787_030_016])
        self.assertEqual([x["survives_a_disk"] for x in plan["layouts"]], [False, True])

    def test_the_stick_it_started_from_is_not_counted(self):
        def machine():
            files, links, tools = F.office_pc()
            files.update(F.block("sdb", 0))
            files["proc/mounts"] = "/dev/sdb1 /run/archiso/bootmnt iso9660 ro 0 0\n"
            files["run/archiso"] = None
            disks = json.loads(tools["lsblk"])["blockdevices"]
            usb = dict(F.disk("sdb", 31_000_000_000, False, "usb", "EXAMPLE STICK"), rm=True)
            tools["lsblk"] = json.dumps({"blockdevices": disks + [usb]})
            return files, links, tools
        d = scan(machine)[0]
        stick = d["machine"]["disks"][1]
        self.assertEqual((stick["medium"], stick["removable"]), (True, True))
        self.assertEqual(d["budget_hardware"]["disk_gb"], 256)
        self.assertEqual(d["machine"]["storage"]["system"], "sda")
        self.assertIn("the stick this started from, not counted", flat(d))
        self.assertIn("BROMIGOS_ANSWERS=salvage.toml bromigos-iso-install --text", flat(d))    # on the live stick

    def test_a_port_named_after_its_mac_address_is_renamed(self):
        def machine():
            files, links, tools = F.laptop_wifi()
            files.update(F.nic("enx020000face08", "02:00:00:fa:ce:08", "1000"))
            return files, links, tools
        d = scan(machine)[0]
        self.assertEqual([n["name"] for n in d["machine"]["network"]], ["usb-ethernet", "wlp2s0"])
        self.assertNotIn("face08", json.dumps(d))

    def test_a_processor_bromigos_cannot_run_on(self):
        def machine():
            files, links, tools = F.desktop_2012()
            files["proc/cpuinfo"] = F.cpuinfo("Example 32-bit processor", "GenuineIntel", "fpu de pse tsc msr pae cx8 sse sse2", 1, 1)
            return files, links, tools
        d = scan(machine)[0]
        self.assertIn("32-bit only", d["fatal"])
        self.assertTrue(all(x["fit"] == "no" and x["reason"] == d["fatal"] for x in d["verdict"]["roles"] + d["verdict"]["items"]))
        self.assertEqual((d["next"]["roles"], d["upgrades"]), ([], []))
        self.assertIsNone(S.answers_toml(d))
        self.assertIn("Nothing, as a bromigOS Server: " + d["fatal"], flat(d))
        self.assertNotIn("NEXT STEP", flat(d))

    def test_an_empty_machine_does_not_crash(self):
        d = scan(lambda: ({"proc": None}, [], {}), euid=1000)[0]
        what = " | ".join(u["what"] for u in d["machine"]["unread"])
        for words in ("the processor", "how much memory there is", "the disks"):
            self.assertIn(words, what)
        self.assertEqual(d["budget_hardware"], {"cpu": 1, "ram_gb": None, "disk_gb": 0, "gpu": False, "gpu_vram_gb": 0, "gpu_name": ""})
        self.assertTrue(S.report(d))


class Parsers(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(S.x86_level(set(F.V2.split())), "x86-64-v2")
        self.assertEqual(S.x86_level(set((F.V2 + " avx").split())), "x86-64-v2")          # AVX without AVX2 is still v2
        self.assertEqual(S.x86_level(set(F.V3.split())), "x86-64-v3")
        self.assertEqual(S.x86_level(set((F.V3 + " avx512f avx512bw avx512cd avx512dq avx512vl").split())), "x86-64-v4")
        self.assertEqual(S.x86_level({"lm", "sse2"}), "x86-64-v1")
        self.assertEqual(S.x86_level(set(F.V2.split()) - {"popcnt"} | {"avx2"}), "x86-64-v1")   # a level needs every flag below it

    def test_ethtool(self):
        self.assertEqual(S.parse_ethtool(F.ethtool("eth0", F.GIGABIT + ["2500baseT/Full"], "Unknown!")), 2500)
        self.assertEqual(S.parse_ethtool(F.ethtool("eth0", ["10baseT/Half 10baseT/Full", "100baseT/Half 100baseT/Full"], "100Mb/s")), 100)
        self.assertIsNone(S.parse_ethtool("Settings for eth0:\n\tLink detected: yes\n"))
        self.assertIsNone(S.parse_ethtool(None))

    def test_vainfo(self):
        text = F.vainfo([("H264Main", "VLD"), ("H264High", "VLD"), ("H264High", "EncSlice"), ("AV1Profile0", "VLD"), ("None", "VideoProc")])
        self.assertEqual(S.parse_vainfo(text), (["H.264", "AV1"], ["H.264"]))
        self.assertEqual(S.parse_vainfo("vainfo: nothing here\n"), ([], []))

    def test_smart(self):
        self.assertEqual(S.smart_verdict(F.SMART_OK), "ok")
        self.assertEqual(S.smart_verdict(F.SMART_FAILING), "failing")
        for nothing in (None, "", "not json", "{}", '{"smart_status": {}}', "[]"):
            self.assertIsNone(S.smart_verdict(nothing))

    def test_memory_from_dmidecode_as_root(self):
        text = ("# dmidecode 3.6\n\nHandle 0x0010, DMI type 16, 23 bytes\nPhysical Memory Array\n\tLocation: System Board Or Motherboard\n"
                "\tError Correction Type: Multi-bit ECC\n\tMaximum Capacity: 64 GB\n\tNumber Of Devices: 4\n\n"
                "Handle 0x0011, DMI type 17, 40 bytes\nMemory Device\n\tSize: 16 GB\n\tType: DDR4\n\tSerial Number: " + F.SERIALS[1] + "\n\n"
                "Handle 0x0012, DMI type 17, 40 bytes\nMemory Device\n\tSize: No Module Installed\n\tType: Unknown\n\n"
                "Handle 0x0013, DMI type 17, 40 bytes\nMemory Device\n\tSize: 16384 MB\n\tType: DDR4\n\n"
                "Handle 0x0014, DMI type 17, 40 bytes\nMemory Device\n\tSize: No Module Installed\n\tType: Unknown\n")

        def machine():
            files, links, tools = F.office_pc()
            del files["run/udev/data/+dmi:id"]
            tools["dmidecode"] = text
            return files, links, tools
        d, run = scan(machine)
        self.assertEqual(d["machine"]["memory"], {"total_gb": 15.5, "installed_gb": 32.0, "slots": 4, "slots_free": 2, "max_gb": 64,
                                                  "type": "DDR4", "ecc": True, "source": "dmidecode"})
        self.assertNotIn(F.SERIALS[1], json.dumps(d))
        d, run = scan(machine, euid=1000)                      # and never without root
        self.assertNotIn("dmidecode", [c[0] for c in run.calls])
        self.assertIsNone(d["machine"]["memory"]["slots"])

    def test_ecc_from_udev_and_from_the_kernel(self):
        raw = {"memory_udev": F.udev_memory(2, [8, 8], "DDR4", ecc="Multi-bit ECC").splitlines()}
        raw["memory_udev"] = [line[2:] for line in raw["memory_udev"] if line.startswith("E:MEMORY_")]
        self.assertTrue(S.memory_table(raw)["ecc"])

        def machine():
            files, links, tools = F.virtual_machine()
            files["sys/devices/system/edac/mc/mc0"] = None
            return files, links, tools
        m = scan(machine, euid=1000)[0]["machine"]["memory"]
        self.assertEqual((m["ecc"], m["source"]), (True, "the kernel's error reporting (EDAC)"))


class Verdict(unittest.TestCase):
    def test_the_2012_desktop(self):
        d = doc("desktop-2012")
        self.assertEqual(d["budget_hardware"], {"cpu": 4, "ram_gb": 3.8, "disk_gb": 500, "gpu": False, "gpu_vram_gb": 0, "gpu_name": ""})
        roles = by_id(d["verdict"]["roles"])
        self.assertEqual({k: v["fit"] for k, v in roles.items()},
                         {"lab-node": "no", "storage": "tradeoff", "home-services": "tradeoff", "game-server": "no", "media": "no", "base": "yes"})
        self.assertEqual(roles["home-services"]["reason"],
                         "without Photos (Immich): Photos (Immich) needs 4 GB of memory; this server has 3.8 GB.")
        self.assertEqual(roles["home-services"]["left_out"], ["photos"])
        self.assertEqual(roles["game-server"]["reason"], "Minecraft server needs 4 GB of memory; this server has 3.8 GB.")
        self.assertEqual(roles["media"]["reason"], "Together these need about 7.2 GB of memory, and this server has 3.8 GB.")
        self.assertEqual(roles["storage"]["reason"], "Memory will be tight: about 3.7 of 3.8 GB.")
        items = by_id(d["verdict"]["items"])
        self.assertEqual((items["photos"]["fit"], items["photos"]["cause"]), ("no", "memory"))
        self.assertEqual(items["photos"]["reason"], "Photos (Immich) needs 4 GB of memory; this server has 3.8 GB.")
        self.assertEqual((items["ollama"]["fit"], items["ollama"]["cause"]), ("no", "graphics"))
        self.assertEqual((items["jellyfin"]["fit"], items["smb-shares"]["fit"], items["seerr"]["fit"]), ("yes", "yes", "tradeoff"))
        self.assertEqual(items["seerr"]["with"], ["jellyfin", "media-library"])
        self.assertEqual([c["id"] for c in d["verdict"]["cautions"]], ["spinning-system", "one-disk", "holds-data"])

    def test_its_upgrades_are_tried_against_the_same_logic(self):
        d = doc("desktop-2012")
        ups = d["upgrades"]
        self.assertEqual([u["id"] for u in ups], ["memory", "system-ssd", "second-disk"])
        self.assertEqual(ups[0]["title"], "More memory: 8 GB in all")
        self.assertEqual(ups[0]["roles"], ["Lab node", "Game server", "Media"])
        self.assertIn("Photos (Immich)", ups[0]["items"])
        self.assertIn("2 of 4 memory slots are free. It takes DDR3 memory.", ups[0]["words"])
        # every gain it names does fit with that much memory, by provcatalog itself
        hw = dict(d["budget_hardware"], ram_gb=7.8)
        names = {it["name"]: it for it in PC.load()}
        for name in ups[0]["items"]:
            ids, _ = PC.resolve([names[name]["id"]])
            self.assertIsNone(PC.fits_item(names[name], hw), name)
            self.assertTrue(PC.budget(ids, hw)["fits"], name)
        # no brands, no prices
        text = " ".join(u["title"] + " " + u["words"] for name in F.MACHINES for u in doc(name)["upgrades"])
        for word in ("$", "€", "£", "price", "cost", "cheap", "buy"):
            self.assertNotIn(word, text.lower())

    def test_upgrades_per_machine(self):
        self.assertEqual([u["id"] for u in doc("office-pc")["upgrades"]], ["second-disk", "graphics-card"])
        self.assertEqual(doc("office-pc")["upgrades"][1]["items"], ["LiteLLM gateway", "Model serving (Ollama)", "Models"])
        self.assertEqual([u["id"] for u in doc("mini-pc")["upgrades"]], ["second-disk", "graphics-card"])
        self.assertEqual([u["id"] for u in doc("laptop-wifi")["upgrades"]], ["second-disk", "wired-network"])
        self.assertEqual([u["id"] for u in doc("virtual-machine")["upgrades"]], ["memory", "more-disk"])
        self.assertEqual(doc("tower")["upgrades"], [])
        for name in F.MACHINES:
            self.assertLessEqual(len(doc(name)["upgrades"]), 3, name)

    def test_memory_is_never_suggested_past_what_the_board_takes(self):
        def machine():
            files, links, tools = F.desktop_2012()
            files["run/udev/data/+dmi:id"] = F.udev_memory(2, [2, 2], "DDR3", max_gb=4)
            return files, links, tools
        self.assertNotIn("memory", [u["id"] for u in scan(machine)[0]["upgrades"]])

    def test_next_step(self):
        want = {"desktop-2012": ["home-services"], "office-pc": ["home-services", "media", "storage"],
                "mini-pc": ["home-services", "media", "storage"], "laptop-wifi": ["home-services"], "virtual-machine": ["base"],
                "tower": ["home-services", "media", "storage", "game-server", "lab-node"]}
        for name, roles in want.items():
            with self.subTest(machine=name):
                d = doc(name)
                nxt, hw = d["next"], d["budget_hardware"]
                self.assertEqual(nxt["roles"], roles)
                self.assertEqual(nxt["provision"], PC.recommend(roles, hw, lab="none"))
                self.assertTrue(nxt["budget"]["fits"])
                self.assertEqual(nxt["budget"], PC.budget(nxt["provision"], hw))
        self.assertNotIn("photos", doc("desktop-2012")["next"]["provision"])
        self.assertIn("photos", doc("office-pc")["next"]["provision"])

    def test_every_reason_names_its_limit(self):
        for name in F.MACHINES:
            v = doc(name)["verdict"]
            for x in v["roles"] + v["items"]:
                with self.subTest(machine=name, item=x["id"]):
                    self.assertEqual(x["cause"] is None, x["fit"] == "yes")
                    self.assertNotEqual(x["cause"], "other", x["reason"])
                    self.assertNotIn("Untick", x["reason"])

    def test_every_catalogue_item_and_role_is_judged(self):
        for name in F.MACHINES:
            v = doc(name)["verdict"]
            self.assertEqual([i["id"] for i in v["items"]], [it["id"] for it in PC.load()])
            self.assertEqual([r["id"] for r in v["roles"]], list(PC.ROLES))
            self.assertEqual([g["id"] for g in v["groups"]], list(PC.GROUPS))


class AgreesWithTheBudgetLogic(unittest.TestCase):
    """One answer to "does this fit": the scan's verdicts are provcatalog's, and the installer's
    meter (bromigos_installer/provision.py, which calls the same engine) says the same for the
    same hardware."""

    def test_the_catalogue_engine(self):
        for name in F.MACHINES:
            d = doc(name)
            hw = d["budget_hardware"]
            cat = PC.by_id()
            for i in d["verdict"]["items"]:
                with self.subTest(machine=name, item=i["id"]):
                    ids, added = PC.resolve([i["id"]])
                    b = PC.budget(ids, hw)
                    fits = b["fits"] and PC.fits_item(cat[i["id"]], hw) is None
                    self.assertEqual(i["fit"] != "no", fits)
                    self.assertEqual(i["fit"] == "tradeoff", fits and bool(b["notes"]))
                    self.assertEqual(i["with"], added)
                    self.assertEqual(i["budget"], {k: b[k] for k in ("cpu", "ram_gb", "disk_gb")})
            for r in d["verdict"]["roles"]:
                with self.subTest(machine=name, role=r["id"]):
                    ids = PC.recommend([r["id"]], hw, lab="none")
                    self.assertEqual(r["items"], ids)
                    self.assertEqual(r["budget"], PC.budget(ids, hw))
                    if r["fit"] != "no":
                        self.assertTrue(r["budget"]["fits"])

    @unittest.skipUnless((INSTALLER_LIB / "bromigos_installer/provision.py").is_file(), "the installer isn't in this tree")
    def test_the_installers_meter(self):
        sys.path.insert(0, str(INSTALLER_LIB))
        self.addCleanup(sys.path.remove, str(INSTALLER_LIB))
        from bromigos_installer import provision as PV
        PV._ENGINE = None
        self.addCleanup(setattr, PV, "_ENGINE", None)
        self.assertIs(PV.engine(), PC, "the installer's meter is the catalogue's engine")
        for name in F.MACHINES:
            d = doc(name)
            with mock.patch.dict(os.environ, {"BROMIGOS_INSTALLER_HW": json.dumps(d["budget_hardware"])}):
                hw = PV.hardware()                       # what the installer's meter is given
            self.assertEqual(hw, d["budget_hardware"])
            for i in d["verdict"]["items"]:
                with self.subTest(machine=name, item=i["id"]):
                    meter = PV.budget(PV.resolve([i["id"]])[0], hw)
                    why = PV.why_not(PV.item(i["id"]), hw)
                    self.assertEqual(i["fit"] != "no", meter["fits"] and why is None)
                    if why:
                        self.assertEqual(i["reason"], why)
            for r in d["verdict"]["roles"]:
                with self.subTest(machine=name, role=r["id"]):
                    ticked = PV.recommend([S.INSTALLER_ROLES[r["id"]]], hw, "none")
                    self.assertEqual(r["items"], ticked)
                    meter = PV.budget(ticked, hw)
                    self.assertEqual(r["budget"]["fits"], meter["fits"])
                    self.assertEqual(r["budget"]["notes"], meter["notes"])
                    if r["fit"] != "no":
                        self.assertTrue(meter["fits"])
            nxt = d["next"]
            self.assertEqual(nxt["provision"], PV.recommend(nxt["installer_roles"], hw, "none"))
            self.assertTrue(PV.budget(nxt["provision"], hw)["fits"])

    def test_hardware_is_counted_as_the_installer_counts_it(self):
        # localprovision.detect's memory figure: MemTotal in GiB, to one decimal
        for kib, want in ((3_982_000, 3.8), (16_261_000, 15.5), (8_030_000, 7.7)):
            self.assertEqual(round(kib / 1024 ** 2, 1), want)
        self.assertEqual(doc("office-pc")["budget_hardware"]["ram_gb"], 15.5)
        # provision.hardware's disk figure: every disk but the medium, in whole decimal GB
        self.assertEqual(doc("tower")["budget_hardware"]["disk_gb"], (500_107_862_016 + 2 * 4_000_787_030_016) // 10 ** 9)
        # a card counts only once its driver works (hardware.legacy)
        def machine():
            files, links, tools = F.tower()
            tools.pop("nvidia-smi")
            return files, [(link, target.replace("nvidia", "nouveau")) for link, target in links], tools
        d = scan(machine)[0]
        self.assertEqual((d["budget_hardware"]["gpu"], d["budget_hardware"]["gpu_vram_gb"]), (False, 0))
        self.assertIn("graphics-driver", [c["id"] for c in d["verdict"]["cautions"]])
        self.assertEqual(by_id(d["verdict"]["items"])["ollama"]["fit"], "no")


class WithoutPrivileges(unittest.TestCase):
    def test_it_says_what_it_could_not_read_and_why(self):
        d, run = scan("desktop-2012", euid=1000)
        asked = [c[0] for c in run.calls]
        self.assertNotIn("smartctl", asked)
        self.assertNotIn("dmidecode", asked)
        self.assertIsNone(d["machine"]["disks"][0]["health"])
        self.assertFalse(d["machine"]["privileged"])
        unread = {u["what"]: u["why"] for u in d["machine"]["unread"]}
        self.assertEqual(unread["each drive's own health verdict (SMART)"],
                         "smartctl needs administrator rights: run it with sudo, or from Field Kit")
        self.assertIn("COULD NOT READ", flat(d))
        self.assertIn("health not read", flat(d))
        # memory slots come from udev's database, which everyone can read
        self.assertEqual(d["machine"]["memory"]["slots_free"], 2)
        # and the verdict is the same: nothing it rests on needs root
        root = doc("desktop-2012")
        self.assertEqual(d["verdict"]["roles"], root["verdict"]["roles"])
        self.assertEqual(d["verdict"]["items"], root["verdict"]["items"])
        self.assertEqual(d["next"], root["next"])

    def test_the_power_counter_needs_root(self):
        d, _ = scan("mini-pc", euid=1000, joules=3.0)
        self.assertIsNone(d["machine"]["power"]["measured_w"])
        self.assertEqual(d["machine"]["power"]["class"], "low")
        self.assertIn("the processor's measured power", [u["what"] for u in d["machine"]["unread"]])

    def test_as_root_the_drives_are_asked(self):
        d, run = scan("tower")
        self.assertEqual(sorted(c[-1] for c in run.calls if c[0] == "smartctl"), ["/dev/sda", "/dev/sdb", "/dev/sdc"])
        self.assertTrue(all(c[1:3] == ["-H", "-j"] for c in run.calls if c[0] == "smartctl"))
        self.assertTrue(d["machine"]["privileged"])


class Privacy(unittest.TestCase):
    SECRETS = F.SERIALS + (F.HOSTNAME, "02:00:00:fa:ce", "FAKE")

    def test_nothing_private_is_read_by_default(self):
        for name in F.MACHINES:
            for euid in (0, 1000):
                d, run = scan(name, euid=euid)
                with self.subTest(machine=name, euid=euid):
                    text = json.dumps(d) + "\n".join(S.report(d))
                    for secret in self.SECRETS:
                        self.assertNotIn(secret, text)
                    self.assertNotIn("identifiers", d["machine"])
                    self.assertFalse([c for c in run.calls if "SERIAL" in " ".join(c) or "hostname" in " ".join(c)])

    def test_a_saved_report_has_no_serials_macs_or_hostname(self):
        for name in F.MACHINES:
            for identifiers in (False, True):               # even when the scan was asked to read them
                d, _ = scan(name, identifiers=identifiers)
                with self.subTest(machine=name, identifiers=identifiers), tempfile.TemporaryDirectory() as tmp:
                    path = S.save(d, os.path.join(tmp, "report.txt"))
                    text = Path(path).read_text()
                    for secret in self.SECRETS:
                        self.assertNotIn(secret, text)
                    self.assertTrue(text.startswith("SALVAGE SCAN"))
                    saved = json.loads(text.split("(JSON; docs/salvage.md) ----\n", 1)[1])
                    self.assertEqual(saved, S.public(d))
                    self.assertNotIn("--save", text)                      # the hint to save isn't saved

    def test_identifiers_only_when_asked_twice(self):
        d, run = scan("tower", identifiers=True)
        ids = d["machine"]["identifiers"]
        self.assertEqual(ids["hostname"], F.HOSTNAME)
        self.assertEqual(ids["mac"], {"enp5s0": "02:00:00:fa:ce:07"})
        self.assertEqual(ids["disk_serial"], {n: F.SERIALS[0] for n in ("sda", "sdb", "sdc")})
        self.assertNotIn(F.HOSTNAME, "\n".join(S.report(d)))             # the report for the screen never shows them
        with tempfile.TemporaryDirectory() as tmp:
            text = Path(S.save(d, os.path.join(tmp, "r.txt"), identifiers=True)).read_text()
        self.assertIn("IDENTIFIERS", text)
        self.assertIn(F.HOSTNAME, text)
        self.assertIn("02:00:00:fa:ce:07", text)

    def test_redact_is_a_second_net(self):
        self.assertEqual(S.redact("port at 02:00:00:FA:CE:07 and 02-00-00-fa-ce-07"), "port at [left out] and [left out]")
        self.assertEqual(S.redact("on fake-hostname-attic", {"machine": {"identifiers": {"hostname": "fake-hostname-attic"}}}), "on [left out]")


class ReportAndCommand(unittest.TestCase):
    def test_the_report_reads_top_to_bottom(self):
        text = "\n".join(S.report(doc("desktop-2012")))
        order = ["SALVAGE SCAN", "Read-only", "THIS COMPUTER", "Processor", "Memory", "Disks", "Graphics", "Network", "Firmware",
                 "Idle power", "COULD NOT READ", "WHAT IT'S GOOD FOR", "Roles", "Apps and services (55 in the catalogue)",
                 "Fit comfortably", "Fit with a trade-off", "Don't fit", "Whatever it runs", "WHAT WOULD CHANGE THE ANSWER", "NEXT STEP",
                 "bromigos hw salvage --answers", "bromigos hw salvage --save"]
        at = [text.index(w) for w in order]
        self.assertEqual(at, sorted(at))
        one = flat(doc("desktop-2012"))
        self.assertIn("3.8 GB of memory isn't enough for:", one)
        self.assertIn("Photos (Immich) (5 GB)", one)                          # with the system's 1 GB
        self.assertIn("Memory would be tight, with 3.8 GB here: External Secrets (3.2 GB)", one)
        self.assertIn("No graphics card is ready for AI: LiteLLM gateway, Model serving (Ollama), Model serving (vLLM), Models "
                      "and Creation studio.", one)
        self.assertIn("Fit comfortably (39): all of Network (2), Storage (4) and BRODEC (1); Lab core except Argo CD and External Secrets;", one)
        self.assertIn("yes, but Home services: without Photos (Immich)", one)
        self.assertIn("Install bromigOS Server as Home services.", one)
        self.assertIn("an estimate from its instruction sets, not a date", one)
        self.assertLess(len(text.splitlines()), 90)
        self.assertLessEqual(max(len(line) for line in text.splitlines()), 100)
        self.assertNotIn("\x1b", text)

    @unittest.skipUnless((REPO / "docs/salvage.md").is_file(), "the docs aren't in this tree")
    def test_the_docs_show_this_report(self):
        page = (REPO / "docs/salvage.md").read_text()
        shown = page.split("```text\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(shown, "\n".join(S.report(doc("desktop-2012"))))
        answers = page.split("```toml\n", 1)[1].split("\n```", 1)[0]
        self.assertEqual(tomllib.loads(answers), tomllib.loads(S.answers_toml(doc("desktop-2012"))))

    def test_the_answer_file(self):
        d = doc("office-pc")
        a = tomllib.loads(S.answers_toml(d))
        self.assertEqual(a["install"], {"edition": "server", "cpu_model": "Intel(R) Core(TM) i5-8500 CPU @ 3.00GHz"})
        self.assertEqual(a["server"], {"roles": ["home", "media", "storage"], "lab": "none", "provision": d["next"]["provision"]})
        self.assertEqual(tomllib.loads(S.answers_toml(doc("virtual-machine")))["server"]["roles"], ["plain"])

    def test_the_command(self):
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            saved, answers = os.path.join(tmp, "report.txt"), os.path.join(tmp, "salvage.toml")
            asked = {}

            def fake(**kw):
                asked.update(kw)
                return doc("office-pc")
            with mock.patch("sys.stdout", io.StringIO()) as said:
                self.assertEqual(S.main(["--save", saved, "--answers", answers], out=out.append, scan_fn=fake), 0)
            self.assertEqual(asked, {"identifiers": False})
            self.assertEqual(out, ["\n".join(S.report(doc("office-pc")))])
            self.assertIn(f"Saved the report to {saved}.", said.getvalue())
            self.assertTrue(Path(saved).read_text().startswith("SALVAGE SCAN"))
            self.assertEqual(tomllib.loads(Path(answers).read_text())["server"]["roles"], ["home", "media", "storage"])
            out.clear()
            with mock.patch("sys.stderr", io.StringIO()) as said:
                self.assertEqual(S.main(["--json", "--save", saved], out=out.append, scan_fn=fake), 0)
            self.assertEqual(json.loads(out[0]), json.loads(json.dumps(doc("office-pc"))))     # only the document on stdout
            self.assertIn("Saved the report", said.getvalue())

    def test_the_json_document(self):
        d = json.loads(json.dumps(doc("mini-pc")))
        self.assertEqual((d["schema"], d["scan"]), (1, "salvage"))
        self.assertEqual(sorted(d), ["budget_hardware", "fatal", "machine", "next", "scan", "schema", "upgrades", "verdict"])
        self.assertEqual(sorted(d["machine"]), ["computer", "disks", "firmware", "graphics", "live", "memory", "network", "power",
                                                "privileged", "processor", "storage", "unread"])
        self.assertEqual(sorted(d["verdict"]), ["cautions", "groups", "items", "roles"])
        self.assertEqual(sorted(d["next"]), ["budget", "installer_roles", "provision", "roles", "words"])

    def test_no_catalogue_is_said_plainly(self):
        def missing(**kw):
            raise FileNotFoundError("no provision-catalogue.toml (the provisioning catalogue)")
        with mock.patch("sys.stderr", io.StringIO()) as said:
            self.assertEqual(S.main([], scan_fn=missing), 1)
        self.assertIn("bromigos-lab", said.getvalue())


if __name__ == "__main__":
    unittest.main()
