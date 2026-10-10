#!/usr/bin/env python3
"""The docs' generated sections, made from the code they describe so they can't drift.

  tools/docs/generate.py            rewrite every generated section
  tools/docs/generate.py --check    rewrite nothing; exit 1 naming each stale file (CI: docs.yml)

A generated section sits between two markers in a Markdown file and is replaced whole:

  <!-- generated:NAME (tools/docs/generate.py; don't edit by hand) -->
  …
  <!-- /generated:NAME -->

  commands  the `bromigos` built-ins (each one's --help) and the bromigos-<group>-<name>
            executables this repository ships (each one's header), as the router lists them
  keys      the default keybinds, read from desktop/hypr/ by the SHORTCUTS panel's own code
            (widgets/keybinds.py, widgets/keybinds-dump.lua) as a full install has them
  packages  the packages, from packaging/*/PKGBUILD

The manual's commands and keys are grouped by task and described in plain words from
tools/docs/manual-reference.toml; what the code has and that file doesn't is still listed,
under "Other keys" or "Other commands", with the code's own words.

Needs a built `bromigos` (--bromigos PATH; default core/target/{debug,release}/bromigos,
the newer), `lua` 5.4 or newer and bash. Runs from any directory.
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TAG = "tools/docs/generate.py; don't edit by hand"

# Where each section goes.
TARGETS = {
    "commands": ["manual/src/commands.md"],
    "keys": ["manual/src/keys.md"],
    "packages": ["docs/install.md", "manual/src/packages.md"],
}

# The manual's task groups and plain descriptions for the keys and the commands.
REFERENCE = REPO / "tools/docs/manual-reference.toml"

# The directories whose bromigos-* executables the packages install as commands.
COMMAND_DIRS = ["bin", "desktop/bin", "desktop/settings", "homelab/bin", "live/bin", "apps/bin", "widgets"]

# Packages built in another repository that the meta-package pulls in.
ELSEWHERE = {
    "bromigos-vector": ("VECTOR, the desktop's caretaker, and the hologram renderer he lives in",
                        "the `vector` repository"),
}


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, check=True, **kw).stdout


def reference(kind):
    """[{title, intro, rows: [{match|route, text}]}] for "keys" or "commands"."""
    with open(REFERENCE, "rb") as f:
        return tomllib.load(f).get(kind, [])


def grouped(items, groups, key, other):
    """items {key: row} placed in the reference's groups, in its order, each with its plain
    text; the rest under `other` with none. [(title, intro, [(row, text or None)])]. A
    reference row the code doesn't have (a key only some setups bind) is left out."""
    out, used = [], set()
    for g in groups:
        rows = []
        for r in g.get("rows", []):
            k = r[key]
            if k in items and k not in used:
                rows.append((items[k], r["text"]))
                used.add(k)
        if rows:
            out.append((g["title"], g.get("intro", ""), rows))
    rest = [(row, None) for k, row in items.items() if k not in used]
    if rest:
        out.append((other, "", rest))
    return out


# ------------------------------------------------------------------ commands


def builtins_help(bromigos, env):
    """[(name, summary, help text, [(sub, help text)])] in the CLI's own order."""
    top = run([bromigos, "commands", "--json"], env=env)
    out = []
    for b in json.loads(top)["builtins"]:
        name = b["name"]
        text = run([bromigos, "help", name], env=env).rstrip()
        subs = []
        for sub in _subcommands(text):
            subs.append((sub, run([bromigos, "help", name, sub], env=env).rstrip()))
        out.append((name, b["summary"], text, subs))
    return out


def _subcommands(help_text):
    m = re.search(r"^Commands:\n(.*?)(?:\n\n|\Z)", help_text, re.S | re.M)
    if not m:
        return []
    return [ln.split()[0] for ln in m.group(1).splitlines() if ln.strip() and ln.split()[0] != "help"]


def externals(bromigos, env):
    return [c for c in json.loads(run([bromigos, "commands", "--json"], env=env))["commands"]
            if not c["hidden"]]


