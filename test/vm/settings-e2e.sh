#!/usr/bin/env bash
# shellcheck disable=SC2329,SC2016  # the checks' functions run through check; the VM's commands expand there
# Settings' system pages against the real services, in the fresh-machine VM (docs/settings.md,
# "Tests"): after `test/vm/arch-vm.sh install` (a channel carrying bromigos net, bluetooth,
# power, about). Everything happens in the VM over SSH; its NetworkManager, bluez,
# power-profiles-daemon and pacman are real, its Wi-Fi is simulated (mac80211_hwsim: two
# radios, hostapd making one a WPA2 access point, dnsmasq its DHCP) and its battery is the kernel's test_power.
# Prints PASS/FAIL per check; exits with the number of failures; the pages drawn on the VM's
# own screen (when its desktop session runs) in DIR/shots/settings-*.png.
#
#   test/vm/settings-e2e.sh [--dir DIR]       (BROMIGOS_VM_PORT etc. as arch-vm.sh)
#
# 1. Network: the wired port seen (left to systemd-networkd: SSH runs over it); the simulated network in reach, secured; joined with
#    its password on stdin (never on a command line: the passwd-file is gone after); a wrong
#    password leaves nothing saved; disconnect, forget; the Wi-Fi radio off and on;
# 2. Bluetooth: bluetoothd running with no controller is said plainly, never a crash;
# 3. Power: power-profiles-daemon's profile switched both ways; the test battery's charge
#    and state read; the lid file shown (--print) without writing;
# 4. Updates & recovery and About: the channel, what's waiting, the snapshots, the version
#    and packages, as the pages read them;
# 5. the Network, Bluetooth, Power, Updates and About pages drawn in the VM's session (signed in
#    at its login screen through QEMU's keyboard when no session runs).
set -uo pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dir=${BROMIGOS_VM_DIR:-$HOME/.cache/bromigos-vmtest}
[[ ${1:-} == --dir ]] && dir=$2
out=$(mktemp "${TMPDIR:-/tmp}/settings-e2e.XXXX")
trap 'rm -f "$out"' EXIT

vm() { "$here/arch-vm.sh" ssh --dir "$dir" "$@"; }
fails=0 passes=0
check() {
  local name=$1; shift
  if "$@" >"$out" 2>&1; then echo "PASS $name"; passes=$((passes + 1)); else
    echo "FAIL $name"; sed 's/^/     /' "$out" | tail -6; fails=$((fails + 1)); fi
}
# a field of a command's --json document, in the VM
field() { vm "$1 --json" | python3 -c "import json,sys; d=json.load(sys.stdin); print($2)"; }
is() { local got; got=$(field "$1" "$2"); [[ $got == "$3" ]] || { echo "$1: $2 = $got, not $3"; return 1; }; }

echo "== setting up the VM's simulated hardware"
# NetworkManager for the radios only (the cloud image's ethernet stays systemd-networkd's: SSH);
# a polkit rule for this test's user, since SSH isn't an active seat session (a desktop session
# is allowed these by default); the modules need the kernel the install upgraded to (reboot)
vm 'uname -r | grep -q "$(pacman -Q linux | cut -d" " -f2 | tr -d " ")" || echo "REBOOT NEEDED"' | grep -q "REBOOT NEEDED" &&
  { echo "rebooting into the upgraded kernel"; "$here/arch-vm.sh" reboot --dir "$dir" >/dev/null; }
