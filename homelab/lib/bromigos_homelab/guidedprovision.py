"""`bromigos lab provision` with no arguments: set up a spare box, one checked step at a time.

Each step checks first and acts only after the user says yes. The desktop never runs sudo:
missing packages and the box's sudo rule are printed for the user to run. Answers are kept
in $XDG_STATE_HOME/bromigos/lab-provision.json, so running it again skips finished steps.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

from . import provision as P, services, hardware as H

# desktop command → the Arch Linux package that provides it
TOOLS = {"ansible-playbook": "ansible", "ansible-galaxy": "ansible", "sops": "sops", "age": "age", "age-keygen": "age",
         "git": "git", "ssh": "openssh", "ssh-keyscan": "openssh", "ssh-copy-id": "openssh"}
PYTHON = {"debian": "sudo apt install python3", "ubuntu": "sudo apt install python3", "fedora": "sudo dnf install python3",
          "arch": "sudo pacman -S python"}
SSH_KEYS = ("id_ed25519", "id_ecdsa", "id_rsa")


class Stop(Exception):
    """The user stopped, or a step can't go on. Progress so far is kept."""


class Terminal:
    """The real terminal. Tests replace it with scripted answers and fake commands."""
    def say(self, text=""):
        print(text, flush=True)

    def ask(self, question, default=""):
        answer = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
        return answer or default

    def yes(self, question):
        return input(question + " Type yes: ").strip() == "yes"

    def wait(self, text):
        if input(text + " Press Enter when it's done, or type q to stop: ").strip().lower() in ("q", "quit"):
            raise Stop("Stopped. Run bromigos lab provision again to carry on from here.")

    def which(self, name):
        return shutil.which(name)

    def run(self, argv, data=None):
        """Capture a command's output: (exit code, stdout, stderr)."""
        try:
            result = subprocess.run(argv, input=data, text=True, capture_output=True, timeout=60,
                                    **({"stdin": subprocess.DEVNULL} if data is None else {}))
        except (OSError, subprocess.TimeoutExpired):
            return 127, "", "could not run " + argv[0]
        return result.returncode, result.stdout, result.stderr

    def interactive(self, argv):
        """Hand the terminal to a command that asks its own questions, such as ssh-copy-id."""
        try:
            return subprocess.run(argv).returncode
        except OSError:
            return 127


def state_path():
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "bromigos/lab-provision.json"


