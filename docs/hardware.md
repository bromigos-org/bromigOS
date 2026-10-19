# Hardware: GPUs, laptops and touchpads

`bromigos hw` looks at the machine and sets up what its hardware needs. That means the
graphics driver, NVIDIA's early KMS, the GPU that drives the screen, a laptop's
battery, brightness and power profiles, and the touchpad. It reads the machine from
files only, and it never swaps an NVIDIA driver you already have.

This page explains what it detects and what it changes. The manual's
[Hardware](../manual/src/hardware.md) page is the user's guide. The code is
`core/crates/bromigos-core/src/hw.rs`.

## Check and set up the hardware

```bash
bromigos hw                        # what this machine is, and what setup would do
bromigos hw --json                 # the same, as JSON (core/README.md describes it)
bromigos hw display                # connected screens and the automatic GPU choice
bromigos hw display --json         # the same display check, as JSON
bromigos hw setup --dry-run        # list the changes without making them
bromigos hw setup                  # make them; asks for sudo for the system's part
bromigos hw setup --user-only      # only your part: Hyprland's GPU environment
```

`hw setup --yes` answers pacman's questions with their defaults.

Setup checks before it changes anything, and changes only what differs. So running it
again is safe. It never removes a package.

You rarely need to run it yourself:

- `bromigos install` runs it as its `hardware` step.
- `bromigos setup hardware` shows what it found and asks before setting it up.
- The ISO's installer brings the packages from the medium.

Run `bromigos hw setup` after changing a GPU if its driver needs setting up. Choosing an
already working card from its connected screens happens at login without running setup.

Other words after `bromigos hw` go to the command router, which runs
`bromigos-hw-<name>`. So a hardware command of your own fits in the same group.

## What it reads

Detection reads files only and never runs a command. So a tree of fixture files can
stand in for a whole machine. `BROMIGOS_FS_ROOT` moves `/` for the tests and for the VM's
faked machines.

| What | Read from |
|---|---|
| The GPUs | `/sys/bus/pci/devices/*/uevent` for display devices, plus `boot_vga`. Names come from `pci.ids`, as `lspci` shows them. |
| Which outputs a GPU drives | `/sys/class/drm/cardN-*`, including each connector's `status`. An `eDP`, `LVDS` or `DSI` connector is a laptop's built-in screen. |
| Laptop or desktop | The DMI chassis type, and whether the machine runs on a battery |
| The battery | `/sys/class/power_supply/*` entries of type `Battery`, leaving out a mouse's or headset's |
| Lid, backlight, keyboard light | `/proc/acpi/button/lid/*`, `/sys/class/backlight/*`, `/sys/class/leds/*::kbd_backlight` |
| Touchpads | `/proc/bus/input/devices`, judged the way udev does |
| A virtual machine | DMI's vendor and product, and the CPU's `hypervisor` flag |
| The kernels | `/usr/lib/modules/*/pkgbase`, such as `linux`, `linux-lts` or `linux-zen` |
| Multilib | A `[multilib]` section in `/etc/pacman.conf` |
| NVIDIA's driver now | `/sys/module/nvidia`, `/proc/driver/nvidia/version`, and `nvidia_drm`'s `modeset` and `fbdev` |
| The initramfs | `MODULES` in `/etc/mkinitcpio.conf` and its drop-ins, and whether hibernation is set up |

The chassis types counted as laptops are 8, 9, 10, 11, 14, 30, 31 and 32. A virtual
machine is one made by QEMU, VMware, VirtualBox, Hyper-V, Xen or KVM.

The plan then asks pacman what's missing with `pacman -T`, asks systemd what's enabled,
and reads the system files themselves.

## GPUs

Which driver a GPU gets comes from its makers' own lists, not from guesses. The table is
`core/crates/bromigos-core/data/gpu-ids.tsv`. `tools/hw/gpu-tables.py` builds it from two
sources:

- the supported-chips appendix of the NVIDIA driver that Arch ships. Its current table is
  every GPU the open kernel modules drive. Its legacy tables say which branch each older
  GPU needs.
- Mesa's PCI ID tables for Intel's older generations.

Run the script again when Arch's `nvidia-utils` or Mesa moves a branch. `--check` says
whether the table is stale.

A device the table doesn't list goes by its vendor. An NVIDIA one from Turing's ID range
up counts as current. An Intel one counts as Gen8 or newer. An AMD one goes by the kernel
driver bound to it.

