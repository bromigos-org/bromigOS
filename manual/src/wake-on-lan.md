# Wake-on-LAN

Wake-on-LAN switches a computer on over the network. Another computer on the same network
sends a short message, a "magic packet", to the network card of the switched-off machine,
and the machine starts as if you had pressed its power button.

bromigOS keeps Wake-on-LAN on for wired network cards, by itself. You don't need to run
anything. It stays on across restarts, after an update, and when you plug the cable into
another port.

BRODEC's **Power on** button on your phone uses it: it asks your lab, or another of your
machines on the same network, to send the packet for you.

## What it needs

- **An Ethernet cable.** Wi-Fi can't wake a powered-off desktop: the Wi-Fi card is off
  with the rest of the machine. Connect a cable from the machine's network port to your
  router or switch.
- **A network card that supports it.** Almost every desktop's built-in network port does.
- **The setting in the BIOS** (UEFI). bromigOS can't change it for you. Start the machine
  and press <kbd>Delete</kbd> or <kbd>F2</kbd> while it starts, then:

  | Board | Where the setting is |
  |---|---|
  | ASUS | Advanced → APM Configuration → **Power On By PCI-E**: Enabled, and **ErP Ready**: Disabled |
  | MSI | Settings → Advanced → Wake Up Event Setup → **Resume By PCI-E Device**: Enabled, and Power Management Setup → **ErP Ready**: Disabled |
  | Gigabyte | Settings → Platform Power → **Wake on LAN**: Enabled, and **ErP**: Disabled |
  | ASRock | Advanced → ACPI Configuration → **PCIE Devices Power On**: Enabled, and **Deep Sleep**: Disabled |
  | Dell | Power Management → **Wake on LAN/WLAN**: LAN Only, and **Deep Sleep Control**: Disabled |
  | HP | Advanced → Power-On Options → **S4/S5 Wake on LAN**: Enable |
  | Lenovo | Power → **Wake on LAN**: Automatic, and turn off Enhanced Power Saving Mode |
  | Others | Look for "Wake on LAN", "Power On By PCI-E" or "Resume by PCI-E Device" and turn it on; turn "ErP" or "Deep Sleep" off |

- **Power at the wall.** A machine needs standby power to wake. A power strip that is
  switched off, or the switch on the back of the power supply, cuts it.

**An encrypted disk** stops at its passphrase screen after waking, as it does when you
press the power button. The machine is on but waits until someone types the passphrase at
it, so it doesn't come online by itself.

## See whether it's on

```bash
bromigos wol status
```

It lists each wired network card: whether Wake-on-LAN is on, whether a cable is in, and
whether the system lets the card wake the machine.

## For power users

bromigOS ships these in `bromigos-core`, on the desktop and on bromigOS Server alike:

| File | What it does |
|---|---|
| `/usr/lib/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf` | NetworkManager's default for wired connections: `ethernet.wake-on-lan=64` (the "magic" flag). Every connection whose own setting is `default` follows it |
| `/usr/lib/udev/rules.d/81-bromigos-wake-on-lan.rules` | For each wired card as it appears (at boot, or plugged in): allows the card to wake the machine (`device/power/wakeup`) and runs `ethtool -s <card> wol g`. It works without NetworkManager too (bromigOS Server on systemd-networkd) |
| `/usr/lib/bromigos/bin/bromigos-wol` | `bromigos wol status [--json]`, and `sudo bromigos wol apply [CARD…]`, which turns it on now. The package's install step runs `apply` on every install and update |

Only real wired Ethernet cards count: not Wi-Fi, bridges, VPNs or containers' interfaces.

Check a card by hand (`enp3s0` is an example name; `ip link` lists yours):

```bash
nmcli -f 802-3-ethernet.wake-on-lan connection show "Wired connection 1"
cat /sys/class/net/enp3s0/device/power/wakeup     # enabled
ethtool enp3s0 | grep Wake-on                     # Wake-on: g
```

**To turn it off**, mask both:

```bash
sudo ln -s /dev/null /etc/udev/rules.d/81-bromigos-wake-on-lan.rules
sudo touch /etc/NetworkManager/conf.d/50-bromigos-wake-on-lan.conf   # an empty file shadows the default
sudo ethtool -s enp3s0 wol d
```

Or keep it on in general and off for one connection:
`nmcli connection modify "Wired connection 1" 802-3-ethernet.wake-on-lan ignore`.

How it's built: [docs/wake-on-lan.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/wake-on-lan.md).
