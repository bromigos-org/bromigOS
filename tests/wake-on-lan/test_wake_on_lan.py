"""Wake-on-LAN (docs/wake-on-lan.md): the files bromigos-core ships, `bromigos wol`
against a fake /sys with stand-in ethtool and nmcli, and the update's migration with stand-in
commands. Nothing here touches a real network card, NetworkManager or sudo."""
import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'lib'))
import bromigos_wol as wol  # noqa: E402

PKG = ROOT / 'packaging' / 'bromigos-core'
MIGRATION = ROOT / 'migrations' / '20261031120000-wake-on-lan.sh'


class Shipped(unittest.TestCase):
    def test_networkmanager_default_is_magic_for_wired_only(self):
        c = configparser.ConfigParser()
        c.read(PKG / '50-bromigos-wake-on-lan.conf')
        sec = c['connection-bromigos-wake-on-lan']
        self.assertEqual(sec['match-device'], 'type:ethernet')
        # NetworkManager's "magic" flag (nm-settings-nmcli(5): 0x40)
        self.assertEqual(int(sec['ethernet.wake-on-lan']), 0x40)

    def test_the_rule_is_for_real_wired_cards(self):
        rule = (PKG / '81-bromigos-wake-on-lan.rules').read_text()
        lines = [l for l in rule.splitlines() if l and not l.startswith('#')]
        self.assertIn('ACTION!="add", GOTO="bromigos_wake_on_lan_end"', lines)
        self.assertIn('ATTR{type}!="1", GOTO="bromigos_wake_on_lan_end"', lines)
        self.assertIn('ENV{DEVTYPE}=="wlan", GOTO="bromigos_wake_on_lan_end"', lines)
        self.assertIn('TEST!="device", GOTO="bromigos_wake_on_lan_end"', lines)
        self.assertIn('TEST=="device/power/wakeup", ATTR{device/power/wakeup}="enabled"', lines)
        self.assertIn('RUN+="/usr/bin/ethtool -s $name wol g"', lines)
        self.assertEqual(lines[-1], 'LABEL="bromigos_wake_on_lan_end"')

    @unittest.skipUnless(shutil.which('udevadm'), 'no udevadm')
    def test_udev_reads_the_rule(self):
        r = subprocess.run(['udevadm', 'verify', '--no-style', str(PKG / '81-bromigos-wake-on-lan.rules')],
                           capture_output=True, text=True)
        if 'Unknown command' in r.stderr or 'invalid option' in r.stderr:
            self.skipTest('this udevadm has no verify')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_package_installs_them_where_brodec_looks(self):
        pkgbuild = (PKG / 'PKGBUILD').read_text()
        # brodec-machine reads this exact path as "bromigOS keeps Wake-on-LAN on"
        self.assertIn('"$pkgdir/usr/lib/udev/rules.d/81-bromigos-wake-on-lan.rules"', pkgbuild)
        self.assertIn('"$pkgdir/usr/lib/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf"', pkgbuild)
        self.assertIn("'ethtool'", pkgbuild)
        self.assertIn('install=$pkgname.install', pkgbuild)
        self.assertIn('bromigos-wol apply --quiet || true', (PKG / 'bromigos-core.install').read_text())


ETHTOOL_ON = 'Settings for enp6s0:\n\tSupports Wake-on: pumbg\n\tWake-on: g\n'
ETHTOOL_OFF = 'Settings for enp6s0:\n\tSupports Wake-on: pumbg\n\tWake-on: d\n'


