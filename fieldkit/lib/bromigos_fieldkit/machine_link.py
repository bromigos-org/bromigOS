"""Field Kit and bromigOS Server as a BRODEC machine (docs/fieldkit-vector.md, "Pair with BRODEC").

BRODEC's own agent, `brodec-machine` (BRODEC's docs/MACHINE_JOBS.md), does the pairing, the
end-to-end encrypted machine room, the owner and fingerprint rules, STOP ALL and the Herdr
remote terminal. Field Kit doesn't reimplement any of it: this reads the agent's own files
(`pair-code.json` while a code waits, `pairing.json` once paired, in its data folder), writes
the root-owned capability file Field Kit needs when there's none, and starts the agent.

  state()            installed, configured, running, paired (with whom), the code waiting
  capability_file()  /etc/brodec-machine/machine.toml for Field Kit or Server: no jobs, the
                     remote terminal on for the `fieldkit` Herdr workspace only, no sessions,
                     no den
  start()            writes that file if there's none (root, here at the machine), starts the agent
  controls()         what the phone (and VECTOR) may ask this machine to do: restart, shut down,
                     update (bromigOS Server only), a new terminal tab, a command (approved)
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


def state():
    """Where pairing stands, in the agent's own words (its files), never a secret: the
    pairing code is shown on this screen anyway, and the bot's tokens stay in its store."""
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


def capability_file(name=None):
    """What a Field Kit or Server machine allows from the phone: nothing runs jobs (no engines),
    the remote terminal sees and steers only the `fieldkit` Herdr workspace (the Field Kit
    console and VECTOR), no NEW SESSION, no den. Root's, like every machine's."""
    name = (name or socket.gethostname() or "fieldkit").replace('"', "")
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
# the phone you enrol here with sudo; STOP ALL ends it.
enabled = true
agent_panes = "listed"
workspaces = ["fieldkit"]
control = ["fieldkit"]
one_tap_answers = []

[sessions]
enabled = false

[den]
enabled = false
"""


def start():
    """The capability file (if there's none: written here, at the machine, as root) and the
    agent started as its user."""
    if not binary():
        raise system.Failed("BRODEC's machine agent isn't on this system (package brodec-machine).")
    if not os.path.isfile(CONFIG):
        os.makedirs(os.path.dirname(CONFIG), mode=0o755, exist_ok=True)
        tmp = CONFIG + ".fieldkit-new"
        with open(tmp, "w") as f:
            f.write(capability_file())
        os.chmod(tmp, 0o644)
        os.replace(tmp, CONFIG)
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
    """Each control the phone's machine page (and VECTOR) may ask for, mapped to Field Kit. Every
    one goes through the approval flow (vector_tools' queue); a phone's answer is signed by its
    enrolled key, as BRODEC defines."""
    live = system.live_medium()
    server = os.path.exists(SERVER)
    tab = bool(shutil.which("herdr") or shutil.which("tmux"))
    return [
        {"id": "reboot", "title": "Restart", "available": True, "why": ""},
        {"id": "poweroff", "title": "Shut down", "available": True, "why": ""},
        {"id": "update", "title": "Update bromigOS", "available": server and not live,
         "why": "" if server and not live else ("a Field Kit stick doesn't update itself" if live else "only on bromigOS Server")},
        {"id": "new_tab", "title": "New terminal tab", "available": tab, "why": "" if tab else "no herdr or tmux here"},
        {"id": "run_command", "title": "Run a command", "available": True, "why": "approved with the command shown in full"},
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
