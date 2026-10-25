"""Find my lab (bromigos_homelab/findlab.py, `bromigos setup homelab --find`): recorded
mDNS, SSDP, WS-Discovery, neighbour-table, Tailscale, ssh_config and lab-source answers;
one record per host; the kinds; private addresses only; the two yes questions; nothing
probed that no source found; homelab.toml only appended to.

    PYTHONPATH=lib python -m unittest tests.test_findlab

Every address here is a documentation one (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24),
and every MAC the documentation block's. The tests count the first two as private, as a
home network's would be; 203.0.113.0/24 stands for a public address.
"""
import builtins
import contextlib
import importlib.machinery
import importlib.util
import io
import ipaddress
import json
import os
import socket
import sys
import tempfile
import types
import unittest
from unittest import mock

from bromigos_homelab import config, findlab as F
from bromigos_homelab.adapters import labcommon as L

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, "fixtures", "findlab")
DOC = tuple(ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24"))
MAC_BITS = ("00:00:5e", "00005e", "00005E", "lladdr", "hardware", "uuid", "CN12345678", "FA8FCA")

try:
    import zeroconf
except ImportError:                       # optional at run time; CI installs it (checkdepends)
    zeroconf = None


def fixture(name, mode="r"):
    with open(os.path.join(FIX, name), mode) as f:
        return f.read()


def rec(type_, name, **kw):
    return types.SimpleNamespace(type=type_, name=name, **kw)


def mdns_records():
    """The recorded mDNS answer's records, as zeroconf parses them; without zeroconf, the
    same records built by hand."""
    if zeroconf:
        return zeroconf.DNSIncoming(bytes.fromhex(fixture("mdns-response.hex").strip())).answers()
    out = []
    for t, inst, host, port, txt, addr in (
            ("_home-assistant._tcp", "Home", "homeassistant", 8123, b"\x10version=2026.10.1", "192.0.2.20"),
            ("_smb._tcp", "nas", "nas", 445, b"", "192.0.2.10"),
            ("_googlecast._tcp", "Chromecast-00005e005301", "00005e005301", 8009,
             b"\x0fid=00005e005301\x0dmd=Chromecast\x11fn=Living Room TV", "192.0.2.40"),
            ("_bromigos-lab._tcp", "bromigOS lab on box1", "box1", 22, b"\x09txtvers=1", "198.51.100.7"),
            ("_ipp._tcp", "Office Printer", "printer", 631, b"\x17ty=Example LaserJet 400\x11serial=CN12345678",
             "192.0.2.50"),
            ("_http._tcp", "Cloud thing", "cloud", 80, b"", "203.0.113.9")):
        tl, server = f"{t}.local.", f"{host}.local."
        full = f"{inst}.{tl}"
        out += [rec(12, "_services._dns-sd._udp.local.", alias=tl), rec(12, tl, alias=full),
                rec(33, full, server=server, port=port), rec(16, full, text=txt),
                rec(1, server, address=socket.inet_aton(addr))]
    return out


class Private(unittest.TestCase):
    """Only private addresses are ever checked; the documentation ranges stand in for them."""

    def setUp(self):
        p = mock.patch.object(F, "PRIVATE", F.PRIVATE + DOC)
        p.start()
        self.addCleanup(p.stop)


# ------------------------------------------------------------------ parsing what was heard


class Parse(Private):
    def test_mdns_services_from_a_recorded_answer(self):
        svcs = {s["type"]: s for s in F.mdns_services(mdns_records())}
        self.assertEqual(svcs["_home-assistant._tcp"]["addresses"], ["192.0.2.20"])
        self.assertEqual(svcs["_home-assistant._tcp"]["port"], 8123)
        self.assertEqual(svcs["_bromigos-lab._tcp"]["server"], "box1.local")
        cast = svcs["_googlecast._tcp"]
        self.assertEqual(cast["instance"], "Chromecast")                    # the id is cut out of the name
        self.assertEqual(cast["txt"], {"md": "Chromecast", "fn": "Living Room TV"})   # no id, no bs
        self.assertEqual(svcs["_ipp._tcp"]["txt"], {"ty": "Example LaserJet 400"})   # no serial
        self.assertEqual(F.mdns_types(mdns_records()) >= {"_smb._tcp.local.", "_ipp._tcp.local."}, True)

    @unittest.skipUnless(zeroconf, "python-zeroconf isn't installed (CI installs it)")
    def test_the_recorded_packet_parses_with_zeroconf(self):
        self.assertEqual(len(F.mdns_services(mdns_records())), 6)

    def test_mdns_sightings_keep_no_ids(self):
        seen = F.mdns_observations(F.mdns_services(mdns_records()))
        text = json.dumps(seen)
        for bit in MAC_BITS:
            self.assertNotIn(bit, text)
        cast = next(o for o in seen if "_googlecast" in o["says"])
        self.assertEqual(cast["names"], [])                                  # its host name was only an id
        self.assertEqual(cast["label"], "Living Room TV")

    def test_ssdp(self):
        hue = F.ssdp_parse(fixture("ssdp-hue.txt", "rb"), "192.0.2.30")
        self.assertEqual(hue["addresses"], ["192.0.2.30"])
        self.assertIn("IpBridge", hue["says"])
        self.assertIn("hue-bridgeid", hue["says"])                          # the header's name, not its value
        self.assertNotIn("00005E", json.dumps(hue))
        self.assertNotIn("uuid", json.dumps(hue))
        nas = F.ssdp_parse(fixture("ssdp-synology.txt", "rb"), "192.0.2.10")
        self.assertEqual(F.recognise(nas["says"]), [("Synology NAS", "lab machine")])
        self.assertIn("MediaRenderer", F.ssdp_parse(fixture("ssdp-notify.txt", "rb"), "192.0.2.41")["says"])
        self.assertIsNone(F.ssdp_parse(fixture("ssdp-search.txt", "rb"), "192.0.2.42"))   # someone else's question

    def test_ws_discovery(self):
        cam = F.wsd_parse(fixture("wsd-probematch.xml", "rb"), "192.0.2.60")
        self.assertEqual(cam["addresses"], ["192.0.2.60", "2001:db8::60"])
        self.assertEqual(cam["label"], "Front Door IPC-EX100")
        self.assertEqual(cam["products"], ["ONVIF camera"])
        self.assertNotIn("urn:uuid", json.dumps(cam))
        self.assertNotIn("00005e", json.dumps(cam))
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'
        self.assertIsNone(F.wsd_parse(bomb, "192.0.2.61"))

    def test_the_neighbour_table(self):
        self.assertEqual(F.neigh_parse(fixture("ip-neigh.json")), ["192.0.2.1", "192.0.2.10", "fe80::1", "203.0.113.5"])
        self.assertEqual(F.arp_parse(fixture("proc-net-arp.txt")), ["192.0.2.1", "192.0.2.10"])
        sightings = [F.obs("neighbours", [a]) for a in F.neigh_parse(fixture("ip-neigh.json"))]
        self.assertNotIn("00:00:5e", json.dumps(sightings))

    def test_tailscale(self):
        peers = F.tailscale_parse(fixture("tailscale-status.json"))
        self.assertEqual(sorted(p["names"][0] for p in peers), ["gpu-box", "nas", "phone"])     # not Self
        self.assertTrue(all(p["tailnet"] for p in peers))
        phone = next(p for p in peers if p["names"][0] == "phone")
        self.assertIs(phone["online"], False)
        nas = next(p for p in peers if p["names"][0] == "nas")
        self.assertEqual(nas["names"], ["nas", "nas.example-tailnet.ts.net"])

    def test_ssh_config_hosts_only(self):
        pairs = F.ssh_parse(fixture("ssh_config"))
        self.assertEqual(pairs, [("gpu-box", "198.51.100.30"), ("gpu", "198.51.100.30"),
                                 ("build", "build.example.org"), ("cloud", "203.0.113.40")])
        path = os.path.join(FIX, "ssh_config")
        opened = []
        real_open = builtins.open

        def spy(p, *a, **kw):
            opened.append(str(p))
            return real_open(p, *a, **kw)
        with mock.patch.object(F, "resolve", lambda names, timeout=4.0: {"build.example.org": ["192.0.2.90"]}), \
                mock.patch("builtins.open", spy):
            seen = F.ssh_config(path)
        self.assertEqual(opened, [path])                       # that one file: Include isn't followed
        self.assertEqual([o["addresses"] for o in seen],
                         [["198.51.100.30"], ["198.51.100.30"], ["192.0.2.90"], ["203.0.113.40"]])

    def test_lab_sources(self):
        rows = L.rows_of(L.parse_prom(fixture("unifi-clients.prom")), "unpoller_client_uptime_seconds")
        clients = F.unifi_parse(rows)
        self.assertEqual([c["addresses"] for c in clients], [["192.0.2.70"], ["192.0.2.80"]])
        self.assertEqual(clients[1]["names"], ["media-pc"])
        self.assertNotIn("00:00:5e", json.dumps(clients))
        targets = F.prometheus_parse(json.loads(fixture("prometheus-targets.json")))
        self.assertEqual([(t["addresses"], t["names"]) for t in targets],
                         [(["192.0.2.10"], []), ([], ["gpu-box.example.org"]), (["198.51.100.5"], [])])   # no pods
        nodes = F.kube_parse(json.loads(fixture("kube-nodes.json")))
        self.assertEqual([(n["addresses"], n["names"]) for n in nodes],
                         [(["198.51.100.4"], ["control-1"]), (["198.51.100.5"], ["worker-1"])])
        vm = F.proxmox_parse("media-vm", json.loads(fixture("proxmox-agent.json")))
        self.assertEqual(vm[0]["addresses"], ["198.51.100.21"])
        self.assertNotIn("00:00:5e", json.dumps(vm))

    def test_lab_sources_go_through_the_configured_adapters_only(self):
        class Prom:
            type = "prometheus"

            def get_json(self, path, timeout=8):
                self.path = path
                return json.loads(fixture("prometheus-targets.json"))
        p = Prom()
        with mock.patch.object(F, "resolve", lambda names, timeout=4.0: {}):
            got = F.lab_known([p])
        self.assertEqual(p.path, "/api/v1/targets?state=active")
        self.assertEqual(len(got["prometheus"]), 3)
        self.assertEqual(F.lab_known([]), {})                                # nothing configured: nothing read


# ------------------------------------------------------------------ one record per host, and its kind


def sightings():
    out = F.mdns_observations(F.mdns_services(mdns_records()))
    out.append(F.ssdp_parse(fixture("ssdp-synology.txt", "rb"), "192.0.2.10"))
    out.append(F.ssdp_parse(fixture("ssdp-hue.txt", "rb"), "192.0.2.30"))
    out.append(F.wsd_parse(fixture("wsd-probematch.xml", "rb"), "192.0.2.60"))
    out += [F.obs("neighbours", [a]) for a in F.neigh_parse(fixture("ip-neigh.json"))]
    out += F.tailscale_parse(fixture("tailscale-status.json"))
    out.append(F.obs("dns", ["192.0.2.10"], ["nas.example.org"]))
    out.append(F.obs("dns", ["192.0.2.95"], ["rosbridge.example.org"]))
    return out


class Merge(Private):
    def hosts(self):
        hosts, ignored = F.merge(sightings(), own={"192.0.2.250"}, gateway="192.0.2.1")
        return {h["name"]: h for h in hosts}, ignored

    def test_one_record_per_host(self):
        hosts, _ = self.hosts()
        nas = hosts["nas.example.org"]
        # mDNS's nas.local, UPnP, the neighbour table, DNS and the tailnet's nas are one host
        self.assertEqual(nas["sources"], ["mdns", "ssdp", "neighbours", "dns", "tailscale"])
        self.assertEqual(nas["addresses"][:2], ["192.0.2.10", "100.100.0.10"])
        self.assertTrue(nas["tailnet"])
        self.assertIsNone(nas["online"])                    # seen on the network, not just on the tailnet
        self.assertEqual(len([h for h in hosts.values() if "192.0.2.10" in h["addresses"]]), 1)

    def test_kinds(self):
        hosts, _ = self.hosts()
        kind = {h["addresses"][0]: h["kind"] for h in hosts.values()}
        self.assertEqual(kind["192.0.2.10"], "lab machine")           # Synology, file shares
        self.assertEqual(kind["198.51.100.7"], "lab machine")         # announces _bromigos-lab._tcp
        self.assertEqual(kind["192.0.2.20"], "smart home")            # Home Assistant
        self.assertEqual(kind["192.0.2.30"], "smart home")            # Hue
        self.assertEqual(kind["192.0.2.40"], "media")                 # Chromecast
        self.assertEqual(kind["192.0.2.50"], "printer")
        self.assertEqual(kind["192.0.2.60"], "camera")                # ONVIF
        self.assertEqual(kind["192.0.2.95"], "robot")                 # by its name
        self.assertEqual(kind["192.0.2.1"], "other")
        self.assertIn("router", next(h for h in hosts.values() if h["addresses"][0] == "192.0.2.1")["products"])
        self.assertEqual(F.classify([("Plex", "media"), ("Synology NAS", "lab machine")]), "lab machine")
        self.assertEqual(F.classify([]), "other")
        self.assertEqual(set(F.KINDS), {"lab machine", "smart home", "camera", "robot", "printer", "media", "other"})

    def test_offline_tailnet_devices_are_marked(self):
        hosts, _ = self.hosts()
        self.assertIs(hosts["phone"]["online"], False)

    def test_no_ids_in_the_records(self):
        hosts, _ = self.hosts()
        text = json.dumps(list(hosts.values()))
        for bit in MAC_BITS:
            self.assertNotIn(bit, text)


class PublicAddresses(Private):
    def test_allowed(self):
        self.assertTrue(F.allowed("192.0.2.1"))
        self.assertTrue(F.allowed(str(F.PRIVATE[0][5])))
        self.assertTrue(F.allowed("fd7a:115c:a1e0::10"))
        self.assertFalse(F.allowed("203.0.113.9"))
        self.assertFalse(F.allowed("fe80::1"))
        self.assertFalse(F.allowed("2001:db8::60"))
        self.assertFalse(F.allowed("not-an-address"))
        self.assertFalse(F.allowed("100.100.0.10"))                     # CGNAT: only on a tailnet
        self.assertTrue(F.allowed("100.100.0.10", tailnet=True))

    def test_the_documentation_ranges_are_only_private_in_these_tests(self):
        with mock.patch.object(F, "PRIVATE", F.PRIVATE[:4]):
            self.assertFalse(F.allowed("192.0.2.1"))

    def test_public_addresses_are_dropped_and_counted(self):
        hosts, ignored = F.merge(sightings())
        every = {a for h in hosts for a in h["addresses"]}
        self.assertNotIn("203.0.113.9", every)                          # the mDNS one
        self.assertNotIn("203.0.113.5", every)                          # the neighbour
        self.assertNotIn("2001:db8::60", every)                         # the camera's second address
        self.assertEqual(ignored, 3)

    def test_check_refuses_a_public_address(self):
        called = []
        host = {"name": "cloud", "names": [], "addresses": ["203.0.113.9"], "tailnet": False, "kind": "other",
                "services": [], "checked": "", "online": None}
        F.check([host], lambda a: called.append(a) or [], names=lambda n: {})
        self.assertEqual(called, [])
        self.assertIn("no private IPv4", host["checked"])


# ------------------------------------------------------------------ checking only what was found


def load_setup():
    path = os.path.join(os.path.dirname(HERE), "bin", "bromigos-setup-homelab")
    loader = importlib.machinery.SourceFileLoader("setup_homelab_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class OnlyWhatWasFound(Private):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(F, "PACE", F.Pace(100000))
        p.start()
        self.addCleanup(p.stop)

    def test_check_runs_the_finder_on_found_hosts_only(self):
        hosts, _ = F.merge(sightings(), gateway="192.0.2.1")
        called = []

        def finder(addr):
            called.append(addr)
            return [{"type": "prometheus", "endpoint": f"http://{addr}:9090"}] if addr == "192.0.2.10" else []
        F.check(hosts, finder, names=lambda n: {"nas.example.org": ["192.0.2.10"]})
        found = {a for h in hosts for a in h["addresses"]}
        self.assertTrue(set(called) <= found)
        # cameras, printers, robots, smart-home devices and media players aren't checked; nor is
        # the offline phone
        self.assertEqual(sorted(called), ["100.100.0.30", "192.0.2.1", "192.0.2.10", "198.51.100.7"])
        for skipped in ("192.0.2.20", "192.0.2.30", "192.0.2.40", "192.0.2.50", "192.0.2.60", "192.0.2.95",
                        "100.100.0.20"):
            self.assertNotIn(skipped, called)
        nas = next(h for h in hosts if "192.0.2.10" in h["addresses"])
        self.assertEqual(nas["services"], [{"type": "prometheus", "endpoint": "http://nas.example.org:9090"}])

    def test_no_connection_goes_anywhere_no_source_found(self):
        """The real per-host check (setup's host_finds), with every connection recorded."""
        S = load_setup()
        hosts, _ = F.merge(sightings(), gateway="192.0.2.1")
        tried = []

        def connect(addr, timeout=None, *a, **kw):
            tried.append(addr)
            raise OSError("refused (test)")
        with mock.patch.object(socket, "create_connection", connect):
            F.check(hosts, S.host_finds, names=lambda n: {})
        self.assertTrue(tried)
        found = {a for h in hosts if F.checkable(h) and h["online"] is not False for a in h["addresses"]}
        self.assertTrue({host for host, _port in tried} <= found)
        self.assertNotIn("192.0.2.99", {h for h, _p in tried})            # a failed neighbour entry
        # each port once per host, however many adapters share it
        self.assertEqual(len(tried), len(set(tried)))

    def test_ssh_boxes_knock_on_found_hosts_only(self):
        """`bromigos lab provision`'s step 3: port 22 on the machines found, nothing else."""
        hosts, _ = F.merge(sightings(), gateway="192.0.2.1")
        tried = []

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def connect(addr, timeout=None, *a, **kw):
            tried.append(addr)
            if addr[0] != "192.0.2.10":
                raise OSError("refused (test)")
            return Conn()
        with mock.patch.object(socket, "create_connection", connect):
            boxes = F.ssh_boxes(hosts, names=lambda n: {"nas.example.org": ["192.0.2.10"]})
        self.assertEqual([b["ssh"] for b in boxes], ["nas.example.org"])
        self.assertEqual({p for _a, p in tried}, {22})
        self.assertEqual(sorted(a for a, _p in tried), ["100.100.0.30", "192.0.2.1", "192.0.2.10", "198.51.100.7"])

    def test_finding_itself_connects_to_nothing(self):
        """Reading the sources opens no connection: only the multicast questions are sent."""
        def boom(*a, **kw):
            raise AssertionError("find() must not connect to a host")
        with mock.patch.object(socket, "create_connection", boom), \
                mock.patch.object(F, "mdns_listen", lambda s: mdns_records()), \
                mock.patch.object(F, "ssdp_listen", lambda s: []), mock.patch.object(F, "wsd_listen", lambda s: []), \
                mock.patch.object(F, "neighbours", lambda: (F.neigh_parse(fixture("ip-neigh.json")), "192.0.2.1")), \
                mock.patch.object(F, "tailscale", lambda: None), mock.patch.object(F, "reverse", lambda a: {}), \
                mock.patch.object(F, "own_addresses", lambda: set()):
            lab = F.find(ssh=False, lab=False)
        self.assertEqual(lab["sources"]["mdns"], 6)
        self.assertEqual(lab["sources"]["tailscale"], "Tailscale isn't installed")
        self.assertEqual(lab["sources"]["ssh"], "not read (no yes for it)")
        self.assertNotIn("prometheus", lab["sources"])

    def test_ssh_config_is_read_only_after_its_own_yes(self):
        read = []
        with mock.patch.object(F, "ssh_config", lambda path=None: read.append(1) or []), \
                mock.patch.object(F, "mdns_listen", lambda s: None), mock.patch.object(F, "ssdp_listen", lambda s: []), \
                mock.patch.object(F, "wsd_listen", lambda s: []), mock.patch.object(F, "neighbours", lambda: ([], "")), \
                mock.patch.object(F, "tailscale", lambda: None), mock.patch.object(F, "reverse", lambda a: {}), \
                mock.patch.object(F, "own_addresses", lambda: set()):
            F.find(ssh=False, lab=False)
            self.assertEqual(read, [])
            F.find(ssh=True, lab=False)
            self.assertEqual(read, [1])

    def test_redirects_stay_on_the_host(self):
        import urllib.request
        h = urllib.request.HTTPRedirectHandler()
        req = urllib.request.Request("http://192.0.2.10:9090/api")
        with F.same_host_redirects():
            self.assertIsNone(h.redirect_request(req, None, 302, "Found", {}, "https://203.0.113.9/"))
            self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "http://192.0.2.10:9090/api/"))
        self.assertIsNotNone(h.redirect_request(req, None, 302, "Found", {}, "https://203.0.113.9/"))