class Guide:
    def __init__(self, term=None, path=None, inventory=None, plan=None, apply=None, home=None):
        self.term = term or Terminal()
        self.path = Path(path or state_path())
        self.home = Path(home or Path.home())
        self.inventory = inventory or P.inventory
        self.apply_repo = apply or P.apply
        self.plan_repo = plan or self.generate
        try:
            self.state = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.state = {}
        self.facts = None

    def save(self):
        P.write(self.path, P.dump(self.state))

    def done(self, text):
        self.term.say("  ✓ " + text)

    def key(self):
        """The first default SSH key pair in this home, if any."""
        return next((self.home / ".ssh" / name for name in SSH_KEYS if (self.home / ".ssh" / (name + ".pub")).exists()), None)

    def target(self):
        # Name the files explicitly: ssh finds ~/.ssh through the password database, not $HOME,
        # and the host key this setup saves must be the one ssh and Ansible check.
        key = self.key()
        return {"kind": "ssh", "ssh": self.state["user"] + "@" + self.state["host"], "port": int(self.state.get("port", 22)),
                "identity": str(key) if key else "", "known_hosts": str(self.home / ".ssh/known_hosts")}

    def ssh(self, command, data=None):
        # A key the user hasn't confirmed is refused, even if their SSH config would accept new keys.
        args = P.ssh_args(self.target())
        return self.term.run(args[:-1] + ["-o", "StrictHostKeyChecking=yes", args[-1], command], data)

    # 1. The desktop's tools
    def tools(self):
        self.term.say("Step 1 of 9: the tools on this desktop")
        while True:
            missing = sorted({pkg for cmd, pkg in TOOLS.items() if not self.term.which(cmd)})
            if not missing:
                self.done("Ansible, sops, age, Git and SSH are installed")
                return
            self.term.say("  These packages are missing: " + ", ".join(missing))
            self.term.say("  Install them in another terminal. This command needs your password, so run it yourself:")
            self.term.say("    sudo pacman -S --needed " + " ".join(missing))
            self.term.wait("  ")

    # 2. The age key that encrypts the lab's passwords
    def age_key(self):
        self.term.say("Step 2 of 9: your age key")
        config = Path(os.environ.get("XDG_CONFIG_HOME") or self.home / ".config")
        path = Path(os.environ.get("SOPS_AGE_KEY_FILE") or config / "sops/age/keys.txt")
        if not path.exists():
            self.term.say("  Your lab's passwords are encrypted with an age key. You don't have one yet.")
            self.term.say(f"  sops looks for it in {path}.")
            if not self.term.yes("  Create one there with age-keygen?"):
                raise Stop("No age key. Create one with age-keygen -o " + shlex.quote(str(path)) + ", then run this again.")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            code, _, _ = self.term.run(["age-keygen", "-o", str(path)])
            if code:
                raise Stop("age-keygen could not create the key")
            self.term.say("  Created. Keep this file safe, and keep a copy in your password manager.")
            self.term.say("  Without it, you can't read your lab's passwords or apply its plan again.")
        code, out, _ = self.term.run(["age-keygen", "-y", str(path)])
        recipient = next((line for line in out.split() if line.startswith("age1")), "")
        if code or not recipient:
            raise Stop(f"Could not read the public key from {path}")
        if os.environ.get("SOPS_AGE_KEY_FILE") is None and path != config / "sops/age/keys.txt":
            os.environ["SOPS_AGE_KEY_FILE"] = str(path)
        self.state.update(age_key=str(path), age_recipient=recipient)
        self.save()
        self.done(f"Age key: {path} (public key {recipient[:16]}…)")

    # 3. Which box
    def box(self):
        self.term.say("Step 3 of 9: the box")
        if self.state.get("host"):
            self.done(f"The box: {self.state['user']}@{self.state['host']} (from last time)")
            return
        self.term.say("  Which spare Linux box should become your lab? It needs Debian, Ubuntu, Fedora or Arch Linux.")
        while True:
            host = self.term.ask("  Its hostname or IP address")
            user = self.term.ask("  Your user name on the box", getpass.getuser())
            port = self.term.ask("  Its SSH port", "22")
            try:
                if not port.isdigit():
                    raise P.ProvisionError("The SSH port is a number")
                if host.startswith("-") or user.startswith("-"):
                    raise P.ProvisionError("Use user@host for the SSH target")
                P.validate_target({"kind": "ssh", "ssh": f"{user}@{host}", "port": int(port)})
                break
            except P.ProvisionError as error:
                self.term.say("  " + str(error) + ". Try again.")
        self.state.update(host=host, user=user, port=int(port))
        self.save()
        self.done(f"The box: {user}@{host}")

    # 4. SSH: the host key and a key login
    def check_ssh(self):
        code, _, err = self.ssh("true")
        err = err.lower()
        if code == 0:
            return "ok"
        if "remote host identification has changed" in err:
            return "changed"
        if "host key verification failed" in err or "no ed25519 host key is known" in err or "host key is not known" in err:
            return "unknown host"
        if "permission denied" in err:
            return "no key login"
        return "unreachable"

    def host_key(self):
        port = int(self.state.get("port", 22))
        code, scanned, _ = self.term.run(["ssh-keyscan", "-T", "10", "-p", str(port), self.state["host"]])
        lines = [line for line in scanned.splitlines() if line and not line.startswith("#")]
        if code or not lines:
            raise Stop("The box didn't answer on its SSH port. Check that it's on and that SSH is running.")
        _, prints, _ = self.term.run(["ssh-keygen", "-l", "-f", "-"], "\n".join(lines) + "\n")
        self.term.say("  The box says its SSH host key is:")
        for line in prints.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                self.term.say(f"    {parts[-1].strip('()')}  {parts[1]}")
        self.term.say("  To check it, run this on the box itself, at its own screen and keyboard:")
        self.term.say("    ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub")
        self.term.say("  The fingerprints must match exactly. If they don't, someone may be in the way.")
        if not self.term.yes("  Do they match?"):
            raise Stop("Host key not trusted. Nothing was changed.")
        known = self.home / ".ssh/known_hosts"
        known.parent.mkdir(mode=0o700, exist_ok=True)
        with open(known, "a") as stream:
            os.chmod(known, 0o600)
            stream.write("\n".join(lines) + "\n")
        self.done("Host key saved in " + str(known))

    def key_login(self):
        if not self.key():
            self.term.say("  You need an SSH key to log in to the box without a password. You don't have one yet.")
            if not self.term.yes("  Create one now with ssh-keygen? It asks for a passphrase."):
                raise Stop("No SSH key. Create one with ssh-keygen -t ed25519, then run this again.")
            if self.term.interactive(["ssh-keygen", "-t", "ed25519", "-f", str(self.home / ".ssh/id_ed25519")]):
                raise Stop("ssh-keygen didn't finish")
        command = ["ssh-copy-id", "-i", str(self.key()) + ".pub", "-o", "UserKnownHostsFile=" + str(self.home / ".ssh/known_hosts"),
                   "-o", "StrictHostKeyChecking=yes", "-p", str(self.state.get("port", 22)), self.state["user"] + "@" + self.state["host"]]
        self.term.say("  The box doesn't accept your SSH key yet. ssh-copy-id copies it there.")
        self.term.say("  It asks for your password on the box once.")
        if not self.term.yes("  Run " + shlex.join(command) + "?"):
            raise Stop("Copy your key with " + shlex.join(command) + ", then run this again.")
        if self.term.interactive(command):
            raise Stop("ssh-copy-id didn't finish. If the box refuses passwords, add your public key to "
                       "~/.ssh/authorized_keys on the box by hand.")

    def ssh_step(self):
        self.term.say("Step 4 of 9: SSH")
        for _ in range(3):
            status = self.check_ssh()
            if status == "ok":
                self.done("SSH works with your key, and the box's host key is trusted")
                return
            if status == "changed":
                raise Stop("The box's host key has CHANGED since you last connected. If you reinstalled it, remove the old key "
                           "with ssh-keygen -R <host>. Otherwise someone may be in the way. Nothing was changed.")
            if status == "unreachable":
                raise Stop(f"Can't reach {self.state['host']} over SSH. Check that it's on, on your network, and running SSH. "
                           "To choose another box, run bromigos lab provision --guided --start-over.")
            if status == "unknown host":
                self.host_key()
            else:
                self.key_login()
        raise Stop("SSH still doesn't work. Try ssh " + self.state["user"] + "@" + self.state["host"] + " to see why.")

    # 5. Python and passwordless sudo on the box
    def sudo(self):
        self.term.say("Step 5 of 9: Python and sudo on the box")
        while True:
            code, _, _ = self.ssh("command -v python3")
            if code == 0:
                break
            _, release, _ = self.ssh("cat /etc/os-release")
            distro = next((line.split("=", 1)[1].strip('"') for line in release.splitlines() if line.startswith("ID=")), "")
            self.term.say("  The box needs Python 3. On the box, run:")
            self.term.say("    " + PYTHON.get(distro, "your package manager's python3 package"))
            self.term.wait("  ")
        while True:
            code, _, _ = self.ssh("sudo -n true")
            if code == 0:
                self.done("Python 3 is there, and sudo works without a password")
                return
            user = self.state["user"]
            self.term.say("  Provisioning needs sudo without a password on the box. To allow it, run this on the box:")
            self.term.say("    sudo visudo -f /etc/sudoers.d/bromigos-lab")
            self.term.say("  and add this line:")
            self.term.say(f"    {user} ALL=(ALL) NOPASSWD: ALL")
            self.term.wait("  ")

    # 6. What the box has
    def hardware(self):
        self.term.say("Step 6 of 9: the hardware check (read-only)")
        self.facts = self.inventory(self.target())
        for line in H.describe(self.facts):
            self.term.say("  " + line)
        for note in H.notes(self.facts, [], {"service": {}}):
            self.term.say("  Note: " + note)

    # 7. Core or Advanced
    def preset(self, cat):
        self.term.say("Step 7 of 9: what to install")
        if self.state.get("preset"):
            self.done(f"Preset: {self.state['preset'].capitalize()} (chosen last time)")
            return
        fits = {}
        for name in ("core", "advanced"):
            warnings = P.selection(cat, P.preset_selection(cat, name), self.facts)["warnings"]
            fits[name] = [w for w in warnings if "unknown" not in w]
        self.term.say("  Core: a start page (Homepage), live graphs (Netdata), daily backups (restic), a web server")
        self.term.say("    in front (Caddy), and monitoring with alerts (Prometheus, Grafana, Loki, Alertmanager).")
        self.term.say("  Advanced: Core, plus Kubernetes (k3s), Helm, Argo CD and Vault. It needs more memory, and a")
        self.term.say("    Git server where you publish your lab's repository.")
        if fits["core"]:
            raise Stop("This box is too small for Core: " + "; ".join(fits["core"]))
        if fits["advanced"]:
            self.term.say("  Recommended: Core. Advanced doesn't fit this box: " + "; ".join(fits["advanced"]))
        else:
            self.term.say("  Recommended: Core. It's simpler, and you can move to Advanced later. Advanced fits too.")
        choices = ("core",) if fits["advanced"] else ("core", "advanced")
        while True:
            choice = self.term.ask("  Preset (" + " or ".join(choices) + ")", "core").lower()
            if choice in choices:
                break
        if choice == "advanced":
            self.term.say("  Argo CD reads your lab from a Git server. Create an empty repository there first.")
            while True:
                url = self.term.ask("  Its HTTPS address, such as https://git.example.org/you/lab.git")
                if re.fullmatch(r"https?://[^\s?#@]+", url):
                    break
                self.term.say("  Use an http(s) address without a password, token or ?query in it.")
            self.state["git_url"] = url
        self.state["preset"] = choice
        self.save()
        self.done(f"Preset: {choice.capitalize()}")

    # 8. Where backups go
    def backup(self):
        self.term.say("Step 8 of 9: where backups go")
        hw = (self.facts or {}).get("hardware") or {}
        places = hw.get("backup_places", [])
        if self.state.get("backup_path"):
            code, _, _ = self.ssh("test -d " + shlex.quote(self.state["backup_path"]))
            if code == 0:
                self.done(f"Backups: {self.state['backup_path']} (from last time)")
                return
        self.term.say("  restic backs up your lab every day. Backups are safest on another disk or a NAS.")
        options = []
        for p in places:
            free = f", {H.size(p['free'])} free" if p["free"] is not None else ""
            options.append((p["path"].rstrip("/") + "/lab-backups", f"{p['path']}: a {p['kind']}{free}"))
        for d in hw.get("disks", []):
            if d["empty"] and not d["removable"]:
                self.term.say(f"  The empty {H.size(d['size'])} {d['kind']} ({d['name']}) could hold backups. To use it, format and")
                self.term.say("  mount it on the box, then run this again. This tool never formats or mounts disks.")
        options.append(("/var/backups/bromigos-lab", "the system disk: fine to start with, but lost if that disk fails"))
        for i, (path, label) in enumerate(options, 1):
            self.term.say(f"  {i}. {path}  ({label})")
        while True:
            answer = self.term.ask("  Choose a number, or type a folder on the box", "1")
            path = options[int(answer) - 1][0] if answer.isdigit() and 1 <= int(answer) <= len(options) else answer
            if path.startswith("/") and not re.search(r"[\s'\"\\]", path):
                break
            self.term.say("  Use an absolute folder path on the box, without spaces or quotes.")
        code, _, _ = self.ssh("test -d " + shlex.quote(path))
        if code:
            if not self.term.yes(f"  {path} doesn't exist yet. Create it on the box (owned by root, mode 0700)?"):
                raise Stop(f"Create {path} on the box, then run this again.")
            code, _, _ = self.ssh("sudo -n install -d -m 0700 " + shlex.quote(path))
            if code:
                raise Stop(f"Could not create {path} on the box")
        self.state["backup_path"] = path
        self.save()
        self.done(f"Backups: {path}")

    # 9. The plan, then apply
    def generate(self, repo, files):
        return P.generate(repo, files)

    def plan(self, cat):
        self.term.say("Step 9 of 9: your lab's plan")
        default = str(self.home / "lab")
        repo = Path(self.state.get("repo") or self.term.ask("  Where should your lab's Git repository go on this desktop?", default)).expanduser().absolute()
        if repo.is_dir() and any(repo.iterdir()) and not (repo / "plan.json").exists():
            raise Stop(f"{repo} already holds other files. Run this again and choose an empty or new folder.")
        self.state["repo"] = str(repo)
        self.save()
        picked = P.preset_selection(cat, self.state["preset"])
        files, _ = P.plan_files(self.target(), picked, self.facts, cat=cat, repo_url=self.state.get("git_url", ""),
                                backup_path=self.state["backup_path"], age_recipient=self.state["age_recipient"])
        wanted = json.loads(files["plan.json"])
        keys = ("target", "selected", "git_url", "backup_path", "age_recipient")
        try:
            current = json.loads((repo / "plan.json").read_text())
        except (OSError, ValueError):
            current = None
        if current and all(current.get(k) == wanted.get(k) for k in keys):
            self.done(f"The plan in {repo} is up to date")
        else:
            try:
                self.plan_repo(repo, files)
            except P.ProvisionError as error:
                raise Stop(str(error)) from None
            self.done(f"Plan written to {repo}. plan.json lists every choice; ansible/ holds what will run")
        code, dirty, _ = self.term.run(["git", "-C", str(repo), "status", "--porcelain"])
        if code == 0 and dirty.strip():
            if self.term.yes("  Commit the plan to your lab's Git repository?"):
                code, _, _ = self.term.run(["git", "-C", str(repo), "add", "--all"])
                code = code or self.term.run(["git", "-C", str(repo), "commit", "--quiet", "-m", "Lab plan from bromigos lab provision"])[0]
                if code:
                    raise Stop('Git could not commit. If it asks who you are, run git config --global user.name "Your Name" '
                               'and git config --global user.email you@example.org, then run this again.')
                self.done("Committed")
            else:
                self.term.say("  Review and commit it yourself before you change the plan again.")
        if "argocd" in picked:
            self.term.say(f"  Argo CD reads the plan from {self.state['git_url']}. Push the repository there:")
            self.term.say(f"    git -C {shlex.quote(str(repo))} push {shlex.quote(self.state['git_url'])} HEAD")
            self.term.wait("  ")
        return repo

    def run(self):
        cat = services.load()
        self.term.say("Let's set up a spare Linux box as your lab. Each step checks first and asks before it changes anything.")
        self.term.say("")
        self.tools()
        self.age_key()
        self.box()
        self.ssh_step()
        self.sudo()
        self.hardware()
        self.preset(cat)
        self.backup()
        repo = self.plan(cat)
        self.term.say("")
        self.term.say("Last check before anything is installed. Here is the plan:")
        result = self.apply_repo(repo, live_facts=self.facts)
        if result == 0:
            self.state["applied"] = True
            self.save()
        return result


def main(argv):
    parser = argparse.ArgumentParser(prog="bromigos lab provision --guided",
                                     description="Set up a spare Linux box as your lab, one checked step at a time")
    parser.add_argument("--guided", action="store_true", help="the default with no arguments")
    parser.add_argument("--start-over", action="store_true", help="forget the answers from last time")
    args = parser.parse_args(argv)
    path = state_path()
    if args.start_over and path.exists():
        path.unlink()
    try:
        return Guide(path=path).run()
    except Stop as stop:
        print(str(stop), file=sys.stderr)
        return 1
    except (P.ProvisionError, OSError, ValueError, KeyError) as error:
        print("Provisioning stopped: " + (str(error) if isinstance(error, P.ProvisionError) else "Invalid or missing input"), file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. Run bromigos lab provision again to carry on from here.", file=sys.stderr)
        return 1
