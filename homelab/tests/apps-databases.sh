#!/usr/bin/env bash
# The database hooks' paths, proven on the real apps: CI's throwaway runner (.github/workflows/
# homelab-tests.yml, "App databases on a Server"), as root, with Podman, Quadlet and systemd.
#
# The engine installs real catalogue apps that keep SQLite databases (`bromigos lab apps add`,
# the real images, pinned by digest). Once each answers, `bromigos lab backups copy-databases`
# must copy at least one database for it, through the hook the engine wrote. A hook whose path is
# wrong copies nothing: this is where that would show. When one copies nothing, the folder's
# files are listed, so the right path can be read off the run.
#
#   apps-databases.sh [ID…]        these apps (default: PROVE below)
#
# The lane's summary lists which apps' paths it proved, and docs/server.md says which are still
# from their documentation only. Never run this on a computer you use: it installs the
# catalogue in /usr/share/bromigos/lab and writes /etc, /srv/apps and /srv/media.
set -uo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
lab="$repo/homelab/bin/bromigos-lab"
[[ $(id -u) == 0 ]] || { echo "run as root, on a throwaway machine" >&2; exit 2; }
[[ ${CI:-} == true ]] || { echo "this changes the machine it runs on: CI only" >&2; exit 2; }

# The apps this lane can run in its time on GitHub's runner: no account with a company, no
# setup form that must be filled, no graphics card. (Photos needs 4 GB of memory and makes its
# database dumps at 02:00; Plex needs an account; the Pelican panel needs Wings.) Apps with a key
# of their own (Prowlarr, Sonarr, Radarr, Lidarr, and so Bazarr and Autoscan; Paperless) don't
# start on this runner: the engine's Podman secrets aren't made here, and why isn't known yet
# (2026-11-11, Podman 4.9: "no secret with name or id bromigos-prowlarr-api-key"). They are tried,
# and reported, not failed
PROVE=(navidrome prowlarr sonarr radarr lidarr bazarr jellyfin seerr autoscan audiobookshelf pinchflat uptime
       home-automation documents)
(( $# )) && PROVE=("$@")
# Apps that make no database until someone uses them: their hook finding nothing here is right,
# and is reported, not failed. Uptime Kuma 2 makes kuma.db when its first page is filled in
LATER=(uptime)

install -Dm0644 "$repo/homelab/share/provision-catalogue.toml" /usr/share/bromigos/lab/provision-catalogue.toml
rm -rf /usr/share/bromigos/lab/quadlet
cp -r "$repo/homelab/share/quadlet" /usr/share/bromigos/lab/quadlet
install -d /etc/bromigos
[[ -e /etc/bromigos/server.toml ]] || printf '# the app databases CI test: a Server\n' > /etc/bromigos/server.toml

echo "::group::add ${PROVE[*]}"
added=()
for id in "${PROVE[@]}"; do
    # one at a time: an image that can't be pulled, or an app that doesn't answer, is that app's
    # result, and the others still run
    if timeout 900 "$lab" apps add "$id"; then added+=("$id"); else echo "ADD-FAILED $id"; fi
done
echo "::endgroup::"

copies() {   # the app's rows from one copy-databases run: "copied PATH", "none PATTERN", "failed REASON"
    "$lab" backups copy-databases --json | python3 -c 'import json, sys
for r in json.load(sys.stdin)["databases"]:
    if r["name"] != sys.argv[1]:
        continue
    print("none " + r["path"] if r.get("none") else ("copied " + r["path"]) if r["ok"] and not r.get("own") else
          ("own " + r["path"]) if r.get("own") else "failed " + r["reason"])' "$1"
}

units_of() {   # the app's services, from the catalogue (an app whose add failed has no hook left)
    PYTHONPATH="$repo/homelab/lib" python3 -c 'import sys
from bromigos_homelab import localprovision as L, provcatalog as PC
print(" ".join(L.services_of(PC.by_id()[sys.argv[1]])))' "$1"
}
proven=() missed=() never=() later=()
for id in "${PROVE[@]}"; do
    # an app whose add stopped at its health check (slow to answer) may still run: its hook is
    # checked all the same once its services are up
    read -ra units < <(units_of "$id")
    if [[ " ${added[*]} " != *" $id "* ]]; then
        up=""
        for _ in $(seq 24); do
            # every one of them (is-active with several units is true when any one is)
            states=$( (( ${#units[@]} )) && systemctl is-active "${units[@]}")
            [[ -n $states ]] && ! grep -vqx active <<<"$states" && { up=1; break; }
            sleep 5
        done
        if [[ -z $up ]]; then
            never+=("$id")
            echo "::group::$id: not running"
            for u in "${units[@]}"; do
                echo "== $u"; systemctl status "$u" --no-pager --lines=0 2>&1 | head -6
                journalctl -u "$u" -n 30 --no-pager -o cat 2>&1 | tail -30
                cat "/etc/containers/systemd/${u%.service}.container" 2>/dev/null
            done
            podman secret ls 2>&1 | head -12
            echo "::endgroup::"
            continue
        fi
    fi
    echo "::group::$id"
    cat "/etc/bromigos/backup-databases.d/$id.toml"
    # an app makes its database as it starts; some take a minute after they answer
    got=""
    for _ in $(seq 36); do
        got=$(copies "$id")
        grep -q '^copied ' <<<"$got" && break
        sleep 5
    done
    echo "$got"
    if grep -q '^copied ' <<<"$got"; then
        proven+=("$id")
    elif [[ " ${LATER[*]} " == *" $id "* ]] && grep -q '^none ' <<<"$got"; then
        later+=("$id")
    else
        missed+=("$id")
        echo "its folder, for the right path:"
        find "/srv/apps/$id" -xdev \( -name '*.db' -o -name '*.sqlite*' -o -name '*.blb' -o -name '*.db-wal' \) -printf '  %p %s bytes\n' 2>/dev/null | head -40
        systemctl --no-pager --lines=0 status "${units[@]}" 2>&1 | grep -E 'Active:|●' || true
    fi
    echo "::endgroup::"
done

echo "::group::every hook, as the next backup finds it"
"$lab" backups copy-databases || true
echo "::endgroup::"
{
    echo "## The database hooks on the real apps"
    echo
    echo "- Proven (a database copied through its hook): ${proven[*]:-none}"
    echo "- No database yet, as expected (it makes one when it is first used): ${later[*]:-none}"
    echo "- Copied nothing (the hook's path is wrong): ${missed[*]:-none}"
    echo "- Not installed here (the image or the app didn't come up): ${never[*]:-none}"
} | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
# A wrong path fails this lane. An app that couldn't run here proves nothing either way: it is
# named in the summary (and in docs/server.md as documentation only), and its journal is above
(( ${#missed[@]} == 0 && ${#proven[@]} > 0 ))
