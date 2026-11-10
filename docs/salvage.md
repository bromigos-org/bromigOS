# Salvage scan: what an old PC can do as a home server

The salvage scan looks at one computer and says, in plain words, what it could do as a home
server. It reads the processor, memory, disks, graphics, network and firmware. Then it
judges every role and every app bromigOS Server can run, with the same budget logic as the
installer's "What should this server run?" step. It ends with the changes that would make
more fit, and the next step.

It exists so that nobody buys hardware before looking at what they have. An office PC from
a cupboard is often enough.

The scan is read-only. It never mounts, writes or changes anything on the computer.

"Salvage scan" is a working name. The command is `bromigos hw salvage`.

## Run it

**On a computer you're deciding about**, start it from a [Field Kit](fieldkit.md) stick
and choose **Server › What can this computer run?**. Field Kit is bromigOS's repair and
install stick. It runs as the administrator, so the scan reads everything it can. The
report opens in a pager: the arrow keys scroll, and `q` goes back to the menu.

**On a computer that already runs bromigOS**, run the command:

```bash
bromigos hw salvage
```

It takes a few seconds. With `sudo` in front it also reads each drive's own health
verdict and the processor's power counter. Without it, the report says what it couldn't
read, and why.

The command comes with the `bromigos-lab` package, which a bromigOS desktop, bromigOS
Server and the Field Kit stick all have.

## Read the report

The report reads from top to bottom. This one is a 2012 office desktop with 4 GB of memory
and one spinning disk:

```text
SALVAGE SCAN: what this computer can do as a home server
Read-only: nothing on this computer was changed.

THIS COMPUTER
  Kind        a desktop (Example Computers Office Desktop 2012)
  Processor   Intel Core i5-3470 CPU @ 3.20GHz: 4 cores, 4 threads
              an older or low-power design: no AVX2, as desktop processors had from about
              2009 to 2013 and low-power ones into the early 2020s (x86-64-v2; an estimate
              from its instruction sets, not a date)
              virtual machines: available (VT-x)
              hardware video: likely (Intel graphics with the i915 driver loaded); the
              formats weren't listed
  Memory      3.8 GB usable (4 GB installed); 2 of 4 slots free; DDR3; no ECC reported
  Disks       500 GB HDD, spinning (EXAMPLE HDD 500G); says it's healthy
              → One disk (500 GB HDD): the system and your data share it. Nothing protects
              them if it fails.
  Graphics    Intel Xeon E3-1200 v2/3rd Gen Core processor Graphics Controller; driver
              loaded
  Network     wired, 1 Gb/s; connected (enp2s0)
  Firmware    BIOS; started the old way, so Secure Boot doesn't apply; no security chip
              (TPM) found
  Idle power  medium: an estimate from the kind of computer and its parts (a desktop, no
              separate graphics card, 1 spinning disk), not a measurement

COULD NOT READ
  - which video formats the graphics chip decodes and encodes: vainfo isn't installed
    (package libva-utils), or it found no device.

WHAT IT'S GOOD FOR
  Judged as the installer's "What should this server run?" step judges it: 4 processor
  threads, 3.8 GB of memory, 500 GB of disk, no graphics card ready for AI.

  Roles
    no        Lab node: Together these need about 4.6 GB of memory, and this server has 3.8
              GB.
    yes, but  Storage: Memory will be tight: about 3.4 of 3.8 GB.
    yes, but  Home services: without Photos (Immich): Photos (Immich) needs 4 GB of memory;
              this server has 3.8 GB.
    no        Game server: Minecraft server needs 4 GB of memory; this server has 3.8 GB.
    no        Media: Together these need about 7.3 GB of memory, and this server has 3.8 GB.
    yes       Just a server

  Apps and services (53 in the catalogue)
    Fit comfortably (38): all of Network (2), Storage (4) and BRODEC (1); Lab core except
    Argo CD and External Secrets; in AI, VECTOR's lab bridge; Home apps except Photos
    (Immich); Media except Requests (Seerr), Autoscan, Tautulli and YouTube library.
    Fit with a trade-off (4):
      - Memory would be tight, with 3.8 GB here: External Secrets (3.2 GB), Requests (Seerr)
        (3.5 GB), Tautulli (3.2 GB) and YouTube library (3.5 GB). Each figure counts the 1
        GB the system uses and the apps it needs beside it.
    Don't fit (11):
      - 3.8 GB of memory isn't enough for: Argo CD (4 GB), Voice (speech in and out) (5 GB),
        Pelican panel (6 GB), Wings game node (5 GB), Minecraft server (5 GB), Photos
        (Immich) (5 GB) and Autoscan (4 GB). Each figure counts the 1 GB the system uses and
        the apps it needs beside it.
      - No graphics card is ready for AI: LiteLLM gateway, Model serving (Ollama), Model
        serving (vLLM) and Models.

  Whatever it runs
    - The system would run from a spinning disk: everything works, but apps start slowly and
      updates take longer.
    - One disk holds the system and your data: nothing protects them if it fails. Back up to
      another machine or a USB drive.
    - The disks hold data now. Installing erases the disk you choose: copy off anything you
      need first.

WHAT WOULD CHANGE THE ANSWER (smallest change first; no brands, no prices)
  1. More memory: 8 GB in all. The Lab node, Game server and Media roles would fit. Argo CD,
     Voice (speech in and out), Pelican panel, Wings game node, Minecraft server and 2 more
     would fit. 2 of 4 memory slots are free. It takes DDR3 memory.
  2. An SSD for the system. Apps start faster and updates finish sooner. The spinning disk
     stays, as the data disk.
  3. A second disk. With two data disks the installer can keep two copies, so one disk can
     fail without losing anything.

NEXT STEP
  Install bromigOS Server as Home services.
  It would run: Backups, Caddy, Start page, Passwords (Vaultwarden), File sync (Syncthing),
  Uptime (Uptime Kuma), This server on BRODEC.
  Together they need about 3.1 GB of memory of 3.8 and 6 GB of disk of 500.

  To carry these choices into the installer:
    bromigos hw salvage --answers salvage.toml
    then copy salvage.toml to a Field Kit stick as fieldkit/install.toml, and start this
    computer from it
  The installer asks for the disk, the password and the rest, with these roles and apps
  already chosen.

  To attach this report when asking for help:  bromigos hw salvage --save salvage-report.txt
```

