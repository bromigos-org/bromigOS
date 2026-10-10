"""Lab: the homelab console in Settings (bromigos-homelab's `bromigos lab`; docs/homelab.md,
"The lab console"). The status summary (every card), the GPUs and models (unload what
ComfyUI holds), the model planner (the catalog's, when installed), recent jobs with their
results, the doctor's findings with their fixes, and where AI runs. Everything is read from
`bromigos lab … --json` without blocking the window; changing the lab itself is Phase 2.
"""
import importlib.util
import os

from gi.repository import Gtk

from bromigos_settings import Page
from bromigos_settings.registry import Entry

MARK = {"ok": "●", "warn": "▲", "crit": "✖", "unreachable": "?", "empty": "·", "unknown": "·", "fail": "✖",
        "skip": "·"}


def _waiting(g, text):
    w = Gtk.Label(label=text, xalign=0)
    w.add_css_class("dim-label")
    g.add(w)
    return w


def _gib(b):
    return f"{(b or 0) / 2**30:.1f} GiB"


def _planner():
    """The model catalog's planner (`build_section(ctx, page)`: pages/_lab_models.py, a section
    the registry doesn't list as a page of its own; or lab_models.py), when it's installed next
    to this page; None otherwise."""
    here = os.path.dirname(os.path.abspath(__file__))
    p = next((os.path.join(here, f) for f in ("_lab_models.py", "lab_models.py")
              if os.path.isfile(os.path.join(here, f))), None)
    if not p:
        return None
    try:
        spec = importlib.util.spec_from_file_location("bromigos_settings_lab_models", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, "build_section", None)
    except Exception:
        return None


