"""`bromigos lab apps`: the apps this server runs, from the provisioning catalogue
(docs/lab.md, "Apps on a Server"; the engine underneath is localprovision.py).

    bromigos lab apps [list] [--all] [--json]   each app: its state, what it uses, its page
    bromigos lab apps show ID [--json]          one app in full: units, data, health check, keys
    bromigos lab apps add ID… [--plan] [--set ITEM.FIELD=VALUE] [--json]
    bromigos lab apps remove ID [--delete-data [--yes]] [--plan] [--json]
    bromigos lab apps restart ID [--json]
    bromigos lab apps logs ID [-f] [-n N] [--json]
    bromigos lab apps budget [ID…] [--json]     what the installed apps (and these) ask of the server

What the server is meant to run is /etc/bromigos/lab/apps.toml, the desired state. It is
seeded once, from the install answers and what the engine's own record says was set up, and
`add` and `remove` change it. What each app reports comes from the machine, never from a
guess: its state from the service manager, whether it answers from the recipe's `health`,
memory from its units' cgroups, disk from its `[[item.data]]` folders.

`add` and `remove` are activity jobs (`bromigos activity`, docs/activity.md): each runs in a
unit of its own with named steps, and holds the lock `apps`, so two app jobs queue. `remove`
keeps the app's data unless `--delete-data` is given.

`list --json` is a JSON array with one tile per catalogue item, in the Lab board's tile
contract. Tests replace the machine (Machine: run, http, clock) and use a stand-in root.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import sys
import time
import tomllib
import urllib.error
import urllib.request

from . import localprovision as L, provcatalog as PC

SCHEMA = 1
DESIRED = "etc/bromigos/lab/apps.toml"
MEASURED = "run/bromigos/lab/apps-measured.json"     # the data folders' sizes, 0644: no secrets
MEASURE_MAX_AGE_MS = 600_000                          # a folder is walked again after ten minutes
# a bromigOS Server, or a machine the local target set up: where lab deploy|restart|logs are apps verbs
SERVER_MARKERS = ("etc/bromigos/server.toml", "usr/lib/bromigos/server/bromigos-server", L.STATE)
# Items set up by a step that can leave: the step installs a package and starts its service,
# and nothing else on the system leans on it. Other steps change more (DNS, the cluster, the
# front door, the secret store), and removing them isn't built yet.
REMOVE_STEPS = ("passwords", "file-sync", "smb")
LOCK = "apps"
HEALTH_WAIT_S = 60          # how long a new app may take to answer, when its recipe gives no within_s
HEALTH_TIMEOUT_S = 3.0
WORDS = {"ok": "Running", "starting": "Starting", "updating": "Updating", "degraded": "Degraded", "down": "Down",
         "unknown": "Unknown"}
SET_UP = "Set up"           # an item with no service of its own (a folder, a setting) that was set up
MARKS = {"ok": "●", "starting": "◐", "updating": "◐", "degraded": "◆", "down": "✖", "unknown": "◌"}
NEVER_TOUCHED = ["the media library (/srv/media)", "shared folders", "other apps' data"]
TAG_NOT_A_VERSION = ("latest", "main", "stable", "nightly", "edge", "release")
EXIT_PROBLEM, EXIT_USAGE, EXIT_REFUSED, EXIT_UNCHECKED = 1, 2, 3, 4


class AppsError(Exception):
    """Said as it is, in plain words; `code` is the exit status."""

    def __init__(self, words, code=EXIT_REFUSED):
        super().__init__(words)
        self.code = code


# ---------------------------------------------------------------- the machine
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):            # the first answer is the one that counts
        return None


def http_status(url, timeout=HEALTH_TIMEOUT_S):
    """The status of the first answer to a GET, with nothing signed in, no redirect followed and
    no proxy; None when nothing answers."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _exec(argv):
    try:
        os.execv(argv[0], argv)
    except OSError as e:
        raise AppsError(f"couldn't start {argv[0]}: {e.strerror or e}", EXIT_PROBLEM) from None


class Machine:
    """What these commands read and run: files under a root, commands, local HTTP, the clock.
    Tests give a stand-in root, run (provfake.FakeMachine), http and clock."""

    def __init__(self, root=None, run=None, hostname=None, http=None, clock=None, sleep=None, euid=None, hw=None,
                 start=None, environ=None):
        self.root = root or L.ROOT
        # under a stand-in root nothing is asked of the machine the tests run on: no command runs
        self.run = run or (L.run if self.root == "/" else (lambda argv, *a, **kw: (127, "", "a stand-in root")))
        self.hostname = hostname or socket.gethostname().split(".")[0]
        self.http = http or http_status
        self.clock = clock or (lambda: int(time.time() * 1000))
        self.sleep = sleep or time.sleep
        self.euid = os.geteuid() if euid is None else euid
        self._hw = hw
        self.start = start or _exec                   # replaces this process with a command (a job's start)
        self.environ = os.environ if environ is None else environ

    @property
    def stand_in(self):
        return self.root != "/"

    def path(self, rel):
        return Path(L.at(rel, self.root))

    def hw(self):
        if self._hw is None:
            self._hw = L.detect(self.root)
        return self._hw

    def may_change(self):
        return self.stand_in or self.euid == 0

    def in_job(self):
        return bool(self.environ.get("BROMIGOS_ACTIVITY_JOB"))


def is_server(root=None):
    """A bromigOS Server, or a machine `bromigos lab provision --local` has set up."""
    return any(os.path.exists(L.at(p, root)) for p in SERVER_MARKERS)


# ---------------------------------------------------------------- the desired state: apps.toml
def _order(ids, cat):
    keys = list(cat)
    return sorted(dict.fromkeys(i for i in ids if i in cat), key=keys.index)


def _blank():
    return {"format": 1, "seeded_from": "", "lab": "none", "roles": [], "apps": [], "models": None, "settings": {}}


def _normal(doc, cat):
    d = _blank()
    d["seeded_from"] = str(doc.get("seeded_from") or "")
    d["lab"] = doc.get("lab") if doc.get("lab") in PC.LABS else "none"
    d["roles"] = [str(r) for r in doc.get("roles") or []]
    d["apps"] = _order([str(i) for i in doc.get("apps") or []], cat)
    d["models"] = [str(x) for x in doc["models"]] if isinstance(doc.get("models"), list) else None
    d["settings"] = {str(k): dict(v) for k, v in (doc.get("settings") or {}).items() if isinstance(v, dict)}
    return d


def engine_record(m):
    """The engine's own record (provision-local.json): {items: {id: {state, fingerprint, …}}}."""
    try:
        doc = json.loads(m.path(L.STATE).read_text())
        return doc if isinstance(doc.get("items"), dict) else {"items": {}}
    except (OSError, ValueError, AttributeError):
        return {"items": {}}


