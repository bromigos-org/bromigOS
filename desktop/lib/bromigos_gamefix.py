"""What bromigOS keeps right for Steam by itself (package bromigos-desktop,
/usr/lib/bromigos/lib). `bromigos game maintain` runs it after `bromigos update` and each
time Steam exits; `bromigos game check` reports it and `--fix` applies it now
(docs/desktop.md, "Steam and Proton kept ready").

plan(root) works out what to change from Steam's own files and changes nothing;
apply(root, plan, log) makes the changes, only while Steam is closed (Steam writes its
config back when it exits and would undo them). Everything can be undone: config.vdf is
copied to ~/.local/state/bromigos/game/backup/<time>/ before it changes, and a runtime or
an old Proton is moved, not deleted, into its library's bromigos-backup/<time>/ folder.
Those folders go after KEEP_DAYS.

  mapping   a game set to a Proton that isn't installed any more follows the default again
            (its entry in CompatToolMapping is removed, as unticking "Force the use of a
            specific compatibility tool" does). One set to a GE-Proton or TKG build that's
            gone gets the newest GE-Proton instead, when the default isn't that already:
            the nearest to what it had, since those builds carry fixes Valve's lacks.
  default   the default for every game ("0") becomes the newest GE-Proton when it names a
            tool that isn't installed, is unset, or is an older GE-Proton. A choice of
            another tool that is here (Valve's Proton Experimental, proton_9, a TKG build)
            stays. With no GE-Proton here, a missing default becomes Proton Experimental,
            which Steam downloads itself.
  priority  the default's priority back to Steam's own 75.
  runtime   a broken Steam Linux Runtime is moved aside, so Steam reinstalls it on Play.
  prune     GE-Proton and TKG builds no game is set to are moved aside, keeping the newest
            GE-Proton and the newest one before it as a fallback. Only with a GE-Proton
            here, only folders directly in compatibilitytools.d, never a package's tools
            and never another kind of tool (Luxtorpeda, Boxtron).
"""
import os
import re
import shutil
import time

import bromigos_steam as S

KEEP_DAYS = 14
STAMP = re.compile(r"\d{8}-\d{6}")
CONFIG_PATH = ("InstallConfigStore", "Software", "Valve", "Steam")
FALLBACK_DEFAULT = "proton_experimental"


class SteamRunning(Exception):
    """Steam started while a change was due: nothing more was changed."""


def _newest_first(tools):
    return sorted((t for t in tools if S.ge_version(t.name)), key=lambda t: S.ge_version(t.name), reverse=True)