def commands_section(bromigos):
    with tempfile.TemporaryDirectory() as tmp:
        lib, path, home = Path(tmp, "lib"), Path(tmp, "path"), Path(tmp, "home")
        for d in (lib, path, home):
            d.mkdir()
        for d in COMMAND_DIRS:
            for f in sorted((REPO / d).glob("bromigos-*")):
                if f.is_file():                          # as the package installs it: 0755
                    (lib / f.name).write_bytes(f.read_bytes())
                    (lib / f.name).chmod(0o755)
        # only this repository's commands: nothing installed, nobody's config
        env = {"HOME": str(home), "PATH": str(path), "BROMIGOS_LIB_BIN": str(lib),
               "BROMIGOS_SHARE_DIR": str(REPO), "LC_ALL": "C.UTF-8"}
        built = builtins_help(bromigos, env)
        ext = externals(bromigos, env)

    # One entry per route: a built-in, an executable, or both (a built-in that hands over to
    # the executable, as `bromigos live` does to bromigos-live).
    routes = {}
    for name, summary, text, subs in built:
        routes[name] = {"route": name, "summary": summary, "help": text, "subs": subs, "ext": None}
    for c in ext:
        route = c["route"].removeprefix("bromigos ")
        e = routes.setdefault(route, {"route": route, "summary": c["summary"] or "",
                                      "help": None, "subs": [], "ext": None})
        e["ext"] = c

    lines = ["## Commands by task", ""]
    for title, intro, rows in grouped(routes, reference("commands"), "route", "Other commands"):
        lines += [f"### {title}", ""]
        if intro:
            lines += [intro, ""]
        lines += ["| Command | What it does |", "|---|---|"]
        for e, text in rows:
            lines.append(f"| [`bromigos {e['route']}`](#{_anchor('bromigos ' + e['route'])}) "
                         f"| {_cell(text or html.escape(e['summary'], quote=False))} |")
        lines.append("")

    lines += ["## Every command in full", "",
              "Each command's own help, A to Z. Commands built into `bromigos` show their whole "
              "`--help`; the others show how to call them and an example or two, and their own "
              "`--help` says more.", ""]
    for route in sorted(routes):
        e = routes[route]
        lines += [f"### bromigos {route}", ""]
        if e["help"]:
            lines += ["```text", e["help"], "```", ""]
        c = e["ext"]
        if c:
            if not e["help"]:
                lines += [_sentence(c["summary"] or ""), ""]
            usage = f"bromigos {route}" + (f" {c['args']}" if c["args"] else "")
            lines += ["```text", usage.strip(), "```", ""]
            examples = [x.strip() for ex in c["examples"] for x in ex.split(";") if x.strip()]
            if examples:
                lines += ["For example:", "", "```text", *examples, "```", ""]
            lines += [f"From the `{_package_of(c['command'])}` package.", ""]
        for sub, sub_text in e["subs"]:
            lines += [f"#### bromigos {route} {sub}", "", "```text", sub_text, "```", ""]
    return "\n".join(lines)


def _anchor(heading):
    """The id mdBook gives a heading: lower case, spaces as hyphens, other punctuation gone."""
    return re.sub(r"[^a-z0-9 _-]", "", heading.lower()).replace(" ", "-")


def _sentence(text):
    """The code's summary as a sentence of Markdown (its <placeholders> as text, not HTML)."""
    text = html.escape(text.strip(), quote=False)
    return text[:1].upper() + text[1:] + ("" if text.endswith((".", "!", "?")) else ".") if text else ""


def _package_of(command):
    for d, pkg in (("bin", "bromigos-core"), ("desktop/bin", "bromigos-desktop"),
                   ("desktop/settings", "bromigos-desktop"),
                   ("homelab/bin", "bromigos-homelab"), ("live/bin", "bromigos-live"),
                   ("apps/bin", "bromigos-apps"), ("widgets", "bromigos-widgets")):
        if (REPO / d / command).exists():
            return pkg
    return "?"


def _cell(text):
    return text.replace("|", "\\|").replace("\n", " ")


# ------------------------------------------------------------------ keys

# Programs the defaults look for before binding to them, as a full install has them
# (bromigos-vector is in the meta-package; bromigos-desktop depends on swayosd).
ASSUME_INSTALLED = ["/usr/bin/bromigos-holo", "/usr/bin/swayosd-client", "/usr/bin/swayosd-server"]

DUMP_WRAPPER = r"""
local assume = {}
for p in (os.getenv("ASSUME") or ""):gmatch("[^:]+") do assume[p] = true end
-- only the programs above exist; nothing else on this machine is looked at
io.open = function(p) if assume[p] then return { close = function() end, read = function() end } end end
arg = { [0] = os.getenv("DUMP"), os.getenv("CONF") }
dofile(os.getenv("DUMP"))
"""