def seed(m, cat):
    """The desired state for a server that has none yet: what was chosen at install (the answer
    file's selection with what it needs, or what its roles tick), and anything the engine's
    record shows was set up since."""
    d = _blank()
    ids = []
    answers = m.path(L.ANSWERS)
    if answers.exists():
        try:
            a = L.read_answers(answers)
        except L.ProvisionError:
            a = None
        if a:
            d.update(seeded_from=L.ANSWERS, lab=a["lab"], roles=list(a["roles"]), models=a["models"],
                     settings={k: dict(v) for k, v in a["settings"].items() if k in cat})
            try:
                if a["provision"] is not None:
                    ids = PC.resolve([i for i in a["provision"] if i in cat])[0]
                else:
                    ids = PC.recommend(a["roles"] or ["base"], m.hw(), a["lab"])
            except PC.CatalogueError:
                ids = []
    done = [i for i, r in engine_record(m)["items"].items() if isinstance(r, dict) and r.get("state") == "done"]
    if done and not d["seeded_from"]:
        d["seeded_from"] = "/" + L.STATE
    d["apps"] = _order(ids + done, cat)
    return d


def desired(m, cat=None, write=False):
    """apps.toml as a dict; seeded when there is none (and written, when `write` and allowed)."""
    cat = cat or PC.by_id()
    p = m.path(DESIRED)
    try:
        doc = tomllib.loads(p.read_text())
    except FileNotFoundError:
        d = seed(m, cat)
        if write and m.may_change():
            save_desired(m, d)
        return d
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise AppsError(f"/{DESIRED} can't be read ({e}). Fix or remove it: it is seeded again when it's gone",
                        EXIT_UNCHECKED) from None
    return _normal(doc, cat)


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k)


def _toml(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_toml_key(str(k))} = {_toml(x)}" for k, x in v.items()) + " }"
    raise AppsError(f"a setting can't be {v!r}", EXIT_USAGE)


def desired_text(d):
    out = ["# What this server is meant to run: bromigos lab apps (docs/lab.md, \"Apps on a Server\").",
           "# `bromigos lab apps add` and `remove` change it. A secret setting is a reference to the",
           "# secret store ({ secret = \"local:ITEM/FIELD\" }), never the value.",
           "format = 1"]
    if d["seeded_from"]:
        out.append(f"seeded_from = {_toml(d['seeded_from'])}")
    out += [f"lab = {_toml(d['lab'])}", f"roles = {_toml(d['roles'])}", f"apps = {_toml(d['apps'])}"]
    if d["models"] is not None:
        out.append(f"models = {_toml(d['models'])}")
    for item, fields in sorted(d["settings"].items()):
        if fields:
            out += ["", f"[settings.{_toml_key(item)}]"] + [f"{_toml_key(k)} = {_toml(v)}" for k, v in fields.items()]
    return "\n".join(out) + "\n"


def save_desired(m, d):
    p = m.path(DESIRED)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".new")
    tmp.write_text(desired_text(d))
    os.chmod(tmp, 0o644)
    os.replace(tmp, p)


def note_applied(ids, root=None):
    """`provision --local --apply` set these up: the desired state has them too."""
    m = Machine(root=root)
    if not m.may_change():
        return
    cat = PC.by_id()
    d = desired(m, cat)
    d["apps"] = _order(d["apps"] + list(ids), cat)
    save_desired(m, d)


# ---------------------------------------------------------------- reading the machine
SHOW = ("Id", "LoadState", "ActiveState", "SubState", "ActiveEnterTimestamp", "ControlGroup")


def unit_states(m, units):
    """{unit: {load, active, sub, since (ms or None), cgroup}} from one `systemctl show`; None
    when the service manager doesn't answer."""
    units = list(dict.fromkeys(units))
    if not units:
        return {}
    rc, out, _ = m.run(["systemctl", "show", "--timestamp=unix", "-p", ",".join(SHOW), "--", *units])
    blocks = [b for b in (out or "").strip().split("\n\n") if b.strip()]
    if rc != 0 and not blocks or rc == 127:
        return None
    rows = {}
    for n, block in enumerate(blocks):
        f = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        name = f.get("Id") or (units[n] if n < len(units) else None)
        if not name:
            continue
        ts = f.get("ActiveEnterTimestamp") or ""
        since = int(ts[1:]) * 1000 if re.fullmatch(r"@\d+", ts) and ts != "@0" else None
        rows[name] = {"load": f.get("LoadState") or "", "active": f.get("ActiveState") or "", "sub": f.get("SubState") or "",
                      "since": since, "cgroup": f.get("ControlGroup") or ""}
    for u in units:
        rows.setdefault(u, {"load": "", "active": "", "sub": "", "since": None, "cgroup": ""})
    return rows


def cgroup_memory(m, cgroup):
    """Bytes the unit's cgroup holds now (memory.current, which counts its containers too)."""
    if not cgroup or not cgroup.startswith("/") or ".." in cgroup.split("/"):
        return None
    try:
        return int(m.path("sys/fs/cgroup" + cgroup + "/memory.current").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def tree_bytes(path):
    """Bytes a folder uses on its own disk, as du counts them (each hard-linked file once); 0
    when it isn't there; None when any part of it can't be read: never a part counted as the
    whole."""
    try:
        top = os.lstat(path)
    except FileNotFoundError:
        return 0
    except OSError:
        return None
    total, seen, todo = top.st_blocks * 512, set(), [path] if stat.S_ISDIR(top.st_mode) else []
    while todo:
        d = todo.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    st = e.stat(follow_symlinks=False)
                    if st.st_dev != top.st_dev:
                        continue
                    if st.st_nlink > 1 and not stat.S_ISDIR(st.st_mode):
                        if (st.st_dev, st.st_ino) in seen:
                            continue
                        seen.add((st.st_dev, st.st_ino))
                    total += st.st_blocks * 512
                    if stat.S_ISDIR(st.st_mode):
                        todo.append(e.path)
        except OSError:
            return None
    return total


class Sizes:
    """The data folders' sizes, walked at most every ten minutes. Root keeps them in /run so
    the board's reader and a person without root see the same numbers."""

    def __init__(self, m):
        self.m = m
        self.p = m.path(MEASURED)
        try:
            self.doc = json.loads(self.p.read_text())
            if not isinstance(self.doc, dict):
                self.doc = {}
        except (OSError, ValueError):
            self.doc = {}
        self.dirty = False

    def get(self, path):
        now = self.m.clock()
        hit = self.doc.get(path)
        if isinstance(hit, list) and len(hit) == 2 and isinstance(hit[1], int) and now - hit[1] < MEASURE_MAX_AGE_MS:
            return hit[0]
        n = tree_bytes(str(self.m.path(path)))
        if n is not None or hit is None:
            self.doc[path] = [n, now]
            self.dirty = True
        return n

    def forget(self, ids):
        """Walk these apps' folders again next time: they were just set up, removed or deleted."""
        for k in list(self.doc):
            if any(k == f"/{L.APPS}/{i}" or k.startswith(f"/{L.APPS}/{i}/") for i in ids):
                del self.doc[k]
                self.dirty = True
        self.save()

    def save(self):
        if not self.dirty or not self.m.may_change():
            return
        try:
            self.p.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.p.with_name(self.p.name + ".new")
            tmp.write_text(json.dumps(self.doc, sort_keys=True))
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.p)
        except OSError:
            pass


