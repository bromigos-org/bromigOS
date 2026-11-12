#!/usr/bin/env python3
"""The bromigOS start page's data: keeps the user's page folder and writes data.js into it.

A browser page cannot read local files or send a lab's bearer token across origins, so
this runs from a user systemd timer (bromigos-startpage.timer, every minute) and the page
loads the result as a plain <script>. The token never leaves this machine.

The page folder, ~/.local/share/bromigos/startpage ($BROMIGOS_STARTPAGE_DIR), is
self-contained (`dir = "…"` in startpage.toml puts it elsewhere): the packaged page (/usr/share/bromigos/startpage) copied in, the current
theme's colours (theme.css) and emblem (emblem-theme.svg, emblem-48.png) copied beside it,
and data.js. So it opens from anywhere: a new-tab extension loaded from it, a browser
home page, or a link to it.

The lab: bromigos-homelab's snapshot (homelab.toml) when it's installed and configured,
else the private overlay's endpoints.lab Lab API with the read-only token.

The lab's jobs (the LAB JOBS card): what the lab's ComfyUI makes now and what it made, and the
runs of tools that write a job feed, from bromigos-core's lib/bromigos_labjobs.py, the source
`bromigos activity` and the Lab board read (docs/activity.md, "Lab jobs"). Their pictures are
the user's follower's (bromigos-labjobs.service, started here when a ComfyUI is set and it
isn't running), copied into the page folder's lab/.

The links: ~/.config/bromigos/startpage.toml (docs/desktop.md, "The start page"):

    from_lab = ["argocd", "grafana"]          # services from the lab's own groups, by id
    [[link]]
    name = "MY APP"                           # a fixed link: url, or endpoint (a private
    role = "what it is"                       # overlay key, so no address in a public file)
    endpoint = "myapp"
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import ssl
import sys
import time
import tomllib
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
STATIC = next((d for d in ("/usr/share/bromigos/startpage", HERE)
               if os.path.exists(os.path.join(d, "index.html"))), HERE)
for lib in ("/usr/lib/bromigos/lib", os.path.join(HERE, "..", "..", "lib"),
            os.path.join(HERE, "..", "..", "homelab", "lib")):
    if os.path.isdir(lib):
        sys.path.append(lib)
import bromigos_private as PRIV  # noqa: E402  the user's private values (empty without an overlay)

try:
    import bromigos_homelab as HL  # noqa: E402  (package bromigos-homelab, optional)
except Exception:
    HL = None

HOME = os.path.expanduser("~")
STATE = os.environ.get("XDG_STATE_HOME") or os.path.join(HOME, ".local/state")
CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.join(HOME, ".config")
LINKS = os.path.join(CONFIG, "bromigos", "startpage.toml")


def _settings():
    try:
        with open(LINKS, "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {}


# the page folder: $BROMIGOS_STARTPAGE_DIR, else startpage.toml's `dir`, else the default
PAGE = os.path.expanduser(os.environ.get("BROMIGOS_STARTPAGE_DIR") or _settings().get("dir")
                          or os.path.join(HOME, ".local/share/bromigos/startpage"))
TOKEN_FILE = os.path.join(HOME, ".local/share/bromigos/lab-token")
NOTES = os.path.join(HOME, ".local/share/bromigos/notes.md")
CTX = ssl.create_default_context()
STATIC_FILES = ("index.html", "app.js", "style.css", "emblem.svg", "icon-48.png", "icon-128.png", "manifest.json")
FROM_LAB_DEFAULT = ["argocd", "grafana", "litellm", "openwebui", "comfyui", "proxmox", "vault", "rustfs"]
LABELS = {"argocd": "ARGO CD", "grafana": "GRAFANA", "litellm": "LITELLM", "openwebui": "OPEN WEBUI",
          "comfyui": "COMFYUI", "proxmox": "PROXMOX", "vault": "VAULT", "rustfs": "RUSTFS"}


def _copy_if_changed(src, dst):
    try:
        s = os.stat(src)
    except OSError:
        return
    try:
        d = os.stat(dst)
        if d.st_size == s.st_size and d.st_mtime >= s.st_mtime:
            return
    except OSError:
        pass
    # a private temporary name: the migration's run and the timer's can copy the same file at
    # once, and a shared "<dst>.tmp" let one replace the other's away (install failed on it)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(dst) + ".", dir=os.path.dirname(dst) or ".")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sync_page():
    """The packaged page, the theme's colours and the emblem in force, into the page folder."""
    os.makedirs(PAGE, exist_ok=True)
    for f in STATIC_FILES:
        _copy_if_changed(os.path.join(STATIC, f), os.path.join(PAGE, f))
    theme = os.path.join(STATE, "bromigos/theme/current/startpage.css")
    if os.path.exists(theme):
        _copy_if_changed(theme, os.path.join(PAGE, "theme.css"))
    elif not os.path.exists(os.path.join(PAGE, "theme.css")):
        open(os.path.join(PAGE, "theme.css"), "w").close()      # the page's own colours stand
    emblem = os.path.join(STATE, "bromigos/emblem")
    for src, dst in (("emblem-small.svg", "emblem-theme.svg"), ("emblem-small-48.png", "emblem-48.png")):
        if os.path.exists(os.path.join(emblem, src)):
            _copy_if_changed(os.path.join(emblem, src), os.path.join(PAGE, dst))
        elif dst == "emblem-theme.svg":
            _copy_if_changed(os.path.join(STATIC, "emblem.svg"), os.path.join(PAGE, dst))


