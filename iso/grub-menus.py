#!/usr/bin/env python3
"""The media's GRUB menus, from one description (docs/boot.md, "The ISO's menu"; docs/fieldkit.md).

  iso/grub-menus.py            rewrites the entries of iso/profile/grub/{grub,loopback}.cfg and
                               iso/fieldkit/grub/{grub,loopback}.cfg
  iso/grub-menus.py --check    exits 1 when one of them isn't what this would write

Each file keeps its own head (the theme, the serial console, the platform's names, up to "# Set
default menu entry"); this writes the rest: the top level in plain sentences, "More options ›"
for the rest, and "Help: what do these do?" (H), a page with a paragraph per entry. An entry
for installing says when an answer file is on the stick (unattended) and then counts down to
it. grub.cfg starts the medium by its UUID; loopback.cfg as an ISO file another GRUB (Ventoy's
GRUB2 mode) loop-mounted.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MARK = "# Set default menu entry"
# DRIFTGLASS's 16 colours on the kernel's console from its first message (the Wick's terminal
# colours, as bromigos-boot's palette.vtrgb): the full medium's Field Kit entry
VT = "vt.default_red=0,255,57,212,90,201,63,180,78,255,156,240,140,227,138,230 vt.default_grn=5,118,255,175,169,123,224,200,107,157,255,211,202,168,245,245 vt.default_blu=0,111,20,55,230,219,197,180,78,151,138,106,245,239,226,230"
ANSWERS = {"server": "/fieldkit/install-server.toml", "desktop": "/fieldkit/install-desktop.toml"}


def linux(title, cls, ident, extra, loop, hotkey="", indent=""):
    search = 'img_dev=UUID=${archiso_img_dev_uuid} img_loop="${iso_path}"' if loop else "archisosearchuuid=%ARCHISO_UUID%"
    hk = f" --hotkey {hotkey}" if hotkey else ""
    body = [f'menuentry "{title}"{hk} --class {cls} --id \'{ident}\' {{', "    set gfxpayload=keep",
            f"    linux /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux archisobasedir=%INSTALL_DIR% {search}{extra}",
            "    initrd /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img", "}"]
    return "\n".join(indent + b for b in body) + "\n"


def install(edition, title, cls, ident, extra, loop):
    """The install entry, and its unattended form when the stick has an answer file: then it's
    the default, with a countdown."""
    f = ANSWERS[edition]
    return (f"# {title}: the installer, {edition} preselected; with {f} on the stick, unattended\n"
            f"if search --no-floppy --set=answers --file {f}; then\n"
            + linux(f"{title} (answers found on the stick: unattended)", cls, ident,
                    f"{extra} bromigos.answers={f}", loop, indent="    ")
            + f"    set default='{ident}'\n    set timeout=15\nelse\n"
            + linux(title, cls, ident, extra, loop, indent="    ") + "fi\n\n")


def help_page(lines):
    def quoted(line):
        return '"' + line.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'
    body = "\n".join(f"    echo {quoted(line)}" for line in ["", *lines, "", "Press Enter to go back to the menu."])
    return ("# a page in plain words for every entry (H from the menu)\n"
            "menuentry \"Help: what do these do?\" --hotkey h --class info --id 'help' {\n"
            "    insmod read\n"
            "    # an entry starts with only exported variables: the theme's text colours again\n"
            "    if [ -f /boot/grub/themes/bromigos/colors.cfg ]; then source /boot/grub/themes/bromigos/colors.cfg; fi\n"
            "    clear\n" + body + "\n    read\n}\n\n")


def indent(text, n=4):
    return "".join((" " * n + line) if line.strip() else line for line in text.splitlines(True))


# releng's entries both media keep: the memory test, the disk's own system (grub.cfg only),
# the UEFI shell and firmware settings, power, in plain words
MEMTEST = r'''# Memtest86+ on UEFI: releng's path, or memtest86+-efi 8's own name, which mkarchiso 91 doesn't
# copy (iso/build-in-container.sh puts it beside this file)
if [ "${grub_platform}" == 'efi' -a "${grub_cpu}" == 'x86_64' ]; then
    if [ -f '/boot/memtest86+/memtest.efi' ]; then
        memtest_efi='/boot/memtest86+/memtest.efi'
    elif [ -f '/boot/grub/memtest86x64.efi' ]; then
        memtest_efi='/boot/grub/memtest86x64.efi'
    fi
    if [ -n "${memtest_efi}" ]; then
        menuentry "Test this computer's memory" --class memtest --id 'memtest' {
            set gfxpayload=800x600,1024x768
            linux "${memtest_efi}"
        }
    fi
fi
if [ "${grub_platform}" == 'pc' -a -f '/boot/memtest86+/memtest' ]; then
    menuentry "Test this computer's memory" --class memtest --id 'memtest' {
        set gfxpayload=800x600,1024x768
        linux /boot/memtest86+/memtest
    }
fi
'''

DISK = r'''# the installed system: its own GRUB menu (its grub.cfg on another disk than this medium,
# read here: a GRUB chainloaded from this one loses its way to its prefix), else the first
# other boot loader found there (systemd-boot's, limine's, Windows', the removable path),
# else the firmware's next device. connectefi: a firmware that booted the medium "fast" may
# not have connected the other disks
if [ "${grub_platform}" == 'efi' ]; then
    menuentry "Start the system on this computer's disk" --class disk --id 'disk' {
        insmod regexp
        insmod connectefi
        connectefi all
        regexp --set=1:medium_disk '^([^,]*)' "${root}"
        for cfg in (*)/grub/grub.cfg (*)/boot/grub/grub.cfg ; do
            if [ -f "${cfg}" ] ; then
                regexp --set=1:cfg_disk '^\(([^,)]*)' "${cfg}"
                regexp --set=1:cfg_dev '^\(([^)]*)\)' "${cfg}"
                if [ "${cfg_disk}" != "${medium_disk}" ] ; then
                    set root="${cfg_dev}"
                    configfile "${cfg}"
                fi
            fi
        done
        for loader in (*)/EFI/systemd/systemd-bootx64.efi (*)/EFI/limine/BOOTX64.EFI (*)/EFI/Microsoft/Boot/bootmgfw.efi (*)/EFI/BOOT/BOOTX64.EFI ; do
            if [ -f "${loader}" ] ; then
                regexp --set=1:loader_disk '^\(([^,)]*)' "${loader}"
                if [ "${loader_disk}" != "${medium_disk}" ] ; then
                    chainloader "${loader}"
                    boot
                fi
            fi
        done
        exit
    }
fi
'''

UEFI = r'''if [ "${grub_platform}" == 'efi' ]; then
    if [ -f "/shell${uefi_machine_type_lower}.efi" ]; then
        menuentry 'Open the UEFI shell' --class shell --id 'uefi-shell' {
            chainloader /shell${uefi_machine_type_lower}.efi
        }
    fi

    menuentry "Open this computer's firmware settings" --class efi --id 'uefi-firmware' {
        fwsetup
    }
fi
'''

POWER = r'''menuentry 'Shut down' --class shutdown --class poweroff --id 'shutdown' {
    echo 'Shutting down...'
    halt
}

menuentry 'Restart' --class restart --class reboot --id 'restart' {
    echo 'Restarting...'
    reboot
}
'''

TUNE = "\n# GRUB init tune for accessibility\nplay 600 988 1 1319 4\n"


def pieces(loop):
    return {"memtest": MEMTEST, "disk": "" if loop else DISK, "uefi": UEFI, "power": POWER,
            "tune": "" if loop else TUNE}


HELP_FK = [
    "Start Field Kit",
    "  bromigOS without the desktop: a menu for repairs, the lab and tools. Nothing on",
    "  this computer changes until you choose something that changes it.",
    "Install bromigOS Server",
    "  The text installer, for a server or lab machine with no desktop. Everything it",
    "  needs is on this stick: no network. It asks before it changes a disk.",
    "Start Field Kit, then unplug the stick (runs from memory)",
    "  Reads all of Field Kit into memory first: a minute, and 4 GB of memory.",
    "Start Field Kit with remote help",
    "  SSH on, so someone you trust can help over the network. The screen shows the",
    "  address and a one-time password. It's off in every other entry.",
    "Start with basic graphics (if the screen stays black)",
    "  The firmware's simple display instead of the graphics card's driver.",
    "Test this computer's memory",
    "  Memtest86+ checks the memory for faults. It runs until you restart.",
    "More options",
    "  The system on this computer's disk, the screen reader (speech), the UEFI shell,",
    "  the firmware settings, shut down, restart.",
]
HELP_FULL = [
    "Start bromigOS (try it first)",
    "  The bromigOS desktop, running from the stick. Nothing on this computer changes.",
    "Install bromigOS",
    "  The desktop, with the installer open. It asks before it changes a disk.",
    "Install bromigOS Server",
    "  The text installer, for a server or lab machine with no desktop.",
    "Field Kit (repair, lab and tools)",
    "  bromigOS without the desktop: a menu for repairs, the lab and tools.",
    "Start with basic graphics (if the screen stays black)",
    "  The firmware's simple display instead of the graphics card's driver.",
    "More options",
    "  Install the desktop with the text installer, test this computer's memory, the",
    "  system on this computer's disk, the screen reader (speech), the UEFI shell, the",
    "  firmware settings, shut down, restart.",
]


def fieldkit(text, loop):
    p = pieces(loop)
    out = [MARK, "default=fieldkit", "timeout=10", "timeout_style=menu", "", "",
           "# Field Kit's ways to start (docs/fieldkit.md), in plain sentences; H shows what each does", ""]
    out = "\n".join(out) + "\n"
    out += linux("Start Field Kit", "fieldkit", "fieldkit", " %KERNEL_PARAMS%", loop) + "\n"
    out += install("server", "Install bromigOS Server", "install", "install-server",
                   " %KERNEL_PARAMS% bromigos.install bromigos.edition=server", loop)
    out += linux("Start Field Kit, then unplug the stick (runs from memory)", "fieldkit", "fieldkit-ram", " %KERNEL_PARAMS% copytoram=y", loop) + "\n"
    out += linux("Start Field Kit with remote help (SSH, details shown on screen)", "fieldkit", "fieldkit-remote", " %KERNEL_PARAMS% bromigos.remote=on", loop) + "\n"
    out += linux("Start with basic graphics (if the screen stays black)", "safe", "fieldkit-nomodeset", " %KERNEL_PARAMS% nomodeset", loop) + "\n"
    out += p["memtest"] + "\n"
    more = p["disk"] + "\n" + linux("Start with the screen reader (speech)", "speech", "archlinux-accessibility",
                                     " accessibility=on %KERNEL_PARAMS%", loop, hotkey="s") + "\n" + p["uefi"] + "\n" + p["power"]
    out += "# the rest, one level down\nsubmenu 'More options ›' --class options --id 'more' {\n" + indent(more) + "}\n\n"
    out += help_page(HELP_FK) + p["tune"]
    return out


def desktop(text, loop):
    p = pieces(loop)
    out = "\n".join([MARK, "default=bromigos", "timeout=10", "timeout_style=menu", "", "",
                     "# The medium's ways to start, in plain sentences; H shows what each does", ""]) + "\n"
    out += linux("Start bromigOS (try it first)", "live --class os", "bromigos", " %KERNEL_PARAMS%", loop) + "\n"
    out += "# the live desktop, straight into the installer (bromigos-iso-autostart opens it)\n"
    out += install("desktop", "Install bromigOS", "install", "bromigos-install",
                   " %KERNEL_PARAMS% bromigos.install bromigos.edition=desktop", loop)
    out += install("server", "Install bromigOS Server", "install", "bromigos-install-server",
                   " bromigos.install bromigos.edition=server systemd.unit=multi-user.target", loop)
    out += ("# Field Kit: the same medium without the desktop, for repairs, the lab and tools\n"
            "# (docs/fieldkit.md): its menu on the first console, no splash\n")
    out += linux("Field Kit (repair, lab and tools)", "fieldkit", "bromigos-fieldkit",
                 f" bromigos.fieldkit systemd.unit=multi-user.target {VT}", loop) + "\n"
    out += linux("Start with basic graphics (if the screen stays black)", "safe", "bromigos-nomodeset", " %KERNEL_PARAMS% nomodeset", loop) + "\n"
    more = (linux("Install bromigOS with the text installer", "install", "bromigos-install-text",
                  " bromigos.install=text bromigos.edition=desktop systemd.unit=multi-user.target", loop)
            + "\n" + p["memtest"] + "\n" + p["disk"] + "\n"
            + linux("Start with the screen reader (speech)", "speech", "archlinux-accessibility",
                    " accessibility=on %KERNEL_PARAMS%", loop, hotkey="s") + "\n" + p["uefi"] + "\n" + p["power"])
    out += "# the rest, one level down\nsubmenu 'More options ›' --class options --id 'more' {\n" + indent(more) + "}\n\n"
    out += help_page(HELP_FULL) + p["tune"]
    return out


# ---------------------------------------------------------------- BIOS: syslinux's vesamenu

def sl(label, title, extra, help_lines, hotkey_title=None):
    """A syslinux entry, with its help text (vesamenu shows it while the entry is highlighted)."""
    out = [f"LABEL {label}", f"MENU LABEL {hotkey_title or title}",
           "LINUX /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux", "INITRD /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img",
           f"APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID%{extra}", "TEXT HELP", *help_lines, "ENDTEXT", ""]
    return "\n".join(out) + "\n"


SL_MORE_TAIL = """LABEL existing
MENU LABEL Start the system on this computer's disk
COM32 chain.c32
APPEND hd0 0
TEXT HELP
The first hard disk's own boot menu. From a USB stick, that may be the stick:
press TAB and change hd0 to hd1.
ENDTEXT

