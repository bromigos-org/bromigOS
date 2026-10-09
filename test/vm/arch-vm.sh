#!/usr/bin/env bash
# The fresh-machine test (docs/install.md): a new Arch VM, install.sh, then checks.
#
#   test/vm/arch-vm.sh up      --repo URL [--ca FILE] [--hosts "IP NAME"] [--heads N] [--dir DIR]
#   test/vm/arch-vm.sh install [--source FILE] [--channel NAME]   run install.sh in it (unattended,
#       answers.toml; --channel: stable by default, as install.sh's)
#       BROMIGOS_VM_WITH="bromigos-apps …" in the environment installs optional packages too
#   test/vm/arch-vm.sh check                     the checks; screenshots to DIR/shots/
#   test/vm/arch-vm.sh ssh [cmd…] | shot NAME [HEAD] | reboot | down | destroy
#   (up again after down keeps the disk: --heads 2 boots the same install with two outputs)
#
# The VM: the official Arch cloud image (checksum-verified), a 40 GB overlay disk, KVM,
# 6 GB and 4 CPUs, virtio-gpu (no 3D: Mesa's software renderer), headless (-display none;
# screenshots through QEMU's monitor, never a window on the host), user networking with
# SSH on localhost:2222. cloud-init makes the user `tester` (sudo without a password, as an
# installer's user would have it) with a key generated here. Everything lives in DIR
# (default ~/.cache/bromigos-vmtest: disk, not tmpfs); `destroy` removes the VM's disk.
# A second VM beside it: BROMIGOS_VM_PORT (SSH, 2222), BROMIGOS_VM_VNC (display, 47),
# BROMIGOS_VM_MEM (MiB, 6144); BROMIGOS_VM_QEMU adds QEMU arguments (the hardware test's
# faked laptop: -smbios file=… with a chassis table; docs/hardware.md).
# The VM stops when the session that started it ends: a closed terminal, a killed script
# (test/vm/vm-keeper.py). BROMIGOS_VM_OWNER=PID ties it to another process, and
# BROMIGOS_VM_OWNER=none keeps it running until `down`.
set -euo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
root=$(cd "$here/../.." && pwd)
dir=${BROMIGOS_VM_DIR:-$HOME/.cache/bromigos-vmtest}
img=Arch-Linux-x86_64-cloudimg.qcow2
url=https://geo.mirror.pkgbuild.com/images/latest
port=${BROMIGOS_VM_PORT:-2222}

cmd=${1:-}; shift || true
repo='' ca='' hosts='' heads=1 source="$root/install.sh" channel=stable
while (($#)); do
  case $1 in
    --repo) repo=$2; shift 2 ;; --ca) ca=$2; shift 2 ;; --hosts) hosts=$2; shift 2 ;;
    --dir) dir=$2; shift 2 ;; --source) source=$2; shift 2 ;; --heads) heads=$2; shift 2 ;;
    --channel) channel=$2; shift 2 ;; *) break ;;
  esac