def links_config():
    c = _settings()
    fixed = []
    for ln in c.get("link") or []:
        url = ln.get("url") or (PRIV.url(ln["endpoint"], "") if ln.get("endpoint") else "")
        if url:
            fixed.append((ln.get("id") or ln.get("endpoint") or ln.get("name", "").lower(),
                          ln.get("name", ""), ln.get("role", ""), url))
    lab = lab_url()
    if lab and not any(f[0] == "lab" for f in fixed):
        fixed.append(("lab", "LAB", "The lab's homepage", lab))
    return fixed, list(c.get("from_lab", FROM_LAB_DEFAULT))


def lab_url():
    if HL is not None:
        try:
            u = HL.lab_url()
            if u:
                return u.rstrip("/")
        except Exception:
            pass
    return PRIV.url("lab")


def token():
    t = os.environ.get("BROMIGOS_LAB_TOKEN")
    if t:
        return t
    try:
        with open(TOKEN_FILE) as f:
            return f.read().strip()
    except OSError:
        return None


def lab_status():
    """(snapshot, state, source): bromigos-homelab's snapshot, else the overlay's Lab API."""
    if HL is not None:
        try:
            src = HL.snapshot_source()
            if src:
                d = HL.snapshot()
                if d:
                    age = time.time() - float(d.get("generatedAt") or 0)
                    return d, ("stale" if age > 120 else "ok"), f"bromigos-homelab ({src})"
        except Exception as e:                       # registry.Unreachable and the like
            return None, "down", "bromigos-homelab: " + type(e).__name__
    url = PRIV.url("lab", "/api/status")
    if not url:
        return None, "unconfigured", ""
    tok = token()
    if not tok:
        return None, "no-token", url
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        with urllib.request.urlopen(req, timeout=8, context=CTX) as r:
            data = json.load(r)
        age = time.time() - float(data.get("generatedAt") or 0)
        return data, ("stale" if age > 120 else "ok"), url
    except urllib.error.HTTPError as e:
        return None, ("unauthorized" if e.code in (401, 403) else f"HTTP {e.code}"), url
    except (OSError, ValueError):
        return None, "down", url