| GPU | Driver | Packages |
|---|---|---|
| NVIDIA Turing and newer (GTX 16, RTX 20 and later) | NVIDIA's open modules | `nvidia-open`, `nvidia-utils`, `libva-nvidia-driver` |
| NVIDIA Maxwell, Pascal, Volta | nouveau | `mesa`, `vulkan-nouveau`, `linux-firmware-nvidia` |
| NVIDIA Kepler, Fermi and older | nouveau | The same |
| AMD GCN and newer | Mesa, on amdgpu | `mesa`, `vulkan-radeon`, `linux-firmware-amdgpu` |
| AMD and ATI TeraScale and older | Mesa, on radeon | `mesa`, `linux-firmware-radeon` |
| Intel Gen8 (Broadwell) and newer, and Arc | Mesa | `mesa`, `vulkan-intel`, `intel-media-driver`, `linux-firmware-intel` |
| Intel Gen4 to Gen7.5 | Mesa | `mesa`, `vulkan-intel`, `libva-intel-driver` |
| Intel Gen3 | Mesa | `mesa` |
| A virtual machine's GPU | Mesa | `mesa` |

Some details:

- **NVIDIA's open modules** come as `nvidia-open` for `linux` and `nvidia-open-lts` for
  `linux-lts`. With any other kernel, setup uses `nvidia-open-dkms` and each kernel's
  headers.
- **Multilib.** With multilib on, setup adds the 32-bit packages too:
  `lib32-nvidia-utils`, `lib32-mesa`, `lib32-vulkan-radeon` or Intel's equivalents.
- **Older NVIDIA cards.** NVIDIA's own driver for Maxwell to Volta is the 580.xx branch,
  and for Kepler the 470.xx branch. Both are only in the AUR, the Arch User Repository
  ([aur.md](aur.md)). bromigOS doesn't carry them.
  - `bromigos hw setup` offers to build the right one with paru, after a [y/N] question.
    `--aur` skips the question, and `--aur --yes` skips paru's review of the recipe too.
  - It runs `paru -S --needed <kernel>-headers nvidia-<branch>-dkms
    nvidia-<branch>-utils`, plus `lib32-nvidia-<branch>-utils` with multilib.
  - `bromigos install` never does this. With the AUR off, or no helper installed, the
    plan's note says how to get one.
  - After a reboot with the driver loaded, run `bromigos hw setup` again. It treats the
    driver as NVIDIA's: it adds early KMS, and turns on `modeset` and `fbdev` in
    `/etc/modprobe.d/bromigos-nvidia-kms.conf` if the driver doesn't. The same happens for
    a driver you installed yourself.
  - This is unit-tested with Pascal and Kepler fixtures, but not yet run on real
    hardware.
