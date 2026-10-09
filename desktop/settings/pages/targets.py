"""Creation targets: where each kind of AI work runs (targets.toml: your homelab, this
machine, the cloud), what each service uses now and why the others don't answer
(docs/settings.md, "Creation targets"; docs/targets.md).

Everything goes through `bromigos target … --json`: a service's choice puts that place
first in its own order (`--only SERVICE`), the cloud only after a question (it spends
credits), Undo puts its order back. VECTOR's terminal can read this but never switch it:
it's the user's to change, here or with `bromigos target`."""
import os

from bromigos_settings import Entry, Page

TARGET = ["bromigos", "target"]
NAMES = {"image.generate": "Images", "image.edit": "Image edits", "image.cutout": "Cutouts",
         "image.upscale": "Upscales", "video.loop": "Video loops", "video.upscale": "Clip upscales",
         "model3d.generate": "3D models", "voice.tts": "VECTOR's voice",
         "voice.stt": "VECTOR's hearing", "llm": "VECTOR's brain"}
WHAT = {"image.generate": "worlds' paintings, concepts", "image.edit": "masked edits of a painting",
        "image.cutout": "cutting a figure from its background", "image.upscale": "a sharper, larger picture",
        "video.loop": "the worlds' living loops", "video.upscale": "a sharper, larger clip",
        "model3d.generate": "holograms from a picture", "voice.tts": "his speech", "voice.stt": "what he hears you say",
        "llm": "the model he thinks with"}
PLACES = [("homelab", "Homelab"), ("local", "This machine"), ("cloud", "The cloud")]
PLACE = {"homelab": "homelab", "local": "this machine", "cloud": "the cloud"}


def _targets_toml():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "bromigos/targets.toml")


