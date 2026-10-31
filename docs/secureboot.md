# Secure Boot

Most Windows PCs start with Secure Boot on: the firmware runs only boot software signed by
a key it trusts, which on almost every PC means Microsoft's. **Secure Boot can stay on.**
bromigOS starts with it on, from the USB stick and once installed. The first time the stick
starts on a PC, and the first time the installed system starts, a blue screen asks you to
approve bromigOS once. After that, every start is silent, and the boot menu looks the same
as with Secure Boot off.

For users, the [Download page](https://bromigos.org/download#secure-boot) and the manual's
[Install bromigOS](../manual/src/install.md#secure-boot) page say this in plain words, with
the screens. This page is how it works: the chain, the keys, what's re-signed when, and how
to recover.

## The medium

The chain is the one most Linux distributions use, with shim:

```text
firmware (Microsoft's keys in db)
  -> EFI/BOOT/BOOTx64.EFI   shim 16.1, Fedora's build, signed by Microsoft's UEFI CA 2011 and 2023
  -> EFI/BOOT/grubx64.efi   GRUB, signed with bromigOS's key, which shim checks against its MOK list
  -> the kernel             signed with bromigOS's key, checked by shim through GRUB's verifier
```

- **shim** is Fedora's signed build (`shim-x64-16.1-10`). Microsoft signs shim only for
  distributions that pass its review, so bromigOS uses one that has: it trusts whatever
  key the PC's owner enrolls in its MOK list, and nothing else of Fedora's matters here.
  `iso/secureboot/medium.sh` downloads the package from Fedora's build system and checks it
  against pinned SHA-256 sums, of the package and of `shimx64.efi` and `mmx64.efi`, and
  that Microsoft's signature is on it. A new shim means new pins, reviewed.
- **MokManager** (`mmx64.efi`, shim's own tool) sits beside it. When shim can't verify
  GRUB, because bromigOS's key isn't enrolled yet, it starts MokManager.
- **GRUB** is built again for the medium with every module its menus and the boot theme
  use built in, because with Secure Boot on GRUB loads no module from disk. Its SBAT data is
  Arch's (`/usr/share/grub/sbat.csv`), and shim's verifier is on, so the kernel GRUB starts
  must be signed too. Themes, fonts, pictures and configuration files are data and load as
  usual. The list is in `medium.sh`; a menu that needs another module must add it there.
- **The kernel** is signed before mkarchiso copies it onto the medium.
- **The certificate** is at the medium's root, `ENROLL_THIS_KEY_IN_MOKMANAGER.cer`, on the
  EFI system partition as well as the ISO, where MokManager's file list finds it.

**The menu is the themed one with Secure Boot on too.** In lockdown, GRUB loads no font
from the disk unless a verifier vouches for it (fonts are among the files its lockdown
verifier defers, and shim's verifier vouches only for kernels). GRUB never checks a file in
its own memdisk, though: the memdisk is part of the signed image. So `medium.sh` puts the
boot theme's fonts in GRUB's memdisk, as `fonts/<name>.pf2`, and the medium's `grub.cfg`
loads them by name (`loadfont geist-mono-regular-16`), which looks in `(memdisk)/fonts`
first. A medium built without a key has no memdisk fonts, and `grub.cfg` loads them from
the theme's folder as before. The theme's pictures and `theme.txt` load from the disk as
usual: lockdown doesn't defer them.

Not signed, so refused with Secure Boot on: Memtest86+, the UEFI shell, and the 32-bit
UEFI GRUB. With Secure Boot off, everything starts as before: shim then hands over without
checking.

`iso/build.sh --secureboot-key KEY --secureboot-cert CERT` builds it: `medium.sh` runs in
the build container, called from a copy of mkarchiso at two points (after the kernel leaves
the image, and once GRUB's EFI binary exists). The copy is made from the container's own
mkarchiso, and the build stops if either anchor isn't there exactly once, so a new archiso
gets looked at first. Without a key the medium is built as before, and starts only with
Secure Boot off.

### Enrolling the key, once per PC

What a person sees, with Secure Boot on, the first time (the screens' own words in bold;
`iso/ci-test.sh` walks through them and saves each one):

1. A blue screen titled **ERROR**: **Verification failed: (0x1A) Security Violation**.
   Press Enter (**OK**).
2. **Shim UEFI key management**: **Press any key to perform MOK management**, with a
   ten-second countdown. Press any key.
3. **Perform MOK management**: choose **Enroll key from disk**.
4. **Select Key**: choose the stick, **ARCHISO_EFI**.
5. Choose **ENROLL_THIS_KEY_IN_MOKMANAGER.cer**.
6. **[Enroll MOK]**: choose **Continue** (**View key 0** shows the certificate first).
7. **Enroll the key(s)?**: choose **Yes**.
8. **Perform MOK management**: choose **Reboot**. The PC starts the stick again (choose it
   in the boot menu if it starts Windows), and the bromigOS menu comes up.

The key stays in the PC's MOK list. Removing it: `sudo mokutil --delete` with the
certificate, from any Linux, then confirm in MokManager at the next start.

### Checking the certificate

The certificate is in the repository, `iso/secureboot/bromigos-secureboot.crt`:

| | |
|---|---|
| Subject | `O = BROMIGOS INC, CN = bromigOS Secure Boot signing key 2026` |
| SHA-256 | `9D:18:1B:07:00:B6:F8:74:94:01:6A:B7:3B:49:E4:A0:96:C7:7D:75:3E:A5:71:D7:75:DB:3E:1B:54:6E:E9:D5` |
| SHA-1 (MokManager shows this one) | `5F:EC:1D:6C:E1:8B:6B:D3:B9:6E:ED:E9:87:AE:B4:E9:EE:62:49:86` |
| Valid until | 2046-10-25 |

## The key

The private key never touches a workstation's disk or the repository. It's in the
deployment's secret store, and in the repository's Actions secrets
`ISO_SECUREBOOT_KEY` and `ISO_SECUREBOOT_CERT` (PEM). The ISO workflow uses it only for
runs that publish: it writes it to memory (`/dev/shm`) for the build, checks that the
certificate is the repository's and that the key is its key, mounts both read-only into
the build container, and removes them when the job ends. Every other build (pull
requests, `publish: false`) signs with a throwaway key made in the job, so the Secure Boot
test still runs.

**Rotating it** means everyone enrolls the new certificate once: put the new certificate
in `iso/secureboot/`, the key and certificate in the secret store and the two secrets, and
say so in the release notes. Old certificates stay in people's MOK lists, harmless.

## The installed system

The installed system starts through the same chain as the stick, with one difference: its
GRUB and kernels are signed on the computer, with a key of its own. Arch Linux's kernels and
GRUB aren't signed by anyone, and an update replaces them, so they can only be signed where
they're installed. bromigOS's own key never leaves CI, so it can't sign them there.

```text
firmware (Microsoft's keys in db, untouched)
  -> EFI/bromigos-secureboot/shimx64.efi   shim 16.1, the same Microsoft-signed build as the stick's
  -> EFI/bromigos-secureboot/grubx64.efi   GRUB, built on the computer with its modules and the boot
                                           theme's fonts inside, signed with the computer's key
  -> /boot/vmlinuz-linux                   the kernel, signed with the computer's key
```

The package is `bromigos-secureboot`. Its root helper,
`/usr/lib/bromigos/secureboot/bromigos-secureboot`, does the work, and `bromigos
secureboot` runs it:

```bash
bromigos secureboot                     # status: where it stands, in plain words
sudo bromigos secureboot setup          # set it up (--dry-run first shows what it would do)
sudo bromigos secureboot resign         # everything signed again (the pacman hooks do this)
sudo bromigos secureboot remove         # back as before setup
```

### What setup does

1. **The key.** It makes an RSA 2048 key and a self-signed certificate, once:
   `/var/lib/bromigos/secureboot/keys/machine.key` (the folder is root's only, `0700`,
   the key `0600`) and `/var/lib/bromigos/secureboot/machine.crt` (public). The certificate's
   name says which computer it's for, so MokManager's **View key** shows it.
2. **GRUB.** It builds GRUB with `grub-mkimage`, with every module in
   [`secureboot/grub-modules.txt`](../secureboot/grub-modules.txt) built in. With Secure
   Boot on, GRUB loads no module from the disk, so every command a menu may use is in the
   list: grub-mkconfig's scripts, grub-btrfs's snapshots, bromigOS's theme and entries. A
   memdisk inside the image holds the boot theme's fonts and a small `grub.cfg`, which finds
   `/boot/grub` by its file system's UUID and reads the real menu from there. Then it signs
   the image.
3. **The EFI system partition.** It puts shim, MokManager, GRUB and the certificate
   (`ENROLL_THIS_KEY_FOR_THIS_PC.cer`, for MokManager's file list) in
   `EFI/bromigos-secureboot/`. Where the disk has no Windows and the fallback path
   `EFI/BOOT/BOOTX64.EFI` is empty or a copy of the installer's GRUB, it puts shim there too,
   so the computer still starts if the firmware forgets its boot entries.
4. **The kernels.** It signs `/boot/vmlinuz-*`, Field Kit's kernel on `/boot`, and Field
   Kit's Unified Kernel Image on the EFI system partition. A Unified Kernel Image (UKI) is
   one EFI file holding a kernel, its initramfs and its command line.
5. **The firmware's boot entry.** It adds "bromigOS" (shim) and puts it first in the boot
   order, and keeps the order from before setup for `remove`. Field Kit's own entry, which
   pointed at its UKI, is made again to start shim with the UKI as shim's second stage, in
   the same place in the order. The firmware alone trusts only Microsoft's keys; shim checks
   the UKI against the enrolled key. The installer also removes its own GRUB entry, which it
   made moments before.
6. **The theme's fonts.** It takes them out of `/boot/grub/themes/bromigos` and makes
   `grub.cfg` again, because GRUB carries them now. grub-mkconfig writes a `loadfont` line
   for every font in the theme's folder, and those would fail with Secure Boot on. The boot
   theme's helper leaves them out from then on (it reads `fonts_embedded` in the state file).
7. **The enrollment.** `mokutil --import` asks for the certificate to be enrolled in shim's
   list at the next start, approved there with a code: four digits, or the ones given with
   `--code`. Digits, because MokManager's keyboard is always a US one, and digits are in the
   same place on every keyboard. The code is kept, root's only, in `keys/enroll-code`, so
   `sudo bromigos secureboot status` can show it until the key is enrolled.

`setup` runs again safely: it keeps the key, asks for no new enrollment while one is
waiting, and changes only what differs. Its state, `/var/lib/bromigos/secureboot/state.json`,
holds no secrets, and anyone may read it.

### What a person sees at the first start

With Secure Boot on or off, the first start after setup shows shim's blue screens once. Use
the arrow keys and <kbd>Enter</kbd>.

1. **Shim UEFI key management: Press any key to perform MOK management**, with a ten-second
   countdown. Press any key.
2. **Perform MOK management**: choose **Enroll MOK**.
3. **[Enroll MOK]**: choose **Continue**. (**View key 0** shows the certificate, with the
   computer's name.)
4. **Enroll the key(s)?**: choose **Yes**.
5. **Password**: type the code, then <kbd>Enter</kbd>. The installer shows the code on its
   last page; `bromigos secureboot setup` prints it.
6. **Perform MOK management**: choose **Reboot**.

Then the themed boot menu, the disk's passphrase and the login screen, as always. If the ten
seconds pass, the request stays, and the next start asks again. Without the code, choose
**Enroll key from disk** at step 2 instead, then the EFI system partition, then
`EFI/bromigos-secureboot/ENROLL_THIS_KEY_FOR_THIS_PC.cer`, then **Continue** and **Yes**:
the same steps as the stick's, with no code.

### Kept signed after updates

`bromigos-secureboot`'s pacman hooks sign again whatever an update replaces. They do nothing
until setup has run.

| Hook | When | What it does |
|---|---|---|
| `bromigos-secureboot-pre.hook` | Before a kernel upgrade | Keeps each signed kernel, its initramfs, and hard links to its modules in `/var/lib/bromigos/secureboot/last-good/` |
| mkinitcpio's post hook, `/usr/lib/initcpio/post/bromigos-secureboot` | When mkinitcpio copies a kernel to `/boot` | Signs it at once |
| `bromigos-secureboot.hook` | After a kernel, grub, font, shim, `bromigos-boot` or `bromigos-fieldkit` update | `resign`: GRUB built and signed again, shim made current, every kernel and Field Kit's files signed, the entries checked |
| `bromigos-secureboot-remove.hook` | Before `bromigos-secureboot` is removed | Stops the removal while Secure Boot is on and set up: the next kernel update wouldn't start |

pacman runs hooks in their files' name order, so `bromigos-secureboot.hook` runs after
mkinitcpio's `90-mkinitcpio-install.hook` and `bromigos-boot-menu.hook`, which copy the
kernels and Field Kit to `/boot`. GRUB is built again after a grub update, because a newer
shim elsewhere on the computer may raise the SBAT level, which refuses older GRUBs.

**When a kernel can't be signed**, the update doesn't leave a computer that won't start. The
hook puts the kept kernel, its initramfs and its modules back, so the next start uses the
kernel from before the update, signed. It says so in pacman's output, in plain words, and
`bromigos secureboot` status says so until it's fixed. `sudo bromigos secureboot resign`
then puts the update's kernel in `/boot` again, makes its initramfs, signs it, and removes
the kept files. The hooks never fail a pacman transaction.

### The keys

| Key | Where its private half is | What it signs | Trusted through |
|---|---|---|---|
| Microsoft's UEFI CA 2011 and 2023 | Microsoft | shim | the firmware's `db`, as shipped |
| bromigOS's release key | CI's secret store only ([The key](#the-key)) | the stick's GRUB and kernel | shim's MOK list, enrolled from the stick |
| The computer's own key | `/var/lib/bromigos/secureboot/keys/`, root's only, never copied off | the installed GRUB, kernels and Field Kit | shim's MOK list, enrolled at the first start |

**MOK or the firmware's own keys.** MOK is shim's list of keys, kept in a firmware variable
that only shim and MokManager can change, and only with someone at the keyboard. The
alternative is to replace the firmware's keys with your own (`sbctl`'s way). bromigOS uses
MOK because:

- **It works on every PC that starts the stick.** Enrolling your own firmware keys needs the
  firmware in setup mode, which each maker reaches differently, and some can't.
- **Microsoft's keys stay.** Graphics cards' firmware is signed by Microsoft's UEFI CA. A PC
  whose `db` loses that key may show no picture at all.
- **Windows and BitLocker aren't touched.** BitLocker seals its key to the Secure Boot
  policy (TPM PCR 7). Changing the firmware's keys changes that policy, and Windows then
  asks for its recovery key. MOK leaves the firmware's keys as they were.
- **It's one approval, with the same screens as the stick.**

Power users who run `sbctl` with their own keys can sign bromigOS's files with them
instead; `bromigos-secureboot` isn't needed then.

### What it protects, and what it doesn't

Secure Boot here means: the firmware runs only shim, shim runs only GRUB and kernels signed
by a key you enrolled, and GRUB runs in lockdown. On an encrypted install, someone with the
computer for a while can't swap the kernel or GRUB on the unencrypted `/boot` for their own.

- **The private key is on the root file system**, which is encrypted when the disk is. It
  can't be read with the computer off. Someone who is root on the running system can read
  it, and could sign something with it. Root can change anything on the system anyway, but
  not the MOK list: enrolling another key needs someone at MokManager.
- **Not the TPM.** Sealing the key in the TPM would keep it from being copied off the disk.
  The disk's encryption already does that. A key sealed to the running system's state is
  still usable by root, and the TPM adds a step every update depends on. So the key is a
  root-only file.
- **Not signed: the initramfs and `grub.cfg`.** GRUB reads them from `/boot`, which isn't
  encrypted, and shim's verifier checks kernels only, as on every distribution that starts
  through shim and GRUB. A Unified Kernel Image, as Field Kit's, signs all three together.
- **Arch Linux's kernel doesn't lock itself down** with Secure Boot on. Drivers built on the
  computer, as NVIDIA's DKMS module, keep loading.

### Windows beside bromigOS

The installer shares Windows' EFI system partition, and `setup` adds its own folder to it.
It never changes `EFI/Microsoft/`, Windows' fallback loader `EFI/BOOT/BOOTX64.EFI`, or
Windows' boot entry. Windows starts from GRUB's menu as before, or from the firmware's own
boot menu (the key that picks a boot device as the computer starts). BitLocker measures
how Windows was started, and a start through shim and GRUB looks different to it from a
start straight from the firmware. If it asks for its recovery key after a start from GRUB's
menu, start Windows from the firmware's boot menu instead: that's the start it expects.

### An existing install

A computer installed before this works the same. Nothing changes until you run setup:

```bash
sudo pacman -S bromigos-secureboot          # the package, if it isn't installed
bromigos secureboot                         # where it stands
sudo bromigos secureboot setup --dry-run    # what it would do, changing nothing
sudo bromigos secureboot setup              # do it; note the code it prints
```

Then restart. Shim's blue screens come up once, with Secure Boot on or off: enroll the key
with the code. Then turn Secure Boot on in the computer's setup if it's off. `bromigos
secureboot` should say **Ready**. It works where GRUB starts the computer, `/boot/grub/grub.cfg`
exists, and an EFI system partition is mounted at `/efi`, `/boot/efi` or `/boot`.

### If something goes wrong

- **Lost the code.** At the blue screen, choose **Enroll key from disk** and the file
  `ENROLL_THIS_KEY_FOR_THIS_PC.cer`, as above. Or run `sudo bromigos secureboot setup
  --code 1234` before the next start, for a new request with a code you choose.
- **Missed the ten seconds.** The next start asks again.
- **"Verification failed: (0x1A) Security Violation" at every start.** The computer's key
  isn't enrolled. Press <kbd>Enter</kbd>, then enroll it from disk as above.
- **A kernel update couldn't be signed.** The previous kernel starts. Run
  `sudo bromigos secureboot resign`.
- **Something else.** Turn Secure Boot off in the computer's setup. bromigOS starts with it
  off too: shim then hands over without checking. Then `sudo bromigos secureboot resign`, or
  `sudo bromigos secureboot remove` to go back to how it was before setup.

`remove` deletes the boot entry and `EFI/bromigos-secureboot/`, puts the boot order back,
and puts the theme's fonts back in `/boot`. It keeps the key, so setup can use it again, and
leaves it enrolled; `sudo mokutil --delete` with the certificate takes it out of the list,
confirmed in MokManager at the next start. A shim at the fallback path stays: it starts
GRUB with Secure Boot off too.

### Before this: Secure Boot off

A stick from before this, or a channel without `bromigos-secureboot`, can't set the
installed system up. Its installer says so, the live desktop shows it once in a
notification, and `bromigos-iso-secureboot check` exits 1. Turn Secure Boot off in the
computer's setup before you start the installed system, then run setup later, as for an
existing install.

## Testing it

`iso/ci-test.sh ISO --out DIR --secureboot-cert CERT [--secureboot-package PKG]` boots the
medium in QEMU with OVMF's Secure Boot build and the variables of a Windows PC (Microsoft's
PK, KEK and db, from `virt-fw-vars --enroll-microsoft`), Secure Boot on, nothing of
bromigOS's enrolled. The ISO workflow runs it for every medium it builds, on GitHub's hosted
runner.

- **The medium.** It goes through MokManager's enrollment as above, keystroke by keystroke,
  saving each screen (`shots/mok-*.png`). Then it must reach the live desktop and pass the
  live checks, with the firmware saying Secure Boot is on and the key in the MOK list.
- **The installed system.** With `--secureboot-package` (the ISO workflow builds
  `bromigos-secureboot` from the same ref), the package goes into the medium's store first.
  Then: an encrypted install, which sets Secure Boot up; the first start, through MokManager
  with the installer's code (`shots/mokm-*.png`); the boot menu, which must be the theme's
  (`shots/grub-secureboot.png`); Secure Boot on, the key enrolled, everything signed and the
  key's folder root's only. Then a kernel update, signed again, and a start after it; then a
  Unified Kernel Image of the system in a firmware entry like Field Kit's, routed through
  shim by `resign`, started once with `BootNext`.
- **Beside Windows.** From the variables after the medium's enrollment: a stand-in Windows
  (`iso/test/fake-windows.sh`) with a "Windows Boot Manager" firmware entry, the text
  installer's install beside it, the first start through MokManager, then: Windows' files and
  boot files unchanged, Windows in GRUB's menu, its firmware entry still there, and bromigOS
  first in the boot order.

`secureboot/tests` (the package's `check()`) tests the helper in a stand-in root, with real
`openssl`, `sbsign` and `grub-mkimage` and stand-ins for the firmware: setup, a kernel update
signed again, a kernel that can't be signed (the previous one put back, then fixed with
`resign`), Windows' files left alone, `remove`, and a dry run that changes nothing.