def keys_section():
    sys.path.insert(0, str(REPO / "widgets"))
    import keybinds as K

    with tempfile.TemporaryDirectory() as tmp:
        share = Path(tmp, "share", "default")
        share.mkdir(parents=True)
        (share / "hypr").symlink_to(REPO / "desktop" / "hypr")
        wrapper = Path(tmp, "dump.lua")
        wrapper.write_text(DUMP_WRAPPER)
        env = {"HOME": tmp, "PATH": os.environ.get("PATH", "/usr/bin"), "BROMIGOS_SHARE_DIR": str(Path(tmp, "share")),
               "DUMP": str(REPO / "widgets" / "keybinds-dump.lua"),
               "CONF": str(REPO / "desktop" / "hypr" / "hyprland.lua"),
               "ASSUME": ":".join(ASSUME_INSTALLED)}
        dump = run(["lua", str(wrapper)], env=env)
        binds = K._parse_dump(dump)
        if not binds:
            sys.exit("generate: no keybinds read from desktop/hypr/hyprland.lua")
        K._hypr_binds = lambda: binds
        K._peripherals = lambda: {}                    # no peripheral module of anyone's
        K._yours = lambda: {}                          # nor anyone's own shortcuts (bromigos keys)
        home = os.environ.get("HOME")
        os.environ["HOME"] = tmp                       # no hardware module of anyone's
        try:
            rows = K.shortcuts()
        finally:
            if home is not None:
                os.environ["HOME"] = home

    # each bind by the SHORTCUTS panel's description, a second key for it ("(also …)") apart
    items = {}
    for s, keys, desc, _ in rows:
        also = None
        if m := ALSO.search(desc):
            desc, also = desc[:m.start()], m.group(1).split("+")
        items[desc if desc not in items else f"{desc} ({s})"] = (keys, desc, also)

    lines = []
    for title, intro, group in grouped(items, reference("keys"), "match", "Other keys"):
        lines += [f"### {title}", ""]
        if intro:
            lines += [intro, ""]
        lines += ["| Keys | What it does |", "|---|---|"]
        for (keys, desc, also), text in group:
            caps = _keys(keys) + (" or " + _keys(also) if also else "")
            lines.append(f"| {caps} | {_cell(text or html.escape(desc, quote=False))} |")
        lines.append("")
    return "\n".join(lines)


ALSO = re.compile(r" \(also ([^)]*)\)$")

# How the keycaps read in the manual (the panel's own names are upper case: SUPER, VOL+).
KEYCAPS = {"SUPER": "Super", "ALT": "Alt", "SHIFT": "Shift", "CTRL": "Ctrl", "SPACE": "Space",
           "ENTER": "Enter", "ESC": "Esc", "TAB": "Tab", "VOL+": "Volume up",
           "VOL−": "Volume down", "MUTE": "Mute", "MIC": "Mic mute", "BRI+": "Brightness up",
           "BRI−": "Brightness down", "PLAY": "Play", "PREV": "Previous", "NEXT": "Next",
           "LMB DRAG": "left-drag", "RMB DRAG": "right-drag"}


def _keys(keys):
    """One key combination, kept on one line (manual/manual.css: .keys)."""
    return f'<span class="keys">{_kbd(keys)}</span>'


def _kbd(keys):
    out = []
    for k in (k.strip() for k in keys):
        if m := re.fullmatch(r"(\w)–(\w)", k):                       # a range: 1–0
            out.append(f"<kbd>{m.group(1)}</kbd> to <kbd>{m.group(2)}</kbd>")
        elif k.endswith("DRAG"):                                    # a mouse drag, not a key
            out.append(KEYCAPS.get(k, k.lower()))
        else:
            out.append(f"<kbd>{html.escape(KEYCAPS.get(k, k))}</kbd>")
    return "+".join(out)


# ------------------------------------------------------------------ packages


def pkgbuild(path):
    script = ('source "$1" >/dev/null 2>&1; printf "%s\\0%s\\0" "$pkgname" "$pkgdesc"; '
              'printf "%s " "${depends[@]}"; printf "\\0"; printf "%s\\n" "${optdepends[@]}"')
    name, desc, deps, opt = run(["bash", "-c", script, "pkgbuild", str(path)],
                                cwd=path.parent, env={"startdir": str(path.parent), "PATH": "/usr/bin:/bin"}).split("\0")
    return {"name": name, "desc": desc, "depends": deps.split(),
            "optdepends": {ln.split(":", 1)[0].strip(): ln.split(":", 1)[1].strip() if ":" in ln else ""
                           for ln in opt.splitlines() if ln.strip()}}


# optional to the meta-package, but `bromigos install` installs them itself unless told not to
BY_INSTALL = {
    "paru": "by `bromigos install` (its `aur` step), unless `--no-aur` or `bromigos setup aur` "
            "leaves it out",
}


