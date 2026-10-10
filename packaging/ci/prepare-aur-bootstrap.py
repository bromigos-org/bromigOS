#!/usr/bin/env python3
"""Pin AUR bootstrap recipes to an immutable packaging tag and the repo versions."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

root = Path(__file__).resolve().parents[2]
tag = sys.argv[1]
if not re.fullmatch(r'aur-bootstrap-[0-9a-f]{12,40}|v[0-9]+\.[0-9]+\.[0-9]+', tag):
    raise SystemExit('Use an immutable packaging or release tag')
url = f'https://github.com/bromigos-org/bromigOS/archive/refs/tags/{tag}.tar.gz'
for attempt in range(4):
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            checksum = hashlib.sha256(response.read()).hexdigest()
        break
    except OSError:
        if attempt == 3:
            raise
        time.sleep(2)
for name in ('bromigos-keyring', 'bromigos-mirrorlist'):
    recipe = root / 'packaging' / name / 'PKGBUILD'
    version, release = subprocess.check_output(
        ['bash', '-ec', 'source "$startdir/PKGBUILD"; if declare -F pkgver >/dev/null; then aur_version=$(pkgver); else aur_version=$pkgver; fi; printf "%s\n%s\n" "$aur_version" "$pkgrel"'],
        env=dict(os.environ, startdir=str(recipe.parent)), text=True).strip().splitlines()
    target = root / 'packaging/aur' / name
    path = target / 'PKGBUILD'
    text = path.read_text()
    text = re.sub(r'^pkgver=.*$', f'pkgver={version}', text, flags=re.M)
    text = re.sub(r'^pkgrel=.*$', f'pkgrel={release}', text, flags=re.M)
    text = re.sub(r'^_tag=.*$', f'_tag={tag}', text, flags=re.M)
    sums = [checksum]
    if name == 'bromigos-mirrorlist':
        asset = (recipe.parent / name).read_bytes()
        (target / name).write_bytes(asset)
        sums.append(hashlib.sha256(asset).hexdigest())
    else:
        (target / f'{name}.install').write_bytes((recipe.parent / f'{name}.install').read_bytes())
    text = re.sub(r'^sha256sums=.*$', 'sha256sums=(' + ' '.join(f"'{s}'" for s in sums) + ')', text, flags=re.M)
    path.write_text(text)
    print(f'{name}: pinned {tag}, version {version}')
