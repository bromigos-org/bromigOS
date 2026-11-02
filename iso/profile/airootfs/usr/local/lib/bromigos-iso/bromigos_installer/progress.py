#!/usr/bin/env python3
"""archinstall's output, read for the installers' progress bar (bromigos-iso-install pipes
it through here): every line goes on unchanged, and a `::stage PERCENT plain words` line
is added when it reaches a step. Partitions and encryption are 11-15 %, the packages
15-74 % (pacman's "(n/N) installing" lines, counted across its runs: the base system, the
boot loader's, then the rest). An install that copies the live system (archinstall_copy.py's
"Copying the live system: N%" lines) has the copy at 15-65 % and the store's packages after it
at 65-74 %. The boot loader comes between two of pacman's runs, so it changes the words, not
the bar (None below)."""
import re
import sys

STEPS = [   # (archinstall's own line, at its start, percent, plain words); package scriptlets
            # print things like "Creating user 'bin'", so nothing here matches mid-line
    (re.compile(r"^Creating partitions"), 12, "Making bromigOS's partitions"),
    (re.compile(r"^luks2 formatting"), 13, "Encrypting the disk"),
    (re.compile(r"^Formatting "), 13, "Formatting the new partitions"),
    (re.compile(r"^Creating subvolumes"), 14, "Laying out the file system"),
    (re.compile(r"^Installing packages:"), 15, "Copying bromigOS onto the disk"),
    (re.compile(r"^Adding bootloader"), None, "Installing the boot menu"),
    (re.compile(r"^Generating grub configuration file"), None, "Writing the boot menu"),
]
PKG = re.compile(r"\(\s*(\d+)/(\d+)\)\s+installing\s+(\S+)", re.I)
COPY = re.compile(r"^Copying the live system: (\d+)%")
ESTIMATE = 800
COPY_ESTIMATE = 60          # the store's packages after a copy (the NVIDIA driver, the headers, …)


def main(inp=sys.stdin, out=sys.stdout):
    base, cur_n, cur_total, last = 0, 0, 0, 0
    copied = False

    def stage(pct, words):
        nonlocal last
        if pct >= last:
            last = pct
            out.write(f"::stage {pct} {words}\n")

    for line in inp:
        out.write(line)
        c = COPY.match(line)
        if c:
            copied = True
            stage(15 + 50 * min(100, int(c.group(1))) // 100, f"Copying bromigOS onto the disk ({c.group(1)}%)")
            out.flush()
            continue
        m = PKG.search(line)
        if m:
            n, total = int(m.group(1)), int(m.group(2))
            if n < cur_n or (total != cur_total and cur_n):   # another pacman run
                base += cur_total
            cur_n, cur_total = n, total
            done = base + n
            if copied:
                whole = max(COPY_ESTIMATE, base + total)
                stage(65 + 9 * done // whole, f"Adding what the live system doesn't have ({done} of {whole})")
            else:
                whole = max(ESTIMATE, base + total)
                stage(15 + 59 * done // whole, f"Copying bromigOS onto the disk ({done} of {whole})")
        else:
            for rx, pct, words in STEPS:
                if rx.match(line):
                    stage(last if pct is None else pct, words)
                    break
        out.flush()


if __name__ == "__main__":
    sys.stdin.reconfigure(errors="replace")         # pacman's bars and escapes: never a reason to stop
    sys.stdout.reconfigure(errors="replace")
    main()
