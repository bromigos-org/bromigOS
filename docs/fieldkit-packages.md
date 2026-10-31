# Field Kit's packages

<!-- Made by iso/fieldkit/manifest.py from iso/fieldkit/packages.toml and the build's sizes. Edit those, not this page. -->

Every package on the Field Kit medium is here for a reason. A package goes on it only when
one of these needs it: (a) a Field Kit menu item, (b) booting and hardware support on
unknown machines, (c) bromigOS Server, the installed edition, or (d) a documented server or lab
job. [fieldkit.md](fieldkit.md) describes Field Kit.

Sizes are each package's own installed size. Their dependencies come with them; the
totals below count those too.

- The running medium: 552 packages with their dependencies, 2691.7 MiB installed.
- The offline store: 585 package files, 1205.3 MiB (compressed, as downloaded).

## Boot & hardware

| Package | Size | On | Why |
|---|---:|---|---|
| `base` | 0 KiB | medium, Server | the base system: systemd, pacman, coreutils, the shell |
| `linux` | 161.6 MiB | medium, Server | the kernel and its drivers |
| `linux-firmware-intel` | 138.0 MiB | medium, Server | Intel Wi-Fi, Bluetooth and graphics |
| `linux-firmware-amdgpu` | 28.1 MiB | medium, Server | AMD graphics (Radeon RX and newer) |
| `linux-firmware-radeon` | 2.3 MiB | medium, Server | older AMD/ATI graphics |
| `linux-firmware-realtek` | 7.7 MiB | medium, Server | Realtek Ethernet, Wi-Fi and Bluetooth |
| `linux-firmware-atheros` | 53.3 MiB | medium, Server | Qualcomm/Atheros Wi-Fi and Bluetooth |
| `linux-firmware-mediatek` | 37.0 MiB | medium, Server | MediaTek Wi-Fi and Bluetooth |
| `linux-firmware-broadcom` | 12.9 MiB | medium, Server | Broadcom Ethernet, Wi-Fi and Bluetooth |
| `linux-firmware-other` | 20.2 MiB | medium, Server | other network and storage controllers (server NICs and HBAs among them) |
| `amd-ucode` | 603 KiB | Server | processor fixes loaded at startup |
| `intel-ucode` | 31.4 MiB | Server | processor fixes loaded at startup |
| `mkinitcpio` | 219 KiB | medium | the medium's startup files (finding the medium, copy to memory) |
| `mkinitcpio-archiso` | 47 KiB | medium | the medium's startup files (finding the medium, copy to memory) |
| `syslinux` | 4.3 MiB | medium | the BIOS boot menu (mkarchiso's bios.syslinux) |
| `grub` | 43.2 MiB | medium, Server | the UEFI boot menu; Repair the boot menu reinstalls it on an install |
| `efibootmgr` | 84 KiB | medium, Server | the firmware's boot entries: Repair the boot menu, Windows boot repair |
| `edk2-shell` | 6.2 MiB | medium | the boot menu's UEFI shell entry |
| `memtest86+` | 206 KiB | medium | the boot menu's memory test |
| `memtest86+-efi` | 405 KiB | medium | the boot menu's memory test |
| `kmscon` | 1.7 MiB | medium, Server | the console: true colour, Geist Mono at a readable size, DRIFTGLASS (the plain console when there's no KMS) |
| `ttf-geist-mono` | 2.6 MiB | medium, Server | Geist Mono for kmscon (bromigOS's font) |
| `ttf-nerd-fonts-symbols-mono` | 2.5 MiB | medium, Server | the icons in Field Kit's screens (kmscon falls back to it for them; MIT) |
| `pango` | 2.4 MiB | medium, Server | kmscon's font engine: Geist Mono with a fallback for icons |
| `sof-firmware` | 55.1 MiB | medium | sound on current laptops, for the screen reader |
| `alsa-utils` | 2.5 MiB | medium | sound on current laptops, for the screen reader |
| `espeakup` | 32 KiB | medium | the screen reader (speech): the boot menu's speech entry |
| `brltty` | 9.5 MiB | medium | braille displays |
| `livecd-sounds` | 306 KiB | medium | the screen reader's cue sounds (releng's livecd-talk) |
| `bolt` | 439 KiB | medium | Thunderbolt docks and their Ethernet |
| `networkmanager` | 18.1 MiB | medium, Server | networking: Lab › Network settings (nmtui), wired DHCP by itself |
| `wpa_supplicant` | 8.3 MiB | medium | Wi-Fi for NetworkManager, the country rules, iw for diagnosis |
| `wireless-regdb` | 22 KiB | medium | Wi-Fi for NetworkManager, the country rules, iw for diagnosis |
| `iw` | 284 KiB | medium | Wi-Fi for NetworkManager, the country rules, iw for diagnosis |
| `modemmanager` | 4.7 MiB | medium | mobile broadband (USB and built-in modems) through nmtui |
| `usb_modeswitch` | 253 KiB | medium | mobile broadband (USB and built-in modems) through nmtui |
| `ppp` | 943 KiB | medium | mobile broadband (USB and built-in modems) through nmtui |
| `usbutils` | 393 KiB | medium, Server | lsusb and lspci: the graphics diagnosis and the hardware report |
| `pciutils` | 418 KiB | medium, Server | lsusb and lspci: the graphics diagnosis and the hardware report |
| `kitty-terminfo` | 4 KiB | medium, Server | correct keys and colours over SSH from bromigOS's terminals |
| `ghostty-terminfo` | 4 KiB | medium, Server | correct keys and colours over SSH from bromigOS's terminals |
| `terminus-font` | 3.0 MiB | medium, Server | the text installer's console font on the plain console (ter-v24b), and bromigOS Server's |

## Repair

| Package | Size | On | Why |
|---|---:|---|---|
| `btrfs-progs` | 6.8 MiB | medium, Server | bromigOS's file system: mounting, snapshots, rollback, scrub |
| `cryptsetup` | 3.6 MiB | medium, Server | unlocking the encrypted install |
| `arch-install-scripts` | 39 KiB | medium | arch-chroot into an install; pacstrap for the installer |
| `dosfstools` | 409 KiB | medium | checking and making the /boot (EFI) partition |
| `exfatprogs` | 347 KiB | medium | USB drives formatted exFAT, for backups |
| `ntfs-3g` | 171 KiB | medium | Windows repair: ntfsfix; NTFS backup drives |
| `chntpw` | 366 KiB | medium | Windows repair: reset a local account's password |
| `parted` | 2.7 MiB | medium | partition tables: Tools › Partition a drive (cfdisk is util-linux's) |
| `gptfdisk` | 735 KiB | medium | partition tables: Tools › Partition a drive (cfdisk is util-linux's) |
| `smartmontools` | 2.1 MiB | medium, Server | Check disks: the drives' own health; NVMe secure erase |
| `nvme-cli` | 6.0 MiB | medium, Server | Check disks: the drives' own health; NVMe secure erase |
| `nwipe` | 614 KiB | medium | Erase a disk securely: the overwrite method for drives without their own secure erase (bromigOS's build: not in Arch's repositories) |
| `dislocker` | 202 KiB | medium | Windows repair: reading a BitLocker drive with its recovery key (bromigOS's build: not in Arch's repositories) |
| `hdparm` | 182 KiB | medium | ATA secure erase |
| `partclone` | 1.9 MiB | medium | disk images and clones, in Clonezilla's format |
| `testdisk` | 1.7 MiB | medium | Recover deleted files (PhotoRec), Repair a partition table (TestDisk) |
| `ddrescue` | 288 KiB | medium | Copy a failing drive |
| `rsync` | 859 KiB | medium, Server | Back up my files to a USB drive |
| `cifs-utils` | 302 KiB | medium | disk images to and from a network share (LAN) |
| `nfs-utils` | 1.4 MiB | medium | disk images to and from a network share (LAN) |
| `micro` | 13.1 MiB | medium | Edit a file on my install, with highlighting |
| `lynx` | 5.2 MiB | medium | the bromigOS manual, readable offline |
| `archinstall` | 7.9 MiB | medium | Install bromigOS Server on this computer (the installer's engine) |

## Lab

| Package | Size | On | Why |
|---|---:|---|---|
| `bromigos-lab` | 6.2 MiB | medium, Server | Lab › Lab console, Provision a machine, Model catalog (works offline) |
| `bromigos-lab-catalog` | 455 KiB | medium, Server | Lab › Lab console, Provision a machine, Model catalog (works offline) |
| `bromigos-homelab` | 1.7 MiB | medium, Server | Lab › Media library (bromigos media) and the lab's adapters |
| `openssh` | 6.8 MiB | medium, Server | Remote help; provisioning lab machines over SSH; the edition's SSH (off until turned on) |
| `ansible-core` | 24.0 MiB | medium, Server | Lab › Provision a machine: applies a reviewed plan |
| `python-zeroconf` | 5.7 MiB | medium, Server | finding lab machines that announce themselves (mDNS) |
| `sops` | 49.9 MiB | medium, Server | encrypted lab credentials without Vault |
| `age` | 12.6 MiB | medium, Server | encrypted lab credentials without Vault |

## Tools

| Package | Size | On | Why |
|---|---:|---|---|
| `btop` | 1.7 MiB | medium, Server | Tools › System monitor (bromigos-apps-terminal needs it too) |
| `htop` | 421 KiB | medium, Server | Tools › Processes |
| `nvtop` | 202 KiB | medium, Server | Tools › Graphics card monitor |
| `gdu` | 21.7 MiB | medium, Server | Tools › Disk usage |
| `inxi` | 1.4 MiB | medium | Tools › Hardware report |
| `dmidecode` | 208 KiB | medium, Server | the hardware report's board and memory details |
| `ethtool` | 987 KiB | medium, Server | network diagnosis: link speed and cable |
| `mtr` | 135 KiB | medium | Tools › Network: trace a route, measure speed, scan the local network, watch traffic |
| `iperf3` | 320 KiB | medium | Tools › Network: trace a route, measure speed, scan the local network, watch traffic |
| `nmap` | 26.5 MiB | medium | Tools › Network: trace a route, measure speed, scan the local network, watch traffic |
| `tcpdump` | 1.1 MiB | medium | Tools › Network: trace a route, measure speed, scan the local network, watch traffic |
| `bluez` | 1.7 MiB | medium, Server | Tools › Bluetooth (bromigos bluetooth tui) |
| `bluez-utils` | 3.7 MiB | medium, Server | Tools › Bluetooth (bromigos bluetooth tui) |
| `tmux` | 1.4 MiB | medium, Server | Tools › Terminal sessions; Remote help's shared session |
| `herdr` | 23.9 MiB | medium, Server | Tools › Herdr; Remote help |
| `zsh` | 6.9 MiB | medium, Server | the shell and bromigOS's prompt (TTY-aware) |
| `mehshell` | 3.0 MiB | medium, Server | the shell and bromigOS's prompt (TTY-aware) |
| `nano` | 2.7 MiB | medium, Server | a plain editor for guides that say nano |
| `less` | 338 KiB | medium, Server | the pager journalctl and git use |
| `neovim` | 30.5 MiB | medium | Tools › Neovim, for people who know it |
| `lazygit` | 20.4 MiB | medium | Tools › lazygit, for people who know it |
| `fzf` | 5.5 MiB | medium | finding and reading: fuzzy finder: Ctrl+R history, Ctrl+T files, Alt+C folders, in DRIFTGLASS colours |
| `ripgrep` | 4.3 MiB | medium | finding and reading: search file contents fast (rg) |
| `fd` | 3.4 MiB | medium | finding and reading: find files by name |
| `bat` | 5.1 MiB | medium | finding and reading: read a file with highlighting (cat) |
| `eza` | 1.8 MiB | medium | finding and reading: list files, with icons and git state (ls) |
| `zoxide` | 1.1 MiB | medium | finding and reading: jump to folders you use (z) |
| `tree` | 94 KiB | medium | finding and reading: a folder as a tree |
| `jq` | 481 KiB | medium | finding and reading: read and change JSON |
| `yq` | 289 KiB | medium | finding and reading: the same for YAML and TOML (jq's wrapper) |
| `file` | 10.5 MiB | medium | finding and reading: what kind of file this is |
| `tealdeer` | 3.2 MiB | medium | finding and reading: tldr: short examples for a command, its pages pre-filled at build so it works offline |
| `man-db` | 2.4 MiB | medium | finding and reading: manual pages (man) |
| `man-pages` | 5.7 MiB | medium | finding and reading: the manual pages of Linux and its C library |
| `curl` | 2.3 MiB | medium | network: fetch a URL |
| `wget` | 5.7 MiB | medium | network: download a file |
| `aria2` | 5.4 MiB | medium | network: download with resume and several connections |
| `mosh` | 655 KiB | medium | network: a remote shell that survives a bad network |
| `sshfs` | 90 KiB | medium | network: a remote folder over SSH |
| `socat` | 580 KiB | medium | network: connect two streams (serial ports, sockets) |
| `openbsd-netcat` | 47 KiB | medium | network: test a port (nc) |
| `iproute2` | 3.1 MiB | medium, Server | network: addresses and routes (ip) |
| `iputils` | 665 KiB | medium, Server | network: ping |
| `bind` | 7.1 MiB | medium | network: DNS lookups (dig) |
| `traceroute` | 79 KiB | medium | network: the route to a host |
| `iwd` | 2.2 MiB | medium | network: Wi-Fi without NetworkManager, for impala (off unless started) |
| `impala` | 5.1 MiB | medium | network: Wi-Fi in the terminal, on iwd |
| `wireguard-tools` | 267 KiB | medium | network: WireGuard VPN (wg) |
| `tailscale` | 51.7 MiB | medium | network: a tailnet, to reach a lab from anywhere (off unless started) |
| `smbclient` | 29.0 MiB | medium | network: Windows and NAS shares (smbclient) |
| `lvm2` | 5.3 MiB | medium | disks and files: LVM volumes |
| `mdadm` | 1.0 MiB | medium | disks and files: software RAID |
| `xfsprogs` | 4.6 MiB | medium | disks and files: XFS |
| `f2fs-tools` | 727 KiB | medium | disks and files: F2FS (phones, SD cards) |
| `fsarchiver` | 255 KiB | medium | disks and files: file-system archives |
| `squashfs-tools` | 939 KiB | medium | disks and files: squashfs images |
| `7zip` | 6.5 MiB | medium | disks and files: 7z, zip and most archives |
| `unzip` | 308 KiB | medium | disks and files: zip archives |
| `zip` | 567 KiB | medium | disks and files: make zip archives |
| `pigz` | 176 KiB | medium | disks and files: gzip on every core |
| `xz` | 2.9 MiB | medium | disks and files: xz archives |
| `zstd` | 1.5 MiB | medium | disks and files: zstd archives |
| `iotop` | 247 KiB | medium | system and debugging: what's using the disk |
| `sysstat` | 1.6 MiB | medium | system and debugging: iostat, sar, mpstat |
| `lsof` | 381 KiB | medium | system and debugging: what has a file open |
| `strace` | 1.7 MiB | medium | system and debugging: what a program asks the kernel |
| `ltrace` | 444 KiB | medium | system and debugging: what a program asks its libraries |
| `gdb` | 32.2 MiB | medium | system and debugging: the debugger |
| `lm_sensors` | 487 KiB | medium | system and debugging: temperatures and fans (sensors) |
| `lshw` | 8.1 MiB | medium | system and debugging: every device, in detail |
| `hwinfo` | 3.9 MiB | medium | system and debugging: hardware probe |
| `mokutil` | 62 KiB | medium | system and debugging: Secure Boot's machine owner keys |
| `sbctl` | 10.3 MiB | medium | system and debugging: Secure Boot keys and signing |
| `fwupd` | 19.1 MiB | medium | system and debugging: firmware versions; updates from a file on the stick (offline) |
| `memtester` | 33 KiB | medium | system and debugging: test memory from a running system |
| `stress-ng` | 19.1 MiB | medium | system and debugging: load the machine to find faults |
| `powertop` | 846 KiB | medium | system and debugging: what uses power |
| `wimlib` | 878 KiB | medium | Windows and security: Windows images (.wim) |
| `gnupg` | 10.4 MiB | medium | Windows and security: signatures and encryption (gpg) |

## Server

| Package | Size | On | Why |
|---|---:|---|---|
| `python-textual` | 10.0 MiB | medium, Server | the text installer's screens, and bromigOS Server's welcome tour after an install (bromigos welcome-console) |
| `bromigos-fieldkit-tools` | 229 KiB | medium, Server | the Field Kit menu's engine: the repairs, the stick's settings, remote help, make-stick (the menu's screens are bromigos-core's) |
| `bromigos-server` | 44 KiB | Server | bromigOS Server, the installed edition: SSH, the firewall, safe automatic updates, containers, the lab's cluster and monitoring |
| `bromigos-keyring` | 12 KiB | medium, Server | bromigOS's signing key: updates are verified |
| `bromigos-core` | 78.1 MiB | medium, Server | the bromigos command: update, rollback, hw, console, bluetooth tui |
| `bromigos-boot` | 9.2 MiB | medium, Server | the boot menu's theme and options, the console's font and colours |
| `bromigos-apps-terminal` | 22 KiB | medium, Server | LazyVim, tmux, lazygit and mise, configured; LazyVim's plugins fetched at build, so Neovim works offline |
| `bromigos-manual` | 9.4 MiB | medium, Server | the manual, offline |
| `sudo` | 7.9 MiB | medium, Server | the edition's administrator rights |
| `snapper` | 3.7 MiB | Server | snapshots before every update, and rollback from the boot menu |
| `snap-pac` | 36 KiB | Server | snapshots before every update, and rollback from the boot menu |
| `grub-btrfs` | 106 KiB | Server | snapshots before every update, and rollback from the boot menu |
| `inotify-tools` | 1.6 MiB | Server | snapshots before every update, and rollback from the boot menu |
| `nftables` | 1.2 MiB | Server | the firewall: SSH, ping and the lab's monitoring in, the rest dropped |
| `podman` | 82.7 MiB | Server | containers, the way the lab runs services |
| `podman-docker` | 12 KiB | Server | the docker command, for the lab's compose files and people's habits |
| `podman-compose` | 763 KiB | Server | compose files with Podman (the lab's monitoring uses compose) |
| `crun` | 828 KiB | Server | the container runtime Podman starts containers with |
| `netavark` | 10.4 MiB | Server | containers' networking for Podman |
| `prometheus-node-exporter` | 17.5 MiB | Server | the metrics the lab's Prometheus reads, on port 9100 (local network only) |

## The largest

The 20 largest packages on the medium, dependencies included:

| Package | Size |
|---|---:|
| `linux` | 161.6 MiB |
| `mise` | 153.2 MiB |
| `linux-firmware-intel` | 138.0 MiB |
| `bromigos-core` | 78.1 MiB |
| `python` | 73.8 MiB |
| `perl` | 72.3 MiB |
| `sof-firmware` | 55.1 MiB |
| `guile` | 54.5 MiB |
| `linux-firmware-atheros` | 53.3 MiB |
| `tailscale` | 51.7 MiB |
| `boost-libs` | 51.1 MiB |
| `glibc` | 50.7 MiB |
| `sops` | 49.9 MiB |
| `binutils` | 43.8 MiB |
| `icu` | 43.2 MiB |
| `grub` | 43.2 MiB |
| `systemd` | 40.6 MiB |
| `glib2` | 38.4 MiB |
| `linux-firmware-mediatek` | 37.0 MiB |
| `git` | 33.5 MiB |

## Left out

Arch's own live medium (archiso's releng profile) carries these; Field Kit doesn't.

| Packages | Why not |
|---|---|
| linux-firmware (the whole set) | its split parts above cover common Wi-Fi, Ethernet, Bluetooth and graphics; the rest is below |
| nvidia-open nvidia-utils (in the offline store) | NVIDIA's driver for a lab machine's compute: about 400 MiB with what it pulls in (Mesa, LLVM). bromigOS Server installs it once online (an open question: carry it?) |
| linux-firmware-nvidia | only for nouveau on the live system, which Field Kit doesn't load (the basic display instead); in the offline store for lab GPU installs |
| linux-firmware-marvell | Marvell Wi-Fi (Surface devices) and some server NICs: 79 MiB for rare hardware (an open question) |
| linux-firmware-cirrus linux-firmware-ti linux-firmware-amd | laptop audio codecs, TI chips, AMD's security processor: not needed to boot, network or repair |
| archlinux releng: clonezilla partimage | Field Kit's own imaging (partclone, in Clonezilla's format) replaces them |
| archlinux releng: cloud-init | for cloud images; the test harness uses a test build's key instead |
| archlinux releng: hyperv open-vm-tools qemu-guest-agent virtualbox-guest-utils-nox | guest tools for virtual machines; Field Kit is for real machines (an open question for VM servers) |
| archlinux releng: wireless_tools dhcpcd wvdial | NetworkManager covers Wi-Fi, wired DHCP and modems; one network stack |
| archlinux releng: openvpn openconnect vpnc pptpclient xl2tpd systemd-resolvconf | VPN clients: no menu item or lab job uses them yet |
| archlinux releng: nbd open-iscsi mkinitcpio-nfs-utils | network block devices and PXE boot hooks: Field Kit boots from a stick or /boot |
| archlinux releng: bcachefs-tools jfsutils nilfs-utils udftools fatresize gpart mtools | file systems bromigOS doesn't use |
| archlinux releng: dmraid | fake RAID (BIOS RAID): mdadm reads the formats that matter |
| archlinux releng: tpm2-tools tpm2-tss libfido2 pcsclite openpgp-card-tools sequoia-sq | TPM, FIDO2 and smartcard unlocking and signing: bromigOS unlocks with a passphrase |
| archlinux releng: ldns ndisc6 darkhttpd lftp irssi mc pv screen vim | duplicates of kept tools (nmap, curl, tmux, micro, neovim) or nothing on the menu |
| archlinux releng: refind syslinux-hdt b43-fwcutter linux-atm usbmuxd mmc-utils sdparm sg3_utils lsscsi | other boot loaders, old Broadcom firmware cutting, ADSL, iPhone tethering, SCSI and MMC tools |
| archlinux releng: grml-zsh-config terminus-font | bromigOS's own prompt (mehshell) and console font (Geist Mono) |
| archlinux releng: reflector xdg-utils dnsmasq gpm | mirror ranking (Field Kit is offline-first), image building (the build machine's), desktop helpers, a DHCP server, the console mouse |
| helm libvirt-python qemu-base cloud-image-utils | the lab's Kubernetes and local-VM provisioning: large, and only for labs that use them (installable later, with a network) |
| base-devel paru | building AUR packages: not an offline job |
| mesa vulkan-* libva-* and the desktop | Field Kit has no desktop: Install › the full bromigOS desktop downloads it |
| ncdu | gdu does the same job |
| p7zip dislocker (Arch) | not in Arch's repositories: 7zip replaces p7zip; dislocker is bromigOS's own build |
| go-yq | yq (the jq wrapper) reads YAML and TOML in 0.3 MiB; go-yq is 14 MiB |