def health(m, it, timeout=HEALTH_TIMEOUT_S):
    """Ask the app, the recipe's way: {ok, ms, how, status}; None when the recipe has no check."""
    h = it.get("health")
    if not h:
        return None
    t0 = time.monotonic()
    if "http" in h:
        url = f"http://127.0.0.1:{h['port']}{h['http']}"
        code = m.http(url, timeout)
        expect = h.get("expect", 200)
        ok = code in (expect if isinstance(expect, list) else [expect])
        how, status = f"GET {url}", code
    else:
        rc, _, _ = m.run(list(h["cmd"]), timeout=max(timeout, 10))
        ok, how, status = rc == 0, " ".join(h["cmd"]), rc
    return {"ok": bool(ok), "ms": int((time.monotonic() - t0) * 1000), "how": how, "status": status, "at": m.clock()}


def running_jobs(m):
    """Activity jobs still going for an app: {app id: kind}."""
    try:
        import bromigos_activity as A
    except ImportError:
        return {}
    try:
        env = A.Env(dict(m.environ, BROMIGOS_ROOT=m.root) if m.stand_in else m.environ)
        jobs = A.list_jobs(env, states=[s for s in A.STATES if s not in A.FINAL])
    except Exception:                                   # noqa: BLE001  no records to read: none running
        return {}
    out = {}
    for r in jobs:
        s = r.get("subject") or {}
        if s.get("type") == "app" and s.get("id"):
            out.setdefault(s["id"], r.get("kind") or "")
    return out


# ---------------------------------------------------------------- one item, as a tile
def packages_of(it):
    inst = it["install"]
    if "pacman" in inst:
        return list(inst["pacman"])
    if "step" in inst:
        return list(L.STEP_PACKAGES.get(inst["step"], []))
    return []


def image_tag(it):
    """The tag the item's first image is pinned at, when it names a version."""
    ref = next(iter(it["images"].values()), "")
    last = ref.split("@")[0].rsplit("/", 1)[-1]
    if ":" not in last:
        return None
    tag = last.rsplit(":", 1)[1]
    return None if tag.lower() in TAG_NOT_A_VERSION else tag


def package_version(run, pkg):
    rc, out, _ = run(["pacman", "-Q", pkg])
    parts = (out or "").split()
    return parts[1] if rc == 0 and len(parts) > 1 else None


def app_version(it, run):
    """What people see as the version, for the engine's record at install."""
    if it.get("app_version"):
        return it["app_version"]
    pkgs = packages_of(it)
    if pkgs:
        return package_version(run, pkgs[0])
    return image_tag(it)


def version(m, it, record, installed):
    if it.get("app_version"):
        return it["app_version"]
    pkgs = packages_of(it)
    if installed and pkgs:                               # packages update with the system: ask pacman
        return package_version(m.run, pkgs[0])
    if installed and (record or {}).get("app_version"):
        return record["app_version"]
    return image_tag(it)


def removable(it):
    inst = it["install"]
    return "quadlet" in inst or "pacman" in inst or inst.get("step") in REMOVE_STEPS


def cant_remove(it):
    if removable(it):
        return None
    return (f"{it['name']} is set up by a step that changes more than its own service, and removing it "
            "isn't built yet (docs/lab.md, \"Apps on a Server\").")


def needed_by(cat, installed, i):
    """The installed apps that can't run without i: an "a|b" need met by another counts as met."""
    out = []
    for j in installed:
        if j == i or j not in cat:
            continue
        for need in cat[j]["needs"]:
            alts = PC.alternatives(need)
            if i in alts and not any(a != i and a in installed for a in alts):
                out.append(j)
                break
    return out


def open_link(m, it, installed):
    """The app's page: its own name through Caddy when Caddy runs here, else its port."""
    web = it.get("web") or {}
    if not web.get("port"):
        return None
    path = web.get("path", "")
    if web.get("name") and "caddy" in installed:
        return {"url": f"https://{web['name']}-{m.hostname}.local{path}", "port": web["port"]}
    return {"url": f"http://{m.hostname}.local:{web['port']}{path}", "port": web["port"]}


def judge(it, units, rows, check, job, now, record):
    """(state, word, since) from the service manager, the health check and the jobs running."""
    if rows is None:
        return "unknown", WORDS["unknown"], None
    if not units:
        if (record or {}).get("state") == "failed":
            return "down", WORDS["down"], None
        return "ok", SET_UP, None
    rs = [rows[u] for u in units]
    since = max((r["since"] for r in rs if r["since"]), default=None)
    if job:
        state = "updating" if job.startswith("app.update") or job.startswith("app.rollback") else "starting"
        return state, WORDS[state], since
    if any(r["load"] == "not-found" for r in rs) and not any(r["active"] == "active" for r in rs):
        return "down", WORDS["down"], None
    active = [r["active"] == "active" for r in rs]
    if all(active):
        if check and not check["ok"]:
            within = (it.get("health") or {}).get("within_s") or HEALTH_WAIT_S
            if since and now - since < within * 1000:
                return "starting", WORDS["starting"], since
            return "degraded", WORDS["degraded"], since
        return "ok", WORDS["ok"], since
    if any(r["active"] in ("activating", "reloading") for r in rs) and not any(r["active"] == "failed" for r in rs):
        return "starting", WORDS["starting"], since
    if any(active):
        return "degraded", WORDS["degraded"], since
    if not any(r["active"] for r in rs):
        return "unknown", WORDS["unknown"], None
    return "down", WORDS["down"], None