| Part | What it tells you |
|---|---|
| This computer | What was found, one line per part |
| Could not read | What the scan couldn't read, and why. It appears only when something is missing. |
| What it's good for | Each role and each app: yes, "yes, but" with the trade-off, or no with the one reason |
| Whatever it runs | Cautions that hold for anything on this machine, such as a spinning system disk |
| What would change the answer | Up to three changes, the smallest first, with what each would let it run |
| Next step | The roles to install with, what they run, and how to carry them into the installer |

A role is one of the installer's jobs for a server: Lab node, Storage, Home services, Game
server, Media, or Just a server. The apps are the provisioning catalogue's items
([lab-provision.md](lab-provision.md#the-catalogue)).

## Carry the choices into the installer

`--answers FILE` writes the next step's choices as an answer file for bromigOS Server's
installer ([iso.md](iso.md#answer-files)):

```bash
bromigos hw salvage --answers salvage.toml
```

```toml
[install]
edition = "server"
cpu_model = "Intel(R) Core(TM) i5-3470 CPU @ 3.20GHz"

[server]
roles = ["home"]
lab = "none"
provision = ["backups", "caddy", "start-page", "passwords", "file-sync", "uptime", "brodec-machine"]
```

The file names no disk, no password, no admin and no SSH key, on purpose. The installer
says so, then asks its questions with these roles and apps already chosen. `cpu_model`
keeps the file to the computer that was scanned: on another one the installer changes
nothing and asks. Add `disk` or `disk_model`, `mode`, `user`, `password` and a key to
install with no questions.

There are two ways to hand the file over:

- On the Field Kit stick, start the installer with it:
  `BROMIGOS_ANSWERS=salvage.toml bromigos-iso-install --text`.
- From another computer, put it on a stick as `fieldkit/install.toml`, or make the stick
  with it: `sudo bromigos fieldkit make-stick /dev/sdX --answers salvage.toml`.

Field Kit's menu item shows the report only. It doesn't start the installer with the
choices by itself.

## Save a report to ask for help

```bash
bromigos hw salvage --save salvage-report.txt
```

The file holds the report, then the same facts as JSON. Attach it when you ask for help.
It never holds serial numbers, MAC addresses or the computer's name. The scan doesn't read
them, and a network port named after its MAC address is shown as `usb-ethernet` or
`usb-wifi`. As a second check, anything shaped like a MAC address is cut from the file.

It does hold the models of the computer, processor, disks and graphics card. Read it
before you post it.

`--identifiers` reads the disks' serial numbers, the MAC addresses and the hostname, and
keeps them in `--json` and in the saved file. Use it for your own records, or a warranty
claim.

## For power users

| Option | What it does |
|---|---|
| `--json` | Prints the JSON document instead of the report ([the schema](#the-json-document)) |
| `--save FILE` | Also writes the report and the JSON to `FILE`, without identifiers |
| `--answers FILE` | Also writes the answer file |
| `--identifiers` | Reads serial numbers, MAC addresses and the hostname too |

With `--json`, the "Saved …" lines go to standard error, so standard output is the
document alone. The exit status is 0 when the scan ran, whatever the verdict, and 1 when
the catalogue is missing.

Without bromigos-core, run `/usr/lib/bromigos/bin/bromigos-hw-salvage`.

The code is `homelab/lib/bromigos_homelab/salvage.py`:

| Function | What it does |
|---|---|
| `collect(root, run, euid, …)` | Reads the machine. `root` and `run` let a fake root and recorded tool outputs stand in. |
| `parse(raw)` | Turns that into the machine's facts, with what couldn't be read |
| `budget_hardware(facts)` | The facts as the catalogue's `hw` |
| `judge(hw)` | Every role and item against `hw`, through `provcatalog` |
| `cautions(facts)`, `upgrades(…)`, `next_step(…)` | The rest of the verdict |
| `assemble(facts)`, `scan()` | The whole document |
| `report(doc)`, `save(doc, path)`, `answers_toml(doc)` | The report, the saved file, the answer file |

### What it reads

Every probe is a file read or a read-only tool. A tool that isn't installed is skipped.

| Fact | Where it comes from | Needs root |
|---|---|---|
| Processor model, cores, threads, sockets | `/proc/cpuinfo`: `model name`, `processor`, `physical id`, `core id` | no |
| Processor class | `/proc/cpuinfo`'s `flags`, against the x86-64 feature levels ([below](#the-processor-class)) | no |
| Virtual machines | The `vmx` or `svm` flag, and whether `/dev/kvm` exists | no |
| Hardware video | `vainfo --display drm --device /dev/dri/renderD*` for the formats. Without it, a graphics chip whose driver is `i915`, `xe`, `amdgpu` or `nvidia` counts as "likely". | no |
| Memory size | `MemTotal` in `/proc/meminfo` | no |
| Memory slots, type, the board's limit, ECC | The firmware's memory table in udev's database, `/run/udev/data/+dmi:id` (`MEMORY_ARRAY_*`, `MEMORY_DEVICE_N_*`). When udev has none, `dmidecode -t memory`. | udev: no. dmidecode: yes |
| ECC, when the firmware doesn't say | `/sys/devices/system/edac/mc/mc0` exists: the kernel reports memory errors | no |
| Disks: size, type, model, whether they hold data | `lsblk -J -b -o NAME,SIZE,TYPE,ROTA,TRAN,RM,RO,MODEL,FSTYPE,MOUNTPOINTS`, or `/sys/block` without lsblk | no |
| Each drive's health verdict | `smartctl -H -j /dev/NAME`: `smart_status.passed`, and nothing else | yes |
| The stick it started from | The source of `/run/archiso/bootmnt` in `/proc/mounts` | no |
| Graphics cards, drivers, graphics memory | `/sys/bus/pci/devices`, `lspci -mm -nn -D`, `nvidia-smi`, `/sys/class/drm/card*/device/mem_info_vram_total` | no |
| Network ports, link speed | `/sys/class/net/NAME/`: `device`, `wireless`, `operstate`, `speed` | no |
| A wired port's top speed | `ethtool NAME`: "Supported link modes" | no |
| UEFI or BIOS | `/sys/firmware/efi` exists | no |
| Secure Boot | The fifth byte of `/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c` | no |
| Security chip | `/sys/class/tpm/tpm0/tpm_version_major` | no |
| Kind of computer, its model | `/sys/class/dmi/id/`: `chassis_type`, `sys_vendor`, `product_name`; a battery in `/sys/class/power_supply` | no |
| A virtual machine | `systemd-detect-virt --vm`, or the `hypervisor` flag | no |
| The processor's power | `/sys/class/powercap/intel-rapl:0/energy_uj`, read twice, half a second apart | yes |

Graphics, disks, network ports and the laptop check come from
`bromigos_homelab/hardware.py`, which the provisioning hardware check already uses
([lab-provision.md](lab-provision.md#the-hardware-check)).

It never reads `/sys/class/dmi/id/*_serial`, `product_uuid`, a network port's `address`,
a disk's serial number or the hostname, unless you pass `--identifiers`. It drops the
serial, asset and part number lines of the memory table before parsing it.

### What it can't read without administrator rights

- Each drive's own health verdict (SMART).
- The processor's measured power (RAPL).
- Memory slots, type and ECC, but only on a system whose udev database has no memory
  table. On bromigOS it has one.

The verdict doesn't depend on any of these. It is the same with and without `sudo`.

### How the hardware is counted

The verdict is judged on six numbers, the catalogue's `hw`. They are counted the way the
installer's meter counts them (`provision.hardware` in the installer, and
`localprovision.detect`):

| Key | How it's counted |
|---|---|
| `cpu` | The processor's threads |
| `ram_gb` | `MemTotal` in GiB, to one decimal. The kernel sees a little less than is installed, so 4 GB shows as about 3.8. |
| `disk_gb` | Every disk but the stick it started from, in whole decimal GB. Disks under 1 GB are ignored. |
| `gpu` | `nvidia` or `amd` once the card's driver works (`hardware.legacy`), else `false` |
| `gpu_vram_gb`, `gpu_name` | That card's memory and name |

There is one difference from the installer on the stick. Field Kit doesn't carry NVIDIA's
driver, so the installer counts an NVIDIA card anyway and guesses its memory from its model
number. The scan doesn't guess. It judges the AI items without the card, says so under
"Whatever it runs", and asks you to scan again once the driver is installed.

### The verdict's rules

Every "does it fit" answer is `provcatalog`'s (`homelab/lib/bromigos_homelab/provcatalog.py`).
The scan adds no rule of its own to it.

**An app** is judged alone, with what it needs: `resolve([id])`, then `fits_item(item, hw)`
and `budget(ids, hw)`.

| Answer | When |
|---|---|
| no | `fits_item` gives a reason, or `budget` says it doesn't fit. The reason is the first sentence. |
| yes, but | It fits, and `budget` has a note |
| yes | It fits, with no note |

**A role** is judged as the installer would tick it for a server on its own:
`recommend([role], hw, lab="none")`, then `budget`.

| Answer | When |
|---|---|
| no | `budget` says the ticked items don't fit together. Or every item that makes it this role was left out because it can't run here (a Game server without its game server). |
| yes, but | Some default item was left out, and the reason names it. Or `budget` has a note. |
| yes | Everything the role ticks fits, with no note |

The items that make a role "this role" are its default items that not every role ticks.
Backups and This server on BRODEC belong to every role, so they don't count.

The numbers are `provcatalog`'s:

| Rule | Number |
|---|---|
| Memory the system itself uses, added to every budget | 1 GB (`OS_RAM_GB`) |
| An item doesn't fit | its memory + 1 GB is more than `ram_gb` |
| Items don't fit together | their memory + 1 GB is more than `ram_gb` |
| "Memory will be tight" | their memory + 1 GB is more than 85 % of `ram_gb` |
| Disk doesn't fit | their disk is more than 90 % of `disk_gb` (a tenth stays free, `DISK_HEADROOM`) |
| Processor doesn't fit | the hungriest item needs more threads than `cpu` |
| "They share N processor cores" | their processor needs add up to more than twice `cpu` |
| Graphics | an item with `gpu = true` needs a ready card; `gpu_vram_gb` and `gpu_vendor` as the item states |

Each item's own needs are in `homelab/share/provision-catalogue.toml`, under `requires`.

The report groups the apps that share a limit on one line. The figures on those lines are
`budget`'s totals: the app, what it needs beside it, and the system's 1 GB. `--json` has
`provcatalog`'s sentence for each one.

### Cautions

These come from the facts, not from the catalogue. They never change a yes or a no.

| Id | When |
|---|---|
| `virtual-machine` | It's a virtual machine |
| `failing-disk` | A drive's own verdict is "failing" |
| `spinning-system` | The disk the system would go on is a spinning one |
| `one-disk` | There is one disk for the system and the data |
| `holds-data` | A disk has partitions or a file system now |
| `wifi-only` | There's no wired port |
| `wifi-connected` | There's a wired port, but only Wi-Fi is connected |
| `slow-link` | The wired link runs below 1 Gb/s |
| `laptop` | It's a laptop |
| `no-hardware-video` | No graphics chip with a video driver was found |
| `old-processor` | The processor is x86-64-v1 |
| `graphics-driver` | An NVIDIA or AMD card is there, but its driver isn't ready |

### What would change the answer

Each change is tried against the same logic: the scan judges again with the changed `hw`
and lists what stops being a "no". At most three are shown, in this order. The order is how
small the change usually is. The scan names no brand and no price.

| Id | When it's offered | How it's tried |
|---|---|---|
| `memory` | A bigger size lets a role or an app fit | 8, 16, 32, 64 and 128 GB in turn, up to the board's limit; the first that changes something |
| `system-ssd` | The `spinning-system` caution holds | Not tried: it changes the caution, not the budget |
| `more-disk` | More disk lets something fit | `disk_gb` + 4000 |
| `second-disk` | The `one-disk` caution holds, and nothing needs more disk | Not tried |
| `wired-network` | The `wifi-only` caution holds | Not tried |
| `graphics-card` | No card is ready, and one would let an AI item fit | `gpu = true`, with no memory figure: so only items that state none |

For memory, the kernel's figure is raised by the difference between the new size and what's
installed now. What's installed is the firmware's figure, or else the next standard size up
from `MemTotal`.

### The next step

The scan takes the roles that aren't a "no", in this order: Home services, Media, Storage,
Game server, Lab node. It adds each one for as long as `budget(recommend(roles, hw,
"none"), hw)` still fits. With none, it offers Just a server. The order puts what a
household uses first.

The installer also knows notes about pairs of roles, in its `presets.toml`. The scan
doesn't read that file.

### The processor class

The class is the highest x86-64 feature level whose flags are all present. It's an estimate
of the processor's generation from its instruction sets. It isn't a date.

| Level | Flags it adds | Class | In words |
|---|---|---|---|
| x86-64-v1 | `lm` | `very-old` | No SSE4.2, as desktop processors had before about 2009 |
| x86-64-v2 | `cx16 lahf_lm popcnt sse4_1 sse4_2 ssse3` | `older` | No AVX2, as desktop processors had from about 2009 to 2013 and low-power ones into the early 2020s |
| x86-64-v3 | `avx avx2 bmi1 bmi2 f16c fma abm movbe xsave` | `current` | AVX2, as desktop processors have had since about 2013 |
| x86-64-v4 | `avx512f avx512bw avx512cd avx512dq avx512vl` | `current` | With AVX-512 |

A 32-bit or ARM processor can't run bromigOS. The scan says so, and judges nothing.

### The idle power class

The class is an estimate from the kind of computer and its parts. The report says so, and
gives no watts for it.

| Part | Points |
|---|---|
| A laptop or a mini PC | 0 |
| A desktop, or a kind it can't tell | 1 |
| A server chassis | 2 |
| A separate graphics card | +1 |
| Three or more spinning disks | +1 |

0 points is `low`, 1 is `medium`, 2 or more is `high`. A virtual machine gets no class.

The kind comes from the DMI chassis type: 8, 9, 10, 14, 31 and 32 are laptops, as is
anything with a battery. 34, 35 and 36 are mini PCs. 17, 23, 28 and 29 are servers. 3, 4,
5, 6, 7, 13, 15, 16 and 24 are desktops.

A graphics card counts as separate when it's NVIDIA's, when its maker isn't the
processor's, or when there's more than one card from the processor's maker.

As root, the scan also measures the processor package's own power for half a second, from
its RAPL counter. That number is real, but it's the processor alone, while the scan runs.
The whole computer draws more.

### How the disks could be grouped

The scan suggests a layout the installer's Storage step can make. It leaves out the stick,
removable disks and a disk that says it's failing.

- The system goes on the fastest disk: not spinning first, NVMe first, then the smallest.
- The other disks are data disks. As one copy, their sizes add up. As two copies (btrfs
  RAID1), you can use half the total, or the total less the biggest disk if that's smaller.
- Two copies need two data disks.

### The JSON document

`bromigos hw salvage --json` prints one object. `schema` is 1.

```text
schema            1
scan              "salvage"
fatal             null, or why bromigOS can't run here at all
machine
  computer        {kind, model, virtual_machine}
                  kind: desktop, laptop, mini PC, server, virtual machine, computer
  processor       {model, cpuinfo_model, vendor, arch, threads, cores, sockets, level,
                   age_class, age_words, age_from, virtualisation, kvm, video}
    video         {source: "vainfo" or "driver", decode: [..], encode: [..], likely, from}
  memory          {total_gb, installed_gb, slots, slots_free, max_gb, type, ecc, source}
  disks           [{name, size_bytes, size, kind, rotational, model, removable, medium,
                    holds_data, health: "ok", "failing" or null}]
  storage         {system, data: [names], layouts: [{id, usable_bytes, survives_a_disk, words}]}
                  layout ids: one-disk, one-copy, two-copies
  graphics        [{vendor, model, driver, ready, state, vram_gib}]
  network         [{name, wifi, connected, speed_mbps, max_mbps}]
  firmware        {boot: "UEFI" or "BIOS", secure_boot: true, false or null, tpm: "2.0", "1.2" or null}
  power           {class: low, medium, high or null, estimate: true, from: [..], measured_w}
  privileged      whether it ran as root
  live            whether it ran from the stick
  unread          [{what, why}]
  identifiers     only with --identifiers: {hostname, mac: {port: address}, disk_serial: {disk: serial}}
budget_hardware   {cpu, ram_gb, disk_gb, gpu, gpu_vram_gb, gpu_name}: what the verdict was judged on
verdict
  roles           [{id, name, fit, reason, cause, items: [ids], left_out: [ids], budget}]
  items           [{id, name, group, fit, reason, cause, with: [ids added], budget: {cpu, ram_gb, disk_gb}}]
  groups          [{id, name}]: the catalogue's groups, in order
  cautions        [{id, text}]
upgrades          [{id, title, words, roles: [names], items: [names]}]
next              {roles: [ids], installer_roles: [the installer's ids], provision: [ids], budget, words}
```

`fit` is `yes`, `tradeoff` or `no`. `reason` is `provcatalog`'s sentence, and it's empty
for a yes. `cause` names the limit the reason is about: `memory`, `disk`, `graphics`,
`processor` or `conflict`. A role's `budget` is `provcatalog.budget`'s whole answer:
`{cpu, ram_gb, disk_gb, gpu_vram_gb, fits, notes}`.

A value the scan couldn't read is `null`, and `unread` says why.

### What it doesn't do

- It doesn't test anything. It runs no memory test, no disk read test and no stress test.
  Field Kit's Tools has those.
- It doesn't know parts that are known to cause trouble. There is no such list yet.
- It doesn't judge model sizes for local AI. [lab-models.md](lab-models.md) does that.
- It doesn't know prices, and it never recommends a product.

### Tests

`homelab/tests/test_salvage.py` scans six stand-in machines from
`homelab/tests/salvagefake.py`: a 2012 desktop, a small office PC, a mini PC, a laptop on
Wi-Fi, a virtual machine and a tower with a graphics card. Each is a fake root and recorded
tool outputs. A real subprocess fails the test, so nothing reads the machine the tests run
on.

They check the facts and the verdicts. They check every verdict against `provcatalog`, and
against the installer's own meter (`bromigos_installer/provision.py`) for the same
hardware. They check a scan without root, and that a saved report holds no serial number,
MAC address or hostname.

`iso/test/installer/test_salvage_answers.py` gives the answer file to the installer's own
reader.

```bash
(cd homelab && PYTHONPATH=lib python -m unittest discover -s tests -p 'test_salvage.py')
python -m unittest discover -s iso/test/installer -p 'test_salvage_answers.py'
```
