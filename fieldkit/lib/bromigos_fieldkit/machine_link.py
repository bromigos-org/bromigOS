"""Field Kit and bromigOS Server as a BRODEC machine (docs/fieldkit-vector.md, "Pair with BRODEC").

BRODEC's own agent, `brodec-machine` (BRODEC's docs/MACHINE_JOBS.md), does the pairing, the
end-to-end encrypted machine room, the owner and fingerprint rules, STOP ALL and the Herdr
remote terminal. Field Kit doesn't reimplement any of it: this reads the agent's own files
(`pair-code.json` while a code waits, `pairing.json` once paired, in its data folder), writes
the root-owned capability file Field Kit needs when there's none, and starts the agent.

  state()            installed, configured, running, paired (with whom), the code waiting: the
                     agent's own `brodec-machine pair --json --once` when it has it, else its files
  capability_file()  /etc/brodec-machine/machine.toml for Field Kit or Server: no jobs; the
                     remote terminal on for the `fieldkit` Herdr workspace only, with the phone's
                     shells; machine controls on (restart and shut down; update on Server); no
                     sessions, no den
  write_capability() that file, when there's none (root, here at the machine): what a setup screen
                     does before `brodec-machine pair --json --start` (`fieldkit-engine brodec-setup`)
  start()            writes that file if there's none, starts the agent
  controls()         what may be asked of this machine, and who carries it out: restart, shut
                     down and update are BRODEC's own machine controls ([system], with the phone's
                     fingerprint); VECTOR's proposals for them, a new terminal tab and a command
                     go through Field Kit's approvals here
"""

import json
import os
import pwd
import shutil
import socket
import subprocess
import time

from . import system

CONFIG = os.environ.get("BROMIGOS_BRODEC_MACHINE_CONFIG", "/etc/brodec-machine/machine.toml")
SERVER = "/usr/lib/bromigos/server/bromigos-server"
UNIT = "brodec-machine-fieldkit"


def binary():
    return shutil.which(os.environ.get("BROMIGOS_BRODEC_MACHINE", "brodec-machine"))


def agent_user():
    """Who the agent runs as: root on a Field Kit medium (it's root's console), else the person
    who ran sudo, else the first person with the agent's data folder."""
    if os.environ.get("BROMIGOS_BRODEC_MACHINE_USER"):
        return os.environ["BROMIGOS_BRODEC_MACHINE_USER"]
    if system.live_medium():
        return "root"
    if os.environ.get("SUDO_USER"):
        return os.environ["SUDO_USER"]
    for e in pwd.getpwall():
        if e.pw_uid >= 1000 and os.path.isdir(os.path.join(e.pw_dir, ".local/share/brodec-machine")):
            return e.pw_name
    return "root"


def data_dir(user=None):
    if os.environ.get("BROMIGOS_BRODEC_MACHINE_DATA"):
        return os.environ["BROMIGOS_BRODEC_MACHINE_DATA"]
    user = user or agent_user()
    try:
        home = pwd.getpwnam(user).pw_dir
    except KeyError:
        home = os.path.expanduser("~")
    return os.path.join(home, ".local/share/brodec-machine")


def _json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def running():
    r = system.run(["pgrep", "-f", "brodec-machine run"], check=False)
    return r.returncode == 0


def _as_agent(argv):
    """argv run as the agent's user (root runs it through runuser for someone else)."""
    user = agent_user()
    if os.geteuid() == 0 and user != "root":
        return ["runuser", "-u", user, "--", *argv]
    return argv