class View:
    """Everything the tiles read, gathered once: the desired state, the engine's record, the
    units, the checks, the jobs, the sizes."""

    def __init__(self, m, cat=None, checks=True):
        self.m = m
        self.cat = cat or PC.by_id()
        self.d = desired(m, self.cat)
        self.installed = self.d["apps"]
        self.record = engine_record(m)["items"]
        self.units = {i: L.services_of(self.cat[i]) for i in self.installed}
        self.rows = unit_states(m, [u for i in self.installed for u in self.units[i]])
        self.jobs = running_jobs(m)
        self.sizes = Sizes(m)
        self.checks = {}
        if checks and self.rows is not None:
            ask = [i for i in self.installed if self.cat[i].get("health") and self.units[i]
                   and all(self.rows[u]["active"] == "active" for u in self.units[i])]
            if ask:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(ask))) as pool:
                    for i, res in zip(ask, pool.map(lambda x: health(m, self.cat[x]), ask)):
                        self.checks[i] = res

    def data(self, it):
        """[(row, whole path, bytes or None)] for its [[item.data]]."""
        return [(d, d["path"], self.sizes.get(d["path"])) for d in L.data_paths(it)]

    def measured(self, it):
        units = self.units.get(it["id"]) or []
        mems = [cgroup_memory(self.m, self.rows[u]["cgroup"]) for u in units] if self.rows else []
        known = [x for x in mems if x is not None]
        ram = sum(known) if known and len(known) == len(mems) else None
        rows = self.data(it)
        disk = None
        if rows and all(n is not None for _, _, n in rows):
            disk = sum(n for _, _, n in rows)
        return {"ram_bytes": ram, "disk_bytes": disk}

    def tile(self, it):
        i = it["id"]
        on = i in self.installed
        rec = self.record.get(i) if isinstance(self.record.get(i), dict) else None
        req = it["requires"] or {}
        recipe = ((rec or {}).get("recipe") if on else None) or it["version"]
        t = {"id": i, "job": it.get("job") or it["name"], "app": it.get("app") or "", "holo": it.get("holo") or "",
             "group": it["group"], "installed": on, "version": version(self.m, it, rec, on), "recipe": recipe,
             "household": None, "state": None, "state_word": None, "since": None, "reading": None,
             "open": None, "update": None, "measured": None,
             "requires": {"cpu": req.get("cpu", 0), "ram_gb": req.get("ram_gb", 0), "disk_gb": req.get("disk_gb", 0)},
             "can": ["add"], "needed_by": []}
        if not on:
            return t
        units = self.units[i]
        t["state"], t["state_word"], t["since"] = judge(it, units, self.rows, self.checks.get(i), self.jobs.get(i),
                                                        self.m.clock(), rec)
        t["open"] = open_link(self.m, it, self.installed)
        t["measured"] = self.measured(it)
        t["needed_by"] = needed_by(self.cat, self.installed, i)
        t["can"] = ((["open"] if t["open"] else []) + (["restart", "logs"] if units else [])
                    + (["remove"] if removable(it) and not t["needed_by"] else []))
        return t

    def tiles(self, ids=None):
        out = [self.tile(it) for it in self.cat.values() if ids is None or it["id"] in ids]
        self.sizes.save()
        return out


# ---------------------------------------------------------------- the budget
def budget_doc(m, ids=(), view=None):
    """The meter: what the installed apps' recipes ask for, plus what's picked (with what it
    needs), against this server; and what the installed apps use now, measured."""
    v = view or View(m, checks=False)
    try:
        wanted, _ = PC.resolve(list(v.installed) + list(ids))
    except PC.CatalogueError as e:
        raise AppsError(str(e)) from None
    picked = [i for i in wanted if i not in v.installed]
    b = PC.budget(picked, m.hw(), installed=v.installed)
    ms = [v.measured(v.cat[i]) for i in v.installed]
    total = {}
    for k in ("ram_bytes", "disk_bytes"):
        known = [x[k] for x in ms if x[k] is not None]
        total[k] = sum(known) if known else None
        total[k.replace("bytes", "apps")] = len(known)
    v.sizes.save()
    b["measured"] = total
    b["hardware"] = {k: m.hw().get(k) for k in ("cpu", "ram_gb", "disk_gb", "gpu", "gpu_vram_gb")}
    return b


# ---------------------------------------------------------------- the jobs: add and remove
def plan_for(m, d, ids, settings):
    try:
        return L.build_plan(list(ids), d["roles"], d["lab"], None, d["models"], settings, m.hw())
    except L.ProvisionError as e:
        raise AppsError(str(e)) from None


def merge_settings(d, sets):
    out = {k: dict(v) for k, v in d["settings"].items()}
    for s in sets or ():
        key, eq, value = s.partition("=")
        item, _, field = key.partition(".")
        if not eq or not item or not field:
            raise AppsError(f"--set ITEM.FIELD=VALUE, not {s!r}", EXIT_USAGE)
        out.setdefault(item, {})[field] = {"true": True, "false": False}.get(value, int(value) if value.isdigit() else value)
    return out


def step(emit, sid, state, words=""):
    emit(f"::step {sid} {state}" + (f" {words}" if words else ""))


def _names(cat, ids):
    jobs = [cat[i].get("job") or cat[i]["name"] for i in ids]
    return jobs[0] if len(jobs) == 1 else ", ".join(jobs[:-1]) + " and " + jobs[-1]


def wait_answers(m, it, emit):
    """Ask a new app the recipe's way until it answers, or its time is up."""
    h = it.get("health")
    if not h:
        return True
    within = h.get("within_s") or HEALTH_WAIT_S
    start = m.clock()
    while True:
        r = health(m, it)
        if r["ok"]:
            return True
        if m.clock() - start >= within * 1000:
            emit(f"::error answers {it.get('job') or it['name']} is set up, but it doesn't answer ({r['how']}: "
                 f"{r['status'] if r['status'] is not None else 'no answer'}) after {within} s. "
                 f"bromigos lab apps logs {it['id']} shows why.")
            return False
        m.sleep(2)


def do_add(m, ids, sets, emit=None, host_kw=None):
    """The job's own work: the engine applies the desired set with these added; then the
    desired state is saved and each new app is asked whether it answers."""
    emit = emit or (lambda line: print(line, flush=True))
    cat = PC.by_id()
    step(emit, "plan", "running", f"Checking what {_names(cat, ids)} needs")
    d = desired(m, cat, write=True)
    settings = merge_settings(d, sets)
    plan = plan_for(m, d, _order(d["apps"] + list(ids), cat), settings)
    if plan["problems"]:
        for p in plan["problems"]:
            emit("::error plan " + p)
        return EXIT_REFUSED
    step(emit, "plan", "done")
    host = L.Host(plan, root=m.root, run_=m.run, emit=emit, hw=plan["hardware"], hostname=m.hostname, **(host_kw or {}))
    runner = L.Runner(host)
    code = runner.run()
    done = [i for i, s in runner.status.items() if s == "done"]
    Sizes(m).forget(ids)
    step(emit, "record", "running", "Saving what this server runs")
    d = desired(m, cat)
    d["apps"] = _order(d["apps"] + [i for i in plan["auto_added"] + list(ids) if i in done], cat)
    d["settings"] = {k: v for k, v in settings.items() if v}
    save_desired(m, d)
    step(emit, "record", "done")
    new = [i for i in ids if i in done and cat[i].get("health")]
    if new:
        step(emit, "answers", "running", f"Checking that {_names(cat, new)} answer{'s' if len(new) == 1 else ''}")
        ok = all([wait_answers(m, cat[i], emit) for i in new])
        step(emit, "answers", "done" if ok else "failed")
        if not ok and code == 0:
            code = EXIT_PROBLEM
    return code