# ------------------------------------------------------------------ the yes questions, and the file


class Tty(io.StringIO):
    def __init__(self, tty):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty


LAB = {"hosts": [{"name": "nas.example.org", "names": ["nas.example.org"], "labels": [], "addresses": ["192.0.2.10"],
                  "sources": ["mdns"], "tailnet": False, "online": None, "products": ["Synology NAS"],
                  "kind": "lab machine", "services": [], "checked": ""}],
       "sources": {"mdns": 1}, "ignored": 0}


class Setup(Private):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.user = os.path.join(self.tmp.name, "homelab.toml")
        saved = config.USER
        config.USER = self.user
        config._cache.update(sig=None)

        def restore():
            config.USER = saved
            config._cache.update(sig=None)
        self.addCleanup(restore)
        env = mock.patch.dict(os.environ, {"BROMIGOS_HOMELAB_PLUGINS": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.S = load_setup()
        self.S.ask_kube = lambda: ""                                    # whatever kubectl this machine has
        self.calls = []

        def find(ssh=False, lab=True, seconds=3.0, log=None):
            self.calls.append(ssh)
            return json.loads(json.dumps(LAB))
        p = mock.patch.object(F, "find", find)
        p.start()
        self.addCleanup(p.stop)
        self.S.host_finds = lambda addr: [{"type": "prometheus", "endpoint": f"http://{addr}:9090"}]
        p2 = mock.patch.object(F, "resolve", lambda names, timeout=4.0: {"nas.example.org": ["192.0.2.10"]})
        p2.start()
        self.addCleanup(p2.stop)

    def run_setup(self, argv, tty=False, answers=()):
        answers = list(answers)
        asked = []

        def fake_input(q=""):
            asked.append(q)
            return answers.pop(0) if answers else ""
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["bromigos-setup-homelab", "--no-local", "--no-detect"] + argv), \
                mock.patch.object(sys, "stdin", Tty(tty)), mock.patch("builtins.input", fake_input), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = self.S.main()
        return code, asked, out.getvalue()

    def test_no_yes_no_reading(self):
        code, asked, _ = self.run_setup(["--find"], tty=False)
        self.assertEqual((code, self.calls), (2, []))                   # no terminal to ask in, no --yes
        code, asked, _ = self.run_setup(["--find"], tty=True, answers=["n"])
        self.assertEqual((code, self.calls), (1, []))
        self.assertIn("Look for your lab", asked[0])
        self.assertFalse(os.path.exists(self.user))

    def test_the_question_names_the_sources(self):
        _code, _asked, out = self.run_setup(["--find", "--print"], tty=True, answers=["n"])
        self.assertIn("devices that announce themselves", out)
        self.assertIn("neighbour table", out)
        self.assertNotIn("ssh", out.split("Look for")[0].lower())       # that one has its own question

    def test_yes_for_scripts_never_reads_ssh_config(self):
        code, asked, _ = self.run_setup(["--find", "--yes", "--print"], tty=True)
        self.assertEqual((code, asked, self.calls), (0, [], [False]))
        self.run_setup(["--find", "--yes", "--ssh-config", "--print"], tty=False)
        self.assertEqual(self.calls, [False, True])

    def test_ssh_config_has_its_own_question(self):
        _c, asked, _ = self.run_setup(["--find", "--print"], tty=True, answers=["y", "n"])
        self.assertIn("~/.ssh/config", asked[1])
        self.assertEqual(self.calls, [False])
        self.run_setup(["--find", "--print"], tty=True, answers=["y", "y"])
        self.assertEqual(self.calls, [False, True])

    def test_the_interactive_default_offers_it_first(self):
        _c, asked, _ = self.run_setup([], tty=True, answers=["n", "", "n"])
        self.assertIn("Look for your lab", asked[0])
        self.assertIn("Hosts or URLs", asked[1])                        # a no: the old question
        self.assertEqual(self.calls, [])

    def test_append_only(self):
        mine = ('# my lab, by hand\nname = "Orbit"\n\n[[source]]\nname = "metrics"\ntype = "prometheus"\n'
                'endpoint = "http://198.51.100.9:9090"   # mine\n')
        with open(self.user, "w") as f:
            f.write(mine)
        config._cache.update(sig=None)
        code, _asked, out = self.run_setup(["--find", "--yes"])
        self.assertEqual(code, 0, out)
        text = open(self.user).read()
        self.assertTrue(text.startswith(mine))                          # untouched, then appended
        self.assertIn('endpoint = "http://nas.example.org:9090"', text[len(mine):])
        self.assertIn('name = "prometheus"', text[len(mine):])
        config._cache.update(sig=None)
        code, _asked, out = self.run_setup(["--find", "--yes"])
        self.assertEqual(open(self.user).read(), text)                  # again: nothing new
        self.assertIn("Nothing new", out)

    def test_the_checklist_adds_what_was_picked(self):
        self.S.host_finds = lambda addr: [{"type": "prometheus", "endpoint": f"http://{addr}:9090"},
                                          {"type": "netdata", "endpoint": f"http://{addr}:19999"}]
        code, asked, out = self.run_setup(["--find"], tty=True, answers=["y", "n", "2"])
        self.assertEqual(code, 0, out)
        self.assertIn("Add which", asked[2])
        text = open(self.user).read()
        self.assertIn("netdata", text)
        self.assertNotIn("prometheus", text)
        self.assertIn("found, not supported yet: Synology NAS", out)

    def test_json(self):
        code, _asked, out = self.run_setup(["--find", "--yes", "--json"])
        doc = json.loads(out)
        self.assertEqual(doc["lab"]["hosts"][0]["services"][0]["endpoint"], "http://nas.example.org:9090")
        self.assertEqual(doc["new"], doc["found"])
        self.assertFalse(os.path.exists(self.user))


class Announce(unittest.TestCase):
    """`bromigos lab provision` makes a box announce _bromigos-lab._tcp, which Find my lab knows."""

    def test_a_box_announces_itself(self):
        from bromigos_homelab import announce as N, provision as P, services as S
        target = {"kind": "ssh", "ssh": "tester@lab.example.org", "port": 2222, "identity": ""}
        facts = {"cpu": 8, "ram_gib": 32, "disk_gib": 500, "distribution": "arch", "gpu": "none", "vram_gib": 0}
        files, _ = P.plan_files(target, P.preset_selection(S.load(), "core"), facts, backup_path="/mnt/backups",
                                age_recipient="age1example")
        self.assertIn("announce", json.loads(files["ansible/playbooks/provision.json"])[0]["roles"])
        xml = files["ansible/roles/announce/files/bromigos-lab.service"]
        self.assertIn("<type>_bromigos-lab._tcp</type>", xml)
        self.assertIn("<port>2222</port>", xml)
        self.assertEqual(xml.count("<txt-record>"), 1)                 # txtvers=1, nothing else on the network
        tasks = json.loads(files["ansible/roles/announce/tasks/main.json"])
        self.assertEqual(tasks[0]["ansible.builtin.package"]["name"], ["avahi"])
        self.assertEqual(tasks[-1]["ansible.builtin.systemd"]["name"], "avahi-daemon")
        self.assertEqual(F.recognise(N.SERVICE), [("bromigOS lab box", "lab machine")])

    def test_an_existing_cluster_does_not(self):
        from bromigos_homelab import announce as N
        files, roles = {}, []
        N.plan(files, {"target": {"kind": "cluster"}, "inventory": {"distribution": "debian"}}, roles)
        self.assertEqual((files, roles), ({}, []))


class Optional(unittest.TestCase):
    def test_zeroconf_is_optional(self):
        real = builtins.__import__

        def no_zeroconf(name, *a, **kw):
            if name == "zeroconf":
                raise ImportError("not installed (test)")
            return real(name, *a, **kw)
        with mock.patch("builtins.__import__", no_zeroconf):
            self.assertIsNone(F.mdns_listen(0.01))


if __name__ == "__main__":
    unittest.main()