def build(ctx):
    page = ctx.page()
    if not ctx.has_command("lab"):
        return _not_installed(ctx, page)

    # ---------------------------------------------------------------- status
    g = ctx.group(page, "The lab", "One line per part of your lab, as `bromigos lab status` reads it now.",
                  hint="The console's cards: each says its state and a summary; hover one for what it shows",
                  key="status")
    wait = _waiting(g, "Reading the lab (a few seconds)…")

    def status(doc, err):
        g.remove(wait)
        if not doc:
            ctx.note(g, f"bromigos lab status didn't answer: {err}", "warn")
            return
        if not doc.get("configured", True):
            ctx.row(g, "No homelab connected", "bromigos lab connect finds your services and writes homelab.toml",
                    hint="Opens a terminal: it probes the hosts you name and asks before writing",
                    buttons=[("Connect…", lambda: ctx.terminal(["bromigos", "lab", "connect"]),
                              "bromigos lab connect, in a terminal")])
            return
        for c in doc.get("cards", []):
            bad = [i for i in c.get("items", []) if i.get("state") in ("warn", "crit")]
            extra = "\n".join(f"{MARK.get(i['state'])} {i.get('hint') or i.get('name')}" for i in bad[:6])
            ctx.row(g, f"{MARK.get(c['state'], '·')}  {c['title']}", c.get("summary") or "",
                    hint=(c.get("hint") or "") + (f"\n\n{extra}" if extra else ""))
    ctx.json(["bromigos", "lab", "status", "--json"], status)
    box = Gtk.Box(spacing=8)
    box.append(ctx.button("Dashboard", lambda: ctx.terminal(["bromigos", "lab"], hold=False),
                          "bromigos lab: every card in full, live, with models, jobs and the doctor (a terminal)"))
    box.append(ctx.button("Lab deck", lambda: ctx.launch(["bromigos-live", "lab", "open"]),
                          "The rack as a hologram, lit by these readings (SUPER+SHIFT+H)"))
    g.set_header_suffix(box)

    # ---------------------------------------------------------------- media requests
    _media(ctx, page)

    # ---------------------------------------------------------------- GPUs and models
    gm = ctx.group(page, "GPUs and models", "What each GPU holds, and what each server has loaded.",
                   hint="bromigos lab models: installed and loaded where, with VRAM", key="models")
    wait_m = _waiting(gm, "Asking the servers…")

    def models(doc, err):
        gm.remove(wait_m)
        if not doc:
            ctx.note(gm, f"bromigos lab models didn't answer: {err}", "warn")
            return
        for x in doc.get("gpus", []):
            vram = f"{_gib(x.get('vram_used'))} of {_gib(x.get('vram_total'))}" if x.get("vram_total") else "unified memory"
            ctx.row(gm, f"{x.get('name')} · {x.get('host')}", f"{vram} · holds {', '.join(x.get('holds') or []) or '-'}",
                    hint=f"{x.get('name')} on {x.get('host')}: {x.get('temp_c') or 0:.0f} °C, {x.get('power_w') or 0:.0f} W"
                         + (f"; {x['group']}, tensor parallel" if x.get("group") else ""))
        for s in doc.get("servers", []):
            loaded = [m for m in s.get("models", []) if m.get("loaded")]
            files = sum(1 for m in s.get("models", []) if m.get("folder"))
            sub = ", ".join(m["name"] for m in loaded[:4]) or "nothing loaded"
            if files:
                sub += f" · {files} model files on disk"
            buttons = []
            if any("unload" in (m.get("can") or []) for m in s.get("models", [])) and s.get("kind") == "ComfyUI":
                src = s["source"]
                buttons.append(("Unload", lambda src=src: _unload(ctx, src),
                                "Asks ComfyUI to drop the models it holds (between jobs; the next job loads what "
                                "it needs)"))
            ctx.row(gm, f"{s.get('kind')} · {s.get('source')}", sub, buttons=buttons,
                    hint=(s.get("detail") or "") + "\n" + "\n".join(f"{m['name']}: {m.get('note') or ''}"
                                                                   for m in s.get("models", [])[:12] if not m.get("folder")))
    ctx.json(["bromigos", "lab", "models", "--json"], models)
    plan = _planner()
    if plan:
        try:
            plan(ctx, page)
        except Exception as e:
            ctx.note(ctx.group(page, "Model planner"), f"the model planner didn't load: {e}", "warn")

    # ---------------------------------------------------------------- jobs
    gj = ctx.group(page, "Recent jobs", "Lab GPU jobs, newest first; results in ~/Pictures/bromigos/lab/.",
                   hint="bromigos lab jobs: queued, waiting (and why), running, done", key="jobs")
    wait_j = _waiting(gj, "Reading the queue…")

    def jobs(doc, err):
        gj.remove(wait_j)
        if not doc:
            ctx.note(gj, f"bromigos lab jobs didn't answer: {err}", "warn")
            return
        js = doc.get("jobs") or []
        if not js:
            ctx.row(gj, "No jobs yet", "bromigos lab run image --prompt …, or n in the dashboard",
                    hint="A job runs on the lab's GPU when it has room; the voice service keeps its share")
        for j in js[:8]:
            what = j.get("preset") or j["kind"]
            outs = j.get("outputs") or []
            detail = j.get("why") if j["state"] in ("waiting", "failed", "cancelled") else (
                f"{int((j.get('progress') or 0) * 100)}% {j.get('progress_text') or ''}" if j["state"] == "running" else
                ", ".join(os.path.basename(o) for o in outs[:2]) or (j.get("prompt") or j.get("text") or ""))
            buttons = []
            if outs:
                buttons.append(("Open", lambda o=outs[0]: ctx.launch(["xdg-open", o]), f"Opens {outs[0]}"))
                buttons.append(("Folder", lambda o=outs[0]: ctx.launch(["xdg-open", os.path.dirname(o)]),
                                "Opens the folder it landed in"))
            if j["state"] in ("queued", "waiting", "running"):
                buttons.append(("Cancel", lambda i=j["id"]: _cancel(ctx, i), f"bromigos lab jobs cancel {j['id']}"))
            ctx.row(gj, f"{what} · {j['state']}", (detail or "")[:120], buttons=buttons,
                    hint=f"{j['id']} (by {j.get('by') or 'you'}): " + (j.get("why") or "") +
                         (f"\nResults: {', '.join(outs)}" if outs else ""))
        ctx.row(gj, f"The queue's service: {doc.get('service', '?')}", "bromigos-lab.service runs the jobs",
                hint="bromigos lab run starts it when it isn't running; `systemctl --user enable --now "
                     "bromigos-lab.service` keeps it up")
    ctx.json(["bromigos", "lab", "jobs", "list", "--json"], jobs)

    # ---------------------------------------------------------------- doctor
    gd = ctx.group(page, "Doctor", "Checks with fixes in plain words: DNS, certificates, GPUs, disks and NAS, "
                                   "backups, GitOps drift, tokens, targets.",
                   hint="bromigos lab doctor: only reads; nothing here changes the lab", key="doctor")
    wait_d = _waiting(gd, "Running the checks (up to a minute)…")

    def doctor(doc, err):
        gd.remove(wait_d)
        if not doc:
            ctx.note(gd, f"bromigos lab doctor didn't answer: {err}", "warn")
            return
        s = doc.get("summary") or {}
        ctx.row(gd, f"{s.get('ok', 0)} ok · {s.get('warn', 0)} to look at · {s.get('fail', 0)} failing",
                f"{s.get('skip', 0)} skipped (nothing to check)",
                hint="Each finding below has its fix; the dashboard's Doctor tab lists the ok ones too")
        for f in [f for f in doc.get("findings", []) if f["status"] in ("fail", "warn")][:12]:
            ctx.row(gd, f"{MARK.get(f['status'])}  {f['title']}", f"{f.get('detail') or ''}\n→ {f.get('fix') or ''}",
                    hint=f"{f['id']}: {f.get('fix') or f.get('detail')}")
    ctx.json(["bromigos", "lab", "doctor", "--json"], doctor)

    # ---------------------------------------------------------------- targets
    gt = ctx.group(page, "Where AI runs", "The lab first; the cloud only where you listed it.",
                   hint="bromigos lab target (the same as bromigos target): per service, what it uses now",
                   key="targets")
    ctx.row(gt, "Creation targets", "each service's order and what answers", hint="The Creation targets page",
            activate=lambda: ctx.open_page("targets"))
    ctx.row(gt, "Connect services", "find your lab's services again and add them to homelab.toml", key="connect",
            hint="bromigos lab connect (= bromigos setup homelab), in a terminal; it never rewrites your edits",
            buttons=[("Connect…", lambda: ctx.terminal(["bromigos", "lab", "connect"]), "bromigos lab connect")])
    return page


