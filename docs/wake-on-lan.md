# Wake-on-LAN

bromigOS keeps Wake-on-LAN on for every wired network card, on the desktop, on bromigOS
Server and on the Server a Field Kit stick installs. A switched-off machine with an
Ethernet cable can then be woken by a magic packet from another machine on its network.
BRODEC's Power on button relies on it. How to use it: the manual's
[Wake-on-LAN](../manual/src/wake-on-lan.md).

## The parts

All of it ships in `bromigos-core` (`packaging/bromigos-core/`), the package every edition
installs, which depends on `ethtool`.

| Source | Installed as | Does |
|---|---|---|
| `packaging/bromigos-core/50-bromigos-wake-on-lan.conf` | `/usr/lib/NetworkManager/conf.d/` | `[connection-bromigos-wake-on-lan]`, `match-device=type:ethernet`, `ethernet.wake-on-lan=64`. NetworkManager reads this connection default as an integer of `NMSettingWiredWakeOnLan` flags; 64 (0x40) is `magic`. It applies to connections whose own `802-3-ethernet.wake-on-lan` is `default`, which is every connection NetworkManager and bromigOS make. NetworkManager sets it on the card at each activation |
| `packaging/bromigos-core/81-bromigos-wake-on-lan.rules` | `/usr/lib/udev/rules.d/` | On `add` of a net device with `type` 1, a `device`, and no `wireless`/`phy80211`/`DEVTYPE=wlan`: `ATTR{device/power/wakeup}="enabled"` and `RUN+="/usr/bin/ethtool -s $name wol g"`. After `80-net-setup-link.rules`, so `$name` is final. This covers systemd-networkd and machines with no network manager |
| `lib/bromigos_wol.py`, `bin/bromigos-wol` | `/usr/lib/bromigos/{lib,bin}` | `bromigos wol status [--json]` and `apply [--quiet] [CARD…]` (root): the same as the rule, for the cards already there, then `nmcli general reload conf` |
| `packaging/bromigos-core/bromigos-core.install` | the package's scriptlet | `post_install` and `post_upgrade` run `bromigos-wol apply --quiet`, so an existing install has it on at once, as root, with no questions |
| `migrations/20261031120000-wake-on-lan.sh` | `/usr/share/bromigos/migrations/` | Per user, on `bromigos update`: checks `status --json`; a card still off (the package was installed where it couldn't reach the cards) is turned on with `sudo -n` only when sudo needs no password; otherwise the next boot's rule does it. Always exits 0 once the helper exists |

**Why not a `.link` file.** systemd applies only the first `.link` file that matches a
device. A file of our own for wired cards would replace `99-default.link` for them, and its
naming policy with it. A drop-in under `99-default.link.d/` can't narrow the match, so it
would set Wake-on-LAN on every interface, Wi-Fi and container veths included. The udev rule
narrows to wired cards and leaves naming alone.

**BRODEC reads it.** `brodec-machine` reports `bromigos_wol: true` in its wake card when
`/usr/lib/udev/rules.d/81-bromigos-wake-on-lan.rules` exists, and its "Can this machine be
woken?" check then says bromigOS turns Wake-on-LAN on by itself. Keep that path.

**Opting out** is masking: a `/dev/null` link at `/etc/udev/rules.d/81-bromigos-wake-on-lan.rules`
(`apply` then does nothing) and an empty `/etc/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf`,
which shadows the default.

## Tests

`tests/wake-on-lan/test_wake_on_lan.py` (run by the `bromigos-core` PKGBUILD's `check()`):
the shipped files' contents, `udevadm verify` on the rule when udevadm is there, the helper
against a fake `/sys` with stand-in `ethtool` and `nmcli`, and the migration with stand-in
`bromigos`, helper and `sudo`. Nothing touches a real card, NetworkManager or sudo.

```bash
PYTHONPATH=lib python -m unittest discover -s tests/wake-on-lan
```
