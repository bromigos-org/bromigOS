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
#     move=1             with disks= and app=: then the server is put back as the installer left
#                        one before November 2026 (the app's data on the system disk, the pool's
#                        apps subvolume empty, no /srv/apps line in fstab), and
#                        bromigos lab app-data move must put the data on the data disks
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
    check "bromigos lab app-data says so" bash -c "bromigos lab app-data status --json | tee /dev/stderr | python3 -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if (d[\"state\"], d[\"where\"]) == (\"ok\", \"pool\") else 1)'"
    # the data disks away: the folder behind the mount is the system disk's, and must take nothing
    check "with the data disks' apps subvolume unmounted, /srv/apps takes no files" bash -c '
        sudo umount /srv/apps || exit 1
        sudo mkdir /srv/apps/on-the-system-disk 2>/dev/null; made=$?
        sudo rmdir /srv/apps/on-the-system-disk 2>/dev/null
        sudo mount /srv/apps || exit 1
        [[ $made -ne 0 ]]'
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
if [[ -n ${want[app]:-} && -n ${want[disks]:-} ]] && (( ${want[move]:-0} )); then
    # A server set up before the installer mounted the data disks' apps subvolume at /srv/apps:
    # that subvolume empty, /srv/apps a folder on the system disk with the app's data in it, the
    # app running on it. Made here from the server above, then moved as a person would
    app=${want[app]}
    units=$(grep -l "/srv/apps" /etc/containers/systemd/*.container | xargs -rn1 basename | sed 's/\.container$/.service/' | tr '\n' ' ')
    check "put back as the old installer left it: $app's data on the system disk, the pool's apps subvolume empty" bash -c "
        set -e
        echo 'a file the app had before the move' | sudo tee /srv/apps/$app/isotest-marker >/dev/null
        sudo systemctl stop $units
        sudo umount /srv/apps
        sudo sed -i -e '\\|[[:space:]]/srv/apps[[:space:]]|d' -e '/^# the apps. data, on the data disks/d' /etc/fstab
        sudo systemctl daemon-reload
        sudo chattr -i /srv/apps
        sudo cp -a /srv/data/apps/. /srv/apps/
        sudo find /srv/data/apps -mindepth 1 -delete
        sudo systemctl start $units
        [[ \$(sudo findmnt -no UUID -T /srv/apps/$app) == \"\$(findmnt -no UUID /)\" ]]
        ! grep -q '[[:space:]]/srv/apps[[:space:]]' /etc/fstab"
    check "bromigos lab app-data says the apps' data is on the system disk, not the data disks" bash -c "
        set -e
        bromigos lab app-data | tee /dev/stderr | grep -q 'sudo bromigos lab app-data move'
        bromigos lab app-data status --json | python3 -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if d[\"state\"] == \"not-on-pool\" and d[\"has_data\"] else 1)'"
    check "the dry run says what the move would do, and changes nothing" bash -c "
        set -e
        sudo bromigos lab app-data move --dry-run | tee /dev/stderr | grep -q 'Nothing was changed'
        systemctl is-active -q ${units%% *} && ! grep -q '[[:space:]]/srv/apps[[:space:]]' /etc/fstab && [[ -z \$(sudo ls -A /srv/data/apps) ]]"
    check "bromigos lab app-data move: the apps stopped, copied, compared, the old copy kept, the apps started" bash -c "sudo bromigos lab app-data move 2>&1 | tail -12; exit \${PIPESTATUS[0]}"
    check "$app's data is on the data disks now, with the file it had (filesystem IDs; the pool's apps subvolume has it)" bash -c "
        a=\$(sudo findmnt -no UUID -T /srv/apps/$app) d=\$(findmnt -no UUID /srv/data) r=\$(findmnt -no UUID /)
        echo \"/srv/apps/$app is on \${a:-nothing}; /srv/data is \${d:-not mounted}; the system disk is \$r\"
        [[ -n \$a && \$a == \"\$d\" && \$a != \"\$r\" ]] && sudo grep -qx 'a file the app had before the move' /srv/apps/$app/isotest-marker /srv/data/apps/$app/isotest-marker"
    check "the old copy is kept whole on the system disk, by name" bash -c "
        old=\$(ls -d /srv/apps.on-system-disk-* | head -1)
        [[ -n \$old && \$(sudo findmnt -no UUID -T \$old/$app) == \"\$(findmnt -no UUID /)\" ]] && sudo grep -qx 'a file the app had before the move' \$old/$app/isotest-marker"
    check "one line in fstab mounts it at every start, and the apps are running again" bash -c "
        grep '[[:space:]]/srv/apps[[:space:]]' /etc/fstab
        [[ \$(grep -c '[[:space:]]/srv/apps[[:space:]]' /etc/fstab) == 1 ]] || exit 1
        for u in $units; do for _ in \$(seq 30); do systemctl is-active -q \$u && break; sleep 2; done; systemctl is-active \$u || exit 1; done"
    check "bromigos lab app-data says it's on the data disks, and names the old copy" bash -c "bromigos lab app-data | tee /dev/stderr | grep -q 'app-data remove-old'"
    check "remove-old deletes the old copy, and only that" bash -c "
        sudo bromigos lab app-data remove-old && ! ls -d /srv/apps.on-system-disk-* 2>/dev/null && sudo test -s /srv/apps/$app/isotest-marker"
fi
echo "server data checks: $fails failed"
exit $fails
