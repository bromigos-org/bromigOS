"""The installer as plain questions, one after another (bromigos_installer.tui --plain): the
same steps, words and checks as the text and graphical installers, but nothing moves on the
screen and every line is new, so a screen reader (the boot menu's speech entry: espeakup)
reads it in order. Choices are numbered; Enter keeps the one in brackets."""
import getpass
import sys

from . import backend, common
from .disks import GiB, plain_size


def say(text=""):
    print(text, flush=True)


def ask(prompt, default=None, check=None):
    while True:
        try:
            v = input(f"{prompt}" + (f" [{default}]" if default not in (None, "") else "") + ": ").strip()
        except EOFError:
            raise SystemExit(1)
        v = v or (default or "")
        problem = check(v) if check else None
        if not problem:
            return v
        say(problem)


def choose(prompt, options, default=0, disabled=None):
    """options: [(value, words)]; disabled: {index: why}. Returns the value."""
    disabled = disabled or {}
    say(prompt)
    for i, (_, words) in enumerate(options, 1):
        say(f"  {i}. {words}" + (f" (not available: {disabled[i - 1]})" if i - 1 in disabled else ""))
    while True:
        v = ask("Number", str(default + 1))
        if v.isdigit() and 1 <= int(v) <= len(options) and int(v) - 1 not in disabled:
            return options[int(v) - 1][0]
        say(f"Type a number from 1 to {len(options)}" + (", one that's available." if disabled else "."))


def secret(prompt, what="password"):
    while True:
        a = getpass.getpass(f"{prompt}: ")
        b = getpass.getpass(f"{prompt}, again: ")
        problem = common.check_password(a, b, what)
        if not problem:
            return a
        say(problem)


def yes(prompt, default=True):
    v = ask(prompt + (" (yes or no)"), "yes" if default else "no").lower()
    return v.startswith("y")


def heading(sid):
    _, _, head, intro = common.STEP[sid]
    say()
    say(head + ".")
    say(intro)


