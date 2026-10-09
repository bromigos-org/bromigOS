#!/bin/bash
# `bromigos lab`'s dashboard in the README's pictures: the real app (homelab/lib
# bromigos_homelab.tui) on the recorded lab the tests use (homelab/tests: labfake.py, a
# scrubbed recording), its clock fixed. Run by the picture's kitty; $PV_READY once drawn.
here=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
root=${BROMIGOS_SRC:-$(cd "$here/../.." && pwd)}
(sleep 5; touch "$PV_READY") &
cd "$HOME" || exit 1
PYTHONPATH="$root/homelab/tests:$root/homelab/lib:$root/lib" TZ=UTC exec python3 "$here/lab_tui.py"