def stays(m, it, view=None):
    """What a removal leaves: the app's folder with its measured size, each data folder, and
    the names of its keys (never their values)."""
    v = view or View(m, checks=False)
    folder = "/" + L.APPS + "/" + it["id"]
    sizes = v.sizes
    rows = [{"path": p, "kind": d["kind"], "what": d["what"], "bytes": n} for d, p, n in v.data(it)]
    keys = [f"{it['id']}/{s}" for s in it["secrets"]]
    keys += [f"{it['id']}/{f['id']}" for f in ((it.get("setup") or {}).get("field") or []) if f.get("kind") == "secret"]
    there = m.path(folder).exists()
    return {"path": folder, "exists": there, "bytes": sizes.get(folder) if there else 0, "data": rows, "keys": keys}


def removal(m, i, view=None):
    """What `remove` would do, or why it won't: {app, stops, leaves, stays, never_touched,
    needed_by, refused}."""
    v = view or View(m, checks=False)
    if i not in v.cat:
        raise AppsError(f"there's no app named {i!r} (bromigos lab apps list --all lists them)")
    it = v.cat[i]
    if i not in v.installed:
        raise AppsError(f"{it['name']} isn't on this server")
    nb = needed_by(v.cat, v.installed, i)
    refused = cant_remove(it)
    if nb and not refused:
        refused = (f"{it['name']} can't be removed while {_names(v.cat, nb)} need{'s' if len(nb) == 1 else ''} it: "
                   f"remove {'it' if len(nb) == 1 else 'them'} first.")
    web = it.get("web") or {}
    leaves = [f"{web['name']}-{m.hostname}.local"] if web.get("name") and "caddy" in v.installed else []
    return {"schema": SCHEMA, "app": i, "name": it["name"], "stops": L.services_of(it), "leaves": leaves,
            "stays": stays(m, it, v), "never_touched": NEVER_TOUCHED, "needed_by": nb, "refused": refused}


def _remove_folder(m, folder):
    p = m.path(folder)
    if not p.exists():
        return 0
    if p.is_symlink() or not p.is_dir():
        raise AppsError(f"{folder} isn't a folder of its own, so it was left as it is", EXIT_PROBLEM)
    size = tree_bytes(str(p))
    shutil.rmtree(p)
    return size


def do_remove(m, i, delete_data=False, emit=None, host_kw=None):
    emit = emit or (lambda line: print(line, flush=True))
    cat = PC.by_id()
    it = cat[i]
    job = it.get("job") or it["name"]
    step(emit, "check", "running", f"Checking what needs {job}")
    d = desired(m, cat, write=True)
    r = removal(m, i, View(m, cat, checks=False))
    if r["refused"]:
        emit(f"::error check {r['refused']}")
        return EXIT_REFUSED
    step(emit, "check", "done")
    step(emit, "stop", "running", f"Stopping {job}")
    inst = it["install"]
    for u in reversed(r["stops"]):
        m.run(["systemctl", "stop", u])
        if "quadlet" not in inst:
            m.run(["systemctl", "disable", u])
    step(emit, "stop", "done")
    step(emit, "units", "running", "Removing its services")
    if "quadlet" in inst:
        for f in L.template_files(inst["quadlet"]):
            with_name = m.path(L.QUADLET_DIR + "/" + f.name)
            if with_name.exists() or with_name.is_symlink():
                with_name.unlink()
        m.run(["systemctl", "daemon-reload"])
    pkgs = [p for p in packages_of(it) if m.run(["pacman", "-Q", p])[0] == 0]
    if pkgs:
        rc, _, _ = m.run(["pacman", "-R", "--noconfirm", *pkgs])
        if rc:
            emit(f"::note units The package{'s' if len(pkgs) > 1 else ''} {', '.join(pkgs)} stay{'' if len(pkgs) > 1 else 's'} "
                 "installed: something else on this server needs it.")
    rec = engine_record(m)
    if rec["items"].pop(i, None) is not None:
        p = m.path(L.STATE)
        p.write_text(json.dumps(rec, indent=1, sort_keys=True) + "\n")
    L.forget_database_hook(m.path(f"{L.DB_HOOKS}/{i}.toml"))      # no backup looks for its database any more
    step(emit, "units", "done")
    folder = r["stays"]["path"]
    if delete_data:
        step(emit, "data", "running", f"Deleting its data in {folder}")
        n = _remove_folder(m, folder)
        emit(f"::note data Deleted {folder} ({gib(n)}).")
        step(emit, "data", "done")
    else:
        step(emit, "data", "skipped", "Keeping its data")
        if r["stays"]["exists"]:
            emit(f"::note data Its data stays in {folder} ({gib(r['stays']['bytes'])}). Adding {job} again picks it up.")
    Sizes(m).forget([i])
    step(emit, "record", "running", "Saving what this server runs")
    d = desired(m, cat)
    d["apps"] = [x for x in d["apps"] if x != i]
    save_desired(m, d)
    step(emit, "record", "done")
    code = 0
    if d["apps"]:
        # The rest again, so names, links and units that named this app follow (the engine
        # leaves what didn't change as it is)
        step(emit, "others", "running", "Bringing the other apps' names and links up to date")

        def keep(line):                     # the engine's own items aren't this job's steps: its words are
            if line.startswith("::error "):
                emit("::note others " + line.split(" ", 2)[-1])
            elif line.startswith("::note ") and not line.startswith("::note secrets"):
                emit(line)
        plan = plan_for(m, d, d["apps"], d["settings"])
        if not plan["problems"]:
            code = L.Runner(L.Host(plan, root=m.root, run_=m.run, emit=keep, hw=plan["hardware"], hostname=m.hostname,
                                   **(host_kw or {}))).run()
        step(emit, "others", "done" if code == 0 and not plan["problems"] else "failed",
             "" if code == 0 else "Some of the other apps didn't come out as they were")
    return code


# ---------------------------------------------------------------- starting a job
def activity_cmd(self_argv, environ=None):
    """bromigos-activity: beside this command (installed, both are in /usr/lib/bromigos/bin; in a
    checkout, bin/ at the top), else on PATH. BROMIGOS_ACTIVITY_CMD names another."""
    environ = os.environ if environ is None else environ
    if environ.get("BROMIGOS_ACTIVITY_CMD"):
        return environ["BROMIGOS_ACTIVITY_CMD"]
    here = os.path.dirname(os.path.realpath(self_argv[0])) if self_argv else ""
    for p in (os.path.join(here, "bromigos-activity"), os.path.join(here, "..", "..", "bin", "bromigos-activity")):
        if here and os.path.isfile(p) and os.access(p, os.X_OK):
            return os.path.normpath(p)
    return shutil.which("bromigos-activity")