def main():
    a = common.defaults()
    say("bromigOS installer. Questions come one at a time; press Enter to keep the answer in brackets.")
    heading("welcome")
    a["locale"] = choose("Language for your new system:", [(loc, n) for loc, n, _ in common.LANGUAGES])
    zones = common.timezones()
    a["timezone"] = ask("Time zone, as Region/City", common.tz_guess(a["locale"]),
                        lambda v: None if v in zones else "That isn't a time zone. For example: America/New_York, Europe/London.")
    eds = common.editions()
    if len(eds) > 1:
        heading("edition")
        a["edition"] = choose("Choose one:", [(e["id"], f"{e['title']}: {e.get('summary', '')}") for e in eds])
        ed = common.edition(a["edition"])
        if common.needs_download(ed):
            say(common.download_words(ed))
            if not common.online():
                say(common.network_words(True, False))
                raise SystemExit(1)
    ed = common.edition(a["edition"])
    heading("keyboard")
    a["keyboard"] = choose("Keyboard layout:", [(k[0], k[1]) for k in common.KEYBOARDS],
                           default=[k[0] for k in common.KEYBOARDS].index(common.LANG_KEYBOARD.get(a["locale"], "us")))
    backend.keyboard_live(a["keyboard"], "console")
    heading("disk")
    say("Looking at the disks. This takes a few seconds.")
    doc = backend.probe()
    if doc.get("error"):
        say(doc["error"])
        raise SystemExit(1)
    a["other_os"] = doc.get("other_os", False)
    for c in common.checks(doc):
        if c["level"] == "warn":
            say("Worth knowing: " + c["title"] + ". " + c["what"] + (" What to do: " + c["fix"] if c.get("fix") else ""))
    disks = doc["disks"]
    usable = {i for i, d in enumerate(disks) if not d["medium"]}
    if not usable:
        say("No disk found to install on. Check that the disk is connected, then restart.")
        raise SystemExit(1)
    path = choose("Disk:", [(d["path"], f"{d['model']}, {d['size_text']}, {d['summary']}") for d in disks],
                  default=min(usable), disabled={i: d["options"]["erase"].get("why", "") for i, d in enumerate(disks) if d["medium"]})
    d = next(x for x in disks if x["path"] == path)
    a["disk"] = path
    al, er = d["options"]["alongside"], d["options"]["erase"]
    opts, dis = [("alongside", al["label"]), ("erase", "Erase the whole disk")], {}
    if not al.get("ok"):
        dis[0] = al["why"] + " " + al.get("fix", "")
    if not er.get("ok"):
        dis[1] = er["why"]
    if len(dis) == 2:
        say("bromigOS can't go on this disk. " + er["why"] + " " + er.get("fix", ""))
        raise SystemExit(1)
    a["mode"] = choose("How:", opts, default=0 if al.get("ok") else 1, disabled=dis)
    if a["mode"] == "alongside" and al["mode"] == "shrink":
        lo, hi = al["min"] // GiB, al["max"] // GiB
        v = ask(f"How many GB (gibibytes) for bromigOS, from {lo} to {hi}. {al['who']} keeps the rest", str(al["default"] // GiB),
                lambda v: None if v.isdigit() and lo <= int(v) <= hi else f"Type a number from {lo} to {hi}.")
        a["bromigos_bytes"] = int(v) * GiB
        say(f"{al['who']} keeps {plain_size(al['part_size'] + al['free_after'] - a['bromigos_bytes'])}.")
    elif a["mode"] == "erase" and d["partitions"]:
        say(f"Everything on this disk is deleted: {er['loses']}.")
    heading("user")
    a["full_name"] = ask("Your name (optional)", "", common.check_full_name)
    a["user"] = ask("User name, for signing in", common.suggest_username(a["full_name"]) or None, common.check_username)
    a["password"] = secret("Password")
    a["hostname"] = ask("The computer's name", common.suggest_hostname(a["user"], a["edition"]), common.check_hostname)
    heading("encryption")
    say(common.ENCRYPT_WORDS)
    a["encrypt"] = yes("Encrypt the disk?", True)
    if a["encrypt"]:
        a["separate_passphrase"] = not yes("Use your password to unlock the disk?", True)
        if a["separate_passphrase"]:
            a["passphrase"] = secret("Disk passphrase", "passphrase")
    if not ed.get("desktop", True):
        heading("ssh")
        say(common.SSH_WORDS)
        a["ssh"] = yes("Turn on SSH?", False)
        if a["ssh"]:
            say(common.SSH_KEY_WORDS)
            a["ssh_password"] = not yes("Keys only?", True)
            found = common.stick_keys()
            a["ssh_keys"] = []
            for name, key in found:
                if yes(f"Use the key in {name} from the USB stick's fieldkit folder?", True):
                    a["ssh_keys"].append(key)
            while not a["ssh_password"] and not a["ssh_keys"]:
                say("Keys only needs a key. Paste one line from your other computer's .pub file, or press Enter to "
                    "allow your password instead.")
                k = ask("Public key", "")
                if not k:
                    a["ssh_password"] = True
                elif common.check_key(k):
                    say(common.check_key(k))
                else:
                    a["ssh_keys"].append(k)
        say(common.FIREWALL_WORDS)
        a["firewall"] = yes("Turn on the firewall?", True)
        say(common.AUTO_UPDATE_WORDS)
        a["auto_updates"] = yes("Turn on automatic updates?", True)
    heading("summary")
    rows, warn = common.summary(a, d)
    for k, v in rows:
        say(f"{k}: {v}.")
    if warn:
        say(warn)
    if not yes("Erase the disk and install now?" if a["mode"] == "erase" else "Install now?", False):
        say("Nothing was changed. Start the installer again to begin anew.")
        return 1
    heading("install")
    last = [-10]

    def stage(pct, text):
        if pct - last[0] >= 10 or pct == 100:
            last[0] = pct
            say(f"{pct} percent. {text}.")

    result = {}

    def done(ok, err):
        result.update(ok=ok, err=err)
    inst = backend.Install(common.backend_answers(a, d), stage, lambda line: None, done).start()
    inst.thread.join()
    if not result.get("ok"):
        say("The install didn't finish. " + (result.get("err") or ""))
        return 1
    heading("done")
    say("Take out the USB stick when the screen goes dark." + (" Then type the disk's passphrase." if a["encrypt"] else ""))
    if yes("Restart now?", True):
        backend.reboot()
    return 0


if __name__ == "__main__":
    sys.exit(main())
