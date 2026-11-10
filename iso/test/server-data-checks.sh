#!/usr/bin/env bash
# Where an installed bromigOS Server keeps its apps' data (docs/server.md, "Where the apps
# keep their data"), checked in the installed system as the test user, with sudo. PASS/FAIL
# per check; exits with the number of failures.
#
#   server-data-checks.sh [key=value…]
#     disks=N raid1=1    the server was installed with N data disks (two copies): /srv/apps must be
#                        on their filesystem. Without disks=: on the system disk
#     app=ID             the lab's engine installs that app from the catalogue (it needs the
#                        internet), and the app's own folder must be on the same filesystem
#
# Every check compares the filesystems' own IDs (findmnt -o UUID), never a path's name: btrfs
# gives every subvolume, and every disk of a RAID1, the same ID. iso/fieldkit/ci-test.sh runs
# this on a Server installed from the stick with two data disks.
declare -A want=()
for kv in "$@"; do want[${kv%%=*}]=${kv#*=}; done
fails=0
check() { local name=$1; shift; if "$@" >/tmp/check.out 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' /tmp/check.out | tail -8; fails=$((fails + 1)); fi; }

if [[ -n ${want[disks]:-} ]]; then
    check "the data disks are btrfs at /srv/data, ${want[disks]} of them" bash -c "
        findmnt -no FSTYPE /srv/data | grep -qx btrfs && [[ \$(sudo btrfs filesystem show /srv/data | grep -c 'devid') == ${want[disks]} ]]"
    if (( ${want[raid1]:-0} )); then
        check "they keep two copies (RAID1)" bash -c "sudo btrfs filesystem df /srv/data | grep -q 'Data, RAID1'"
    fi
    check "app data is on the data disks: /srv/apps is their apps subvolume (/srv/data's filesystem, not the system disk's)" bash -c '
        a=$(findmnt -no UUID -T /srv/apps) d=$(findmnt -no UUID /srv/data) r=$(findmnt -no UUID /)
        echo "/srv/apps is on ${a:-nothing}; /srv/data is ${d:-not mounted}; the system disk is $r"
        [[ -n $a && $a == "$d" && $a != "$r" && $(findmnt -no FSROOT /srv/apps) == /apps ]]'
    # for the run's log, not a check: what's mounted under /srv, the pool's subvolumes, snapper's configurations
    { echo "--- /srv, the data disks' subvolumes, snapper's configurations:"; findmnt -R -no TARGET,SOURCE,FSTYPE,UUID /srv
      sudo btrfs subvolume list /srv/data; sudo snapper --no-dbus list-configs; grep -v '^#' /etc/fstab | grep srv; } 2>&1 | sed 's/^/     /'
else
    check "app data is on the system disk (no data disks)" bash -c '[[ -d /srv/apps && $(findmnt -no UUID -T /srv/apps) == "$(findmnt -no UUID /)" ]]'
fi
if [[ -n ${want[app]:-} ]]; then
    app=${want[app]}
    check "the lab's engine installs $app (bromigos lab provision --local)" bash -c "
        nm-online -q -t 90 || true
        sudo bromigos lab provision --local --select $app --apply --no-wait 2>&1 | tail -20; exit \${PIPESTATUS[0]}"
    if [[ -n ${want[disks]:-} ]]; then
        check "$app's data is on the data disks (its folder is on /srv/data's filesystem, and the pool's apps subvolume has it)" bash -c "
            a=\$(sudo findmnt -no UUID -T /srv/apps/$app) d=\$(findmnt -no UUID /srv/data) r=\$(findmnt -no UUID /)
            echo \"/srv/apps/$app is on \${a:-nothing}; /srv/data is \${d:-not mounted}; the system disk is \$r\"
            [[ -n \$a && \$a == \"\$d\" && \$a != \"\$r\" ]] && sudo test -d /srv/data/apps/$app"
    else
        check "$app's data is on the system disk (no data disks)" bash -c "[[ \$(sudo findmnt -no UUID -T /srv/apps/$app) == \"\$(findmnt -no UUID /)\" ]]"
    fi
fi
echo "server data checks: $fails failed"
exit $fails