LABEL archspeech
MENU LABEL Start with the screen reader (^speech)
LINUX /%INSTALL_DIR%/boot/%ARCH%/vmlinuz-linux
INITRD /%INSTALL_DIR%/boot/%ARCH%/initramfs-linux.img
APPEND archisobasedir=%INSTALL_DIR% archisosearchuuid=%ARCHISO_UUID% accessibility=on %KERNEL_PARAMS%
TEXT HELP
Speech for the whole system.
ENDTEXT

LABEL hdt
MENU LABEL Hardware information (HDT)
COM32 hdt.c32
APPEND modules_alias=hdt/modalias.gz pciids=hdt/pciids.gz
TEXT HELP
What's in this computer, before anything starts.
ENDTEXT

LABEL reboot
MENU LABEL Restart
COM32 reboot.c32

LABEL poweroff
MENU LABEL Shut down
COM32 poweroff.c32

LABEL back
MENU LABEL < Back
MENU EXIT
"""

SL_MEMTEST = """LABEL memtest
MENU LABEL Test this computer's memory
LINUX /boot/memtest86+/memtest
TEXT HELP
Memtest86+ checks the memory for faults. It runs until you restart.
ENDTEXT

"""


def syslinux(kind):
    head = ("# The medium's BIOS menu (syslinux's vesamenu), written by iso/grub-menus.py: the UEFI\n"
            "# menu's entries in plain sentences, a help line for the highlighted one, the rest under\n"
            "# More options. @DOT@ becomes CP437's middle dot.\n\n")
    if kind == "fieldkit":
        body = (sl("fieldkit", "Start Field Kit", " %KERNEL_PARAMS%", [
                    "bromigOS without the desktop: a menu for repairs, the lab and tools.",
                    "Nothing on this computer changes until you choose something that does."])
                + sl("install-server", "Install bromigOS Server", " %KERNEL_PARAMS% bromigos.install bromigos.edition=server", [
                    "The text installer, for a server or lab machine with no desktop.",
                    "Everything it needs is on this stick: no network."])
                + sl("fieldkit-ram", "Start Field Kit, then unplug the stick (runs from memory)", " %KERNEL_PARAMS% copytoram=y", [
                    "Reads all of Field Kit into memory first: a minute, and 4 GB of memory."])
                + sl("fieldkit-remote", "Start Field Kit with remote help (SSH)", " %KERNEL_PARAMS% bromigos.remote=on", [
                    "SSH on, so someone you trust can help. The screen shows the address",
                    "and a one-time password."])
                + sl("nomodeset", "Start with basic graphics (if the screen stays black)", " %KERNEL_PARAMS% nomodeset", [
                    "The firmware's simple display instead of the graphics card's driver."])
                + SL_MEMTEST)
        more = ""
    else:
        body = (sl("arch", "Start bromigOS (try it first)", " %KERNEL_PARAMS%", [
                    "The bromigOS desktop, running from the stick. Nothing on this computer changes."])
                + sl("bromigos-install", "Install bromigOS", " %KERNEL_PARAMS% bromigos.install bromigos.edition=desktop", [
                    "The desktop, with the installer open. It asks before it changes a disk."])
                + sl("bromigos-install-server", "Install bromigOS Server", " bromigos.install bromigos.edition=server systemd.unit=multi-user.target", [
                    "The text installer, for a server or lab machine with no desktop."])
                + sl("bromigos-fieldkit", "Field Kit (repair, lab and tools)", f" bromigos.fieldkit systemd.unit=multi-user.target {VT}", [
                    "bromigOS without the desktop: a menu for repairs, the lab and tools."])
                + sl("nomodeset", "Start with basic graphics (if the screen stays black)", " %KERNEL_PARAMS% nomodeset", [
                    "The firmware's simple display instead of the graphics card's driver."]))
        more = (sl("bromigos-install-text", "Install bromigOS with the text installer",
                   " bromigos.install=text bromigos.edition=desktop systemd.unit=multi-user.target",
                   ["The desktop, installed from a text installer instead of the graphical one."]) + SL_MEMTEST)
    tail = ("MENU BEGIN more\nMENU TITLE More options\nMENU LABEL More options >\nTEXT HELP\n"
            "The system on this computer's disk, the screen reader, hardware information, power.\nENDTEXT\n\n"
            + more + SL_MORE_TAIL + "MENU END\n")
    return head + body, "# More options (iso/grub-menus.py)\n\n" + tail


def render(path, kind, loop):
    text = open(path).read()
    head = text[:text.index(MARK)]
    return head + (fieldkit if kind == "fieldkit" else desktop)(text, loop)


def main(argv):
    stale = 0
    for prof, kind in (("fieldkit", "fieldkit"), ("profile", "desktop")):
        sys_linux, tail = syslinux(kind)
        for name, new in (("archiso_sys-linux.cfg", sys_linux), ("archiso_tail.cfg", tail)):
            path = os.path.join(HERE, prof, "syslinux", name)
            if new != (open(path).read() if os.path.exists(path) else ""):
                if "--check" in argv:
                    print(f"{path}: not what iso/grub-menus.py writes")
                    stale += 1
                else:
                    open(path, "w").write(new)
    for prof in ("fieldkit", "profile"):
        for name in ("grub.cfg", "loopback.cfg"):
            path = os.path.join(HERE, prof, "grub", name)
            new = render(path, "fieldkit" if prof == "fieldkit" else "desktop", name == "loopback.cfg")
            if new != open(path).read():
                if "--check" in argv:
                    print(f"{path}: not what iso/grub-menus.py writes")
                    stale += 1
                else:
                    open(path, "w").write(new)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