AUDIO = [("en ja", "English, with Japanese as a second track"), ("en", "English"), ("ja", "Japanese"),
         ("ja en", "Japanese, with English as a second track"), ("any", "Any language")]
SUBS = [("en", "English"), ("ja", "Japanese"), ("en ja", "English and Japanese"), ("es", "Spanish"), ("fr", "French"),
        ("de", "German")]


def _opts(base, cur):
    """base, plus the current value when it isn't one of them (set by hand or on the command line)."""
    return base if not cur or cur in [v for v, _ in base] else base + [(cur, cur.replace(" ", ", "))]


def _media(ctx, page):
    """Your languages for `bromigos lab media get`: [media] in homelab.toml, through `bromigos
    lab media language`. Sonarr and Radarr pick the matching profile; Bazarr fetches the
    subtitles."""
    g = ctx.group(page, "Media requests", "The languages `bromigos lab media get` and VECTOR ask your lab for.",
                  hint="Your [media] settings in homelab.toml: the audio you want (the first required, the rest welcome "
                       "as extra tracks), anime's own, and the subtitles Bazarr fetches", key="media")
    wait = _waiting(g, "Reading your languages…")

    def shown(doc, err):
        g.remove(wait)
        if not doc or doc.get("error"):
            ctx.note(g, f"bromigos lab media language didn't answer: {err or doc.get('error')}", "warn")
            return
        audio, anime, subs = " ".join(doc["audio"]), " ".join(doc["anime_audio"]), " ".join(doc["subtitles"])
        set_ = lambda verb, label: (lambda v: ctx.change(["bromigos", "lab", "media", "language", verb] + v.split()
                                                         + ["--json"], f"{label}: {v.replace(' ', ', ')}"))
        ctx.combo_row(g, "Audio", "the first language is required; a release with both tracks ranks first",
                      hint="Sonarr and Radarr use the profile that matches (Recyclarr's TRaSH profiles score the audio "
                           "languages): with English first, a release with no English track isn't grabbed",
                      options=_opts(AUDIO, audio), current=audio, on_select=set_("set", "Audio"), key="audio")
        ctx.combo_row(g, "Anime audio", "anime's own, when it differs (dub or the original with subtitles)",
                      hint="Anime goes to the TRaSH anime profile with this audio rule; 'Same as audio' follows the "
                           "row above", options=[("same", "Same as audio")] + _opts(AUDIO, anime if anime != audio
                                                                                    else None),
                      current="same" if anime == audio else anime, on_select=set_("anime", "Anime audio"),
                      key="anime_audio")
        ctx.switch_row(g, "Require the first audio language", "off: it's only preferred, other releases still count",
                       hint="On: a release without your first audio language is never grabbed",
                       active=doc.get("required", True),
                       on_toggle=lambda on: ctx.change(["bromigos", "lab", "media", "language", "required",
                                                        "yes" if on else "no", "--json"],
                                                       "Required" if on else "Preferred only"), key="required")
        ctx.combo_row(g, "Subtitles", "what Bazarr fetches for new and requested titles",
                      hint="Sets Bazarr's default language profile (made when it's missing)",
                      options=_opts(SUBS, subs), current=subs, on_select=set_("subtitles", "Subtitles"),
                      key="subtitles")
    ctx.json(["bromigos", "lab", "media", "language", "--json"], shown)


