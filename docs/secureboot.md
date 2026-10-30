# Secure Boot

Most Windows PCs start with Secure Boot on: the firmware runs only boot software signed
by a key it trusts, which on almost every PC means Microsoft's. The bromigOS medium
starts with Secure Boot on. The first time, on each PC, you enroll bromigOS's key once.
The installed system can't start with Secure Boot on yet: before you start it, turn
Secure Boot off ([The installed system](#the-installed-system)).

For users, the [Download page](https://bromigos.org/download#secure-boot) says all this
in plain words, with how to turn Secure Boot off on common PCs.

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

**The menu looks plainer with Secure Boot on.** In lockdown GRUB loads no font file unless
a verifier vouches for it (fonts are among the files its lockdown verifier defers), and
shim's verifier vouches only for kernels. Without a font the boot theme can't draw, so
`grub.cfg` falls back to the text menu: the same entries, in the firmware's console. With
Secure Boot off the theme shows as always. Bringing it back under Secure Boot would mean
GRUB's own signature checking (`--pubkey`, a `.sig` beside every file GRUB opens),
which would also stop "Boot from disk" from starting another system's unsigned loader.

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

Not yet: the installer's GRUB and kernel aren't signed. A PC that started the medium with
Secure Boot on would refuse the installed system. So:

- the live desktop says so, once, in a notification, when Secure Boot is on;
- `bromigos-iso-secureboot check` prints the same in plain words and exits 1, for the
  installer to show before it installs (`state` prints `on`, `off` or `none`);
- the Download page and the manual say to turn Secure Boot off before starting the
  installed system.

Doing it properly needs, on the installed system: shim and MokManager on the EFI system
partition, GRUB installed with its modules built in and signed, the kernel signed again on
every update (a pacman hook), and a key of the machine's own, enrolled with
`mokutil --import` and confirmed in MokManager at the first start. That machine key is
the owner's, made at install; bromigOS's key signs only what bromigOS builds.

## Testing it

`iso/ci-test.sh ISO --out DIR --secureboot-cert CERT` boots the medium in QEMU with OVMF's
Secure Boot build and the variables of a Windows PC (Microsoft's PK, KEK and db, from
`virt-fw-vars --enroll-microsoft`), Secure Boot on, nothing of bromigOS's enrolled. It
goes through MokManager's enrollment as above, keystroke by keystroke, saving each screen
(`shots/mok-*.png`), then must reach the live desktop and pass the live checks, with the
firmware saying Secure Boot is on and the key in the MOK list. The ISO workflow runs it
for every medium it builds.
