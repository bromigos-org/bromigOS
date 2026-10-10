# The AUR

The AUR (Arch User Repository) is where Arch users share build recipes for software that
isn't in Arch's repositories. A recipe is a file called a PKGBUILD. An AUR helper fetches
the recipe, builds the package on your machine and installs it with pacman. bromigOS
installs one: paru.

bromigOS never needs the AUR. Everything an install puts on your machine comes from
Arch's repositories and bromigOS's own repository. That includes paru: bromigOS builds it
from paru's source and publishes it, signed, like its other packages. So a broken AUR
package can't break an install. bromigOS's paru also brings `base-devel`, the build tools
(a compiler, `fakeroot`, …) every AUR package needs; the AUR takes them for granted.

## What to do

```text
bromigos aur                      # the helper here, whether bromigOS uses it, AUR updates waiting
paru -S <name>                    # install a package from the AUR
bromigos update                   # updates everything: the repositories', then the AUR's
bromigos update --no-aur          # this once, leave AUR packages alone
bromigos aur off                  # leave the AUR alone from now on
bromigos aur on                   # use it again
```

## Read a recipe before you build it

Anyone can submit a recipe to the AUR, and nobody checks it before you use it. A recipe runs
commands on your machine when it builds. So read it first, or trust whoever maintains it.

paru helps with that. Before it builds a package it shows you the recipe, or what changed
in it since you last built it, and asks whether to go on. `bromigos update` keeps that
review: run it in a terminal and paru asks, package by package.

`bromigos update --yes` skips the review. paru then builds whatever the recipes say,
without asking (and pacman takes its default answers too). Use `--yes` for unattended
updates only, and only with AUR packages whose maintainers you trust.

Without a terminal (from a script or a timer) and without `--yes`, `bromigos update` leaves
the AUR out and says so. It never builds a recipe nobody was asked about.

## What `bromigos update` does with AUR packages

An update goes in this order:

1. a snapshot of the system before anything changes (the *pre* snapshot);
2. `sudo pacman -Syu`: the packages from the repositories;
3. `paru -Sua`: the packages from the AUR (the *AUR step*);
4. a snapshot after (the *post* snapshot);
5. the migrations, the theme, and restarts of whatever still runs old code.

The AUR step runs only when step 2 worked. Both steps sit between the same two snapshots.
So `bromigos update --rollback` undoes the AUR's changes too.

snap-pac (which takes its own snapshots around every pacman run) is told to skip the
update's transactions, paru's included, so you get one pair of snapshots per update, not
one per package. paru runs pacman through sudo, and sudo is told to pass that on
(`--sudoflags --preserve-env=SNAP_PAC_SKIP`).

When nothing from the AUR is waiting, paru isn't run at all.

### When an AUR package fails to build

The update goes on. Migrations, the theme and the restarts still run. At the end it says
which AUR packages weren't updated and how to try again:

```text
== AUR: FAILED: not updated: cbonsai (its build failed, or it was declined at the review: paru's messages above say which)
  retry: bromigos update again, or paru -S cbonsai to see why; leave the AUR out of one update with bromigos update --no-aur
```

The update then exits with 1, as it does when a restart fails. A package that keeps
failing is usually waiting for its maintainer. To skip it until then, add it to
`IgnorePkg` in `/etc/pacman.conf`; paru honours that.

### What waits

`bromigos update --check` lists the AUR updates waiting (`paru -Qua`), under the
repositories' ones:

```text
AUR (paru 2.1.0 (bromigOS's build)): 2 waiting (bromigos update builds them after the repositories', inside its snapshot pair)
  cbonsai                      1.4.0-1 -> 1.4.2-1
  pfetch                       1.10.0-1 -> 1.11.0-1
```

Packages you hold back with `IgnorePkg` aren't listed, and an update doesn't count them as
failed.

## If you already have an AUR helper

bromigOS uses what's there. It doesn't replace or reconfigure it.

