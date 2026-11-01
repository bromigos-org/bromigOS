#!/usr/bin/env bash
# bromigOS Server's own checks, in the installed system after iso/test.sh boot-disk (as the
# test user, with sudo): what the installer's server steps set up (docs/server.md). PASS/FAIL
# per check; exits with the number of failures.
#
#   server-checks.sh ROLE [key=value…]
#     method=static address=A iface=IF   the fixed address on that port
#     raid1=1 disks=2                     /srv/data is btrfs RAID1 over that many disks
#     window=03:00-05:00 mode=auto        the update window and mode in server.toml and the timer
#     docker=0|1 lab=0|1 shares=1         Docker's engine, the lab account, the shares
#     online=1                            the packages the medium lacked came from the network
role=${1:?ROLE}; shift
declare -A want=([window]=03:00-05:00 [mode]=auto [docker]=0 [lab]=0 [online]=1)
for kv in "$@"; do want[${kv%%=*}]=${kv#*=}; done
fails=0
check() { local name=$1; shift; if "$@" >/tmp/check.out 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' /tmp/check.out | tail -6; fails=$((fails + 1)); fi; }

declare -A pkgrole=([lab]=lab-node [storage]=storage [home]=home-services [games]=game-server [plain]=just-a-server)
check "server.toml names the role ($role, bromigos-server's ${pkgrole[$role]})" bash -c "sudo python3 -c 'import tomllib; d = tomllib.load(open(\"/etc/bromigos/server.toml\", \"rb\"))[\"roles\"]; print(d[\"picked\"], d[\"enabled\"])' | grep -q \"'$role'.*'${pkgrole[$role]}\""
check "the update window in server.toml (${want[window]})" bash -c "[[ \$(sudo python3 -c 'import tomllib; print(tomllib.load(open(\"/etc/bromigos/server.toml\", \"rb\"))[\"updates\"][\"window\"])') == ${want[window]} ]]"
check "the update mode in server.toml (${want[mode]})" bash -c "[[ \$(sudo python3 -c 'import tomllib; print(tomllib.load(open(\"/etc/bromigos/server.toml\", \"rb\"))[\"updates\"][\"mode\"])') == ${want[mode]} ]]"
check "the update timer starts in the window" bash -c "grep -h '^OnCalendar=\\*-\\*-\\* ${want[window]%%-*}:00' /etc/systemd/system/bromigos-*update.timer.d/10-window.conf"
if [[ ${want[mode]} == off ]]; then
    check "no automatic update timer enabled (mode off)" bash -c "! systemctl is-enabled -q bromigos-server-update.timer 2>/dev/null && ! systemctl is-enabled -q bromigos-auto-update.timer 2>/dev/null"
fi
if (( ${want[online]} )); then
    check "running the LTS kernel (linux-lts first in the boot menu)" bash -c "uname -r | grep -q lts"
    check "linux, the spare kernel, is in the boot menu" bash -c "sudo grep -q \"vmlinuz-linux'\\|vmlinuz-linux \" /boot/grub/grub.cfg"
    check "nothing left waiting for a network" test ! -e /etc/bromigos/server/pending-packages
    check "sshguard is on" systemctl is-active -q sshguard
    check "AppArmor is on" bash -c "grep -q apparmor /sys/kernel/security/lsm && systemctl is-enabled -q apparmor"
    check "WireGuard and Tailscale installed, both off" bash -c "command -v wg && command -v tailscale && ! systemctl is-enabled -q tailscaled"
    check "the mDNS announcement (Find my lab)" bash -c "systemctl is-active -q avahi-daemon && grep -q _bromigos-lab._tcp /etc/avahi/services/bromigos-server.service"
fi
check "smartd watches the disks" systemctl is-enabled -q smartd
check "the monthly btrfs scrub of /" systemctl is-enabled -q btrfs-scrub@-.timer
check "journald keeps logs, within 1G" bash -c "grep -q SystemMaxUse=1G /etc/systemd/journald.conf.d/90-bromigos-server.conf"
check "the hardening sysctls (kptr_restrict 2)" bash -c "[[ \$(sysctl -n kernel.kptr_restrict) == 2 ]]"
check "SSH: keys only" bash -c "sudo sshd -T | grep -qix 'passwordauthentication no'"
check "SSH: three tries, wheel and bromigos-ssh only" bash -c "sudo sshd -T | grep -qix 'maxauthtries 3' && sudo sshd -T | grep -qix 'allowgroups wheel' && sudo sshd -T | grep -qix 'allowgroups bromigos-ssh'"
check "root can't sign in (locked)" bash -c "sudo passwd -S root | awk '{print \$2}' | grep -qx L"
check "the firewall: its own table, SSH open" bash -c "sudo nft list table inet bromigos-server | grep -q 'dport 22'"
check "the role's health checks are there and pass" bash -c "ls /etc/bromigos/server/health.d/*.sh && for f in /etc/bromigos/server/health.d/*.sh; do sudo sh \"\$f\" || { echo \"\$f failed\"; exit 1; }; done"
check "the network profile (NetworkManager)" bash -c "sudo ls /etc/NetworkManager/system-connections/ | grep -q bromigos"
if [[ ${want[method]:-dhcp} == static ]]; then
    check "the fixed address ${want[address]} on ${want[iface]}" bash -c "ip -4 -brief addr show ${want[iface]} | grep -qw ${want[address]}/[0-9]*"
    check "Wake-on-LAN on that port (magic packet)" bash -c "nmcli -g 802-3-ethernet.wake-on-lan connection show bromigos-server | grep -q magic"
fi
if (( ${want[lab]} )); then
    check "the lab account: its key, passwordless sudo" bash -c "id lab && sudo test -s /home/lab/.ssh/authorized_keys && sudo -l -U lab | grep -q NOPASSWD"
    check "the cluster's ports open to the LAN (lab-cluster)" bash -c "sudo nft list table inet bromigos-server | grep -q lab-cluster"
    check "the cluster's sysctls (inotify watches)" bash -c "[[ \$(sysctl -n fs.inotify.max_user_watches) == 524288 ]]"
else
    check "no lab account (not a Lab node)" bash -c "! id lab"
fi
if [[ -n ${want[disks]:-} ]]; then
    check "/srv/data is btrfs" bash -c "findmnt -no FSTYPE /srv/data | grep -qx btrfs"
    check "/srv/data spans ${want[disks]} disks" bash -c "[[ \$(sudo btrfs filesystem show /srv/data | grep -c 'devid') == ${want[disks]} ]]"
    if (( ${want[raid1]:-0} )); then
        check "/srv/data keeps two copies (RAID1)" bash -c "sudo btrfs filesystem df /srv/data | grep -q 'Data, RAID1'"
    fi
    check "the data's monthly scrub" systemctl is-enabled -q btrfs-scrub@srv-data.timer
fi
if (( ${want[shares]:-0} )); then
    check "SMB shares on" systemctl is-active -q smb
    check "NFS export on" bash -c "systemctl is-active -q nfs-server && sudo exportfs -v | grep -q /srv/data/shares"
    check "hourly snapshots of /srv/data" bash -c "sudo snapper --no-dbus list-configs | grep -q '^data '"
fi
if (( ${want[docker]} )); then
    check "Docker's engine (Arch's docker), for Wings" bash -c "pacman -Qq | grep -qx docker && systemctl is-active -q docker"
    check "no podman-docker beside it" bash -c "! pacman -Q podman-docker"
else
    check "no Docker engine (Podman only)" bash -c "! pacman -Qq | grep -qx docker"
    check "Podman" command -v podman
fi
echo "server checks: $fails failed"
exit $fails
