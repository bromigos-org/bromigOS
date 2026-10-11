#!/usr/bin/env python3
"""Render a pinned, checksummed lab release recipe; local archives are for tests only."""
import argparse
import hashlib
from pathlib import Path
import re
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]

def render(tag, data):
    match = re.fullmatch(r"(?:bromigos-lab-)?v(\d+\.\d+\.\d+)", tag)
    if not match:
        raise ValueError("Use a stable bromigOS or bromigos-lab release tag")
    text = (ROOT / 'packaging/aur/bromigos-lab/PKGBUILD.in').read_text()
    for marker, value in {'@TAG@': tag, '@VERSION@': match[1], '@SHA256@': hashlib.sha256(data).hexdigest()}.items():
        text = text.replace(marker, value)
    return text

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tag')
    p.add_argument('--archive', type=Path, help='test only: an already downloaded source archive')
    p.add_argument('--output', type=Path, default=ROOT / 'packaging/aur/bromigos-lab')
    a = p.parse_args()
    # Validate before a URL or a file is opened.
    render(a.tag, b'')
    if a.archive:
        data = a.archive.read_bytes()
    else:
        url = 'https://github.com/bromigos-org/bromigOS/archive/refs/tags/' + a.tag + '.tar.gz'
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as response: data = response.read()
                break
            except OSError:
                if attempt == 3: raise
                time.sleep(2)
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'PKGBUILD').write_text(render(a.tag, data))
    print('bromigos-lab: pinned ' + a.tag + ', SHA-256 ' + hashlib.sha256(data).hexdigest())

if __name__ == '__main__': main()