vm 'sudo pacman -S --noconfirm --needed hostapd dnsmasq iw bluez bluez-utils power-profiles-daemon >/dev/null 2>&1
    printf "%s\n" "polkit.addRule(function(action, subject) {" \
      "  if (subject.user == \"tester\" && (action.id.indexOf(\"org.freedesktop.NetworkManager.\") == 0 ||" \
      "      action.id.indexOf(\"org.freedesktop.UPower.PowerProfiles.\") == 0 || action.id.indexOf(\"net.hadess.PowerProfiles.\") == 0))" \
      "    return polkit.Result.YES; });" | sudo tee /etc/polkit-1/rules.d/90-bromigos-settings-e2e.rules >/dev/null
    printf "[keyfile]\nunmanaged-devices=interface-name:en*;interface-name:eth*\n" |
      sudo tee /etc/NetworkManager/conf.d/90-settings-e2e.conf >/dev/null
    sudo modprobe bluetooth; sudo modprobe mac80211_hwsim radios=2; sudo modprobe test_power
    sudo systemctl start NetworkManager bluetooth power-profiles-daemon; sleep 4
    ap=$(ls /sys/class/net | grep -E "^wlan" | sort | head -1)
    sudo nmcli dev set "$ap" managed no
    printf "interface=%s\ndriver=nl80211\nssid=bromigos-test\nhw_mode=g\nchannel=6\nwpa=2\nwpa_passphrase=correct horse battery\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n" "$ap" | sudo tee /etc/hostapd/settings-e2e.conf >/dev/null
    sudo pkill -x hostapd; sudo hostapd -B /etc/hostapd/settings-e2e.conf >/dev/null; sleep 3
    sudo ip addr replace 192.0.2.1/24 dev "$ap"         # its addresses: a documentation range, DHCP from dnsmasq
    sudo pkill -x dnsmasq; sudo dnsmasq --interface="$ap" --bind-interfaces --port=0 --dhcp-range=192.0.2.10,192.0.2.50,1h
    echo "access point on $ap"' || true

echo "== 1. Network"
check "net: NetworkManager answers; the wired port listed, the Wi-Fi radios found" \
  is "bromigos net" '[d["running"], bool(d["wired"]), d["wifi"]["hardware"]]' "[True, True, True]"
check "net: the simulated network is in reach, secured" bash -c '
  for _ in 1 2 3 4 5 6; do "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "bromigos net scan --json >/dev/null; sleep 4; bromigos net --json" |
    python3 -c "import json,sys; d=json.load(sys.stdin); n=[w for w in d[\"wifi\"][\"networks\"] if w[\"ssid\"]==\"bromigos-test\"]; sys.exit(0 if n and n[0][\"secured\"] else 1)" && exit 0; done; exit 1'