class TargetsPage:
    def __init__(self, ctx):
        self.ctx = ctx
        self.doc = None
        self.page = ctx.page()
        self.page.set_reset(self.reset, what="Every service follows the one order again (homelab, this machine, "
                                             "the cloud), as bromigOS ships it. Your targets.toml keeps its other keys.")
        ctx_ = ctx
        g = ctx_.group(self.page, "Where AI runs", "Each service tries its places in order and uses the first that "
                                                   "answers. The cloud spends credits and is only used where it's "
                                                   "listed.", key="services")
        self.svc_group = g
        self.rows = [ctx_.loading(g, "Asking each service (a few seconds)…")]
        tools = ctx_.group(self.page, "Check and change")
        ctx_.row(tools, "Probe now", "Asks every place of every service again (a ComfyUI: its workflow's models, "
                                     "its VRAM)", key="probe", hint="Runs bromigos target check",
                 buttons=[("Probe", self.probe, "Asks every service's places again, now")],
                 advanced={"runs": "bromigos target check --json"})
        self.order_row = ctx_.row(tools, "The order", "", key="order",
                                  hint="The order every service follows unless it has its own",
                                  advanced={"file": _targets_toml(), "key": "order",
                                            "runs": "bromigos target order homelab local cloud"})
        ctx_.row(tools, "The questions again", "Homelab, this machine or the cloud, for everything "
                                               "(bromigos setup targets)", key="setup",
                 hint="Opens the targets setup in a terminal",
                 buttons=[("Change…", lambda: ctx.terminal(["bromigos", "setup", "targets"]),
                           "bromigos setup targets, in a terminal")], advanced={"runs": "bromigos setup targets"})
        ctx_.row(tools, "targets.toml", "~/.config/bromigos/targets.toml", key="file",
                 hint="Opens the file in your editor",
                 buttons=[("Open", lambda: ctx.open_file(_targets_toml()), "Opens ~/.config/bromigos/targets.toml")],
                 advanced={"file": _targets_toml()})
        lab = ctx_.group(self.page, "Your lab's models")
        ctx_.row(lab, "The models your lab runs", "What fits its GPUs, what's loaded, the planner: Lab",
                 hint="Opens the Lab page (bromigos lab)", key="lab", activate=lambda: ctx.open_page("lab"))
        ctx.json(TARGET + ["--json"], self._got)

    # ------------------------------------------------------------------ state
    def _got(self, doc, err):
        ctx = self.ctx
        ctx.clear_group(self.svc_group, self.rows)
        if not doc or not doc.get("services"):
            self.rows.append(ctx.failed(self.svc_group, TARGET + ["--json"], (doc or {}).get("error") or err))
            return
        self.doc = doc
        self.order_row.set_subtitle(" → ".join(PLACE.get(t, t) for t in doc.get("order") or []) +
                                    ("  (yours, in targets.toml)" if doc.get("yours") else "  (bromigOS's)"))
        for s in doc["services"]:
            svc = s["service"]
            uses = s.get("uses")
            lines = [f"uses {PLACE.get(uses['target'], uses['target'])}: {uses['engine']}" if uses
                     else "nothing answers now"]
            for e in s.get("entries") or []:
                if not e.get("ok") and (not uses or e["target"] != uses["target"]):
                    lines.append(f"{PLACE.get(e['target'], e['target'])}: {e.get('detail')}")
            first = (s.get("order") or ["homelab"])[0]
            cell = []
            row = ctx.combo_row(
                self.svc_group, NAMES.get(svc, svc), "\n".join(lines), options=PLACES, current=first,
                key=svc, on_select=lambda t, s=s, cell=cell: self._choose(s, t, cell[0]),
                hint=f"{NAMES.get(svc, svc)} ({WHAT.get(svc, svc)}): which place it tries first. "
                     + (" Its own order: " if s.get("own_order") else " The common order: ")
                     + " → ".join(s.get("order") or []),
                advanced={"file": _targets_toml(), "key": f'[service."{svc}"] order',
                          "runs": f"bromigos target homelab|local|cloud --only {svc}"})
            row.set_use_markup(True)          # a ComboRow's text isn't markup by default; ctx escaped it
            cell.append(row)
            if not uses:
                row.add_css_class("bromigos-warn")
            row.set_subtitle_lines(4)
            self.rows.append(row)

    # ------------------------------------------------------------------ changes
    def _choose(self, s, target, row):
        if (s.get("order") or [None])[0] == target:
            return
        undo = (TARGET + ["order", *s["order"], "--only", s["service"], "--json"] if s.get("own_order")
                else TARGET + ["reset", "--only", s["service"], "--json"])
        name = NAMES.get(s["service"], s["service"])

        def go():
            self.ctx.change(TARGET + [target, "--only", s["service"], "--json"],
                            f"{name}: {PLACE[target]} first", undo=undo, done=lambda d: self._got(d, ""),
                            failed=lambda *_: self.ctx.json(TARGET + ["--json"], self._got))
        if target == "cloud":
            self.ctx.confirm(f"{name}: the cloud first?",
                             "The cloud spends credits (nolgia's, or a hosted model's). Your homelab and this "
                             "machine come after it for this service.", "Use the cloud", go,
                             no="Keep it as it is")
            row.set_quiet(s["order"][0])        # the order in force until the answer
        else:
            go()

    def probe(self):
        self.ctx.clear_group(self.svc_group, self.rows)
        self.rows.append(self.ctx.loading(self.svc_group, "Probing every place of every service…"))
        self.ctx.json(TARGET + ["check", "--json"], self._got)

    def reset(self):
        self.ctx.change(TARGET + ["reset", "--json"], "Every service follows the common order again",
                        done=lambda d: self._got(d, ""))
        return None


def build(ctx):
    p = TargetsPage(ctx)
    p.page._targets = p
    return p.page


PAGE = Page(
    id="targets", title="Creation targets", group="vector", order=50, build=build, docs="settings.md#creation-targets",
    icon="network-server-symbolic", summary="where AI runs, per service",
    intro="Where each kind of AI work runs: your homelab, this machine, or the cloud, which spends credits. What "
          "each service uses now, and why the others don't answer.",
    keywords=["ai", "homelab", "local", "cloud", "targets", "credits", "nolgia", "comfyui"],
    entries=[Entry(svc, NAMES[svc], [WHAT[svc], svc, "where it runs"], "Where AI runs") for svc in NAMES] + [
        Entry("probe", "Probe the targets", ["check", "test", "answers"], "Check and change"),
        Entry("order", "The common order", ["homelab first", "local first", "cloud first"], "Check and change"),
        Entry("setup", "Set up where AI runs", ["setup targets"], "Check and change"),
        Entry("lab", "The models your lab runs", ["lab models", "planner", "gpu"], "Your lab's models"),
    ])
