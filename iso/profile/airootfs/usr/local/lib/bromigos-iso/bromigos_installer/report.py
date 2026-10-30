#!/usr/bin/env python3
"""A problem report on a USB drive (common.save_report), as root (it mounts the drive):

  report.py [--answers FILE]     prints the report's path (or nothing) and, on the last
                                 line, where it went in plain words
"""
import json
import os
import sys


def _read(path):
    with open(path) as f:
        return f.read()

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    from bromigos_installer import common
else:
    from . import common


def main(argv):
    a = None
    if "--answers" in argv:
        a = json.loads(_read(argv[argv.index("--answers") + 1]))
    path, words = common.save_report(a)
    print(path or "")
    print(words)
    return 0 if path else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
