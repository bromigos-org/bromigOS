"""The web apps' names on the local network (mdnsnames.py, localprovision.caddy_routes): one
label each (photos-box.local), unique, served by Caddy and published over mDNS, following the
server's address. No network, no avahi."""
import re
import tempfile
import unittest
from pathlib import Path

from bromigos_homelab import localprovision as L, mdnsnames as M, secretstore as S
from provfake import FakeMachine

HW = {"cpu": 8, "ram_gb": 32, "disk_gb": 900, "gpu": False, "gpu_vram_gb": 0, "gpu_name": ""}
WEB_ITEMS = ["caddy", "start-page", "home-automation", "jellyfin", "passwords", "photos"]


class Names(unittest.TestCase):
    def test_every_web_app_has_its_own_name(self):
        self.assertEqual(len(set(L.WEB.values())), len(L.WEB), "two apps would share a name")

    def test_apply_writes_one_label_names_for_caddy_and_mdns(self):
        with tempfile.TemporaryDirectory() as root:
            m = FakeMachine(root)
            plan = L.build_plan(WEB_ITEMS, ["home-services"], "none", {}, [], {}, HW)
            host = L.Host(plan, root=root, run_=m, online=lambda: True, sleep=lambda s: None,
                          store=S.LocalStore(root, m, "box"), emit=lambda l: None, hw=HW, hostname="box",
                          tz="America/Los_Angeles")
            L.Runner(host, poll=1).run()
            names = Path(root, "etc/bromigos/lab/mdns-names").read_text().split()
            caddy = Path(root, "etc/caddy/conf.d/bromigos-lab.caddy").read_text()
            unit = Path(root, "etc/systemd/system/bromigos-lab-mdns-names.service").read_text()
        self.assertTrue(names)
        self.assertEqual(len(names), len(set(names)))
        for n in names:
            self.assertRegex(n, r"^[a-z0-9-]+-box\.local$")       # one label before .local
            self.assertIn(n + " {", caddy)
        self.assertIn("photos-box.local", names)
        self.assertIn("automation-box.local", names)
        self.assertIn("home-box.local", names)
        self.assertFalse(re.search(r"\b[a-z0-9-]+\.box\.local\b", caddy), "a subdomain name crept back in")
        self.assertIn("ExecStart=/usr/lib/bromigos/bin/bromigos-lab mdns-names publish", unit)
        self.assertIn("Requires=avahi-daemon.service", unit)


class Publisher(unittest.TestCase):
    class Proc:
        def __init__(self, argv):
            self.argv, self.ended = argv, False

        def poll(self):
            return 0 if self.ended else None

        def terminate(self):
            self.ended = True

        def wait(self, timeout=None):
            return 0

    def test_publishes_each_name_and_follows_the_address(self):
        addrs = iter(["198.51.100.10", "198.51.100.10", "198.51.100.11", None])
        spawned = []

        def spawn(argv):
            p = self.Proc(argv)
            spawned.append(p)
            return p
        pub = M.Publisher(["photos-box.local", "media-box.local"], spawn=spawn, address=lambda: next(addrs))
        pub.tick()
        self.assertEqual([p.argv for p in spawned], [
            ["avahi-publish", "--address", "--no-reverse", "photos-box.local", "198.51.100.10"],
            ["avahi-publish", "--address", "--no-reverse", "media-box.local", "198.51.100.10"]])
        pub.tick()                                    # same address: nothing new
        self.assertEqual(len(spawned), 2)
        pub.tick()                                    # a new address: the old ones end, new ones start
        self.assertTrue(all(p.ended for p in spawned[:2]))
        self.assertEqual([p.argv[-1] for p in spawned[2:]], ["198.51.100.11"] * 2)
        pub.tick()                                    # no address: nothing published
        self.assertTrue(all(p.ended for p in spawned))
        self.assertEqual(pub.procs, [])

    def test_a_publisher_that_ends_is_started_again(self):
        spawned = []

        def spawn(argv):
            p = self.Proc(argv)
            spawned.append(p)
            return p
        pub = M.Publisher(["photos-box.local"], spawn=spawn, address=lambda: "198.51.100.10")
        pub.tick()
        spawned[0].ended = True                       # avahi restarted under it
        pub.tick()
        self.assertEqual(len(spawned), 2)

    def test_primary_address_from_the_default_route(self):
        class R:
            def __init__(self, out):
                self.stdout = out
        run = lambda argv, **kw: R("1.1.1.1 via 198.51.100.1 dev enp3s0 src 198.51.100.10 uid 0\n    cache\n")
        self.assertEqual(M.primary_ipv4(run), "198.51.100.10")


if __name__ == "__main__":
    unittest.main()