def pair_once():
    """The agent's own word on pairing (`brodec-machine pair --json --once`, BRODEC's
    docs/MACHINE_JOBS.md "Pairing from a setup screen"): its last event, or None when this
    agent doesn't have the command."""
    if not binary():
        return None
    r = system.run(_as_agent([binary(), "pair", "--json", "--once"]), check=False)
    for line in reversed(r.stdout.strip().splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("event"):
            return ev
    return None


def state():
    """Where pairing stands, in the agent's own words, never a secret: the pairing code is
    shown on this screen anyway, and the bot's tokens stay in its store."""
    ev = pair_once() if os.environ.get("BROMIGOS_BRODEC_PAIR_FILES") != "1" else None
    if ev:
        doc = {"ok": True, "installed": True, "configured": os.path.isfile(CONFIG), "running": running(),
               "user": agent_user(), "state": "stopped", "code": None, "paired": None}
        kind = ev["event"]
        if kind == "code":
            doc["state"] = "waiting"
            doc["code"] = {k: ev.get(k) for k in ("user_code", "user_code_display", "verification_uri", "qr", "qr_text",
                                                  "fingerprint", "expires_at_ms")}
            doc["code"]["lab_name"] = ev.get("name", "")
            doc["message"] = "In BRODEC: LAB › MACHINES › ADD MACHINE, then scan this code."
        elif kind == "paired":
            doc["state"] = "paired"
            doc["paired"] = {"name": ev.get("name", ""), "machine_id": ev.get("id", ""), "paired_at": ev.get("paired_at", 0)}
            doc["message"] = f"Paired with BRODEC as {ev.get('name') or 'this machine'}."
        elif kind == "waiting":
            doc["state"] = "starting" if ev.get("reason") in ("starting", "disconnected") else "stopped"
            doc["message"] = ev.get("message") or "BRODEC's agent isn't running."
        elif kind == "failed":
            doc["state"] = "stopped"
            doc["message"] = ev.get("message") or "Pairing can't go on."
            if ev.get("code") == "no_capability_file":
                doc["configured"] = False
        else:
            doc["message"] = ev.get("message", "")
        return doc
    d = data_dir()
    doc = {"ok": True, "installed": bool(binary()), "configured": os.path.isfile(CONFIG), "running": running(),
           "user": agent_user(), "state": "missing", "code": None, "paired": None}
    p = _json(os.path.join(d, "pairing.json"))
    c = _json(os.path.join(d, "pair-code.json"))
    if not doc["installed"]:
        doc["message"] = ("BRODEC's machine agent isn't on this system. It comes in the brodec-machine package "
                          "(docs/fieldkit-vector.md): with it, pairing works from here.")
    elif p and not p.get("revoked_at"):
        doc["state"] = "paired"
        doc["paired"] = {"name": p.get("name", ""), "machine_id": p.get("lab_id", ""), "fingerprint": p.get("fingerprint", ""),
                         "paired_at": p.get("paired_at", 0)}
        doc["message"] = f"Paired with BRODEC as {p.get('name', 'this machine')}."
    elif c and c.get("expires_at_ms", 0) > time.time() * 1000:
        doc["state"] = "waiting"
        doc["code"] = {k: c.get(k) for k in ("user_code", "verification_uri", "qr", "fingerprint", "lab_name", "expires_at_ms")}
        doc["message"] = "In BRODEC: LAB › MACHINES › ADD MACHINE, then scan this code."
    elif doc["running"]:
        doc["state"] = "starting"
        doc["message"] = "BRODEC's agent is starting; its code shows in a moment."
    else:
        doc["state"] = "stopped"
        doc["message"] = ("Not paired. Pairing starts BRODEC's agent here; it needs the internet to reach your "
                          "BRODEC account (only for pairing and the encrypted room).")
        if p and p.get("revoked_at"):
            doc["message"] = "BRODEC disconnected this machine; pair it again."
    return doc


def capability_file(name=None, server=None):
    """What a Field Kit or Server machine allows from the phone: nothing runs jobs (no engines),
    the remote terminal sees and steers only the `fieldkit` Herdr workspace (the Field Kit
    console and VECTOR) and the phone's own shells, machine controls (restart and shut down;
    update too on bromigOS Server: never on a live stick), no NEW SESSION, no den. Root's,
    like every machine's."""
    name = (name or socket.gethostname() or "fieldkit").replace('"', "")
    if server is None:
        server = os.path.exists(SERVER) and not system.live_medium()
    actions = '["restart", "shutdown", "update"]' if server else '["restart", "shutdown"]'
    return f"""# BRODEC machine jobs: what this machine allows (written by Field Kit; BRODEC's docs/MACHINE_JOBS.md).
# Root's file: change it only with sudo, here at the machine. The agent reloads it by itself.

[machine]
name = "{name}"

[jobs]
# Field Kit and bromigOS Server run no Codex or Claude Code jobs.
engines = []
max_running = 1
max_minutes = 30
network = "never"

[remote_terminal]
# The phone watches and steers the Field Kit console (Herdr's "fieldkit" workspace), signed by
# the phone you enrol here with sudo; STOP ALL ends it. phone_shells: the phone's own shells
# (its terminal buttons) work here too.
enabled = true
agent_panes = "listed"
workspaces = ["fieldkit"]
control = ["fieldkit"]
one_tap_answers = []
phone_shells = true

[system]
# Machine controls from the phone: each takes its fingerprint, a restart or shutdown counts down
# and can be cancelled, STOP ALL cancels it.{" A Field Kit stick never updates itself." if not server else ""}
enabled = true
actions = {actions}

[wake]
# Power on from BRODEC: a Field Kit stick neither wakes nor is woken; an always-on bromigOS
# Server can send wake-ups for your other machines on its network ("Power on", MACHINE_JOBS.md).
enabled = false
send = {"true" if server else "false"}

[sessions]
enabled = false

[den]
enabled = false
"""


def write_capability():
    """The capability file, when there's none (an existing one is the operator's and stays):
    root's, 0644, in a root folder. What a setup screen runs with root before
    `brodec-machine pair --json --start` (`fieldkit-engine brodec-setup`). True when written."""
    if os.path.isfile(CONFIG):
        return False
    os.makedirs(os.path.dirname(CONFIG), mode=0o755, exist_ok=True)
    tmp = CONFIG + ".fieldkit-new"
    with open(tmp, "w") as f:
        f.write(capability_file())
    os.chmod(tmp, 0o644)
    os.replace(tmp, CONFIG)
    return True


def start():
    """The capability file (if there's none: written here, at the machine, as root) and the
    agent started as its user."""
    if not binary():
        raise system.Failed("BRODEC's machine agent isn't on this system (package brodec-machine).")
    write_capability()
    user = agent_user()
    if running():
        return "BRODEC's agent is already running."
    if user == "root":
        r = system.run(["systemd-run", f"--unit={UNIT}", "--property=Restart=on-failure", "--setenv=HOME=/root",
                        binary(), "run"], check=False)
    else:
        r = system.run(["systemctl", "--user", f"--machine={user}@.host", "enable", "--now", "brodec-machine.service"], check=False)
    if r.returncode != 0:
        raise system.Failed("BRODEC's agent didn't start: " + (r.stderr.strip() or r.stdout.strip() or "?"))
    return "BRODEC's agent started; its pairing code shows in a moment."


# ------------------------------------------------------------------ what the phone may ask

def controls():
    """Each control that may be asked of this machine, and who carries it out (`by`). The phone's
    Restart, Shut down and Update are BRODEC's own machine controls: the agent checks the
    phone's fingerprint and [system] in root's capability file, and a fixed system unit acts
    (BRODEC's docs/MACHINE_JOBS.md, "Machine controls"); Field Kit doesn't queue them a second
    time. VECTOR's proposals for the same three, a new terminal tab and a command go through
    Field Kit's approvals at this screen (vector_tools' queue)."""
    live = system.live_medium()
    server = os.path.exists(SERVER)
    tab = bool(shutil.which("herdr") or shutil.which("tmux"))
    brodec = bool(binary())
    phone = "the phone: BRODEC's machine controls ([system])" if brodec else ""
    return [
        {"id": "reboot", "title": "Restart", "available": True, "why": "", "phone": phone},
        {"id": "poweroff", "title": "Shut down", "available": True, "why": "", "phone": phone},
        {"id": "update", "title": "Update bromigOS", "available": server and not live,
         "why": "" if server and not live else ("a Field Kit stick doesn't update itself" if live else "only on bromigOS Server"),
         "phone": phone if server and not live else ""},
        {"id": "new_tab", "title": "New terminal tab", "available": tab, "why": "" if tab else "no herdr or tmux here", "phone": ""},
        {"id": "run_command", "title": "Run a command", "available": True, "why": "approved with the command shown in full",
         "phone": ""},
    ]


def control_argv(action):
    """The command a control runs once approved (None: refused, with why)."""
    if action == "reboot":
        return ["systemctl", "reboot"], ""
    if action == "poweroff":
        return ["systemctl", "poweroff"], ""
    if action == "update":
        if system.live_medium():
            return None, "A Field Kit stick doesn't update itself: write a newer one."
        if not os.path.exists(SERVER):
            return None, "Updating from here is for bromigOS Server."
        return [SERVER, "update", "--now"], ""
    if action == "new_tab":
        if shutil.which("herdr"):
            return ["herdr", "tab", "create", "--label", "Field Kit shell", "--cwd", os.path.expanduser("~"), "--no-focus"], ""
        if shutil.which("tmux"):
            return ["tmux", "new-window", "-t", "fieldkit", "-d"], ""
        return None, "There's no herdr or tmux here."
    return None, f"No control {action}."