def plan(root, installed=None, tools=None):
    """What would change, as a dict (see the module's doc). Reads only."""
    installed = S.apps(root) if installed is None else installed
    tools = (S.custom_tools(root) + S.steam_tools(root, installed)) if tools is None else tools
    names = {t.name for t in tools}
    text, doc, block = S.compat_mapping(root)
    entries = S.mapping_entries(block)
    ges = _newest_first(tools)
    newest = ges[0].name if ges else None
    fallback = next((t.name for t in ges[1:] if S.ge_version(t.name) < S.ge_version(newest)), None)
    out = {"newest_ge": newest, "fallback_ge": fallback, "default": None, "priority": False,
           "mapping": [], "runtimes": [], "prune": [], "config": text is not None and doc is not None,
           "current_default": (entries.get("0") or {}).get("name") or None}

    def here(n):
        return bool(n) and (n in names or S.steam_own(n))

    target = cur = out["current_default"] or ""
    if out["config"]:
        if cur and here(cur) and not S.is_ge(cur):
            pass                                         # the user's choice of another tool
        elif cur in names and S.ge_version(cur):
            if newest and S.ge_version(cur) < S.ge_version(newest):
                target = newest
        elif not here(cur):
            target = newest or (FALLBACK_DEFAULT if cur else "")
        if target != cur:
            out["default"] = {"from": cur or None, "to": target}
        zero = entries.get("0")
        out["priority"] = bool(zero and zero["priority"] != S.DEFAULT_PRIORITY)
        for appid, e in sorted(entries.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            n = e["name"]
            if appid == "0" or not n or here(n):
                continue
            to = newest if (S.is_ge(n) or S.is_tkg(n)) and newest and target != newest else None
            app = installed.get(appid)
            out["mapping"].append({"appid": appid, "game": (app and app.name) or None, "from": n, "to": to})

    wanted = set(S.RUNTIMES) | {t.requires for t in tools if t.requires}
    for appid in sorted(wanted, key=int):
        app = installed.get(appid)
        if app and app.installed and not app.busy and S.runtime_problems(app):
            out["runtimes"].append(appid)

    if newest:
        gone = {m["from"] for m in out["mapping"] if not m["to"]}
        keep = ({newest, fallback, target} | {e["name"] for k, e in entries.items() if k != "0"}
                | {m["to"] for m in out["mapping"] if m["to"]}) - gone
        base = os.path.realpath(S.compat_dir(root))
        folders = {}
        for t in tools:
            if t.kind == "user":
                folders.setdefault(os.path.realpath(t.folder), []).append(t)
        for folder, ts in sorted(folders.items()):
            if os.path.dirname(folder) != base or os.path.islink(os.path.join(base, os.path.basename(folder))):
                continue
            if not all(S.is_ge(t.name) or S.is_tkg(t.name) for t in ts) or any(t.name in keep for t in ts):
                continue
            out["prune"].append({"name": ts[0].name, "display": ts[0].display, "folder": folder})
    return out


def changes(p):
    """Whether plan `p` has anything to do."""
    return bool(p["default"] or p["priority"] or p["mapping"] or p["runtimes"] or p["prune"])


def describe(p):
    """Plan `p` in plain words, a line per change."""
    lines = []
    for m in p["mapping"]:
        who = m["game"] or f"Game {m['appid']}"
        lines.append(f"{who} is set to {m['from']}, which isn't installed: " +
                     (f"set it to {m['to']}" if m["to"] else "it follows the default again"))
    if p["default"]:
        lines.append(f"The default Proton for every game: {p['default']['from'] or '(not set)'} → {p['default']['to']}")
    if p["priority"]:
        lines.append("The default's priority back to Steam's own 75")
    for appid in p["runtimes"]:
        lines.append(f"{S.RUNTIMES.get(appid, f'app {appid}')} is broken: move it aside so Steam reinstalls it")
    for t in p["prune"]:
        lines.append(f"{t['display']} isn't used by any game: move it aside")
    return lines


def _edit_config(text, p):
    """config.vdf's text with plan `p`'s mapping, default and priority changes."""
    new = text
    for m in p["mapping"]:
        block = S.parse(new).block(*CONFIG_PATH, "CompatToolMapping")
        e = block and block.entry(m["appid"])
        if e is None or not isinstance(e.value, S.Block) or e.value.get("name") != m["from"]:
            continue
        new = S.set_value(new, e.value, "name", m["to"]) if m["to"] else S.remove_entry(new, e)
    if p["default"] or p["priority"]:
        to = p["default"]["to"] if p["default"] else None
        steam = S.parse(new).block(*CONFIG_PATH)
        block = steam and steam.block("CompatToolMapping")
        zero = block and block.get("0")
        if steam is None:
            pass
        elif block is None:
            if to:
                new = S.add_block(new, steam, "CompatToolMapping",
                                  {"0": {"name": to, "config": "", "priority": S.DEFAULT_PRIORITY}})
        elif not isinstance(zero, S.Block):
            if to:
                new = S.add_block(new, block, "0", {"name": to, "config": "", "priority": S.DEFAULT_PRIORITY})
        else:
            if to:
                new = S.set_value(new, zero, "name", to)
            zero = S.parse(new).block(*CONFIG_PATH, "CompatToolMapping", "0")
            if zero.get("priority") != S.DEFAULT_PRIORITY:
                new = S.set_value(new, zero, "priority", S.DEFAULT_PRIORITY)
    S.parse(new)                                         # never write what doesn't read back
    return new


def _write_atomically(path, text):
    tmp = path + ".bromigos-new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    shutil.copymode(path, tmp)
    os.replace(tmp, path)


def apply(root, p, log=print):
    """Makes plan `p`'s changes; what was done, as lines (each also given to `log`).
    SteamRunning when Steam runs (before anything, or before the config is written)."""
    did = []

    def done(line):
        did.append(line)
        log(line)
    if S.steam_running():
        raise SteamRunning()
    if p["config"] and (p["mapping"] or p["default"] or p["priority"]):
        path = S.config_path(root)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        new = _edit_config(text, p)
        if new != text:
            if S.steam_running():
                raise SteamRunning()
            backup = S.backup_file(path)
            _write_atomically(path, new)
            for line in describe(dict(p, runtimes=[], prune=[])):
                done(line)
            done(f"Steam's config.vdf was backed up to {backup} first.")
    apps = S.apps(root)
    for appid in p["runtimes"]:
        app = apps.get(appid)
        if app is None:
            continue
        dest = S.move_aside(app.library, S.runtime_paths(app))
        if dest:
            done(f"Moved {app.name or appid} aside to {dest}: Steam reinstalls it when you next press Play.")
    for t in p["prune"]:
        if not os.path.isdir(t["folder"]):
            continue
        dest = S.move_aside(root, [os.path.relpath(t["folder"], root)])
        if dest:
            done(f"Moved {t['display']} aside to {dest}: no game uses it (deleted after {KEEP_DAYS} days).")
    for line in expire(root):
        done(line)
    return did


def expire(root, now=None):
    """Deletes bromigos-backup/<time> folders older than KEEP_DAYS in every library; what went."""
    now = time.time() if now is None else now
    gone = []
    for lib in S.libraries(root):
        d = os.path.join(lib, "bromigos-backup")
        try:
            stamps = os.listdir(d)
        except OSError:
            continue
        for name in stamps:
            if not STAMP.fullmatch(name):
                continue
            try:
                at = time.mktime(time.strptime(name, "%Y%m%d-%H%M%S"))
            except ValueError:
                continue
            if now - at > KEEP_DAYS * 86400:
                shutil.rmtree(os.path.join(d, name), ignore_errors=True)
                gone.append(f"Deleted the backup {os.path.join(d, name)} ({KEEP_DAYS} days old).")
    return gone


def readiness(doc):
    """`bromigos game check --json`'s document as Settings › Playing games says it:
    {ready, headline, detail, needs_you, handled, fixable, root, setup, proton}.
    needs_you: what only the person can do; handled: what bromigOS does by itself (or Fix
    does now; root: one of them needs the password)."""
    proton = doc.get("proton") or {}
    open_ = [f for f in doc.get("findings") or [] if f.get("level") in ("warn", "problem")]
    handled = [f for f in open_ if f.get("auto") or f.get("fixable") == "sddm"]
    needs = [f for f in open_ if f not in handled]
    out = {"ready": False, "needs_you": needs, "handled": handled, "setup": False,
           "proton": proton.get("display") or proton.get("default"),
           "fixable": bool(handled) or any(f.get("fixable") for f in needs),
           "root": any(f.get("fixable") == "sddm" for f in open_)}
    if not doc.get("steam_root"):
        if not doc.get("steam_installed"):
            return dict(out, headline="Steam isn't installed", setup=True,
                        detail="Set up Steam installs it, with the graphics drivers games need on this computer.")
        return dict(out, headline="Start Steam once",
                    detail="After its first start, bromigOS gets the newest GE-Proton and makes it the default.")
    n = len(needs)
    if n:
        headline = f"{n} thing{'s' if n != 1 else ''} need{'s' if n == 1 else ''} you"
    elif handled:
        headline = "Almost ready"
    else:
        headline = "Games are ready"
    if handled:
        detail = (f"bromigOS fixes {len(handled)} thing{'s' if len(handled) != 1 else ''} by itself " +
                  ("when Steam closes." if doc.get("steam_running") else "the next time Steam closes, or now with Fix."))
    elif n:
        detail = "Each one says what to do. Hover over it for more."
    else:
        detail = "Steam, Proton and the runtimes are in order. bromigOS keeps them that way by itself."
    return dict(out, ready=not open_, headline=headline, detail=detail)
