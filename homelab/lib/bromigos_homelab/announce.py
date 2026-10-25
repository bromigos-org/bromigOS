"""A provisioned box announces itself: an Ansible role that publishes `_bromigos-lab._tcp`
over mDNS with Avahi, so Find my lab (findlab.py, `bromigos setup homelab --find`) always
finds it (docs/lab-provision.md, "The box announces itself").

The announced port is the box's SSH port, the one bromigOS provisions it through. Its one
TXT record is txtvers=1: no service list, version or name of yours goes on the network.
A box (an SSH target) announces itself. A cluster plan's first control node does too, and
Find my lab finds the other nodes through the Kubernetes source.
"""

SERVICE = "_bromigos-lab._tcp"
PACKAGES = {"debian": ["avahi-daemon"], "ubuntu": ["avahi-daemon"], "fedora": ["avahi"], "arch": ["avahi"]}
ROLE = "announce"


def service_xml(port):
    """Avahi's static service file (/etc/avahi/services/bromigos-lab.service)."""
    return ('<?xml version="1.0" standalone="no"?>\n'
            '<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            '<!-- bromigos lab provision: so bromigos setup homelab --find finds this box -->\n'
            '<service-group>\n'
            '  <name replace-wildcards="yes">bromigOS lab on %h</name>\n'
            '  <service>\n'
            f'    <type>{SERVICE}</type>\n'
            f'    <port>{int(port)}</port>\n'
            '    <txt-record>txtvers=1</txt-record>\n'
            '  </service>\n'
            '</service-group>\n')


def plan(files, state, roles):
    """Add the role for a box whose distribution it knows; anything else is left as it is."""
    from . import provision as P
    target = state["target"]
    packages = PACKAGES.get((state.get("inventory") or {}).get("distribution"))
    if target.get("kind") != "ssh" or not packages:
        return
    files[f"ansible/roles/{ROLE}/files/bromigos-lab.service"] = service_xml(target.get("port") or 22)
    files[f"ansible/roles/{ROLE}/tasks/main.json"] = P.dump([
        P.task("Install Avahi, which answers mDNS questions on the local network", "ansible.builtin.package",
               {"name": packages, "state": "present"}),
        P.task("Announce the box as a bromigOS lab", "ansible.builtin.copy",
               {"src": "bromigos-lab.service", "dest": "/etc/avahi/services/bromigos-lab.service", "mode": "0644"}),
        P.task("Keep Avahi running", "ansible.builtin.systemd",
               {"name": "avahi-daemon", "enabled": True, "state": "started"})])
    roles.append(ROLE)
