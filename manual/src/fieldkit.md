# Field Kit

Field Kit is bromigOS without the desktop. Use it when bromigOS won't start properly, to
look after your lab's machines, or to install bromigOS Server on a machine with no screen.
It works with no internet connection.

You can start it three ways:

- **From your boot menu.** Choose **bromigOS Field Kit**. It's also in the computer's own
  boot menu (often <kbd>F8</kbd>, <kbd>F11</kbd> or <kbd>F12</kbd> as it starts), so it
  works even when the bromigOS boot menu itself is broken.
- **From a USB stick.** Write the Field Kit ISO to a stick, or put it on a Ventoy stick.
- **From the bromigOS ISO.** Choose **Field Kit · repair, lab and tools, no desktop**.

Field Kit opens on its Home screen: what's in this computer, what it found on the drives
(bromigOS, Windows, USB sticks), and seven sections: Repair, Lab, VECTOR, Tools, Server,
Install and Shell. When it finds something wrong, a **Suggested** line offers the fix:
press <kbd>F</kbd>.

| Key | What it does |
|---|---|
| Arrows, <kbd>Enter</kbd> | Choose and open |
| <kbd>R</kbd> <kbd>L</kbd> <kbd>V</kbd> <kbd>T</kbd> <kbd>S</kbd> <kbd>I</kbd> <kbd>X</kbd> | Repair, Lab, VECTOR, Tools, Server, Install, Shell, from anywhere (<kbd>Alt</kbd> with the letter while you're typing) |
| <kbd>1</kbd>–<kbd>7</kbd> | The sections, on Home |
| <kbd>Esc</kbd> | Back to Home |
| <kbd>?</kbd> or <kbd>F1</kbd> | Every key on this screen |

The bar at the bottom says what the highlighted item does, and its shortcut.

## Repair

Start with **Mount my bromigOS install**. Choose your disk and type the passphrase you
type at startup. Every repair then works on it. When you're done, choose **Unmount my
install** before you restart.

| Item | Use it when |
|---|---|
| What went wrong on the last boot? | You want to know why. It reads your system's own log and says it plainly. |
| Fix a black screen / blinking cursor at startup | bromigOS starts to a black screen. It checks the usual causes and offers a fix for each. |
| Roll back to a snapshot | An update broke something. Choose the snapshot from before it. |
| Repair the boot menu | The computer goes straight to its firmware, or the boot menu is missing. |
| Change the boot options | You need a setting at every start, such as safe graphics. |
| Edit a file on my install | A guide tells you to change a file. |
| Check disks | You think a drive is failing. Nothing is changed. |
| Back up my files to a USB drive | You want your files safe before anything else. |
| Copy or image a disk | You want a copy of a whole disk. Clonezilla can restore it too. |
| Erase a disk securely | You're giving a drive away. You type its name to confirm. |
| Windows repair | Another disk has Windows on it: a forgotten password, a BitLocker drive, a missing boot entry. |

Every repair keeps a copy of what it changes first, in `/var/lib/bromigos/fieldkit-backups/`
on your install.

## Lab, Tools and Shell

- **Lab** opens the [lab console](lab.md) and its step-by-step provisioning. These talk to
  your other machines over your local network; they don't need the internet.
- **VECTOR** explains what Field Kit found and proposes fixes. Nothing runs until you
  approve it. He uses your lab's model when the lab is on the network.
- **Tools** has the toolbelt: a system monitor, disk usage, temperatures, a hardware
  report, network tests, Wi-Fi, editors and file recovery. `tldr NAME` shows examples for
  any of them, offline.
- **Shell** opens a command line, here or inside your install, and turns on remote help.

## Get help from someone else

**Remote help** lets someone you trust work on the machine over SSH. Turn it on in
**Shell › Remote help**, or choose **Field Kit with remote help** in the stick's boot menu.
The bottom line then says **REMOTE HELP ON**, with the address and a one-time password to
give them. Turn it off in the same place when they're done.

## Make your own stick

```bash
bromigos fieldkit make-stick
bromigos fieldkit make-stick /dev/sdX --wifi "Workshop:password"
```

The first command lists your USB drives. The second writes Field Kit to one, with your SSH
key, your Wi-Fi network and your lab connection already on it. Everything on the drive is
replaced, so you type its name to confirm. Scripts you put in the stick's `fieldkit/autorun/`
folder run at every start.

## Your settings on the stick

A Field Kit stick can carry your settings in a folder called `fieldkit`: on its own small
partition (what `make-stick` makes), next to the ISO on a Ventoy stick, or on the stick
itself. Field Kit reads it at every start.

```text
fieldkit/
  config.toml      your SSH keys, Wi-Fi networks and the lab connection
  homelab.toml     your lab connection (copy it from ~/.config/bromigos/)
  autorun/         scripts that run at every start, in name order
  reports/         where secure erase saves its reports
```

`config.toml` looks like this. Every part is optional:

```toml
[ssh]
authorized_keys = ["ssh-ed25519 AAAA… you@laptop"]   # who may sign in over SSH
start = false                                       # true: SSH on at every start

[[wifi]]
ssid = "Workshop"
password = "the Wi-Fi password"

[[wifi]]
ssid = "Lab"                                        # an open network: no password

[lab]
config = "homelab.toml"
```

A startup script is any `.sh` file in `autorun/`, for example `10-mount-nas.sh`. Each runs
as root, in name order. Field Kit's Home screen says how many ran and whether one failed;
what each printed is in `/run/bromigos-fieldkit/`.

## VECTOR in the terminal

**VECTOR** (<kbd>V</kbd>) is bromigOS's assistant, in the terminal. He sees what Field Kit
sees: this computer, what's on its drives, the last boot's log and the repair checks. You
choose what he reads on the left. Ask him in plain words; when he has a fix, he shows it as a
plan: each step, the exact change, and how to undo it. Nothing runs until you press
**Apply** (and type a word for the big ones, like a rollback). He never touches money or
secrets.

His brain is your lab's model, over your local network: no internet needed. With no lab in
reach, he still explains what Field Kit found, using its own repair checks.

**Pair with BRODEC** (<kbd>Ctrl</kbd>+<kbd>P</kbd> in VECTOR) shows a QR code to scan with
the BRODEC app. It works where BRODEC's machine agent is installed; approving VECTOR's plans
from the phone is still being built on BRODEC's side. Until then, remote help lets someone
watch and use the screen from their own terminal.

## Install bromigOS Server

In **Install**, choose **bromigOS Server (no desktop)**. Everything it needs is on the
stick, so no network is needed. See [bromigOS Server](server.md).

## For power users

Everything above is also a command, so you can use Field Kit over SSH or from a stick's
startup script. `--dry-run` shows the exact commands and the files each one touches, without
running them; `--json` prints the result for scripts; `--yes` skips the question.

```bash
bromigos fieldkit overview --json
echo -n 'disk passphrase' | bromigos fieldkit mount /dev/nvme0n1p2
bromigos fieldkit repair black-screen --dry-run
bromigos fieldkit repair black-screen --fix --yes
bromigos fieldkit repair rollback 12 --dry-run
bromigos fieldkit unmount
```

In the menu, <kbd>C</kbd> shows the commands behind the highlighted action, and can open a
shell with them ready to run one by one. <kbd>X</kbd> opens a shell from anywhere; leaving
it brings you back to the same screen.

The contributor notes ([docs/fieldkit.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/fieldkit.md))
list every command, the kernel parameters Field Kit reads, how each check decides what's
wrong, where its files live, and how to build your own medium. The packages on it, with their
sizes, are in [docs/fieldkit-packages.md](https://github.com/bromigos-org/bromigOS/blob/main/docs/fieldkit-packages.md).