def http_alive(url, timeout=4):
    """Any answer below 500 counts as up (the same rule the lab and the widgets use)."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD"),
                                    timeout=timeout, context=CTX) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except OSError:
        return False


def lab_summary(d):
    """Only the numbers the page shows (no addresses, names or series)."""
    if not d:
        return None
    c, a, s = d.get("cluster") or {}, d.get("argocd") or {}, d.get("services") or {}
    g, ai, n = d.get("gpu") or {}, d.get("ai") or {}, d.get("network") or {}
    down = sorted(k for k, v in s.items() if (v or {}).get("status") != "up")
    return {
        "generatedAt": d.get("generatedAt"),
        "nodesReady": c.get("nodesReady"), "nodesTotal": c.get("nodesTotal"),
        "podsRunning": c.get("podsRunning"), "podsNotRunning": c.get("podsNotRunning"),
        "alertsFiring": c.get("alertsFiring"), "cpuNow": c.get("cpuNow"),
        "argoHealthy": a.get("healthy"), "argoTotal": a.get("total"),
        "servicesUp": len(s) - len(down), "servicesTotal": len(s), "servicesDown": down,
        "gpuUtil": g.get("utilNow"), "gpuCount": g.get("count"),
        "aiRpm": ai.get("rpmNow"),
        "wanDownBps": n.get("wanDownBps"), "wanUpBps": n.get("wanUpBps"),
    }


def switchboard(d):
    fixed, from_lab = links_config()
    out = [{"id": sid, "name": name, "role": role, "url": url, "up": http_alive(url)}
           for sid, name, role, url in fixed]
    groups = (d or {}).get("config", {}).get("groups", [])
    status = (d or {}).get("services", {})
    for sid in from_lab:
        for g in groups:
            for s in g.get("services", []):
                if s.get("id") == sid and s.get("lan"):
                    st = (status.get(sid) or {}).get("status")
                    out.append({"id": sid, "name": LABELS.get(sid) or s.get("name") or sid.upper(), "role": s.get("role", ""),
                                "url": s["lan"], "up": None if st is None else st == "up"})
    return out


def notes(limit=8):
    try:
        with open(NOTES) as f:
            lines = [ln.rstrip() for ln in f if ln.strip()]
        return {"lines": lines[-limit:], "count": len(lines), "mtime": os.path.getmtime(NOTES)}
    except OSError:
        return {"lines": [], "count": 0, "mtime": None}


LAB_LATEST = 6                  # ended lab jobs on the card, newest first
LAB_FILE_MAX = 8 * 1024 * 1024  # bytes of one picture copied into the page folder


def _lab_copy(m, media_dir, out, keep):
    """A picture of a lab job (its follower's media name, or a feed's own file) copied into the
    page folder's lab/ under a name made of its content; its name there, or None. Pictures only:
    a clip or a model shows as its kind."""
    try:
        import bromigos_labjobs as L
    except ImportError:
        return None
    src = None
    for n in (m.get("thumb"), m.get("media")):
        p = L.media_path(media_dir, n) if n and media_dir else None
        if p:
            src = p
            break
    if src is None and isinstance(m.get("path"), str):
        src = m["path"]
    try:
        if not src or os.path.getsize(src) > LAB_FILE_MAX:
            return None
        with open(src, "rb") as f:
            data = f.read(LAB_FILE_MAX + 1)
    except OSError:
        return None
    ext = L.sniff(data)
    if ext not in ("png", "jpg", "webp", "gif"):
        return None
    name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
    dst = os.path.join(out, name)
    if not os.path.exists(dst):
        tmp = dst + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, dst)
    keep.add(name)
    return "lab/" + name


def lab_jobs():
    """The LAB JOBS card's data, or None when there is no lab to show (bromigos-core's lab module
    isn't here, or no ComfyUI and no job feed is set up)."""
    try:
        import bromigos_activity as A
        import bromigos_labjobs as L
    except Exception:
        return None
    try:
        where = L.Where(A.Env(), system=False)
        insts = [i for i in L.instances(where) if not i.get("quiet")]
        if not insts and not L.feed_files(where):
            return None
        doc, media_dir = L.read_state(where)
        if doc is None and insts and not os.environ.get("BROMIGOS_STARTPAGE_NO_FOLLOW"):
            # the pictures as they're made come from the follower: start it for next time
            try:
                subprocess.run(["systemctl", "--user", "start", "--no-block", "bromigos-labjobs.service"],
                               capture_output=True, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        jobs = L.jobs(where=where)
    except Exception as e:                  # a lab that can't be read never stops the page
        return {"error": f"{type(e).__name__}", "running": [], "queued": {"count": 0, "titles": []}, "latest": [], "instances": []}
    out = os.path.join(PAGE, "lab")
    os.makedirs(out, exist_ok=True)
    keep = set()
    running, latest = [], []
    for j in jobs:
        lab = j.get("lab") or {}
        if j["state"] == "running" and len(running) < 2:
            running.append({"id": j["id"], "title": j["title"], "label": lab.get("label"), "stage": j.get("stage"),
                            "pct": j.get("pct"), "estimated": bool(lab.get("estimated")),
                            "where": f"ComfyUI {lab['instance']}" if lab.get("instance") else "a job feed",
                            "client": lab.get("client"), "elapsed_ms": lab.get("elapsed_ms"), "estimate_ms": lab.get("estimate_ms"),
                            "preview": _lab_copy(lab["preview"], media_dir, out, keep) if isinstance(lab.get("preview"), dict) else None})
        elif j["state"] in ("succeeded", "failed", "cancelled", "interrupted") and len(latest) < LAB_LATEST:
            outs = (j.get("result") or {}).get("outputs") or lab.get("outputs") or []
            first = outs[0] if outs else None
            latest.append({"id": j["id"], "title": j["title"], "label": lab.get("label"), "state": j["state"],
                           "summary": (j.get("result") or {}).get("summary") or (j.get("error") or {}).get("words") or "",
                           "ended_at": j.get("ended_at"), "kind": (first or {}).get("kind"),
                           "thumb": _lab_copy(first, media_dir, out, keep) if first else None})
    queued = [j for j in jobs if j["state"] == "queued"]
    for n in os.listdir(out):               # pictures no job on the card shows any more
        if n not in keep:
            try:
                os.unlink(os.path.join(out, n))
            except OSError:
                pass
    return {"running": running, "queued": {"count": len(queued), "titles": [j["title"] for j in queued[:3]]},
            "latest": latest, "following": doc is not None,
            "instances": [{"name": i["name"], "state": i.get("state"), "live": i.get("live"), "relay": i.get("relay")}
                          for i in ((doc or {}).get("instances") or [])]}


def main():
    sync_page()
    d, state, source = lab_status()
    snap = {
        "at": time.time(),
        "lab": {"state": state, "summary": lab_summary(d), "url": lab_url(), "source": source,
                "token_vault": PRIV.vault("lab_api")},
        "switchboard": switchboard(d),
        "notes": notes(),
        "labjobs": lab_jobs(),
    }
    out = os.path.join(PAGE, "data.js")
    tmp = out + ".tmp"
    with open(tmp, "w") as f:
        f.write("window.BROMIGOS_SNAPSHOT = " + json.dumps(snap, separators=(",", ":")) + ";\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