def as_job(m, self_argv, kind, title, subject, inner, json_out):
    """Hand over to `bromigos activity run`: the job gets a unit of its own and the lock
    `apps`, and runs `inner` (this command again, which sees it's inside the job)."""
    exe = activity_cmd(self_argv, m.environ)
    if not exe:
        return None
    argv = [exe, "run", "--kind", kind, "--title", title, "--subject", subject, "--lock", LOCK]
    return m.start(argv + (["--json"] if json_out else []) + ["--"] + list(self_argv) + list(inner))


# ---------------------------------------------------------------- for people
def gib(n):
    if n is None:
        return "size unknown"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KiB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.0f} MiB"
    return f"{n / 1024 ** 3:.1f} GiB"


def ago(ms, now):
    s = max(0, (now - ms) // 1000)
    if s < 120:
        return f"{s} s"
    if s < 7200:
        return f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h"
    return f"{s // 86400} days"


def tile_line(t, now):
    name = t["job"] + (f" · {t['app']}" if t["app"] else "") + (f" {t['version']}" if t["version"] else "")
    bits = [t["state_word"] or ""]
    if t["since"] and t["state"] in ("ok", "degraded"):
        bits[0] += f" for {ago(t['since'], now)}"
    ms = t["measured"] or {}
    if ms.get("ram_bytes") is not None:
        bits.append(f"{gib(ms['ram_bytes'])} memory")
    if ms.get("disk_bytes") is not None:
        bits.append(f"{gib(ms['disk_bytes'])} data")
    if t["open"]:
        bits.append(t["open"]["url"])
    return f"  {MARKS.get(t['state'], '·')} {name:<40} " + "  ".join(b for b in bits if b)


def print_list(tiles, cat, m, everything):
    on = [t for t in tiles if t["installed"]]
    off = [t for t in tiles if not t["installed"]]
    bad = [t for t in on if t["state"] in ("down", "degraded")]
    if not on:
        print("No apps on this server yet. bromigos lab apps list --all shows what can be added; "
              "sudo bromigos lab apps add ID adds one.")
    else:
        head = f"Apps on {m.hostname}: {len(on)}"
        head += (f", {len(bad)} need{'s' if len(bad) == 1 else ''} a look" if bad else
                 ", all running" if all(t["state"] == "ok" for t in on) else "")
        print(head)
        for t in on:
            print(tile_line(t, m.clock()))
        for t in bad:
            print(f"  {t['job']}: {'its services stopped' if t['state'] == 'down' else 'it is running but does not answer'}. "
                  f"bromigos lab apps logs {t['id']} shows why; sudo bromigos lab apps restart {t['id']} starts it again.")
    if everything:
        print("\nCan be added (sudo bromigos lab apps add ID):")
        for g in PC.groups():
            rows = [t for t in off if t["group"] == g["id"]]
            if rows:
                print(f"  {g['name']}")
                for t in rows:
                    it = cat[t["id"]]
                    print(f"    {t['id']:<18} {t['job'] + (' · ' + t['app'] if t['app'] else ''):<34} {it['line']}")
    elif off:
        print(f"{len(off)} more can be added: bromigos lab apps list --all")


def print_show(doc, m):
    t, r = doc["app"], doc["recipe"]
    print(f"{t['job']}" + (f" · {t['app']}" if t["app"] else "") + (f"  {t['version']}" if t["version"] else ""))
    print(f"  {r['line']}")
    if not t["installed"]:
        print(f"  Not on this server. sudo bromigos lab apps add {t['id']} adds it.")
    else:
        print(f"  {t['state_word']}" + (f", since {ago(t['since'], m.clock())} ago" if t["since"] else ""))
        for u in doc["units"]:
            print(f"    {u['unit']}: {u['active'] or 'unknown'}" + (f" ({u['sub']})" if u["sub"] else "")
                  + (f", {gib(u['ram_bytes'])} memory" if u.get("ram_bytes") is not None else ""))
        h = doc["health"]
        if h:
            print(f"  Answers: {'yes' if h['ok'] else 'no'}, {h['how']} ({h['status']}, {h['ms']} ms)")
        if t["open"]:
            print(f"  Open: {t['open']['url']}")
    for d in doc["data"]:
        print(f"  Data: {d['path']} ({d['kind']}" + (f", {gib(d['bytes'])}" if t["installed"] else "") + f"): {d['what']}")
    if doc["keys"]:
        print(f"  Keys in the secret store: {', '.join(doc['keys'])}")
    if doc["needs"]:
        print(f"  Needs: {', '.join(doc['needs'])}")
    if t["needed_by"]:
        print(f"  Needed by: {', '.join(t['needed_by'])}")
    print(f"  Recipe {t['recipe']}, installs with {r['install']['kind']}" + (f"; ports {', '.join(map(str, r['ports']))}"
                                                                              if r["ports"] else ""))


def print_removal(r, delete_data):
    print(f"Removing {r['name']}:")
    if r["stops"]:
        print(f"  stops and leaves: {', '.join(r['stops'])}" + (f"; its name {', '.join(r['leaves'])}" if r["leaves"] else ""))
    s = r["stays"]
    where = f"its data in {s['path']} ({gib(s['bytes'])})" if s["exists"] else f"nothing in {s['path']} (it kept no data there)"
    keys = f", and its keys ({', '.join(s['keys'])})" if s["keys"] else ""
    if delete_data:
        print(f"  deletes: {where}. Its keys stay in the secret store{(' (' + ', '.join(s['keys']) + ')') if s['keys'] else ''}.")
    else:
        print(f"  stays: {where}{keys}. Adding it again picks {'them' if keys else 'it'} up.")
        for d in s["data"]:
            print(f"    {d['path']} ({gib(d['bytes'])}): {d['what']}")
    print(f"  never touched: {', '.join(r['never_touched'])}.")


def confirm_delete(it, yes):
    if yes:
        return True
    if not sys.stdin.isatty():
        raise AppsError("deleting an app's data needs a yes: run it in a terminal, or add --yes", EXIT_REFUSED)
    typed = input(f"Type {it['id']} to delete its data for good: ").strip()
    return typed == it["id"]


# ---------------------------------------------------------------- the commands
def cmd_list(m, a):
    v = View(m)
    tiles = v.tiles()
    if a.json:
        print(json.dumps(tiles, indent=1))
    else:
        print_list(tiles, v.cat, m, a.all)
    if v.rows is None:
        if not a.json:
            print("The service manager didn't answer, so no app's state is known.", file=sys.stderr)
        return EXIT_UNCHECKED
    return EXIT_PROBLEM if any(t["installed"] and t["state"] in ("down", "degraded") for t in tiles) else 0


def show_doc(m, i):
    v = View(m, checks=False)
    if i not in v.cat:
        raise AppsError(f"there's no app named {i!r} (bromigos lab apps list --all lists them)")
    it = v.cat[i]
    if i in v.installed and it.get("health") and v.rows and all(v.rows[u]["active"] == "active" for u in v.units[i]):
        v.checks[i] = health(m, it)
    t = v.tile(it)
    units = []
    for u in v.units.get(i) or []:
        row = (v.rows or {}).get(u) or {}
        units.append({"unit": u, "active": row.get("active") or None, "sub": row.get("sub") or None,
                      "since": row.get("since"), "ram_bytes": cgroup_memory(m, row.get("cgroup"))})
    on = i in v.installed
    data = [{"path": p, "kind": d["kind"], "what": d["what"], "bytes": n if on else None}
            for d, p, n in (v.data(it) if on else [(d, d["path"], None) for d in L.data_paths(it)])]
    v.sizes.save()
    keys = stays(m, it, v)["keys"]
    return {"schema": SCHEMA, "app": t,
            "recipe": {"name": it["name"], "line": it["line"], "hint": it["hint"], "install": PC.describe_item(it),
                       "ports": list(it["ports"]), "web": it.get("web"), "health": it.get("health"),
                       "size_text": it["size_text"], "internet": bool(it["internet"]), "version": it["version"]},
            "units": units, "data": data, "health": v.checks.get(i), "keys": keys,
            "needs": list(it["needs"]), "record": v.record.get(i) if on else None, "snapshots": None}


def cmd_show(m, a):
    doc = show_doc(m, a.id)
    if a.json:
        print(json.dumps(doc, indent=1))
    else:
        print_show(doc, m)
    t = doc["app"]
    return EXIT_PROBLEM if t["installed"] and t["state"] in ("down", "degraded") else 0


def cmd_budget(m, a):
    cat = PC.by_id()
    bad = [i for i in a.ids if i not in cat]
    if bad:
        raise AppsError(f"there's no app named {', '.join(bad)} (bromigos lab apps list --all lists them)")
    b = budget_doc(m, a.ids)
    if a.json:
        print(json.dumps(dict(b, schema=SCHEMA), indent=1))
        return 0
    hw = b["hardware"]
    inst, pick = b["installed"], b["picked"]
    print(f"This server: {hw['cpu']} cores, {hw['ram_gb']} GB memory, {hw['disk_gb']} GB free where apps keep data.")
    print(f"What the installed apps ask for ({len(inst['ids'])}): about {inst['ram_gb']:g} GB of memory and "
          f"{inst['disk_gb']:g} GB of disk; the hungriest needs {inst['cpu_max']:g} cores.")
    if pick["ids"]:
        print(f"With {_names(cat, pick['ids'])}: about {b['ram_gb']:g} GB of memory in all, and "
              f"{pick['disk_gb']:g} GB more disk. " + ("It fits." if b["fits"] else "It doesn't fit."))
    for n in b["notes"]:
        print("  " + n)
    ms = b["measured"]
    if ms["ram_bytes"] is not None or ms["disk_bytes"] is not None:
        print("In use now, measured: " + ", ".join(x for x in (
            f"{gib(ms['ram_bytes'])} of memory by {ms['ram_apps']} apps" if ms["ram_bytes"] is not None else "",
            f"{gib(ms['disk_bytes'])} of data" if ms["disk_bytes"] is not None else "") if x) + ".")
    return 0 if b["fits"] else EXIT_PROBLEM


def _needs_root(m, verb):
    if not m.may_change():
        raise AppsError(f"{verb} changes the server, so it needs root: sudo bromigos lab apps {verb} …", EXIT_REFUSED)


def cmd_add(m, a, self_argv):
    cat = PC.by_id()
    bad = [i for i in a.ids if i not in cat]
    if bad:
        raise AppsError(f"there's no app named {', '.join(bad)} (bromigos lab apps list --all lists them)")
    ids = list(dict.fromkeys(a.ids))
    if m.in_job():
        return do_add(m, ids, a.set)
    d = desired(m, cat)
    settings = merge_settings(d, a.set)
    plan = plan_for(m, d, _order(d["apps"] + ids, cat), settings)
    new = [i for i in ids if i not in d["apps"]]
    b = budget_doc(m, ids)
    if a.plan:
        if a.json:
            print(json.dumps({"schema": SCHEMA, "ok": not plan["problems"], "add": new,
                              "added_for_them": [i for i in plan["auto_added"] if i not in d["apps"]],
                              "problems": plan["problems"], "budget": b,
                              "plan": [r for r in plan["items"] if r["id"] in new or
                                       (r["id"] in plan["auto_added"] and r["id"] not in d["apps"])]}, indent=1))
        else:
            for r in plan["items"]:
                if r["id"] in new or r["id"] in plan["auto_added"] and r["id"] not in d["apps"]:
                    extra = " (ticked for you: something you chose needs it)" if r["id"] not in new else ""
                    print(f"Adds {r['name']}{extra}: {r['line']}")
                    print(f"  {r['size_text'] or 'nothing to download'}" + (f"; ports {', '.join(map(str, r['ports']))}" if r["ports"] else ""))
                    for n in r["notes"]:
                        print("  " + n)
            if not new:
                print(f"{_names(cat, ids)} {'is' if len(ids) == 1 else 'are'} on this server already.")
            print(f"Together with what's installed: about {b['ram_gb']:g} GB of memory of {b['hardware']['ram_gb']} GB, "
                  f"and {b['picked']['disk_gb']:g} GB more disk of {b['hardware']['disk_gb']} GB free.")
            for n in b["notes"]:
                print("  " + n)
            for p in plan["problems"]:
                print("Problem: " + p)
        return EXIT_REFUSED if plan["problems"] else 0
    if plan["problems"]:
        raise AppsError(" ".join(plan["problems"]))
    rec = engine_record(m)["items"]
    if not new and not a.set and all((rec.get(i) or {}).get("state") == "done" for i in ids):
        print(f"{_names(cat, ids)} {'is' if len(ids) == 1 else 'are'} on this server already. "
              f"bromigos lab apps show {ids[0]} says how {'it is' if len(ids) == 1 else 'they are'}.")
        return 0
    for n in b["notes"]:
        print(n, file=sys.stderr)
    title = f"Adding {_names(cat, ids)}"
    subject = f"app:{ids[0]}:{cat[ids[0]].get('job') or cat[ids[0]]['name']}"
    inner = ["add", *ids] + [x for s in a.set for x in ("--set", s)]
    code = as_job(m, self_argv, "app.install", title, subject, inner, a.json)
    if code is not None:
        return code
    _needs_root(m, "add")
    print("bromigos activity isn't installed, so this runs here, with no record of the job.", file=sys.stderr)
    return do_add(m, ids, a.set)


def cmd_remove(m, a, self_argv):
    if m.in_job():
        return do_remove(m, a.id, a.delete_data)
    r = removal(m, a.id)
    if a.json and a.plan:
        print(json.dumps(dict(r, delete_data=a.delete_data), indent=1))
        return EXIT_REFUSED if r["refused"] else 0
    if r["refused"]:
        raise AppsError(r["refused"])
    if not a.json:
        print_removal(r, a.delete_data)
    if a.plan:
        return 0
    cat = PC.by_id()
    it = cat[a.id]
    if a.delete_data and not confirm_delete(it, a.yes):
        print("Nothing was removed.")
        return EXIT_REFUSED
    job = it.get("job") or it["name"]
    inner = ["remove", a.id] + (["--delete-data", "--yes"] if a.delete_data else [])
    code = as_job(m, self_argv, "app.remove", f"Removing {job}", f"app:{a.id}:{job}", inner, a.json)
    if code is not None:
        return code
    _needs_root(m, "remove")
    print("bromigos activity isn't installed, so this runs here, with no record of the job.", file=sys.stderr)
    return do_remove(m, a.id, a.delete_data)


def _installed(m, i, verb):
    cat = PC.by_id()
    if i not in cat:
        raise AppsError(f"there's no app named {i!r} (bromigos lab apps list --all lists them)")
    if i not in desired(m, cat)["apps"]:
        raise AppsError(f"{cat[i]['name']} isn't on this server (sudo bromigos lab apps add {i} adds it)")
    units = L.services_of(cat[i])
    if not units:
        raise AppsError(f"{cat[i]['name']} has no service of its own to {verb}")
    return cat[i], units


def cmd_restart(m, a):
    it, units = _installed(m, a.id, "restart")
    _needs_root(m, "restart")
    bad = [u for u in units if m.run(["systemctl", "restart", u])[0] != 0]
    ok = not bad
    if a.json:
        print(json.dumps({"schema": SCHEMA, "ok": ok, "app": a.id, "units": units, "failed": bad}, indent=1))
    elif ok:
        print(f"Restarted {it.get('job') or it['name']}: {', '.join(units)}. bromigos lab apps show {a.id} says when it answers.")
    else:
        print(f"{', '.join(bad)} didn't start again. bromigos lab apps logs {a.id} shows why.", file=sys.stderr)
    return 0 if ok else EXIT_PROBLEM


def cmd_logs(m, a):
    it, units = _installed(m, a.id, "show the logs of")
    argv = ["journalctl", "--no-pager", "-n", str(a.lines)] + [x for u in units for x in ("-u", u)]
    if a.json:
        rc, out, err = m.run(argv + ["-o", "short-iso"])
        print(json.dumps({"schema": SCHEMA, "ok": rc == 0, "app": a.id, "units": units, "lines": out.splitlines()}, indent=1))
        return 0 if rc == 0 else EXIT_UNCHECKED
    exe = shutil.which("journalctl") or "/usr/bin/journalctl"
    return m.start([exe] + argv[1:] + (["-f"] if a.follow else []))


def stub(cmd, rest, self_argv, m=None):
    """`bromigos lab deploy|restart|logs|update` on a Server: the apps verbs (DESIGN: the four
    stubs become real on a Server; on a lab with a repository they stay Phase 2)."""
    if cmd == "update":
        print("Updating apps is planned, and not built yet: a snapshot of each app's data, the new version, a check "
              "that it answers, and going back by itself when it doesn't (docs/lab-provision.md, \"Updates\"). Until "
              "then packaged apps update with the system, and container apps stay at the version their recipe pins.",
              file=sys.stderr)
        return EXIT_REFUSED
    verb = {"deploy": "add", "restart": "restart", "logs": "logs"}[cmd]
    return main([verb] + list(rest), self_argv, m)


def main(argv, self_argv=None, m=None):
    self_argv = list(self_argv or [os.path.realpath(sys.argv[0]), "apps"])
    p = argparse.ArgumentParser(prog="bromigos lab apps", description="The apps this server runs")
    sub = p.add_subparsers(dest="verb")
    lp = sub.add_parser("list", help="each app: its state, what it uses, its page")
    lp.add_argument("--all", action="store_true", help="the apps that can be added too")
    sp = sub.add_parser("show", help="one app in full")
    sp.add_argument("id")
    ap = sub.add_parser("add", help="add apps (a job; needs root)")
    ap.add_argument("ids", nargs="+", metavar="ID")
    ap.add_argument("--plan", action="store_true", help="say what it would add and what it asks of the server")
    ap.add_argument("--set", action="append", default=[], metavar="ITEM.FIELD=VALUE", help="a setup field (not a secret)")
    rp = sub.add_parser("remove", help="remove an app, keeping its data (a job; needs root)")
    rp.add_argument("id")
    rp.add_argument("--delete-data", action="store_true", help="delete its data too, for good")
    rp.add_argument("--yes", action="store_true", help="with --delete-data: don't ask to type its name")
    rp.add_argument("--plan", action="store_true", help="say what would stop, what stays and what would go")
    tp = sub.add_parser("restart", help="restart an app's services (needs root)")
    tp.add_argument("id")
    gp = sub.add_parser("logs", help="an app's logs, from the journal")
    gp.add_argument("id")
    gp.add_argument("-f", "--follow", action="store_true")
    gp.add_argument("-n", "--lines", type=int, default=50)
    bp = sub.add_parser("budget", help="what the installed apps, and these, ask of the server")
    bp.add_argument("ids", nargs="*", metavar="ID")
    for q in (p, lp, sp, ap, rp, tp, gp, bp):
        q.add_argument("--json", action="store_true", default=argparse.SUPPRESS if q is not p else False)
    a = p.parse_args(argv)
    a.json = getattr(a, "json", False)
    m = m or Machine()
    try:
        verb = a.verb or "list"
        if verb == "list":
            a.all = getattr(a, "all", False)
            return cmd_list(m, a)
        if verb == "show":
            return cmd_show(m, a)
        if verb == "add":
            return cmd_add(m, a, self_argv)
        if verb == "remove":
            return cmd_remove(m, a, self_argv)
        if verb == "restart":
            return cmd_restart(m, a)
        if verb == "logs":
            return cmd_logs(m, a)
        if verb == "budget":
            return cmd_budget(m, a)
    except AppsError as e:
        if a.json:
            print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(e)}))
        print(f"bromigos lab apps: {e}", file=sys.stderr)
        return e.code
    except (PC.CatalogueError, FileNotFoundError) as e:
        print(f"bromigos lab apps: {e}", file=sys.stderr)
        return EXIT_UNCHECKED
    return EXIT_USAGE