- **paru** (built from the AUR, or bromigOS's): `bromigos update` uses it.
- **yay**: `bromigos update` uses it, when there's no paru.
- **both**: paru.

bromigOS's paru has the same name and version as the AUR's (2.1.0-2). pacman leaves a paru
you built from the AUR's recipe in place, and updates it from bromigOS's repository when a
newer one is published there. paru-bin and paru-git are never swapped out: bromigOS's paru
doesn't replace them, and `bromigos install` doesn't install it next to them.

paru's settings stay yours: `/etc/paru.conf` (the package's, kept across updates) and
`~/.config/paru/paru.conf`. bromigOS ships no paru settings and never writes either file.
It passes what it needs on the command line, for its own runs only.

## Turning it off

`bromigos aur off` turns the AUR off on this machine:

- `bromigos update` leaves AUR packages alone;
- the paru that bromigOS installed is removed (`sudo pacman -R paru`). A helper you
  installed yourself stays, unused by bromigOS;
- no later update installs paru again.

`bromigos aur on` turns it back on, and installs bromigOS's paru when there's no helper.

The setting lives in `~/.config/bromigos/aur.toml`. It's yours: an update never touches it.

```toml
enabled = false   # true (the default): an AUR helper, and AUR packages in bromigos update
```

## At install

`bromigos install` installs bromigOS's paru (its `aur` step), unless:

- you pass `--no-aur`, or your setup answers file says
  ```toml
  [aur]
  mode = "off"    # "on" (the default) or "off"
  ```
  Either way the AUR is turned off before anything is installed, so paru never is;
- a helper is installed already.

Then `bromigos setup` asks too (its *The AUR* page, before the hardware page). "Off" there
removes the paru the install just put in. `bromigos setup aur` asks again any time;
`bromigos setup --aur on|off` answers without asking.

If paru can't be installed during the install (the repository isn't reachable, or the
install medium's offline copy doesn't carry it, as the ISO's doesn't yet), the install
goes on. The next `bromigos
update` installs it. The same happens on machines installed before bromigOS carried paru:
a migration (`20261009235000-aur-helper`) installs it on their next update, unless the AUR
is off there or a helper is installed.

## Drivers only the AUR has

Some NVIDIA cards need a driver branch that Arch no longer carries:

| Cards | Driver branch | AUR packages |
|---|---|---|
| Maxwell, Pascal, Volta (GTX 900 and 1000 series, TITAN V) | 580.xx | `nvidia-580xx-dkms`, `nvidia-580xx-utils` |
| Kepler (GTX 600 and 700 series) | 470.xx | `nvidia-470xx-dkms`, `nvidia-470xx-utils` |

With the multilib repository on, the `lib32-` package of the branch is added too.

Such a card runs on nouveau (the open driver, through Mesa) until NVIDIA's driver is in.
`bromigos hw setup` offers to build it with paru. It asks first:

```text
NVIDIA's driver for this GPU is in the AUR only (nvidia-580xx-dkms, nvidia-580xx-utils). The AUR's recipes are user-submitted, not vetted by Arch or bromigOS; paru builds it here and shows you the recipe to review first. Build and install it now? [y/N]
```

