#!/usr/bin/env bash
# shellcheck disable=SC2016,SC2329  # the VM's commands expand there; the checks' functions run through check
# The AUR in the fresh-machine VM (docs/aur.md): bromigOS's paru, the update's AUR step
# inside its snapshot pair, a failed AUR build, the rollback, the setting. Prints PASS/FAIL
# per check; exits with the number of failures. BROMIGOS_VM_DIR, BROMIGOS_VM_PORT as
# arch-vm.sh's.
#
#   test/vm/aur-e2e.sh devrepo DIR   before install.sh: DIR (a pacman repository named
#                                    bromigos-dev: a bromigos-core and a paru of yours) into
#                                    the VM (/srv/bromigos-devrepo), first in its pacman.conf
#   test/vm/aur-e2e.sh fresh         after `arch-vm.sh install` with that bromigos-core
#   test/vm/aur-e2e.sh opted-out     after an install with --no-aur or [aur] mode = "off"
#   test/vm/aur-e2e.sh own-paru      on an install from a channel whose bromigos-core has no
#                                    AUR step yet: paru built from the AUR's own recipe first
#                                    (the machine of someone who had it), then devrepo's
#                                    bromigos-core through `bromigos update`
#
# fresh: two small AUR packages at older versions, built from the AUR's git history (pfetch
# 1.10.0-1 from github.com, cbonsai 1.4.0-1 from gitlab.com), then:
# 1. bromigos update --check lists them; without a terminal or --yes the AUR is left out;
# 2. at a terminal (a pty), paru's review is offered: "Proceed to review?";
# 3. gitlab.com blocked: cbonsai can't build. The update goes on (migrations, theme,
#    restarts), names cbonsai and how to retry, exits 1; pfetch is updated inside the
#    update's own pair (post = pre + 1: snap-pac took no snapshot of paru's transactions);
#    --rollback puts pfetch back;
# 4. unblocked: both updated, recorded in updates.jsonl; --rollback puts both back;
# 5. a package built by paru with a file in Hyprland's default config: pacman's hooks
#    (bromigos-hypr-hold, -release) run for paru's transaction;
# 6. bromigos aur off removes bromigOS's paru and the update leaves the AUR alone; on puts
#    it back.
set -uo pipefail
dir=${BROMIGOS_VM_DIR:-$HOME/.cache/bromigos-vmtest}
port=${BROMIGOS_VM_PORT:-2222}
mode=${1:-}; shift || true
work=$(mktemp -d "${TMPDIR:-/tmp}/aur-e2e.XXXX")
out=$work/check.out
trap 'rm -rf "$work"' EXIT
SSH=(ssh -i "$dir/id_ed25519" -p "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR tester@127.0.0.1)
vm() { "${SSH[@]}" "$@"; }
fails=0
check() {
  local name=$1; shift
  if "$@" >"$out" 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' "$out" | tail -12; fails=$((fails + 1)); fi
}
log() { printf '== %s\n' "$*"; }
# a run's log, kept on this machine: a rollback reverts the VM's home with / (one subvolume)
save() { mkdir -p "$dir/aur-e2e"; vm "cat $1" > "$dir/aur-e2e/$1" 2>/dev/null; }

# an AUR package at an older version, built from its AUR git history as the user
old_version() {  # NAME VERSION (pkgver-pkgrel)
  vm "set -e; rm -rf aur-old/$1; mkdir -p aur-old; git clone -q https://aur.archlinux.org/$1.git aur-old/$1; cd aur-old/$1
      for c in \$(git log --format=%H -- .SRCINFO); do
        v=\$(git show \$c:.SRCINFO | awk -F' = ' '/^\tpkgver/ {p=\$2} /^\tpkgrel/ {r=\$2} END {print p\"-\"r}')
        if [ \"\$v\" = '$2' ]; then git checkout -q \$c; break; fi
      done
      grep -q 'pkgver = ${2%-*}' .SRCINFO
      makepkg -si --noconfirm --needed >/dev/null 2>&1; pacman -Q $1"
}

# the newest pre/post pair described "bromigos update": "PRE POST"
last_pair() {
  vm "snapper -c root --no-headers --csvout list --columns number,type,pre-number,description" \
    | awk -F, '$2 == "post" && $4 == "bromigos update" { p = $3 " " $1 } END { print p }'
}

case $mode in
  devrepo)
    src=${1:?devrepo DIR}
    vm "rm -rf devrepo; mkdir -p devrepo"
    scp -q -i "$dir/id_ed25519" -P "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
      -o LogLevel=ERROR "$src"/* tester@127.0.0.1:devrepo/
    # where pacman's download user (alpm) can read it
    vm "sudo rm -rf /srv/bromigos-devrepo && sudo cp -rL devrepo /srv/bromigos-devrepo && sudo chmod -R a+rX /srv/bromigos-devrepo
        grep -qx '\[bromigos-dev\]' /etc/pacman.conf || sudo sed -i '0,/^\[core\]/s||[bromigos-dev]\nSigLevel = Optional TrustAll\nServer = file:///srv/bromigos-devrepo\n\n[core]|' /etc/pacman.conf
        sudo sed -i 's|^Server = file:///home/tester/devrepo$|Server = file:///srv/bromigos-devrepo|' /etc/pacman.conf
        sudo pacman -Sy >/dev/null && pacman -Sl bromigos-dev"
    exit $? ;;

  fresh)
    log "the install's paru"
    check "paru installed, bromigOS's build from its repository" \
      vm "pacman -Qi paru | grep -E '^(Version|Packager)'; pacman -Qi paru | grep -q '^Packager *: bromigOS'"
    check "bromigos aur: on (the default), paru, bromigOS's build, installed by bromigos install" \
      vm "bromigos aur --json | python3 -c 'import json,sys; d=json.load(sys.stdin); c=d[\"check\"]; print(d[\"setting\"][\"enabled\"], c[\"found\"], d[\"installed_by_bromigos\"]); assert d[\"setting\"][\"enabled\"] and c[\"found\"][\"helper\"] == \"paru\" and c[\"found\"][\"bromigos_build\"] and d[\"installed_by_bromigos\"]'"
    check "install.log: the aur step" vm "grep -E 'aur: |pacman -S --needed --noconfirm paru' ~/.local/state/bromigos/install.log | tail -3"
    check "sudo accepts the AUR step's flags (paru's sudo loop: sudo --preserve-env=SNAP_PAC_SKIP -v)" \
      vm "SNAP_PAC_SKIP=y sudo --preserve-env=SNAP_PAC_SKIP -v && SNAP_PAC_SKIP=y sudo --preserve-env=SNAP_PAC_SKIP sh -c 'echo SNAP_PAC_SKIP=\$SNAP_PAC_SKIP' | grep -x SNAP_PAC_SKIP=y"

    log "two AUR packages, older"
    check "pfetch 1.10.0-1 from the AUR's history" old_version pfetch 1.10.0-1
    check "cbonsai 1.4.0-1 from the AUR's history" old_version cbonsai 1.4.0-1
    check "bromigos update --check lists them (paru -Qua)" \
      vm "bromigos update --check > u.log 2>&1; grep -A3 '^AUR (paru' u.log; grep -A3 '^AUR (paru' u.log | grep -q 'pfetch *1.10.0-1 -> 1.11.0-1'"
    check "--no-aur: the repositories' packages only (now nothing else waits there)" \
      vm "bromigos update --yes --no-aur > u.log 2>&1; tail -12 u.log; grep -q '== AUR: left out: --no-aur' u.log && pacman -Q pfetch | grep -q 1.10.0-1"
    check "no terminal, no --yes: the AUR is left out, said why" \
      vm "bromigos update </dev/null > u.log 2>&1; tail -12 u.log; grep -q '== AUR: left out: no terminal' u.log && pacman -Q pfetch | grep -q 1.10.0-1"

    log "at a terminal: paru's review"
    vm "cat > pty-update.py" <<'EOF'
import os, pty, re, time
# bromigos update at a terminal; a person who answers no at paru's review
pid, fd = pty.fork()
if pid == 0:
    os.environ["PARU_PAGER"] = "cat"
    os.execvp("bromigos", ["bromigos", "update"])
import select
buf = b""
deadline = time.time() + 900
while time.time() < deadline:
    if not select.select([fd], [], [], 60)[0]:
        buf += b"\n[pty-update: nothing for 60 s]\n"   # a question it didn't recognise
        os.kill(pid, 15)
        break
    try:
        b = os.read(fd, 4096)
    except OSError:
        break
    if not b:
        break
    buf += b
    tail = buf[-600:].decode("utf-8", "replace")
    tail = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)|\x1b\[[0-9;?]*[A-Za-z]", "", tail)
    if re.search(r"Proceed to review\? \[Y/n\]:? *$", tail):
        os.write(fd, b"n\n")      # decline: nothing is built
    elif re.search(r"\[Y/n\]:? *$", tail):
        os.write(fd, b"y\n")      # pacman's own questions
    elif re.search(r"\[y/N\]:? *$", tail):
        os.write(fd, b"n\n")      # paru's "Remove make dependencies after install?"
open("pty-update.log", "wb").write(buf)
_, st = os.waitpid(pid, 0)
print("exit", os.waitstatus_to_exitcode(st))
EOF
    check "at a terminal, paru offers its review (declined: nothing built, the update says so)" \
      vm "python3 pty-update.py; grep -a 'Proceed to review' pty-update.log && grep -a -A1 '== AUR: FAILED' pty-update.log && pacman -Q pfetch | grep -q 1.10.0-1"
    save pty-update.log
    check "nothing changed: the pair around it deleted (once snapperd's comparison let it)" \
      bash -c "f='$dir/aur-e2e/pty-update.log'; ! grep -a 'snapper delete exited' \$f && { ! grep -aq '== packages changed: 0' \$f || ! grep -a '== snapshot: pre [0-9]*, post' \$f; }"

    log "a build that fails: gitlab.com blocked"
    vm "echo '127.0.0.1 gitlab.com' | sudo tee -a /etc/hosts >/dev/null; rm -rf ~/.cache/paru/clone/cbonsai"
    vm "bromigos update --yes > upd-fail.log 2>&1; echo \$? > upd-fail.code"; save upd-fail.log
    pair=$(last_pair)
    check "the update exits 1, after the migrations, the theme and the restarts" \
      vm "cat upd-fail.code | grep -x 1 && grep -E '^== (migrations|theme|restarts)' upd-fail.log"
    check "it names cbonsai and how to retry" \
      vm "grep -A1 '== AUR: FAILED: not updated: cbonsai' upd-fail.log | grep -q 'retry: bromigos update again, or paru -S cbonsai'"
    check "pfetch updated, cbonsai not" vm "pacman -Q pfetch cbonsai | tee /dev/stderr | tr '\n' ' ' | grep -q 'pfetch 1.11.0-1 cbonsai 1.4.0-1'"
    check "in the update's own pair, no snap-pac pair inside it (post = pre + 1): $pair" \
      bash -c "read -r a b <<<'$pair'; [[ -n \$a && \$b == \$((a + 1)) ]]"
    check "snapper status pre..post has pfetch's files" \
      vm "read -r a b <<<'$pair'; sudo snapper -c root status \$a..\$b | grep '/usr/bin/pfetch'"
    check "recorded: pfetch in updates.jsonl" vm "tail -1 ~/.local/state/bromigos/updates.jsonl | grep -q 'pfetch 1.10.0-1 -> 1.11.0-1'"
    check "--rollback puts pfetch back" \
      vm "bromigos update --rollback --yes | tail -3; pacman -Q pfetch | grep -q 1.10.0-1"

    log "both build"
    vm "sudo sed -i '/127.0.0.1 gitlab.com/d' /etc/hosts"
    vm "bromigos update --yes > upd-ok.log 2>&1; echo \$? > upd-ok.code"; save upd-ok.log
    pair=$(last_pair)
    check "the update exits 0, the AUR step done" vm "grep -x 0 upd-ok.code && grep -E '^== AUR: [0-9]+ packages? changed' upd-ok.log"
    check "both updated" vm "pacman -Q pfetch cbonsai | tr '\n' ' ' | grep -q 'pfetch 1.11.0-1 cbonsai 1.4.2-1'"
    check "in the update's own pair (post = pre + 1): $pair" bash -c "read -r a b <<<'$pair'; [[ -n \$a && \$b == \$((a + 1)) ]]"
    check "recorded: both in updates.jsonl" vm "tail -1 ~/.local/state/bromigos/updates.jsonl | grep 'pfetch 1.10.0-1 -> 1.11.0-1' | grep -q 'cbonsai 1.4.0-1 -> 1.4.2-1'"
    check "--rollback puts both back" \
      vm "bromigos update --rollback --yes | tail -3; pacman -Q pfetch cbonsai | tr '\n' ' ' | grep -q 'pfetch 1.10.0-1 cbonsai 1.4.0-1'"

    log "pacman's hooks for paru's transactions"
    vm "rm -rf hypr-probe; mkdir hypr-probe; cat > hypr-probe/PKGBUILD" <<'EOF'
pkgname=bromigos-vmtest-hypr-probe
pkgver=1
pkgrel=1
pkgdesc='aur-e2e.sh: a file where the Hyprland hooks look'
arch=(any)
license=(MIT)
package() {
  install -Dm644 /dev/null "$pkgdir/usr/share/bromigos/default/hypr/zz-vmtest-probe.txt"
}
EOF
    check "paru -Bi of a package with a file in Hyprland's defaults: the hold and release hooks run" \
      vm "cd hypr-probe && paru -Bi . --noconfirm --skipreview > ../hypr-probe.log 2>&1; grep -E 'Hyprland' ../hypr-probe.log; grep -q 'Holding Hyprland' ../hypr-probe.log"
    save hypr-probe.log
    vm "sudo pacman -R --noconfirm bromigos-vmtest-hypr-probe >/dev/null 2>&1"

    log "off and on"
    check "bromigos aur off: bromigOS's paru removed, the setting off" \
      vm "bromigos aur off --yes && ! pacman -Q paru 2>/dev/null && grep -x 'enabled = false' ~/.config/bromigos/aur.toml"
    check "off: the update leaves the AUR alone, the check says so" \
      vm "bromigos update --check | grep -q 'AUR: left alone: the AUR is off here' && bromigos update --yes > u.log 2>&1; grep -q '== AUR: left out: the AUR is off here' u.log"
    check "bromigos aur on: paru back" vm "bromigos aur on --yes && pacman -Q paru"
    ;;

  opted-out)
    check "no paru, ever (pacman's log never installed it)" \
      vm "! pacman -Q paru 2>/dev/null && ! command -v paru && ! grep -E 'installed paru|reinstalled paru' /var/log/pacman.log"
    check "the AUR off (aur.toml written before anything was installed)" vm "grep -x 'enabled = false' ~/.config/bromigos/aur.toml"
    check "install.log: the aur step skipped" vm "grep -E 'aur: .*no AUR helper' ~/.local/state/bromigos/install.log"
    check "bromigos update: the migration done, still no paru" \
      vm "bromigos update --yes > u.log 2>&1; tail -12 u.log; grep -q '== AUR: left out: the AUR is off here' u.log && test -f ~/.local/state/bromigos/migrations/20261009235000-aur-helper && ! pacman -Q paru 2>/dev/null"
    check "bromigos update --check: left alone" vm "bromigos update --check | grep -q 'AUR: left alone: the AUR is off here'"
    ;;

  own-paru)
    src=${1:?own-paru DIR (the dev repository)}
    log "paru from the AUR's own recipe, as someone who had it"
    check "makepkg the AUR's paru (2.1.0-2)" \
      vm "set -e; sudo pacman -S --needed --noconfirm base-devel git >/dev/null; rm -rf aur-paru; git clone -q https://aur.archlinux.org/paru.git aur-paru; cd aur-paru; makepkg -si --noconfirm >/dev/null 2>&1; pacman -Qi paru | grep -E '^(Version|Packager)'"
    check "the installed bromigos-core has no AUR step yet" vm "! bromigos aur --help >/dev/null 2>&1"
    "$0" devrepo "$src" >/dev/null || { echo "FAIL devrepo"; exit 1; }
    # the installed bromigos update has no --yes for pacman yet: its questions answered here
    vm "yes | bromigos update --yes > upd-own.log 2>&1; echo \$? > upd-own.code"; save upd-own.log
    check "bromigos update (the old one, then the new core's migration): exit 0" vm "grep -x 0 upd-own.code; grep -A3 '== migrations' upd-own.log"
    check "the migration: paru is yours, nothing installed" \
      vm "grep -q 'paru 2.1.0 (yours): bromigos update updates AUR packages with it' ~/.local/state/bromigos/migrations/log"
    check "pacman left the AUR-built paru in place (same 2.1.0-2)" \
      vm "pacman -Qi paru | grep -E '^(Version|Packager)'; ! pacman -Qi paru | grep -q '^Packager *: bromigOS'"
    check "paru isn't foreign now: [bromigos] carries it, paru -Qua won't offer it" vm "! pacman -Qmq | grep -x paru"
    check "the next update's AUR step uses it (now bromigOS's bromigos update)" \
      vm "bromigos update --yes > u.log 2>&1; grep '^== AUR' u.log; grep -qE '^== AUR: (up to date|[0-9]+ packages? changed)' u.log"
    check "bromigos aur off: your paru stays" vm "bromigos aur off --yes | grep -q 'paru stays' && pacman -Q paru"
    vm "bromigos aur on --yes >/dev/null"
    ;;

  *) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
echo "$fails failed"
exit "$fails"