- **Virtual machines** use Mesa's virgl with 3D, or else its software renderer. That
  covers virtio, QXL, bochs, VMware, VirtualBox, Hyper-V and Cirrus. On the software
  renderer, the live layer holds a still frame
  ([live/README.md](../live/README.md#no-gpu)).

### NVIDIA

**An installed driver is never swapped.** If any package that provides `NVIDIA-MODULE`
is installed, such as `nvidia-open`, `nvidia-open-dkms` or an AUR branch, setup leaves the
kernel modules alone. It tells you if they're installed but not loaded.

**Early KMS.** Setup writes `/etc/mkinitcpio.conf.d/bromigos-nvidia.conf` with
`MODULES+=(nvidia nvidia_modeset nvidia_uvm nvidia_drm)`, then runs `mkinitcpio -P`.
That gives the driver the screen before the boot splash and the login screen. Setup
skips it in two cases:

- when the initramfs already loads `nvidia_drm`;
- when hibernation is set up, because loading the driver that early breaks resuming.

If you set up hibernation later, remove the file and run `mkinitcpio -P`.

**modeset, fbdev and suspend.** Arch's `nvidia-utils` already turns on
`nvidia_drm.modeset` and `fbdev`, and keeps video memory across suspend. bromigOS adds
nothing to that.

**No Hyprland environment variables.** The variables people used to set for NVIDIA aren't
needed any more, and some do harm:

- `LIBVA_DRIVER_NAME` isn't needed. libva finds `libva-nvidia-driver` by itself.
- `__GLX_VENDOR_LIBRARY_NAME` is harmful. Set for the whole session, it pulls every X
  client onto a laptop's NVIDIA GPU, and it has broken logins.
- `GBM_BACKEND` isn't needed. GBM finds NVIDIA's backend.
- `NVD_BACKEND` isn't needed. `direct` is already the default.
- The cursor settings aren't needed. Hyprland's `cursor:use_cpu_buffer` and
  `no_hardware_cursors` default to `auto`, which handles NVIDIA.

Hyprland's wiki sends NVIDIA users to the Arch wiki, which sets none of them for Wayland.

**After a driver update, restart the computer.** An update replaces NVIDIA's libraries at
once, but the kernel module only loads at the next start. Until then the two halves
differ, and a program that starts can't use the GPU. It falls back to Mesa's software
renderer, on the CPU. `bromigos update` checks for this. It holds back the live layer,
VECTOR and the theme previews, ends with a line asking you to restart, and sends a
notification ([update.md](update.md#when-the-kernel-or-the-graphics-driver-changes)).
`bromigos restart --check` lists a `driver` line while the halves differ.

### Choosing the GPU with a connected screen

The login screen and Hyprland check the connected screens when they start. If exactly
one usable host GPU reports a `connected` output, they prefer that GPU. It can have
several screens. A disconnected GPU marked as the firmware's boot device does not win
over it. The current card number is read again on each start, so a change from `card0`
to `card1` does not leave a saved automatic choice pointing at the wrong device.

With no connected GPUs, or with screens connected to several GPUs, this rule makes no
choice. The existing compositor defaults and laptop policy remain in effect. A card
bound to VFIO, or reserved for VFIO through a driver override, is excluded from the
automatic choice. VFIO is the kernel interface used to assign devices to virtual
machines. The rule does not install drivers, change their bindings or hand a card to a
VM.

A usable card has a DRM device, a bound host driver and the matching seat. A seat is a
set of displays and input devices assigned to one login session. The selector reads
the connector's current `status`; missing and `unknown` values do not count as
connected. Hyprland's automatic device list puts the selected card first and keeps
the other usable cards available for their outputs.

Explicit settings take precedence:

- Hyprland keeps an existing `AQ_DRM_DEVICES` value and a valid GPU choice from the saved
  hardware environment. `bromigos.hw = false` disables its hardware selection.
- SDDM keeps an administrator's `CompositorCommand` override in `/etc/sddm.conf.d/` or
  `/etc/sddm.conf`. Its packaged launcher falls back to Weston's usual device choice
  when the core command is missing or too old.

`bromigos hw display` explains the automatic candidate using read-only checks. It does
not claim that a running desktop uses that candidate. `--json` gives the same report to
tools; `--hyprland` supplies the internal device list used at Hyprland startup.

This is a startup choice. Moving a cable during a session does not move its renderer
to another card. The next login checks again. The greeter checks when its compositor
next starts. Drivers must already be working for the connected card to be usable.

### Laptops with two GPUs

A laptop with two GPUs draws the desktop on the one wired to its built-in screen. If
that's unclear, it uses Intel's, or else the one the firmware booted on. The other GPU is
kept for programs that ask for it. Setup does this:

- **Stable names.** `/etc/udev/rules.d/61-bromigos-gpu.rules` names the two GPUs
  `/dev/dri/bromigos-igpu` and `/dev/dri/bromigos-dgpu`, by PCI address. `cardN` numbers
  change between boots, and Hyprland can't take `/dev/dri/by-path` names, so this follows
  the recipe on Hyprland's multi-GPU page.
- **Hyprland's GPU list.** Hyprland gets
  `AQ_DRM_DEVICES=/dev/dri/bromigos-igpu:/dev/dri/bromigos-dgpu`. The integrated GPU comes
  first. The discrete one is listed too, so a monitor wired to it still works.
- **An NVIDIA second GPU** gets `nvidia-prime`, so `prime-run <program>` runs a program on
  it. Its runtime power management is turned on with
  `/etc/udev/rules.d/80-bromigos-nvidia-pm.rules`, the rules from NVIDIA's README. On
  Turing, `/etc/modprobe.d/bromigos-nvidia-pm.conf` also sets
  `NVreg_DynamicPowerManagement=0x02`. Ampere and newer laptops do this by default.
- **An AMD second GPU** runs a program with `DRI_PRIME=1 <program>`.

The connected-screen rule above also applies when no explicit GPU choice is saved.
The laptop's saved GPU environment takes precedence over that rule.

## Hyprland's GPU environment

Setup writes `~/.local/state/bromigos/hw/hyprland.lua`, which bromigOS's default
`hyprland.lua` reads. It updates files it generated and preserves a custom file. On a
laptop with two GPUs a generated file looks like this:

```lua
return {
    gpus = "Intel CoffeeLake-H GT2 [UHD Graphics 630] (…); NVIDIA TU117M [GeForce GTX 1650 Mobile / Max-Q] (…)",
    laptop = true,
    env = {
        { "AQ_DRM_DEVICES", "/dev/dri/bromigos-igpu:/dev/dri/bromigos-dgpu", when = { "/dev/dri/bromigos-igpu" } },
    },
}
```

A variable is set only while every path in its `when` list exists. If a saved GPU choice
no longer applies, the connected-screen rule can choose the replacement. An inherited
`AQ_DRM_DEVICES` value is kept. To ignore the file and automatic selection, set
`bromigos = { hw = false }` in your `hyprland.lua`. Changes take effect at your next login.

## Laptops

A machine counts as a laptop when its chassis type says it's portable, or it runs on a
battery. A server never does. A laptop gets these:

- **Power tools.** `brightnessctl` and `power-profiles-daemon` are installed and enabled,
  and started at once on a running system. Setup skips this if another power manager is
  installed, such as TLP, tuned or auto-cpufreq, because the two would fight. It tells you
  so.
- **Brightness keys.** They go through the on-screen display, swayosd, which changes the
  brightness and shows it. Where swayosd isn't installed, they use `brightnessctl`.
- **The bar's battery.** It shows the charge, with `+` while charging, `=` when plugged in
  but not charging, and `FULL`. It turns amber at 25% and red at 10%. Its tooltip gives
  the time left or to full, the power draw, the battery's health and its charge cycles.
  It appears only on a machine with a battery.
- **The bar's power profile.** It shows `SAVER`, `BALANCED` or `PERFORMANCE` while the
  daemon runs. Click it to move to the next one.
- **The menu.** TOGGLE › Power profile lists the profiles, with the one in use marked.
  SETUP › Hardware runs the hardware setup.

The bar's battery and power icons come from the theme, in `theme/icons/bat*.svg` and
`power*.svg`.

### The touchpad

bromigOS's defaults apply to any touchpad:

- tap to click: one finger clicks, two fingers right-click, three fingers middle-click;
- natural scrolling;
- off while you type;
- clicks counted by fingers;
- a three-finger swipe sideways switches workspaces, one at a time.

A desktop without a touchpad is unaffected. To change them, use `bromigos setup input`,
or set them in your `hyprland.lua`:

```lua
bromigos.config = { input = { touchpad = { tap_to_click = false } } }
bromigos.gestures = false    -- no touchpad gestures
```

Add more gestures with `hl.gesture({ … })` after the defaults.

## In the installers

- **`bromigos install`** runs the `hardware` step after the rollback step and before the
  configs. If it fails, the install reports it and carries on. The desktop still runs,
  just without hardware video decoding. `--no-hardware` skips the step.
- **`bromigos setup hardware`** shows what was found and what setup would do, then asks:
  set it up now, or leave it. For an unattended run, put `[hardware] mode = "auto"` or
  `"skip"` in the answers file, or pass `--hardware auto`.
- **The ISO's installer** runs `bromigos hw detect --json` on the live system, whose
  `/sys` is the real machine's. It adds that plan's packages and services to
  archinstall's configuration, so they come from the medium like everything else. Then
  `bromigos install` in the new system writes the system files. [iso.md](iso.md) has the
  details.
- **An existing install** isn't changed by an update, because installing drivers needs
  sudo and a decision. Run `bromigos hw setup` once. `bromigos hw` shows what it would do.

The ISO's offline repository carries every package a plan can install, except the
`-lts` and DKMS ones, since the ISO installs the stock kernel. A unit test keeps that
list and `hw.rs` in step. The live session itself runs on Mesa, with nouveau on NVIDIA.

## What's proven, and how

**Proven:**

- **The detection tables.** Unit tests in `hw/tests.rs` run on whole machines made of
  fixture files with real PCI IDs. They cover NVIDIA's branches, Intel's generations,
  vendors, virtual machines, chassis types, batteries, touchpads, `MODULES` and
  hibernation. CLI tests on a fixture root (`tests/cli.rs`, the `hw_*` tests) cover the
  commands.
- **Automatic GPU selection.** Hardware fixtures cover connector status, driver
  readiness, card numbering, seats and VFIO reservations. The greeter's tests use
  stand-ins for the hardware query and Weston, including late device readiness and
  fallback when the query is unavailable. These checks do not start the live desktop.
- **An NVIDIA desktop** with an RTX 5070 (Blackwell) and `nvidia-open` 615, with early KMS
  set up by hand. `bromigos hw` read it correctly, read-only. Its plan keeps the driver,
  writes no system file because `nvidia_drm` already loads early, and adds
  `libva-nvidia-driver` and `lib32-nvidia-utils`. `hw setup` wasn't run on it.
- **A virtio GPU in QEMU.** On the Arch cloud image with bromigOS installed, `bromigos hw`
  and `hw setup` ran for real, and Hyprland and the bar worked afterwards.
- **A laptop, faked in the same VM.** QEMU's `-smbios` option gave it a "Notebook"
  chassis, and the kernel's `test_power` module gave it a battery. Setup installed and
  started `brightnessctl` and `power-profiles-daemon`. The bar showed the battery,
  plugged in at 50% and red at 8% discharging, and the power profile. The menu's profiles,
  SETUP › Hardware, `bromigos install --dry-run` and `bromigos setup hardware` all worked.
- **Hyprland reading the GPU environment file.** In the VM, a variable whose `when` path
  existed reached waybar's environment, and one whose path didn't was left out.
  `Hyprland --verify-config` and `hyprctl configerrors` were clean.
- **The touchpad defaults.** `Hyprland --verify-config` accepts them, and `tap_to_click`
  was on in the running VM.
- **The ISO installer's hardware step.** CI checks `hardware.py`'s merge
  (`iso-check.yml`). An ISO built with it booted in QEMU as a faked laptop. The live
  medium's `bromigos hw` saw a laptop. The install took `brightnessctl` and
  `power-profiles-daemon` from the medium, and the hardware step in the new system wrote
  the rest. The installed system ran the daemon and showed the profile in the bar, and
  `iso/test.sh boot-disk` passed all 78 checks.
- **NVIDIA installs, older NVIDIA cards, laptops with two GPUs, and Intel and AMD** are
  covered by fixtures and by the CLI's dry and recorded runs.
- **A driver update before the restart.** On the RTX 5070 desktop above, after
  `nvidia-utils` went from 615.71.09 to 615.78.08 with the old module loaded,
  `bromigos restart --check` listed the `driver` line, read-only. The live layer's guard
  and the update's held restarts were tested on llvmpipe and in a VM
  ([update.md](update.md#test-runs)).

**Not proven without real hardware:**

- automatic startup selection across different multi-GPU machines; fixture and
  compositor stand-in tests do not establish that every driver combination can render;
- NVIDIA's open modules and early KMS installed on a machine that doesn't have them yet,
  including from the ISO;
- the AUR drivers for older NVIDIA cards on real hardware;
- a laptop with two GPUs: drawing on the integrated GPU, offloading, and the NVIDIA GPU
  powering down;
- Intel and AMD GPUs on real hardware;
- virgl's 3D path;
- a real battery, lid, backlight, brightness keys and touchpad.

### Run the VM tests as a laptop

To fake a laptop in the fresh-machine VM:

```bash
test/vm/smbios-chassis.py 10 notebook.bin
BROMIGOS_VM_QEMU="-smbios file=$PWD/notebook.bin" test/vm/arch-vm.sh up
test/vm/arch-vm.sh install
```

Then, inside the VM, run `sudo modprobe test_power`. The files in
`/sys/module/test_power/parameters/` set the battery's charge and status, and the AC.
`BROMIGOS_VM_PORT`, `BROMIGOS_VM_VNC` and `BROMIGOS_VM_MEM` let a second VM run beside
the usual one.

For the ISO, run `iso/test.sh` with `BROMIGOS_ISOTEST_QEMU="-smbios file=…"`. The
`_DIR`, `_PORT` and `_VNC` variants let it run beside another test.
