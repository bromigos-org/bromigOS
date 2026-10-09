#!/usr/bin/env python3
"""An SMBIOS type 3 (System Enclosure) table for QEMU's `-smbios file=`, so a VM reports
the chassis type a hardware test needs (QEMU's own `-smbios type=3` can't set it):

  test/vm/smbios-chassis.py 10 notebook.bin       # 10: Notebook; 9 Laptop, 3 Desktop, 31 Convertible
  BROMIGOS_VM_QEMU="-smbios file=$PWD/notebook.bin" test/vm/arch-vm.sh up …

The 2.3 layout (21 bytes) and its strings; QEMU then leaves its own type 3 out.
"""
import struct
import sys


def table(chassis: int) -> bytes:
    strings = b"QEMU\x00bromigOS hardware test\x00\x00"
    s = struct.pack("<BBHBBBBBBBBBIBBBB",
                    3, 0x15, 0x0300,      # type, length, handle
                    1, chassis,           # manufacturer: string 1; the chassis type
                    2, 0, 0,              # version: string 2; no serial, no asset tag
                    3, 3, 3, 2,           # boot-up, power supply, thermal: safe; security: none
                    0, 0, 0, 0, 0)        # OEM, height, power cords, contained elements, their length
    assert len(s) == 0x15
    return s + strings


if __name__ == "__main__":
    if len(sys.argv) != 3 or not sys.argv[1].isdigit():
        raise SystemExit(__doc__.strip().splitlines()[3].strip())
    open(sys.argv[2], "wb").write(table(int(sys.argv[1])))