class Helper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='bromigos-wol-test-')
        self.addCleanup(self.tmp.cleanup)
        self.paths = wol.Paths(self.tmp.name)
        self.card('enp6s0', wired=True, carrier=False, wakeup='disabled')
        self.card('wlan0', wired=False, carrier=True, wakeup='disabled')
        # a container's veth: no device behind it
        veth = self.paths.sys_net / 'veth0'
        veth.mkdir(parents=True)
        (veth / 'type').write_text('1\n')
        self.put('/usr/bin/ethtool', '# stand-in; never run\n')
        self.calls = []
        self.ethtool_out = ETHTOOL_OFF

    def put(self, path, text):
        p = self.paths.at(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def card(self, name, wired, carrier, wakeup):
        d = self.paths.sys_net / name
        (d / 'device' / 'power').mkdir(parents=True)
        (d / 'type').write_text('1\n')
        (d / 'carrier').write_text('1\n' if carrier else '0\n')
        (d / 'device' / 'power' / 'wakeup').write_text(wakeup + '\n')
        if not wired:
            (d / 'wireless').mkdir()

    def runner(self, argv):
        self.calls.append([Path(argv[0]).name] + argv[1:])
        if Path(argv[0]).name == 'ethtool' and len(argv) == 2:
            return SimpleNamespace(returncode=0, stdout=self.ethtool_out, stderr='')
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    def test_only_the_wired_card_counts(self):
        self.assertEqual([c['name'] for c in wol.wired_cards(self.paths)], ['enp6s0'])

    def test_status_reads_ethtool(self):
        s = wol.status(self.paths, self.runner)
        self.assertEqual(s['cards'][0]['on'], False)
        self.assertEqual(s['cards'][0]['supports'], 'pumbg')
        self.assertFalse(s['kept_on'])          # no rule in this fake root
        self.put(wol.RULE, '# rule\n')
        self.ethtool_out = ETHTOOL_ON
        s = wol.status(self.paths, self.runner)
        self.assertTrue(s['kept_on'] and s['cards'][0]['on'])

    def test_apply_turns_it_on_and_is_idempotent(self):
        self.put('/run/NetworkManager/.keep', '')
        orig = wol.shutil.which
        wol.shutil.which = lambda n: '/usr/bin/nmcli' if n == 'nmcli' else orig(n)
        self.addCleanup(setattr, wol.shutil, 'which', orig)
        done = wol.apply(self.paths, self.runner)
        wakeup = self.paths.sys_net / 'enp6s0' / 'device' / 'power' / 'wakeup'
        self.assertEqual(wakeup.read_text().strip(), 'enabled')
        self.assertIn(['ethtool', '-s', 'enp6s0', 'wol', 'g'], self.calls)
        self.assertIn(['nmcli', 'general', 'reload', 'conf'], self.calls)
        # Wi-Fi is never touched
        self.assertEqual((self.paths.sys_net / 'wlan0' / 'device' / 'power' / 'wakeup').read_text().strip(), 'disabled')
        self.assertFalse(any('wlan0' in c for c in self.calls))
        self.assertTrue(any('Wake-on-LAN on' in d for d in done))
        # again: the same end state, nothing new written
        before = wakeup.stat().st_mtime_ns
        wol.apply(self.paths, self.runner)
        self.assertEqual(wakeup.stat().st_mtime_ns, before)

    def test_apply_records_the_cards_for_the_user(self):
        self.ethtool_out = ETHTOOL_ON
        wol.apply(self.paths, self.runner)
        rec_path = self.paths.at(wol.RECORD)
        rec = json.loads(rec_path.read_text())
        self.assertEqual(rec['schema'], 1)
        self.assertEqual([c['name'] for c in rec['cards']], ['enp6s0'])
        self.assertEqual((rec['cards'][0]['supports'], rec['cards'][0]['wake_on']), ('pumbg', 'g'))
        self.assertTrue(rec['cards'][0]['on'])
        self.assertEqual(rec_path.stat().st_mode & 0o777, 0o644)
        self.assertNotIn('sopass', rec_path.read_text())

    def test_record_needs_root_and_the_rule_runs_it(self):
        if os.geteuid() != 0:
            self.assertEqual(wol.main(['record'], self.paths, self.runner), 1)
        rule = (PKG / '81-bromigos-wake-on-lan.rules').read_text()
        self.assertIn('RUN+="/usr/lib/bromigos/bin/bromigos-wol record"', rule)
        self.assertLess(rule.index('wol g"'), rule.index('bromigos-wol record'))

    def test_a_masked_rule_turns_it_off(self):
        etc = self.paths.at(wol.RULE_ETC)
        etc.parent.mkdir(parents=True)
        etc.symlink_to('/dev/null')
        done = wol.apply(self.paths, self.runner)
        self.assertEqual(self.calls, [])
        self.assertIn('turned off', done[0])

    def test_no_wired_card_is_fine(self):
        shutil.rmtree(self.paths.sys_net / 'enp6s0')
        self.assertIn('no wired network card', wol.apply(self.paths, self.runner)[-1])

    def test_apply_needs_root(self):
        if os.geteuid() == 0:
            self.skipTest('running as root')
        code = wol.main(['apply'], self.paths, self.runner)
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])

    def test_status_json(self):
        import io
        from contextlib import redirect_stdout
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(wol.main(['status', '--json'], self.paths, self.runner), 0)
        self.assertEqual(json.loads(out.getvalue())['cards'][0]['name'], 'enp6s0')


class Migration(unittest.TestCase):
    """migrations/20261031120000-wake-on-lan.sh with stand-in bromigos, helper and sudo."""

    def run_it(self, cards, sudo_ok, helper=True):
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, 'sudo.log')
            state = json.dumps({'schema': 1, 'opted_out': False, 'cards': cards})
            bodies = {
                'bromigos': 'exit 0',
                'sudo': f'echo "$*" >> {log}; [ "$1" = -n ] && [ "$2" = true ] && exit {0 if sudo_ok else 1}; exit 0',
                'helper': f"[ \"$1\" = status ] && echo '{state}'; exit 0",
            }
            for name, body in bodies.items():
                p = os.path.join(d, name)
                with open(p, 'w') as f:
                    f.write(f'#!/bin/sh\n{body}\n')
                os.chmod(p, 0o755)
            env = {'PATH': d + ':/usr/bin:/bin', 'HOME': d,
                   'BROMIGOS_WOL_HELPER': os.path.join(d, 'helper' if helper else 'missing')}
            r = subprocess.run(['bash', str(MIGRATION)], capture_output=True, text=True, env=env)
            calls = Path(log).read_text() if os.path.exists(log) else ''
        return r.returncode, r.stdout, calls

    def test_on_already_is_done(self):
        code, out, calls = self.run_it([{'name': 'enp6s0', 'on': True}], True)
        self.assertEqual(code, 0)
        self.assertIn('kept on', out)
        self.assertEqual(calls, '')

    def test_off_with_passwordless_sudo_turns_it_on(self):
        code, out, calls = self.run_it([{'name': 'enp6s0', 'on': False}], True)
        self.assertEqual(code, 0)
        self.assertIn('apply --quiet enp6s0', calls)
        self.assertIn('turned on for: enp6s0', out)

    def test_off_without_sudo_asks_nothing_and_finishes(self):
        code, out, calls = self.run_it([{'name': 'enp6s0', 'on': False}], False)
        self.assertEqual(code, 0)
        self.assertNotIn('apply', calls)
        self.assertIn('next start', out)

    def test_no_wired_card(self):
        self.assertEqual(self.run_it([], True)[0], 0)

    def test_not_installed_yet_waits(self):
        self.assertEqual(self.run_it([], True, helper=False)[0], 75)


if __name__ == '__main__':
    unittest.main()
