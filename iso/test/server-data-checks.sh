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
#     passwords=1        the lab's engine installs passwords (Vaultwarden, a package from the
#                        internet): the real service must run with its vault in /srv/apps/passwords
#     dbapp=ID dbfile=PATH
#                        the lab's engine installs that app too, one that keeps a SQLite database at
#                        /srv/apps/ID/PATH: the real app must make it, the engine must write its
#                        backup hook, and with disks= and app= the nightly backup must hold a copy
#                        of it that opens
#     move=1             with disks= and app=: then the server is put back as the installer left
#                        one before November 2026 (the app's data on the system disk, the pool's
#                        apps subvolume empty, no /srv/apps line in fstab; the same for the media
#                        library and the backups folder; with passwords=1 the vault back in
#                        /var/lib/vaultwarden), and bromigos lab app-data move must put all of
#                        it on the data disks
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
    for sub in media backups; do
        check "/srv/$sub is on the data disks too: their $sub subvolume" bash -c "
            a=\$(findmnt -no UUID -T /srv/$sub) d=\$(findmnt -no UUID /srv/data) r=\$(findmnt -no UUID /)
            echo \"/srv/$sub is on \${a:-nothing}; /srv/data is \${d:-not mounted}; the system disk is \$r\"
            [[ -n \$a && \$a == \"\$d\" && \$a != \"\$r\" && \$(findmnt -no FSROOT /srv/$sub) == /$sub ]]"
    done
    check "bromigos lab app-data says so" bash -c "bromigos lab app-data status --json | tee /dev/stderr | python3 -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if [(f[\"state\"], f[\"where\"]) for f in (d, *d[\"folders\"])] == [(\"ok\", \"pool\")] * 3 else 1)'"
    # the disk number the engine's plan sets the apps against is the data disks' free space
    check "the budget measures the data disks, where the apps' data goes, not the system disk" bash -c '
        got=$(bromigos lab provision --local --select start-page --plan --json | python3 -c "import json, sys; print(json.load(sys.stdin)[\"hardware\"][\"disk_gb\"])")
        pool=$(df -B1 --output=avail /srv/apps | tail -1) root=$(df -B1 --output=avail / | tail -1)
        echo "the plan says $got GB; free on the data disks: $pool bytes; free on the system disk: $root bytes"
        python3 -c "import sys; got, pool, root = float(sys.argv[1]), int(sys.argv[2]) / 2**30, int(sys.argv[3]) / 2**30; sys.exit(0 if abs(got - pool) < 0.3 and abs(got - root) > 1 else 1)" "$got" "$pool" "$root"'
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
if (( ${want[passwords]:-0} )); then
    # Vaultwarden is Arch's package: its own file names /var/lib/vaultwarden and its unit may
    # write nowhere else. Only the real unit says whether the engine's two files move the vault
    check "the lab's engine installs passwords (Vaultwarden, from Arch's packages)" bash -c "
        nm-online -q -t 90 || true
        for try in 1 2 3; do
            sudo pacman -Sy --noconfirm 2>&1 | tail -3          # a server installed offline has no package lists yet
            sudo bromigos lab provision --local --select passwords --apply --no-wait 2>&1 | tail -20; rc=\${PIPESTATUS[0]}
            (( rc == 0 )) && break
            echo \"try \$try failed (\$rc)\"; sleep 30
        done
        exit \$rc"
    check "Vaultwarden runs, and its vault is in /srv/apps/passwords, not in its package's folder" bash -c '
        for _ in $(seq 30); do systemctl is-active -q vaultwarden && sudo test -s /srv/apps/passwords/db.sqlite3 && break; sleep 2; done
        systemctl is-active vaultwarden || { sudo journalctl -u vaultwarden -n 20 --no-pager; exit 1; }
        sudo ls -la /srv/apps/passwords /var/lib/vaultwarden
        sudo test -s /srv/apps/passwords/db.sqlite3 && ! sudo test -e /var/lib/vaultwarden/db.sqlite3 && curl -fsS http://127.0.0.1:8222/alive'
    # the package's own settings file turns the web vault off; the engine's file, read after it, turns it on
    check "the web vault's page is served (200, not 404)" bash -c '
        got=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8222/); echo "the web vault answers $got"
        sudo systemctl show -p EnvironmentFiles vaultwarden
        [[ $got == 200 ]]'
    if [[ -n ${want[disks]:-} ]]; then
        check "the vault is on the data disks (its folder is on /srv/data's filesystem)" bash -c '
            a=$(sudo findmnt -no UUID -T /srv/apps/passwords) d=$(findmnt -no UUID /srv/data) r=$(findmnt -no UUID /)
            echo "/srv/apps/passwords is on ${a:-nothing}; /srv/data is ${d:-not mounted}; the system disk is $r"
            [[ -n $a && $a == "$d" && $a != "$r" ]] && sudo test -s /srv/data/apps/passwords/db.sqlite3'
    fi
fi
if [[ -n ${want[app]:-} ]]; then
    app=${want[app]}
    check "the lab's engine installs $app (bromigos lab provision --local)" bash -c "
        nm-online -q -t 90 || true
        # the image comes from a registry on the internet: a pull that fails is tried again
        # (CI, 2026-11-10: \"couldn't download ... (podman stopped with code 125)\", once)
        for try in 1 2 3; do
            sudo bromigos lab provision --local --select $app --apply --no-wait 2>&1 | tail -20; rc=\${PIPESTATUS[0]}
            (( rc == 0 )) && break
            echo \"try \$try failed (\$rc)\"; sleep 30
        done
        exit \$rc"
    if [[ -n ${want[disks]:-} ]]; then
        check "$app's data is on the data disks (its folder is on /srv/data's filesystem, and the pool's apps subvolume has it)" bash -c "
            a=\$(sudo findmnt -no UUID -T /srv/apps/$app) d=\$(findmnt -no UUID /srv/data) r=\$(findmnt -no UUID /)
            echo \"/srv/apps/$app is on \${a:-nothing}; /srv/data is \${d:-not mounted}; the system disk is \$r\"
            [[ -n \$a && \$a == \"\$d\" && \$a != \"\$r\" ]] && sudo test -d /srv/data/apps/$app"
    else
        check "$app's data is on the system disk (no data disks)" bash -c "[[ \$(sudo findmnt -no UUID -T /srv/apps/$app) == \"\$(findmnt -no UUID /)\" ]]"
    fi
fi
if [[ -n ${want[dbapp]:-} ]]; then
    # An app that keeps a SQLite database, from the catalogue: the real app makes its real
    # database, and the engine writes the hook that has every backup copy it whole
    db=${want[dbapp]} dbfile=${want[dbfile]:?dbfile=PATH is needed with dbapp=}
    check "the lab's engine installs $db, an app with a database (bromigos lab provision --local)" bash -c "
        nm-online -q -t 90 || true
        for try in 1 2 3; do
            sudo bromigos lab provision --local --select $db --apply --no-wait 2>&1 | tail -20; rc=\${PIPESTATUS[0]}
            (( rc == 0 )) && break
            echo \"try \$try failed (\$rc)\"; sleep 30
        done
        exit \$rc"
    check "$db made its database (/srv/apps/$db/$dbfile), and the engine wrote its backup hook" bash -c "
        for _ in \$(seq 60); do sudo test -s /srv/apps/$db/$dbfile && break; sleep 2; done
        sudo test -s /srv/apps/$db/$dbfile || { sudo journalctl -u $db -n 20 --no-pager; sudo ls -laR /srv/apps/$db | head -40; exit 1; }
        cat /etc/bromigos/backup-databases.d/$db.toml
        grep -q '^sqlite = ' /etc/bromigos/backup-databases.d/$db.toml
        ls /etc/bromigos/backup-databases.d/"
fi
if [[ -n ${want[app]:-} && -n ${want[disks]:-} ]]; then
    # The nightly backup on a server whose /srv/apps is a mount of the data disks' apps subvolume:
    # the real bromigos-server backup run, to a folder, and what the newest backup holds, read
    # back with the real restic. A backup that didn't cross into that mount would hold none of it
    app=${want[app]}
    # everything the newest backup holds under a folder (restic ls lists one level unless told)
    ls_latest='ls_latest() { sudo env RESTIC_REPOSITORY=/var/tmp/isotest-backup RESTIC_PASSWORD_FILE=/etc/bromigos/server/backup.key restic ls --recursive latest "$@"; }'
    opens='import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"; print(c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0], "tables and indexes in", sys.argv[1])'
    sudo cp /etc/bromigos/server.toml /root/isotest-server.toml
    check "the nightly backup holds $app's data from the data disks$( (( ${want[passwords]:-0} )) && echo ", and the vault's database copied whole")" bash -c "
        set -e
        $ls_latest
        sudo python3 -c 'import re, sys; p = \"/etc/bromigos/server.toml\"; s = re.sub(r\"(?ms)^\\[backup\\]\\n.*?(?=^\\[|\\Z)\", \"\", open(p).read()); open(p, \"w\").write(s + \"\\n[backup]\\nto = \\\"/var/tmp/isotest-backup\\\"\\n\")'
        sudo bromigos server backup run
        ls_latest /srv/apps/$app > /tmp/isotest-ls-app
        grep -x /srv/apps/$app /tmp/isotest-ls-app
        echo \"\$(grep -c '^/srv/apps/$app/' /tmp/isotest-ls-app) files and folders of $app's in the backup\"
        grep -q '^/srv/apps/$app/' /tmp/isotest-ls-app
        if (( ${want[passwords]:-0} )); then
            ls_latest /var/lib/bromigos/backup-databases > /tmp/isotest-ls-db
            cat /tmp/isotest-ls-db
            grep -x /var/lib/bromigos/backup-databases/passwords/db.sqlite3 /tmp/isotest-ls-db
            sudo python3 -c '$opens' /var/lib/bromigos/backup-databases/passwords/db.sqlite3
        fi
        sudo bromigos server backup check
        bromigos lab backups --json | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d[\"health\"]); sys.exit(0 if d[\"health\"][\"state\"] == \"ok\" else 1)'"
    if [[ -n ${want[dbapp]:-} ]]; then
        db=${want[dbapp]} dbfile=${want[dbfile]}
        check "that backup holds $db's database too, copied whole by its hook while $db ran" bash -c "
            set -e
            $ls_latest
            systemctl is-active $db
            ls_latest /var/lib/bromigos/backup-databases/$db | tee /tmp/isotest-ls-db2
            grep -x /var/lib/bromigos/backup-databases/$db/$(basename "$dbfile") /tmp/isotest-ls-db2
            sudo python3 -c '$opens' /var/lib/bromigos/backup-databases/$db/$(basename "$dbfile")
            sudo python3 -c 'import json; r = json.load(open(\"/var/lib/bromigos/server/backup.json\"))[\"run\"]; print(r[\"databases\"]); print(r[\"saw\"]); assert all(d[\"ok\"] for d in r[\"databases\"]) and \"/srv/apps/$db\" in r[\"saw\"]'"
    fi
    # An app set up after the last backup ran: the weekly check and the test restore must not call
    # it missing from that backup, and the status must say it isn't in one yet
    check "a folder made after that backup doesn't fail the check or the test restore: the status says \"not in a backup yet\"" bash -c "
        set -e
        sudo mkdir /srv/apps/isotest-later
        sudo bromigos server backup check | tee /tmp/isotest-check
        grep 'bromigos-server: /srv/apps/isotest-later (the isotest-later app.s data): not in a backup yet: the next one runs ' /tmp/isotest-check
        bromigos lab backups | tee /tmp/isotest-status
        grep -E '^  Added since +/srv/apps/isotest-later .*: not in a backup yet: the next one runs ' /tmp/isotest-status
        bromigos lab backups --json | python3 -c 'import json, sys; d = json.load(sys.stdin); print(d[\"not_in_backup_yet\"], d[\"next_backup_ts\"]); sys.exit(0 if d[\"ok\"] and d[\"health\"][\"state\"] == \"ok\" and [x[\"path\"] for x in d[\"not_in_backup_yet\"]] == [\"/srv/apps/isotest-later\"] else 1)'
        sudo bromigos lab backups test 2>&1 | tail -6
        bromigos lab backups | sed -n 1p | grep -E 'Last test restore: (just now|a minute ago|[0-9]+ minutes ago), passed'"
    # the server's own settings back, whatever the checks above made of it
    sudo rmdir /srv/apps/isotest-later 2>/dev/null
    sudo cp /root/isotest-server.toml /etc/bromigos/server.toml
    sudo rm -rf /var/tmp/isotest-backup
fi
if [[ -n ${want[app]:-} && -n ${want[disks]:-} ]] && (( ${want[move]:-0} )); then
    # A server set up before the installer mounted the data disks' apps subvolume at /srv/apps:
    # that subvolume empty, /srv/apps a folder on the system disk with the app's data in it, the
    # app running on it. Made here from the server above, then moved as a person would
    app=${want[app]}
    units=$(grep -l "/srv/apps" /etc/containers/systemd/*.container | xargs -rn1 basename | sed 's/\.container$/.service/' | tr '\n' ' ')
    if (( ${want[passwords]:-0} )); then
        # the vault as a server set up before November 2026 has it: in the package's folder, the
        # service knowing no other. Vaultwarden made this database itself, above
        check "put back as the old engine left it: the vault in /var/lib/vaultwarden, Vaultwarden running on it" bash -c '
            set -e
            sudo systemctl stop vaultwarden
            sudo rm /etc/systemd/system/vaultwarden.service.d/60-bromigos-data.conf /etc/bromigos/lab/passwords.env
            sudo cp -a /srv/apps/passwords/. /var/lib/vaultwarden/
            sudo rm -rf /srv/apps/passwords
            echo "a file the vault had before the move" | sudo tee /var/lib/vaultwarden/isotest-marker >/dev/null
            sudo sh -c "cat /var/lib/vaultwarden/rsa_key*" | sha256sum | sudo tee /root/isotest-vault-key >/dev/null
            sudo systemctl daemon-reload
            sudo systemctl start vaultwarden
            for _ in $(seq 30); do curl -fsS http://127.0.0.1:8222/alive >/dev/null && break; sleep 2; done
            curl -fsS http://127.0.0.1:8222/alive && ! sudo test -e /srv/apps/passwords'
    fi
    check "put back as the old installer left it: $app's data on the system disk, the pool's apps subvolume empty" bash -c "
        set -e
        echo 'a file the app had before the move' | sudo tee /srv/apps/$app/isotest-marker >/dev/null
        sudo systemctl stop $units
        sudo umount /srv/apps /srv/media /srv/backups
        sudo sed -i -e '\\#[[:space:]]/srv/\\(apps\\|media\\|backups\\)[[:space:]]#d' -e '/^# .*, on the data disks: their [a-z]* subvolume/d' /etc/fstab
        sudo systemctl daemon-reload
        sudo chattr -i /srv/apps /srv/media /srv/backups
        sudo cp -a /srv/data/apps/. /srv/apps/
        sudo find /srv/data/apps -mindepth 1 -delete
        # the media library and the backups folder as the old engine made them: folders on the
        # system disk. The old installer made no media subvolume at all
        sudo mkdir -p /srv/media/movies /srv/backups/data
        echo 'a film the library had before the move' | sudo tee /srv/media/movies/isotest-marker >/dev/null
        echo 'a backup another machine sent before the move' | sudo tee /srv/backups/data/isotest-marker >/dev/null
        sudo btrfs subvolume delete /srv/data/media >/dev/null
        sudo systemctl start $units
        [[ \$(sudo findmnt -no UUID -T /srv/apps/$app) == \"\$(findmnt -no UUID /)\" ]]
        [[ \$(sudo findmnt -no UUID -T /srv/media/movies) == \"\$(findmnt -no UUID /)\" ]]
        ! grep -q '[[:space:]]/srv/\\(apps\\|media\\|backups\\)[[:space:]]' /etc/fstab"
    check "bromigos lab app-data says the apps' data is on the system disk, not the data disks" bash -c "
        set -e
        bromigos lab app-data | tee /dev/stderr | grep -q 'sudo bromigos lab app-data move'
        bromigos lab app-data | grep -q 'the media library (/srv/media): on the system disk, not the data disks'
        bromigos lab app-data | grep -q '(/srv/backups): on the system disk, not the data disks'
        bromigos lab app-data status --json | python3 -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if all(f[\"state\"] == \"not-on-pool\" and f[\"has_data\"] for f in (d, *d[\"folders\"])) else 1)'"
    if (( ${want[passwords]:-0} )); then
        check "bromigos lab app-data names the vault, and the command that moves it" bash -c "
            bromigos lab app-data | tee /dev/stderr | grep -q 'passwords (Vaultwarden) keeps its data in /var/lib/vaultwarden, on the system disk; sudo bromigos lab app-data move'"
    fi
    check "the dry run says what the move would do, and changes nothing" bash -c "
        set -e
        sudo bromigos lab app-data move --dry-run | tee /dev/stderr | grep -q 'Nothing was changed'
        systemctl is-active -q ${units%% *} && ! grep -q '[[:space:]]/srv/apps[[:space:]]' /etc/fstab && [[ -z \$(sudo ls -A /srv/data/apps) ]]"
    check "bromigos lab app-data move: the apps stopped, copied, compared, the old copy kept, the apps started" bash -c "sudo bromigos lab app-data move 2>&1 | tail -40; exit \${PIPESTATUS[0]}"
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
    for sub in media backups; do
        check "/srv/$sub is on the data disks now, with the file it had, and the old copy is kept by name" bash -c "
            a=\$(findmnt -no UUID -T /srv/$sub) d=\$(findmnt -no UUID /srv/data) r=\$(findmnt -no UUID /)
            echo \"/srv/$sub is on \${a:-nothing}; /srv/data is \${d:-not mounted}; the system disk is \$r\"
            [[ -n \$a && \$a == \"\$d\" && \$a != \"\$r\" && \$(findmnt -no FSROOT /srv/$sub) == /$sub ]] || exit 1
            [[ \$(grep -c '[[:space:]]/srv/${sub}[[:space:]]' /etc/fstab) == 1 ]] || exit 1
            old=\$(ls -d /srv/$sub.on-system-disk-* | head -1)
            sudo find /srv/$sub /srv/data/$sub \$old -name isotest-marker | sort | tee /dev/stderr | wc -l | grep -qx 3"
    done
    if (( ${want[passwords]:-0} )); then
        check "the vault is on the data disks now: the same key and file, Vaultwarden running on it, the old copy kept" bash -c '
            for _ in $(seq 30); do curl -fsS http://127.0.0.1:8222/alive >/dev/null && break; sleep 2; done
            systemctl is-active vaultwarden || { sudo journalctl -u vaultwarden -n 20 --no-pager; exit 1; }
            sudo ls -la /srv/apps/passwords /var/lib/vaultwarden /var/lib | grep -v "^total"
            a=$(sudo findmnt -no UUID -T /srv/apps/passwords) d=$(findmnt -no UUID /srv/data)
            old=$(sudo sh -c "ls -d /var/lib/vaultwarden.on-system-disk-*" | head -1)
            [[ -n $a && $a == "$d" && -n $old ]] || exit 1
            sudo grep -qx "a file the vault had before the move" /srv/apps/passwords/isotest-marker "$old/isotest-marker" || exit 1
            [[ $(sudo sh -c "cat /srv/apps/passwords/rsa_key*" | sha256sum) == "$(sudo cat /root/isotest-vault-key)" ]] || exit 1
            ! sudo sh -c "ls /var/lib/vaultwarden/db.sqlite3* /var/lib/vaultwarden/rsa_key*" 2>/dev/null || exit 1
            curl -fsS http://127.0.0.1:8222/alive'
    fi
    check "bromigos lab app-data says it's on the data disks, and names the old copy" bash -c "bromigos lab app-data | tee /dev/stderr | grep -q 'app-data remove-old'"
    check "remove-old deletes the old copies, and only those" bash -c "
        sudo bromigos lab app-data remove-old || exit 1
        ! sudo sh -c 'ls -d /srv/*.on-system-disk-* /var/lib/vaultwarden.on-system-disk-*' 2>/dev/null || exit 1
        sudo test -s /srv/apps/$app/isotest-marker && sudo test -s /srv/media/movies/isotest-marker && sudo test -s /srv/backups/data/isotest-marker"
fi
echo "server data checks: $fails failed"
exit $fails