def packages_section():
    pkgs = {p["name"]: p for p in (pkgbuild(f) for f in sorted(REPO.glob("packaging/*/PKGBUILD")))}
    meta = pkgs["bromigos"]
    ours = set(pkgs) | set(ELSEWHERE)
    order, how = ["bromigos"], {"bromigos": "the one to install: everything below marked *with bromigOS*"}

    queue = [(d, "*with bromigOS*") for d in meta["depends"]]   # breadth first: the meta's own first
    while queue:
        name, via = queue.pop(0)
        if name in how or name not in ours:
            continue
        order.append(name)
        how[name] = via
        queue += [(d, f"*with bromigOS* (through `{name}`)") for d in pkgs.get(name, {}).get("depends", [])]
    for d in meta["optdepends"]:
        if d in ours and d not in how:
            order.append(d)
            how[d] = BY_INSTALL.get(d, f"optional: `bromigos install --with {d}`")
    for d in sorted(ours - set(order)):
        order.append(d)
        needs = sorted(p["name"] for p in pkgs.values() if d in p["depends"])
        wants = sorted(p["name"] for p in pkgs.values() if d in p["optdepends"])
        how[d] = ("with " + ", ".join(f"`{u}`" for u in needs) if needs
                  else "optional, for " + ", ".join(f"`{u}`" for u in wants) if wants
                  else "on its own")

    lines = ["| Package | What it is | Installed |", "|---|---|---|"]
    for n in order:
        desc = pkgs[n]["desc"] if n in pkgs else ELSEWHERE[n][0] + f" (from {ELSEWHERE[n][1]})"
        lines.append(f"| `{n}` | {_cell(desc)} | {how[n]} |")
    lines += ["", "`herdr`, `ttf-geist-mono`, `1password` and `paru` aren't in Arch's own repositories, "
              "so bromigOS packages them into its own, each pinned by checksum. Only `1password` "
              "needs the AUR, and only on a public install (below).", "",
              "- `herdr` and `paru` are built from their upstream source.",
              "- `ttf-geist-mono` packages the fonts from Geist's release.",
              "- `1password` repackages 1Password's own Linux download. It isn't built from source. "
              "Its licence is proprietary, so the public mirror leaves it out: there, "
              "`bromigos install --with 1password` gets it from the AUR with paru.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------ the files


def splice(text, name, body, path):
    start = re.compile(rf"^<!-- generated:{name}\b[^>]*-->\n", re.M)
    end = f"<!-- /generated:{name} -->"
    m = start.search(text)
    if not m or end not in text[m.end():]:
        sys.exit(f"generate: {path} has no <!-- generated:{name} --> … {end} markers")
    tail = text.index(end, m.end())
    return text[:m.start()] + f"<!-- generated:{name} ({TAG}) -->\n\n" + body.strip("\n") + "\n\n" + text[tail:]


def default_bromigos():
    found = [p for p in (REPO / "core/target/debug/bromigos", REPO / "core/target/release/bromigos") if p.exists()]
    return str(max(found, key=lambda p: p.stat().st_mtime)) if found else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="change nothing; exit 1 when a section is stale")
    ap.add_argument("--bromigos", default=default_bromigos(), help="the built bromigos binary")
    ap.add_argument("only", nargs="*", metavar="SECTION", help=f"just these: {', '.join(TARGETS)}")
    a = ap.parse_args()
    if unknown := set(a.only) - set(TARGETS):
        ap.error(f"no section {', '.join(sorted(unknown))}")
    if not a.bromigos and (not a.only or "commands" in a.only):
        sys.exit("generate: no built bromigos (cargo build -p bromigos in core/, or --bromigos PATH)")
    makers = {"commands": lambda: commands_section(a.bromigos), "keys": keys_section,
              "packages": packages_section}
    stale = []
    for name in a.only or TARGETS:
        body = makers[name]()
        for rel in TARGETS[name]:
            path = REPO / rel
            old = path.read_text()
            new = splice(old, name, body, rel)
            if new != old:
                stale.append(f"{rel} ({name})")
                if not a.check:
                    path.write_text(new)
    if a.check and stale:
        print("The docs' generated sections are stale:", *stale, sep="\n  ", file=sys.stderr)
        print("Run tools/docs/generate.py (after cargo build -p bromigos in core/) and commit the result.",
              file=sys.stderr)
        return 1
    for s in stale:
        print(f"generate: updated {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