A yes builds it, with the kernel headers its module needs (`linux-headers` for each
kernel installed). Then reboot, and run `bromigos hw setup` again: with the driver loaded
it adds the rest (NVIDIA's modules loaded early, kernel mode setting).

- `bromigos hw setup --aur` builds it without that question; paru still shows the recipe.
- `bromigos hw setup --aur --yes` builds it without any question or review.
- `bromigos install` never builds it. Its hardware step notes the driver and how to get it.
- With the AUR off, or no helper, `bromigos hw setup` says how to get one.

## Hyprland during an AUR install

paru installs what it built with `sudo pacman -U`, so pacman's hooks run for it as for any
other transaction. The hooks that hold Hyprland's config reloads while its files change
(docs/update.md, "Hyprland during a package transaction") cover a package from the AUR the
same way.

## The commands

| Command | What it does |
|---|---|
| `bromigos aur` (`status`) | the setting, the helper here and where it came from, the AUR updates waiting (`paru -Qua`) |
| `bromigos aur on [--yes] [--dry-run]` | the setting on; bromigOS's paru installed when there's no paru or yay |
| `bromigos aur off [--yes] [--dry-run]` | the setting off; the paru bromigOS installed removed |
| `bromigos aur ensure [--yes] [--dry-run]` | bromigOS's paru, unless the AUR is off or a helper is here: what `bromigos install` and the migration run. Exits 75 when paru isn't in the repositories pacman has synced yet |
| `bromigos update [--yes] [--no-aur]` | the AUR step: reviewed at a terminal; `--yes`: no review; `--no-aur`: not this time |
| `bromigos update --check` | the AUR updates waiting, with the repositories' |
| `bromigos install --no-aur` | no AUR helper; the AUR off |
| `bromigos install --with PKG` | a `PKG` no synced repository has (`1password`, which the public mirror leaves out) comes from the AUR with the helper, after the repositories' packages; with the AUR off it's left out, and the step says so |
| `bromigos setup aur`, `--aur on\|off` | the setup page |
| `bromigos hw setup [--aur]` | a driver only the AUR has, after a question (`--aur`: without it) |

The code: `core/crates/bromigos-core/src/aur.rs` (the setting, the helper, the update's
step), `update.rs` (the order), `hw.rs` (the drivers); the package:
`packaging/paru/PKGBUILD`.

## Test runs

<!-- newest first -->

### 2026-10-09, 10:05 to 11:20 Pacific: pass, in the fresh-machine VM

`test/vm/aur-e2e.sh` (docs/install.md, "The fresh-machine test", for the VM itself), with
this branch's `bromigos-core` (r118 at the install, r129 after two rebases for the last
runs) and `paru` in a local repository listed before `[bromigos]` (`aur-e2e.sh devrepo`),
the rest from edge. Three machines:

- **A fresh install, the AUR on (the default).** `install.sh --channel edge --yes --answers
  test/vm/answers.toml`: the `aur` step installed bromigOS's paru (with `base-devel`);
  `checks.sh` 44 of 44. Then `aur-e2e.sh fresh`, 27 of 27:
  - pfetch 1.10.0-1 and cbonsai 1.4.0-1 built from the AUR's git history;
    `bromigos update --check` listed both (`paru -Qua`);
  - without a terminal and without `--yes`, the AUR step was left out and said why;
  - at a terminal (a pty), paru asked "Proceed to review?"; declined, nothing was built,
    the update said which packages weren't updated, and the empty pair was deleted;
  - gitlab.com blocked, so cbonsai couldn't download: `bromigos update --yes` updated
    pfetch, named cbonsai with the retry, still ran the migrations, the theme, the boot
    menu and the restarts, and exited 1. The pair was 45/46: no snapshot in between, so
    snap-pac took none of paru's transactions. `snapper status 45..46` had pfetch's files,
    `updates.jsonl` its line; `--rollback` put pfetch 1.10.0-1 back;
  - unblocked, both built (pair 47/48, both recorded); `--rollback` put both back;
  - `paru -Bi` of a package with a file in `usr/share/bromigos/default/hypr/`: pacman ran
    the hold hook before and the verified reload after;
  - `bromigos aur off` removed bromigOS's paru and the update left the AUR alone;
    `bromigos aur on` put it back. `sudo --preserve-env=SNAP_PAC_SKIP -v` (paru's sudo
    loop, for those who turn it on) was accepted.
- **An install opted out** (`[aur] mode = "off"` in the answers): `aur-e2e.sh opted-out`,
  5 of 5. No paru, ever (pacman's log never names it); `aur.toml` off; the migration done
  without installing it; `--check` and the update left the AUR alone.
- **A machine with the AUR's own paru.** Installed from edge (no AUR step yet), then paru
  2.1.0-2 built with `makepkg` from the AUR's recipe, then this `bromigos-core` through
  `bromigos update`: `aur-e2e.sh own-paru`, 8 of 8. The migration found "paru 2.1.0
  (yours)" and installed nothing; pacman left the AUR build in place (same version, no
  conflicts); paru is no longer a foreign package; the next update's AUR step used it;
  `bromigos aur off` left it installed.

What the runs found and fixed: paru needs `base-devel` to build anything, and a cloud
image has none (bromigOS's paru depends on it now); a pair around nothing wasn't deleted
when snapperd was still comparing it ("Config is in use.": the delete is tried again for
up to 10 s).

Not run: yay as the helper (paru was always there), and a driver from the AUR on real
NVIDIA hardware (`bromigos hw setup`'s offer is unit-tested with a Pascal and a Kepler
card's files).