check "net: a wrong password: refused, nothing saved" bash -c '
  r=$("'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "printf %s nope-nope-nope | bromigos net connect bromigos-test --password-stdin --json")
  echo "$r"; echo "$r" | grep -q "\"ok\": false" &&
  ! "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "nmcli -t -f NAME con show" | grep -qx bromigos-test'
check "net: joined with the password on stdin" bash -c '
  "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "printf %s \"correct horse battery\" | bromigos net connect bromigos-test --password-stdin --json" | grep -q "\"ok\": true"'
check "net: in use, with an address" \
  is "bromigos net" '[w["ssid"] for w in d["wifi"]["networks"] if w.get("in_use")] == ["bromigos-test"] and any(c.get("ip4") for c in d.get("devices", []) if c.get("type") == "wifi" and c.get("state") == "connected")' "True"
check "net: no password file left behind, none in NetworkManager's log of commands" \
  vm '! ls /tmp/bromigos-net-* 2>/dev/null | grep -q . && ! sudo journalctl -u NetworkManager --no-pager | grep -q "correct horse"'
okdoc() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("said") or d.get("error")); sys.exit(0 if d.get("ok") else 1)'; }
wifi_dev() { vm "bromigos net --json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(next(x["name"] for x in d["devices"] if x["type"] == "wifi" and x["state"] == "connected"))'; }
check "net: disconnect" bash -c "$(declare -f vm okdoc wifi_dev); here='$here' dir='$dir'; vm \"bromigos net disconnect \$(wifi_dev) --json\" | okdoc"
check "net: forget: the saved network gone" bash -c "$(declare -f vm okdoc); here='$here' dir='$dir'; vm 'bromigos net forget bromigos-test --json' | okdoc &&
  ! vm 'nmcli -t -f NAME con show' | grep -qx bromigos-test"
check "net: the Wi-Fi radio off, then on" bash -c '
  "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "bromigos net wifi off --json >/dev/null; nmcli radio wifi" | grep -qx disabled &&
  "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "bromigos net wifi on --json >/dev/null; nmcli radio wifi" | grep -qx enabled'

echo "== 2. Bluetooth"
check "bluetooth: bluetoothd with no controller: said plainly" bash -c '
  r=$("'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "bromigos bluetooth --json"); echo "$r"
  echo "$r" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if (d.get(\"adapter\") is None and d.get(\"ok\", True)) or (not d.get(\"ok\") and \"adapter\" in d.get(\"error\", \"\").lower()) else 1)"'

echo "== 3. Power"
check "power: the profiles power-profiles-daemon offers" \
  is "bromigos power" '"balanced" in [p["name"] for p in d["profiles"]["list"]]' "True"
check "power: Power saver, then Balanced again" bash -c '
  "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "bromigos power profile power-saver --json >/dev/null; powerprofilesctl get" | grep -qx power-saver &&
  "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "bromigos power profile balanced --json >/dev/null; powerprofilesctl get" | grep -qx balanced'
check "power: the test battery's charge and state" \
  is "bromigos power" '[(b["name"], b["capacity"] is not None) for b in d["batteries"]][:1]' "[('test_battery', True)]"
check "power: the lid's file shown, not written (--print)" \
  vm 'bromigos power lid lock --print --json | grep -q HandleLidSwitch && ! test -e /etc/systemd/logind.conf.d/50-bromigos-lid.conf'

echo "== 4. Updates & recovery, About"
check "about: version, channel and packages" \
  is "bromigos about" '[bool(d["version"]), d["channel"], any(p["name"] == "bromigos-desktop" for p in d["packages"])]' "[True, 'edge', True]"
check "update --check answers (what's waiting)" is "bromigos update --check" '"packages" in d["check"]' "True"
check "rollback status answers (how updates are snapshotted)" is "bromigos rollback status" '"snapshots" in d' "True"

echo "== 5. The pages, on the VM's screen"
in_session() { vm 'bromigos session 2>/dev/null | grep -q HYPRLAND_INSTANCE_SIGNATURE'; }
if ! in_session; then      # sign in at the VM's own login screen (QEMU's keyboard; the test user's password)
  qmp() { printf '%s\n' '{"execute":"qmp_capabilities"}' "$@" | socat - "UNIX-CONNECT:$dir/qmp.sock" >/dev/null; }
  key() { qmp "{\"execute\":\"send-key\",\"arguments\":{\"keys\":[{\"type\":\"qcode\",\"data\":\"$1\"}]}}"; sleep 0.15; }
  for c in t e s t e r; do key "$c"; done; key ret
  for _ in $(seq 30); do in_session && break; sleep 2; done
fi
if in_session; then
  mkdir -p "$dir/shots"
  for p in network bluetooth power updates about; do
    check "settings: $p drawn in the VM's session" bash -c '
      "'"$here"'/arch-vm.sh" ssh --dir "'"$dir"'" "rm -f /tmp/settings-'"$p"'.png; bromigos session exec bromigos settings --render /tmp/settings-'"$p"'.png --page '"$p"' --size 1120x780" | grep -q rendered &&
      scp -i "'"$dir"'/id_ed25519" -P "${BROMIGOS_VM_PORT:-2222}" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR tester@127.0.0.1:/tmp/settings-'"$p"'.png "'"$dir"'/shots/settings-'"$p"'.png"'
  done
else
  echo "SKIP the pages: no desktop session in the VM (the login screen didn't take the password)"
fi

vm "sudo pkill -x hostapd; sudo pkill -x dnsmasq; true" >/dev/null 2>&1
echo
echo "$passes/$((passes + fails)) passed"
exit "$fails"