def _not_installed(ctx, page):
    """Without bromigos-homelab: what the page will show, each part a row the search can land on
    (greyed, saying why), the way to install and connect, and where AI runs (which works now)."""
    need = "needs bromigos-homelab (Connect your lab, below)"
    g = ctx.placeholder(page, "Lab", "The homelab console comes with bromigos-homelab; once it's installed, "
                                     "`bromigos lab connect` finds your services.",
                        hint="bromigos lab: status, models, jobs and the doctor for your homelab")
    for key, title, what in (("status", "The lab's status", "one line per part of your lab: nodes, GPUs, services, "
                                                            "apps, storage, alerts"),
                             ("models", "GPUs and models", "what each GPU holds and each server has loaded"),
                             ("jobs", "Recent jobs", "images, holograms and voice lines made on your lab's GPUs"),
                             ("doctor", "Doctor", "checks with fixes in plain words")):
        r = ctx.row(g, title, f"{what}: {need}", key=key,
                    hint=f"{title}: {what}. It appears here once bromigos-homelab is installed and your lab is "
                         "connected.")
        r.set_sensitive(False)
    gc = ctx.group(page, "Connect your lab", "Install the homelab integrations, then let them find your services "
                                             "(Prometheus, Kubernetes, ComfyUI, the voice service, …).",
                   hint="bromigos-homelab, then bromigos setup homelab: it probes the hosts you name and asks "
                        "before writing homelab.toml")
    ctx.row(gc, "Connect your lab", "sudo pacman -S bromigos-homelab, then bromigos setup homelab (in a terminal)",
            key="connect", hint="Opens a terminal: pacman asks for your password, then setup asks for your hosts",
            buttons=[("Install and connect…",
                      lambda: ctx.terminal(["sh", "-c", "sudo pacman -S --needed bromigos-homelab && "
                                                        "bromigos setup homelab"]),
                      "Installs bromigos-homelab and runs bromigos setup homelab, in a terminal")])
    gt = ctx.group(page, "Where AI runs", "This machine or the cloud until a lab is connected.",
                   hint="bromigos target: per service, what it uses now", key="targets")
    ctx.row(gt, "Creation targets", "each service's order and what answers", hint="The Creation targets page",
            activate=lambda: ctx.open_page("targets"))
    return page


def _unload(ctx, src):
    def done(ok, out, err):
        ctx.toast(("Unloading: " + (out.strip() or src)) if ok else f"Couldn't unload: {err.strip() or out.strip()}")
    ctx.run(["bromigos", "lab", "models", "unload", src], done)


def _cancel(ctx, jid):
    def done(ok, out, err):
        ctx.toast(f"{jid}: cancelling" if ok else f"Couldn't cancel: {err.strip()}")
    ctx.run(["bromigos", "lab", "jobs", "cancel", jid], done)


PAGE = Page(id="lab", title="Lab", icon="network-server-symbolic applications-science-symbolic", order=10,
            group="lab", summary="your homelab: status, models, jobs, doctor",
            intro="Your homelab at a glance: what each part is doing, what its GPUs hold, the work you sent it and "
                  "what needs fixing (bromigos lab).",
            docs="lab.md",
            keywords=["homelab", "gpu", "models", "jobs", "doctor", "comfyui", "voice", "argo", "lab"],
            entries=[Entry("status", "The lab's status", ["nodes", "gpus", "services", "alerts", "storage", "argo"],
                           "The lab"),
                     Entry("audio", "Media audio language", ["dub", "dual audio", "anime", "sonarr", "radarr", "language"],
                           "Media requests"),
                     Entry("subtitles", "Media subtitles", ["bazarr", "subs", "language"], "Media requests"),
                     Entry("models", "GPUs and models", ["vram", "unload", "comfyui", "ollama", "loaded"],
                           "GPUs and models"),
                     Entry("jobs", "Recent jobs", ["queue", "image", "hologram", "voice line", "results"],
                           "Recent jobs"),
                     Entry("doctor", "Doctor", ["checks", "certificates", "dns", "disk", "backups", "drift"],
                           "Doctor"),
                     Entry("targets", "Where AI runs", ["targets", "homelab", "cloud"], "Where AI runs"),
                     Entry("connect", "Connect services", ["setup homelab", "homelab.toml"], "Where AI runs")],
            build=build)
