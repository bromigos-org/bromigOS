"""Wake-on-LAN for this machine's wired network cards (docs/wake-on-lan.md).

bromigos-core ships the policy: NetworkManager's default for wired connections
(`/usr/lib/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf`) and a udev rule
(`/usr/lib/udev/rules.d/81-bromigos-wake-on-lan.rules`) that turns it on for each wired
card as it appears. This module reads where things stand (`bromigos wol status`)
and turns it on now for the cards already there (`apply`: the package's install step and
the update's migration run it as root).

Only real wired Ethernet cards count: type 1, a device behind it, not Wi-Fi.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

NM_CONF = '/usr/lib/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf'
NM_CONF_ETC = '/etc/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf'
RULE = '/usr/lib/udev/rules.d/81-bromigos-wake-on-lan.rules'
RULE_ETC = '/etc/udev/rules.d/81-bromigos-wake-on-lan.rules'


class Error(Exception):
    pass


class Paths:
    """Every path this module reads or writes, under `root` (tests use a temporary one)."""

    def __init__(self, root='/'):
        self.root = Path(root)

    def at(self, path):
        return self.root / str(path).lstrip('/')

    @property
    def sys_net(self):
        return self.at('/sys/class/net')


def _read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=20, check=False)


def wired_cards(paths):
    """The wired Ethernet cards, by name, with what sysfs says about each."""
    out = []
    try:
        names = sorted(p.name for p in paths.sys_net.iterdir())
    except OSError:
        return out
    for name in names:
        d = paths.sys_net / name
        if name == 'lo' or not (d / 'device').exists():
            continue
        if _read(d / 'type') != '1' or (d / 'wireless').exists() or (d / 'phy80211').exists():
            continue
        out.append({
            'name': name,
            'carrier': _read(d / 'carrier') == '1',
            'wakeup': _read(d / 'device' / 'power' / 'wakeup'),
        })
    return out


def opted_out(paths):
    """The udev rule is masked in /etc (an empty file, or a link to /dev/null)."""
    etc = paths.at(RULE_ETC)
    if not (etc.exists() or etc.is_symlink()):
        return False
    try:
        return os.path.realpath(etc) == '/dev/null' or etc.stat().st_size == 0
    except OSError:
        return True


def _ethtool(paths):
    p = paths.at('/usr/bin/ethtool')
    return str(p) if p.exists() else shutil.which('ethtool')


def wake_on(name, paths, runner=_run):
    """What ethtool says for a card: (supports, wake_on), letters like `pumbg` and `g`."""
    tool = _ethtool(paths)
    if not tool:
        return None, None
    r = runner([tool, name])
    supports = wake = None
    for line in (r.stdout or '').splitlines():
        line = line.strip()
        if line.startswith('Supports Wake-on:'):
            supports = line.split(':', 1)[1].strip()
        elif line.startswith('Wake-on:'):
            wake = line.split(':', 1)[1].strip()
    return supports, wake


def status(paths, runner=_run):
    cards = []
    for c in wired_cards(paths):
        supports, wake = wake_on(c['name'], paths, runner)
        c.update({'supports': supports, 'wake_on': wake,
                  'on': ('g' in wake) if wake is not None else None})
        cards.append(c)
    nm_shadowed = paths.at(NM_CONF_ETC).exists()
    return {
        'schema': 1,
        'kept_on': paths.at(RULE).exists() and not opted_out(paths),
        'networkmanager_default': paths.at(NM_CONF).exists() and not nm_shadowed,
        'opted_out': opted_out(paths),
        'ethtool': _ethtool(paths) is not None,
        'cards': cards,
    }


def _nm_running(paths):
    return paths.at('/run/NetworkManager').is_dir() and shutil.which('nmcli') is not None


def apply(paths, runner=_run, names=None):
    """Turn Wake-on-LAN on now for the wired cards (or those named), and have
    NetworkManager read its default again. Returns what it did, a line each."""
    done = []
    if opted_out(paths):
        return ['Wake-on-LAN is turned off on this machine (the udev rule is masked in /etc): nothing changed']
    cards = [c for c in wired_cards(paths) if not names or c['name'] in names]
    tool = _ethtool(paths)
    for c in cards:
        wakeup = paths.sys_net / c['name'] / 'device' / 'power' / 'wakeup'
        if c['wakeup'] not in (None, 'enabled'):
            try:
                wakeup.write_text('enabled\n')
                done.append(f"{c['name']}: the card may now wake the machine")
            except OSError as e:
                done.append(f"{c['name']}: couldn't allow waking ({e.strerror or e})")
        if tool:
            r = runner([tool, '-s', c['name'], 'wol', 'g'])
            if r.returncode == 0:
                done.append(f"{c['name']}: Wake-on-LAN on (magic packet)")
            else:
                done.append(f"{c['name']}: this card can't wake the machine ({(r.stderr or '').strip() or 'not supported'})")
        else:
            done.append(f"{c['name']}: ethtool isn't installed: on from the next start")
    if not names and _nm_running(paths):
        r = runner(['nmcli', 'general', 'reload', 'conf'])
        if r.returncode == 0:
            done.append('NetworkManager read its Wake-on-LAN default again')
    if not cards:
        done.append('no wired network card here: nothing to do')
    return done


def _require_root():
    if os.geteuid() != 0:
        raise Error('turning Wake-on-LAN on needs root: sudo bromigos wol apply')


def main(argv=None, paths=None, runner=_run):
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = paths or Paths()
    cmd = argv.pop(0) if argv else 'status'
    try:
        if cmd == 'status':
            s = status(paths, runner)
            if '--json' in argv:
                print(json.dumps(s, indent=2))
                return 0
            if s['opted_out']:
                print('Wake-on-LAN: turned off here (the udev rule is masked in /etc)')
            else:
                print('Wake-on-LAN: bromigOS keeps it on for wired cards' if s['kept_on']
                      else 'Wake-on-LAN: not kept on (bromigos-core is older or missing)')
            if not s['cards']:
                print('  no wired network card')
            for c in s['cards']:
                state = {True: 'on', False: 'off', None: 'unknown (no ethtool)'}[c['on']]
                cable = 'cable in' if c['carrier'] else 'no cable'
                print(f"  {c['name']}: {state}, {cable}, may wake the machine: {c['wakeup'] or 'unknown'}")
            return 0
        if cmd == 'apply':
            quiet = '--quiet' in argv
            names = [a for a in argv if not a.startswith('-')]
            _require_root()
            for line in apply(paths, runner, names or None):
                if not quiet:
                    print(line)
            return 0
        if cmd in ('-h', '--help', 'help'):
            print('bromigos wol status [--json] | apply [--quiet] [CARD...]')
            return 0
        raise Error(f'unknown command {cmd!r}: status or apply')
    except Error as e:
        print(f'bromigos wol: {e}', file=sys.stderr)
        return 1
