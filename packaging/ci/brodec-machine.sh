#!/usr/bin/env bash
# BRODEC's machine agent on its own (brodec-machine: GTK-free, for Field Kit and bromigOS Server)
# for [bromigos]: packaging/README.md, "BRODEC's desktop app" and "BRODEC's machine agent".
# BRODEC's CI stages it, unsigned, as the only file of the commit at refs/brodec-machine/package;
# this is brodec-desktop.sh with the same checks, for a brodec-machine package:
#
#   brodec-machine.sh staged         the staged file's name and source commit (nothing: none)
#   brodec-machine.sh missing FILE   the channels whose public database doesn't list FILE
#   brodec-machine.sh fetch DIR      fetch the staged package into DIR, after every check
#
# (BRODEC's docs/MACHINE_JOBS.md, "What a machine needs": BRODEC splits the package and stages
# brodec-machine first; then this publishes it; then brodec-desktop depends on it; then the Field
# Kit stick and bromigos-server take it. Each step leaves every machine installable.)
set -euo pipefail
case ${1:-} in staged|missing|fetch) ;; *) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 2 ;; esac
BRODEC_PACKAGE=brodec-machine exec "$(dirname "${BASH_SOURCE[0]}")/brodec-desktop.sh" "$@"