done
mkdir -p "$dir/shots"
key=$dir/id_ed25519
SSH=(ssh -i "$key" -p "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=5 tester@127.0.0.1)
SCP=(scp -i "$key" -P "$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)
qmp() { printf '%s\n' '{"execute":"qmp_capabilities"}' "$1" | socat - "UNIX-CONNECT:$dir/qmp.sock" >/dev/null; }

wait_ssh() {
  for _ in $(seq 1 120); do "${SSH[@]}" true 2>/dev/null && return 0; sleep 5; done
  echo "arch-vm: no SSH after 10 minutes (console: $dir/console.log)" >&2; return 1
}

case $cmd in
  up)
    [[ -n $repo || -f $dir/repo.url ]] || { echo "arch-vm: up needs --repo URL" >&2; exit 2; }
    [[ -n $repo ]] || repo=$(cat "$dir/repo.url"); [[ -n $hosts ]] || hosts=$(cat "$dir/hosts.entry" 2>/dev/null || true)
    cd "$dir"
    if [[ ! -f $img ]]; then
      curl -fsSL -o "$img.SHA256" "$url/$img.SHA256"
      curl -fsSL -o "$img" "$url/$img"
    fi
    sha256sum -c "$img.SHA256"
    [[ -f $key ]] || ssh-keygen -q -t ed25519 -N '' -f "$key"
    [[ -f vm.qcow2 ]] || qemu-img create -q -f qcow2 -b "$img" -F qcow2 vm.qcow2 40G
    printf '%s\n' "$repo" > repo.url
    if [[ -n $ca ]]; then install -m 0644 "$ca" ca.crt; fi
    { echo "instance-id: bromigos-vmtest"; echo "local-hostname: bromigos-vm"; } > meta-data
    {
      echo "#cloud-config"
      echo "users:"
      echo "  - name: tester"
      echo "    sudo: ALL=(ALL) NOPASSWD:ALL"
      echo "    shell: /bin/bash"
      echo "    lock_passwd: false"
      echo "    plain_text_passwd: tester"
      echo "    ssh_authorized_keys: [\"$(cat "$key.pub")\"]"
    } > user-data
    rm -f seed.iso
    xorriso -as mkisofs -quiet -o seed.iso -V cidata -J -r user-data meta-data
    # more outputs: one GPU each (a virtio-gpu device's first head is connected by itself;
    # QEMU leaves its other heads disconnected without a display client on them)
    gpus=(-device "virtio-vga,id=video0")
    for ((h = 1; h < heads; h++)); do gpus+=(-device "virtio-gpu-pci,id=video$h"); done
    # through vm-keeper.py: QEMU stops when whoever started the test is gone
    # (BROMIGOS_VM_OWNER=none keeps it until down)
    # shellcheck disable=SC2086  # BROMIGOS_VM_QEMU is words
    "$here/vm-keeper.py" --ready "$dir/qmp.sock" --log "$dir/keeper.log" -- \
    qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -m "${BROMIGOS_VM_MEM:-6144}" -smp 4 ${BROMIGOS_VM_QEMU:-} \
      -drive file=vm.qcow2,if=virtio -drive file=seed.iso,media=cdrom \
      -nic user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:$port-:22 \
      "${gpus[@]}" -display none -vnc "127.0.0.1:${BROMIGOS_VM_VNC:-47}" \
      -qmp "unix:$dir/qmp.sock,server,nowait" -serial "file:$dir/console.log" \
      -pidfile "$dir/qemu.pid"
    wait_ssh
    printf '%s\n' "$hosts" > hosts.entry
    if [[ -n $hosts ]]; then      # the repository's name, when the host's DNS doesn't reach the VM
      "${SSH[@]}" "grep -qxF '$hosts' /etc/hosts || echo '$hosts' | sudo tee -a /etc/hosts >/dev/null"
    fi
    echo "arch-vm: up (ssh: $0 ssh)"
    ;;
  install)
    [[ -f "$dir/repo.url" ]] || { echo "arch-vm: run up first" >&2; exit 2; }
    "${SCP[@]}" "$source" "$here/answers.toml" tester@127.0.0.1:
    [[ -f "$dir/ca.crt" ]] && "${SCP[@]}" "$dir/ca.crt" tester@127.0.0.1:homelab-ca.crt
    ca_arg=(); [[ -f "$dir/ca.crt" ]] && ca_arg=(--ca homelab-ca.crt)
    # BROMIGOS_VM_WITH="bromigos-apps bromigos-homelab": optional packages too (bromigos install --with)
    with_args=(); for p in ${BROMIGOS_VM_WITH:-}; do with_args+=(--with "$p"); done
    "${SSH[@]}" "sudo pacman -Syu --noconfirm --needed >/dev/null 2>&1; bash install.sh --repo '$(cat "$dir/repo.url")' --channel $channel ${ca_arg[*]} --yes --answers answers.toml${with_args:+ -- ${with_args[*]}}" 2>&1 | tee "$dir/install.out"
    ;;
  check) "${SCP[@]}" "$here/checks.sh" tester@127.0.0.1: && "${SSH[@]}" bash checks.sh 2>&1 | tee "$dir/checks.out" ;;
  ssh) "${SSH[@]}" "$@" ;;
  shot)
    name=${1:-screen} head=${2:-}        # head: which output (its GPU: video<N>; none: the first)
    target=''; [[ -n $head ]] && target=",\"device\":\"video$head\""
    qmp "{\"execute\":\"screendump\",\"arguments\":{\"filename\":\"$dir/shots/$name.ppm\"$target}}"
    sleep 1
    if command -v magick >/dev/null; then magick "$dir/shots/$name.ppm" "$dir/shots/$name.png" && rm -f "$dir/shots/$name.ppm"; fi
    ls "$dir/shots/$name".*
    ;;
  reboot) "${SSH[@]}" "sudo systemctl reboot" || true; sleep 15; wait_ssh ;;
  down) [[ -f "$dir/qemu.pid" ]] && kill "$(cat "$dir/qemu.pid")" 2>/dev/null; rm -f "$dir/qemu.pid" ;;
  destroy) "$0" down --dir "$dir" || true; rm -f "$dir/vm.qcow2" "$dir/seed.iso" ;;
  *) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
