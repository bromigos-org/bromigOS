#!/usr/bin/env bash
# The firewall an installed bromigOS Server really has (docs/server.md, "The firewall"), read
# from the kernel with nft in the installed system, as the test user with sudo. PASS/FAIL per
# check; exits with the number of failures.
#
#   server-firewall-checks.sh [web=lan|none]
#     web=lan    the server was installed with a role that serves web pages (Home services,
#                Media): ports 80 and 443 must answer the local network, and nobody else
#     web=none   no such role: nothing may be open on 80 or 443 at all (and the rest is skipped)
#
# Then, with web=lan, the servers that the installers of 0.1.4-rc1 to 0.1.5 left (docs/server.md, "Servers
# installed from 0.1.4-rc1 to 0.1.5"): this one's settings are put back as those installers
# wrote them, and the next apply must close the ports to the internet and say so; and an
# owner's own "open to everyone" must stay through every apply after it.
#
# iso/fieldkit/ci-test.sh runs this on a Server installed from the stick with the Home services
# role. Nothing here needs a network.
declare -A want=([web]=lan)
for kv in "$@"; do want[${kv%%=*}]=${kv#*=}; done
fails=0
check() { local name=$1; shift; if "$@" >/tmp/check.out 2>&1; then echo "PASS $name"; else echo "FAIL $name"; sed 's/^/     /' /tmp/check.out | tail -12; fails=$((fails + 1)); fi; }
toml=/etc/bromigos/server.toml
rules() { sudo nft list table inet bromigos-server; }
# the accept rules that name port 80 or 443, one a line
web_rules() { rules | grep -E 'dport (\{[^}]*\b(80|443)\b[^}]*\}|(80|443)\b)' | grep -w accept; }
# every one of them is from the local network's sets, and there is at least one for each family
# The local network: @lan and @lan6, and (since #140) the lab network's range, only on its own
# interface (`iifname "tailscale0" ip saddr @lab`: the twin each local rule has). Anything else
# letting 80 or 443 in is the internet
local_only() {
    local all; all=$(web_rules)
    echo "$all"
    [[ -n $all ]] && ! grep -Ev '^\s*(ip6? saddr @lan6? |iifname "tailscale0" ip saddr @lab )' <<<"$all" | grep -q . \
        && grep -q 'ip saddr @lan ' <<<"$all" && grep -q 'ip6 saddr @lan6 ' <<<"$all"
}
open_to_everyone() { web_rules | grep -Ev 'saddr' | grep -q .; }
allow() { sudo python3 -c 'import sys, tomllib; print(" ".join(tomllib.load(open(sys.argv[1], "rb"))["firewall"][sys.argv[2]]))' "$toml" "$1"; }

check "the firewall is loaded, and drops what nothing lets in" bash -c "
    systemctl is-active bromigos-server-firewall.service && sudo nft list table inet bromigos-server | grep -q 'policy drop'"
if [[ ${want[web]} == lan ]]; then
    check "as installed: 80 and 443 answer the local network, and nobody else" local_only
    check "as installed: the settings and the installer's record name web-lan, never web" bash -c "
        a=' $(allow allow) ' r=' $(allow rule_sets) '; echo \"allow:\$a rule_sets:\$r\"
        [[ \$a == *' web-lan '* && \$r == *' web-lan '* && \$a != *' web '* && \$r != *' web '* ]]"
else
    check "as installed: nothing is open on 80 or 443" bash -c "! sudo nft list table inet bromigos-server | grep -E 'dport (\{[^}]*\b(80|443)\b[^}]*\}|(80|443)\b)' | grep -w accept"
fi
check "status says nothing about the web ports on a server installed right" bash -c "! bromigos server status | grep -q '80 and 443'"

if [[ ${want[web]} != lan ]]; then
    echo "==> the server's firewall: $fails failed"
    exit "$fails"
fi

# ---- a server as the installers of 0.1.4-rc1 to 0.1.5 left it: web in both lists
everyone='tcp dport \{ 80, 443 \} accept comment "web"$'
sudo cp "$toml" /root/server.toml.asinstalled
sudo sed -i -E '/^\[firewall\]/,/^\[/ s/^(allow|rule_sets) = (.*)"web-lan"/\1 = \2"web"/' "$toml"
sudo rm -f /var/lib/bromigos/server/firewall.json
check "put back as those installers wrote it: web in the settings and in the installer's record" bash -c "
    a=' $(allow allow) ' r=' $(allow rule_sets) '; echo \"allow:\$a rule_sets:\$r\"; [[ \$a == *' web '* && \$r == *' web '* ]]"
# (--print loads nothing and changes nothing: it shows what those settings meant)
check "what that meant: 80 and 443 from anywhere (the fault)" bash -c "sudo bromigos server firewall apply --print | grep -Eq '$everyone'"
check "status says so before the fix, with the command that fixes it now" bash -c "
    bromigos server status | grep -q 'ports 80 and 443 are open to everyone: the installer set that by mistake'"
check "the next apply (the firewall's unit runs it at every start, and every update) moves it to the local network" bash -c "
    sudo systemctl restart bromigos-server-firewall.service && systemctl is-active bromigos-server-firewall.service || exit 1
    a=\" \$(sudo python3 -c 'import sys, tomllib; print(\" \".join(tomllib.load(open(sys.argv[1], \"rb\"))[\"firewall\"][\"allow\"]))' $toml) \"
    echo \"allow:\$a\"; [[ \$a == *' web-lan '* && \$a != *' web '* ]]"
check "after it: 80 and 443 answer the local network, and nobody else" local_only
check "status says so, in one line, with the command that opens them on purpose" bash -c "
    [[ \$(bromigos server status | grep -c '80 and 443') == 1 ]] || { bromigos server status; exit 1; }
    bromigos server status | grep -q 'ports 80 and 443 now answer the local network only: the installer had opened them to everyone by mistake. To open them to everyone on purpose: sudo bromigos server firewall allow web'"
check "another apply changes nothing" bash -c "sudo bromigos server firewall apply && ! sudo nft list table inet bromigos-server | grep -Eq '$everyone'"

# ---- an owner's own "open to everyone" stays
check "the owner opens the server to everyone on purpose" bash -c "
    sudo bromigos server firewall allow web && sudo nft list table inet bromigos-server | grep -Eq '$everyone'"
check "and it stays through an apply and a restart of the firewall" bash -c "
    sudo bromigos server firewall apply >/dev/null && sudo systemctl restart bromigos-server-firewall.service
    sudo nft list table inet bromigos-server | grep -Eq '$everyone'"
check "status says it is open to everyone, with the one command that closes it" bash -c "
    bromigos server status | grep -q 'ports 80 and 443 are open to everyone (the rule set web). To close them to the internet: sudo bromigos server firewall deny web'"
check "that command closes it" bash -c "
    sudo bromigos server firewall deny web && ! sudo nft list table inet bromigos-server | grep -Eq '$everyone'"
check "and the local network still reaches 80 and 443" local_only
sudo cp /root/server.toml.asinstalled "$toml"
sudo rm -f /var/lib/bromigos/server/firewall.json
sudo systemctl restart bromigos-server-firewall.service

echo "==> the server's firewall: $fails failed"
exit "$fails"
